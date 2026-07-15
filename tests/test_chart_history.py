"""Tests für Produktiv-Log in der S-2-Simulations-Tabelle (Phase 2)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import config
from data.planning_window import history_boundary_exclusive
from runtime_store import history_timeline, optimization_history
from ui.chart_context import SLOT_MILP, build_chart_display_context, build_live_chart_context

LAT = 47.404
LON = 9.743
TZ = "Europe/Vienna"


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


def _write_jsonl(path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def _entry(completed: datetime, **extra) -> dict:
    base = {
        "completed_at": completed.isoformat(timespec="seconds"),
        "source": "main.py",
        "success": True,
        "soc_percent": 50.0,
        "mode": 0,
        "target_power_kw": 0.0,
        "target_soc_percent": 99.0,
        "market_price_cent": 10.0,
        "forecast_pv_kw": 2.0,
        "forecast_consumption_kw": 1.0,
        "battery_plan_kw": 0.5,
        "consumer_powers_kw": {},
        "consumer_pv_follow": {},
    }
    base.update(extra)
    return base


@pytest.fixture
def history_files(tmp_path, monkeypatch):
    jsonl = tmp_path / "optimization_history.jsonl"
    legacy = tmp_path / "legacy.csv"
    monkeypatch.setattr(optimization_history, "HISTORY_FILE", str(jsonl))
    monkeypatch.setattr(optimization_history, "LEGACY_CSV_FILE", str(legacy))
    return jsonl


def test_quarter_hour_slots_between():
    start = _dt(2026, 6, 15, 10, 0)
    end = _dt(2026, 6, 15, 11, 0)
    slots = history_timeline.quarter_hour_slots_between(start, end)
    assert slots == (
        _dt(2026, 6, 15, 10, 0),
        _dt(2026, 6, 15, 10, 15),
        _dt(2026, 6, 15, 10, 30),
        _dt(2026, 6, 15, 10, 45),
    )


def test_build_chart_history_tracks_slot_qualities(history_files):
    window_start = _dt(2026, 6, 15, 10, 0)
    _write_jsonl(
        history_files,
        [_entry(window_start.replace(minute=30), soc_percent=42.0)],
    )
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    assert result.present_slot_count == 1
    assert result.missing_slot_count == 3
    assert result.held_slot_count == 0
    assert result.slot_qualities == (
        history_timeline.SLOT_MISSING,
        history_timeline.SLOT_MISSING,
        history_timeline.SLOT_PRESENT,
        history_timeline.SLOT_MISSING,
    )
    assert result.rows[3]["Simulierter SoC (%)"] is None


def test_build_chart_history_accepts_naive_log_timestamps(history_files):
    window_start = _dt(2026, 6, 15, 10, 0)
    naive_completed = datetime(2026, 6, 15, 10, 0)
    _write_jsonl(history_files, [_entry(naive_completed, soc_percent=41.0)])
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    assert result.present_slot_count == 1
    assert result.rows[0]["Simulierter SoC (%)"] == 41.0


def test_missing_slots_after_present_leave_gaps(history_files):
    import config
    from optimizer.targets import consumer_column_name

    consumers = config.get_flexible_consumers(optimizer_only=True)
    swimspa = next((c for c in consumers if c["id"] == "swimspa"), None)
    if swimspa is None:
        pytest.skip("Kein SwimSpa in der Test-Config.")

    window_start = _dt(2026, 6, 15, 10, 0)
    col = consumer_column_name(swimspa)
    _write_jsonl(
        history_files,
        [
            _entry(
                window_start,
                consumer_powers_kw={"swimspa": 2.8},
                flex_live_kw={"swimspa": 2.8},
            )
        ],
    )
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    assert result.rows[0][col] == 2.8
    assert result.rows[1][col] is None
    assert result.slot_qualities[1] == history_timeline.SLOT_MISSING
    assert result.rows[1]["Simulierter SoC (%)"] is None


def test_build_chart_history_uses_snapshot_grid_kw_for_slot_cost(history_files):
    """Ist-Kosten: Netzbezug aus consumption_snapshot.grid_kw, nicht Soll-Bilanz."""
    window_start = _dt(2026, 6, 15, 10, 0)
    _write_jsonl(
        history_files,
        [
            _entry(
                window_start,
                forecast_pv_kw=2.0,
                forecast_consumption_kw=1.0,
                battery_plan_kw=0.5,
                market_price_cent=20.0,
                consumption_snapshot={
                    "baseload_kw": 1.0,
                    "pv_kw": 2.0,
                    "grid_kw": 2.5,
                    "flex_kw": {},
                    "battery_kw": 0.0,
                },
            ),
        ],
    )
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    row = result.rows[0]
    assert row["Netzbezug (kW)"] == 2.5
    assert result.slot_costs_euro[0] > 0.0
    without_snapshot = history_timeline.entry_to_chart_row(
        _entry(window_start, forecast_pv_kw=2.0, forecast_consumption_kw=1.0, battery_plan_kw=0.5),
        window_start,
    )
    assert without_snapshot["Netzbezug (kW)"] == -0.5


def test_build_chart_history_cumulative_skips_missing_slots(history_files):
    window_start = _dt(2026, 6, 15, 10, 0)
    _write_jsonl(
        history_files,
        [_entry(window_start.replace(minute=30), soc_percent=50.0, market_price_cent=20.0)],
    )
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    assert result.slot_costs_euro[:2] == [0.0, 0.0]
    assert result.slot_costs_euro[3] == 0.0
    assert result.slot_costs_euro[2] != 0.0
    assert result.cumulative_costs_euro[2] == round(result.slot_costs_euro[2], 4)
    assert result.cumulative_costs_euro[3] == result.cumulative_costs_euro[2]


def test_build_chart_display_history_split_ignores_stale_zones(history_files):
    """Log/MILP-Grenze folgt history_boundary_exclusive, nicht zones.history.end."""
    now = _dt(2026, 6, 15, 14, 30)
    chart_context = build_live_chart_context(0, 0, now=now)
    wrong_hour_end = _dt(2026, 6, 15, 14, 0)
    stale_zones = replace(
        chart_context.zones,
        history=replace(chart_context.zones.history, end=wrong_hour_end),
    )
    chart_context = replace(chart_context, zones=stale_zones)
    assert chart_context.zones.history.end == wrong_hour_end

    display = build_chart_display_context(chart_context, [])
    boundary = history_boundary_exclusive(now)
    assert display.slot_datetimes[display.history_slot_count] == boundary
    assert display.slot_qualities[display.history_slot_count] == SLOT_MILP


def test_build_chart_display_merges_history_and_milp(history_files):
    now = _dt(2026, 6, 15, 14, 30)
    chart_context = build_live_chart_context(0, 0, now=now)
    history_end = history_boundary_exclusive(now)
    assert history_end == _dt(2026, 6, 15, 14, 30)
    log_slot = chart_context.chart_window.start.replace(
        hour=chart_context.chart_window.start.hour + 1
    )
    _write_jsonl(history_files, [_entry(log_slot, soc_percent=33.0)])

    hour_zero = _dt(2026, 6, 15, 14, 0)
    sim_rows = [
        {
            "slot_datetime": slot,
            "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
            "Strompreis (Cent/kWh)": 12.0,
            "Preis extrapoliert": False,
            "PV-Prognose (kW)": 1.0,
            "Verbrauch-Prognose (kW)": 0.5,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 0.0,
            "Simulierter SoC (%)": 60.0,
            "Steuerbefehl": "Automatik",
        }
        for slot in chart_context.chart_window.slot_datetimes
        if slot >= hour_zero
    ]

    display = build_chart_display_context(chart_context, sim_rows)
    assert display.history_slot_count > 0
    assert len(display.rows) == len(display.slot_qualities)
    assert display.slot_qualities[-1] == SLOT_MILP
    assert all(
        quality in (
            history_timeline.SLOT_PRESENT,
            history_timeline.SLOT_MISSING,
        )
        for quality in display.slot_qualities[: display.history_slot_count]
    )


def test_build_chart_display_merges_history_and_milp_with_iso_string_slots(history_files):
    """Persistierte Snapshots liefern slot_datetime als ISO-String (main.py JSON)."""
    now = _dt(2026, 6, 15, 14, 30)
    chart_context = build_live_chart_context(0, 0, now=now)
    log_slot = chart_context.chart_window.start.replace(
        hour=chart_context.chart_window.start.hour + 1
    )
    _write_jsonl(history_files, [_entry(log_slot, soc_percent=33.0)])

    hour_zero = _dt(2026, 6, 15, 14, 0)
    sim_rows = [
        {
            "slot_datetime": slot.isoformat(timespec="seconds"),
            "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
            "Strompreis (Cent/kWh)": 12.0,
            "Preis extrapoliert": False,
            "PV-Prognose (kW)": 1.0,
            "Verbrauch-Prognose (kW)": 0.5,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 0.0,
            "Simulierter SoC (%)": 60.0,
            "Steuerbefehl": "Automatik",
        }
        for slot in chart_context.chart_window.slot_datetimes
        if slot >= hour_zero
    ]

    display = build_chart_display_context(chart_context, sim_rows)
    milp_rows = [
        row
        for row, quality in zip(display.rows, display.slot_qualities)
        if quality == SLOT_MILP
    ]
    assert milp_rows
    assert any(row.get("Simulierter SoC (%)") == 60.0 for row in milp_rows)


def test_build_chart_display_quarter_soll_from_milp_hour_zero(history_files):
    now = _dt(2026, 6, 15, 14, 45)
    chart_context = build_live_chart_context(0, 0, now=now)
    hour_zero = _dt(2026, 6, 15, 14, 0)
    _write_jsonl(
        history_files,
        [
            _entry(_dt(2026, 6, 15, 14, 0), soc_percent=40.0),
            _entry(_dt(2026, 6, 15, 14, 15), soc_percent=41.0),
            _entry(_dt(2026, 6, 15, 14, 30), soc_percent=42.0),
        ],
    )
    sim_rows = [
        {
            "slot_datetime": hour_zero,
            "Uhrzeit": hour_zero.strftime("%d.%m. %H:%M"),
            "Strompreis (Cent/kWh)": 12.0,
            "Preis extrapoliert": False,
            "PV-Prognose (kW)": 3.3,
            "Verbrauch-Prognose (kW)": 0.5,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 0.0,
            "Simulierter SoC (%)": 60.0,
            "Steuerbefehl": "Automatik",
        }
    ]
    display = build_chart_display_context(chart_context, sim_rows)
    soll_slots = [
        slot
        for slot, quality in zip(display.slot_datetimes, display.slot_qualities)
        if quality == SLOT_MILP and slot < _dt(2026, 6, 15, 15, 0)
    ]
    assert soll_slots == [_dt(2026, 6, 15, 14, 45)]
    soll_row = next(
        row for row, slot in zip(display.rows, display.slot_datetimes)
        if slot == _dt(2026, 6, 15, 14, 45)
    )
    assert soll_row["PV-Prognose (kW)"] == 3.3
    assert soll_row["Simulierter SoC (%)"] == 60.0


def test_entry_to_chart_row_uses_logged_k_push_act(history_files):
    window_start = _dt(2026, 6, 15, 10, 0)
    _write_jsonl(history_files, [_entry(window_start, k_push_act=8.12)])
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    assert result.rows[0]["Einspeisevergütung (Cent/kWh)"] == 8.12


def test_entry_to_chart_row_feed_in_fallback_without_k_push_act(history_files):
    window_start = _dt(2026, 6, 15, 10, 0)
    _write_jsonl(history_files, [_entry(window_start)])
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    assert result.rows[0]["Einspeisevergütung (Cent/kWh)"] == round(
        config.get_push_price_cent(), 4
    )


def test_entry_to_chart_row_includes_milp_table_columns(history_files):
    from optimizer.targets import consumer_immediate_charge_column_name
    from settings.flexible_consumers import runtime_consumer_id

    ev = next(
        (
            consumer
            for consumer in config.get_flexible_consumers(optimizer_only=True)
            if (consumer.get("charging_schedule") or {}).get("enabled")
        ),
        None,
    )
    if ev is None:
        pytest.skip("Kein EV in der Test-Config.")
    ev_col = consumer_immediate_charge_column_name(ev)
    ev_ctx_id = runtime_consumer_id(ev)

    window_start = _dt(2026, 6, 15, 10, 0)
    _write_jsonl(
        history_files,
        [
            _entry(
                window_start,
                k_push_act=6.0,
                charging_contexts={
                    ev_ctx_id: {"immediate_charge": True, "immediate_charge_kw": 3.5},
                },
            ),
        ],
    )
    result = history_timeline.build_chart_history(
        window_start,
        window_start.replace(hour=11),
    )
    row = result.rows[0]
    assert row["Einspeisevergütung (Cent/kWh)"] == 6.0
    assert ev_col in row
    assert row[ev_col] == 1


def test_build_chart_display_past_cycle_is_history_only(history_files):
    now = _dt(2026, 6, 15, 14, 30)
    chart_context = build_live_chart_context(1, 0, now=now)
    _write_jsonl(
        history_files,
        [_entry(chart_context.chart_window.start.replace(hour=chart_context.chart_window.start.hour + 1))],
    )
    display = build_chart_display_context(chart_context, [])
    assert display.history_only is True
    assert all(q != SLOT_MILP for q in display.slot_qualities)
