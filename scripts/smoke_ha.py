"""Run actual HA setup/recorder/reauth APIs with a synthetic portal, offline.

Does not use the version-pinned pytest HA fixtures or access a production HA.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import homeassistant  # Initialize HTTP/schema compatibility aliases first.
import asyncio
from datetime import datetime, UTC
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
        client.get_user_details.return_value = UserDetails("Synthetic User", False, {})
        client.list_service_points.return_value = [
            ServicePoint("123", "Test", True, True, "S1", None, None, None, {})
        ]
        channel = MeasurementChannel("456", "S-KWH-24H", "KWH", "24H", False, 8, 0, {})
        client.get_meter_configs.return_value = [
            MeterConfig(
                "S1", "Test", "Test", datetime(2026, 1, 1), None, (channel,), {}
            )
        ]
        client.get_readings.return_value = [
            ChannelReadings("456", (Reading(datetime(2026, 11, 1), 10, 100),))
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
