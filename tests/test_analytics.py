"""Synthetic cross-account, interval coverage, tariff and permission checks."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from eac_dso_portal import Reading

from custom_components.eac_cyprus.analytics import (
    merge_profile,
    profile_insights,
    window_start,
)
from custom_components.eac_cyprus.tariff import parse_tariff_code
from custom_components.eac_cyprus.time import PORTAL_TIME_ZONE
from custom_components.eac_cyprus.websocket import ws_meters, ws_profile
from tests.test_security import Response, client_with
from tests.test_sensor import _setup_integration


def test_cache_corrections_pruning_and_independent_channels():
    now = datetime(2026, 4, 20, 12, tzinfo=UTC)
    start = window_start(now, 7)
    rows = (
        Reading(start + timedelta(minutes=30), 1, None),
        Reading(start + timedelta(hours=1), 2, None),
        Reading(start - timedelta(hours=1), 99, None),
        Reading(now + timedelta(hours=1), 99, None),
    )
    cache = {}
    merge_profile(cache, "import", rows, start, now, now, 7)
    merge_profile(cache, "import", rows, start, now, now, 7)
    assert len(cache["import"]) == 2
    merge_profile(
        cache,
        "import",
        (Reading(rows[0].dt, 3, None), Reading(rows[1].dt, float("nan"), None)),
        start,
        now,
        now,
        7,
    )
    report = profile_insights(cache, now, 7, 0, 6)
    assert len(report["points"]) == 1 and report["points"][0][1:] == [3, None]
    assert report["peak_import_kw"] == 6
    assert report["export_intervals"] == 0 and report["paired_intervals"] == 0
    assert report["overnight_baseline_kw"] is None
    merge_profile(cache, "import", (), start, now, now + timedelta(days=8), 7)
    assert cache["import"] == {}


@pytest.mark.parametrize(("month", "day", "slots"), [(3, 29, 10), (10, 25, 14)])
def test_complete_nights_dst_and_missing_sample(month, day, slots):
    midnight = datetime(2026, month, day, tzinfo=PORTAL_TIME_ZONE).astimezone(UTC)
    end = datetime(2026, month, day, 6, tzinfo=PORTAL_TIME_ZONE).astimezone(UTC)
    now = end + timedelta(hours=1)
    cache = {}
    rows = tuple(
        Reading(midnight + timedelta(minutes=30 * i), 0.25, None)
        for i in range(1, slots + 1)
    )
    merge_profile(cache, "import", rows, midnight, end, now, 7)
    report = profile_insights(cache, now, 7, 0, 6)
    assert report["complete_nights"] == 1 and report["overnight_baseline_kw"] == 0.5
    cache["import"].pop(str(int(rows[0].dt.timestamp())))
    assert profile_insights(cache, now, 7, 0, 6)["complete_nights"] == 0


def test_night_wrap_and_export_zeros():
    start = datetime(2026, 4, 19, 22, tzinfo=PORTAL_TIME_ZONE).astimezone(UTC)
    now = start + timedelta(hours=7)
    cache = {}
    rows = tuple(
        Reading(start + timedelta(minutes=30 * i), 1, None) for i in range(1, 13)
    )
    merge_profile(cache, "import", rows, start, now, now, 7)
    merge_profile(cache, "export", (Reading(rows[0].dt, 0, None),), start, now, now, 7)
    r = profile_insights(cache, now, 7, 22, 4)
    assert r["complete_nights"] == 1 and r["overnight_baseline_kw"] == 2
    assert r["surplus_by_half_hour"][44] == [44, 0, 1]
    assert r["surplus_by_half_hour"][45] == [45, None, 0]


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<td>TARRIF/RATE:</td><td>TEST-7B</td>", "TEST-7B"),
        ("<b>Tariff:</b><span>FUTURE_CODE</span>", "FUTURE_CODE"),
        ("<p>Tariff: Z-NEW/3</p>", "Z-NEW/3"),
        ("<b>ΔΙΑΤΙΜΗΣΗ:</b><td>TEST9</td>", "TEST9"),
        (
            "<style>Tariff: BAD</style><script>Tariff: BAD</script><td>Customer:</td><td>SECRET NAME</td>",
            None,
        ),
        ("<td>Tariff:</td><td>Customer Name:</td><td>SECRET</td>", None),
    ],
)
def test_tariff_identifier_not_personal_report_content(html, expected):
    assert parse_tariff_code(html) == expected


async def test_report_transport_reuses_security_and_auth_retry():
    client, session = client_with(
        Response(200, {"jwt": "FIRST"}),
        Response(401),
        Response(200, {"jwt": "SECOND"}),
        Response(200, body=b"<td>TARRIF/RATE:</td><td>TEST-9</td>"),
    )
    code = await client.get_tariff_code(
        "synthetic-sp", "synthetic-meter", datetime(2026, 4, 20, tzinfo=UTC)
    )
    assert code == "TEST-9"
    call = session.request.call_args
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["headers"]["Authorization"] == "Bearer SECOND"
    assert call.kwargs["json"]["serialNumber"] == "synthetic-meter"


async def test_discovery_and_profile_require_entity_read_permission(
    hass, patch_eac_client
):
    await _setup_integration(hass, patch_eac_client)
    connection = MagicMock()
    connection.user.permissions.check_entity.return_value = True
    ws_meters(hass, connection, {"id": 1, "type": "eac_cyprus/profile_meters"})
    meters = connection.send_result.call_args.args[1]
    assert len(meters) == 1
    entity = meters[0]["entity_id"]
    ws_profile(hass, connection, {"id": 2, "entity_id": entity})
    result = connection.send_result.call_args.args[1]
    assert "points" in result and "password" not in result
    assert not any(
        "points" in s.attributes
        for s in hass.states.async_all()
        if "profile_coverage" in s.entity_id
    )
    connection.user.permissions.check_entity.return_value = False
    ws_meters(hass, connection, {"id": 3})
    assert connection.send_result.call_args.args[1] == []
    ws_profile(hass, connection, {"id": 4, "entity_id": entity})
    assert connection.send_error.call_args.args[1] == "not_found"


async def test_cache_seed_and_tariff_do_not_refetch_each_poll(
    hass, patch_eac_client, freezer
):
    freezer.move_to("2026-05-08T18:00:00+03:00")
    patch_eac_client.get_tariff_code.return_value = "SYNTHETIC-2"
    entry = await _setup_integration(hass, patch_eac_client)
    coordinator = hass.data["eac_cyprus"][entry.entry_id]
    first = next(
        c
        for c in patch_eac_client.get_readings.call_args_list
        if c.kwargs.get("mc_id") == "100002"
    )
    assert (first.args[2] - first.args[1]).days >= 29
    await coordinator.async_refresh()
    calls = [
        c
        for c in patch_eac_client.get_readings.call_args_list
        if c.kwargs.get("mc_id") == "100002"
    ]
    assert (calls[-1].args[2] - calls[-1].args[1]).days == 14
    assert patch_eac_client.get_tariff_code.await_count == 1
    assert len(coordinator._profiles) == 1
    assert "raw" not in str(coordinator._profiles)
    stored = await coordinator._profile_store.async_load()
    assert stored == coordinator._profiles
    coordinator._profiles_loaded = False
    await coordinator.async_refresh()
    assert patch_eac_client.get_tariff_code.await_count == 1


async def test_two_accounts_only_return_authorized_meter(
    hass, patch_eac_client, fake_active_sp, fake_active_meter
):
    from dataclasses import replace

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.eac_cyprus.const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

    await _setup_integration(hass, patch_eac_client)
    patch_eac_client.list_service_points.return_value = [
        replace(fake_active_sp, id="333333333333")
    ]
    patch_eac_client.get_meter_configs.return_value = [
        replace(fake_active_meter, serial_number="OTHER-METER")
    ]
    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="second@example.test",
        data={CONF_EMAIL: "second@example.test", CONF_PASSWORD: "synthetic"},
        title="Second synthetic account",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    connection = MagicMock()
    connection.user.permissions.check_entity.return_value = True
    ws_meters(hass, connection, {"id": 1})
    meters = connection.send_result.call_args.args[1]
    assert len(meters) == 2
    allowed = meters[0]["entity_id"]
    denied = meters[1]["entity_id"]
    connection.user.permissions.check_entity.side_effect = lambda entity, policy: (
        entity == allowed
    )
    ws_meters(hass, connection, {"id": 2})
    assert [x["entity_id"] for x in connection.send_result.call_args.args[1]] == [
        allowed
    ]
    ws_profile(hass, connection, {"id": 3, "entity_id": denied})
    assert connection.send_error.call_args.args[1] == "not_found"
    caches = [c._profiles for c in hass.data[DOMAIN].values()]
    assert not set(caches[0]) & set(caches[1])
