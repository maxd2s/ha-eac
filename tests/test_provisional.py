"""Provisional estimates must not fabricate missing energy or persist totals."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from eac_dso_portal import ChannelReadings, Reading

from custom_components.eac_cyprus.provisional import today_profile
from custom_components.eac_cyprus.time import PORTAL_TIME_ZONE
from tests.test_sensor import _setup_integration


def reading(hour, minute, value=1):
    return Reading(datetime(2026, 11, 11, hour, minute), value, None)


def test_pairing_invalid_duplicates_and_window():
    incoming = (
        reading(0, 0, 99),
        reading(0, 30, 2),
        reading(0, 30, 3),
        reading(1, 0, 8),
        reading(1, 30, float("nan")),
        reading(2, 0, -1),
        reading(2, 30, 6),
        reading(1, 10, 55),
    )
    outgoing = tuple(reading(h, m, 0.5) for h, m in [(0, 30), (1, 30), (2, 0), (2, 30)])
    result = today_profile(incoming, outgoing, datetime(2026, 11, 11, 2, 15))
    assert result["import_kwh"] == 3
    assert result["export_kwh"] == 0.5
    assert result["paired_intervals"] == 1
    assert result["expected_intervals"] == 4
    assert result["missing_intervals"] == 3
    assert result["gaps_before_latest"] == 0
    assert len(result["points"]) == 1
    assert today_profile(incoming, outgoing, datetime(2026, 11, 11, 2, 15)) == result


def test_gap_is_not_zero_and_directions_share_coverage():
    imp = (reading(0, 30, 2), reading(1, 0, 100), reading(1, 30, 3))
    exp = (reading(0, 30, 0), reading(1, 30, 4))
    result = today_profile(imp, exp, datetime(2026, 11, 11, 2))
    assert result["import_kwh"] == 5
    assert result["export_kwh"] == 4
    assert result["gaps_before_latest"] == 1
    assert result["missing_intervals"] == 2


def test_empty_is_unknown_not_zero_and_midnight_clears():
    assert today_profile((), (), datetime(2026, 11, 11, 12))["import_kwh"] is None
    assert (
        today_profile((reading(1, 0),), (), datetime(2026, 11, 11, 12))["import_kwh"]
        is None
    )
    assert (
        today_profile((reading(1, 0),), (reading(1, 0),), datetime(2026, 11, 12))[
            "points"
        ]
        == []
    )
    result = today_profile(
        (reading(0, 30, 0),), (reading(0, 30, 0),), datetime(2026, 11, 11, 1)
    )
    assert result["import_kwh"] == 0


@pytest.mark.parametrize(("month", "day", "hours"), [(3, 29, 23), (10, 25, 25)])
def test_dst_uses_real_half_hours(month, day, hours):
    start = datetime(2026, month, day, tzinfo=PORTAL_TIME_ZONE).astimezone(UTC)
    # Last completed interval before next local midnight.
    now = start + timedelta(hours=hours, minutes=-1)
    rows = tuple(
        Reading(start + timedelta(minutes=30 * i), 1, None) for i in range(1, 51)
    )
    result = today_profile(rows, rows, now)
    assert result["paired_intervals"] == hours * 2 - 1
    assert result["expected_intervals"] == hours * 2 - 1
    assert result["missing_intervals"] == 0


async def test_live_entities_fetch_replacement_midnight_and_no_statistics(
    hass, patch_eac_client, fake_active_meter, fake_meter_30min_channel, freezer
):
    freezer.move_to("2026-11-11T00:00:00+00:00")  # 02:00 Cyprus
    export = replace(fake_meter_30min_channel, id="100003", type="KWH-30MIN-LP-EXP")
    patch_eac_client.get_meter_configs.return_value = [
        replace(fake_active_meter, channels=(*fake_active_meter.channels, export))
    ]

    def fetch(sp_id, start, end, mc_id=None):
        values = (
            (reading(0, 30, 2), reading(1, 0, 3))
            if mc_id == "100002"
            else (reading(0, 30, 0.5), reading(1, 0, 1))
        )
        return [ChannelReadings(mc_id, values)] if mc_id in ("100002", "100003") else []

    patch_eac_client.get_readings.side_effect = fetch
    entry = await _setup_integration(hass, patch_eac_client)
    states = [s for s in hass.states.async_all() if "today_" in s.entity_id]
    assert len(states) == 3
    from custom_components.eac_cyprus.sensor import EacTodaySensor
    assert "points" in EacTodaySensor._unrecorded_attributes
    net_id = next(s.entity_id for s in states if "today_net" in s.entity_id)
    net = hass.states.get(net_id)
    assert float(net.state) == 3.5
    assert net.attributes["paired_intervals"] == 2
    assert len(net.attributes["points"]) == 2
    assert all("state_class" not in s.attributes for s in states)
    coordinator = hass.data["eac_cyprus"][entry.entry_id]
    await coordinator.async_refresh()
    assert float(hass.states.get(net_id).state) == 3.5  # no duplicate accumulation
    # Empty response replaces old data instead of carrying forward yesterday.
    patch_eac_client.get_readings.side_effect = lambda *a, mc_id=None, **kw: []
    await coordinator.async_refresh()
    assert hass.states.get(net_id).state == "unknown"
    patch_eac_client.get_readings.side_effect = fetch
    await coordinator.async_refresh()
    freezer.move_to("2026-11-12T00:00:00+02:00")
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(net_id).state == "unknown"
    assert hass.states.get(net_id).attributes["points"] == []
