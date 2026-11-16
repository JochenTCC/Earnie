"""EHAL read kinds of the heat pump / heat store (``thermal_annual`` consumer).

One list for mapping UI, Live-Lesen, signal export and recording. All kinds are stored on
the consumer's ``ehal_bindings`` and exchange as ``heatpump.<Kennung>.<kind>``.

Levels follow ``docs/dev/heat-control-sg-ready.md`` § 6. Level 3 (feedback) is read-only;
no kind here is required. The store band function is in ``ehal.functions``
(``heat_storage_band``).
"""
from __future__ import annotations

KIND_STORE_TEMP_EQ = "sens_temperature_heat_storage"
KIND_STORE_TEMP_LOW = "sens_temperature_heat_storage_low"

KIND_OPERATING_MODE = "sens_operating_mode"
KIND_SG_READY_STATE = "sens_sg_ready_state"
KIND_HEAT_POWER = "sens_heat_power"
KIND_SOURCE_TEMP = "sens_temperature_source"
KIND_STORE_TEMP_TOP = "sens_temperature_heat_storage_top"
KIND_DHW_TEMP = "sens_temperature_dhw"
KIND_ROOM_TEMP = "sens_temperature_room"
KIND_STORE_SETPOINT = "get_temperature_heat_storage_setpoint"
KIND_STORE_TOLERANCE = "get_temperature_heat_storage_tolerance"
KIND_STORE_MAX = "get_temperature_heat_storage_max"
KIND_DHW_MIN = "get_temperature_dhw_min"
KIND_ROOM_SETPOINT = "get_temperature_room_setpoint"

# Level 0 (today): store temperatures.
HEAT_STORE_TEMP_KINDS: tuple[str, ...] = (KIND_STORE_TEMP_EQ, KIND_STORE_TEMP_LOW)

# Level 3: feedback (HeatControl P1). Order = display order.
HEAT_FEEDBACK_KINDS: tuple[str, ...] = (
    KIND_STORE_TEMP_TOP,
    KIND_STORE_SETPOINT,
    KIND_STORE_TOLERANCE,
    KIND_STORE_MAX,
    KIND_OPERATING_MODE,
    KIND_SG_READY_STATE,
    KIND_HEAT_POWER,
    KIND_SOURCE_TEMP,
    KIND_DHW_TEMP,
    KIND_DHW_MIN,
    KIND_ROOM_TEMP,
    KIND_ROOM_SETPOINT,
)

# The two kinds of the function ``heat_storage_band`` (Live plans with the backend's band).
HEAT_STORE_BAND_KINDS: tuple[str, ...] = (KIND_STORE_SETPOINT, KIND_STORE_TOLERANCE)

THERMAL_ANNUAL_READ_KINDS: tuple[str, ...] = HEAT_STORE_TEMP_KINDS + HEAT_FEEDBACK_KINDS

# Level 1: operating state (HeatControl P2). Written on the consumer's ``ehal_bindings``
# as ``heatpump.<Kennung>.set_sg_ready_state``; optional next to ``set_enable``.
KIND_SET_SG_READY_STATE = "set_sg_ready_state"

# SG-Ready states Earnie sends. 1 (lock) waits for decision O2. 4 (forced charge, HeatControl
# P5): the plan runs the generator on a negative price or on surplus that would be curtailed.
SG_READY_NORMAL = 2
SG_READY_CHARGE = 3
SG_READY_FORCED_CHARGE = 4

# Level 2: store charge target (HeatControl P3), °C; 0 = no target. Written on the
# consumer's ``ehal_bindings`` as ``heatpump.<Kennung>.set_temperature_heat_storage_target``.
KIND_SET_STORE_TARGET = "set_temperature_heat_storage_target"


def sg_ready_state_for_plan(charges: bool, *, forced: bool = False) -> int:
    """State for one slot: 3 where the plan runs the generator, otherwise 2.

    Level 1 is today's enable in SG-Ready terms: enable 1 ↔ state 3, enable 0 ↔ state 2.
    ``forced``: a planned run on a negative price or on curtailed surplus is state 4.
    """
    if not charges:
        return SG_READY_NORMAL
    return SG_READY_FORCED_CHARGE if forced else SG_READY_CHARGE


# ``sens_operating_mode``: what the controller requests (not whether the compressor runs).
OPERATING_MODES: dict[int, str] = {
    0: "off",
    1: "space_heating",
    2: "hot_water",
    3: "defrost",
    4: "locked",
    5: "cooling",
    6: "fault",
}

# German labels for the mapping UI (HITL).
HEAT_FIELD_LABELS_DE: dict[str, str] = {
    KIND_STORE_TEMP_EQ: "Wärmespeicher T_eq (°C)",
    KIND_STORE_TEMP_LOW: "Wärmespeicher T_low (°C)",
    KIND_STORE_TEMP_TOP: "Wärmespeicher oberster Fühler (°C)",
    KIND_STORE_SETPOINT: "Wärmespeicher Soll der Regelung (°C)",
    KIND_STORE_TOLERANCE: "Wärmespeicher Toleranz der Regelung (K)",
    KIND_STORE_MAX: "Wärmespeicher Maximaltemperatur (°C)",
    KIND_OPERATING_MODE: "Betriebsart (0 aus … 6 Störung)",
    KIND_SG_READY_STATE: "SG-Ready-Zustand der Regelung (1–4)",
    KIND_HEAT_POWER: "Wärmeleistung (W)",
    KIND_SOURCE_TEMP: "Quellentemperatur (°C)",
    KIND_DHW_TEMP: "Warmwasserspeicher Temperatur (°C)",
    KIND_DHW_MIN: "Warmwasser Komfort-Minimum (°C)",
    KIND_ROOM_TEMP: "Raumtemperatur (°C)",
    KIND_ROOM_SETPOINT: "Raum-Solltemperatur (°C)",
}
