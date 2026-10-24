"""Load and validate the house generator parameter file (``haeuser.json``).

One file holds every value the generator uses (assumptions, implementation constants,
scenario tariffs, heat pump levels and the house catalogue). The Abo tiers and prices are
not part of it (they are business data and live outside this repository). Unknown keys,
wrong types or inconsistent references fail loudly with the offending path.

The file is chosen by, in this order: ``--params PATH`` on the command line (scripts call
``set_path_from_argv()`` before importing ``archetypes``), the environment variable
``EARNIE_STUDY_PARAMS``, then ``haeuser.json`` next to this module.
Keys starting with ``_`` are comments and ignored.
"""
from __future__ import annotations

import json
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ENV_VAR = "EARNIE_STUDY_PARAMS"
DEFAULT_PATH = Path(__file__).resolve().parent / "haeuser.json"

SECTIONS = {
    "annahmen": {"ev_kwh_pro_100km", "ev_akku_kwh", "wallbox_kw", "heizstab_kw", "heizstab_kwh_jahr",
                 "pv_neigung_grad", "pv_azimut_sued_grad", "standort", "haushalte", "standard_haushalt"},
    "umsetzung": {"netzbereich", "akku_leistung_kw_pro_kwh", "akku_verschleiss_eur_pro_kwh",
                  "heizstab_startstunde", "heizstab_spielraum_h", "ev_ziel_soc_prozent"},
    "waermepumpe": {"stufen", "basis", "flaeche_bereich_m2"},
    "szenarien": {"duo", "dynamisch"},
}
ARCHETYPE_KEYS = {"id", "name", "pv_kwp", "pv_layout", "battery_kwh", "evs", "heat_pump_kwh", "heating_rod"}
PV_LAYOUTS = {"south", "east_west"}


class ParameterError(ValueError):
    """The parameter file is invalid."""


def set_path_from_argv(argv: list[str] | None = None) -> None:
    """Honour ``--params PATH`` / ``--params=PATH`` before ``archetypes`` is imported."""
    args = sys.argv[1:] if argv is None else argv
    for index, arg in enumerate(args):
        if arg == "--params" and index + 1 < len(args):
            os.environ[ENV_VAR] = str(Path(args[index + 1]).resolve())
        elif arg.startswith("--params="):
            os.environ[ENV_VAR] = str(Path(arg.split("=", 1)[1]).resolve())


def resolve_path() -> Path:
    raw = os.environ.get(ENV_VAR, "").strip()
    return Path(raw) if raw else DEFAULT_PATH


def _fail(where: str, message: str) -> None:
    raise ParameterError(f"parameters: {where}: {message}")


def _number(where: str, value: Any, *, minimum: float | None = None, maximum: float | None = None,
            integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(where, f"Zahl erwartet, gefunden {value!r}")
    if integer and float(value) != int(value):
        _fail(where, f"ganze Zahl erwartet, gefunden {value!r}")
    if minimum is not None and value < minimum:
        _fail(where, f"muss >= {minimum} sein, gefunden {value!r}")
    if maximum is not None and value > maximum:
        _fail(where, f"muss <= {maximum} sein, gefunden {value!r}")
    return float(value)


def _text(where: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(where, f"nicht leerer Text erwartet, gefunden {value!r}")
    return value.strip()


def _keys(where: str, obj: Any, allowed: set[str], *, required: bool = True) -> dict:
    if not isinstance(obj, dict):
        _fail(where, "Objekt erwartet")
    data = {k: v for k, v in obj.items() if not str(k).startswith("_")}
    unknown = sorted(set(data) - allowed)
    if unknown:
        _fail(where, f"unbekannte Schluessel {unknown}; erlaubt: {sorted(allowed)}")
    if required:
        missing = sorted(allowed - set(data))
        if missing:
            _fail(where, f"fehlende Schluessel {missing}")
    return data


def _validate_assumptions(raw: Any) -> dict:
    data = _keys("annahmen", raw, SECTIONS["annahmen"])
    where = "annahmen"
    households_raw = data["haushalte"]
    if not isinstance(households_raw, dict) or not households_raw:
        _fail(f"{where}.haushalte", "nicht leeres Objekt erwartet (Kuerzel -> kWh/Jahr)")
    households = {
        _text(f"{where}.haushalte key", k): int(_number(f"{where}.haushalte.{k}", v, minimum=1, integer=True))
        for k, v in households_raw.items()
    }
    default = _text(f"{where}.standard_haushalt", data["standard_haushalt"])
    if default not in households:
        _fail(f"{where}.standard_haushalt", f"{default!r} steht nicht in haushalte {sorted(households)}")
    location = data["standort"]
    if not isinstance(location, list) or len(location) != 2:
        _fail(f"{where}.standort", "[Breite, Laenge] erwartet")
    lat = _number(f"{where}.standort[0]", location[0], minimum=-90, maximum=90)
    lon = _number(f"{where}.standort[1]", location[1], minimum=-180, maximum=180)
    return {
        "ev_kwh_per_100km": _number(f"{where}.ev_kwh_pro_100km", data["ev_kwh_pro_100km"], minimum=1),
        "ev_battery_kwh": _number(f"{where}.ev_akku_kwh", data["ev_akku_kwh"], minimum=1),
        "wallbox_kw": _number(f"{where}.wallbox_kw", data["wallbox_kw"], minimum=1),
        "heating_rod_kw": _number(f"{where}.heizstab_kw", data["heizstab_kw"], minimum=0.1),
        "heating_rod_kwh": _number(f"{where}.heizstab_kwh_jahr", data["heizstab_kwh_jahr"], minimum=1),
        "pv_tilt_deg": _number(f"{where}.pv_neigung_grad", data["pv_neigung_grad"], minimum=0, maximum=90),
        "pv_azimuth_south": _number(f"{where}.pv_azimut_sued_grad", data["pv_azimut_sued_grad"],
                                    minimum=-180, maximum=180),
        "location": (lat, lon),
        "households": households,
        "default_household": default,
    }


def _validate_implementation(raw: Any) -> dict:
    data = _keys("umsetzung", raw, SECTIONS["umsetzung"])
    where = "umsetzung"
    return {
        "grid_area": _text(f"{where}.netzbereich", data["netzbereich"]),
        "battery_power_per_kwh": _number(f"{where}.akku_leistung_kw_pro_kwh", data["akku_leistung_kw_pro_kwh"],
                                         minimum=0.05),
        "battery_replacement_eur_per_kwh": _number(f"{where}.akku_verschleiss_eur_pro_kwh",
                                                   data["akku_verschleiss_eur_pro_kwh"], minimum=0),
        "heating_rod_start_hour": int(_number(f"{where}.heizstab_startstunde", data["heizstab_startstunde"],
                                              minimum=0, maximum=23, integer=True)),
        "heating_rod_shift_h": _number(f"{where}.heizstab_spielraum_h", data["heizstab_spielraum_h"], minimum=0.25),
        "ev_target_soc": _number(f"{where}.ev_ziel_soc_prozent", data["ev_ziel_soc_prozent"],
                                 minimum=10, maximum=100),
    }


def _validate_heat_pump(raw: Any) -> dict:
    data = _keys("waermepumpe", raw, SECTIONS["waermepumpe"])
    levels_raw = data["stufen"]
    if not isinstance(levels_raw, dict) or not levels_raw:
        _fail("waermepumpe.stufen", "nicht leeres Objekt erwartet (kWh -> Gebaeudeklasse)")
    levels = {
        int(_number(f"waermepumpe.stufen key {k!r}", float(k), minimum=1, integer=True)):
            int(_number(f"waermepumpe.stufen.{k}", v, minimum=1, maximum=4, integer=True))
        for k, v in levels_raw.items()
    }
    base = _keys("waermepumpe.basis", data["basis"],
                 {"heat_pump_type", "persons", "target_temp_c", "absent_temp_reduction_c", "heating_limit_c"})
    if base["heat_pump_type"] not in ("luft", "erde"):
        _fail("waermepumpe.basis.heat_pump_type", "luft oder erde erwartet")
    area = data["flaeche_bereich_m2"]
    if not isinstance(area, list) or len(area) != 2 or not 0 < area[0] < area[1]:
        _fail("waermepumpe.flaeche_bereich_m2", "[min, max] mit 0 < min < max erwartet")
    return {"levels": levels, "base": dict(base), "area_range": (float(area[0]), float(area[1]))}


def _validate_scenarios(raw: Any) -> dict:
    data = _keys("szenarien", raw, SECTIONS["szenarien"])
    out = {}
    for sid, tariffs in data.items():
        item = _keys(f"szenarien.{sid}", tariffs, {"import_tariff_id", "export_tariff_id"})
        out[sid] = {k: _text(f"szenarien.{sid}.{k}", v) for k, v in item.items()}
    return out


def _validate_houses(raw: Any, hp_levels: dict[int, int]) -> tuple[dict, ...]:
    if not isinstance(raw, list) or not raw:
        _fail("haeuser", "nicht leere Liste erwartet")
    out, seen = [], set()
    for index, item in enumerate(raw):
        where = f"haeuser[{index}]"
        required = {"id", "name"}
        if not isinstance(item, dict) or not required <= set(item):
            _fail(where, f"mindestens {sorted(required)} erwartet")
        data = _keys(where, item, ARCHETYPE_KEYS, required=False)
        house_id = _text(f"{where}.id", data["id"])
        if "-" in house_id:
            _fail(f"{where}.id", "darf keinen Bindestrich enthalten (er trennt das Haushalts-Suffix)")
        if house_id in seen:
            _fail(f"{where}.id", f"{house_id!r} doppelt")
        seen.add(house_id)
        layout = data.get("pv_layout", "south")
        if layout not in PV_LAYOUTS:
            _fail(f"{where}.pv_layout", f"{layout!r} ungueltig; erlaubt: {sorted(PV_LAYOUTS)}")
        evs = data.get("evs", [])
        if not isinstance(evs, list):
            _fail(f"{where}.evs", "Liste mit Jahreskilometern erwartet")
        km = tuple(int(_number(f"{where}.evs[{i}]", v, minimum=1, integer=True)) for i, v in enumerate(evs))
        heat_pump = int(_number(f"{where}.heat_pump_kwh", data.get("heat_pump_kwh", 0), minimum=0, integer=True))
        if heat_pump and heat_pump not in hp_levels:
            _fail(f"{where}.heat_pump_kwh",
                  f"{heat_pump} fehlt in waermepumpe.stufen {sorted(hp_levels)}; zuerst eintragen und "
                  "calibrate_wp ausfuehren")
        rod = data.get("heating_rod", False)
        if not isinstance(rod, bool):
            _fail(f"{where}.heating_rod", "true oder false erwartet")
        out.append({
            "id": house_id, "name": _text(f"{where}.name", data["name"]),
            "pv_kwp": _number(f"{where}.pv_kwp", data.get("pv_kwp", 0.0), minimum=0),
            "pv_layout": layout,
            "battery_kwh": _number(f"{where}.battery_kwh", data.get("battery_kwh", 0.0), minimum=0),
            "evs": km, "heat_pump_kwh": heat_pump, "heating_rod": rod,
        })
    return tuple(out)


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    file = Path(path)
    if not file.is_file():
        raise ParameterError(f"parameters: Datei nicht gefunden: {file}")
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParameterError(f"parameters: {file} ist kein gueltiges JSON: {exc}") from exc
    data = _keys(str(file.name), doc, set(SECTIONS) | {"haeuser"})
    heat_pump = _validate_heat_pump(data["waermepumpe"])
    return {
        "path": file,
        "assumptions": _validate_assumptions(data["annahmen"]),
        "implementation": _validate_implementation(data["umsetzung"]),
        "heat_pump": heat_pump,
        "scenarios": _validate_scenarios(data["szenarien"]),
        "houses": _validate_houses(data["haeuser"], heat_pump["levels"]),
    }


def load(path: str | Path | None = None) -> dict:
    """Validated parameters (cached per path)."""
    return _load(str(Path(path) if path else resolve_path()))
