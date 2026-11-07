"""Ledger P11: Chart 1's baseline and the plan's baselines run on the shadow chain."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import pytest

import config
from optimizer.sim_costs import (
    BASELINE_START_LIVE_SOC,
    BASELINE_START_SHADOW_CHAIN,
    soc_correction_increments_euro,
)
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_daemon as daemon
from runtime_store import savings_ledger_store as store
from ui import chart_ledger_savings as cls
from ui.chart_account_render import plan_soc_correction_eur
from ui.chart_slot_axis import ChartSlotAxis
from ui.chart_soc import add_ledger_baseline_soc_trace
from ui.charts import build_power_soc_chart_figure
from ui.simulation_display_bundle import HINT_NO_SHADOW_CHAIN, chart1_baseline_soc

_TZ = ZoneInfo("Europe/Vienna")
_DAY_START = datetime(2026, 11, 7, 7, 0, tzinfo=_TZ)
_DAY_END = datetime(2026, 11, 8, 7, 0, tzinfo=_TZ)
_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 0.9,
    "min_soc": 5.0,
    "max_soc": 100.0,
    "max_power_kw": 5.0,
    "standby_power_kw": 0.0,
}


def _slot(start: datetime, soc_end: float, *, counted: bool = True) -> dict:
    return {
        "slot_start": start.isoformat(),
        "counted": counted,
        "skip_reason": None if counted else sl.SKIP_MISSING,
        "cost_with_eur": 0.1 if counted else 0.0,
        "cost_without_eur": 0.2 if counted else 0.0,
        "import_kwh_with": 0.5 if counted else 0.0,
        "import_kwh_without": 0.8 if counted else 0.0,
        "export_kwh_with": 0.0,
        "export_kwh_without": 0.0,
        "k_act_cent": 20.0 if counted else None,
        "shadow_soc_end": soc_end,
        "house_kwh": 0.5 if counted else 0.0,
    }


def _state(slots: list[dict], *, shadow_soc: float = 40.0, pending: dict | None = None) -> sl.LedgerState:
    return sl.LedgerState(
        savings_v=sl.SAVINGS_V,
        chain_start=_DAY_START,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=shadow_soc,
        day_start=_DAY_START,
        day_end=_DAY_END,
        last_slot_start=datetime.fromisoformat(slots[-1]["slot_start"]) if slots else None,
        soc_actual_end=50.0,
        prev_correction_eur=None,
        slots=tuple(slots),
        pending_slot=pending,
    )


def _slots(count: int) -> list[datetime]:
    return [_DAY_START + timedelta(minutes=15 * i) for i in range(count)]


def _closed(start: datetime, *, pv_kw: float, house_kw: float) -> dict:
    return {
        "interval_start": start.replace(tzinfo=None).isoformat(),
        "sample_count": 30,
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
        "pv_kw": pv_kw,
        "grid_kw": house_kw - pv_kw,
        "battery_kw": 0.0,
        "house_kw": house_kw,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
    }


def _baseline_df(starts: list[datetime], soc: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "slot_datetime": starts,
            "Uhrzeit": [s.strftime("%d.%m. %H:%M") for s in starts],
            "Simulierter SoC (%)": soc,
            "Geplante Batterie-Aktion (kW)": [0.0] * len(starts),
        }
    )


def _trace_points(fig: go.Figure) -> list[tuple[pd.Timestamp, float]]:
    trace = next(item for item in fig.data if item.name == "SoC BL Ziel")
    return [(pd.Timestamp(x), float(y)) for x, y in zip(trace.x, trace.y)]


# --- Past: shadow SoC per slot of the open day


def test_ledger_view_has_shadow_soc_of_open_day_slots_left_of_now():
    starts = _slots(4)
    state = _state([_slot(starts[0], 41.0), _slot(starts[1], 42.0)])

    view = cls.build_ledger_chart_savings(
        starts, 3, state, _BATTERY, [], window_start=starts[0], window_end=_DAY_END
    )

    assert view["slot_shadow_soc"] == [41.0, 42.0, None, None]


def test_no_ledger_has_no_shadow_soc():
    view = cls._no_ledger(3, 2, cls.HINT_NOT_RUNNING)

    assert view["slot_shadow_soc"] == [None, None, None]
    assert view["open_day_start"] is None


# --- Chart 1: one line, no jump at Jetzt


def test_line_runs_from_the_chain_into_the_plan_without_a_jump():
    starts = _slots(5)
    # Slots 0 and 1 are booked; the plan's first row starts where slot 1 ended.
    fig = go.Figure()
    add_ledger_baseline_soc_trace(
        fig,
        _baseline_df(starts, [float("nan"), float("nan"), 42.0, 43.0, 44.0]),
        ChartSlotAxis.from_dataframe(_baseline_df(starts, [0.0] * 5)),
        [41.0, 42.0, None, None, None],
        history_slot_count=2,
        battery_params=_BATTERY,
    )

    points = _trace_points(fig)
    assert points[0] == (pd.Timestamp(starts[0] + timedelta(minutes=15)).tz_localize(None), 41.0)
    assert points[1] == (pd.Timestamp(starts[2]).tz_localize(None), 42.0)
    assert points[2] == (pd.Timestamp(starts[2]).tz_localize(None), 42.0)
    assert points[3] == (pd.Timestamp(starts[3]).tz_localize(None), 43.0)
    assert points[-1][1] == 44.0


def test_line_leaves_a_gap_for_a_slot_without_a_value_but_not_for_the_unbooked_tail():
    starts = _slots(5)
    fig = go.Figure()
    add_ledger_baseline_soc_trace(
        fig,
        None,
        ChartSlotAxis.from_dataframe(_baseline_df(starts, [0.0] * 5)),
        [41.0, None, 43.0, None, None],
        history_slot_count=4,
    )

    values = [y for _x, y in _trace_points(fig)]
    assert values[0] == 41.0
    assert pd.isna(values[1])
    assert values[2] == 43.0
    assert len(values) == 3


def test_no_values_and_no_plan_draw_nothing():
    starts = _slots(3)
    fig = go.Figure()
    add_ledger_baseline_soc_trace(
        fig,
        None,
        ChartSlotAxis.from_dataframe(_baseline_df(starts, [0.0] * 3)),
        [None, None, None],
        history_slot_count=3,
    )

    assert len(fig.data) == 0


# --- From the ledger state to the figure


def _chart1_df(starts: list[datetime]) -> pd.DataFrame:
    count = len(starts)
    return pd.DataFrame(
        {
            "slot_datetime": starts,
            "Uhrzeit": [s.strftime("%d.%m. %H:%M") for s in starts],
            "Simulierter SoC (%)": [50.0] * count,
            "Geplante Batterie-Aktion (kW)": [0.0] * count,
            "Verbrauch-Prognose (kW)": [1.0] * count,
            "PV-Prognose (kW)": [0.0] * count,
            "Netzbezug (kW)": [1.0] * count,
            "Strompreis (Cent/kWh)": [20.0] * count,
            "Steuerbefehl": ["Automatik"] * count,
            "Preis extrapoliert": [False] * count,
        }
    )


def test_figure_draws_the_past_from_a_ledger_state_and_goes_on_from_the_shadow_soc():
    starts = _slots(5)
    state = _state([_slot(starts[0], 41.0), _slot(starts[1], 42.0)], shadow_soc=42.0)
    ledger = cls.build_ledger_chart_savings(
        starts, 2, state, _BATTERY, [], window_start=starts[0], window_end=_DAY_END
    )

    fig = build_power_soc_chart_figure(
        _chart1_df(starts),
        matched_baseline_df=_baseline_df(starts, [float("nan"), float("nan"), 42.0, 43.0, 44.0]),
        history_slot_count=2,
        battery_params=_BATTERY,
        slot_shadow_soc=ledger["slot_shadow_soc"],
    )

    values = [y for _x, y in _trace_points(fig)]
    assert values[:3] == [41.0, 42.0, 42.0]
    assert values[3] == 43.0


def test_figure_without_a_chain_has_no_baseline_line():
    starts = _slots(3)

    fig = build_power_soc_chart_figure(
        _chart1_df(starts),
        matched_baseline_df=_baseline_df(starts, [40.0, 41.0, 42.0]),
        history_slot_count=1,
        battery_params=_BATTERY,
        show_baseline_soc=False,
    )

    assert not [trace for trace in fig.data if trace.name == "SoC BL Ziel"]


def test_chart2_shows_the_plans_soc_correction_only_with_a_future():
    from ui.chart_account_render import account_slots, build_account_figure
    from ui.chart_account_view import ANCHOR_NOW, build_account_view

    starts = _slots(4)
    df = pd.DataFrame({"slot_datetime": starts})
    view_data = {
        "hourly_matched_baseline_cost_euro": [0.1] * 4,
        "hourly_optimized_cost_euro": [0.05] * 4,
        "hourly_matched_baseline_consumption_kwh": [0.5] * 4,
        "hourly_optimized_consumption_kwh": [0.5] * 4,
    }
    slots = account_slots(view_data, history_slot_count=0, slot_count=4)
    view = build_account_view(slots, ANCHOR_NOW)

    fig = build_account_figure(
        df, slots, view, ledger=None, chart_window=None, plan_soc_correction=-0.25
    )
    plain = build_account_figure(df, slots, view, ledger=None, chart_window=None)

    label = "SoC am Ende: 0,25 € abgezogen"
    texts = [item.text for item in fig.layout.annotations]
    assert any(text.replace(".", ",").startswith(label) for text in texts)
    assert not [item.text for item in plain.layout.annotations if "SoC am Ende" in item.text]


# --- What Chart 1 draws


def test_monitor_on_the_chain_draws_the_ledger_line():
    ledger = {"open_day_start": _DAY_START.isoformat(), "slot_shadow_soc": [41.0, None]}

    show, shadow, hint = chart1_baseline_soc(
        {"baseline_start_source": BASELINE_START_SHADOW_CHAIN}, {"ledger_savings": ledger}
    )

    assert (show, shadow, hint) == (True, (41.0, None), None)


@pytest.mark.parametrize(
    ("source", "open_day"),
    [
        (BASELINE_START_LIVE_SOC, _DAY_START.isoformat()),
        (BASELINE_START_SHADOW_CHAIN, None),
        (None, _DAY_START.isoformat()),
    ],
)
def test_monitor_without_a_chain_has_no_line_but_a_hint(monkeypatch, source, open_day):
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [_BATTERY])
    ledger = {"open_day_start": open_day, "slot_shadow_soc": [None]}

    show, shadow, hint = chart1_baseline_soc(
        {"baseline_start_source": source}, {"ledger_savings": ledger}
    )

    assert (show, shadow, hint) == (False, None, HINT_NO_SHADOW_CHAIN)


def test_monitor_without_a_battery_has_no_line_and_no_hint(monkeypatch):
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [])

    assert chart1_baseline_soc({}, {"ledger_savings": {"open_day_start": None}}) == (False, None, None)


def test_scenario_explorer_keeps_its_anchored_line():
    assert chart1_baseline_soc({"matched_baseline_rows": []}, {}) == (True, None, None)


# --- Horizon costs


def _row(soc: float, *, action_kw: float = 0.0, grid_kw: float = 0.0, price: float = 20.0) -> dict:
    return {
        "Simulierter SoC (%)": soc,
        "Geplante Batterie-Aktion (kW)": action_kw,
        "Netzbezug (kW)": grid_kw,
        "Strompreis (Cent/kWh)": price,
        "Einspeisevergütung (Cent/kWh)": 5.0,
    }


def test_correction_uses_the_ledger_formula_on_the_gap_change():
    optimized = [_row(60.0, grid_kw=4.0), _row(60.0, grid_kw=4.0)]
    baseline = [_row(40.0), _row(40.0)]

    # The gap stays at 20 %, so nothing changes and nothing is credited.
    assert sum(soc_correction_increments_euro(optimized, baseline, _BATTERY)) == pytest.approx(0.0)

    # The gap closes from 20 % to 10 %: 10 % × 10 kWh × 0.9 × 20 ct = 0.18 € less.
    optimized = [_row(60.0, grid_kw=4.0), _row(50.0, grid_kw=4.0)]
    assert sum(soc_correction_increments_euro(optimized, baseline, _BATTERY)) == pytest.approx(-0.18)


def test_correction_takes_p_ref_from_the_plans_import_or_the_time_mean():
    baseline = [_row(40.0), _row(40.0)]
    weighted = [_row(50.0, grid_kw=3.0, price=10.0), _row(40.0, grid_kw=1.0, price=30.0)]
    # (3 × 10 + 1 × 30) / 4 = 15 ct on the import; gap −10 % × 10 kWh × 0.9.
    assert sum(soc_correction_increments_euro(weighted, baseline, _BATTERY)) == pytest.approx(-0.135)

    no_import = [_row(50.0, price=10.0), _row(40.0, price=30.0)]
    # Time mean 20 ct.
    assert sum(soc_correction_increments_euro(no_import, baseline, _BATTERY)) == pytest.approx(-0.18)


def test_end_soc_includes_the_last_rows_battery_action():
    optimized = [_row(50.0, action_kw=4.0, grid_kw=1.0)]
    baseline = [_row(50.0)]
    # 4 kW × 0.25 h × 0.9 = 0.9 kWh = 9 % on 10 kWh, valued at 0.9 × 20 ct.
    charged = soc_correction_increments_euro(optimized, baseline, _BATTERY)

    assert len(charged) == 1
    assert charged[0] > 0.0


def _run_savings(monkeypatch, *, initial_soc: float, baseline_soc: float | None) -> dict:
    """The real savings path; the "plan" is the vendor-mode run too, so only the start differs."""
    from optimizer.simulation import calculate_optimization_savings, simulate_baseline_horizon

    monkeypatch.setattr(config, "get_battery_params", lambda: dict(_BATTERY))
    monkeypatch.setattr(config, "get_flexible_consumers", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "optimizer.simulation.simulate_horizon",
        lambda matrix, soc, **_: simulate_baseline_horizon(matrix, soc),
    )
    matrix = [
        {
            "hour": hour,
            "expected_p_pv": 0.0,
            "expected_p_act": 2.0,
            "k_act": 20.0,
            "k_push_act": 5.0,
            "expected_flex_kw": {},
        }
        for hour in range(40)
    ]
    return calculate_optimization_savings(matrix, initial_soc, {}, baseline_initial_soc=baseline_soc)


def test_baselines_start_on_the_chain_and_the_plan_at_the_live_soc(monkeypatch):
    info = _run_savings(monkeypatch, initial_soc=60.0, baseline_soc=30.0)

    assert info["optimized_rows"][0]["Simulierter SoC (%)"] == 60.0
    for key in ("baseline_rows", "matched_baseline_rows", "baseline_same_flex_rows"):
        assert info[key][0]["Simulierter SoC (%)"] == 30.0


def test_plan_that_only_uses_its_start_energy_saves_about_nothing(monkeypatch):
    """Same behaviour, more energy at the start: the cost gap is the start energy, not a saving."""
    info = _run_savings(monkeypatch, initial_soc=60.0, baseline_soc=30.0)

    cost_gap = info["matched_baseline_cost_euro"] - info["optimized_cost_euro"]
    assert cost_gap > 0.4
    assert info["plan_soc_correction_euro"] == pytest.approx(-cost_gap, abs=0.08)
    assert info["savings_matched_euro"] == pytest.approx(0.0, abs=0.08)
    assert info["savings_euro"] == pytest.approx(0.0, abs=0.08)
    assert info["baseline_start_source"] == BASELINE_START_SHADOW_CHAIN
    assert info["baseline_start_soc_percent"] == 30.0
    assert sum(info["hourly_soc_correction_euro"]) == pytest.approx(info["plan_soc_correction_euro"], abs=0.01)


def test_without_a_chain_the_figures_stay_as_they_were(monkeypatch):
    info = _run_savings(monkeypatch, initial_soc=60.0, baseline_soc=None)

    assert info["baseline_start_source"] == BASELINE_START_LIVE_SOC
    assert "plan_soc_correction_euro" not in info
    assert "hourly_soc_correction_euro" not in info
    assert info["baseline_rows"][0]["Simulierter SoC (%)"] == 60.0
    assert info["savings_matched_euro"] == pytest.approx(0.0)


def test_snapshot_keeps_the_start_source_and_the_correction(monkeypatch):
    from runtime_store.live_display_loader import savings_info_from_snapshot
    from runtime_store.live_optimization_debug import _savings_summary

    info = _run_savings(monkeypatch, initial_soc=60.0, baseline_soc=30.0)

    restored = savings_info_from_snapshot({"savings": _savings_summary(info)})

    assert restored["baseline_start_source"] == BASELINE_START_SHADOW_CHAIN
    assert restored["plan_soc_correction_euro"] == info["plan_soc_correction_euro"]
    assert restored["hourly_soc_correction_euro"] == info["hourly_soc_correction_euro"]


def test_chart2_label_sums_the_correction_from_now_to_the_window_end():
    view = {"hourly_soc_correction_euro": [1.0, 2.0, 0.25, 0.25]}

    assert plan_soc_correction_eur(view, anchor=2) == pytest.approx(0.5)
    assert plan_soc_correction_eur({}, anchor=2) is None


# --- Daemon: where the chain stands once the closed slot is booked


@pytest.fixture
def ledger_files(tmp_path, monkeypatch):
    state_file = tmp_path / "savings_ledger_state.json"
    monkeypatch.setattr(store, "savings_ledger_state_file", lambda: str(state_file))
    monkeypatch.setattr(config, "get_battery_params_list", lambda: [dict(_BATTERY)])
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr(store, "sunrise_day_bounds", lambda *_a: lambda _m: (_DAY_START, _DAY_END))
    daemon.reset()
    yield state_file
    daemon.reset()


def _pending(slot_start: datetime) -> dict:
    return {"slot_start": slot_start.isoformat(), "k_act_cent": 20.0, "k_push_cent": 5.0}


def test_planning_shadow_soc_without_a_chain_is_none(ledger_files):
    assert daemon.planning_shadow_soc(_closed(_DAY_START, pv_kw=0.0, house_kw=1.0)) is None
    assert not ledger_files.exists()


def test_planning_shadow_soc_is_where_the_chain_stands_after_booking(ledger_files):
    start = _DAY_START + timedelta(minutes=15)
    store.save_state(_state([_slot(_DAY_START, 40.0)], shadow_soc=40.0, pending=_pending(start)))
    closed = _closed(start, pv_kw=0.0, house_kw=2.0)
    before = ledger_files.read_text(encoding="utf-8")

    planned = daemon.planning_shadow_soc(closed)

    assert planned < 40.0
    assert ledger_files.read_text(encoding="utf-8") == before
    daemon.on_cycle(closed, {}, now=start + timedelta(minutes=15))
    assert store.current_shadow_soc() == pytest.approx(planned)


def test_planning_shadow_soc_without_a_closed_slot_is_the_chain_as_it_stands(ledger_files):
    store.save_state(_state([_slot(_DAY_START, 40.0)], shadow_soc=40.0))

    assert daemon.planning_shadow_soc(None) == 40.0


def test_planning_shadow_soc_on_failure_counts_as_no_chain(ledger_files, monkeypatch, caplog):
    store.save_state(_state([_slot(_DAY_START, 40.0)], shadow_soc=40.0))
    monkeypatch.setattr(sl, "advance", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("boom")))

    start = _DAY_START + timedelta(minutes=15)
    assert daemon.planning_shadow_soc(_closed(start, pv_kw=0.0, house_kw=2.0)) is None
    assert "no shadow SoC" in caplog.text


def test_current_shadow_soc_without_a_state_is_none(tmp_path):
    assert store.current_shadow_soc(str(tmp_path / "missing.json")) is None
