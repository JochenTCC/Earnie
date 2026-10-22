# tests/apptest/fields.py
"""Feldliste für die parametrisierten Persistenztests (Ebene 1, T1-T3).

Ein neues Feld braucht nur eine neue Zeile hier, keinen neuen Test.
``suffix`` ist der Widget-Key ohne ``<profil-id>__``-Präfix (session_scope),
``profile_key`` der Schlüssel im geladenen Profil-Dokument.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Field:
    kind: str  # AppTest-Widget: text_input | number_input | checkbox | selectbox
    suffix: str
    profile_key: str
    valid: Any  # ein anderer als der Fixture-Wert
    boundaries: tuple = field(default_factory=tuple)
    # Gültige Typen, die die Seite fachlich ablehnen muss (T3): Fehlermeldung, Datei unverändert.
    rejected: tuple = field(default_factory=tuple)
    # Nur Komponenten-Formulare: Tab im Hauskonfigurator, Entitäts-id (= Key-Präfix)
    # und Sammlung in components.json. ``stored`` weicht ab, wenn die Datei einen
    # anderen Wert als das Widget hält (z. B. Selectbox-Label vs. Code).
    tab: str = ""
    entity: str = ""
    collection: str = ""
    stored: Any = None
    # Widget-Wert -> erwarteter Dateiwert (z. B. Prozent im Widget, Anteil in der Datei).
    to_stored: Any = None

    def expected_stored(self, widget_value):
        return self.to_stored(widget_value) if self.to_stored else widget_value

    @property
    def id(self) -> str:
        return self.suffix


HOUSE_PROFILE_FIELDS = [
    Field("text_input", "house_profile_label", "label", "Haus Müller – Zürich 🏠",
          boundaries=("A", "Ä" * 60)),
    Field("number_input", "house_annual_kwh", "annual_kwh", 5250.0,
          boundaries=(123456.0,),
          rejected=(0.0, 1.0)),
    Field("checkbox", "house_absent_mode", "absent_mode", True),
    Field("selectbox", "house_profile_land", "land", "DE"),
    Field("number_input", "house_profile_latitude", "latitude", 52.52,
          boundaries=(-60.0, 60.0)),
    Field("number_input", "house_profile_longitude", "longitude", 13.4,
          boundaries=(-179.0, 179.0)),
    Field("number_input", "house_profile_default_pv_tilt", "default_pv_tilt", 35,
          boundaries=(0, 90)),
    Field("number_input", "house_profile_default_pv_azimuth", "default_pv_azimuth", 45,
          boundaries=(-180, 180)),
]


def _comp(tab, entity, collection, kind, suffix, key, valid, boundaries=(), rejected=(), to_stored=None):
    return Field(kind, suffix, key, valid, boundaries=boundaries, rejected=rejected,
                 tab=tab, entity=entity, collection=collection, to_stored=to_stored)


_INV = ("Wechselrichter", "wr_main", "inverters")
_PV = ("PV-Felder", "test_pv", "pv_systems")
_BAT = ("Batterien", "test_battery", "batteries")

COMPONENT_FIELDS = [
    # Wechselrichter
    _comp(*_INV, "text_input", "planning_inv_label", "label", "Wechselrichter Ünï – 日本",
          boundaries=("W",)),
    _comp(*_INV, "number_input", "planning_inv_efficiency", "efficiency", 0.95,
          boundaries=(0.5, 1.0)),
    _comp(*_INV, "number_input", "planning_inv_max_ac", "max_ac_power_kw", 8.0,
          boundaries=(0.1, 1000.0)),
    _comp(*_INV, "number_input", "planning_inv_max_pv", "max_pv_input_kw", 10.0,
          boundaries=(0.1, 1000.0)),
    _comp(*_INV, "number_input", "planning_inv_max_charge", "max_ac_charge_kw", 3.0,
          boundaries=(0.1, 1000.0)),
    # PV-Felder
    _comp(*_PV, "text_input", "planning_pv_label", "label", "Süddach – 日本 ☀",
          boundaries=("P",)),
    _comp(*_PV, "number_input", "planning_pv_kwp", "kwp", 9.5,
          boundaries=(0.1, 1000.0)),
    _comp(*_PV, "number_input", "planning_pv_tilt", "pv_tilt", 35,
          boundaries=(0, 90)),
    _comp(*_PV, "number_input", "planning_pv_azimuth", "pv_azimuth", -45,
          boundaries=(-180, 180)),
    # Batterien
    _comp(*_BAT, "text_input", "planning_battery_label", "label", "Speicher Ünï – 日本 🔋",
          boundaries=("B",)),
    _comp(*_BAT, "number_input", "planning_battery_capacity", "battery_capacity_kwh", 12.5,
          boundaries=(0.5, 500.0)),
    _comp(*_BAT, "number_input", "planning_battery_charge_power", "battery_max_charge_power_kw", 5.5,
          boundaries=(0.1, 100.0)),
    _comp(*_BAT, "number_input", "planning_battery_discharge_power", "battery_max_discharge_power_kw", 6.5,
          boundaries=(0.1, 100.0)),
    _comp(*_BAT, "number_input", "planning_battery_efficiency", "battery_efficiency", 0.9,
          boundaries=(0.5, 1.0)),
    _comp(*_BAT, "number_input", "planning_battery_min_soc", "battery_min_soc", 15.0,
          boundaries=(0.0, 50.0)),
    _comp(*_BAT, "number_input", "planning_battery_max_soc", "battery_max_soc", 95.0,
          boundaries=(60.0, 100.0)),
    _comp(*_BAT, "number_input", "planning_battery_threshold", "threshold_power", 5.0,
          boundaries=(1.0, 100.0), to_stored=lambda percent: percent / 100.0),
    _comp(*_BAT, "checkbox", "planning_battery_limits_from_live", "limits_from_live", True),
]
