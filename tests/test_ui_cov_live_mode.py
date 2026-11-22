"""Coverage: Live-Modus opt-in simulation and snapshot bundle plumbing (``ui.live_mode``).

The module talks to Streamlit only through ``st.session_state`` / ``st.error``; a fake ``st``
records both. Planning inputs, the optimizer and the debug persistence are monkeypatched —
no MILP runs, no network, no runtime files.
"""
from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ui import live_mode
from ui import simulation_results
from ui.simulation_results import SESSION_LIVE_DISPLAY_BUNDLE

_NOW = datetime(2026, 7, 5, 10, 30, tzinfo=ZoneInfo("Europe/Vienna"))


class _FakeSt:
    def __init__(self) -> None:
        self.session_state: dict = {}
        self.errors: list[str] = []

    def error(self, text: str) -> None:
        self.errors.append(text)


@pytest.fixture
def fake_st(monkeypatch) -> _FakeSt:
    fake = _FakeSt()
    monkeypatch.setattr(live_mode, "st", fake)
    monkeypatch.setattr(live_mode, "get_s2_cycle_offset", lambda: 2)
    monkeypatch.setattr(live_mode, "get_s2_segment_index", lambda: 1)
    monkeypatch.setattr(live_mode, "get_s2_span", lambda: "segment")
    monkeypatch.setattr(live_mode, "live_now", lambda: _NOW)
    monkeypatch.setattr(live_mode, "simulation_settings_fingerprint", lambda: "fp")
    return fake


# --- main.py sync notice ----------------------------------------------------------------


def test_main_py_sync_notice_renders_the_status_with_help(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        live_mode,
        "render_status_with_help",
        lambda message, help_text, *, key, prominent: calls.append(
            (message, help_text, key, prominent)
        ),
    )
    live_mode._render_main_py_sync_notice(30, 90, "wait_main", key="k1", prominent=True)
    (message, help_text, key, prominent) = calls[0]
    assert "spätestens in 30 s" in message
    assert "max. **90 s**" in message
    assert help_text == live_mode.MAIN_PY_SYNC_HELP
    assert (key, prominent) == ("k1", True)


# --- snapshot bundle ----------------------------------------------------------------------


def test_store_bundle_from_snapshot_passes_navigation_and_stores_bundle(fake_st, monkeypatch) -> None:
    seen: dict = {}

    def _build(snapshot, **kwargs):
        seen.update(kwargs, snapshot=snapshot)
        return "BUNDLE"

    monkeypatch.setattr(live_mode, "build_optimization_display_bundle_from_snapshot", _build)
    assert live_mode._store_bundle_from_snapshot({"id": 1}) is True
    assert fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] == "BUNDLE"
    assert seen == {
        "snapshot": {"id": 1},
        "cycle_offset": 2,
        "segment_index": 1,
        "now": _NOW,
        "span": "segment",
    }


def test_store_bundle_from_snapshot_without_rows_drops_the_old_bundle(fake_st, monkeypatch) -> None:
    fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] = "OLD"
    monkeypatch.setattr(
        live_mode, "build_optimization_display_bundle_from_snapshot", lambda *a, **k: None
    )
    assert live_mode._store_bundle_from_snapshot({}) is False
    assert SESSION_LIVE_DISPLAY_BUNDLE not in fake_st.session_state


def test_refresh_snapshot_bundle_caches_by_key(fake_st, monkeypatch) -> None:
    builds: list[dict] = []

    def _build(snapshot, **kwargs):
        builds.append(snapshot)
        return f"B{len(builds)}"

    monkeypatch.setattr(live_mode, "build_optimization_display_bundle_from_snapshot", _build)
    live_mode._refresh_snapshot_bundle({"s": 1}, "key-a")
    assert fake_st.session_state[live_mode.SESSION_SNAPSHOT_CACHE_KEY] == "key-a"
    assert fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] == "B1"
    live_mode._refresh_snapshot_bundle({"s": 1}, "key-a")  # same key: no rebuild
    assert len(builds) == 1
    live_mode._refresh_snapshot_bundle({"s": 2}, "key-b")
    assert fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] == "B2"
    assert fake_st.session_state[live_mode.SESSION_SNAPSHOT_CACHE_KEY] == "key-b"


def test_refresh_snapshot_bundle_without_snapshot_clears_the_bundle(fake_st) -> None:
    fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] = "OLD"
    live_mode._refresh_snapshot_bundle(None, "key")
    assert SESSION_LIVE_DISPLAY_BUNDLE not in fake_st.session_state


def test_refresh_snapshot_bundle_keeps_key_unset_when_nothing_was_built(fake_st, monkeypatch) -> None:
    monkeypatch.setattr(
        live_mode, "build_optimization_display_bundle_from_snapshot", lambda *a, **k: None
    )
    live_mode._refresh_snapshot_bundle({"s": 1}, "key")
    assert live_mode.SESSION_SNAPSHOT_CACHE_KEY not in fake_st.session_state


# --- opt-in display bundle ------------------------------------------------------------


def _capture_bundle_build(monkeypatch) -> dict:
    seen: dict = {}

    def _ctx(cycle, segment, **kwargs):
        seen["ctx"] = (cycle, segment, kwargs)
        return "CTX"

    def _bundle(savings, optimized, baseline, matched, **kwargs):
        seen["bundle"] = (savings, optimized, baseline, matched, kwargs)
        return "OPT_IN_BUNDLE"

    monkeypatch.setattr(live_mode, "build_live_chart_context", _ctx)
    monkeypatch.setattr(live_mode, "build_optimization_display_bundle", _bundle)
    return seen


def test_store_opt_in_display_bundle(fake_st, monkeypatch) -> None:
    seen = _capture_bundle_build(monkeypatch)
    optimized = pd.DataFrame([{"Uhrzeit": "10:00", "Simulierter SoC (%)": 50.0}])
    live_mode._store_opt_in_display_bundle(
        {"x": 1}, optimized, pd.DataFrame(), None, [{"m": 1}], "PW"
    )
    assert fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] == "OPT_IN_BUNDLE"
    cycle, segment, kwargs = seen["ctx"]
    assert (cycle, segment) == (2, 1)
    assert kwargs["planning_window"] == "PW"
    assert kwargs["sim_rows"] == [{"Uhrzeit": "10:00", "Simulierter SoC (%)": 50.0}]
    assert kwargs["now"] == _NOW
    *_, bundle_kwargs = seen["bundle"]
    assert bundle_kwargs == {
        "chart_context": "CTX",
        "optimization_matrix": [{"m": 1}],
        "show_soc_plausibility": True,
    }


def test_restore_cached_opt_in_bundle_rebuilds_from_session(fake_st, monkeypatch) -> None:
    seen = _capture_bundle_build(monkeypatch)
    cached_df = pd.DataFrame([{"Uhrzeit": "10:00"}])
    fake_st.session_state.update(
        {
            "live_savings_info": {
                "baseline_rows": [{"a": 1}],
                "matched_baseline_rows": [{"b": 2}],
            },
            "live_optimization_df": cached_df,
            "live_optimization_matrix": ["M"],
            "live_planning_window": "PW",
        }
    )
    live_mode._restore_cached_opt_in_bundle()
    savings, optimized, baseline, matched, kwargs = seen["bundle"]
    assert optimized is cached_df
    assert baseline.to_dict("records") == [{"a": 1}]
    assert matched.to_dict("records") == [{"b": 2}]
    assert kwargs["optimization_matrix"] == ["M"]
    assert seen["ctx"][2]["planning_window"] == "PW"
    assert fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] == "OPT_IN_BUNDLE"


# --- planning inputs --------------------------------------------------------------------


def _planning(monkeypatch, *, market, matrix_exc: Exception | None = None):
    window = SimpleNamespace(end="END")
    monkeypatch.setattr(live_mode.profile_manager, "compute_live_planning_window", lambda: window)
    monkeypatch.setattr(
        live_mode, "fetch_live_day_ahead_prices", lambda planning_end: market
    )

    def _matrix(market_data, planning_window):
        if matrix_exc is not None:
            raise matrix_exc
        return [{"price": market_data[0]}]

    monkeypatch.setattr(live_mode.profile_manager, "build_live_planning_matrix", _matrix)
    return window


def test_opt_in_planning_inputs_ok(fake_st, monkeypatch) -> None:
    window = _planning(monkeypatch, market=[12.5])
    assert live_mode._opt_in_planning_inputs() == (window, [{"price": 12.5}])
    assert fake_st.errors == []


def test_opt_in_planning_inputs_without_prices_aborts(fake_st, monkeypatch) -> None:
    _planning(monkeypatch, market=[])
    fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] = "OLD"
    assert live_mode._opt_in_planning_inputs() is None
    assert "Börsenstrompreise" in fake_st.errors[0]
    assert SESSION_LIVE_DISPLAY_BUNDLE not in fake_st.session_state


def test_opt_in_planning_inputs_without_pv_forecast_aborts(fake_st, monkeypatch) -> None:
    from data.pv_forecast import PvForecastUnavailableError

    _planning(monkeypatch, market=[1.0], matrix_exc=PvForecastUnavailableError("kein PV"))
    fake_st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] = "OLD"
    assert live_mode._opt_in_planning_inputs() is None
    assert fake_st.errors == ["🚨 Planung nicht möglich: kein PV"]
    assert SESSION_LIVE_DISPLAY_BUNDLE not in fake_st.session_state


def test_opt_in_planning_inputs_without_consumption_profile_aborts(fake_st, monkeypatch) -> None:
    exc = live_mode.profile_manager.ConsumptionProfileUnavailableError("kein Profil")
    _planning(monkeypatch, market=[1.0], matrix_exc=exc)
    assert live_mode._opt_in_planning_inputs() is None
    assert "kein Profil" in fake_st.errors[0]


# --- consumption snapshot ---------------------------------------------------------------


def _live_fetch(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        live_mode.live_consumption,
        "fetch_live_consumption_snapshot",
        lambda state: calls.append(state) or "LIVE",
    )
    return calls


def test_opt_in_consumption_snapshot_reuses_a_fresh_main_snapshot(monkeypatch) -> None:
    calls = _live_fetch(monkeypatch)
    monkeypatch.setattr(live_mode.run_state, "age_seconds", lambda state: 60)
    state = {"consumption_snapshot": {"flex_kw": 1.0}}
    assert live_mode._opt_in_consumption_snapshot(state) == {"flex_kw": 1.0}
    assert calls == []


def test_opt_in_consumption_snapshot_reads_live_when_stale_or_missing(monkeypatch) -> None:
    calls = _live_fetch(monkeypatch)
    limit = live_mode.optimization_schedule.QUARTER_HOUR_SECONDS * 1.5
    monkeypatch.setattr(live_mode.run_state, "age_seconds", lambda state: limit + 1)
    state = {"consumption_snapshot": {"flex_kw": 1.0}}
    assert live_mode._opt_in_consumption_snapshot(state) == "LIVE"
    monkeypatch.setattr(live_mode.run_state, "age_seconds", lambda state: None)
    assert live_mode._opt_in_consumption_snapshot(state) == "LIVE"
    assert live_mode._opt_in_consumption_snapshot(None) == "LIVE"
    assert live_mode._opt_in_consumption_snapshot({"consumption_snapshot": None}) == "LIVE"
    assert len(calls) == 4


def test_store_opt_in_session_state_clears_the_confirmation(fake_st) -> None:
    fake_st.session_state[live_mode.SESSION_OPT_IN_SIMULATION] = True
    df = pd.DataFrame([{"a": 1}])
    live_mode._store_opt_in_session_state(
        "ck", optimized_df=df, savings_info={"s": 1}, matrix=["m"], planning_window="PW"
    )
    state = fake_st.session_state
    assert state["live_opt_in_cache_key"] == "ck"
    assert state["live_optimization_df"] is df
    assert state["live_savings_info"] == {"s": 1}
    assert state["live_optimization_matrix"] == ["m"]
    assert state["live_planning_window"] == "PW"
    assert live_mode.SESSION_OPT_IN_SIMULATION not in state


# --- the opt-in run itself -------------------------------------------------------------


@pytest.fixture
def opt_in_run(fake_st, monkeypatch):
    """Everything around ``calculate_optimization_savings`` patched; returns the recorder."""
    rec: dict = {"persist": [], "display": [], "applied": []}
    window = SimpleNamespace(end="END")
    matrix = [{"slot": 0, "k": 1.0}]
    monkeypatch.setattr(live_mode, "_opt_in_planning_inputs", lambda: (window, list(matrix)))
    monkeypatch.setattr(
        "data.planning_window.sunrise_anchor_slot_index", lambda pw: 7, raising=True
    )
    monkeypatch.setattr(live_mode, "_opt_in_consumption_snapshot", lambda state: {"snap": 1})
    monkeypatch.setattr(
        live_mode.live_consumption, "reject_live_matrix_snapshot_reason", lambda snap: None
    )

    def _apply(m, snap, *, hour_index):
        rec["applied"].append((snap, hour_index))
        return [dict(row, live=True) for row in m]

    monkeypatch.setattr(live_mode.live_consumption, "apply_live_snapshot_to_matrix", _apply)
    monkeypatch.setattr(
        live_mode.consumer_targets,
        "resolve_consumer_daily_targets",
        lambda *, matrix: {"pool": 3.0},
    )
    monkeypatch.setattr(live_mode.savings_ledger_store, "current_shadow_soc", lambda: 33.0)

    def _calc(m, soc, **kwargs):
        rec["calc"] = (m, soc, kwargs)
        return {
            "optimized_rows": [{"Uhrzeit": "10:00", "Simulierter SoC (%)": soc}],
            "baseline_rows": [{"Uhrzeit": "10:00"}],
            "matched_baseline_rows": [{"Uhrzeit": "10:00", "m": 1}],
        }

    monkeypatch.setattr(live_mode.optimizer, "calculate_optimization_savings", _calc)
    monkeypatch.setattr(
        live_mode.optimizer,
        "overlay_main_run_on_rows",
        lambda rows, state: [dict(row, overlay=True) for row in rows],
    )
    monkeypatch.setattr(
        live_mode,
        "_store_opt_in_display_bundle",
        lambda *args: rec["display"].append(args),
    )
    monkeypatch.setattr(
        live_mode, "persist_simulation_debug", lambda *a, **k: rec["persist"].append((a, k))
    )
    rec["window"] = window
    return rec


def test_run_opt_in_live_simulation_full_path(fake_st, opt_in_run) -> None:
    fake_st.session_state[live_mode.SESSION_OPT_IN_SIMULATION] = True
    main_state = {"completed_at": "2026-07-05T09:00:00", "soc_percent": 61.0}
    live_mode._run_opt_in_live_simulation(40.0, main_state, "2026-07-05T10:30", "main_down")

    m, soc, kwargs = opt_in_run["calc"]
    assert soc == 61.0  # SOC of the last main run wins over the live SOC
    assert m == [{"slot": 0, "k": 1.0, "live": True}]  # live snapshot applied to hour 0
    assert opt_in_run["applied"] == [({"snap": 1}, 0)]
    assert kwargs == {
        "consumer_daily_targets_kwh": {"pool": 3.0},
        "sunrise_soc_min_index": 7,
        "baseline_initial_soc": 33.0,
    }
    state = fake_st.session_state
    assert state["live_opt_in_cache_key"] == "opt_in|2026-07-05T10:30|2026-07-05T09:00:00|fp"
    assert state["live_optimization_df"].iloc[0]["overlay"]  # main run overlaid
    assert live_mode.SESSION_OPT_IN_SIMULATION not in state
    assert len(opt_in_run["display"]) == 1

    (args, persist_kwargs), = opt_in_run["persist"]
    assert persist_kwargs["kind"] == "live"
    assert persist_kwargs["initial_soc"] == 61.0
    assert persist_kwargs["sync_reason"] == "main_down"
    assert persist_kwargs["quarter_hour_slot"] == "2026-07-05T10:30"
    assert "overlay" not in persist_kwargs["optimized_df_raw"].columns  # raw kept separately
    assert persist_kwargs["matched_baseline_df"].to_dict("records") == [{"Uhrzeit": "10:00", "m": 1}]


def test_run_opt_in_live_simulation_without_main_state(fake_st, opt_in_run, monkeypatch) -> None:
    monkeypatch.setattr(
        live_mode.live_consumption,
        "reject_live_matrix_snapshot_reason",
        lambda snap: "stale",
    )
    live_mode._run_opt_in_live_simulation(40.0, None, "slot", "main_down")
    m, soc, _ = opt_in_run["calc"]
    assert soc == 40.0  # live SOC
    assert m == [{"slot": 0, "k": 1.0}]  # rejected snapshot leaves the matrix alone
    assert "overlay" not in fake_st.session_state["live_optimization_df"].columns


def test_run_opt_in_live_simulation_stops_without_planning_inputs(fake_st, opt_in_run, monkeypatch) -> None:
    monkeypatch.setattr(live_mode, "_opt_in_planning_inputs", lambda: None)
    live_mode._run_opt_in_live_simulation(40.0, None, "slot", "main_down")
    assert "calc" not in opt_in_run
    assert opt_in_run["persist"] == []


def test_run_opt_in_live_simulation_reuses_a_valid_cache(fake_st, opt_in_run, monkeypatch) -> None:
    restored: list = []
    monkeypatch.setattr(live_mode, "_restore_cached_opt_in_bundle", lambda: restored.append(1))
    fake_st.session_state.update(
        {
            "live_opt_in_cache_key": "opt_in|slot||fp",
            "live_optimization_df": pd.DataFrame([{"a": 1}]),
            "live_savings_info": {},
        }
    )
    live_mode._run_opt_in_live_simulation(40.0, None, "slot", "main_down")
    assert restored == [1]
    assert "calc" not in opt_in_run


# --- simulation_results.persist_simulation_debug ---------------------------------------


def test_persist_simulation_debug_builds_and_saves_the_payload(monkeypatch) -> None:
    saved: list = []
    monkeypatch.setattr(
        simulation_results.live_optimization_debug,
        "save_debug_snapshot",
        lambda payload, *, kind: saved.append((payload, kind)),
    )
    savings = {
        "optimized_cost_euro": 1.0,
        "baseline_cost_euro": 1.5,
        "matched_baseline_rows": [{"Uhrzeit": "10:00", "x": 2}],
        "baseline_same_flex_rows": [{"Uhrzeit": "10:00", "y": 3}],
    }
    simulation_results.persist_simulation_debug(
        savings,
        pd.DataFrame([{"Uhrzeit": "10:00", "Simulierter SoC (%)": 50.0}]),
        pd.DataFrame([{"Uhrzeit": "10:00"}]),
        kind="live",
        initial_soc=50.0,
        quarter_hour_slot="2026-07-05T10:00",
        sync_reason="main_down",
        optimized_df_raw=pd.DataFrame([{"Uhrzeit": "10:00", "raw": 1}]),
    )
    (payload, kind), = saved
    assert kind == "live"
    text = repr(payload)
    # matched rows come from savings_info when no frame is passed
    assert "'x': 2" in text
    assert "'raw': 1" in text
    assert "main_down" in text


def test_persist_simulation_debug_logs_instead_of_raising(monkeypatch, caplog) -> None:
    def _boom(payload, *, kind):
        raise OSError("disk full")

    monkeypatch.setattr(simulation_results.live_optimization_debug, "save_debug_snapshot", _boom)
    with caplog.at_level(logging.WARNING, logger="app"):
        simulation_results.persist_simulation_debug(
            {}, pd.DataFrame(), pd.DataFrame(), kind="live", initial_soc=10.0
        )
    assert "disk full" in caplog.text


def test_slot_quality_label() -> None:
    from runtime_store.history_timeline import SLOT_MISSING, SLOT_PRESENT
    from ui.chart_context import SLOT_MILP

    assert simulation_results._slot_quality_label(SLOT_PRESENT) == "Produktiv-Log"
    assert simulation_results._slot_quality_label(SLOT_MISSING) == "fehlend"
    assert simulation_results._slot_quality_label(SLOT_MILP) == "MILP"
    assert simulation_results._slot_quality_label("other") == "other"
