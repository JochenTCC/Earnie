"""Hand-written device presets: battery + owned island inverter (Inverter P2)."""
from __future__ import annotations

from house_config.inverter import (
    AC_ISLAND,
    DEFAULT_INVERTER_CONTROL,
    DEFAULT_INVERTER_EFFICIENCY,
    INVERTER_TYPE_HYBRID,
)


def ecoflow_delta_3_seeds(*, battery_id: str = "ecoflow_delta_3") -> tuple[dict, dict]:
    """Return (battery_spec, inverter_spec) seed dicts for EcoFlow Delta 3 style PS."""
    bat_id = str(battery_id or "").strip()
    if not bat_id:
        raise ValueError("battery_id fehlt für EcoFlow-Preset.")
    inv_id = f"wr_{bat_id}"
    battery = {
        "id": bat_id,
        "label": "EcoFlow Delta 3",
        "type": "powerstation",
        "backing": "physical",
        "role": "standby_backup",
        "battery_capacity_kwh": 1.024,
        "battery_max_charge_power_kw": 1.5,
        "battery_max_discharge_power_kw": 2.2,
        "battery_efficiency": 0.9,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "threshold_power": 0.03,
        "standby_power_kw": 0.02,
        "control": "full",
        "limits_from_live": True,
        "battery_wear": {"enabled": False},
        "ehal_bindings": {},
        "inverter_id": inv_id,
        "attached_consumer_ids": [],
        "attached_consumer_id": "",
    }
    inverter = {
        "id": inv_id,
        "label": "Insel-WR EcoFlow Delta 3",
        "type": INVERTER_TYPE_HYBRID,
        "ac_connection": AC_ISLAND,
        "control": DEFAULT_INVERTER_CONTROL,
        "efficiency": DEFAULT_INVERTER_EFFICIENCY,
        "owned_by": bat_id,
        "max_ac_power_kw": 1.8,
        "max_pv_input_kw": 0.5,
        "ehal_bindings": {},
    }
    return battery, inverter
