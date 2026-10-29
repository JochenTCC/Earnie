"""Optimisation (profile_spec) load must match the hourly reference load per consumer."""
from __future__ import annotations

from datetime import datetime, timedelta

from house_config.profiles_store import normalize_house_profiles_document
from simulation.load_consistency import profile_spec_vs_reference

_ANCHORS = [datetime(2025, 10, 1, 7) + timedelta(days=i) for i in range(7)]


def _profile(consumers: list[dict]) -> dict:
    raw = {"id": "home", "label": "Home", "annual_kwh": 20000.0, "netznutzung": {"area_id": "user_no_grid_fee"}, "consumers": consumers}
    return normalize_house_profiles_document({"profiles": [raw]})["profiles"]["home"]


def _manual(
    cid: str,
    nominal: float,
    duration_h: float,
    start_hour: int,
    shift_h: float,
    runs_per_week: int = 7,
) -> dict:
    return {
        "id": cid,
        "label": cid,
        "type": "generic",
        "nominal_power_kw": nominal,
        "earnie_role": "manual",
        "schedule": {
            "runs_per_week": runs_per_week,
            "duration_h": duration_h,
            "start_hour": start_hour,
            "start_shift_h": shift_h,
        },
    }


def test_deliverable_schedule_is_consistent():
    profile = _profile([_manual("trockner", 1.0, 2.0, 16, 4.0)])
    report = profile_spec_vs_reference(profile, _ANCHORS)
    assert report["status"] == "ok", report["message"]
    assert report["reference_kwh"] > 0.0
    assert abs(report["deviation_rel"]) <= 0.03


def test_run_that_does_not_fit_into_the_day_is_named():
    # 24 h run on 5 of 7 days starting at 12:00 (+6 h shift) cannot finish on the same
    # day and is no continuous load (not every weekday) → named as deviation.
    profile = _profile(
        [_manual("server", 0.12, 24.0, 12, 6.0, runs_per_week=5), _manual("trockner", 1.0, 2.0, 16, 4.0)]
    )
    report = profile_spec_vs_reference(profile, _ANCHORS, tolerance=0.001)
    assert report["status"] == "deviation"
    assert "server" in report["message"]
    assert "trockner" not in report["message"]
    rows = {cid: (ref, spec) for cid, ref, spec in report["consumers"]}
    assert rows["server"][1] < rows["server"][0] * 0.6


def test_continuous_load_is_consistent_with_the_reference():
    # 24 h on every weekday = continuous load: booked as fixed load, same as the reference.
    profile = _profile([_manual("dev-pc", 0.12, 24.0, 12, 6.0), _manual("trockner", 1.0, 2.0, 16, 4.0)])
    report = profile_spec_vs_reference(profile, _ANCHORS, tolerance=0.001)
    assert report["status"] == "ok", report["message"]
    rows = {cid: (ref, spec) for cid, ref, spec in report["consumers"]}
    assert abs(rows["dev-pc"][1] - rows["dev-pc"][0]) < 0.01


def test_cli_gate_aborts_on_stale_cons_data_and_can_be_overridden(monkeypatch, caplog):
    import pytest as _pytest

    from data import cons_data_store

    monkeypatch.setattr(
        cons_data_store, "cons_data_consumer_match_reason", lambda path=None: "profile_mismatch"
    )
    with _pytest.raises(SystemExit, match="profile_mismatch"):
        cons_data_store.ensure_cons_data_current(allow_stale=False)
    with caplog.at_level("WARNING"):
        cons_data_store.ensure_cons_data_current(allow_stale=True)
    assert "--allow-stale-cons-data" in caplog.text
    monkeypatch.setattr(
        cons_data_store, "cons_data_consumer_match_reason", lambda path=None: None
    )
    cons_data_store.ensure_cons_data_current(allow_stale=False)  # no raise
