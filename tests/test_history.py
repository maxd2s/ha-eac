"""Tests for the one-time full-history import."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from homeassistant.core import HomeAssistant


async def test_import_full_history_imports_cumulative_channels(
    hass: HomeAssistant, mock_client
) -> None:
    """Full import writes stats for each cumulative channel of the active meter."""
    from custom_components.eac_cyprus.history import async_import_full_history

    with patch(
        "custom_components.eac_cyprus.history.import_cumulative_history"
    ) as mock_import:
        results = await async_import_full_history(hass, mock_client)

    # One cumulative kWh channel (100001); the 30-min interval channel and
    # the inactive service point are skipped.
    assert len(results) == 1
    assert results[0]["channel"] == "S-KWH-24H"
    assert results[0]["meter"] == "NEW123"
    assert mock_import.call_count == 1
    _hass, sp_id, ch_id, display_name, _readings = mock_import.call_args.args
    assert sp_id == "111111111111"
    assert ch_id == "100001"
    # Named from the meter serial, not the transliterated address.
    assert display_name.startswith("NEW123 ")


async def test_import_full_history_spans_install_window(
    hass: HomeAssistant, mock_client
) -> None:
    """Readings are fetched from the meter's install date, not a rolling window."""
    from custom_components.eac_cyprus.history import async_import_full_history

    with patch("custom_components.eac_cyprus.history.import_cumulative_history"):
        await async_import_full_history(hass, mock_client)

    calls = [
        c
        for c in mock_client.get_readings.call_args_list
        if c.kwargs.get("mc_id") == "100001"
    ]
    assert calls
    # fake_active_meter install_date is 2026-02-02; start should be that date.
    start = calls[0].args[1].astimezone(__import__("zoneinfo").ZoneInfo("Asia/Nicosia"))
    assert isinstance(start, datetime)
    assert (start.year, start.month, start.day) == (2026, 2, 2)


async def test_net_history_is_processed_per_window(
    hass, mock_client, fake_active_meter, fake_meter_total_channel
):
    from dataclasses import replace
    from datetime import UTC, timedelta

    from eac_dso_portal import ChannelReadings, Reading

    from custom_components.eac_cyprus.history import async_import_full_history

    exported = replace(fake_meter_total_channel, id="export", type="S-KWH-EXP")
    now = datetime.now(UTC)
    mock_client.get_meter_configs.return_value = [
        replace(
            fake_active_meter,
            install_date=now - timedelta(days=40),
            channels=(fake_meter_total_channel, exported),
        )
    ]
    completed_windows = []

    def readings(sp, start, end, mc_id=None):
        if mc_id == fake_meter_total_channel.id and start > now - timedelta(days=40):
            assert completed_windows[-1] == start
        value = 100 if mc_id == "export" else 200
        return [
            ChannelReadings(
                mc_id, (Reading(start, 0, value), Reading(end, 0, value + 1))
            )
        ]

    def net(hass, sp, serial, imports, exports):
        assert len(imports) <= 2 and len(exports) <= 2
        assert imports[0].dt == exports[0].dt
        completed_windows.append(imports[-1].dt)

    mock_client.get_readings.side_effect = readings
    with (
        patch("custom_components.eac_cyprus.history.import_cumulative_history"),
        patch(
            "custom_components.eac_cyprus.history.import_grid_net_history",
            side_effect=net,
        ),
    ):
        result = await async_import_full_history(hass, mock_client)
    assert len(completed_windows) == 3
    assert [r["readings"] for r in result] == [4, 4]


async def test_history_clamps_untrusted_dates(hass, mock_client, fake_active_meter):
    from dataclasses import replace
    from datetime import UTC, timedelta

    from custom_components.eac_cyprus.history import async_import_full_history

    before = datetime.now(UTC)
    mock_client.get_meter_configs.return_value = [
        replace(
            fake_active_meter,
            install_date=datetime(1900, 1, 1),
            removal_date=datetime(2100, 1, 1),
        )
    ]
    mock_client.get_readings.return_value = []
    await async_import_full_history(hass, mock_client)
    calls = mock_client.get_readings.call_args_list
    assert calls[0].args[1] >= before - timedelta(days=3650)
    assert calls[-1].args[2] <= datetime.now(UTC)
    assert len(calls) <= 261
