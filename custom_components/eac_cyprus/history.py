"""One-time deep backfill of the full available meter history.

The regular coordinator only imports a rolling window (``history_days``). This
pulls up to ten years of the available series for every cumulative kWh channel of every
meter -- active and retired -- from the portal and writes it as external
statistics, so the Energy Dashboard graph reaches back to each meter's install
date instead of only a couple of weeks. Retired meters (already swapped out)
get their full history too, so their device is not an empty stub.

Exposed as the ``eac_cyprus.import_full_history`` service and offered once via
a persistent notification on first setup. Idempotent -- safe to re-run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from eac_dso_portal import EacApiError
from eac_dso_portal.exceptions import EacRateLimitError
from homeassistant.core import HomeAssistant

from .client import EacClient
from .const import channel_label
from .statistics import (
    GRID_CHANNEL_DIRECTIONS,
    import_cumulative_history,
    import_grid_net_history,
)
from .time import as_utc as _as_utc

_LOGGER = logging.getLogger(__name__)

# Hard history bound, including when the portal supplies an implausible date.
_MAX_LOOKBACK = timedelta(days=3650)


def _meter_serial(cfg) -> str:
    return cfg.serial_number or (
        cfg.install_date.date().isoformat() if cfg.install_date else "unknown"
    )


async def async_import_full_history(
    hass: HomeAssistant, client: EacClient
) -> list[dict[str, Any]]:
    """Backfill full history for all meters. Returns a per-channel summary."""
    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    for sp in await client.list_service_points():
        if not (sp.active and sp.device_exists):
            continue
        try:
            configs = await client.get_meter_configs(sp.id)
        except EacRateLimitError:
            raise
        except EacApiError:
            raise RuntimeError("EAC history import interrupted; retry later") from None

        for cfg in configs:
            serial = _meter_serial(cfg)
            start = max(
                _as_utc(cfg.install_date) or (now - _MAX_LOOKBACK), now - _MAX_LOOKBACK
            )
            end = min(_as_utc(cfg.removal_date) or now, now)
            channels = [
                ch for ch in cfg.channels if ch.uom.upper() == "KWH" and not ch.interval
            ]
            counts = {ch.id: 0 for ch in channels}
            last_dates: dict = {}
            cursor = start
            # Process every channel within a window before advancing. Net pairs
            # retain only this window instead of the entire meter lifetime.
            while cursor < end and channels:
                chunk_end = min(cursor + timedelta(days=14), end)
                grid_readings: dict[str, list] = {"import": [], "export": []}
                for ch in channels:
                    try:
                        crs = await client.get_readings(
                            sp.id, cursor, chunk_end, mc_id=ch.id
                        )
                    except EacRateLimitError:
                        raise
                    except EacApiError:
                        raise RuntimeError(
                            "EAC history import interrupted; rerun to retry"
                        ) from None
                    matching = next((cr for cr in crs if cr.channel_id == ch.id), None)
                    if matching is None:
                        continue
                    window = tuple(
                        sorted(
                            (
                                r
                                for r in matching.readings
                                if cursor <= _as_utc(r.dt) <= chunk_end
                            ),
                            key=lambda r: _as_utc(r.dt),
                        )
                    )
                    # Keep boundary observations for net pairing; idempotent
                    # recorder writes replace them. Deduplicate channel counts.
                    if direction := GRID_CHANNEL_DIRECTIONS.get(ch.type):
                        grid_readings[direction].extend(window)
                    last_dt = last_dates.get(ch.id)
                    readings = tuple(
                        r for r in window if last_dt is None or _as_utc(r.dt) > last_dt
                    )
                    if readings:
                        import_cumulative_history(
                            hass,
                            sp.id,
                            ch.id,
                            f"{serial} {channel_label(ch.type)}",
                            readings,
                            meter_serial=cfg.serial_number,
                            channel_type=ch.type,
                        )
                        counts[ch.id] += len(readings)
                        last_dates[ch.id] = _as_utc(readings[-1].dt)
                import_grid_net_history(
                    hass,
                    sp.id,
                    cfg.serial_number,
                    tuple(grid_readings["import"]),
                    tuple(grid_readings["export"]),
                )
                cursor = chunk_end
            for ch in channels:
                if counts[ch.id]:
                    results.append(
                        {
                            "meter": serial,
                            "channel": ch.type,
                            "readings": counts[ch.id],
                            "from": start.date().isoformat(),
                            "to": end.date().isoformat(),
                        }
                    )
                    _LOGGER.debug("Queued %d historical observations", counts[ch.id])

    _LOGGER.info("Full history import complete: %d channel(s)", len(results))
    return results
