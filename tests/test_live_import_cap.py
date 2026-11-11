"""Import cap in Live (max-power tariff P5b): limits, cycle record, replay, Automatik report."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

import main as main_module
from optimizer import milp
from optimizer.import_power_limit import ImportCaps
from optimizer.live_import_cap import resolve_live_import_caps
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
from runtime_store import cycle_recorder
from runtime_store import recorder_replay as rr
from runtime_store.capacity_peak_store import MonthPeak
from tests.main_run_harness import patch_main_run
from tests.test_capacity_charge import _charge, _params

CAP = {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3}


def _matrix(start: datetime, slots: int) -> list[dict]:
    return [{"slot_datetime": start + timedelta(minutes=15 * i)} for i in range(slots)]


def _peak(kw: float) -> MonthPeak:
    return MonthPeak("2027-03", kw, "2027-03-02T18:00:00", "counter", "2027-03-01T00:00:00",
                     "2027-03-02T18:00:00", 150, 0)


@pytest.fixture
def capped(tmp_path):
    return {**_params(tmp_path, [_charge()]), **CAP}


def test_without_a_cap_the_peak_store_is_not_read(tmp_path):
    ctx = resolve_live_import_caps(
        _matrix(datetime(2027, 3, 2, 18), 4),
        params=_params(tmp_path, [_charge()]),
        read_peak=lambda _m: pytest.fail("no cap, no peak needed"),
    )
    assert ctx == {"import_caps": None, "peak_by_month": {}, "unknown_months": []}


def test_the_month_peak_lifts_the_limit(capped):
    ctx = resolve_live_import_caps(
        _matrix(datetime(2027, 3, 2, 18), 2), params=capped, read_peak=lambda _m: _peak(6.2)
    )
    assert ctx["import_caps"] == ImportCaps((5.9, 5.9), ("2027-03", "2027-03"))
    assert ctx["peak_by_month"] == {"2027-03": 6.2}
    assert ctx["unknown_months"] == []


def test_an_unknown_month_holds_the_cap_and_is_named(capped):
    """After an install or a month change without a measured slot, the plan holds the cap itself."""
    ctx = resolve_live_import_caps(
        _matrix(datetime(2027, 3, 31, 23, 30), 4),
        params=capped,
        read_peak=lambda month: _peak(6.2) if month == "2027-03" else None,
    )
    assert ctx["import_caps"].limits_kw == (5.9, 5.9, 4.7, 4.7)
    assert ctx["import_caps"].months == ("2027-03", "2027-03", "2027-04", "2027-04")
    assert ctx["unknown_months"] == ["2027-04"]


def test_the_cycle_record_replays_the_limits_it_planned_with():
    caps = ImportCaps((4.7, None), ("2027-04", None))
    token = cycle_recorder.CycleToken.__new__(cycle_recorder.CycleToken)
    token.start_state = {}
    cycle_recorder.record_import_caps(
        token, {"import_caps": caps, "peak_by_month": {"2027-03": 6.2}, "unknown_months": ["2027-04"]}
    )
    assert token.start_state["import_caps"] == {
        "limits_kw": [4.7, None],
        "months": ["2027-04", None],
        "peak_by_month": {"2027-03": 6.2},
        "unknown_months": ["2027-04"],
    }
    assert rr._recorded_import_caps(token.start_state) == caps


def test_replay_of_a_cycle_without_a_cap_or_from_before_p5b_has_none():
    without = {"import_caps": {"limits_kw": None, "months": None, "peak_by_month": {}, "unknown_months": []}}
    assert rr._recorded_import_caps(without) is None
    assert rr._recorded_import_caps({}) is None


def test_a_broken_cycle_record_fails_loud():
    with pytest.raises(ValueError, match="months"):
        rr._recorded_import_caps({"import_caps": {"limits_kw": [4.7]}})
    with pytest.raises(ValueError, match="one length"):
        rr._recorded_import_caps({"import_caps": {"limits_kw": [4.7], "months": []}})


@pytest.mark.parametrize(
    ("trivial", "reason"),
    [(True, "trivial window"), (False, "Automatik")],
    ids=["trivial", "no solve"],
)
def test_a_plan_that_cannot_hold_the_cap_says_so(monkeypatch, caplog, trivial, reason):
    monkeypatch.setattr(milp, "_try_trivial_milp_skip", lambda *_a, **_k: object() if trivial else None)
    monkeypatch.setattr(milp, "_solve_milp_to_model", lambda *_a, **_k: None)
    with caplog.at_level(logging.WARNING):
        milp.milp_optimizer(
            [{"slot_datetime": datetime(2027, 4, 1, 18)}], 18, 50.0, battery_params={"max_power_kw": 5.0},
            import_caps=ImportCaps((4.7,), ("2027-04",)),
        )
    assert "Bezugsgrenze (4.70 kW) nicht eingeplant" in caplog.text
    assert reason in caplog.text


def test_the_live_cycle_plans_and_records_with_the_limits(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    caps = ImportCaps((4.7,), ("2027-04",))
    seen: dict = {}
    recorded: list = []

    def fake_milp(*_a, **kwargs):
        seen["import_caps"] = kwargs.get("import_caps")
        return (0, 0.0, 99.0, {}, {}, {}, {})

    monkeypatch.setattr(main_module.optimizer, "milp_optimizer", fake_milp)
    monkeypatch.setattr(
        "optimizer.live_import_cap.resolve_live_import_caps",
        lambda _matrix: {"import_caps": caps, "peak_by_month": {}, "unknown_months": ["2027-04"]},
    )
    monkeypatch.setattr(
        main_module.cycle_recorder, "record_import_caps", lambda _token, ctx: recorded.append(ctx)
    )
    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)
    assert seen["import_caps"] is caps
    assert recorded[0]["unknown_months"] == ["2027-04"]
