"""Per-case overrides and extra metrics of the L2 regression runner (Cases P0)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from tests.fixtures.backtesting_fixtures import FIXTURES_ROOT
from tests.regression import l2_runner
from tests.regression.l2_case_inputs import (
    COMPONENTS_ENV,
    HOUSE_PROFILES_ENV,
    SCENARIOS_ENV,
    case_inputs,
    consumer_metric_ids,
    deep_merge,
    write_case_config,
)
from tests.regression.loader import RegressionCase

os.environ.setdefault("EARNIE_OFFLINE", "1")

CHARGE = {
    "id": "lp_case",
    "basis": "monthly_peak_15min",
    "min_kw": 2.0,
    "bands": [{"up_to_kw": None, "cent_per_kw_month": 300}],
}


def _meta(**inputs) -> dict:
    return {
        "id": "REG-S-t",
        "window": {"start": "2026-01-14", "end": "2026-01-14"},
        "inputs": {"kind": "backtesting_fixtures", **inputs},
    }


# --- inputs validation -------------------------------------------------------------


def test_unknown_input_key_fails_loud():
    with pytest.raises(ValueError, match="unknown inputs keys"):
        case_inputs(_meta(import_cap_kw=5.0), "REG-S-t")


def test_capacity_charges_need_the_case_grid_area():
    with pytest.raises(ValueError, match="needs grid_fee_base_cent_kwh"):
        case_inputs(_meta(grid_capacity_charges=[CHARGE]), "REG-S-t")


def test_consumer_metric_ids():
    assert consumer_metric_ids({}, "c") == ()
    assert consumer_metric_ids({"extra_metrics": {"consumer_kwh": ["wp"]}}, "c") == ("wp",)
    with pytest.raises(ValueError, match="unknown extra_metrics"):
        consumer_metric_ids({"extra_metrics": {"rod": ["x"]}}, "c")
    with pytest.raises(TypeError):
        consumer_metric_ids({"extra_metrics": {"consumer_kwh": "wp"}}, "c")
    priced = {"extra_metrics": {"consumer_kwh": ["wp"], "consumer_price_ct": ["wp", "rod"]}}
    assert consumer_metric_ids(priced, "c", "consumer_price_ct") == ("wp", "rod")


# --- patched fixture files --------------------------------------------------------


def test_no_overrides_writes_nothing(tmp_path):
    assert write_case_config({}, tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c") == {}
    assert list(tmp_path.iterdir()) == []


def test_scenario_settings_patch_the_selected_scenario(tmp_path):
    paths = write_case_config(
        {"scenario_settings": {"house_profile_id": "test_home", "import_cap_kw": 5.0,
                               "import_cap_margin_kw": 0.3, "battery_capacity_kwh": 8.0}},
        tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
    )
    doc = json.loads(paths[SCENARIOS_ENV].read_text(encoding="utf-8"))
    settings = next(s for s in doc["scenarios"] if s["id"] == "fixture_5kwh_fixed")["settings"]
    assert settings["house_profile_id"] == "test_home"
    assert settings["import_cap_kw"] == 5.0
    assert settings["battery_capacity_kwh"] == 8.0
    assert settings["pv_kwp"] == 6.0  # untouched
    assert HOUSE_PROFILES_ENV not in paths


def test_scenario_settings_reject_keys_the_scenario_does_not_have(tmp_path):
    with pytest.raises(ValueError, match="pv_kwpp"):
        write_case_config(
            {"scenario_settings": {"pv_kwpp": 7.0}},
            tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
        )


def test_unknown_scenario_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="not in the fixture"):
        write_case_config(
            {"scenario_id": "nope", "scenario_settings": {}},
            tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
        )


def test_house_profile_patch_needs_a_profile_on_the_scenario(tmp_path):
    with pytest.raises(ValueError, match="needs a house_profile_id"):
        write_case_config(
            {"house_profile_patch": {"persons": 3}},
            tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
        )


def test_house_profile_patch_merges_into_the_scenario_profile(tmp_path):
    paths = write_case_config(
        {
            "scenario_settings": {"house_profile_id": "test_home"},
            "house_profile_patch": {"persons": 3, "thermal": {"living_area_m2": 140}},
        },
        tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
    )
    doc = json.loads(paths[HOUSE_PROFILES_ENV].read_text(encoding="utf-8"))
    profile = next(p for p in doc["profiles"] if p["id"] == "test_home")
    assert profile["persons"] == 3
    assert profile["thermal"]["living_area_m2"] == 140
    assert profile["thermal"]["building_class"] == 3  # merged, not replaced


def test_heating_system_patch_merges_into_the_catalog_entry(tmp_path):
    store = {"volume_liters": 500, "heat_loss_kw_per_k": 0.0}
    paths = write_case_config(
        {"heating_system_patch": {"heating_test_home": {"heat_storage": store}}},
        tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
    )
    assert set(paths) == {COMPONENTS_ENV}
    doc = json.loads(paths[COMPONENTS_ENV].read_text(encoding="utf-8"))
    system = next(s for s in doc["heating_systems"] if s["id"] == "heating_test_home")
    assert system["heat_storage"] == store
    assert system["heating_power_kw"] == 10.5  # merged, not replaced


def test_heating_system_patch_unknown_system_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="heating system 'nope' not in the fixture"):
        write_case_config(
            {"heating_system_patch": {"nope": {"heating_power_kw": 1}}},
            tmp_path, fixtures_root=FIXTURES_ROOT, case_id="c",
        )


def test_deep_merge_does_not_touch_the_base():
    base = {"a": {"b": 1, "c": [1]}}
    out = deep_merge(base, {"a": {"b": 2}, "d": 4})
    assert out == {"a": {"b": 2, "c": [1]}, "d": 4}
    assert base == {"a": {"b": 1, "c": [1]}}


# --- metrics ----------------------------------------------------------------------


def _frame(import_kwh, wp_kw=None) -> pd.DataFrame:
    index = pd.date_range("2026-01-14", periods=len(import_kwh), freq="15min")
    data = {"import_kwh": import_kwh}
    if wp_kw is not None:
        data["wp_kw"] = wp_kw
    return pd.DataFrame(data, index=index)


def test_peak_import_and_consumer_energy():
    metrics = l2_runner.metrics_from_l2_frame(
        _frame([0.5, 1.5, 1.0], wp_kw=[2.0, 0.0, 4.0]), None, consumers=("wp",)
    )
    assert metrics["peak_import_kw"] == pytest.approx(6.0)
    assert metrics["consumer_kwh_wp"] == pytest.approx(1.5)
    assert "capacity_charge_eur" not in metrics


def test_slots_over_the_import_limit_without_a_cause():
    frame = _frame([0.55, 0.77, 0.77, 0.4]).assign(
        import_cap_limit=[2.2, 2.2, 2.2, None],
        import_cap_cause=[None, None, "battery_energy", None],
    )
    metrics = l2_runner.metrics_from_l2_frame(frame, None)
    # 2.2 kW on the limit, 3.08 kW without a cause, 3.08 kW with one, 1.6 kW without a limit.
    assert metrics["import_cap_slots_over_without_cause"] == 1.0


def test_no_import_limit_no_overshoot_metric():
    assert "import_cap_slots_over_without_cause" not in l2_runner.metrics_from_l2_frame(
        _frame([0.5]), None
    )


def test_consumer_price_is_weighted_by_its_energy():
    frame = _frame([0.5, 1.5, 1.0], wp_kw=[2.0, 0.0, 6.0]).assign(k_act=[10.0, 40.0, 30.0])
    metrics = l2_runner.metrics_from_l2_frame(frame, None, priced_consumers=("wp",))
    # (2 * 10 + 6 * 30) / 8 = 25 ct; the 40 ct slot has no heat pump energy.
    assert metrics["consumer_price_ct_wp"] == pytest.approx(25.0)


def test_consumer_price_without_energy_fails_loud():
    frame = _frame([0.5], wp_kw=[0.0]).assign(k_act=[10.0])
    with pytest.raises(ValueError, match="has no energy in the window"):
        l2_runner.metrics_from_l2_frame(frame, None, priced_consumers=("wp",))


def test_missing_consumer_column_fails_loud():
    with pytest.raises(ValueError, match="no column 'rod_kw'"):
        l2_runner.metrics_from_l2_frame(_frame([0.5]), None, consumers=("rod",))


# --- run_l2 wiring ----------------------------------------------------------------


def _fake_result(start, end, scenario, prices, **kwargs):
    index = pd.date_range(start, periods=96, freq="15min")
    df = pd.DataFrame(
        {
            "import_kwh": [1.0] * 96,
            "export_kwh": 0.0,
            "sim_cost": 0.1,
            "batt_action_kw": 0.0,
            "pv_kw": 0.0,
            "baseload_kw": 0.4,
            "k_act": 25.0,
            "k_push_act": 5.0,
        },
        index=index,
    )
    return df, None, None


def test_run_l2_uses_the_patched_scenario_and_capacity_charge(monkeypatch):
    import config
    import simulation.engine as engine

    seen: dict = {}

    def _capture(start, end, scenario, prices, **kwargs):
        seen["scenario"] = scenario
        seen["scenario_id"] = kwargs["scenario_id"]
        return _fake_result(start, end, scenario, prices, **kwargs)

    monkeypatch.setattr(engine, "run_simulation", _capture)
    monkeypatch.setattr(l2_runner, "assert_pv_day_shape", lambda df, *, case_id: None)
    before = os.environ.get("EARNIE_HOUSE_PROFILES_PATH")
    meta = _meta(
        scenario_settings={"house_profile_id": "test_home", "import_cap_kw": 5.0,
                           "import_cap_margin_kw": 0.3},
        house_profile_patch={"persons": 3},
        grid_fee_base_cent_kwh=5.0,
        grid_capacity_charges=[CHARGE],
    )
    meta["extra_metrics"] = {"consumer_kwh": []}
    metrics = l2_runner.run_l2(RegressionCase(case_dir=Path("."), meta=meta, expected=None))

    scenario = seen["scenario"]
    assert seen["scenario_id"] == "fixture_5kwh_fixed"
    assert scenario["import_cap_kw"] == 5.0
    assert scenario["_house_profile"]["persons"] == 3
    assert metrics["peak_import_kw"] == pytest.approx(4.0)
    # The case grid area carries the charge: a 4 kW peak costs at least 4 kW x 3.00 EUR net.
    assert metrics["capacity_charge_eur"] >= 12.0
    assert os.environ.get("EARNIE_HOUSE_PROFILES_PATH") == before
    assert config.get_backtesting_scenarios()["fixture_5kwh_fixed"].get("import_cap_kw") is None
