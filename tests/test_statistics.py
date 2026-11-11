"""Tests for the long-term-statistics backfill module."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from eac_dso_portal import Reading
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import EnergyConverter
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eac_cyprus.const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from custom_components.eac_cyprus.statistics import (
    external_statistic_id,
    import_cumulative_history,
)


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com",
        data={CONF_EMAIL: "test@example.com", CONF_PASSWORD: "x"},
        title="Test User",
    )
    entry.add_to_hass(hass)
    return entry


def _readings(*pairs: tuple[str, float | None, float]) -> tuple[Reading, ...]:
    """Build Readings from (iso_dt, reading|None, value) triples."""
    return tuple(
        Reading(dt=datetime.fromisoformat(dt), reading=r, value=v) for dt, r, v in pairs
    )


def test_external_statistic_id_format() -> None:
    """The ID must contain a colon and start with the integration domain.
    HA's recorder rejects external statistic_ids that do not follow that
    pattern."""
    sid = external_statistic_id("863224497404", "129343890428")
    assert sid == "eac_cyprus:863224497404_129343890428"
    assert ":" in sid


async def test_no_op_when_no_cumulative_readings(hass: HomeAssistant) -> None:
    """Interval channels (reading=None) produce no statistics."""
    interval_only = _readings(
        ("2026-05-01T01:00:00", None, 0.5),
        ("2026-05-01T01:30:00", None, 0.6),
    )
    with patch(
        "custom_components.eac_cyprus.statistics.async_add_external_statistics"
    ) as mock_add:
        import_cumulative_history(
            hass, "111", "mc-30min", "KWH-30MIN-LP-IMP", interval_only
        )
    mock_add.assert_not_called()


async def test_imports_cumulative_kwh_with_correct_metadata(
    hass: HomeAssistant,
) -> None:
    """Verify the metadata and StatisticData rows we hand to the recorder."""
    rdgs = _readings(
        ("2026-05-01T00:00:00", 2900.0, 23.0),
        ("2026-05-02T00:00:00", 2924.0, 24.0),
        ("2026-05-03T00:00:00", 2950.0, 26.0),
    )

    with patch(
        "custom_components.eac_cyprus.statistics.async_add_external_statistics"
    ) as mock_add:
        import_cumulative_history(
            hass, "863224497404", "mc-total", "1281890 Energy total (24h)", rdgs
        )

    mock_add.assert_called_once()
    _, metadata, stats = mock_add.call_args.args
    assert metadata["statistic_id"] == "eac_cyprus:863224497404_mc-total"
    assert metadata["source"] == DOMAIN
    assert metadata["has_sum"] is True
    assert metadata["mean_type"] == StatisticMeanType.NONE
    assert metadata["unit_class"] == EnergyConverter.UNIT_CLASS
    assert metadata["unit_of_measurement"] == UnitOfEnergy.KILO_WATT_HOUR
    # Display name is passed through verbatim (meter serial + channel label).
    assert metadata["name"] == "1281890 Energy total (24h)"

    assert len(stats) == 3
    for s, expected_reading in zip(stats, [2900.0, 2924.0, 2950.0], strict=True):
        assert s["start"].tzinfo is UTC
        assert s["start"].minute == 0 and s["start"].second == 0
        assert s["sum"] == expected_reading
        # External statistics do not carry `state`; we only push `sum`.
        assert "state" not in s


async def test_coordinator_pushes_stats_for_cumulative_channel_only(
    hass: HomeAssistant, mock_client
) -> None:
    """Integration check: cumulative channel triggers import, 30-min channel does not."""
    from custom_components.eac_cyprus.coordinator import EacCoordinator

    entry = _entry(hass)
    coord = EacCoordinator(hass, mock_client, entry)
    with patch(
        "custom_components.eac_cyprus.coordinator.import_cumulative_history"
    ) as mock_import:
        await coord._async_update_data()

    called_channels = [
        c.kwargs.get("channel_id") or c.args[2] for c in mock_import.call_args_list
    ]
    assert "100001" in called_channels
    assert "100002" not in called_channels


async def test_channel_change_keeps_same_physical_meter_series(hass):
    """A portal channel change must not restart a cumulative energy series."""
    from custom_components.eac_cyprus.statistics import grid_statistic_id

    with patch(
        "custom_components.eac_cyprus.statistics.async_add_external_statistics"
    ) as add:
        for channel_id, channel_type, stamp, value in [
            ("old", "S-KWH-24H", "2026-10-22T00:00:00", 9305.0),
            ("new", "S-KWH-NET-IMP-MMTR", "2026-10-23T00:00:00", 9337.0),
        ]:
            import_cumulative_history(
                hass,
                "111",
                channel_id,
                "Meter",
                _readings((stamp, value, 0)),
                meter_serial="123",
                channel_type=channel_type,
            )
    continuous = [
        c
        for c in add.call_args_list
        if c.args[1]["statistic_id"] == grid_statistic_id("111", "123", "import")
    ]
    assert len(continuous) == 2
    assert continuous[1].args[2][0]["sum"] - continuous[0].args[2][0]["sum"] == 32
    # Cyprus midnight on the 23rd closes the UTC hour starting 20:00 on the 22nd.
    assert continuous[1].args[2][0]["start"] == datetime(2026, 10, 22, 20, tzinfo=UTC)


async def test_tariffs_do_not_duplicate_grid_total(hass):
    with patch(
        "custom_components.eac_cyprus.statistics.async_add_external_statistics"
    ) as add:
        import_cumulative_history(
            hass,
            "111",
            "tariff",
            "Tariff",
            _readings(("2026-10-23T00:00:00", 100, 0)),
            meter_serial="123",
            channel_type="S-KWH-NORMAL",
        )
    assert add.call_count == 1


def test_grid_register_closes_day_and_month_across_dst():
    from custom_components.eac_cyprus.statistics import grid_statistics_rows

    rows = grid_statistics_rows(
        _readings(
            ("2026-10-25T00:00:00", 100, 0),
            ("2026-10-26T00:00:00", 110, 0),
            ("2026-11-01T00:00:00", 120, 0),
        )
    )
    assert [r["start"] for r in rows] == [
        datetime(2026, 10, 24, 20, tzinfo=UTC),
        datetime(2026, 10, 25, 21, tzinfo=UTC),
        datetime(2026, 10, 31, 21, tzinfo=UTC),
    ]


async def test_net_export_can_be_negative_and_unpaired_values_are_omitted(hass):
    from custom_components.eac_cyprus.statistics import import_grid_net_history

    imports = _readings(
        ("2026-11-01T00:00:00", 100, 0),
        ("2026-11-02T00:00:00", 104, 0),
        ("2026-11-03T00:00:00", 105, 0),
    )
    exports = _readings(
        ("2026-11-01T00:00:00", 110, 0), ("2026-11-02T00:00:00", 127, 0)
    )
    with patch(
        "custom_components.eac_cyprus.statistics.async_add_external_statistics"
    ) as add:
        import_grid_net_history(hass, "111", "123", imports, exports)
    rows = add.call_args.args[2]
    assert len(rows) == 2
    assert [r["sum"] for r in rows] == [-10, -23]
    assert rows[1]["sum"] - rows[0]["sum"] == -13
