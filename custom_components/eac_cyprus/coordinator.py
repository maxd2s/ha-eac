"""DataUpdateCoordinator that polls the EAC DSO portal.

Data model is meter-centric: a service point can carry several meters over its
lifetime (the DSO swaps hardware), and we surface each as its own HA device so
a retired meter keeps its history and final reading instead of vanishing. Every
refresh fetches fresh readings for the *active* meter; retired meters never
change, so their final snapshot is fetched once and cached.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp
from eac_dso_portal import (
    EacApiError,
    EacAuthError,
    MeasurementChannel,
    MeterConfig,
    Reading,
    ServicePoint,
    UserDetails,
)
from eac_dso_portal.exceptions import EacRateLimitError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .analytics import (
    CONF_NIGHT_END,
    CONF_NIGHT_START,
    CONF_PROFILE_DAYS,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_PROFILE_DAYS,
    merge_profile,
    profile_insights,
    window_start,
)
from .client import EacClient
from .const import (
    CONF_HISTORY_DAYS,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    channel_label,
)
from .provisional import INTERVAL_DIRECTIONS, today_profile
from .statistics import (
    GRID_CHANNEL_DIRECTIONS,
    import_cumulative_history,
    import_grid_net_history,
)
from .time import as_utc as _as_utc

_LOGGER = logging.getLogger(__name__)


def meter_key(sp_id: str, meter: MeterConfig) -> str:
    """Stable per-meter identifier: service point + serial (or install date)."""
    serial = meter.serial_number or (
        meter.install_date.date().isoformat() if meter.install_date else "unknown"
    )
    return f"{sp_id}_{serial}"


@dataclass(frozen=True, slots=True)
class ChannelState:
    """Current state of a single measurement channel."""

    channel: MeasurementChannel
    latest: Reading | None  # most recent reading we have (cumulative or interval)


@dataclass(frozen=True, slots=True)
class MeterState:
    """One meter on a service point, active or retired, with its channels."""

    service_point: ServicePoint
    meter: MeterConfig
    active: bool  # removal_date is None
    channels: dict[str, ChannelState]  # keyed by channel id
    measured_at: datetime | None  # provider dt of the newest reading (tz-aware UTC)
    received_at: datetime | None  # when this snapshot was fetched (tz-aware UTC)

    today: dict | None = None
    insights: dict | None = None
    tariff: dict | None = None

    @property
    def key(self) -> str:
        return meter_key(self.service_point.id, self.meter)

    @property
    def serial(self) -> str:
        return self.meter.serial_number or self.key.rsplit("_", 1)[-1]


@dataclass(frozen=True, slots=True)
class ServicePointState:
    """Per-service-point snapshot built every refresh."""

    service_point: ServicePoint
    meters: dict[str, MeterState]  # keyed by meter_key()


@dataclass(frozen=True, slots=True)
class EacData:
    """What the coordinator hands to entities."""

    user: UserDetails
    points: dict[str, ServicePointState]  # keyed by service-point id
    last_success_time: datetime  # tz-aware UTC; surfaced via a diagnostic sensor


class EacCoordinator(DataUpdateCoordinator[EacData]):
    """Fetch service points, meters, and per-channel readings on a schedule."""

    def __init__(
        self, hass: HomeAssistant, client: EacClient, entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=_interval_from_options(entry),
        )
        self.operation_lock = asyncio.Lock()
        self.history_import_running = False
        self._client = client
        self._entry = entry
        # Retired meters never change; cache their final snapshot by meter_key.
        self._retired_cache: dict[str, MeterState] = {}
        self._profile_store = Store(hass, 1, f"{DOMAIN}_profiles_{entry.entry_id}")
        self._profiles: dict = {}
        self._profiles_loaded = False

    @property
    def client(self) -> EacClient:
        """The portal client, for one-off operations like full-history import."""
        return self._client

    def apply_options(self) -> None:
        """Re-read options after the options flow. Only cadence needs pushing."""
        self.update_interval = _interval_from_options(self._entry)

    async def _async_update_data(self) -> EacData:
        try:
            async with asyncio.timeout(180), self.operation_lock:
                return await self._fetch_data()
        except EacAuthError:
            raise ConfigEntryAuthFailed("EAC login needs to be renewed") from None
        except (
            EacApiError,
            aiohttp.ClientError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
            RecursionError,
        ):
            raise UpdateFailed(
                "EAC portal update failed; retrying on the next refresh"
            ) from None

    async def _fetch_data(self) -> EacData:
        if not self._profiles_loaded:
            saved = await self._profile_store.async_load()
            self._profiles = saved if isinstance(saved, dict) else {}
            self._profiles_loaded = True
        user = await self._client.get_user_details()
        sps = await self._client.list_service_points()

        received_at = datetime.now(UTC)
        history_days = self._entry.options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)

        points: dict[str, ServicePointState] = {}
        for sp in sps:
            meters: dict[str, MeterState] = {}
            if sp.active and sp.device_exists:
                try:
                    configs = await self._client.get_meter_configs(sp.id)
                except EacRateLimitError:
                    raise
                except EacApiError as err:
                    _LOGGER.warning(
                        "Meter configuration fetch failed (HTTP %s)", err.status
                    )
                    configs = []

                for cfg in configs:
                    if cfg.removal_date is None:
                        end = received_at
                        start = end - timedelta(days=history_days)
                        ms = await self._fetch_meter(sp, cfg, start, end, received_at)
                    else:
                        ms = await self._retired_meter(sp, cfg, received_at)
                    meters[ms.key] = ms

            points[sp.id] = ServicePointState(service_point=sp, meters=meters)

        current_keys = {key for point in points.values() for key in point.meters}
        self._retired_cache = {
            key: value
            for key, value in self._retired_cache.items()
            if key in current_keys
        }
        self._profiles = {k: v for k, v in self._profiles.items() if k in current_keys}
        await self._profile_store.async_save(self._profiles)
        return EacData(user=user, points=points, last_success_time=datetime.now(UTC))

    async def _retired_meter(
        self, sp: ServicePoint, cfg: MeterConfig, received_at: datetime
    ) -> MeterState:
        """Final snapshot of a retired meter, fetched once and cached."""
        key = meter_key(sp.id, cfg)
        if key not in self._retired_cache:
            end = _as_utc(cfg.removal_date) or received_at
            start = end - timedelta(days=14)
            snapshot = await self._fetch_meter(sp, cfg, start, end, received_at)
            if snapshot.channels:
                self._retired_cache[key] = snapshot
            return snapshot
        return self._retired_cache[key]

    async def _fetch_meter(
        self,
        sp: ServicePoint,
        cfg: MeterConfig,
        start: datetime,
        end: datetime,
        received_at: datetime,
    ) -> MeterState:
        """Fetch every channel's latest reading for one meter."""
        channels: dict[str, ChannelState] = {}
        grid_readings: dict[str, tuple[Reading, ...]] = {}
        interval_readings: dict[str, tuple[Reading, ...]] = {}
        measured_at: datetime | None = None
        key = meter_key(sp.id, cfg)
        cache = self._profiles.setdefault(key, {})
        days = self._entry.options.get(CONF_PROFILE_DAYS, DEFAULT_PROFILE_DAYS)
        night_start = self._entry.options.get(CONF_NIGHT_START, DEFAULT_NIGHT_START)
        night_end = self._entry.options.get(CONF_NIGHT_END, DEFAULT_NIGHT_END)
        bounds = {
            str(ch["id"]): (
                _as_utc(datetime.fromisoformat(conf["startDate"]))
                if conf.get("startDate")
                else None,
                _as_utc(datetime.fromisoformat(conf["endDate"]))
                if conf.get("endDate")
                else None,
            )
            for conf in cfg.raw.get("configurationsList", [])
            for ch in conf.get("mcList", [])
        }
        for ch in cfg.channels:
            direction = (
                INTERVAL_DIRECTIONS.get(ch.type)
                if ch.interval and ch.uom.upper() == "KWH"
                else None
            )
            request_start, request_end = start, end
            if direction and cfg.removal_date is None:
                last = cache.get("fetched", {}).get(ch.id)
                previous = (
                    datetime.fromtimestamp(last, UTC)
                    if isinstance(last, (int, float))
                    else window_start(received_at, days)
                )
                # A larger configured window triggers a one-time extra backfill.
                if cache.get("seed_days", {}).get(ch.id, 0) < days:
                    previous = window_start(received_at, days)
                request_start = max(
                    window_start(received_at, days), min(start, previous)
                )
            bound_start, bound_end = bounds.get(ch.id, (None, None))
            request_start = (
                max(request_start, bound_start) if bound_start else request_start
            )
            request_end = min(request_end, bound_end) if bound_end else request_end
            if request_start >= request_end:
                continue
            try:
                per_channel = await self._client.get_readings(
                    sp.id, request_start, request_end, mc_id=ch.id
                )
            except EacRateLimitError:
                raise
            except EacApiError as err:
                _LOGGER.debug("Channel readings unavailable (HTTP %s)", err.status)
                continue
            matching = next((cr for cr in per_channel if cr.channel_id == ch.id), None)
            if direction and cfg.removal_date is None and matching is not None:
                merge_profile(
                    cache,
                    direction,
                    matching.readings,
                    request_start,
                    request_end,
                    received_at,
                    days,
                )
                cache.setdefault("fetched", {})[ch.id] = received_at.timestamp()
                cache.setdefault("seed_days", {})[ch.id] = days
            if matching is None or not matching.readings:
                continue
            if direction := GRID_CHANNEL_DIRECTIONS.get(ch.type):
                grid_readings[direction] = matching.readings
            if (
                ch.interval
                and ch.uom.upper() == "KWH"
                and (direction := INTERVAL_DIRECTIONS.get(ch.type))
            ):
                interval_readings[direction] = matching.readings
            latest = max(matching.readings, key=lambda r: _as_utc(r.dt))
            channels[ch.id] = ChannelState(channel=ch, latest=latest)
            dt = _as_utc(latest.dt)
            if dt is not None and (measured_at is None or dt > measured_at):
                measured_at = dt

            # Backfill external statistics (the "what actually happened" half)
            # for cumulative kWh channels, named from the meter serial.
            if ch.uom.upper() == "KWH" and not ch.interval:
                serial = cfg.serial_number or (
                    cfg.install_date.date().isoformat()
                    if cfg.install_date
                    else "unknown"
                )
                import_cumulative_history(
                    self.hass,
                    sp.id,
                    ch.id,
                    f"{serial} {channel_label(ch.type)}",
                    matching.readings,
                    meter_serial=cfg.serial_number,
                    channel_type=ch.type,
                )

        import_grid_net_history(
            self.hass,
            sp.id,
            cfg.serial_number,
            grid_readings.get("import", ()),
            grid_readings.get("export", ()),
        )
        insights = None
        if cfg.removal_date is None:
            for direction in ("import", "export"):
                merge_profile(cache, direction, (), start, end, received_at, days)
            insights = profile_insights(
                cache, received_at, days, night_start, night_end
            )
            if (
                cfg.serial_number
                and received_at.timestamp() - cache.get("tariff_attempt", 0) >= 86400
            ):
                cache["tariff_attempt"] = received_at.timestamp()
                try:
                    code = await self._client.get_tariff_code(
                        sp.id, cfg.serial_number, received_at
                    )
                except (
                    EacApiError,
                    EacAuthError,
                    aiohttp.ClientError,
                    TimeoutError,
                    ValueError,
                    TypeError,
                ):
                    code = None
                if isinstance(code, str) and code:
                    cache["tariff"] = {
                        "code": code,
                        "retrieved_at": received_at.isoformat(),
                        "source": "DSO consumption report",
                    }
        return MeterState(
            service_point=sp,
            meter=cfg,
            active=cfg.removal_date is None,
            channels=channels,
            measured_at=measured_at,
            received_at=received_at,
            insights=insights,
            tariff=cache.get("tariff"),
            today=today_profile(
                interval_readings.get("import", ()),
                interval_readings.get("export", ()),
                received_at,
            )
            if cfg.removal_date is None
            else None,
        )


def _interval_from_options(entry: ConfigEntry) -> timedelta:
    minutes = entry.options.get(
        CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
    )
    return timedelta(minutes=int(minutes))
