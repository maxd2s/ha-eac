"""One-time deep backfill of the full available meter history.

The regular coordinator only imports a rolling window (``history_days``). This
pulls the *entire* available series for every cumulative kWh channel of every
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
from .statistics import import_cumulative_history
from .time import as_utc as _as_utc

_LOGGER = logging.getLogger(__name__)

# Lower bound if a meter somehow reports no install date.
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
            start = _as_utc(cfg.install_date) or (now - _MAX_LOOKBACK)
            end = _as_utc(cfg.removal_date) or now
            for ch in cfg.channels:
                if ch.uom.upper() != "KWH" or ch.interval:
                    continue
                cursor = start
                imported = 0
                last_dt = None
                while cursor < end:
                    chunk_end = min(cursor + timedelta(days=14), end)
                    try:
                        crs = await client.get_readings(
                            sp.id, cursor, chunk_end, mc_id=ch.id
                        )
                    except EacRateLimitError:
                        raise
                    except EacApiError:
                        # Do not claim a complete import after silently skipping a window.
                        raise RuntimeError(
                            "EAC history import interrupted; rerun to resume"
                        ) from None
                    matching = next((cr for cr in crs if cr.channel_id == ch.id), None)
                    if matching is not None:
                        readings = tuple(
                            sorted(
                                (
                                    r
                                    for r in matching.readings
                                    if (last_dt is None or _as_utc(r.dt) > last_dt)
                                    and cursor <= _as_utc(r.dt) <= chunk_end
                                ),
                                key=lambda r: _as_utc(r.dt),
                            )
                        )
                        if readings:
                            import_cumulative_history(
                                hass,
                                sp.id,
                                ch.id,
                                f"{serial} {channel_label(ch.type)}",
                                readings,
                            )
                            imported += len(readings)
                            last_dt = _as_utc(readings[-1].dt)
                    cursor = chunk_end
                if not imported:
                    continue

                results.append(
                    {
                        "meter": serial,
                        "channel": ch.type,
                        "readings": imported,
                        "from": start.date().isoformat(),
                        "to": end.date().isoformat(),
                    }
                )
                _LOGGER.debug("Queued %d historical observations", imported)

    _LOGGER.info("Full history import complete: %d channel(s)", len(results))
    return results
