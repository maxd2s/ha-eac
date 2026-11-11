"""History-service access and concurrency limits."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from tests.test_sensor import _setup_integration


async def test_history_requires_admin(hass, patch_eac_client, hass_read_only_user):
    await _setup_integration(hass, patch_eac_client)
    with patch("custom_components.eac_cyprus.async_import_full_history") as importer:
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                "eac_cyprus",
                "import_full_history",
                {},
                blocking=True,
                context=Context(user_id=hass_read_only_user.id),
            )
    importer.assert_not_called()


async def test_duplicate_history_rejected_and_lock_released(hass, patch_eac_client):
    entry = await _setup_integration(hass, patch_eac_client)
    coordinator = hass.data["eac_cyprus"][entry.entry_id]
    started = asyncio.Event()
    finish = asyncio.Event()

    async def importing(*args):
        started.set()
        await finish.wait()
        return []

    with patch(
        "custom_components.eac_cyprus.async_import_full_history", side_effect=importing
    ):
        task = asyncio.create_task(
            hass.services.async_call(
                "eac_cyprus", "import_full_history", {}, blocking=True
            )
        )
        await started.wait()
        assert coordinator.operation_lock.locked()
        with pytest.raises(HomeAssistantError, match="already running"):
            await hass.services.async_call(
                "eac_cyprus", "import_full_history", {}, blocking=True
            )
        finish.set()
        await task
    assert not coordinator.history_import_running
    assert not coordinator.operation_lock.locked()


async def test_history_deadline_includes_lock_wait(hass, patch_eac_client):
    entry = await _setup_integration(hass, patch_eac_client)
    coordinator = hass.data["eac_cyprus"][entry.entry_id]
    timeout = asyncio.timeout
    await coordinator.operation_lock.acquire()
    try:
        with (
            patch(
                "custom_components.eac_cyprus.asyncio.timeout",
                side_effect=lambda _: timeout(0.01),
            ),
            patch("custom_components.eac_cyprus.async_import_full_history") as importer,
        ):
            with pytest.raises(HomeAssistantError, match="interrupted"):
                await hass.services.async_call(
                    "eac_cyprus", "import_full_history", {}, blocking=True
                )
        importer.assert_not_called()
        assert not coordinator.history_import_running
    finally:
        coordinator.operation_lock.release()


async def test_poll_deadline_includes_lock_wait(hass, patch_eac_client):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    entry = await _setup_integration(hass, patch_eac_client)
    coordinator = hass.data["eac_cyprus"][entry.entry_id]
    timeout = asyncio.timeout
    await coordinator.operation_lock.acquire()
    try:
        with patch(
            "custom_components.eac_cyprus.coordinator.asyncio.timeout",
            side_effect=lambda _: timeout(0.01),
        ):
            with pytest.raises(UpdateFailed, match="retrying"):
                await coordinator._async_update_data()
    finally:
        coordinator.operation_lock.release()
