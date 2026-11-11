"""EAC Cyprus integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_admin_service

from .client import EacClient
from .const import CONF_BASE_URL, CONF_EMAIL, CONF_PASSWORD, DEFAULT_BASE_URL, DOMAIN
from .coordinator import EacCoordinator
from .history import async_import_full_history

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

SERVICE_IMPORT_HISTORY = "import_full_history"
_OFFERED_FLAG = "history_import_offered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an EAC Cyprus config entry."""
    session = async_get_clientsession(hass)
    client = EacClient(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        session=session,
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
    )

    coordinator = EacCoordinator(hass, client, entry)
    coordinator.connection_data = tuple(
        entry.data.get(key) for key in (CONF_EMAIL, CONF_PASSWORD, CONF_BASE_URL)
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_offer_history_import(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the one-time full-history import service (once per HA)."""
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORY):
        return

    async def _handle_import(call: ServiceCall) -> ServiceResponse:
        details: list[dict] = []
        for coordinator in list(hass.data.get(DOMAIN, {}).values()):
            if coordinator.history_import_running:
                raise HomeAssistantError("An EAC history import is already running")
            coordinator.history_import_running = True
            try:
                async with coordinator.operation_lock, asyncio.timeout(600):
                    details.extend(
                        await async_import_full_history(hass, coordinator.client)
                    )
            except Exception:
                raise HomeAssistantError(
                    "EAC history import interrupted; retry later"
                ) from None
            finally:
                coordinator.history_import_running = False
            await coordinator.async_request_refresh()
        readings = sum(d["readings"] for d in details)
        persistent_notification.async_create(
            hass,
            f"Imported full history: {len(details)} channel(s), {readings} readings.",
            title="EAC Cyprus: full history imported",
            notification_id=f"{DOMAIN}_history_done",
        )
        _LOGGER.info(
            "Imported full history: %d channel(s), %d readings", len(details), readings
        )
        return {
            "channels_imported": len(details),
            "readings_imported": readings,
            "details": details,
        }

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        _handle_import,
        supports_response=SupportsResponse.OPTIONAL,
    )


@callback
def _async_offer_history_import(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """On first setup, nudge the user to run the full-history import once."""
    if entry.data.get(_OFFERED_FLAG):
        return
    persistent_notification.async_create(
        hass,
        "To load your complete meter history into the Energy Dashboard, run the "
        "**EAC: Import full history** action once (Developer Tools -> Actions -> "
        "`eac_cyprus.import_full_history`). Regular polling only keeps a rolling "
        "window; this backfills everything the portal has, for every meter.",
        title="EAC Cyprus: import full history",
        notification_id=f"{DOMAIN}_{entry.entry_id}_history",
    )
    # Persist so the nudge is shown only once, before the update listener attaches.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, _OFFERED_FLAG: True}
    )


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changes from the options flow without reloading the entry."""
    coordinator: EacCoordinator = hass.data[DOMAIN][entry.entry_id]
    connection_data = tuple(
        entry.data.get(key) for key in (CONF_EMAIL, CONF_PASSWORD, CONF_BASE_URL)
    )
    if connection_data != coordinator.connection_data:
        hass.config_entries.async_schedule_reload(entry.entry_id)
    else:
        coordinator.apply_options()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_IMPORT_HISTORY)
    return unloaded
