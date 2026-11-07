"""Viability study generator: derived values by hand, packs on the current data model."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from data.consumption_profiles import _timestamp_hour_key
from house_config.edibert_tariffs import load_grid_fees, profile_grid_fee
from house_config.netznutzung import default_netznutzung_config
from studies.viability import params as params_mod
from studies.viability.appliances import baseload_target_kwh, daily_runs, start_hour_weights
from studies.viability.derive import (
    all_houses,
    derive_house,
    storage_liters,
    storage_loss_kw_per_k,
    stratified_sample,
)
from studies.viability.make_houses import (
    check_thermal_year,
    heating_system,
    load_house_list,
    price_csv_for_year,
    study_grid_fees,
    write_pack,
)
from studies.viability.run_houses import DONE_FILE, house_ids, is_done

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def params() -> dict:
    return params_mod.load(params_mod.DEFAULT_PATH)


def _house(**overrides) -> dict:
    return {
        "id": "T",
        "personen": 2,
        "huelle": "neubau",
        "heizsystem": "H1",
        "pv_kwp_je_mwh": 1.25,
        "pv_belegung": "sued",
        "speicher_kwh_je_kwp": 1,
        "eauto": "keins",
        "szenarien": ["duo", "dynamisch"],
        **overrides,
    }


def test_derived_values_of_a_hand_calculated_house(params):
    house = derive_house(_house(), params)
    assert house.living_area_m2 == 120
    assert house.gross_floor_area_m2 == 150
    assert house.household_kwh == 3400
    assert house.space_heat_kwh == pytest.approx(150 * 45)
    assert house.hot_water_kwh == pytest.approx(2 * 2 * 365)
    assert house.heat_pump_kwh == pytest.approx((6750 + 1460) / 3.5)
    assert house.heating_power_kw == pytest.approx(6750 * 32 / (3044 * 24) + 1.2, abs=0.01)
    assert house.building_class == 2
    assert house.storage_liters == 416  # 4.16 kW * 100 l/kW
    assert house.pv_wanted_kwp == pytest.approx(1.25 * (3400 + 8210 / 3.5) / 1000)
    assert house.pv_limit == "verbrauch"
    assert house.battery_kwh == pytest.approx(house.pv_kwp, abs=0.05)


def test_roof_cap_south_and_east_west(params):
    side_kwp = (150 / 1.5 / 2 / math.cos(math.radians(30))) * 0.75 / 5.5
    south = derive_house(_house(pv_kwp_je_mwh=2.2), params)
    assert south.roof_cap_kwp == pytest.approx(side_kwp)
    assert south.pv_limit == "dach"
    assert south.pv_kwp == pytest.approx(side_kwp, abs=0.01)
    east_west = derive_house(_house(pv_kwp_je_mwh=2.2, pv_belegung="ost_west"), params)
    assert east_west.roof_cap_kwp == pytest.approx(2 * side_kwp)


def test_collector_takes_roof_and_keeps_the_store_of_its_heating_power(params):
    plain = derive_house(_house(personen=5), params)
    collector = derive_house(_house(personen=5, heizsystem="H2"), params)
    assert collector.collector_m2 == 7.5
    assert collector.storage_liters == plain.storage_liters == 714  # 525 l for the collector stay below
    assert collector.roof_cap_kwp == pytest.approx(plain.roof_cap_kwp - 7.5 / 5.5)


def test_store_volume_stays_within_its_limits_and_a_collector_can_raise_it(params):
    rules = params["regeln"]
    assert storage_liters(3.0, 0.0, rules) == 400
    assert storage_liters(6.46, 0.0, rules) == 646
    assert storage_liters(10.36, 0.0, rules) == 1000
    assert storage_liters(6.46, 12.0, rules) == 840  # 70 l/m2 above the power rule
    big_collector = derive_house(_house(personen=5, heizsystem="H2", huelle="bestand"), params)
    assert big_collector.storage_liters == 1000


def test_store_band_follows_the_heat_source(params):
    pump = derive_house(_house(), params)
    assert (pump.storage_setpoint_c, pump.storage_tolerance_c) == (60, 20)  # usable from 40 to 60 degrees
    for system in ("H6", "H7"):
        fuel = derive_house(_house(huelle="bestand", heizsystem=system), params)
        assert (fuel.storage_setpoint_c, fuel.storage_tolerance_c) == (70, 30)


def test_store_loss_grows_with_the_volume(params):
    rules = params["regeln"]
    assert storage_loss_kw_per_k(500, rules) == pytest.approx(0.0026, abs=0.00005)  # 117 W at 45 K
    assert storage_loss_kw_per_k(1000, rules) == pytest.approx((16.66 + 8.33 * 1000**0.4) / 45 / 1000)


def test_house_without_a_store_writes_no_store(params):
    house = derive_house(_house(huelle="bestand", heizsystem="H5"), params)
    assert house.storage_liters == 0
    assert "heat_storage" not in heating_system(house, params)


def test_pack_heating_system_carries_volume_loss_and_band(params):
    house = derive_house(_house(huelle="bestand", heizsystem="H7", personen=4), params)
    assert heating_system(house, params)["heat_storage"] == {
        "volume_liters": 906.0,
        "heat_loss_kw_per_k": pytest.approx(storage_loss_kw_per_k(906.0, params["regeln"])),
        "setpoint_c": 70.0,
        "tolerance_c": 30.0,
    }


def test_invalid_store_band_and_limits_fail_loud():
    doc = _raw_doc()
    doc["regeln"]["speicher_band_c"]["gas"]["von"] = 70
    with pytest.raises(params_mod.ParameterError, match="speicher_band_c.gas"):
        params_mod.validate(doc)
    doc = _raw_doc()
    del doc["regeln"]["speicher_band_c"]["pellets"]
    with pytest.raises(params_mod.ParameterError, match="pellets"):
        params_mod.validate(doc)
    doc = _raw_doc()
    doc["regeln"]["speicher_min_l"] = 2000
    with pytest.raises(params_mod.ParameterError, match="speicher_min_l"):
        params_mod.validate(doc)


def test_minimum_kwp_applies(params):
    house = derive_house(_house(pv_kwp_je_mwh=0.75), params)
    assert house.pv_wanted_kwp < 5
    assert (house.pv_kwp, house.pv_limit) == (5.0, "mindest_kwp")


def test_fuel_house_has_no_heat_pump_electricity_and_two_cars_count_twice(params):
    house = derive_house(_house(huelle="bestand", heizsystem="H6", eauto="zwei"), params)
    assert house.heat_pump_kwh == 0
    assert house.ev_kwh == pytest.approx(2 * 12000 * 21 / 100)
    assert house.ev_patterns == ("pendler", "zuhause")


def test_fuel_price_comes_from_the_price_year(params):
    house = derive_house(_house(huelle="bestand", heizsystem="H7"), params)
    system = heating_system(house, params)
    assert system["heat_source"] == {"type": "pellets", "fuel_price": 343.0}
    assert system["parts"][0]["nominal_power_kw"] == 3.0
    assert "min_on_quarterhours" not in system


def test_invalid_combination_fails_loud(params):
    with pytest.raises(params_mod.ParameterError, match="H5"):
        params_mod.validate_house(_house(heizsystem="H5"), params, "x")
    with pytest.raises(params_mod.ParameterError, match="personen"):
        params_mod.validate_house(_house(personen=6), params, "x")


def _raw_doc() -> dict:
    return json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))


_HEAT_PUMP_WITH_ROD = {
    "quelle": "heat_pump", "kollektor": False, "heizstab": True, "speicher": True, "huellen": ["neubau", "bestand"],
}


def test_parameter_file_with_heat_pump_and_rod_fails_loud():
    doc = _raw_doc()
    doc["heizsysteme"]["HX"] = dict(_HEAT_PUMP_WITH_ROD)
    with pytest.raises(params_mod.ParameterError, match="HX.*Waermepumpe mit Heizstab"):
        params_mod.validate(doc)


def test_generator_rejects_heat_pump_with_rod_without_the_loader(params):
    """``derive_house`` and ``all_houses`` also refuse parameters that skipped ``validate``."""
    other = copy.deepcopy(params)
    other["heizsysteme"]["HX"] = dict(_HEAT_PUMP_WITH_ROD)
    other["achsen"]["heizsystem"].append("HX")
    with pytest.raises(params_mod.ParameterError, match="Waermepumpe mit Heizstab"):
        derive_house(_house(heizsystem="HX"), other)
    with pytest.raises(params_mod.ParameterError, match="Waermepumpe mit Heizstab"):
        all_houses(other)


def test_fuel_source_keeps_its_rod(params):
    assert params["heizsysteme"]["H6"]["heizstab"] and params["heizsysteme"]["H7"]["heizstab"]
    assert not any(
        system["heizstab"] and system["quelle"] == params_mod.HEAT_PUMP
        for system in params["heizsysteme"].values()
    )


def test_sample_houses_cover_every_level_without_s5(params):
    houses = params["stichproben"]
    assert [h["id"] for h in houses] == ["S1", "S2", "S3", "S4", "S6", "S7", "S8", "S9"]
    for axis, levels in params["achsen"].items():
        for level in levels:
            assert any(h[axis] == level for h in houses), (axis, level)


def test_unknown_key_and_missing_fuel_year_fail_loud():
    doc = _raw_doc()
    doc["annahmen"]["tippfehler"] = 1
    with pytest.raises(params_mod.ParameterError, match="tippfehler"):
        params_mod.validate(doc)
    doc = _raw_doc()
    doc["preisjahr"] = 2024
    with pytest.raises(params_mod.ParameterError, match="2024"):
        params_mod.validate(doc)


def test_missing_price_data_fails_loud():
    with pytest.raises(SystemExit, match="1999"):
        price_csv_for_year(1999)


def test_price_year_other_than_the_thermal_year_fails_loud():
    from data.open_meteo_solar_archive import last_full_archive_year

    with pytest.raises(SystemExit, match="Archivjahr"):
        check_thermal_year(last_full_archive_year() - 1)


def _list_file(tmp_path: Path, *houses: dict) -> Path:
    path = tmp_path / "liste.json"
    path.write_text(json.dumps({"_hinweis": "x", "haeuser": list(houses)}), encoding="utf-8")
    return path


def test_house_list_ignores_comment_keys_and_keeps_its_ids(params, tmp_path):
    path = _list_file(tmp_path, _house(id="G0001", _rolle="kontrolle"), _house(id="G0002"))
    houses = load_house_list(path, params, tmp_path / "packs")
    assert list(houses) == ["G0001", "G0002"]
    assert "_rolle" not in houses["G0001"]


def test_house_list_rejects_an_invalid_house_and_a_double_id(params, tmp_path):
    with pytest.raises(ValueError):
        load_house_list(_list_file(tmp_path, _house(personen=9)), params, tmp_path / "packs")
    with pytest.raises(SystemExit, match="doppelt"):
        load_house_list(_list_file(tmp_path, _house(), _house()), params, tmp_path / "packs")


def test_house_list_does_not_overwrite_a_pack_with_results(params, tmp_path):
    (tmp_path / "packs" / "T" / "results").mkdir(parents=True)
    with pytest.raises(SystemExit, match="Ergebnisse"):
        load_house_list(_list_file(tmp_path, _house()), params, tmp_path / "packs")


def test_runner_finds_all_built_packs_and_what_is_done(tmp_path):
    for house_id, done in (("G2", True), ("G1", False)):
        run_dir = tmp_path / house_id / "results" / "stufe1"
        run_dir.mkdir(parents=True)
        (tmp_path / house_id / "house.json").write_text("{}", encoding="utf-8")
        if done:
            (run_dir / DONE_FILE).write_text("x", encoding="utf-8")
    (tmp_path / "no_pack").mkdir()
    assert house_ids(tmp_path, None) == ["G1", "G2"]
    assert house_ids(tmp_path, "G2, G1") == ["G2", "G1"]
    assert is_done(tmp_path, "G2", "stufe1")
    assert not is_done(tmp_path, "G1", "stufe1")
    assert not is_done(tmp_path, "G2", "other")


def test_grid_size_and_sample_is_reproducible_and_covers_every_level(params):
    assert len(all_houses(params)) == 3584  # 4 storage levels since stage 2 (F17)
    first = stratified_sample(params, 60, seed=7)
    assert first == stratified_sample(params, 60, seed=7)
    assert first != stratified_sample(params, 60, seed=8)
    for axis, levels in params["achsen"].items():
        for level in levels:
            assert sum(h[axis] == level for h in first) >= 10, (axis, level)


def _load_pack(pack_dir: Path) -> dict:
    env = {
        **os.environ,
        "EARNIE_ENV_PATH": str(pack_dir),
        "EARNIE_OFFLINE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    for key in (
        "EARNIE_CONFIG_PATH",
        "EARNIE_RUNTIME_PATH",
        "EARNIE_HOUSE_PROFILES_PATH",
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        "EARNIE_COMPONENTS_PATH",
        "EARNIE_TARIFFS_PATH",
    ):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-m", "studies.viability.inspect_pack"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_fuel_pack_passes_the_loader_with_more_than_two_scenarios(params, tmp_path):
    spec = _house(
        huelle="bestand",
        heizsystem="H6",
        eauto="zwei",
        pv_belegung="ost_west",
        szenarien=["duo", "dynamisch", "duo_pvdyn"],
    )
    house = derive_house(spec, params)
    root = write_pack(house, params, tmp_path / "T")
    report = _load_pack(root / "pack")
    assert report["scenarios"] == ["duo", "duo_pvdyn", "dynamisch"]
    assert report["points"]["wallbox"] == 4  # three-phase, two wallboxes
    assert report["points"]["pv"] == 1 + math.ceil((house.pv_kwp - 6) / 4)  # nominal, not effective kWp
    assert report["consumers"]["wp_heating"] == 0

    profile = json.loads((root / "pack/config/house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    schedules = {c["id"]: c["charging_schedule"] for c in profile["consumers"] if c["type"] == "ev"}
    assert schedules["ev1"]["weekday"]["car_available_from_hour"] == 18
    assert schedules["ev2"]["weekday"]["car_available_from_hour"] == 9
    components = json.loads((root / "pack/config/components.json").read_text(encoding="utf-8"))
    assert sum(s["kwp"] for s in components["pv_systems"]) == pytest.approx(house.pv_kwp * 0.8, abs=0.01)
    assert [s["pv_azimuth"] for s in components["pv_systems"]] == [-90, 90]


def test_pack_grid_fee_takes_levies_from_the_catalog_and_snap_in_the_price_year(params, tmp_path):
    root = write_pack(derive_house(_house(), params), params, tmp_path / "T")
    doc = json.loads((root / "pack/config/grid_fees.json").read_text(encoding="utf-8"))
    area = next(a for a in doc["areas"] if a["id"] == "AT-VBG")
    assert area["base_cent_kwh"]["unmetered_power"] == 4.96  # no surcharge on top of the catalog's
    fee = profile_grid_fee(
        "T",
        {"netznutzung": {**default_netznutzung_config(), "area_id": "AT-VBG"}},
        load_grid_fees(str(root / "pack/config/grid_fees.json")),
    )
    assert sum(part.value for part in fee.components) == pytest.approx(0.393 + 0.1 + 0.62)
    snap = next(r for r in doc["rule_sets"]["AT_NE7"] if r["id"] == "SNAP")
    assert snap["valid_from"] == "2025-01-01"
    assert snap["effect"] == {"mode": "percent_off", "value": 20.0}  # work price only, not the levies
    profile = json.loads((root / "pack/config/house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    assert profile["netznutzung"]["power_metering"] == "unmetered_power"


def test_study_grid_fee_leaves_the_product_catalog_alone(params):
    catalog = json.loads((REPO_ROOT / "share/config/grid_fees.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(catalog)
    study_grid_fees(catalog, params)
    assert catalog == before
    assert next(r for r in catalog["rule_sets"]["AT_NE7"] if r["id"] == "SNAP")["valid_from"] == "2026-04-01"


def test_study_grid_fee_without_snap_or_with_unknown_area(params):
    catalog = json.loads((REPO_ROOT / "share/config/grid_fees.json").read_text(encoding="utf-8"))
    off = copy.deepcopy(params)
    off["netz"] = {**off["netz"], "snap_im_preisjahr": False}
    snap = next(r for r in study_grid_fees(catalog, off)["rule_sets"]["AT_NE7"] if r["id"] == "SNAP")
    assert snap["valid_from"] == "2026-04-01"
    unknown = copy.deepcopy(params)
    unknown["annahmen"]["netzbereich"] = "AT-NIRGENDS"
    with pytest.raises(SystemExit, match="AT-NIRGENDS"):
        study_grid_fees(catalog, unknown)


def test_duo_scenario_uses_flex_with_all_months_of_the_price_year(params):
    assert params["szenarien"]["duo"]["export_tariff_id"] == "at_vkw_pv_flex"
    catalog = json.loads((REPO_ROOT / "share/config/tariffs.json").read_text(encoding="utf-8"))
    flex = next(t for t in catalog["export_tariffs"] if t["id"] == "at_vkw_pv_flex")
    months = {(r["year"], r["month"]) for r in flex["monthly_rates"]}
    assert {(2024, 12)} | {(2025, m) for m in range(1, 13)} <= months


def test_study_runs_skip_the_reference_without_pv_and_battery():
    from scripts.run_backtesting import _build_arg_parser
    from scripts.run_reference_ladder import _backtesting_argv

    parser = _build_arg_parser()
    assert parser.parse_args(["--workers", "2"]).skip_historical_reference is False
    assert parser.parse_args(["--workers", "2", "--skip-historical-reference"]).skip_historical_reference is True
    ladder_args = argparse.Namespace(
        workers=2, scenario=None, start_month=None, end_month=None, allow_stale_cons_data=False,
        skip_historical_reference=True,
    )
    assert "--skip-historical-reference" in _backtesting_argv(ladder_args, "out")
    assert '"--skip-historical-reference"' in (REPO_ROOT / "studies/viability/run_houses.py").read_text(encoding="utf-8")


def test_appliances_can_be_switched_off(params, tmp_path):
    off = copy.deepcopy(params)
    off["geraete"]["aktiv"] = False
    root = write_pack(derive_house(_house(), off), off, tmp_path / "T")
    profile = json.loads((root / "pack/config/house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    assert {c["type"] for c in profile["consumers"]} == {"thermal_annual"}
    assert not (root / "pack/config/appliances").exists()


def test_appliance_profiles_are_reproducible_and_stay_in_the_window(params):
    first = daily_runs("trockner", 2.0, "T", params)
    assert first == daily_runs("trockner", 2.0, "T", params)
    assert first != daily_runs("trockner", 2.0, "U", params)
    assert first != daily_runs("waschmaschine", 2.0, "T", params)
    assert set(first.values()) <= set(range(7, 22))
    in_year = sum(1 for day in first if day.year == 2025)
    assert in_year == pytest.approx(2.0 * 365 / 7, rel=0.2)


def test_start_hours_peak_slightly_at_eight_noon_and_seven_pm(params):
    weights = start_hour_weights(params)
    assert sorted(weights) == list(range(7, 22))
    assert weights[8] > weights[10] and weights[12] > weights[10] and weights[19] > weights[16]
    assert max(weights.values()) < 2.5 * min(weights.values())


def test_pack_with_appliances_reads_back_their_energy_as_fixed_load(params, tmp_path):
    known = copy.deepcopy(params)
    known["geraete"]["rolle"] = "known"
    house = derive_house(_house(), known)
    root = write_pack(house, known, tmp_path / "T")
    config = root / "pack/config"
    profile = json.loads((config / "house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    rows = {c["id"]: c for c in profile["consumers"] if c["type"] == "generic"}
    assert set(rows) == {"waschmaschine", "geschirrspueler", "trockner"}
    dryer = rows["trockner"]
    assert dryer["earnie_role"] == "known"
    assert dryer["nominal_power_kw"] == pytest.approx(1.25)
    assert "appliance_recommendation" not in dryer
    assert "schedule" not in dryer
    # The profile must parse with Earnie's own slot key, a different timestamp text reads as 0 kW.
    lines = (config / "appliances/trockner.csv").read_text(encoding="utf-8").splitlines()[1:]
    power = {line.split(";")[0]: float(line.split(";")[1]) for line in lines}
    in_year = sum(kw for ts, kw in power.items() if ts.startswith("2025"))
    assert in_year == pytest.approx(dryer["annual_kwh"], abs=0.1)
    assert in_year > 0
    assert _timestamp_hour_key(datetime(2025, 3, 1, 12, 15)) in power


def test_flex_appliances_keep_the_profile_and_get_the_start_window_as_schedule(params, tmp_path):
    assert params["geraete"]["rolle"] == "flex"  # the default since stage 2 (plan 5.2)
    root = write_pack(derive_house(_house(), params), params, tmp_path / "T")
    profile = json.loads((root / "pack/config/house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    rows = {c["id"]: c for c in profile["consumers"] if c["type"] == "generic"}
    dish = rows["geschirrspueler"]
    assert dish["earnie_role"] == "flex" and dish["use_profile_csv"] is True
    first, last = params["geraete"]["fenster_start"]
    weekly = params["geraete"]["laeufe_je_woche"][str(_house()["personen"])]["geschirrspueler"]
    assert dish["schedule"] == {
        "runs_per_week": math.ceil(weekly),  # a whole number for Earnie's schedule check
        "duration_h": 2.5,
        "start_hour": (first + last) // 2,
        "start_shift_h": float((last - first) // 2),
    }
    assert dish["schedule"]["start_hour"] - dish["schedule"]["start_shift_h"] == first
    assert dish["schedule"]["start_hour"] + dish["schedule"]["start_shift_h"] == last
    assert "appliance_recommendation" not in dish


def test_appliance_role_and_odd_flex_window_fail_loud():
    doc = json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    doc["geraete"]["rolle"] = "manual"
    with pytest.raises(params_mod.ParameterError, match="geraete.rolle"):
        params_mod.validate(doc)
    doc["geraete"]["rolle"] = "flex"
    doc["geraete"]["fenster_start"] = [7, 20]
    with pytest.raises(params_mod.ParameterError, match="gerade"):
        params_mod.validate(doc)
    doc["geraete"]["rolle"] = "known"
    params_mod.validate(doc)  # an odd window is fine for fixed load


def test_appliance_section_fails_loud_on_a_missing_household_size(params):
    doc = json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    del doc["geraete"]["laeufe_je_woche"]["3"]
    with pytest.raises(params_mod.ParameterError, match="laeufe_je_woche.3"):
        params_mod.validate(doc)


def test_pack_price_path_follows_the_price_year(params, tmp_path):
    root = write_pack(derive_house(_house(huelle="bestand", heizsystem="H5"), params), params, tmp_path / "T")
    config = json.loads((root / "pack/config/config.json").read_text(encoding="utf-8"))
    assert config["scenario_explorer_conf"]["path_price"].endswith("prices_AT_2025.csv")
    other = copy.deepcopy(params)
    other["preisjahr"] = 1999
    with pytest.raises(SystemExit, match="1999"):
        write_pack(derive_house(_house(huelle="bestand", heizsystem="H5"), other), other, tmp_path / "U")


def test_baseload_target_leaves_out_only_profile_consumers() -> None:
    consumers = [
        {"annual_kwh": 2000.0},
        {"annual_kwh": 150.0, "use_profile_csv": True},
        {"annual_kwh": 250.0, "use_profile_csv": True},
    ]
    assert baseload_target_kwh(3400.0, consumers) == pytest.approx(3000.0)
