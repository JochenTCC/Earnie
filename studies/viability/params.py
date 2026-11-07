"""Load the house generator parameter file (``haeuser.json``) and fail loud on anything unexpected.

One file holds every value the generator uses: price year, assumptions, derivation rules, fuel
prices per year, heating systems, axes, scenario tariffs and the sample houses. Subscription
tiers and prices are business data and live outside this repository. Keys starting with ``_``
are comments.

The file is chosen by ``--params PATH`` on a script's command line, else the environment
variable ``EARNIE_STUDY_PARAMS``, else ``haeuser.json`` next to this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ENV_VAR = "EARNIE_STUDY_PARAMS"
DEFAULT_PATH = Path(__file__).resolve().parent / "haeuser.json"

_SECTIONS = {
    "preisjahr", "annahmen", "solver", "regeln", "brennstoffpreise", "heizsysteme", "achsen", "eauto_muster",
    "szenarien", "standard_szenarien", "stichproben", "netz", "geraete",
}
_GRID = {"snap_im_preisjahr"}
_APPLIANCES = {
    "aktiv", "seed", "fenster_start", "haeufungen", "haeufung_gewicht", "haeufung_breite_h", "geraete",
    "laeufe_je_woche",
}
_APPLIANCE_KEYS = {"kwh_je_lauf", "dauer_h"}
_ASSUMPTIONS = {
    "standort", "netzbereich", "pv_neigung_grad", "pv_performance_ratio", "akku_leistung_c",
    "akku_zell_wirkungsgrad", "akku_verschleiss_eur_pro_kwh", "ev_km_pro_jahr", "ev_kwh_pro_100km", "ev_akku_kwh",
    "ev_ziel_soc_prozent", "wallbox_kw", "wallbox_min_kw", "wallbox_phasen", "solltemperatur_c",
    "heizgrenze_c", "absenkung_c", "heizstab_kw", "kollektor_neigung_grad", "speicher_verlust_kw_pro_k",
}
_RULES = {
    "wohnflaeche_basis_m2", "wohnflaeche_je_person_m2", "bgf_faktor", "haushaltsstrom_kwh",
    "warmwasser_kwh_je_person_tag", "huellen", "heizlast_delta_t_k", "heizgradtage_kd",
    "heizlast_kw_je_person", "kollektor_m2_je_person", "speicher_basis_l",
    "speicher_l_je_m2_kollektor", "dach_geschosse", "dach_neigung_grad", "dach_nutzbar",
    "dach_m2_je_kwp", "pv_min_kwp",
}
_AXES = {
    "personen", "heizsystem", "huelle", "pv_kwp_je_mwh", "pv_belegung", "speicher_kwh_je_kwp", "eauto",
}
_HEATING_KEYS = {"quelle", "kollektor", "heizstab", "speicher", "huellen"}
_HOUSE_KEYS = _AXES | {"id", "szenarien"}
FUELS = {"gas", "pellets"}
HEAT_PUMP = "heat_pump"


class ParameterError(ValueError):
    """The parameter file is invalid."""


def _fail(where: str, message: str) -> None:
    raise ParameterError(f"{where}: {message}")


def _public(obj: Any, where: str) -> dict:
    if not isinstance(obj, dict):
        _fail(where, "Objekt erwartet")
    return {k: v for k, v in obj.items() if not str(k).startswith("_")}


def _exact_keys(obj: Any, allowed: set[str], where: str) -> dict:
    data = _public(obj, where)
    unknown, missing = sorted(set(data) - allowed), sorted(allowed - set(data))
    if unknown:
        _fail(where, f"unbekannte Schluessel {unknown}")
    if missing:
        _fail(where, f"fehlende Schluessel {missing}")
    return data


def validate_heating_system(system: dict, where: str) -> None:
    """A heat pump with a heating rod is not an allowed configuration (decided 2026-11-06)."""
    if system["quelle"] == HEAT_PUMP and system["heizstab"]:
        _fail(where, "Waermepumpe mit Heizstab ist keine erlaubte Konfiguration")


def validate_house(raw: Any, doc: dict, where: str) -> dict:
    """Axis values of one house; an invalid combination fails here."""
    data = _public(raw, where)
    unknown = sorted(set(data) - _HOUSE_KEYS)
    missing = sorted((_AXES | {"id"}) - set(data))
    if unknown:
        _fail(where, f"unbekannte Schluessel {unknown}")
    if missing:
        _fail(where, f"fehlende Schluessel {missing}")
    axes = doc["achsen"]
    for axis in _AXES:
        if data[axis] not in axes[axis]:
            _fail(f"{where}.{axis}", f"{data[axis]!r} ist keine Stufe der Achse {axes[axis]}")
    system = doc["heizsysteme"][data["heizsystem"]]
    if data["huelle"] not in system["huellen"]:
        _fail(where, f"{data['heizsystem']} gibt es nur mit Huelle {system['huellen']}, nicht {data['huelle']}")
    scenarios = data.get("szenarien", doc["standard_szenarien"])
    unknown_scenarios = sorted(set(scenarios) - set(doc["szenarien"]))
    if unknown_scenarios or not scenarios:
        _fail(f"{where}.szenarien", f"ungueltig: {scenarios}")
    return {**data, "szenarien": list(scenarios)}


def _validated_appliances(raw: Any, persons: list[int]) -> dict:
    data = _exact_keys(raw, _APPLIANCES, "geraete")
    specs = {
        name: _exact_keys(spec, _APPLIANCE_KEYS, f"geraete.geraete.{name}")
        for name, spec in _public(data["geraete"], "geraete.geraete").items()
    }
    data["geraete"] = specs
    first, last = data["fenster_start"]
    if not 0 <= first <= last <= 23:
        _fail("geraete.fenster_start", f"ungueltig: {data['fenster_start']}")
    per_week = _public(data["laeufe_je_woche"], "geraete.laeufe_je_woche")
    data["laeufe_je_woche"] = {
        str(count): _exact_keys(per_week.get(str(count)), set(specs), f"geraete.laeufe_je_woche.{count}")
        for count in persons
    }
    for count, values in data["laeufe_je_woche"].items():
        for name, runs in values.items():
            if not 0 < runs < 7:
                _fail(f"geraete.laeufe_je_woche.{count}.{name}", f"{runs} ist nicht zwischen 0 und 7")
    return data


def validate(doc: Any) -> dict:
    data = _exact_keys(doc, _SECTIONS, "haeuser.json")
    data["annahmen"] = _exact_keys(data["annahmen"], _ASSUMPTIONS, "annahmen")
    data["regeln"] = _exact_keys(data["regeln"], _RULES, "regeln")
    data["solver"] = _exact_keys(data["solver"], {"cbc_gap_rel", "cbc_strict_time_limit_sec"}, "solver")
    data["achsen"] = _exact_keys(data["achsen"], _AXES, "achsen")
    data["szenarien"] = _public(data["szenarien"], "szenarien")
    data["netz"] = _exact_keys(data["netz"], _GRID, "netz")
    data["geraete"] = _validated_appliances(data["geraete"], data["achsen"]["personen"])
    data["heizsysteme"] = {
        sid: _exact_keys(system, _HEATING_KEYS, f"heizsysteme.{sid}")
        for sid, system in _public(data["heizsysteme"], "heizsysteme").items()
    }
    for sid, system in data["heizsysteme"].items():
        if system["quelle"] not in FUELS | {HEAT_PUMP}:
            _fail(f"heizsysteme.{sid}.quelle", f"{system['quelle']!r} unbekannt")
        if (system["heizstab"] or system["kollektor"]) and not system["speicher"]:
            _fail(f"heizsysteme.{sid}", "Heizstab und Kollektor brauchen einen Waermespeicher")
        validate_heating_system(system, f"heizsysteme.{sid}")
    data["brennstoffpreise"] = {
        year: _exact_keys(prices, FUELS, f"brennstoffpreise.{year}")
        for year, prices in _public(data["brennstoffpreise"], "brennstoffpreise").items()
    }
    data["eauto_muster"] = _public(data["eauto_muster"], "eauto_muster")
    for name in data["achsen"]["eauto"]:
        if name not in data["eauto_muster"]["fahrzeuge"]:
            _fail("eauto_muster.fahrzeuge", f"Stufe {name!r} fehlt")
    if str(data["preisjahr"]) not in data["brennstoffpreise"]:
        _fail("brennstoffpreise", f"keine Preise fuer das Preisjahr {data['preisjahr']}")
    houses = [validate_house(h, data, f"stichproben[{i}]") for i, h in enumerate(data["stichproben"])]
    ids = [h["id"] for h in houses]
    if len(ids) != len(set(ids)):
        _fail("stichproben", "doppelte id")
    data["stichproben"] = houses
    return data


def resolve_path() -> Path:
    raw = os.environ.get(ENV_VAR, "").strip()
    return Path(raw) if raw else DEFAULT_PATH


def load(path: str | Path | None = None) -> dict:
    file = Path(path) if path else resolve_path()
    if not file.is_file():
        raise ParameterError(f"Parameterdatei nicht gefunden: {file}")
    try:
        return validate(json.loads(file.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ParameterError(f"{file} ist kein gueltiges JSON: {exc}") from exc
