"""Import cap report (max-power tariff P6a): slots over the limit, causes, Live store, measured check."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

import main as main_module
from optimizer import import_cap_report as icr
from optimizer import milp
from optimizer.import_power_limit import ImportCaps
from runtime_store import cycle_recorder
from runtime_store import import_cap_report_store as store
from runtime_store.power_interval_sampler import GRID_IMPORT_SOURCE_COUNTER
from tests.test_capacity_charge import _charge, _params
from tests.test_milp_import_cap import _battery, _caps, _ev, _rows, _solve


def _report(rows, caps, **kwargs) -> dict:
    remaining = kwargs.get("remaining")
    model = _solve(rows, caps, **kwargs)
    return icr.report_from_model(model, rows, caps, remaining)


# --- causes from the solved model ----------------------------------------------------------


def test_a_plan_that_holds_reports_no_slot():
    rows = _rows([0.5, 4.0, 0.5, 0.5])
    report = _report(rows, _caps(rows, 3.0), soc=100.0)
    assert report["planned"] is True
    assert report["slots"] == []
    assert report["months"] == {}
    assert report["limits_kw"] == {"2027-01": 3.0}
    assert report["first_slot"] == "2027-01-12T16:00"


def test_load_above_the_limit_with_full_battery_power_is_base_load():
    rows = _rows([0.5, 9.0, 0.5, 0.5])
    report = _report(rows, _caps(rows, 2.0), battery=_battery(max_power_kw=1.0), soc=100.0)
    [slot] = report["slots"]
    assert slot["slot"] == "2027-01-12T16:15"
    assert slot["over_kw"] == pytest.approx(6.0, abs=1e-3)
    assert slot["limit_kw"] == 2.0
    assert slot["cause"] == icr.CAUSE_BASE_LOAD
    assert icr.CAUSE_BATTERY_POWER in slot["causes"]
    assert report["months"] == {"2027-01": {"slots_over": 1, "max_over_kw": 6.0}}


def test_a_battery_that_runs_empty_is_battery_energy():
    """4 kW for an hour over a 2 kW limit: 2 kWh needed, the battery holds 1 kWh above its floor."""
    rows = _rows([4.0] * 4 + [0.5] * 2)
    battery = _battery(battery_capacity_kwh=10.0, min_soc=10.0, max_power_kw=5.0, efficiency=1.0)
    report = _report(rows, _caps(rows, 2.0), battery=battery, soc=20.0)
    assert report["slots"]
    assert {slot["cause"] for slot in report["slots"]} == {icr.CAUSE_BATTERY_ENERGY}


def test_a_consumer_with_a_target_and_no_battery_is_consumer_target():
    rows = _rows([0.5] * 4)
    report = _report(
        rows,
        _caps(rows, 2.0),
        battery=_battery(battery_capacity_kwh=0.0, max_power_kw=0.0),
        consumers=[_ev()],
        remaining={"eauto": 8.0},
    )
    assert report["slots"]
    for slot in report["slots"]:
        assert slot["causes"] == [icr.CAUSE_CONSUMER_TARGET]
        assert slot["consumers_kw"]["eauto"] > 0.0


def test_a_consumer_next_to_a_battery_at_full_power_names_both():
    rows = _rows([0.5] * 4)
    report = _report(
        rows,
        _caps(rows, 2.0),
        battery=_battery(max_power_kw=1.0),
        soc=100.0,
        consumers=[_ev()],
        remaining={"eauto": 8.0},
    )
    assert report["slots"]
    for slot in report["slots"]:
        assert slot["cause"] == icr.CAUSE_BATTERY_POWER
        assert icr.CAUSE_CONSUMER_TARGET in slot["causes"]


def test_a_model_without_a_cap_has_no_report():
    rows = _rows([1.0] * 2)
    model = _solve(rows, None)
    with pytest.raises(ValueError, match="keine Bezugsgrenze"):
        icr.report_from_model(model, rows, _caps(rows, 2.0), {})


def test_not_planned_needs_a_known_reason():
    rows = _rows([1.0])
    with pytest.raises(ValueError, match="unbekannter Grund"):
        icr.not_planned_report(_caps(rows, 2.0), rows, "other")


# --- milp_optimizer -------------------------------------------------------------------------


def test_the_optimizer_plan_carries_the_report():
    rows = _rows([9.0, 0.5, 0.5, 0.5])
    result = milp.milp_optimizer(
        rows, rows[0]["hour"], 100.0, battery_params=_battery(max_power_kw=1.0), k_push=5.0,
        verbose=False, consumers=[], import_caps=_caps(rows, 2.0),
    )
    report = result[5]["import_cap_report"]
    assert report["slots"][0]["slot"] == "2027-01-12T16:00"
    assert report["slots"][0]["cause"] == icr.CAUSE_BASE_LOAD


def test_without_a_cap_the_plan_has_no_report():
    rows = _rows([9.0, 0.5])
    result = milp.milp_optimizer(
        rows, rows[0]["hour"], 100.0, battery_params=_battery(), k_push=5.0, verbose=False,
        consumers=[],
    )
    assert "import_cap_report" not in result[5]


@pytest.mark.parametrize(
    ("trivial", "reason"),
    [(True, icr.NOT_PLANNED_TRIVIAL), (False, icr.NOT_PLANNED_AUTOMATIK)],
    ids=["trivial", "no solve"],
)
def test_trivial_window_and_automatik_say_the_cap_was_not_planned(monkeypatch, trivial, reason):
    monkeypatch.setattr(milp, "_try_trivial_milp_skip", lambda *_a, **_k: object() if trivial else None)
    monkeypatch.setattr(milp, "_solve_milp_to_model", lambda *_a, **_k: None)
    rows = _rows([1.0])
    result = milp.milp_optimizer(
        rows, 16, 50.0, battery_params={"max_power_kw": 5.0}, import_caps=_caps(rows, 4.7)
    )
    report = result[5]["import_cap_report"]
    assert report["planned"] is False
    assert report["reason"] == reason
    assert "import_cap_report" not in milp.EMPTY_MILP_PLAN


# --- cycle record --------------------------------------------------------------------------


def test_the_cycle_record_keeps_the_report():
    token = cycle_recorder.CycleToken.__new__(cycle_recorder.CycleToken)
    token.timestamp = "2027-01-12T16:00:00"
    token.app_version = "test"
    token.config_hash = "x"
    token.optimization_matrix = []
    token.planning_window = None
    token.start_state = {}
    report = {"schema": 1, "planned": False, "reason": "automatik", "slots": []}
    entry = cycle_recorder._build_cycle_entry(
        token, setpoints=None, plan_hash="h", flags=None, mode=0, target_power_kw=0.0,
        battery_plan_kw=None, consumer_powers_kw={}, import_cap_report=report,
    )
    assert entry["outputs"]["import_cap_report"] == report
    without = cycle_recorder._build_cycle_entry(
        token, setpoints=None, plan_hash="h", flags=None, mode=0, target_power_kw=0.0,
        battery_plan_kw=None, consumer_powers_kw={},
    )
    assert "import_cap_report" not in without["outputs"]


# --- Live store ----------------------------------------------------------------------------

SLOT = datetime(2027, 3, 2, 18, 0)
CAP = {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3}


@pytest.fixture
def capped(tmp_path):
    return {**_params(tmp_path, [_charge()]), **CAP}


def _plan(first: datetime, *, planned=True, slots=()) -> dict:
    return {
        "schema": 1,
        "planned": planned,
        "reason": None if planned else icr.NOT_PLANNED_AUTOMATIK,
        "first_slot": first.isoformat(timespec="minutes"),
        "limits_kw": {"2027-03": 4.7},
        "slots": list(slots),
        "months": {},
    }


def test_no_cap_writes_no_file_and_a_removed_cap_clears_the_report(tmp_path: Path):
    path = str(tmp_path / "report.json")
    store.save_plan_report(None, path=path)
    assert not Path(path).exists()
    store.save_plan_report(_plan(SLOT), path=path)
    assert store.load(path)["plan"]["first_slot"] == "2027-03-02T18:00"
    store.save_plan_report(None, path=path)
    assert store.load(path)["plan"] is None


def test_a_measured_quarter_hour_within_the_cap_is_no_event(tmp_path: Path, capped):
    path = str(tmp_path / "report.json")
    assert store.record_measured(SLOT.isoformat(), 4.9, params=capped, peak_before_kw=None, path=path) is None
    assert store.record_measured(SLOT.isoformat(), None, params=capped, peak_before_kw=None, path=path) is None
    assert not Path(path).exists()


def test_without_a_cap_nothing_is_checked(tmp_path: Path):
    params = _params(tmp_path, [_charge()])
    assert store.record_measured(SLOT.isoformat(), 9.0, params=params, peak_before_kw=None,
                                 path=str(tmp_path / "r.json")) is None


def test_the_plan_held_and_the_meter_did_not_is_forecast(tmp_path: Path, capped):
    path = str(tmp_path / "report.json")
    store.save_plan_report(_plan(SLOT), path=path)
    event = store.record_measured(SLOT.isoformat(), 5.6, params=capped, peak_before_kw=None, path=path)
    assert event == {
        "slot": "2027-03-02T18:00",
        "import_kw": 5.6,
        "threshold_kw": 5.0,
        "over_kw": pytest.approx(0.6),
        "cause": icr.CAUSE_FORECAST,
        "planned": False,
    }
    assert store.load(path)["measured"]["2027-03"][0]["cause"] == icr.CAUSE_FORECAST


def test_a_slot_the_plan_already_had_over_keeps_the_plan_cause(tmp_path: Path, capped):
    path = str(tmp_path / "report.json")
    planned_slot = {"slot": "2027-03-02T18:00", "cause": icr.CAUSE_BATTERY_ENERGY}
    store.save_plan_report(_plan(SLOT, slots=[planned_slot]), path=path)
    event = store.record_measured(SLOT.isoformat(), 6.0, params=capped, peak_before_kw=None, path=path)
    assert event["cause"] == icr.CAUSE_BATTERY_ENERGY
    assert event["planned"] is True


def test_automatik_and_an_unknown_plan_are_named(tmp_path: Path, capped):
    path = str(tmp_path / "report.json")
    store.save_plan_report(_plan(SLOT, planned=False), path=path)
    event = store.record_measured(SLOT.isoformat(), 6.0, params=capped, peak_before_kw=None, path=path)
    assert event["cause"] == icr.CAUSE_NOT_PLANNED
    later = SLOT + timedelta(minutes=15)
    event = store.record_measured(later.isoformat(), 6.0, params=capped, peak_before_kw=None, path=path)
    assert event["cause"] == icr.CAUSE_NONE


def test_the_month_peak_before_lifts_the_threshold(tmp_path: Path, capped):
    path = str(tmp_path / "report.json")
    assert store.record_measured(SLOT.isoformat(), 6.0, params=capped, peak_before_kw=6.2, path=path) is None
    event = store.record_measured(SLOT.isoformat(), 6.5, params=capped, peak_before_kw=6.2, path=path)
    assert event["threshold_kw"] == pytest.approx(6.2)


def test_only_two_months_are_kept(tmp_path: Path, capped):
    path = str(tmp_path / "report.json")
    for month in (1, 2, 3):
        slot = datetime(2027, month, 2, 18, 0)
        store.record_measured(slot.isoformat(), 6.0, params=capped, peak_before_kw=None, path=path)
    assert sorted(store.load(path)["measured"]) == ["2027-02", "2027-03"]


def test_a_broken_file_fails_loud(tmp_path: Path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"measured": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="measured"):
        store.load(str(path))


# --- Live cycle hooks ----------------------------------------------------------------------


def _closed(slot: datetime, kw: float) -> dict:
    opened = slot + timedelta(seconds=30)
    return {
        "interval_start": slot.isoformat(),
        "sample_count": 30,
        "grid_import_kw": kw,
        "grid_import_source": GRID_IMPORT_SOURCE_COUNTER,
        "grid_import_start": opened.isoformat(),
        "grid_import_end": (opened + timedelta(seconds=870)).isoformat(),
    }


def test_a_closed_quarter_hour_over_the_cap_is_logged(monkeypatch, caplog, tmp_path: Path, capped):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    monkeypatch.setattr(main_module.config, "get_resolved_runtime_settings", lambda: capped)
    with caplog.at_level(logging.WARNING):
        main_module._record_month_peak(_closed(SLOT, 5.8))
    assert "Bezugsgrenze: Viertelstunde 2027-03-02T18:00 gemessen 5.80 kW" in caplog.text
    assert store.load()["measured"]["2027-03"][0]["cause"] == icr.CAUSE_NONE


def test_the_check_uses_the_peak_before_the_quarter_hour(monkeypatch, tmp_path: Path, capped):
    """The first quarter hour sets the peak; checked against the cap, not against itself."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    monkeypatch.setattr(main_module.config, "get_resolved_runtime_settings", lambda: capped)
    main_module._record_month_peak(_closed(SLOT, 5.8))
    main_module._record_month_peak(_closed(SLOT + timedelta(minutes=15), 5.7))
    events = store.load()["measured"]["2027-03"]
    assert [e["slot"] for e in events] == ["2027-03-02T18:00"]


def test_a_failing_check_does_not_stop_the_cycle(monkeypatch, caplog, tmp_path: Path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))

    def broken():
        raise RuntimeError("no settings")

    monkeypatch.setattr(main_module.config, "get_resolved_runtime_settings", broken)
    with caplog.at_level(logging.WARNING):
        main_module._record_month_peak(_closed(SLOT, 5.8))
    assert "import_cap_report: 2027-03-02T18:00:00 not checked: no settings" in caplog.text


def test_the_cycle_saves_and_logs_the_plan_report(monkeypatch, caplog, tmp_path: Path):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    report = _plan(SLOT, slots=[{
        "slot": "2027-03-02T18:15", "month": "2027-03", "import_kw": 6.0, "limit_kw": 4.7,
        "over_kw": 1.3, "cause": icr.CAUSE_BASE_LOAD, "causes": [icr.CAUSE_BASE_LOAD],
        "consumers_kw": {},
    }])
    with caplog.at_level(logging.WARNING):
        main_module._save_import_cap_report(report)
    assert store.load()["plan"] == report
    assert "Plan hält 1 Viertelstunde(n) nicht, erste 2027-03-02T18:15" in caplog.text


def test_an_inverter_ac_limit_below_the_battery_power_is_battery_power():
    """5 kW battery behind a 2 kW battery inverter, EV with a target: the inverter binds."""
    from optimizer.milp import _solve_milp_to_model

    rows = _rows([0.5] * 4)
    caps = _caps(rows, 2.0)
    battery = {**_battery(max_power_kw=5.0), "id": "ess", "inverter_id": "wr1"}
    inverter = {"id": "wr1", "type": "battery", "ac_connection": "grid_tied", "max_ac_power_kw": 2.0}
    solved = _solve_milp_to_model(
        rows, 100.0, [battery], 5.0, False, [_ev()], {"eauto": 8.0},
        None, None, {}, None, None, None, None, None,
        current_soc_by_id={"ess": 100.0},
        inverter_params=[inverter],
        pv_systems=[{"id": "pv", "inverter_id": "wr1"}],
        import_caps=caps,
    )
    assert solved is not None
    report = icr.report_from_model(solved[0], rows, caps, {"eauto": 8.0})
    assert report["slots"]
    for slot in report["slots"]:
        assert slot["cause"] == icr.CAUSE_BATTERY_POWER
        assert icr.CAUSE_BASE_LOAD not in slot["causes"]
