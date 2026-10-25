"""Generate one Earnie config pack per catalogue house (archetype x household).

For every house this writes ``<out>/<id>/pack/config`` and migrates it with Earnie's own
``scripts.migrate_config``. Parameters come from parameters.json (``--params FILE`` selects another). Two scenarios per house, both with ``own_reference``:
  duo        VKW Strom Duo (Normalpreis) + fixed feed-in        -> reference = B0, optimised = E0
  dynamisch  VKW Strom Dynamisch + PV-Dynamisch   -> reference = B1, optimised = E1

  python -m studies.viability.make_houses --ids A09-m,A18-m --out studies/viability/packs
  python -m studies.viability.make_houses --all
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

from studies.viability import archetypes as cat  # also applies --params (see params.py)
from studies.viability import params

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
SHARE = REPO_ROOT / "share" / "config"
POC_PACK_CONFIG = REPO_ROOT / "studies" / "poc_cloud" / "pack" / "config"
WP_CALIBRATION = STUDY_DIR / "wp_calibration.json"

_P = params.load()
_IMPL = _P["implementation"]
GRID_AREA = _IMPL["grid_area"]
HOUSE_ID = "house"
INVERTER_ID = "wr_main"
BATTERY_POWER_PER_KWH = _IMPL["battery_power_per_kwh"]  # kW per kWh
BATTERY_REPLACEMENT_EUR_PER_KWH = _IMPL["battery_replacement_eur_per_kwh"]
HEATING_ROD_START_HOUR = _IMPL["heating_rod_start_hour"]
HEATING_ROD_SHIFT_H = _IMPL["heating_rod_shift_h"]
EV_TARGET_SOC = _IMPL["ev_target_soc"]
HEAT_PUMP_BASE = _P["heat_pump"]["base"]

SCENARIOS = _P["scenarios"]  # {"duo": {...tariff ids}, "dynamisch": {...}}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def _heat_pump(house: cat.Archetype, template: dict, lat: float, lon: float) -> dict:
    calibration_all = _load(WP_CALIBRATION)
    if str(house.heat_pump_kwh) not in calibration_all:
        raise SystemExit(
            f"wp_calibration.json hat keinen Eintrag fuer {house.heat_pump_kwh} kWh/a "
            f"(vorhanden: {sorted(calibration_all)}). Zuerst 'python -m studies.viability.calibrate_wp' ausfuehren.")
    calibration = calibration_all[str(house.heat_pump_kwh)]
    wp = copy.deepcopy(template)
    wp.update(
        nominal_power_kw=calibration["nominal_power_kw"],
        living_area_m2=calibration["living_area_m2"],
        building_class=calibration["building_class"],
        heat_pump_type=HEAT_PUMP_BASE["heat_pump_type"],
        persons=HEAT_PUMP_BASE["persons"],
        target_temp_c=HEAT_PUMP_BASE["target_temp_c"],
        absent_temp_reduction_c=HEAT_PUMP_BASE["absent_temp_reduction_c"],
        heating_limit_c=HEAT_PUMP_BASE["heating_limit_c"],
    )
    return wp


def _ev(index: int, km: float, template: dict) -> dict:
    ev = copy.deepcopy(template)
    daily_kwh = km / 365.0 * cat.EV_KWH_PER_100KM / 100.0
    rest_soc = round(EV_TARGET_SOC - daily_kwh / cat.EV_BATTERY_KWH * 100.0, 1)
    ev_id = f"ev{index}"
    ev.update(
        id=ev_id,
        label=f"E-Auto {index} ({km:,.0f} km/a)",
        nominal_power_kw=cat.WALLBOX_KW,
        min_power_kw=4.1,
        battery_capacity_kwh=cat.EV_BATTERY_KWH,
    )
    schedule = ev["charging_schedule"]
    schedule["target_soc_percent"] = EV_TARGET_SOC
    schedule["weekday"]["daily_rest_soc"] = rest_soc
    schedule["weekend"]["daily_rest_soc"] = rest_soc
    ev["ehal_bindings"] = {k.replace(".ev.", f".{ev_id}.") if ".ev." in k else k: v
                           for k, v in ev["ehal_bindings"].items()}
    return ev


def _heating_rod() -> dict:
    duration_h = round(cat.HEATING_ROD_KWH / cat.HEATING_ROD_KW / (7 * 52), 2)
    return {
        "id": "heizstab",
        "label": "Heizstab Warmwasser",
        "type": "generic",
        "nominal_power_kw": cat.HEATING_ROD_KW,
        "absent_mode_enabled": False,
        "earnie_role": "flex",
        "schedule": {"runs_per_week": 7, "duration_h": duration_h,
                     "start_hour": HEATING_ROD_START_HOUR, "start_shift_h": HEATING_ROD_SHIFT_H},
    }


def _profile(house: cat.Archetype) -> dict:
    example = _load(SHARE / "house_profiles.example.json")
    profile = example["profiles"][0]
    lat, lon = cat.LOCATION
    consumers: list[dict] = []
    templates = {c["id"]: c for c in profile["consumers"]}
    if house.heat_pump_kwh:
        consumers.append(_heat_pump(house, templates["wp_heating"], lat, lon))
    for index, km in enumerate(house.evs, start=1):
        consumers.append(_ev(index, km, templates["ev"]))
    if house.heating_rod:
        consumers.append(_heating_rod())
    profile.update(
        id=HOUSE_ID,
        label=f"{house.id}: {house.name}",
        annual_kwh=round(house.total_kwh),
        latitude=lat,
        longitude=lon,
        default_pv_tilt=cat.PV_TILT_DEG,
        default_pv_azimuth=cat.PV_AZIMUTH_SOUTH,
        consumers=consumers,
        netznutzung={"area_id": GRID_AREA},
    )
    example["profiles"] = [profile]
    return example


def _components(house: cat.Archetype, pv_pr: float):
    example = _load(SHARE / "components.example.json")
    battery_tpl = example["batteries"][0]
    pv_tpl = example["pv_systems"][0]
    batteries = []
    if house.battery_kwh:
        battery = copy.deepcopy(battery_tpl)
        power = round(house.battery_kwh * BATTERY_POWER_PER_KWH, 2)
        battery.update(
            id=f"b{house.battery_kwh:g}", label=f"{house.battery_kwh:g} kWh Speicher",
            battery_capacity_kwh=house.battery_kwh,
            battery_max_charge_power_kw=power, battery_max_discharge_power_kw=power,
        )
        battery["battery_wear"]["replacement_cost_euro"] = round(
            house.battery_kwh * BATTERY_REPLACEMENT_EUR_PER_KWH)
        batteries.append(battery)
    pv_systems = []
    if house.pv_kwp:
        halves = ((house.pv_kwp / 2, -90, "east"), (house.pv_kwp / 2, 90, "west")) \
            if house.pv_layout == "east_west" else ((house.pv_kwp, cat.PV_AZIMUTH_SOUTH, "south"),)
        for kwp, azimuth, name in halves:
            system = copy.deepcopy(pv_tpl)
            # Earnie's backtest PV = irradiance x kWp without system losses; the effective
            # kWp (nominal x performance ratio) is the lever to model them. 1.0 = Earnie native.
            system.update(id=f"pv_{name}", label=f"{kwp:g} kWp {name} (PR {pv_pr:g})", kwp=round(kwp * pv_pr, 3),
                          pv_tilt=cat.PV_TILT_DEG, pv_azimuth=azimuth)
            pv_systems.append(system)
    example["batteries"] = batteries
    example["pv_systems"] = pv_systems
    return example, [b["id"] for b in batteries], [p["id"] for p in pv_systems]


def build_house(house: cat.Archetype, out_dir: Path, pv_pr: float = 1.0) -> Path:
    root = out_dir / house.id
    config_dir = root / "pack" / "config"
    if root.exists():
        shutil.rmtree(root)
    config_dir.mkdir(parents=True)
    (root / "pack" / "runtime").mkdir()

    for name in ("tariffs.json", "grid_fees.json"):
        shutil.copy2(SHARE / name, config_dir / name)
    shutil.copy2(SHARE / "deviation_rules.example.json", config_dir / "deviation_rules.json")

    config = _load(POC_PACK_CONFIG / "config.json")
    config["live_scenario_id"] = "duo"
    _dump(config_dir / "config.json", config)
    _dump(config_dir / "house_profiles.json", _profile(house))
    components, battery_ids, pv_ids = _components(house, pv_pr)
    _dump(config_dir / "components.json", components)

    scenarios = _load(SHARE / "backtesting_scenarios.minimal.json")
    scenarios["scenarios"] = [
        {
            "id": sid, "label": f"{house.id} {sid}", "own_reference": True,
            "settings": {"battery_ids": battery_ids, "pv_system_ids": pv_ids,
                         "house_profile_id": HOUSE_ID, **tariffs},
        }
        for sid, tariffs in SCENARIOS.items()
    ]
    _dump(config_dir / "backtesting_scenarios.json", scenarios)

    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate_config", "--config-dir", str(config_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit(f"migrate_config failed for {house.id}:\n{result.stdout}\n{result.stderr}")
    shutil.rmtree(config_dir / "backups", ignore_errors=True)
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, help="Parameter file (default: parameters.json)")
    parser.add_argument("--ids", help="Comma-separated house ids, e.g. A09-m,A18-m")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--out", type=Path, default=STUDY_DIR / "packs")
    parser.add_argument("--pv-pr", type=float, default=1.0,
                        help="PV performance ratio applied to the effective kWp (1.0 = Earnie native, no losses).")
    args = parser.parse_args()
    houses = {h.id: h for h in cat.variants()}
    ids = list(houses) if args.all else [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    if not ids:
        raise SystemExit("Give --ids or --all.")
    for house_id in ids:
        if house_id not in houses:
            raise SystemExit(f"Unknown house id {house_id}. Known: {', '.join(houses)}")
        root = build_house(houses[house_id], args.out, args.pv_pr)
        print(f"{house_id}: {root}")


if __name__ == "__main__":
    main()
