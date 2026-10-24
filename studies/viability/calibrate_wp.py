"""Calibrate the heat pump consumer to the catalogue's annual electricity targets.

Earnie derives the heat pump's annual kWh from living area, building class, heat pump
type and the Open-Meteo climate of the location (reference year = last full archive year).
This solves for ``living_area_m2`` per target and writes ``wp_calibration.json``.

Needs network on the first run (climate bundle for the location, cached afterwards).

  python -m studies.viability.calibrate_wp
"""
from __future__ import annotations

import json
import os
import argparse
from pathlib import Path

from studies.viability import params

params.set_path_from_argv()  # honour --params before reading the file
_HP = params.load()["heat_pump"]

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
OUT = STUDY_DIR / "wp_calibration.json"

# target kWh/a -> building class; the area is solved. Values come from parameters.json ("waermepumpe").
LEVELS = _HP["levels"]
THERMAL_BASE = _HP["base"]
AREA_RANGE = _HP["area_range"]


def _annual_kwh(area: float, building_class: int, lat: float, lon: float, nominal_kw: float) -> float:
    from optimizer.thermal_parameters import house_thermal_parameters

    thermal = {
        **THERMAL_BASE,
        "living_area_m2": area,
        "building_class": building_class,
        "latitude": lat,
        "longitude": lon,
        "nominal_power_kw": nominal_kw,
    }
    return float(house_thermal_parameters(thermal).annual_electric_kwh)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, help="Parameter file (default: parameters.json)")
    parser.parse_args()
    os.chdir(REPO_ROOT)
    os.environ.setdefault("EARNIE_ENV_PATH", str(REPO_ROOT / "studies" / "poc_cloud" / "pack"))
    os.environ["EARNIE_OFFLINE"] = "1"
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from studies.viability.archetypes import LOCATION

    lat, lon = LOCATION
    result: dict[str, dict] = {}
    for target, building_class in LEVELS.items():
        nominal = min(6.0, max(2.5, target / 1100.0))
        lo, hi = AREA_RANGE
        for _ in range(40):
            mid = (lo + hi) / 2.0
            if _annual_kwh(mid, building_class, lat, lon, nominal) < target:
                lo = mid
            else:
                hi = mid
        area = round((lo + hi) / 2.0, 1)
        got = _annual_kwh(area, building_class, lat, lon, nominal)
        result[str(target)] = {"living_area_m2": area, "building_class": building_class,
                               "nominal_power_kw": round(nominal, 1), "annual_kwh": round(got, 1)}
        print(target, result[str(target)], flush=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
