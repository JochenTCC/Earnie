"""Viability study generator: derived values by hand, packs on the current data model."""
from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from studies.viability import params as params_mod
from studies.viability.derive import all_houses, derive_house, stratified_sample
from studies.viability.make_houses import (
    check_thermal_year,
    heating_system,
    price_csv_for_year,
    write_pack,
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
    assert house.storage_liters == 500
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


def test_collector_takes_roof_and_can_raise_the_storage(params):
    plain = derive_house(_house(personen=5), params)
    collector = derive_house(_house(personen=5, heizsystem="H2"), params)
    assert collector.collector_m2 == 7.5
    assert collector.storage_liters == 525
    assert collector.roof_cap_kwp == pytest.approx(plain.roof_cap_kwp - 7.5 / 5.5)


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


def test_grid_size_and_sample_is_reproducible_and_covers_every_level(params):
    assert len(all_houses(params)) == 3456
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


def test_pack_price_path_follows_the_price_year(params, tmp_path):
    root = write_pack(derive_house(_house(huelle="bestand", heizsystem="H5"), params), params, tmp_path / "T")
    config = json.loads((root / "pack/config/config.json").read_text(encoding="utf-8"))
    assert config["scenario_explorer_conf"]["path_price"].endswith("prices_AT_2025.csv")
    other = copy.deepcopy(params)
    other["preisjahr"] = 1999
    with pytest.raises(SystemExit, match="1999"):
        write_pack(derive_house(_house(huelle="bestand", heizsystem="H5"), other), other, tmp_path / "U")
