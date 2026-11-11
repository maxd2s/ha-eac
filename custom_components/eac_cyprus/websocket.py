"""Authenticated, entity-permission-scoped access to cached meter profiles."""

import probatio as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .statistics import grid_statistic_id


def _readable_meters(hass, connection):
    registry = er.async_get(hass)
    for coordinator in hass.data.get(DOMAIN, {}).values():
        for point in coordinator.data.points.values():
            for meter in point.meters.values():
                entity = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{meter.key}_profile_coverage"
                )
                if entity and connection.user.permissions.check_entity(
                    entity, POLICY_READ
                ):
                    yield entity, meter, coordinator


@websocket_api.websocket_command({vol.Required("type"): "eac_cyprus/profile_meters"})
@callback
def ws_meters(hass, connection, msg):
    connection.send_result(
        msg["id"],
        [
            {
                "entity_id": entity,
                "name": f"{meter.meter.manufacturer or 'Meter'} {meter.serial}",
                "has_import": (meter.insights or {}).get("import_intervals", 0) > 0,
                "has_export": (meter.insights or {}).get("export_intervals", 0) > 0,
            }
            for entity, meter, _ in _readable_meters(hass, connection)
        ],
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "eac_cyprus/profile", vol.Required("entity_id"): str}
)
@callback
def ws_profile(hass, connection, msg):
    for entity, meter, coordinator in _readable_meters(hass, connection):
        if entity != msg["entity_id"]:
            continue
        connection.send_result(
            msg["id"],
            {
                **(meter.insights or {}),
                "statistic_ids": {
                    direction: grid_statistic_id(
                        meter.service_point.id, meter.serial, direction
                    )
                    for direction in ("import", "export", "net")
                },
                "tariff": meter.tariff,
                "phases": meter.service_point.phases,
                "load_entitlement": meter.service_point.load_entitlement,
                "load_entitlement_unit": meter.service_point.load_entitlement_uom,
                "model": meter.meter.model,
                "fetched_at": meter.received_at.isoformat()
                if meter.received_at
                else None,
                "available": coordinator.last_update_success,
            },
        )
        return
    # Same response for a nonexistent entity or one this user cannot read.
    connection.send_error(msg["id"], "not_found", "Meter profile unavailable")


@callback
def async_register_profile_api(hass):
    websocket_api.async_register_command(hass, ws_meters)
    websocket_api.async_register_command(hass, ws_profile)
