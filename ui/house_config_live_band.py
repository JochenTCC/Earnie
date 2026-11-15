"""House configurator: note that Live takes the heat-store band from the backend (HeatControl P1)."""
from __future__ import annotations

from typing import Literal

from ehal.heat_fields import (
    HEAT_STORE_BAND_KINDS,
    KIND_STORE_SETPOINT,
    KIND_STORE_TOLERANCE,
)

NoteLevel = Literal["info", "warning"]


def live_band_override_note(consumer: dict) -> tuple[NoteLevel, str] | None:
    """Note for the store band fields; ``None`` when the backend reports no band."""
    from optimizer.thermal_live_band import heat_storage_band_state
    from ui.number_format import format_general

    state, missing = heat_storage_band_state(consumer)
    if state == "not_configured":
        return None
    if state == "incomplete":
        return (
            "warning",
            "Das Speicherband der Regelung ist nur teilweise gemappt (es fehlt: "
            f"{', '.join(missing)}). Live plant deshalb mit Soll und Toleranz von hier.",
        )
    from integrations.ehal_live import fetch_heat_feedback

    values = fetch_heat_feedback(consumer, kinds=HEAT_STORE_BAND_KINDS)
    unread = [kind for kind in HEAT_STORE_BAND_KINDS if values.get(kind) is None]
    if unread:
        return (
            "warning",
            "Live plant mit dem Speicherband der Regelung, nicht mit Soll und Toleranz von "
            f"hier. Gerade liefert {', '.join(unread)} aber keinen Wert – Live meldet dann "
            "einen Fehler, statt mit den Werten von hier zu planen.",
        )
    return (
        "info",
        "Live plant mit dem Speicherband der Regelung: aktuell Soll "
        f"{format_general(values[KIND_STORE_SETPOINT])} °C, Toleranz "
        f"{format_general(values[KIND_STORE_TOLERANCE])} K. Soll und Toleranz von hier "
        "gelten für den Szenario-Explorer.",
    )


def render_live_band_override(consumer: dict) -> None:
    import streamlit as st

    note = live_band_override_note(consumer)
    if note is None:
        return
    level, text = note
    (st.info if level == "info" else st.warning)(text)
