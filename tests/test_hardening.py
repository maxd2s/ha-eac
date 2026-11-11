"""Regression checks for auth recovery, bounded work and accurate units/times."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from eac_dso_portal import ChannelReadings, EacApiError, Reading
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eac_cyprus.const import DOMAIN
from custom_components.eac_cyprus.sensor import _value_description
from custom_components.eac_cyprus.statistics import import_cumulative_history
from custom_components.eac_cyprus.time import as_utc


@pytest.mark.parametrize(
    ("local", "utc"),
    [
        ("2026-01-02T00:00:00", "2026-01-01T22:00:00+00:00"),
        ("2026-07-02T00:00:00", "2026-07-01T21:00:00+00:00"),
        ("2026-07-02T00:00:00+00:00", "2026-07-02T00:00:00+00:00"),
    ],
)
def test_portal_timezone(local, utc):
    assert as_utc(datetime.fromisoformat(local)) == datetime.fromisoformat(utc)


def test_unknown_and_reactive_channels_do_not_crash_or_change_energy_to_power():
    assert _value_description("OTHER", "NEW-TYPE", False).name == "NEW-TYPE"
    assert (
        _value_description("KVAH", "S-KVAH-24H", False).native_unit_of_measurement
        == "kVAh"
    )
    assert (
        _value_description("KVRH", "S-KVRH-24H", False).native_unit_of_measurement
        == "kvarh"
    )
    assert (
        _value_description("KWH", "UNKNOWN-INTERVAL", True).native_unit_of_measurement
        == "kWh"
    )


async def test_statistics_sort_deduplicate_and_reject_nonfinite(hass):
    def r(hour, minute, value):
        return Reading(datetime(2026, 1, 2, hour, minute, tzinfo=UTC), 0, value)

    points = (
        r(2, 0, 22),
        r(1, 30, 12),
        r(1, 0, 10),
        r(3, 0, float("nan")),
        r(4, 0, float("inf")),
        r(5, 0, -1),
    )
    with patch(
        "custom_components.eac_cyprus.statistics.async_add_external_statistics"
    ) as add:
        import_cumulative_history(hass, "123", "456", "Test", points)
    stats = add.call_args.args[2]
    assert [row["sum"] for row in stats] == [12, 22]
    assert [row["start"].hour for row in stats] == [1, 2]


async def test_reauth_preserves_entry_identity(hass, patch_eac_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com",
        data={"email": "test@example.com", "password": "old"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    with patch("custom_components.eac_cyprus.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new"}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"
    assert entry.unique_id == "test@example.com"


async def test_unsupported_existing_url_fails_before_network(hass, patch_eac_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with pytest.raises(InvalidData):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": "test@example.com",
                "password": "secret",
                "base_url": "http://127.0.0.1",
            },
        )
    patch_eac_client.login.assert_not_called()


async def test_history_streams_bounded_windows_and_deduplicates_boundaries(
    hass, mock_client
):
    from custom_components.eac_cyprus.history import async_import_full_history

    def readings(sp, start, end, mc_id=None):
        return [ChannelReadings(mc_id, (Reading(start, 0, 100), Reading(end, 0, 101)))]

    mock_client.get_readings.side_effect = readings
    with patch("custom_components.eac_cyprus.history.import_cumulative_history") as add:
        result = await async_import_full_history(hass, mock_client)
    calls = mock_client.get_readings.call_args_list
    assert len(calls) > 1
    assert all(c.args[2] - c.args[1] <= timedelta(days=14) for c in calls)
    assert add.call_count == len(calls)
    assert result[0]["readings"] == len(calls) + 1
    assert max(len(c.args[4]) for c in add.call_args_list) == 2


async def test_history_failure_is_not_reported_as_complete(hass, mock_client):
    from custom_components.eac_cyprus.history import async_import_full_history

    mock_client.get_readings.side_effect = EacApiError(500, "sensitive server body")
    with pytest.raises(RuntimeError, match="interrupted") as err:
        await async_import_full_history(hass, mock_client)
    assert "sensitive" not in str(err.value)


async def test_invalid_options_cannot_overload_portal(hass, patch_eac_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com",
        data={"email": "test@example.com", "password": "secret"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "scan_interval_minutes": "0",
                "history_days": 999999,
                "stale_threshold_days": 4,
            },
        )
    assert not entry.options
