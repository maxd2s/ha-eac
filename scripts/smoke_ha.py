"""Run actual HA setup/recorder/reauth APIs with a synthetic portal, offline.

Does not use the version-pinned pytest HA fixtures or access a production HA.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import homeassistant  # Initialize HTTP/schema compatibility aliases first.
import asyncio
from datetime import datetime, UTC, timedelta
import json
import tempfile
from unittest.mock import AsyncMock, patch
from importlib.metadata import version
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries
from homeassistant import loader
from homeassistant.setup import async_setup_component
from homeassistant.components.recorder import get_instance
from eac_dso_portal import (
    UserDetails,
    ServicePoint,
    MeterConfig,
    MeasurementChannel,
    ChannelReadings,
    Reading,
)


async def main():
    with tempfile.TemporaryDirectory(prefix="eac-ha-smoke-") as directory:
        (Path(directory) / "custom_components").symlink_to(
            Path(__file__).resolve().parents[1] / "custom_components",
            target_is_directory=True,
        )
        hass = HomeAssistant(directory)
        hass.config.time_zone = "Asia/Nicosia"
        hass.config_entries = ConfigEntries(hass, {})
        loader.async_setup(hass)
        from homeassistant.bootstrap import async_load_base_functionality
        from homeassistant.helpers.recorder import async_initialize_recorder

        await async_load_base_functionality(hass)
        async_initialize_recorder(hass)
        client = AsyncMock()
        client.get_tariff_code.return_value = "SYNTHETIC-5"
        client.get_user_details.return_value = UserDetails("Synthetic User", False, {})
        client.list_service_points.return_value = [
            ServicePoint("123", "Test", True, True, "S1", None, None, None, {})
        ]
        channel = MeasurementChannel("456", "S-KWH-24H", "KWH", "24H", False, 8, 0, {})
        from custom_components.eac_cyprus.time import PORTAL_TIME_ZONE
        midnight = datetime.now(PORTAL_TIME_ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        interval_stamp = midnight + timedelta(minutes=30)
        profile_channels = tuple(
            MeasurementChannel(str(500+i), f"KWH-30MIN-LP-{direction}", "KWH", "30MIN", True, 4, 3, {})
            for i, direction in enumerate(("IMP", "EXP"))
        )
        client.get_meter_configs.return_value = [
            MeterConfig(
                "S1", "Test", "Test", datetime(2026, 1, 1), None, (channel, *profile_channels), {}
            )
        ]
        client.get_readings.return_value = [
            ChannelReadings("456", (Reading(datetime(2026, 11, 1), 10, 100),)),
            ChannelReadings("500", (Reading(interval_stamp, 1.25, None),)),
            ChannelReadings("501", (Reading(interval_stamp, .5, None),)),
        ]
        try:
            assert await async_setup_component(hass, "recorder", {"recorder": {}})
            await hass.async_start()
            with (
                patch("custom_components.eac_cyprus.async_get_clientsession"),
                patch(
                    "custom_components.eac_cyprus.config_flow.async_get_clientsession"
                ),
                patch("custom_components.eac_cyprus.EacClient", return_value=client),
                patch(
                    "custom_components.eac_cyprus.config_flow.EacClient",
                    return_value=client,
                ),
            ):
                result = await hass.config_entries.flow.async_init(
                    "eac_cyprus", context={"source": "user"}
                )
                assert result["type"] == "form", result
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {"email": "synthetic@example.com", "password": "synthetic"},
                )
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                entry = result["result"]
                assert entry.state.value == "loaded", entry.state
                await get_instance(hass).async_block_till_done()
                sensors = [
                    s
                    for s in hass.states.async_all()
                    if s.entity_id.startswith("sensor.")
                ]
                assert any(s.state in ("100", "100.0") for s in sensors), sensors
                today = [s for s in sensors if "today_" in s.entity_id]
                assert len(today) == 3
                net = next(s for s in today if "today_net" in s.entity_id)
                if datetime.now(PORTAL_TIME_ZONE) >= interval_stamp:
                    assert float(net.state) == .75, net
                    assert len(net.attributes["points"]) == 1
                assert all("state_class" not in s.attributes for s in today)
                tariff = next(s for s in sensors if "tariff_code" in s.entity_id)
                assert tariff.state == "SYNTHETIC-5", tariff
                from custom_components.eac_cyprus.websocket import ws_meters, ws_profile
                from unittest.mock import MagicMock
                connection = MagicMock()
                connection.user.permissions.check_entity.return_value = True
                ws_meters(hass, connection, {"id": 1})
                available = connection.send_result.call_args.args[1]
                assert len(available) == 1
                ws_profile(hass, connection, {"id": 2, "entity_id": available[0]["entity_id"]})
                assert "points" in connection.send_result.call_args.args[1]
                # Verify the chart payload is not stored in Recorder.
                from homeassistant.components.recorder.db_schema import StateAttributes
                from sqlalchemy import select
                def recorded_attributes():
                    with get_instance(hass).get_session() as session:
                        return session.execute(select(StateAttributes.shared_attrs)).scalars().all()
                attributes = await get_instance(hass).async_add_executor_job(recorded_attributes)
                assert not any('"points"' in item for item in attributes), attributes
                # Verify a real recorder row, not just that enqueue returned.
                from homeassistant.components.recorder.statistics import get_metadata

                metadata = await get_instance(hass).async_add_executor_job(
                    __import__("functools").partial(
                        get_metadata, hass, statistic_ids={"eac_cyprus:123_456"}
                    )
                )
                assert "eac_cyprus:123_456" in metadata, metadata
                from homeassistant.components.recorder.db_schema import Statistics
                from sqlalchemy import select

                def recorded():
                    with get_instance(hass).get_session() as session:
                        return session.execute(select(Statistics.sum)).scalars().all()

                totals = await get_instance(hass).async_add_executor_job(recorded)
                assert 100.0 in totals, totals
                # A second identical refresh must not add duplicate rows.
                await hass.data["eac_cyprus"][entry.entry_id].async_refresh()
                await get_instance(hass).async_block_till_done()
                assert (
                    await get_instance(hass).async_add_executor_job(recorded) == totals
                )
                result = await hass.config_entries.flow.async_init(
                    "eac_cyprus",
                    context={"source": "reauth", "entry_id": entry.entry_id},
                    data=entry.data,
                )
                assert result["step_id"] == "reauth_confirm", result
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"], {"password": "replacement"}
                )
                await hass.async_block_till_done()
                assert result["reason"] == "reauth_successful", result
                assert entry.state.value == "loaded"
                assert entry.data["password"] == "replacement"
                assert await hass.config_entries.async_unload(entry.entry_id)
                assert not hass.services.has_service(
                    "eac_cyprus", "import_full_history"
                )
                print(
                    json.dumps(
                        {
                            "homeassistant": version("homeassistant"),
                            "result": "passed",
                            "checks": [
                                "config flow",
                                "entity setup",
                                "provisional sensors and graph payload exclusion",
                                "tariff discovery and permission-scoped profile API",
                                "actual SQLite statistics write",
                                "repeat import idempotency",
                                "reauth and reload",
                                "unload and service cleanup",
                            ],
                        }
                    )
                )
        finally:
            await hass.async_stop(force=True)


asyncio.run(main())
