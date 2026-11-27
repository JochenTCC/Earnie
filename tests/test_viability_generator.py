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
from house_config.generic_schedule import eligible_start_hours, generic_allowed_slot_hours
from house_config.edibert_tariffs import load_grid_fees, profile_grid_fee
from house_config.netznutzung import default_netznutzung_config
from studies.viability import params as params_mod
from studies.viability.appliances import baseload_target_kwh, daily_runs, start_hour_weights, write_profile
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
    scenario_market_zone,
    study_grid_fees,
    write_pack,
)
from studies.viability.run_houses import (
    DONE_FILE,
    cons_data_range,
    house_ids,
    is_done,
    ladder_command,
    needs_cons_data,
)

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
    doc["preisjahr"] = 2023
    with pytest.raises(params_mod.ParameterError, match="2023"):
        params_mod.validate(doc)


def test_missing_price_data_fails_loud():
    with pytest.raises(SystemExit, match="1999"):
        price_csv_for_year(1999, "AT")


def test_price_file_must_reach_a_week_before_the_year(tmp_path, monkeypatch):
    from studies.viability import make_houses

    monkeypatch.setattr(make_houses, "REPO_ROOT", tmp_path)
    folder = tmp_path / make_houses.PRICE_DIR
    folder.mkdir(parents=True)
    (folder / "prices_AT_2025.csv").write_text("x", encoding="utf-8")
    manifest = folder / "prices_AT_2025.manifest.json"
    manifest.write_text(json.dumps({"start": "2025-01-01", "end": "2026-01-04"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="2025-01-01"):
        make_houses.price_csv_for_year(2025, "AT")
    manifest.write_text(json.dumps({"start": "2024-12-20", "end": "2026-01-04"}), encoding="utf-8")
    assert make_houses.price_csv_for_year(2025, "AT").endswith("prices_AT_2025.csv")


def test_price_year_must_be_a_full_archive_year():
    from datetime import date

    from data.open_meteo_solar_archive import last_full_archive_year

    latest = last_full_archive_year(reference=date.today())
    check_thermal_year(latest)
    check_thermal_year(latest - 1)  # an earlier price year is fine: the pack's environment pins the climate year
    with pytest.raises(SystemExit, match="Archivjahr"):
        check_thermal_year(latest + 1)


def test_pack_environment_pins_the_climate_year_to_the_price_year(tmp_path):
    from studies.poc_cloud.run_poc import _env

    env = _env(tmp_path, offline_guard=True, climate_year=2024)
    assert env["EARNIE_CLIMATE_REFERENCE_YEAR"] == "2024"
    assert env["EARNIE_ENV_PATH"] == str(tmp_path)


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


def test_list_may_fix_roof_and_battery_per_house(params):
    capped = derive_house(params_mod.validate_house(_house(pv_kwp_je_mwh=2.2, eauto="zwei"), params, "t"), params)
    assert capped.pv_limit == "dach"
    roof = derive_house(params_mod.validate_house(_house(pv_kwp_je_mwh=2.2, eauto="zwei", dach_kwp=24), params, "t"), params)
    assert roof.pv_limit == "verbrauch"
    assert roof.roof_cap_kwp == 24.0
    assert roof.pv_kwp == round(roof.pv_wanted_kwp, 2) > capped.pv_kwp
    assert roof.battery_kwh == round(roof.pv_kwp, 1)  # the storage axis still applies
    fixed = derive_house(params_mod.validate_house(_house(pv_kwp_je_mwh=0.75, speicher_kwh=10), params, "t"), params)
    assert fixed.battery_kwh == 10.0
    assert fixed.pv_kwp < 10.0
    plant = derive_house(params_mod.validate_house(_house(personen=2, pv_kwp=9.97, speicher_kwh=10), params, "t"), params)
    assert (plant.pv_kwp, plant.pv_limit, plant.battery_kwh) == (9.97, "fest", 10.0)
    assert plant.pv_wanted_kwp < 9.97  # the demand rule would have given less; the fixed plant wins
    for bad in ({"dach_kwp": 0}, {"speicher_kwh": -1}, {"dach_kwp": "gross"}, {"speicher_kwh": True}, {"pv_kwp": 0}):
        with pytest.raises(ValueError):
            params_mod.validate_house(_house(**bad), params, "t")


def test_house_list_does_not_overwrite_a_pack_with_results(params, tmp_path):
    (tmp_path / "packs" / "T" / "results").mkdir(parents=True)
    with pytest.raises(SystemExit, match="Ergebnisse"):
        load_house_list(_list_file(tmp_path, _house()), params, tmp_path / "packs")
    # a list that grew after its first build: the built houses are left out, the new ones stay
    kept = load_house_list(_list_file(tmp_path, _house(), _house(id="N")), params, tmp_path / "packs", skip_done=True)
    assert list(kept) == ["N"]


def test_runner_cons_data_reaches_past_the_year_on_both_sides(tmp_path):
    from datetime import date

    first, last = cons_data_range(2025)
    # L1's first sunrise step reads two days before the year, the last chain the day after.
    assert first <= date(2024, 12, 30) and last >= date(2026, 1, 1)
    path = tmp_path / "cons_data.csv"
    assert needs_cons_data(path, 2025)
    path.write_text("timestamp;total_kw\n2025-01-01 00:00:00;0.4\n", encoding="utf-8")
    assert needs_cons_data(path, 2025)  # a pack built before the margin
    path.write_text(f"timestamp;total_kw\n{first.isoformat()} 00:00:00;0.4\n", encoding="utf-8")
    assert not needs_cons_data(path, 2025)


def test_runner_passes_months_with_the_price_year(tmp_path):
    args = argparse.Namespace(workers=2, start_month=1, end_month=12, sensitivity=False, forecast_price_strategy=None)
    command = ladder_command(args, 2025, tmp_path)
    # A bare month number would land in 2026, the latest year of the cons_data with its margin.
    assert command[command.index("--start-month") + 1] == "2025-01"
    assert command[command.index("--end-month") + 1] == "2025-12"


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


CLIMATE_FIXTURE_YEAR = 2025  # thermal reference year of the committed climate (tests/fixtures/viability_open_meteo)


def _load_pack(pack_dir: Path) -> dict:
    env = {
        **os.environ,
        "EARNIE_ENV_PATH": str(pack_dir),
        "EARNIE_OFFLINE": "1",
        "EARNIE_CLIMATE_REFERENCE_YEAR": str(CLIMATE_FIXTURE_YEAR),
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
        "EARNIE_OPEN_METEO_CACHE_PATH",
    ):
        env.pop(key, None)
    # Climate comes from the committed fixture only; CI has no cache and the archive times out there.
    result = subprocess.run(
        [sys.executable, "-m", "tests.fixtures.viability_inspect_offline"],
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
    assert report["points"]["wallbox"] == 4  # two wallboxes, with storage
    # Rule version 2, nominal (not effective) kWp: 1 point per 7 kWp, rounded half up.
    assert report["points"]["pv"] == math.floor(house.pv_kwp / 7 + 0.5)
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


DE_PARAMS = REPO_ROOT / "studies/viability/haeuser_de.json"


@pytest.fixture(scope="module")
def params_de() -> dict:
    return params_mod.load(DE_PARAMS)


def test_german_parameters_differ_from_the_austrian_only_in_the_tariff_frame():
    at = json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    de = json.loads(DE_PARAMS.read_text(encoding="utf-8"))
    tariff_frame = {"szenarien", "standard_szenarien", "netz", "stichproben"}
    public = {k for k in at if not k.startswith("_")}
    assert {k for k in de if not k.startswith("_")} == public
    for key in sorted(public - tariff_frame - {"annahmen"}):
        assert de[key] == at[key], f"{key} weicht in haeuser_de.json ab"
    assert {k: v for k, v in de["annahmen"].items() if k != "netzbereich"} == {
        k: v for k, v in at["annahmen"].items() if k != "netzbereich"
    }
    # Same sample houses, only the scenario names change.
    strip = [{k: v for k, v in h.items() if k != "szenarien"} for h in at["stichproben"]]
    assert [{k: v for k, v in h.items() if k != "szenarien"} for h in de["stichproben"]] == strip


def test_german_pack_carries_the_study_tariffs_and_prices_in_de_lu(params_de, tmp_path):
    root = write_pack(derive_house(_house(szenarien=["de_fix", "de_dynamisch"]), params_de), params_de, tmp_path / "T")
    config = root / "pack/config"
    user_tariffs = json.loads((config / "user_tariffs.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in user_tariffs["import_tariffs"]] == ["user_de_tibber_simple_fix"]
    assert (config / "user_grid_fees.json").read_text(encoding="utf-8") == (
        REPO_ROOT / "studies/viability/tarife_de/user_grid_fees.json"
    ).read_text(encoding="utf-8")
    profile = json.loads((config / "house_profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    assert profile["netznutzung"]["area_id"] == "user_de_netze_bw_2026"
    settings = json.loads((config / "config.json").read_text(encoding="utf-8"))
    assert settings["scenario_explorer_conf"]["path_price"].endswith("prices_DE-LU_2025.csv")
    # The catalog grid fees stay untouched (no SNAP shift for a study area).
    catalog = json.loads((REPO_ROOT / "share/config/grid_fees.json").read_text(encoding="utf-8"))
    assert json.loads((config / "grid_fees.json").read_text(encoding="utf-8")) == catalog


def test_austrian_pack_has_no_study_tariff_files(params, tmp_path):
    root = write_pack(derive_house(_house(), params), params, tmp_path / "T")
    assert not (root / "pack/config/user_tariffs.json").exists()
    assert not (root / "pack/config/user_grid_fees.json").exists()


def test_scenarios_of_two_market_zones_fail_loud(params_de):
    mixed = copy.deepcopy(params_de)
    mixed["szenarien"]["duo"] = {"import_tariff_id": "at_vkw_strom_duo_normalpreis", "export_tariff_id": "at_vkw_pv_flex"}
    user_dir = REPO_ROOT / "studies/viability/tarife_de"
    assert scenario_market_zone(["de_fix", "de_dynamisch"], mixed, user_dir) == "DE-LU"
    with pytest.raises(SystemExit, match="Marktzonen"):
        scenario_market_zone(["de_fix", "duo"], mixed, user_dir)
    mixed["szenarien"]["kaputt"] = {"import_tariff_id": "de_gibt_es_nicht", "export_tariff_id": "x"}
    with pytest.raises(SystemExit, match="de_gibt_es_nicht"):
        scenario_market_zone(["kaputt"], mixed, user_dir)


def test_snap_on_a_study_grid_area_fails_loud(params_de):
    catalog = json.loads((REPO_ROOT / "share/config/grid_fees.json").read_text(encoding="utf-8"))
    areas = json.loads((REPO_ROOT / "studies/viability/tarife_de/user_grid_fees.json").read_text(encoding="utf-8"))["areas"]
    snap = copy.deepcopy(params_de)
    snap["netz"] = {**snap["netz"], "snap_im_preisjahr": True}
    with pytest.raises(SystemExit, match="SNAP"):
        study_grid_fees(catalog, snap, areas)


def test_german_pack_passes_the_tariff_check(params_de, tmp_path):
    from scripts.validate_tariffs import main as validate_tariffs

    root = write_pack(derive_house(_house(szenarien=["de_fix", "de_dynamisch"]), params_de), params_de, tmp_path / "T")
    config = root / "pack/config"
    # Catalog, study tariffs, grid areas and the house profile's price context, all through Edibert.
    assert validate_tariffs([
        "--tariffs", str(config / "tariffs.json"),
        "--scenarios", str(config / "backtesting_scenarios.json"),
        "--grid-fees", str(config / "grid_fees.json"),
        "--house-profiles", str(config / "house_profiles.json"),
    ]) == 0


def test_missing_study_tariff_file_fails_loud(params_de, tmp_path, monkeypatch):
    from studies.viability import make_houses

    monkeypatch.setattr(make_houses, "STUDY_DIR", tmp_path)
    (tmp_path / "tarife_de").mkdir()
    (tmp_path / "tarife_de" / "user_tariffs.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="user_grid_fees.json"):
        make_houses.user_tariff_dir(params_de)


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
    assert parser.parse_args(["--workers", "2"]).references == "historical,l0"
    assert parser.parse_args(["--workers", "2", "--references", "l0"]).references == "l0"
    ladder_args = argparse.Namespace(
        workers=2, scenario=None, start_month=None, end_month=None, allow_stale_cons_data=False,
        references="l0",
    )
    argv = _backtesting_argv(ladder_args, "out")
    assert argv[argv.index("--references") + 1] == "l0"
    # The ladder study needs L1 / L2, which run_backtesting computes only on request.
    assert parser.parse_args([]).rule_reference is False
    assert "--rule-reference" in argv
    assert '"--references", "l0"' in (REPO_ROOT / "studies/viability/run_houses.py").read_text(encoding="utf-8")


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
    assert set(first.values()) <= set(range(14, 23))
    in_year = sum(1 for day in first if day.year == 2025)
    assert in_year == pytest.approx(2.0 * 365 / 7, rel=0.2)


def test_start_hours_peak_in_the_evening_at_six(params):
    weights = start_hour_weights(params)
    assert sorted(weights) == list(range(14, 23))
    assert max(weights, key=weights.get) == 18
    evening = sum(weights[hour] for hour in (17, 18, 19)) / sum(weights.values())
    assert evening == pytest.approx(0.56, abs=0.01)  # the share haeuser.json states


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
    weekly = params["geraete"]["laeufe_je_woche"][str(_house()["personen"])]["geschirrspueler"]
    # Earnie's window is fenster_earnie [12, 24], not the window of the random starts.
    assert dish["schedule"] == {
        "runs_per_week": math.ceil(weekly),  # a whole number for Earnie's schedule check
        "duration_h": 2.5,
        "start_hour": 18,
        "start_shift_h": 6.0,
    }
    # Earnie reads start hours modulo 24: the window runs from noon to midnight.
    assert eligible_start_hours(18, 6.0) == frozenset(range(12, 24)) | {0}
    # The slot mask MILP and L2 use: a late run may still lie in the hours after midnight.
    assert generic_allowed_slot_hours(18, 6.0, 2.5) == frozenset(range(12, 24)) | {0, 1, 2}
    assert "appliance_recommendation" not in dish


def test_appliance_role_and_odd_flex_window_fail_loud():
    doc = json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    doc["geraete"]["rolle"] = "manual"
    with pytest.raises(params_mod.ParameterError, match="geraete.rolle"):
        params_mod.validate(doc)
    doc["geraete"]["rolle"] = "flex"
    doc["geraete"]["fenster_earnie"] = [12, 23]
    with pytest.raises(params_mod.ParameterError, match="gerade"):
        params_mod.validate(doc)
    doc["geraete"]["rolle"] = "known"
    params_mod.validate(doc)  # an odd window is fine for fixed load


@pytest.mark.parametrize(
    "window, message",
    [
        ([16, 24], "enthaelt"),  # misses the starts at 14 and 15
        ([14, 20], "enthaelt"),  # misses the starts up to 22
        ([12, 26], "ungueltig"),  # beyond midnight after the run day
        ([18, 18], "mindestens 2"),  # Earnie needs a shift above 0
        ([8, 24], "Mitternacht"),  # L2 knows no price after midnight before noon
    ],
)
def test_earnie_window_must_hold_every_random_start(window, message):
    doc = json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    doc["geraete"]["fenster_earnie"] = window
    with pytest.raises(params_mod.ParameterError, match=f"fenster_earnie.*{message}"):
        params_mod.validate(doc)


def test_appliance_section_fails_loud_without_the_earnie_window():
    doc = json.loads(params_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    del doc["geraete"]["fenster_earnie"]
    with pytest.raises(params_mod.ParameterError, match="fenster_earnie"):
        params_mod.validate(doc)


def test_a_late_run_carries_into_the_next_day(params, tmp_path):
    from datetime import date

    path = tmp_path / "geschirrspueler.csv"
    # 2.5 h from 22:00 on New Year's Eve: two hours that day, half an hour after midnight.
    annual = write_profile(path, {date(2025, 3, 1): 22, date(2024, 12, 31): 22}, 0.4, 2.5, params)
    lines = path.read_text(encoding="utf-8").splitlines()[1:]
    power = {line.split(";")[0]: float(line.split(";")[1]) for line in lines}
    assert power["2025-03-01 22:00:00"] == pytest.approx(0.4)
    assert power["2025-03-01 23:00:00"] == pytest.approx(0.4)
    assert power["2025-03-02 00:00:00"] == pytest.approx(0.2)
    assert power["2025-03-02 01:00:00"] == 0.0
    assert power["2025-01-01 00:00:00"] == pytest.approx(0.2)
    # Only the price year counts: the March run in full, the half hour after New Year's Eve.
    assert annual == pytest.approx(1.0 + 0.2)


def test_parameter_module_loads_without_earnie_config_and_knows_the_publication_hour():
    from data.backtesting_prices import EPEX_DAY_AHEAD_PUBLISH_HOUR

    assert params_mod.EPEX_DAY_AHEAD_PUBLISH_HOUR == EPEX_DAY_AHEAD_PUBLISH_HOUR
    # Earnie-Projekt's evaluation imports the module without EARNIE_ENV_PATH or a config.json.
    probe = "import sys; import studies.viability.params; sys.exit('config' in sys.modules)"
    env = {k: v for k, v in os.environ.items() if k != "EARNIE_ENV_PATH"}
    assert subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT, env=env).returncode == 0


def test_overlapping_runs_fail_loud(params, tmp_path):
    from datetime import date

    # 3 h from 23:00 reaches 01:00, where the next day's run starts.
    runs = {date(2025, 3, 1): 23, date(2025, 3, 2): 1}
    with pytest.raises(SystemExit, match="ueberlappen"):
        write_profile(tmp_path / "trockner.csv", runs, 1.0, 3.0, params)


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
