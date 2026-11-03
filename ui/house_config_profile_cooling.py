"""House-profile section „Kühlung“ with the switch „Kühlung betrachten“.

The air conditioning is the ``cooling`` block of the house's heating consumer
(``house_config.house_cooling``); the switch is independent of „Heizung betrachten“. It needs the
building block and the „Haus Wärme“ consumer (the house RC model), so a house that never had
heating on cannot switch cooling on yet. Off: the stored device is kept.
"""
from __future__ import annotations

import streamlit as st

from house_config.house_cooling import (
    COOLING_ENABLED_KEY,
    COOLING_KEY,
    COOLING_TYPE_HEAT_PUMP,
    COOLING_TYPE_SPLIT,
    cooling_seer_default,
    default_cooling,
    normalize_cooling,
)
from house_config.house_thermal import (
    HEATING_ENABLED_KEY,
    HOUSE_THERMAL_KEY,
    INACTIVE_CONSUMERS_KEY,
)
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
)
from ui.house_config_profile_session import _scoped_key

_TYPE_LABELS = {
    COOLING_TYPE_SPLIT: "Klimagerät (Split / Monoblock)",
    COOLING_TYPE_HEAT_PUMP: "Wärmepumpe kühlt (reversibel)",
}


def _heating_consumer(existing: dict) -> dict | None:
    for consumer in [
        *(existing.get("consumers") or []),
        *(existing.get(INACTIVE_CONSUMERS_KEY) or []),
    ]:
        if consumer.get("type") == "thermal_annual":
            return consumer
    return None


def _heat_source_type(consumer: dict) -> str:
    thermal = consumer.get("thermal") or consumer
    return str((thermal.get("heat_source") or {}).get("type") or "")


def _render_device_fields(stored: dict, *, heat_pump: bool, session_scope: str) -> dict:
    options = [COOLING_TYPE_SPLIT] + ([COOLING_TYPE_HEAT_PUMP] if heat_pump else [])
    current = stored["type"] if stored["type"] in options else COOLING_TYPE_SPLIT
    cooling_type = labeled_selectbox(
        "Gerät",
        options=options,
        index=options.index(current),
        format_func=lambda value: _TYPE_LABELS[value],
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "house_cooling_type"),
        help=(
            "Klimagerät: eigenes Gerät. Wärmepumpe: die Wärmepumpe des Heizsystems kühlt "
            "(nur mit Wärmepumpe als Wärmequelle)."
        ),
    )
    seer_value = (
        float(stored["seer"])
        if cooling_type == stored["type"]
        else cooling_seer_default(cooling_type)
    )
    seer = labeled_number_input(
        "Kälteleistungszahl SEER",
        min_value=0.5,
        max_value=15.0,
        value=seer_value,
        step=0.1,
        ratios=WIDE_LABEL_RATIOS,
        # Per type: switching the device shows that type's default, not the other's value.
        key=_scoped_key(session_scope, f"house_cooling_seer_{cooling_type}"),
        help="Kälte je kWh Strom über die Saison (Datenblatt). Ohne Angabe gilt ein typischer Wert.",
    )
    power = labeled_number_input(
        "Kälteleistung (kW)",
        min_value=0.5,
        max_value=50.0,
        value=float(stored["cooling_power_kw"]),
        step=0.5,
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "house_cooling_power"),
        help="Thermische Kälteleistung, nicht die Stromaufnahme.",
    )
    setpoint = labeled_number_input(
        "Kühlen ab Raumtemperatur (°C)",
        min_value=18.0,
        max_value=32.0,
        value=float(stored["setpoint_c"]),
        step=0.5,
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "house_cooling_setpoint"),
    )
    return normalize_cooling(
        {
            "type": cooling_type,
            "seer": float(seer),
            "cooling_power_kw": float(power),
            "setpoint_c": float(setpoint),
        },
        label="Kühlung",
        heat_source={"type": "heat_pump"} if heat_pump else None,
    )


def render_house_cooling_section(*, session_scope: str, existing: dict, heating: dict) -> dict:
    """Switch plus device fields; returns ``cooling_enabled`` and the ``cooling`` block.

    The block is ``None`` for a house without a stored device and the switch off.
    """
    st.subheader("Kühlung")
    carrier = _heating_consumer(existing)
    stored = (carrier or {}).get(COOLING_KEY)
    ready = carrier is not None and heating.get(HOUSE_THERMAL_KEY) is not None
    enabled = bool(
        labeled_checkbox(
            "Kühlung betrachten",
            value=ready and bool(existing.get(COOLING_ENABLED_KEY, False)),
            key=_scoped_key(session_scope, "house_cooling_enabled"),
            disabled=not ready,
            help=(
                "Ein: eine Klimaanlage kühlt das Hausmodell; ihr Strom ist ein fester "
                "Verbraucher und wird von der Grundlast abgezogen. Unabhängig von "
                "„Heizung betrachten“."
            ),
        )
    )
    if not ready:
        st.caption(
            "Kühlung braucht das Hausmodell: einmal „Heizung betrachten“ einschalten und "
            "„Gebäude / Wärmebedarf“ ausfüllen. Danach lässt sich die Heizung wieder ausschalten."
        )
        return {COOLING_ENABLED_KEY: False, COOLING_KEY: stored}
    if not enabled:
        st.caption("Kühlung wird nicht betrachtet; ein eingetragenes Gerät bleibt gespeichert.")
        return {COOLING_ENABLED_KEY: False, COOLING_KEY: stored}
    block = _render_device_fields(
        stored or default_cooling(),
        heat_pump=_heat_source_type(carrier) == "heat_pump",
        session_scope=session_scope,
    )
    return {COOLING_ENABLED_KEY: True, COOLING_KEY: block}


def with_cooling(consumers: list[dict], cooling: dict) -> list[dict]:
    """Consumers with the section's device on the „Haus Wärme“ row (saved with the consumer)."""
    block = cooling.get(COOLING_KEY)
    out: list[dict] = []
    for consumer in consumers:
        if consumer.get("type") == "thermal_annual":
            consumer = {k: v for k, v in consumer.items() if k != COOLING_KEY}
            if block is not None:
                consumer[COOLING_KEY] = dict(block)
        out.append(consumer)
    return out


def cooling_preview_kwh(
    resolved: list[dict], *, heating: dict, cooling: dict, preview_carrier
) -> float:
    """Annual electricity of the air conditioning for the form's current values (0 when off)."""
    if not cooling.get(COOLING_ENABLED_KEY):
        return 0.0
    from optimizer.house_cooling import cooling_annual_electric_kwh

    carriers = [preview_carrier(c) for c in resolved if c.get("type") == "thermal_annual"]
    stub = {
        COOLING_ENABLED_KEY: True,
        HEATING_ENABLED_KEY: bool(heating[HEATING_ENABLED_KEY]),
        "consumers": carriers,
    }
    return cooling_annual_electric_kwh(stub)


def render_cooling_metric(kwh: float) -> None:
    if kwh > 0.0:
        st.caption(f"Klimaanlage im Hausmodell: {kwh:.0f} kWh/a Strom.")
