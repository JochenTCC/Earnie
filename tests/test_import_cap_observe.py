"""Observe mode of the import cap (max-power tariff P6d-1): shadow plan, hypothetical peak, replay."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

import main as main_module
from house_config.import_cap import (
    MODE_OBSERVE,
    MODE_OPTIMIZE,
    parse_import_cap_mode,
)
from optimizer import import_cap_report as icr
from optimizer import milp
from optimizer.live_import_cap import resolve_live_import_caps
from runtime_store import capacity_peak_store, cycle_recorder
from runtime_store import import_cap_report_store as store
from runtime_store import recorder_replay as rr
from tests.test_capacity_charge import _charge, _params
from tests.test_import_cap_report import _closed
from tests.test_milp_import_cap import _battery, _caps, _rows

SLOT = datetime(2027, 3, 2, 18, 0)
OBSERVE = {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3, "import_cap_mode": MODE_OBSERVE}


def _shift_rows() -> list[dict]:
    """Cheap now, dear later: without the cap Earnie buys now and keeps the battery for later."""
    rows = _rows([4.0, 4.0, 3.0, 3.0, 3.0, 3.0])
    for row, price in zip(rows, [5.0, 5.0, 40.0, 40.0, 40.0, 40.0]):
        row["k_act"] = price
    return rows


def _optimize(rows, *, caps=None, observe=False):
    return milp.milp_optimizer(
        rows, rows[0]["hour"], 50.0, battery_params=_battery(), k_push=5.0, verbose=False,
        consumers=[], import_caps=caps, import_cap_observe=observe,
    )


# --- the mode setting ------------------------------------------------------------------------


def test_live_needs_a_mode_once_a_cap_is_set():
    cap = {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3}
    with pytest.raises(ValueError, match="import_cap_mode fehlt"):
        parse_import_cap_mode(cap, required=True)
    assert parse_import_cap_mode(cap, required=False) is None
    assert parse_import_cap_mode({**cap, "import_cap_mode": "observe"}, required=True) == MODE_OBSERVE
    assert parse_import_cap_mode({}, required=True) is None


def test_a_mode_without_a_cap_or_an_unknown_mode_is_an_error():
    with pytest.raises(ValueError, match="ohne import_cap_kw"):
        parse_import_cap_mode({"import_cap_mode": "observe"}, required=False)
    with pytest.raises(ValueError, match="ungültig"):
        parse_import_cap_mode(
            {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3, "import_cap_mode": "watch"},
            required=False,
        )


def test_the_scenario_check_refuses_a_bad_mode_but_not_a_missing_one(tmp_path):
    from house_config.scenario_resolution import _check_import_cap

    params = {**_params(tmp_path, [_charge()]), "import_cap_kw": 5.0, "import_cap_margin_kw": 0.3}
    _check_import_cap(params)
    with pytest.raises(ValueError, match="ungültig"):
        _check_import_cap({**params, "import_cap_mode": "maybe"})


# --- shadow plan in milp_optimizer -----------------------------------------------------------


def test_observe_executes_the_plan_without_the_cap_and_reports_the_one_with_it():
    rows = _shift_rows()
    caps = _caps(rows, 2.0)
    free = _optimize(rows)
    observed = _optimize(rows, caps=caps, observe=True)
    assert observed[:5] == free[:5]
    assert observed[5]["p_grid_buy"] == pytest.approx(free[5]["p_grid_buy"])
    assert observed[5]["p_grid_buy"] == pytest.approx(4.0, abs=1e-3)
    report = observed[5]["import_cap_report"]
    assert report["mode"] == MODE_OBSERVE
    assert report["planned"] is True
    block = report["observe"]
    assert block["slot"] == "2027-01-12T16:00"
    assert block["executed"]["import_kw"] == pytest.approx(4.0, abs=1e-3)
    assert block["shadow"]["import_kw"] == pytest.approx(2.0, abs=1e-3)
    assert block["delta_import_kw"] == pytest.approx(-2.0, abs=1e-3)
    assert block["shadow"]["battery_kw"] > block["executed"]["battery_kw"]
    assert block["energy_cost_extra_eur"] > 0.0


def test_optimize_plans_under_the_cap_and_has_no_observe_block():
    rows = _shift_rows()
    result = _optimize(rows, caps=_caps(rows, 2.0))
    assert result[5]["p_grid_buy"] == pytest.approx(2.0, abs=1e-3)
    report = result[5]["import_cap_report"]
    assert report["mode"] == MODE_OPTIMIZE
    assert "observe" not in report


def test_a_failed_shadow_solve_leaves_the_executed_plan(monkeypatch, caplog):
    rows = _shift_rows()
    free = _optimize(rows)
    original = milp._solve_milp_to_model

    def no_capped_solve(*args, **kwargs):
        return None if kwargs.get("import_caps") is not None else original(*args, **kwargs)

    monkeypatch.setattr(milp, "_solve_milp_to_model", no_capped_solve)
    with caplog.at_level(logging.WARNING):
        observed = _optimize(rows, caps=_caps(rows, 2.0), observe=True)
    assert observed[:5] == free[:5]
    report = observed[5]["import_cap_report"]
    assert (report["planned"], report["reason"]) == (False, icr.NOT_PLANNED_SHADOW)
    assert report["observe"]["delta_import_kw"] is None
    assert "Beobachtungsmodus" in caplog.text


@pytest.mark.parametrize(
    ("trivial", "reason", "delta"),
    [(True, icr.NOT_PLANNED_TRIVIAL, 0.0), (False, icr.NOT_PLANNED_AUTOMATIK, None)],
    ids=["trivial", "no solve"],
)
def test_trivial_window_and_automatik_in_observe_mode(monkeypatch, caplog, trivial, reason, delta):
    monkeypatch.setattr(milp, "_try_trivial_milp_skip", lambda *_a, **_k: object() if trivial else None)
    monkeypatch.setattr(milp, "_solve_milp_to_model", lambda *_a, **_k: None)
    rows = _rows([1.0])
    with caplog.at_level(logging.WARNING):
        result = milp.milp_optimizer(
            rows, 16, 50.0, battery_params={"max_power_kw": 5.0}, import_caps=_caps(rows, 4.7),
            import_cap_observe=True,
        )
    report = result[5]["import_cap_report"]
    assert (report["mode"], report["reason"]) == (MODE_OBSERVE, reason)
    assert report["observe"]["delta_import_kw"] == delta
    assert "nicht eingeplant" not in caplog.text


def test_shadow_failed_exists_only_in_observe_mode():
    rows = _rows([1.0])
    with pytest.raises(ValueError, match="Beobachtungsmodus"):
        icr.not_planned_report(_caps(rows, 2.0), rows, icr.NOT_PLANNED_SHADOW)
    with pytest.raises(ValueError, match="Modus"):
        icr.not_planned_report(_caps(rows, 2.0), rows, icr.NOT_PLANNED_TRIVIAL, mode="watch")


# --- Live caps in observe mode -----------------------------------------------------------------


def _matrix(start: datetime, slots: int) -> list[dict]:
    return [{"slot_datetime": start + timedelta(minutes=15 * i)} for i in range(slots)]


def test_observe_mode_plans_the_shadow_with_the_hypothetical_peak(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    params = {**_params(tmp_path, [_charge()]), **OBSERVE}
    capacity_peak_store.record_slot(SLOT, 9.0, "counter")  # the real peak: not for the shadow
    capacity_peak_store.record_slot(SLOT, 5.6, "x", path=capacity_peak_store.observe_path())
    ctx = resolve_live_import_caps(_matrix(SLOT + timedelta(minutes=15), 2), params=params)
    assert ctx["mode"] == MODE_OBSERVE
    assert ctx["peak_by_month"] == {"2027-03": 5.6}
    assert ctx["import_caps"].limits_kw == (pytest.approx(5.3), pytest.approx(5.3))


def test_live_without_a_mode_fails_loud(tmp_path):
    params = {**_params(tmp_path, [_charge()]), "import_cap_kw": 5.0, "import_cap_margin_kw": 0.3}
    with pytest.raises(ValueError, match="import_cap_mode fehlt"):
        resolve_live_import_caps(_matrix(SLOT, 1), params=params, read_peak=lambda _m: None)


# --- hypothetical quarter hours ----------------------------------------------------------------


def _observe_plan(slot: datetime, delta: float | None, *, slots=()) -> dict:
    return {
        "schema": icr.REPORT_SCHEMA,
        "mode": MODE_OBSERVE,
        "planned": delta is not None,
        "reason": None if delta is not None else icr.NOT_PLANNED_SHADOW,
        "first_slot": slot.isoformat(timespec="minutes"),
        "limits_kw": {"2027-03": 4.7},
        "slots": list(slots),
        "months": {},
        "observe": {
            "slot": slot.isoformat(timespec="minutes"),
            "delta_import_kw": delta,
            "executed": None if delta is None else {"import_kw": 7.0, "battery_kw": 0.0, "consumers_kw": {}},
            "shadow": None if delta is None else {"import_kw": 7.0 + delta, "battery_kw": -delta, "consumers_kw": {}},
            "energy_cost_extra_eur": None if delta is None else 0.12,
        },
    }


@pytest.fixture
def observed(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    params = {**_params(tmp_path, [_charge()]), **OBSERVE}
    return params, str(tmp_path / "report.json"), str(tmp_path / "observe_peaks.json")


def _baseline(month: str = "2027-03"):
    return capacity_peak_store.month_peak(month, path=capacity_peak_store.observe_baseline_path())


def test_the_quarter_hour_gets_the_plan_delta(observed):
    params, path, peaks = observed
    over = {"slot": "2027-03-02T18:00", "cause": icr.CAUSE_BATTERY_ENERGY}
    store.save_plan_report(_observe_plan(SLOT, -1.5, slots=[over]), path=path)
    event = store.record_observed(SLOT.isoformat(), 7.0, params=params, path=path, peak_path=peaks)
    assert event["import_kw"] == pytest.approx(5.5)
    assert event["measured_kw"] == 7.0
    assert event["hypothetical"] is True
    assert event["cause"] == icr.CAUSE_BATTERY_ENERGY
    peak = capacity_peak_store.month_peak("2027-03", path=peaks)
    assert peak.peak_kw == pytest.approx(5.5)
    assert peak.peak_source == store.OBSERVE_PEAK_SOURCE
    assert (_baseline().peak_kw, _baseline().peak_source) == (7.0, store.OBSERVE_BASELINE_SOURCE)
    [step] = store.load(path)["interventions"]["2027-03"]
    assert step["delta_kw"] == -1.5
    assert step["hypothetical_kw"] == pytest.approx(5.5)
    assert step["shadow"]["import_kw"] == pytest.approx(5.5)
    assert step["cause"] == icr.CAUSE_BATTERY_ENERGY


def test_the_hypothetical_peak_lifts_the_threshold_not_the_real_one(observed):
    params, path, peaks = observed
    store.save_plan_report(_observe_plan(SLOT, -1.0), path=path)
    first = store.record_observed(SLOT.isoformat(), 7.0, params=params, path=path, peak_path=peaks)
    assert first["threshold_kw"] == pytest.approx(5.0)
    later = SLOT + timedelta(minutes=15)
    store.save_plan_report(_observe_plan(later, -0.5), path=path)
    assert store.record_observed(later.isoformat(), 6.4, params=params, path=path, peak_path=peaks) is None
    peak = capacity_peak_store.month_peak("2027-03", path=peaks)
    assert (peak.peak_kw, peak.slots_logged) == (pytest.approx(6.0), 2)


def test_without_the_plan_of_that_quarter_hour_it_is_missing(observed):
    params, path, peaks = observed
    store.save_plan_report(_observe_plan(SLOT, -1.0), path=path)
    store.record_observed(SLOT.isoformat(), 4.0, params=params, path=path, peak_path=peaks)
    later = SLOT + timedelta(minutes=15)
    assert store.record_observed(later.isoformat(), 9.0, params=params, path=path, peak_path=peaks) is None
    store.save_plan_report(_observe_plan(later + timedelta(minutes=15), None), path=path)
    last = later + timedelta(minutes=15)
    assert store.record_observed(last.isoformat(), 9.0, params=params, path=path, peak_path=peaks) is None
    peak = capacity_peak_store.month_peak("2027-03", path=peaks)
    assert (peak.peak_kw, peak.slots_logged, peak.slots_missing) == (pytest.approx(3.0), 1, 2)
    baseline = _baseline()
    assert (baseline.peak_kw, baseline.slots_logged, baseline.slots_missing) == (4.0, 1, 2)
    assert [e["slot"] for e in store.load(path)["interventions"]["2027-03"]] == ["2027-03-02T18:00"]


def test_an_unmeasured_quarter_hour_is_missing_and_the_import_never_negative(observed):
    params, path, peaks = observed
    store.save_plan_report(_observe_plan(SLOT, -3.0), path=path)
    assert store.record_observed(SLOT.isoformat(), 1.0, params=params, path=path, peak_path=peaks) is None
    assert capacity_peak_store.month_peak("2027-03", path=peaks).peak_kw == 0.0
    later = SLOT + timedelta(minutes=15)
    store.save_plan_report(_observe_plan(later, -1.0), path=path)
    assert store.record_observed(later.isoformat(), None, params=params, path=path, peak_path=peaks) is None
    assert capacity_peak_store.month_peak("2027-03", path=peaks).slots_missing == 1


def test_an_optimize_report_gives_no_delta(observed):
    params, path, peaks = observed
    report = {**_observe_plan(SLOT, -1.0), "mode": MODE_OPTIMIZE}
    store.save_plan_report(report, path=path)
    assert store.record_observed(SLOT.isoformat(), 9.0, params=params, path=path, peak_path=peaks) is None
    assert capacity_peak_store.month_peak("2027-03", path=peaks) is None


def test_the_live_hook_uses_the_hypothetical_quarter_hour(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    params = {**_params(tmp_path, [_charge()]), **OBSERVE}
    monkeypatch.setattr(main_module.config, "get_resolved_runtime_settings", lambda: params)
    store.save_plan_report(_observe_plan(SLOT, -0.5))
    with caplog.at_level(logging.WARNING):
        main_module._record_month_peak(_closed(SLOT, 5.8))
    assert "Bezugsgrenze (Beobachtung): Viertelstunde 2027-03-02T18:00 mit Earnie geschätzt 5.30 kW" in caplog.text
    assert capacity_peak_store.month_peak("2027-03").peak_kw == 5.8
    observe_peak = capacity_peak_store.month_peak("2027-03", path=capacity_peak_store.observe_path())
    assert observe_peak.peak_kw == pytest.approx(5.3)


def test_the_cycle_logs_the_observed_plan(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    with caplog.at_level(logging.INFO):
        main_module._save_import_cap_report(_observe_plan(SLOT, -1.5))
    assert "mit Grenze würde Earnie ab 2027-03-02T18:00 5.50 kW statt 7.00 kW beziehen" in caplog.text


# --- cycle record and replay -------------------------------------------------------------------


def test_the_cycle_record_keeps_the_mode():
    token = cycle_recorder.CycleToken.__new__(cycle_recorder.CycleToken)
    token.start_state = {}
    caps = _caps(_rows([1.0]), 2.0)
    cycle_recorder.record_import_caps(
        token, {"import_caps": caps, "mode": MODE_OBSERVE, "peak_by_month": {}, "unknown_months": []}
    )
    assert token.start_state["import_caps"]["mode"] == MODE_OBSERVE
    assert rr._recorded_import_cap_observe(token.start_state) is True


def test_records_from_before_p6d_replay_as_optimize_and_a_bad_mode_fails_loud():
    legacy = {"import_caps": {"limits_kw": [2.0], "months": ["2027-01"]}}
    assert rr._recorded_import_cap_observe(legacy) is False
    assert rr._recorded_import_cap_observe({}) is False
    with pytest.raises(ValueError, match="unknown mode"):
        rr._recorded_import_cap_observe({"import_caps": {"mode": "watch"}})


def _replay_ctx(rows, caps, observe: bool) -> rr._PreparedReplay:
    return rr._PreparedReplay(
        prepared=rows, contexts={}, filter_contexts={}, remaining={}, consumers=[],
        battery_params=_battery(), soc=50.0, soc_by_id=None, current_hour=rows[0]["hour"],
        continue_on={}, inverter_params=None, pv_systems=None, k_push=5.0,
        import_caps=caps, import_cap_observe=observe,
    )


def test_replay_of_an_observed_cycle_executes_without_the_cap(monkeypatch):
    monkeypatch.setattr(rr, "_apply_recorded_standby_relief", lambda _ctx: None)
    rows = _shift_rows()
    caps = _caps(rows, 2.0)
    free = rr._run_milp_replay(_replay_ctx(rows, None, False), verbose=False, sunrise_soc_min_index=None)
    observed = rr._run_milp_replay(_replay_ctx(rows, caps, True), verbose=False, sunrise_soc_min_index=None)
    capped = rr._run_milp_replay(_replay_ctx(rows, caps, False), verbose=False, sunrise_soc_min_index=None)
    assert observed.plan_hash == free.plan_hash
    assert capped.plan_hash != free.plan_hash
    assert observed.import_cap_report["mode"] == MODE_OBSERVE
    assert observed.import_cap_report["observe"]["delta_import_kw"] == pytest.approx(-2.0, abs=1e-3)
    assert capped.import_cap_report["mode"] == MODE_OPTIMIZE


def test_a_broken_report_file_fails_loud(tmp_path: Path):
    path = tmp_path / "report.json"
    path.write_text('{"measured": {}, "interventions": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="interventions"):
        store.load(str(path))
