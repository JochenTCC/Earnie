"""Battery form helpers: inverter select, built-in section, EcoFlow preset."""
from __future__ import annotations

import streamlit as st

from house_config.battery_control import (
    BATTERY_CONTROL_VALUES,
    CONTROL_LABELS_DE,
    DEFAULT_BATTERY_CONTROL,
)
from house_config.inverter import (
    AC_ISLAND,
    DEFAULT_INVERTER_EFFICIENCY,
    INVERTER_TYPE_HYBRID,
)
from house_config.inverter_presets import ecoflow_delta_3_seeds
from ui.form_layout import labeled_number_input, labeled_selectbox, labeled_text_input
from ui.house_config_io import list_inverters, upsert_battery, upsert_inverter
from ui.label_select import label_select_choices, resolve_label_select


def selectable_inverters_for_battery(
    *,
    battery_id: str = "",
) -> dict[str, dict]:
    """Inverters without owned_by, or owned by this battery."""
    bat = str(battery_id or "").strip()
    out: dict[str, dict] = {}
    for item in list_inverters():
        if not isinstance(item, dict):
            continue
        inv_id = str(item.get("id") or "").strip()
        if not inv_id:
            continue
        owned = str(item.get("owned_by") or "").strip()
        if owned and owned != bat:
            continue
        out[inv_id] = item
    return out


def owned_inverter_for_battery(battery_id: str) -> dict | None:
    bat = str(battery_id or "").strip()
    if not bat:
        return None
    for item in list_inverters():
        if not isinstance(item, dict):
            continue
        if str(item.get("owned_by") or "").strip() == bat:
            return item
    return None


def default_inverter_id_for_new_house() -> str:
    for item in list_inverters():
        if not isinstance(item, dict):
            continue
        if str(item.get("owned_by") or "").strip():
            continue
        return str(item.get("id") or "").strip()
    return ""


def render_inverter_select(
    session_scope: str,
    *,
    battery_id: str,
    current_id: str,
    widget_base: str = "planning_battery_inverter",
) -> str:
    """Return selected inverter_id (may be empty if catalog empty)."""
    inv_map = selectable_inverters_for_battery(battery_id=battery_id)
    inv_ids = sorted(inv_map.keys())
    if not inv_ids:
        st.warning(
            "Kein freier Wechselrichter vorhanden. Bitte zuerst unter "
            "Hauskonfigurator → Wechselrichter einen anlegen."
        )
        return ""
    options, id_by_display = label_select_choices(
        inv_map, inv_ids, new_option=None
    )
    key = f"{session_scope}__{widget_base}"
    current = str(current_id or "").strip()
    if current and current in inv_map:
        display_seed = str(inv_map[current].get("label") or current)
        if key not in st.session_state:
            st.session_state[key] = display_seed
    elif key not in st.session_state and options:
        st.session_state[key] = options[0]
    picked_display = labeled_selectbox(
        "Wechselrichter",
        options=options,
        key=key,
        help="PV und Batterie teilen sich denselben Wechselrichter über inverter_id.",
    )
    return resolve_label_select(picked_display, id_by_display)


def render_builtin_inverter_section(
    session_scope: str,
    *,
    battery_id: str,
    inverter: dict | None,
) -> dict | None:
    """Edit owned island inverter fields; return payload or None if missing."""
    st.subheader("Integrierter Wechselrichter")
    if not inverter:
        st.caption(
            "Wird beim Speichern einer physischen Powerstation automatisch angelegt."
        )
        return None
    inv_id = str(inverter.get("id") or "").strip()
    st.caption(f"Kennung `{inv_id}` · owned_by `{battery_id}` · AC = Insel")
    label = labeled_text_input(
        "WR-Bezeichnung",
        key=f"{session_scope}__planning_bat_inv_label",
    )
    control_labels = [CONTROL_LABELS_DE[v] for v in sorted(BATTERY_CONTROL_VALUES)]
    control_label = labeled_selectbox(
        "WR-Steuerbarkeit",
        options=control_labels,
        key=f"{session_scope}__planning_bat_inv_control",
    )
    label_to_control = {v: k for k, v in CONTROL_LABELS_DE.items()}
    control = label_to_control.get(str(control_label), DEFAULT_BATTERY_CONTROL)
    efficiency = labeled_number_input(
        "Wirkungsgrad DC↔AC (η_inv)",
        min_value=0.5,
        max_value=1.0,
        step=0.01,
        key=f"{session_scope}__planning_bat_inv_efficiency",
        help="Einweg-Faktor Wechselrichter (Teil des Speicher-Pfads η_inv · η_batt).",
    )
    max_ac = labeled_number_input(
        "Max. AC-Leistung (kW, 0 = kein Cap)",
        min_value=0.0,
        step=0.1,
        key=f"{session_scope}__planning_bat_inv_max_ac",
    )
    max_pv = labeled_number_input(
        "Max. PV-Eingang (kW, 0 = kein Cap)",
        min_value=0.0,
        step=0.1,
        key=f"{session_scope}__planning_bat_inv_max_pv",
    )
    payload: dict = {
        "id": inv_id,
        "label": label,
        "type": INVERTER_TYPE_HYBRID,
        "ac_connection": AC_ISLAND,
        "control": control,
        "efficiency": float(efficiency),
        "owned_by": battery_id,
        "ehal_bindings": dict(inverter.get("ehal_bindings") or {}),
    }
    if float(max_ac or 0.0) > 0.0:
        payload["max_ac_power_kw"] = float(max_ac)
    if float(max_pv or 0.0) > 0.0:
        payload["max_pv_input_kw"] = float(max_pv)
    return payload


def seed_builtin_inverter_widgets(session_scope: str, inverter: dict | None) -> None:
    if not inverter:
        return
    st.session_state[f"{session_scope}__planning_bat_inv_label"] = str(
        inverter.get("label") or inverter.get("id") or ""
    )
    control = str(inverter.get("control") or DEFAULT_BATTERY_CONTROL).strip().lower()
    if control not in BATTERY_CONTROL_VALUES:
        control = DEFAULT_BATTERY_CONTROL
    st.session_state[f"{session_scope}__planning_bat_inv_control"] = CONTROL_LABELS_DE[
        control
    ]
    efficiency = inverter.get("efficiency")
    st.session_state[f"{session_scope}__planning_bat_inv_efficiency"] = (
        float(efficiency)
        if efficiency not in (None, "")
        else DEFAULT_INVERTER_EFFICIENCY
    )
    max_ac = inverter.get("max_ac_power_kw")
    max_pv = inverter.get("max_pv_input_kw")
    st.session_state[f"{session_scope}__planning_bat_inv_max_ac"] = (
        float(max_ac) if max_ac not in (None, "") else 0.0
    )
    st.session_state[f"{session_scope}__planning_bat_inv_max_pv"] = (
        float(max_pv) if max_pv not in (None, "") else 0.0
    )


def persist_builtin_inverter(payload: dict | None, *, battery_id: str) -> None:
    if not payload or not battery_id:
        return
    upsert_inverter(payload, stable_id=str(payload.get("id") or "").strip())


def render_ecoflow_preset_button(*, is_new: bool) -> bool:
    """Create EcoFlow Delta 3 battery + owned island inverter. Returns True if ran."""
    if not is_new:
        return False
    if not st.button(
        "Vorlage: EcoFlow Delta 3",
        key="planning_battery_ecoflow_preset",
        help="Legt physische Powerstation + integrierten Insel-Hybrid-WR an.",
    ):
        return False
    battery, inverter = ecoflow_delta_3_seeds()
    try:
        # Battery first so owned_by topology validates; then enrich WR limits.
        bat_id = upsert_battery(battery, stable_id="")
        inv_id = str(battery.get("inverter_id") or "").strip()
        inv_payload = dict(inverter)
        inv_payload["owned_by"] = bat_id
        upsert_inverter(inv_payload, stable_id=inv_id)
    except ValueError as exc:
        st.error(str(exc))
        return False
    st.session_state["planning_battery_select_pending"] = bat_id
    st.session_state["planning_battery_sync_id"] = None
    st.success(f"EcoFlow Delta 3 angelegt (`{bat_id}`).")
    st.rerun()
    return True
