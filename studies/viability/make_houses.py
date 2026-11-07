"""Generate one Earnie config pack per derived house (data model 5).

For every house this writes ``<out>/<id>/pack/config``, migrates it with Earnie's own
``scripts.migrate_config``, and then asks Earnie for the consumers' annual kWh, so the profile's
``annual_kwh`` leaves exactly the rule's household electricity as baseload. ``house.json`` next
to the pack records the derived values and the Earnie-Points (product rule, nominal kWp).

  python -m studies.viability.make_houses --stichproben --out studies/viability/packs
  python -m studies.viability.make_houses --ids S1,S3 --allow-network
  python -m studies.viability.make_houses --liste LISTE.json --out studies/viability/packs_stufe1
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from studies.poc_cloud.run_poc import _env, _install_weather_cache
from studies.viability import params as params_mod
from studies.viability.appliances import Appliance, appliance_consumer, baseload_target_kwh, build_appliances
from studies.viability.derive import DerivedHouse, derive_house

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
SHARE = REPO_ROOT / "share" / "config"
POC_PACK_CONFIG = REPO_ROOT / "studies" / "poc_cloud" / "pack" / "config"
PRICE_DIR = "studies/poc_cloud/cache"
WEATHER_CACHE = STUDY_DIR / "cache" / "open_meteo"
HOUSE_ID = "house"
HEATING_CONSUMER_ID = "wp_heating"
HEATING_SYSTEM_ID = f"heating_{HOUSE_ID}"
BASELOAD_TOLERANCE_KWH = 5.0
BASELOAD_ITERATIONS = 5


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, doc: dict) -> None:
    # Study script: paths are built from STUDY_DIR and the house id (S2083).
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")  # NOSONAR pythonsecurity:S2083


def price_csv_for_year(year: int) -> str:
    """Repo-relative price CSV of the year; its absence or a short range fails loud."""
    relative = f"{PRICE_DIR}/prices_AT_{year}.csv"
    csv_path = REPO_ROOT / relative
    manifest_path = csv_path.with_suffix(".manifest.json")
    if not csv_path.is_file() or not manifest_path.is_file():
        raise SystemExit(
            f"Preisdaten fuer {year} fehlen: {relative}. Erst holen: python -m studies.poc_cloud.fetch_prices "
            f"--start {year}-01-01 --end {year + 1}-01-04"
        )
    manifest = _load(manifest_path)
    if manifest["start"] > f"{year}-01-01" or manifest["end"] < f"{year + 1}-01-02":
        raise SystemExit(f"{relative} deckt {year} samt Jahresrand nicht ab: {manifest['start']}..{manifest['end']}")
    return relative


def check_thermal_year(year: int) -> None:
    """Earnie's thermal model takes its climate from the last full archive year, not the study's."""
    from data.open_meteo_solar_archive import last_full_archive_year

    if year != last_full_archive_year():
        raise SystemExit(
            f"Preisjahr {year} weicht vom letzten vollen Archivjahr {last_full_archive_year()} ab, das "
            "Waermemodell und Grundlast rechnen. Ein anderes Preisjahr braucht erst eine Anpassung dort."
        )


def heating_system(house: DerivedHouse, params: dict) -> dict:
    source = house.heat_source
    if source == "heat_pump":
        heat_source = {"type": "heat_pump", "heat_pump_type": "luft", "efficiency": house.jaz}
    else:
        price = params["brennstoffpreise"][str(params["preisjahr"])][source]
        heat_source = {"type": source, "fuel_price": price}
    system = {
        "id": HEATING_SYSTEM_ID,
        "label": f"Heizsystem {house.id}",
        "heat_source": heat_source,
        "heating_power_kw": house.heating_power_kw,
    }
    if source == "heat_pump":
        system["min_on_quarterhours"] = 4
    if house.storage_liters:
        system["heat_storage"] = {
            "volume_liters": house.storage_liters,
            "heat_loss_kw_per_k": params["annahmen"]["speicher_verlust_kw_pro_k"],
        }
    if house.axes["_heizstab"]:
        system["parts"] = [
            {"id": "heating_rod", "type": "heating_rod",
             "nominal_power_kw": params["annahmen"]["heizstab_kw"]}
        ]
    return system


def _collector_azimuth(house: DerivedHouse) -> float:
    return 0.0 if house.axes["pv_belegung"] == "sued" else -90.0


def _heating_consumer(house: DerivedHouse, template: dict, params: dict) -> dict:
    consumer = copy.deepcopy(template)
    consumer["id"] = HEATING_CONSUMER_ID
    consumer["label"] = "Heizung"
    consumer["heating_system_id"] = HEATING_SYSTEM_ID
    if house.collector_m2:
        consumer["solar_thermal_area_m2"] = house.collector_m2
        consumer["solar_thermal_tilt_deg"] = params["annahmen"]["kollektor_neigung_grad"]
        consumer["solar_thermal_azimuth_deg"] = _collector_azimuth(house)
    return consumer


def _ev(index: int, pattern: str, template: dict, params: dict) -> dict:
    assumptions = params["annahmen"]
    windows = params["eauto_muster"][pattern]
    daily_kwh = assumptions["ev_km_pro_jahr"] / 365.0 * assumptions["ev_kwh_pro_100km"] / 100.0
    target = assumptions["ev_ziel_soc_prozent"]
    rest_soc = round(target - daily_kwh / assumptions["ev_akku_kwh"] * 100.0, 1)
    ev_id = f"ev{index}"
    ev = copy.deepcopy(template)
    ev.update(
        id=ev_id,
        label=f"E-Auto {index} ({pattern})",
        nominal_power_kw=assumptions["wallbox_kw"],
        min_power_kw=assumptions["wallbox_min_kw"],
        battery_capacity_kwh=assumptions["ev_akku_kwh"],
    )
    schedule = ev["charging_schedule"]
    schedule["target_soc_percent"] = target
    schedule["nominal_power_phases"] = assumptions["wallbox_phasen"]
    for day, key in (("weekday", "werktag"), ("weekend", "wochenende")):
        schedule[day] = {
            "car_available_from_hour": windows[key][0],
            "ready_by_hour": windows[key][1],
            "daily_rest_soc": rest_soc,
        }
    ev["ehal_bindings"] = {
        k.replace(".ev.", f".{ev_id}.") if ".ev." in k else k: v for k, v in ev["ehal_bindings"].items()
    }
    return ev


def _profile(house: DerivedHouse, params: dict, annual_kwh: float, appliances: list[Appliance]) -> dict:
    assumptions = params["annahmen"]
    doc = _load(SHARE / "house_profiles.example.json")
    profile = doc["profiles"][0]
    templates = {c["id"]: c for c in profile["consumers"]}
    consumers = [_heating_consumer(house, templates["wp_heating"], params)]
    consumers += [
        _ev(index, pattern, templates["ev"], params)
        for index, pattern in enumerate(house.ev_patterns, start=1)
    ]
    consumers += [appliance_consumer(a, templates[a.id], params) for a in appliances]
    lat, lon = assumptions["standort"]
    thermal = dict(profile["thermal"])
    thermal.update(
        living_area_m2=house.living_area_m2,
        gross_floor_area_m2=house.gross_floor_area_m2,
        building_class=house.building_class,
        target_temp_c=assumptions["solltemperatur_c"],
        heating_limit_c=assumptions["heizgrenze_c"],
        absent_temp_reduction_c=assumptions["absenkung_c"],
    )
    profile.update(
        id=HOUSE_ID,
        label=f"{house.id}: {house.axes['personen']} Personen, {house.axes['huelle']}, {house.axes['heizsystem']}",
        annual_kwh=round(annual_kwh, 1),
        latitude=lat,
        longitude=lon,
        default_pv_tilt=assumptions["pv_neigung_grad"],
        default_pv_azimuth=0,
        persons=int(house.axes["personen"]),
        thermal=thermal,
        consumers=consumers,
        netznutzung={**profile["netznutzung"], "area_id": assumptions["netzbereich"]},
    )
    doc["profiles"] = [profile]
    return doc


def _components(house: DerivedHouse, params: dict, *, performance_ratio: float) -> tuple[dict, list[str], list[str]]:
    """Earnie's backtest PV is irradiance × kWp without losses; ``kwp`` × PR models them."""
    assumptions = params["annahmen"]
    doc = _load(SHARE / "components.example.json")
    battery_template, pv_template = doc["batteries"][0], doc["pv_systems"][0]
    batteries = []
    if house.battery_kwh:
        battery = copy.deepcopy(battery_template)
        power = round(house.battery_kwh * assumptions["akku_leistung_c"], 2)
        battery.update(
            id="akku",
            label=f"{house.battery_kwh:g} kWh Speicher",
            battery_capacity_kwh=house.battery_kwh,
            battery_max_charge_power_kw=power,
            battery_max_discharge_power_kw=power,
            battery_efficiency=assumptions["akku_zell_wirkungsgrad"],
            ehal_bindings={k.replace(".default_5kwh.", ".akku."): v for k, v in battery["ehal_bindings"].items()},
        )
        battery["battery_wear"]["replacement_cost_euro"] = round(
            house.battery_kwh * assumptions["akku_verschleiss_eur_pro_kwh"]
        )
        batteries.append(battery)
    planes = (
        ((house.pv_kwp, 0, "sued"),)
        if house.axes["pv_belegung"] == "sued"
        else ((house.pv_kwp / 2, -90, "ost"), (house.pv_kwp / 2, 90, "west"))
    )
    pv_systems = []
    for kwp, azimuth, name in planes:
        system = copy.deepcopy(pv_template)
        system.update(
            id=f"pv_{name}",
            label=f"{kwp:g} kWp {name} (PR {performance_ratio:g})",
            kwp=round(kwp * performance_ratio, 3),
            pv_tilt=assumptions["pv_neigung_grad"],
            pv_azimuth=azimuth,
        )
        pv_systems.append(system)
    doc.update(batteries=batteries, pv_systems=pv_systems, heating_systems=[heating_system(house, params)])
    return doc, [b["id"] for b in batteries], [p["id"] for p in pv_systems]


def study_grid_fees(catalog: dict, params: dict) -> dict:
    """Grid fee catalog of a pack: SNAP over the whole price year, the catalog's prices as they are."""
    doc = copy.deepcopy(catalog)
    area_id = params["annahmen"]["netzbereich"]
    area = next((a for a in doc["areas"] if a["id"] == area_id), None)
    if area is None:
        raise SystemExit(f"Netzbereich {area_id} fehlt im Netzentgelt-Katalog.")
    if params["netz"]["snap_im_preisjahr"]:
        snap = next((r for r in doc["rule_sets"][area["rule_set"]] if r["id"] == "SNAP"), None)
        if snap is None:
            raise SystemExit(f"SNAP fehlt im Regelwerk {area['rule_set']}.")
        snap["valid_from"] = f"{params['preisjahr']}-01-01"
    return doc


def write_pack(house: DerivedHouse, params: dict, root: Path, *, annual_kwh: float | None = None) -> Path:
    """Write the config files of one house (replaces the pack, keeps nothing)."""
    config_dir = root / "pack" / "config"
    if root.exists():
        shutil.rmtree(root)
    config_dir.mkdir(parents=True)
    (root / "pack" / "runtime").mkdir()
    shutil.copy2(SHARE / "tariffs.json", config_dir / "tariffs.json")
    _dump(config_dir / "grid_fees.json", study_grid_fees(_load(SHARE / "grid_fees.json"), params))
    shutil.copy2(SHARE / "deviation_rules.example.json", config_dir / "deviation_rules.json")

    config = _load(POC_PACK_CONFIG / "config.json")
    config["live_scenario_id"] = house.scenarios[0]
    config["scenario_explorer_conf"]["path_price"] = price_csv_for_year(int(params["preisjahr"]))
    _dump(config_dir / "config.json", config)
    appliances = build_appliances(house, params, config_dir)
    _dump(config_dir / "house_profiles.json", _profile(house, params, annual_kwh or house.demand_kwh, appliances))
    components, battery_ids, pv_ids = _components(
        house, params, performance_ratio=params["annahmen"]["pv_performance_ratio"]
    )
    _dump(config_dir / "components.json", components)
    scenarios = _load(SHARE / "backtesting_scenarios.minimal.json")
    scenarios.update(params["solver"])
    scenarios["scenarios"] = [
        {
            "id": sid,
            "label": f"{house.id} {sid}",
            "own_reference": True,
            "settings": {
                "battery_ids": battery_ids,
                "pv_system_ids": pv_ids,
                "house_profile_id": HOUSE_ID,
                **params["szenarien"][sid],
            },
        }
        for sid in house.scenarios
    ]
    _dump(config_dir / "backtesting_scenarios.json", scenarios)
    return root


def _migrate(config_dir: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate_config", "--config-dir", str(config_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit(f"migrate_config failed for {config_dir}:\n{result.stdout}\n{result.stderr}")
    shutil.rmtree(config_dir / "backups", ignore_errors=True)


def inspect_pack(pack_dir: Path, *, offline_guard: bool) -> dict:
    """Load the pack with Earnie in a process of its own and read back what Earnie derives."""
    result = subprocess.run(
        [sys.executable, "-m", "studies.viability.inspect_pack"],
        cwd=REPO_ROOT, env=_env(pack_dir, offline_guard=offline_guard),
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit(f"Earnie lehnt das Paket {pack_dir} ab:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _set_annual_kwh(pack_dir: Path, annual_kwh: float) -> None:
    path = pack_dir / "config" / "house_profiles.json"
    doc = _load(path)
    doc["profiles"][0]["annual_kwh"] = round(annual_kwh, 1)
    _dump(path, doc)


def build_house(house: DerivedHouse, params: dict, out_dir: Path, *, offline_guard: bool = True) -> dict:
    """Write and check one pack; the baseload gains feed the heat demand, hence the iteration."""
    root = write_pack(house, params, out_dir / house.id)
    pack_dir = root / "pack"
    _migrate(pack_dir / "config")
    annual = house.demand_kwh
    report = {}
    profile_rows = _load(pack_dir / "config" / "house_profiles.json")["profiles"][0]["consumers"]
    baseload_target = baseload_target_kwh(house.household_kwh, profile_rows)
    for _ in range(BASELOAD_ITERATIONS):
        report = inspect_pack(pack_dir, offline_guard=offline_guard)
        if abs(report["baseload_kwh"] - baseload_target) <= BASELOAD_TOLERANCE_KWH:
            break
        annual = baseload_target + report["consumers_kwh"]
        _set_annual_kwh(pack_dir, annual)
    else:
        raise SystemExit(
            f"{house.id}: Grundlast {report['baseload_kwh']:.1f} kWh trifft den Zielwert "
            f"{baseload_target:.1f} kWh nicht."
        )
    record = {"derived": asdict(house), "earnie": report, "annual_kwh": round(annual, 1),
              "preisjahr": params["preisjahr"]}
    _dump(root / "house.json", record)
    return record


def load_house_list(path: Path, params: dict, out_dir: Path) -> dict[str, dict]:
    """Houses of a list file ``{"haeuser": [...]}``; a pack that already holds results fails loud."""
    houses: dict[str, dict] = {}
    for index, raw in enumerate(_load(path)["haeuser"]):
        house = params_mod.validate_house(raw, params, f"{path.name}[{index}]")
        if house["id"] in houses:
            raise SystemExit(f"{path}: Haus {house['id']} steht doppelt in der Liste.")
        if (out_dir / house["id"] / "results").exists():
            raise SystemExit(f"{out_dir / house['id']} enthaelt schon Ergebnisse; make_houses wuerde sie loeschen.")
        houses[house["id"]] = house
    return houses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, help="Parameterdatei (Standard: haeuser.json)")
    parser.add_argument("--ids", help="Kommagetrennte Haus-IDs aus den Stichproben, z. B. S1,S3")
    parser.add_argument("--stichproben", action="store_true", help="Alle Stichproben-Haeuser")
    parser.add_argument("--liste", type=Path, help="JSON-Datei mit einer Hausliste; baut alle ihre Haeuser")
    parser.add_argument("--out", type=Path, default=STUDY_DIR / "packs")
    parser.add_argument("--allow-network", action="store_true", help="Wetterdaten duerfen nachgeladen werden.")
    args = parser.parse_args()
    if args.params:
        os.environ[params_mod.ENV_VAR] = str(args.params.resolve())
    params = params_mod.load(args.params)

    os.environ.setdefault("EARNIE_ENV_PATH", str(REPO_ROOT / "studies" / "poc_cloud" / "pack"))
    check_thermal_year(int(params["preisjahr"]))
    if args.liste and (args.ids or args.stichproben):
        raise SystemExit("--liste geht nicht zusammen mit --ids oder --stichproben.")
    houses = load_house_list(args.liste, params, args.out) if args.liste else {h["id"]: h for h in params["stichproben"]}
    all_ids = args.stichproben or args.liste
    ids = list(houses) if all_ids else [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    if not ids:
        raise SystemExit("--ids, --stichproben oder --liste angeben.")
    _install_weather_cache(WEATHER_CACHE)
    for house_id in ids:
        if house_id not in houses:
            raise SystemExit(f"Unbekanntes Haus {house_id}. Bekannt: {', '.join(houses)}")
        record = build_house(derive_house(houses[house_id], params), params, args.out,
                             offline_guard=not args.allow_network)
        print(f"{house_id}: {record['derived']['pv_kwp']} kWp ({record['derived']['pv_limit']}), "
              f"{record['earnie']['consumers_kwh']:.0f} kWh Verbraucher, {record['earnie']['points']['total']} Punkte")


if __name__ == "__main__":
    main()
