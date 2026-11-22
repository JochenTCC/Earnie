"""Pure logic of the Szenario-Explorer result view (deviation list, calendar, display bundle,
run helpers). Render paths are covered in tests/apptest/test_backtesting_results_cov_apptest.py."""
from __future__ import annotations

import sys
from contextlib import nullcontext
from datetime import date, datetime

import pandas as pd
import pytest

import ui.backtesting  # noqa: F401  first: ui.backtesting imports ui.backtesting_results
from ui import backtesting_deviation_list as dl
from ui import backtesting_display_bundle as bundle_mod
from ui.backtesting_deviation_calendar import (
    CalendarCellState,
    _month_grid_weeks,
    _period_year_label,
    default_calendar_date,
)


class _FakeSt:
    """Stand-in for ``streamlit`` in pure helpers that only use session state / spinner."""

    def __init__(self) -> None:
        self.session_state: dict = {}

    @staticmethod
    def spinner(_text):
        return nullcontext()


# --- deviation list formatting ----------------------------------------------------


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        (None, "—"),
        ("", "—"),
        ("2026-06-25T07:00:00", "2026-06-25 07:00"),
        ("2026-06-25T07:00:00+02:00", "2026-06-25 07:00"),
        ("2026-06-25T05:00:00Z", "2026-06-25 05:00"),
        ("kein Anker", "kein Anker"),
    ],
)
def test_format_window_anchor(anchor, expected):
    assert dl._format_window_anchor(anchor) == expected


def test_format_consumer_targets_sorted_with_three_decimals():
    assert dl._format_consumer_targets(None) is None
    assert dl._format_consumer_targets({}) is None
    assert dl._format_consumer_targets({"wp": 1.5, "eauto": 0.25}) == (
        "eauto=0,250 kWh, wp=1,500 kWh"
    )


def test_scenario_label_and_option_label_with_marker():
    labels = {"live": "Live"}
    assert dl._scenario_label("live", labels) == "Live"
    assert dl._scenario_label("dyn", labels) == "dyn"
    assert dl._scenario_option_label("live", labels, None) == "Live"
    red = {"kind": "milp_no_optimal"}
    assert dl._scenario_option_label("live", labels, red) == "🔴 Live"
    feasible = {"kind": "strict_slow", "window_consumption_ok": True}
    assert dl._scenario_option_label("dyn", labels, feasible) == "⚪ dyn"


def test_scenario_options_put_deviations_first_keeping_order():
    options = dl._scenario_options_for_cell(
        ["a", "b", "c", "d"], {"c": {"kind": "x"}, "a": {"kind": "y"}}
    )
    assert options == ["a", "c", "b", "d"]


def test_run_anchors_cache_key_covers_period_run_and_fingerprint():
    meta = {
        "period": {"start": "2026-06-01", "end": "2026-06-30", "backtesting_year": 2026},
        "created_at": "2026-11-22T10:00:00",
        "config_fingerprint": "abc",
    }
    assert dl._run_anchors_cache_key(meta) == (
        "2026-06-01",
        "2026-06-30",
        "2026",
        "2026-11-22T10:00:00",
        "abc",
    )
    assert dl._run_anchors_cache_key({}) == ("None", "None", "None", "", "")


# --- run anchors (session cached) ----------------------------------------------------


def _hourly(start: str, hours: int, scenario_id: str = "live") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range(start, periods=hours, freq="h"),
            "scenario_id": [scenario_id] * hours,
        }
    )


@pytest.fixture
def fake_st(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(dl, "st", fake)
    return fake


def test_run_anchors_from_stored_anchors_are_cached_in_session(fake_st):
    meta = {
        "period": {
            "start": "2026-06-24",
            "end": "2026-06-25",
            "window_anchors": {
                "2026-06-24": "2026-06-25T00:00:00",
                "2026-06-25": "2026-06-26T00:00:00",
            },
        },
        "created_at": "run-1",
    }
    # Only the first window has booked rows in its 24 h.
    hourly = _hourly("2026-06-24", 24)
    anchors = dl._run_anchors_for_meta(meta, hourly)
    assert anchors == [datetime(2026, 6, 25)]
    cached = fake_st.session_state[dl._SESSION_RUN_ANCHORS_KEY]
    assert cached["key"] == dl._run_anchors_cache_key(meta)
    # Same run: the cached list wins even with another series.
    assert dl._run_anchors_for_meta(meta, _hourly("2026-06-24", 48)) == [datetime(2026, 6, 25)]
    # Another run (created_at) recomputes.
    meta2 = {**meta, "created_at": "run-2"}
    assert dl._run_anchors_for_meta(meta2, _hourly("2026-06-24", 48)) == [
        datetime(2026, 6, 25),
        datetime(2026, 6, 26),
    ]


def test_run_anchors_without_stored_anchors_come_from_hourly(fake_st, monkeypatch):
    monkeypatch.setattr(
        dl, "window_anchor_for_date", lambda day: datetime.combine(day, datetime.min.time()) + pd.Timedelta(days=1)
    )
    meta = {"period": {"start": "2026-06-24", "end": "2026-06-25"}}
    anchors = dl._run_anchors_for_meta(meta, _hourly("2026-06-24", 24))
    assert anchors == [datetime(2026, 6, 25)]
    assert fake_st.session_state[dl._SESSION_RUN_ANCHORS_KEY]["anchors"] == anchors


def test_run_anchors_fall_back_to_cons_data_scan(fake_st, monkeypatch):
    calls = []

    def _list(start, end, cache):
        calls.append((start, end))
        return [datetime(2026, 6, 25)]

    monkeypatch.setattr(dl, "HistoricalDataCache", lambda: "cache")
    monkeypatch.setattr(dl, "list_simulation_anchors", _list)
    meta = {"period": {"start": "2026-06-24", "end": "2026-06-24"}}
    # Only reference rows: the hourly series cannot tell the run's windows.
    hourly = _hourly("2026-06-24", 24, scenario_id="historical_reference")
    assert dl._run_anchors_for_meta(meta, hourly) == [datetime(2026, 6, 25)]
    assert calls == [(pd.Timestamp("2026-06-24 00:00:00"), pd.Timestamp("2026-06-24 23:59:59"))]


def test_run_anchors_via_cons_data_without_period_is_empty():
    assert dl._run_anchors_via_cons_data({}) == []


# --- calendar helpers -----------------------------------------------------------------


def test_month_grid_weeks_pads_to_full_weeks():
    june = _month_grid_weeks(2026, 6)  # 1 June 2026 is a Monday
    assert june[0] == [1, 2, 3, 4, 5, 6, 7]
    assert june[-1] == [29, 30, None, None, None, None, None]
    assert all(len(week) == 7 for week in june)
    feb = _month_grid_weeks(2021, 2)  # Monday 1st, 28 days: exactly four weeks
    assert len(feb) == 4 and feb[-1][-1] == 28
    nov = _month_grid_weeks(2025, 11)  # Saturday 1st
    assert nov[0] == [None, None, None, None, None, 1, 2]


def test_period_year_label():
    assert _period_year_label({"start": "2026-01-01", "end": "2026-12-31"}, {}) == "2026"
    assert _period_year_label({"start": "2025-10-01", "end": "2026-09-30"}, {}) == "2025–2026"
    assert _period_year_label({}, {1: 2024, 2: 2024}) == "2024"
    assert _period_year_label({}, {1: 2025, 12: 2024}) == "2024–2025"


def _cell(day: date, *, in_run: bool, cases: dict | None = None) -> CalendarCellState:
    return CalendarCellState(
        date=day, in_run=in_run, severity="none", cases_by_scenario=cases or {}
    )


def test_default_calendar_date_prefers_first_deviation_day():
    index = {
        date(2026, 6, 1): _cell(date(2026, 6, 1), in_run=True),
        date(2026, 6, 5): _cell(date(2026, 6, 5), in_run=True, cases={"live": {}}),
        date(2026, 6, 3): _cell(date(2026, 6, 3), in_run=True, cases={"live": {}}),
        # Out of run deviations do not count.
        date(2026, 5, 1): _cell(date(2026, 5, 1), in_run=False, cases={"live": {}}),
    }
    assert default_calendar_date(index) == date(2026, 6, 3)


def test_default_calendar_date_without_deviation_and_without_run_days():
    index = {
        date(2026, 6, 9): _cell(date(2026, 6, 9), in_run=True),
        date(2026, 6, 2): _cell(date(2026, 6, 2), in_run=True),
        date(2026, 6, 1): _cell(date(2026, 6, 1), in_run=False),
    }
    assert default_calendar_date(index) == date(2026, 6, 2)
    assert default_calendar_date({date(2026, 6, 1): _cell(date(2026, 6, 1), in_run=False)}) is None
    assert default_calendar_date({}) is None


# --- results helpers ------------------------------------------------------------------


def test_hourly_timestamps_for_scenario_filters_scenario_and_bounds():
    from ui.backtesting_results import _hourly_timestamps_for_scenario

    hourly = pd.concat(
        [_hourly("2026-06-23 22:00", 4, "live"), _hourly("2026-06-24", 2, "dyn")],
        ignore_index=True,
    )
    bounds = (datetime(2026, 6, 24), datetime(2026, 6, 24, 23, 59, 59))
    assert _hourly_timestamps_for_scenario(hourly, "live", bounds) == [
        "2026-06-24 00:00:00",
        "2026-06-24 01:00:00",
    ]
    assert len(_hourly_timestamps_for_scenario(hourly, "live", None)) == 4
    assert _hourly_timestamps_for_scenario(hourly, "missing", None) == []


def test_results_optimized_ids_need_a_house_profile():
    from ui.backtesting_results import _optimized_scenario_ids

    meta = {"reference_id": "historical_reference", "scenario_ids": ["historical_reference", "a", "b", "c"]}
    scenarios = {"a": {"_house_profile": {}}, "b": {"_house_profile": None}, "historical_reference": {"_house_profile": {}}}
    assert _optimized_scenario_ids(meta, scenarios) == ["a"]


def test_deviation_labels_map_log_labels_win(monkeypatch):
    from ui import backtesting_results as results

    monkeypatch.setattr(results, "scenario_labels_map", lambda: {"live": "Live (Config)", "dyn": "Dyn"})
    assert results._deviation_labels_map({"labels": {"live": "Live (Lauf)"}}) == {
        "live": "Live (Lauf)",
        "dyn": "Dyn",
    }
    assert results._deviation_labels_map({}) == {"live": "Live (Config)", "dyn": "Dyn"}


def test_format_config_error_adds_tariff_hint_only_for_tariff_ids():
    from ui.backtesting_run import _format_config_error

    tariff = _format_config_error("Szenario live: import_tariff_id 'x' fehlt")
    assert tariff.startswith("Szenario live: import_tariff_id 'x' fehlt\n\n")
    assert "Szenarienkonfigurator → Runtime" in tariff
    assert "Szenarienkonfigurator" in _format_config_error("export_tariff_id leer")
    assert _format_config_error("anderer Fehler") == "anderer Fehler"


# --- window diagnosis subprocess ------------------------------------------------------


def test_run_diag_single_window_returns_exit_code_and_joined_output():
    from ui.backtesting_diag_single_window import run_diag_single_window

    code, output = run_diag_single_window(
        [
            sys.executable,
            "-c",
            "import sys; print('aus stdout'); print('aus stderr', file=sys.stderr); sys.exit(3)",
        ],
        timeout_sec=60,
    )
    assert code == 3
    assert output.replace("\r\n", "\n") == "aus stdout\naus stderr"


# --- display bundle -------------------------------------------------------------------


def test_scenario_expects_multi_ess_soc(monkeypatch):
    import config

    scenarios = {
        "two": {"_planning_batteries": [{}, {}]},
        "one": {"_planning_batteries": [{}]},
        "none": {},
    }
    monkeypatch.setattr(config, "get_backtesting_scenarios", lambda: scenarios)
    assert bundle_mod._scenario_expects_multi_ess_soc("two") is True
    assert bundle_mod._scenario_expects_multi_ess_soc("one") is False
    assert bundle_mod._scenario_expects_multi_ess_soc("none") is False
    assert bundle_mod._scenario_expects_multi_ess_soc("missing") is False

    def _broken():
        raise ValueError("kaputt")

    monkeypatch.setattr(config, "get_backtesting_scenarios", _broken)
    assert bundle_mod._scenario_expects_multi_ess_soc("two") is False


def test_snapshot_missing_multi_ess_soc():
    missing = bundle_mod._snapshot_missing_multi_ess_soc
    assert missing({}) is True
    assert missing({"chart_rows_24h": [{"Simulierter SoC (%)": 50.0}]}) is True
    # chart_rows_full wins over chart_rows_24h.
    assert missing(
        {
            "chart_rows_full": [{"Simulierter SoC Haus (%)": 40.0, "Simulierter SoC Garage (%)": 60.0}],
            "chart_rows_24h": [{"Simulierter SoC (%)": 50.0}],
        }
    ) is False


def test_session_caches_are_created_once(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(bundle_mod, "st", fake)
    first = bundle_mod._on_demand_snapshot_cache()
    first[("k",)] = {"x": 1}
    assert bundle_mod._on_demand_snapshot_cache() is first
    fake.session_state[bundle_mod._BUNDLE_CACHE_KEY] = "kaputt"
    bundles = bundle_mod._display_bundle_cache()
    assert bundles == {} and fake.session_state[bundle_mod._BUNDLE_CACHE_KEY] is bundles


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []


@pytest.fixture
def bundle_env(monkeypatch):
    """Fake collaborators of ``resolve_backtesting_display_bundle``; records every call."""
    from simulation import backtesting_single_window as sw
    from simulation import backtesting_snapshots as snaps

    rec = _Recorder()
    state = {"existing": None, "multi": False, "loaded": "bundle-from-log", "stale": None}
    fake = _FakeSt()
    monkeypatch.setattr(bundle_mod, "st", fake)
    monkeypatch.setattr(bundle_mod, "standard_rules_series", lambda meta, hourly, sid: "rules")
    monkeypatch.setattr(bundle_mod, "load_window_snapshot", lambda log_dir, anchor, sid: state["existing"])
    monkeypatch.setattr(bundle_mod, "_scenario_expects_multi_ess_soc", lambda sid: state["multi"])

    def _load(log_dir, anchor, sid, **kwargs):
        rec.calls.append(("load", kwargs["view_mode"], kwargs["standard_rules"]))
        return state["loaded"]

    def _build(snapshot, **kwargs):
        rec.calls.append(("build", snapshot["id"], kwargs["view_mode"]))
        return f"bundle-of-{snapshot['id']}"

    def _simulate(anchor, sid, meta, *, initial_soc, horizon_mode):
        rec.calls.append(("simulate", sid, initial_soc, horizon_mode))
        return {"id": "on-demand"}

    monkeypatch.setattr(bundle_mod, "load_backtesting_display_bundle", _load)
    monkeypatch.setattr(bundle_mod, "build_backtesting_display_bundle", _build)
    monkeypatch.setattr(sw, "simulate_window_snapshot", _simulate)
    monkeypatch.setattr(sw, "initial_soc_for_anchor", lambda *a, **k: 42.0)
    monkeypatch.setattr(snaps, "append_window_snapshot", lambda d, s: rec.calls.append(("append", s["id"])))
    monkeypatch.setattr(snaps, "upsert_window_snapshot", lambda d, s: rec.calls.append(("upsert", s["id"])))
    import ui.backtesting as ui_backtesting

    monkeypatch.setattr(ui_backtesting, "log_stale_reason", lambda meta: state["stale"])
    return rec, state, fake


_META = {"period": {"horizon_mode": "fixed_24h"}, "created_at": "run-1"}


def _resolve(**kwargs):
    return bundle_mod.resolve_backtesting_display_bundle(
        "logdir", "2026-06-25T00:00:00", "live", _META, pd.DataFrame(), **kwargs
    )


def test_resolve_uses_stored_snapshot_and_caches_bundle(bundle_env):
    rec, state, fake = bundle_env
    state["existing"] = {"id": "stored", "chart_rows_24h": [{"x": 1}]}
    assert _resolve() == "bundle-from-log"
    assert _resolve() == "bundle-from-log"
    assert rec.calls == [("load", "24h", "rules")]
    assert len(fake.session_state[bundle_mod._BUNDLE_CACHE_KEY]) == 1


def test_resolve_simulates_missing_window_once_and_appends_it(bundle_env):
    rec, _state, fake = bundle_env
    assert _resolve() == "bundle-of-on-demand"
    # Another view of the same window: new bundle, but the simulated window is reused.
    assert _resolve(view_mode=bundle_mod.VIEW_MODE_SUNRISE, segment_index=1) == "bundle-of-on-demand"
    assert rec.calls == [
        ("simulate", "live", 42.0, "fixed_24h"),
        ("append", "on-demand"),
        ("build", "on-demand", "24h"),
        ("build", "on-demand", bundle_mod.VIEW_MODE_SUNRISE),
    ]
    assert len(fake.session_state[bundle_mod._ON_DEMAND_CACHE_KEY]) == 1


def test_resolve_replaces_stored_window_without_multi_ess_soc(bundle_env):
    rec, state, _fake = bundle_env
    state["existing"] = {"id": "stored", "chart_rows_24h": [{"Simulierter SoC (%)": 50.0}]}
    state["multi"] = True
    assert _resolve() == "bundle-of-on-demand"
    assert ("load", "24h", "rules") not in rec.calls
    assert ("upsert", "on-demand") in rec.calls
    assert not any(call[0] == "append" for call in rec.calls)


def test_resolve_falls_back_to_simulation_when_stored_bundle_is_none(bundle_env):
    rec, state, _fake = bundle_env
    state["existing"] = {"id": "stored", "chart_rows_24h": [{"x": 1}]}
    state["loaded"] = None
    assert _resolve() == "bundle-of-on-demand"
    assert [call[0] for call in rec.calls] == ["load", "simulate", "append", "build"]


def test_resolve_refuses_on_demand_window_for_stale_log(bundle_env):
    rec, state, fake = bundle_env
    state["stale"] = "mismatch"
    with pytest.raises(ValueError, match="kein gespeicherter Plan"):
        _resolve()
    assert rec.calls == []
    assert fake.session_state[bundle_mod._BUNDLE_CACHE_KEY] == {}
