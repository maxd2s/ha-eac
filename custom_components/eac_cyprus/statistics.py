"""Long-term-statistics backfill for cumulative kWh channels.

The EAC portal publishes meter readings with a lag of 2-3 days. Home
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


def import_cumulative_history(
    hass: HomeAssistant,
    sp_id: str,
    channel_id: str,
    display_name: str,
    readings: tuple[Reading, ...],
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
