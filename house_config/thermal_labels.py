"""UI-Labels für thermische Planungs-Verbraucher."""
from __future__ import annotations

from data.heating_need import specific_heating_kwh_m2

CONSUMER_TYPE_LABELS = {
    "generic": "Allgemein",
    "thermal_annual": "Haus Wärme",
    "ev": "E-Auto",
}

BUILDING_CLASS_LABELS = {
    1: "Passivhaus",
    2: "Neubau",
    3: "Bestand",
    4: "Altbau",
}


def building_class_option_label(building_class: int) -> str:
    name = BUILDING_CLASS_LABELS.get(int(building_class), f"Klasse {building_class}")
    hwb = specific_heating_kwh_m2(int(building_class))
    return f"{building_class} — {name} (ca. {hwb:.0f} kWh/m²a)"
