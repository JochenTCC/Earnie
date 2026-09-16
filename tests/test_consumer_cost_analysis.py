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
    filter_slots_trailing_days,
    filter_slots_window,
    iso_weeks_in_slots,
)
from ui.consumption_display.period import PeriodKind, resolve_rolling_window


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
    from ui.consumer_cost_battery_metrics import build_battery_period_metrics

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
    metrics = build_battery_period_metrics(
        totals, eta_nominal=0.95, standby_power_kw=0.1
    )
    fig = battery_flow_chart(totals, title="t", standby_a_kwh=metrics.standby_a_kwh)
    assert fig.layout.barmode == "stack"
    names = {t.name for t in fig.data}
    assert names == {
        "PV",
        "Netz (Laden)",
        "Verbrauch",
        "Netz (Einspeisung)",
        "Standby",
    }
    caption = battery_flow_balance_caption(totals, metrics)
    assert "Laden" in caption and "Entladen" in caption and "Δ" in caption
    assert "Gemessener Wirkungsgrad" in caption
    assert "Empfehlung für HK" in caption
    assert "Kleine Abweichungen sind normal" not in caption


def test_battery_period_metrics_helpers() -> None:
    from ui.consumer_cost_battery_metrics import (
        build_battery_period_metrics,
        configured_standby_kwh,
        measured_battery_efficiency,
        recommended_standby_power_kw,
        residual_standby_kwh,
        standby_diff_significant,
    )

    assert measured_battery_efficiency(4.0, 3.61) == pytest.approx(0.95)
    assert measured_battery_efficiency(0.0, 1.0) is None
    assert measured_battery_efficiency(1.0, 0.0) is None

    assert configured_standby_kwh(0.1, 4) == pytest.approx(0.1)
    assert residual_standby_kwh(10.0, 8.0, 0.95) == pytest.approx(10.0 * 0.95**2 - 8.0)
    assert residual_standby_kwh(10.0, 9.5, 0.95) == pytest.approx(0.0)

    assert recommended_standby_power_kw(1.0, 4) == pytest.approx(1.0)
    assert recommended_standby_power_kw(0.5, 0) is None

    assert standby_diff_significant(1.0, 1.05) is False
    assert standby_diff_significant(1.0, 1.3) is True
    assert standby_diff_significant(0.0, 0.0) is False
    assert standby_diff_significant(0.0, 1.0) is True

    slot = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 12, 0),
        price_cent=20.0,
        pv_kw=0.0,
        load_by_id={BASELOAD_ID: 1.0},
        battery_charge_kw=4.0,
        battery_discharge_kw=0.0,
        grid_import_kw=1.0,
        grid_export_kw=0.0,
    )
    disc = build_slot_from_powers(
        slot_start=datetime(2026, 7, 20, 20, 0),
        price_cent=40.0,
        pv_kw=0.0,
        load_by_id={BASELOAD_ID: 1.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=2.0,
        grid_import_kw=0.0,
        grid_export_kw=0.0,
    )
    totals = aggregate_slots((slot, disc))
    metrics = build_battery_period_metrics(
        totals, eta_nominal=1.0, standby_power_kw=0.0
    )
    assert metrics.recommended_standby_kw == pytest.approx(
        metrics.standby_b_kwh / 0.5
    )
    assert metrics.standby_hint is True
    from ui.consumer_cost_analysis_charts import battery_flow_balance_caption

    caption = battery_flow_balance_caption(totals, metrics)
    assert "Empfehlung Standby-Leistung" in caption
    assert f"{metrics.recommended_standby_kw:.3f} kW" in caption


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


def test_filter_slots_window_and_trailing_days() -> None:
    s1 = build_slot_from_powers(
        slot_start=datetime(2026, 9, 1, 10, 0),
        price_cent=20.0,
        pv_kw=0.0,
        load_by_id={"a": 4.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
    )
    s2 = build_slot_from_powers(
        slot_start=datetime(2026, 9, 10, 10, 0),
        price_cent=20.0,
        pv_kw=0.0,
        load_by_id={"a": 4.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
    )
    s3 = build_slot_from_powers(
        slot_start=datetime(2026, 9, 14, 10, 0),
        price_cent=20.0,
        pv_kw=0.0,
        load_by_id={"a": 4.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
    )
    window = resolve_rolling_window(datetime(2026, 9, 14, 10, 0), days=7)
    assert window.kind == PeriodKind.ROLLING_7
    filtered = filter_slots_window((s1, s2, s3), window)
    assert filtered == (s2, s3)

    trailing = filter_slots_trailing_days(
        (s1, s2, s3), end=datetime(2026, 9, 14, 12, 0), days=5
    )
    assert trailing == (s2, s3)

    yearish = filter_slots_trailing_days(
        (s1, s2, s3), end=datetime(2026, 9, 14, 12, 0), days=365
    )
    assert yearish == (s1, s2, s3)


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
