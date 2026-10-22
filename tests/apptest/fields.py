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


# --- Verbraucher-Gruppen im Hausprofil -------------------------------------
# ``entity`` = Verbraucher-id, ``profile_key`` = Pfad im Verbraucher (Punkt-getrennt).
# Widget-Keys: ``test_home__hc_g0_<suffix>`` (g0 = Widget-Generation, Index = Position
# in der Verbraucherliste: wp=0, wasch=1, ev1=2, pool=3).

def _cons(entity, kind, suffix, key, valid, boundaries=()):
    return Field(kind, suffix, key, valid, boundaries=boundaries, entity=entity)


CONSUMER_FIELDS = [
    # Haus Wärme (thermal_annual)
    _cons("wp", "number_input", "nom_0", "nominal_power_kw", 4.5),
    _cons("wp", "number_input", "ta_min_qh_0", "min_on_quarterhours", 6),
    _cons("wp", "number_input", "area_0", "living_area_m2", 150.0),
    _cons("wp", "number_input", "persons_0", "persons", 4, boundaries=(1,)),
    _cons("wp", "number_input", "target_temp_0", "target_temp_c", 22.5),
    _cons("wp", "number_input", "house_tol_0", "house_tolerance_c", 1.5),
    _cons("wp", "number_input", "house_h_0", "house_heat_loss_kw_per_k", 0.2),
    _cons("wp", "number_input", "absent_temp_red_0", "absent_temp_reduction_c", 8.0),
    _cons("wp", "number_input", "solar_area_0", "solar_thermal_area_m2", 5.0),
    _cons("wp", "number_input", "solar_tilt_0", "solar_thermal_tilt_deg", 30),
    _cons("wp", "number_input", "solar_azimuth_0", "solar_thermal_azimuth_deg", 15),
    _cons("wp", "number_input", "storage_vol_0", "heat_storage.volume_liters", 200.0),
    _cons("wp", "checkbox", "absent_opt_in_0", "absent_mode_enabled", True),
    # Allgemein (generic) mit Zeitplan
    _cons("wasch", "number_input", "nom_1", "nominal_power_kw", 3.0),
    _cons("wasch", "number_input", "runs_1", "schedule.runs_per_week", 4, boundaries=(1, 7)),
    _cons("wasch", "number_input", "duration_1", "schedule.duration_h", 3.0),
    _cons("wasch", "number_input", "start_1", "schedule.start_hour", 11, boundaries=(0, 23)),
    _cons("wasch", "number_input", "shift_1", "schedule.start_shift_h", 2.0),
    _cons("wasch", "checkbox", "absent_opt_in_1", "absent_mode_enabled", True),
    # E-Auto (ev)
    _cons("ev1", "number_input", "nom_2", "nominal_power_kw", 12.0),
    _cons("ev1", "number_input", "ev_min_2", "min_power_kw", 1.0),
    _cons("ev1", "number_input", "ev_min_qh_2", "min_on_quarterhours", 5),
    _cons("ev1", "number_input", "ev_cap_2", "battery_capacity_kwh", 55.0),
    _cons("ev1", "number_input", "ev_target_soc_2", "charging_schedule.target_soc_percent", 80.0),
    _cons("ev1", "number_input", "ev_eff_2", "charging_schedule.charging_efficiency", 0.9),
    _cons("ev1", "number_input", "ev_voltage_2", "charging_schedule.nominal_power_voltage_v", 235.0),
    _cons("ev1", "number_input", "ev_phases_2", "charging_schedule.nominal_power_phases", 3),
    _cons("ev1", "number_input", "ev_Werktag_from_2", "charging_schedule.weekday.car_available_from_hour", 16),
    _cons("ev1", "number_input", "ev_Werktag_ready_2", "charging_schedule.weekday.ready_by_hour", 8),
    _cons("ev1", "number_input", "ev_Werktag_soc_2", "charging_schedule.weekday.daily_rest_soc", 21.0),
    _cons("ev1", "number_input", "ev_Wochenende_from_2", "charging_schedule.weekend.car_available_from_hour", 19),
    _cons("ev1", "number_input", "ev_Wochenende_ready_2", "charging_schedule.weekend.ready_by_hour", 9),
    _cons("ev1", "number_input", "ev_Wochenende_soc_2", "charging_schedule.weekend.daily_rest_soc", 31.0),
    _cons("ev1", "checkbox", "ev_forecast_2", "charging_schedule.forecast_when_absent", False),
    _cons("ev1", "checkbox", "ev_bidirectional_2", "bidirectional", True),
    _cons("ev1", "checkbox", "absent_opt_in_2", "absent_mode_enabled", True),
    # Temperatur (thermal_rc)
    _cons("pool", "number_input", "nom_3", "nominal_power_kw", 3.0),
    _cons("pool", "number_input", "rc_min_qh_3", "min_on_quarterhours", 9),
    _cons("pool", "number_input", "rc_vol_3", "thermal_rc.water_volume_liters", 1500.0),
    _cons("pool", "number_input", "rc_set_3", "thermal_rc.setpoint_c", 26.0),
    _cons("pool", "number_input", "rc_tol_3", "thermal_rc.tolerance_c", 2.0),
    _cons("pool", "number_input", "rc_u_3", "thermal_rc.heat_loss_kw_per_k", 0.5),
    _cons("pool", "number_input", "rc_eff_3", "thermal_rc.heating_efficiency", 0.8),
    _cons("pool", "checkbox", "absent_opt_in_3", "absent_mode_enabled", True),
]


# --- Szenarienkonfigurator --------------------------------------------------
# ``entity`` = Szenario-id (= Key-Präfix ``<id>__``), ``profile_key`` = Pfad im Szenario.
# ``valid`` ist der Widget-Wert (Anzeige-Label bei Selectbox/Multiselect); ``stored`` der
# erwartete Dateiwert, ``ABSENT`` wenn der Schlüssel danach fehlen muss.
# Land- und Typ-Filter sind reine UI-Filter und werden nicht gespeichert.

ABSENT = "<absent>"
SCENARIO_ID = "entity_test"
SCENARIO_RADIO_LABEL = "Entitäten-Referenzen Test"


def _scen(kind, suffix, key, valid, stored=None, boundaries=()):
    return Field(kind, suffix, key, valid, boundaries=boundaries, entity=SCENARIO_ID, stored=stored)


SCENARIO_FIELDS = [
    _scen("text_input", "scenario_label", "label", "Neu Ünï – 日本 🏠"),
    _scen("text_input", "scenario_label", "label", "S"),
    _scen("checkbox", "scenario_enabled", "enabled", False),
    _scen("checkbox", "scenario_own_reference", "own_reference", True),
    _scen("selectbox", "scenario_import", "settings.import_tariff_id",
          "aWATTar Österreich", stored="awattar_at"),
    _scen("selectbox", "scenario_profile", "settings.house_profile_id",
          "— keine —", stored=ABSENT),
    _scen("multiselect", "scenario_battery", "settings.battery_ids", [], stored=ABSENT),
    _scen("multiselect", "scenario_pv", "settings.pv_system_ids", [], stored=ABSENT),
]
