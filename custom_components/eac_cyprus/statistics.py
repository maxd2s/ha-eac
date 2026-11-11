"""Long-term-statistics backfill for cumulative kWh channels.

The EAC portal publishes delayed readings with channel-specific cadence. Home
Assistant's `state_class=total_increasing` contract assumes the live state
moves more or less in real time, and the recorder writes its own auto-stats
based on that assumption. Pushing backfilled hourly rows through
`async_import_statistics` against the same `entity_id` collides with that
auto-record (see issue #1) and produces a `sum` cliff at the boundary
between the API's data window and the HA-restart point.

Solution: use `async_add_external_statistics` with our own
`eac_cyprus:<sp>_<channel>` statistic IDs. External statistics are an
independent source as far as the recorder is concerned, with no auto-record
behind them, so the historical view stays consistent regardless of when
HA was started.

Energy Dashboard then sees `EAC ... <channel>` as separate entries in the
'Add consumption' dropdown. The sensor entities themselves keep being
'latest known value' displays and are not the right thing to put into
Energy Dashboard for a delayed-data provider.

v1 scope (this module): cumulative kWh channels only. Interval channels
(30-min load profile) have no cumulative reading on the API side, so the
running sum has to be synthesised. Tracked separately.
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta

from eac_dso_portal import Reading
from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import EnergyConverter

from .const import DOMAIN
from .time import as_utc

_LOGGER = logging.getLogger(__name__)


def external_statistic_id(sp_id: str, channel_id: str) -> str:
    """Stable identifier for the channel's external statistic.

    Stays the same across upgrades and restarts so the recorder keeps
    appending to the same series instead of orphaning it on every release.
    """
    return f"{DOMAIN}:{sp_id}_{channel_id}"


GRID_CHANNEL_DIRECTIONS = {
    "S-KWH-24H": "import",
    "S-KWH-NET-IMP-MMTR": "import",
    "S-KWH-EXP": "export",
    "S-KWH-NET-EXP-MMTR": "export",
}


def grid_statistic_id(sp_id: str, serial: str, direction: str) -> str:
    """Keep a physical meter's register history across portal channel changes."""
    return f"{DOMAIN}:{sp_id}_meter_{slugify(serial)}_{direction}"


def grid_statistics_rows(readings: tuple[Reading, ...]) -> list[StatisticData]:
    """Assign an instantaneous register reading to the hour it closes.

    A midnight register closes the preceding day; assigning it to midnight's
    starting hour would shift daily/monthly consumption forward. Subtract in
    UTC so daylight-saving transitions retain distinct real hours. No values
    are interpolated across missing readings.
    """
    rows: dict = {}
    for reading in sorted(readings, key=lambda item: as_utc(item.dt)):
        value = reading.reading
        if value is None or not math.isfinite(value) or value < 0:
            continue
        start = (as_utc(reading.dt) - timedelta(microseconds=1)).replace(
            minute=0, second=0, microsecond=0
        )
        rows[start] = {"start": start, "sum": value}
    return list(rows.values())


def import_grid_net_history(
    hass: HomeAssistant,
    sp_id: str,
    serial: str | None,
    imports: tuple[Reading, ...],
    exports: tuple[Reading, ...],
) -> None:
    """Net energy uses paired register timestamps, never missing-as-zero."""
    if not serial:
        return
    # Match exact measurement times before bucketing to hours.
    incoming = {
        as_utc(r.dt): r
        for r in imports
        if r.reading is not None and math.isfinite(r.reading) and r.reading >= 0
    }
    outgoing = {
        as_utc(r.dt): r
        for r in exports
        if r.reading is not None and math.isfinite(r.reading) and r.reading >= 0
    }
    rows: dict = {}
    for stamp in sorted(incoming.keys() & outgoing.keys()):
        start = (stamp - timedelta(microseconds=1)).replace(
            minute=0, second=0, microsecond=0
        )
        rows[start] = {
            "start": start,
            "sum": incoming[stamp].reading - outgoing[stamp].reading,
        }
    if rows:
        async_add_external_statistics(
            hass,
            {
                "mean_type": StatisticMeanType.NONE,
                "unit_class": EnergyConverter.UNIT_CLASS,
                "has_sum": True,
                "name": f"{serial} Net grid energy",
                "source": DOMAIN,
                "statistic_id": grid_statistic_id(sp_id, serial, "net"),
                "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
            },
            list(rows.values()),
        )


def import_cumulative_history(
    hass: HomeAssistant,
    sp_id: str,
    channel_id: str,
    display_name: str,
    readings: tuple[Reading, ...],
    *,
    meter_serial: str | None = None,
    channel_type: str | None = None,
) -> None:
    """Push readings for one cumulative kWh channel as hourly external stats.

    ``display_name`` is what the Energy Dashboard shows; we name it from the
    meter serial + channel label so it reads e.g. "1281890 Energy total (24h)"
    instead of a transliterated address. The ``statistic_id`` stays derived
    from (service point, channel) so it is stable across renames and restarts.
    """
    points = [
        r
        for r in readings
        if r.reading is not None and math.isfinite(r.reading) and r.reading >= 0
    ]
    if not points:
        _LOGGER.debug("No valid cumulative readings in %d observations", len(readings))
        return

    statistic_id = external_statistic_id(sp_id, channel_id)

    metadata: StatisticMetaData = {
        "mean_type": StatisticMeanType.NONE,
        "unit_class": EnergyConverter.UNIT_CLASS,
        "has_sum": True,
        "name": display_name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }

    # At most one row per UTC hour. Sort first so the last observation wins.
    by_hour: dict = {}
    for r in sorted(points, key=lambda reading: as_utc(reading.dt)):
        start = as_utc(r.dt).replace(minute=0, second=0, microsecond=0)
        by_hour[start] = {"start": start, "sum": r.reading}
    stats: list[StatisticData] = list(by_hour.values())

    try:
        async_add_external_statistics(hass, metadata, stats)
    except Exception:  # noqa: BLE001 - recorder exceptions are interesting
        raise RuntimeError("Could not enqueue EAC statistics") from None
    else:
        _LOGGER.debug("Queued %d statistic rows", len(stats))

    # Preserve the original per-channel series. Only the explicitly identified
    # whole-meter import/export registers feed the continuous meter series;
    # tariff registers must never be added to the total a second time.
    direction = GRID_CHANNEL_DIRECTIONS.get(channel_type)
    if meter_serial and direction:
        grid_metadata = dict(
            metadata,
            statistic_id=grid_statistic_id(sp_id, meter_serial, direction),
            name=f"{meter_serial} Grid {direction}",
        )
        async_add_external_statistics(
            hass, grid_metadata, grid_statistics_rows(readings)
        )
