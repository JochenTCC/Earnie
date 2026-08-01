"""Tests for consumer cost attribution (2.3.e option I)."""
from __future__ import annotations

from datetime import datetime

import pytest

from ui.consumer_cost_analysis_data import (
    BASELOAD_ID,
    aggregate_slots,
    attribute_load_shares,
    build_slot_from_powers,
    filter_slots_calendar_month,
    filter_slots_iso_week,
    iso_weeks_in_slots,
)


def test_attribute_pro_rata_equal_loads() -> None:
    shares = attribute_load_shares(
        load_by_id={BASELOAD_ID: 2.0, "ev": 2.0},
        pv_to_load=2.0,
        grid_to_load=1.0,
        discharge_to_load=1.0,
        price_cent=40.0,
        dt_hours=0.25,
    )
    assert len(shares) == 2
    by_id = {s.consumer_id: s for s in shares}
    assert by_id[BASELOAD_ID].pv_kwh == pytest.approx(0.25)
    assert by_id["ev"].pv_kwh == pytest.approx(0.25)
    assert by_id[BASELOAD_ID].grid_kwh == pytest.approx(0.125)
    assert by_id["ev"].battery_kwh == pytest.approx(0.125)
    # Option I: only grid costs money
    assert by_id[BASELOAD_ID].cost_euro == pytest.approx(0.05)
    assert by_id["ev"].cost_euro == pytest.approx(0.05)


def test_attribute_zero_load_returns_empty() -> None:
    shares = attribute_load_shares(
        load_by_id={BASELOAD_ID: 0.0, "ev": 0.0},
        pv_to_load=1.0,
        grid_to_load=1.0,
        discharge_to_load=0.0,
        price_cent=30.0,
    )
    assert shares == ()


def test_build_slot_pv_covers_load_zero_cost() -> None:
    slot = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 12, 0),
        price_cent=50.0,
        pv_kw=4.0,
        load_by_id={BASELOAD_ID: 1.0, "pool": 1.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=0.0,
        grid_export_kw=2.0,
    )
    assert slot.house_grid_cost_euro == pytest.approx(0.0)
    assert sum(s.cost_euro for s in slot.shares) == pytest.approx(0.0)
    assert sum(s.pv_kwh for s in slot.shares) == pytest.approx(0.5)


def test_build_slot_grid_only_costs() -> None:
    slot = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 18, 0),
        price_cent=40.0,
        pv_kw=0.0,
        load_by_id={"ev": 4.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
    )
    assert len(slot.shares) == 1
    share = slot.shares[0]
    assert share.grid_kwh == pytest.approx(1.0)
    assert share.cost_euro == pytest.approx(0.4)
    assert share.pv_kwh == pytest.approx(0.0)
    assert share.battery_kwh == pytest.approx(0.0)


def test_build_slot_battery_discharge_zero_cost() -> None:
    slot = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 20, 0),
        price_cent=60.0,
        pv_kw=0.0,
        load_by_id={BASELOAD_ID: 2.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=2.0,
        grid_import_kw=0.0,
        grid_export_kw=0.0,
    )
    share = slot.shares[0]
    assert share.battery_kwh == pytest.approx(0.5)
    assert share.cost_euro == pytest.approx(0.0)
    assert slot.battery_discharge_kwh == pytest.approx(0.5)
    assert slot.discharge_to_load_kwh == pytest.approx(0.5)
    assert slot.export_from_battery_kwh == pytest.approx(0.0)


def test_build_slot_discharge_export_split() -> None:
    slot = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 14, 0),
        price_cent=10.0,
        pv_kw=0.0,
        load_by_id={BASELOAD_ID: 1.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=3.0,
        grid_import_kw=0.0,
        grid_export_kw=2.0,
    )
    assert slot.discharge_to_load_kwh == pytest.approx(0.25)
    assert slot.export_from_battery_kwh == pytest.approx(0.5)
    assert slot.battery_discharge_kwh == pytest.approx(0.75)


def test_battery_flow_chart_stacked_totals() -> None:
    from ui.consumer_cost_analysis_charts import (
        battery_flow_balance_caption,
        battery_flow_chart,
    )

    slot = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 12, 0),
        price_cent=20.0,
        pv_kw=5.0,
        load_by_id={BASELOAD_ID: 1.0},
        battery_charge_kw=2.0,
        battery_discharge_kw=0.0,
        grid_import_kw=0.0,
        grid_export_kw=2.0,
    )
    disc = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 20, 0),
        price_cent=40.0,
        pv_kw=0.0,
        load_by_id={BASELOAD_ID: 1.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=2.0,
        grid_import_kw=0.0,
        grid_export_kw=1.0,
    )
    totals = aggregate_slots((slot, disc))
    assert totals.charge_from_pv_kwh == pytest.approx(0.5)
    assert totals.discharge_to_load_kwh + totals.export_from_battery_kwh == pytest.approx(
        totals.battery_discharge_kwh
    )
    fig = battery_flow_chart(totals, title="t")
    assert fig.layout.barmode == "stack"
    names = {t.name for t in fig.data}
    assert names == {"PV", "Netz (Laden)", "Verbrauch", "Netz (Einspeisung)"}
    caption = battery_flow_balance_caption(totals)
    assert "Laden" in caption and "Entladen" in caption and "Δ" in caption


def test_aggregate_and_week_filter() -> None:
    s1 = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 10, 0),  # ISO week 30
        price_cent=20.0,
        pv_kw=0.0,
        load_by_id={"a": 4.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
    )
    s2 = build_slot_from_powers(
        slot_start=datetime(2026, 7, 27, 10, 0),  # ISO week 31
        price_cent=20.0,
        pv_kw=0.0,
        load_by_id={"a": 4.0},
        battery_charge_kw=1.0,
        battery_discharge_kw=0.0,
        grid_import_kw=5.0,
        grid_export_kw=0.0,
    )
    week30 = filter_slots_iso_week((s1, s2), iso_year=2026, iso_week=30)
    assert week30 == (s1,)
    totals = aggregate_slots(week30)
    assert totals.cost_euro == pytest.approx(0.2)
    assert totals.slot_count == 1
    assert totals.by_consumer["a"].cost_euro == pytest.approx(0.2)

    month = filter_slots_calendar_month((s1, s2), year=2026, month=7)
    assert len(month) == 2
    weeks = iso_weeks_in_slots((s1, s2))
    assert weeks == [(2026, 30), (2026, 31)]

    week31 = aggregate_slots(filter_slots_iso_week((s1, s2), iso_year=2026, iso_week=31))
    assert week31.battery_charge_kwh == pytest.approx(0.25)
    assert week31.charge_from_grid_kwh == pytest.approx(0.25)


def test_manual_schedule_peels_from_baseload() -> None:
    import config
    from data.planning_window import align_to_planning_timezone
    from optimizer.appliance_schedule import CHART_KIND_MANUAL_APPLIANCE
    from ui.consumer_cost_analysis_data import _load_by_id_from_entry

    manual = {
        "id": "waschmaschine",
        "name": "Waschmaschine",
        "chart_kind": CHART_KIND_MANUAL_APPLIANCE,
        "default_power_kw": 2.0,
    }
    entry = {
        "consumption_snapshot": {"baseload_kw": 3.0, "pv_kw": 0.0, "flex_kw": {}},
        "forecast_pv_kw": 0.0,
        "forecast_consumption_kw": 3.0,
        "flex_measured_ids": [],
    }
    slot_start = align_to_planning_timezone(
        datetime(2026, 7, 20, 10, 0),
        config.get_planning_timezone(),
    )
    schedules = {
        "waschmaschine": {
            "start_at": slot_start.isoformat(timespec="seconds"),
            "power_kw": 2.0,
            "runtime_h": 1.0,
        }
    }
    loads = _load_by_id_from_entry(
        entry,
        [manual],
        slot_start=slot_start,
        schedules=schedules,
    )
    assert loads["waschmaschine"] == pytest.approx(2.0)
    assert loads["baseload"] == pytest.approx(1.0)


def test_cost_analysis_consumers_includes_manuals(monkeypatch) -> None:
    from ui.consumer_cost_analysis_data import cost_analysis_consumers

    monkeypatch.setattr(
        "ui.consumer_cost_analysis_data.config.get_flexible_consumers",
        lambda optimizer_only=False: [{"id": "eauto", "name": "E-Auto"}],
    )
    monkeypatch.setattr(
        "ui.consumer_cost_analysis_data.config.get_appliances",
        lambda: [{"id": "waschmaschine", "name": "Waschmaschine"}],
    )
    consumers = cost_analysis_consumers()
    ids = [c["id"] for c in consumers]
    assert "eauto" in ids
    assert "waschmaschine" in ids
    manual = next(c for c in consumers if c["id"] == "waschmaschine")
    assert manual.get("chart_kind") == "manual_appliance"
