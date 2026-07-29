"""Reusable Streamlit fields for Smarthome-Merker role ↔ address assignments."""
from __future__ import annotations

from ui.form_layout import WIDE_LABEL_RATIOS, labeled_text_input

# Role key → German UI label (address string stays Loxone Miniserver name).
EV_CHARGING_LOXONE_FIELDS: tuple[tuple[str, str], ...] = (
    ("plugged_in_name", "Merker: Angeschlossen"),
    ("soc_at_plug_in_name", "Merker: Rest-SOC bei Anschluss"),
    ("actual_soc_name", "Merker: Ist-SOC"),
    ("ready_by_time_name", "Merker: Fertig-Uhrzeit"),
    ("nominal_power_kw_name", "Merker: max. Ladeleistung"),
    ("battery_capacity_kwh_name", "Merker: Akkukapazität"),
    ("charge_immediate_name", "Merker: Sofort-Laden"),
    ("charge_immediate_remaining_name", "Merker: Restzeit Sofortladen"),
)

THERMAL_CONTROL_LOXONE_FIELDS: tuple[tuple[str, str], ...] = (
    ("actual_temp_name", "Merker: Ist-Temperatur"),
    ("setpoint_temp_name", "Merker: Soll-Temperatur"),
    ("ambient_temp_name", "Merker: Außentemperatur"),
    ("tolerance_c_name", "Merker: Toleranz"),
    ("heating_active_name", "Merker: Heizung aktiv"),
)

LOXONE_BLOCKS_FIELDS: tuple[tuple[str, str], ...] = (
    ("soc_name", "Batterie-SOC (Lesen)"),
    ("pv_power_name", "PV-Leistung (Lesen)"),
    ("battery_power_name", "Batterie-Leistung (Lesen)"),
    ("grid_power_name", "Netz-Leistung (Lesen)"),
    ("target_charge_power_name", "Ziel-Ladeleistung (Schreiben)"),
    ("target_discharge_power_name", "Ziel-Entladeleistung (Schreiben)"),
    ("control_cmd_name", "Steuerbefehl (Schreiben)"),
)


def render_marker_text(
    label: str,
    value: object,
    *,
    key: str,
) -> str:
    """Labeled text input; returns stripped address or empty string."""
    return str(
        labeled_text_input(
            label,
            value=str(value or ""),
            ratios=WIDE_LABEL_RATIOS,
            key=key,
        )
    ).strip()


def collect_named_markers(
    source: dict,
    fields: tuple[tuple[str, str], ...],
    *,
    key_prefix: str,
) -> dict[str, str]:
    """Render fields and return non-empty role→address map."""
    out: dict[str, str] = {}
    for role, label in fields:
        marker = render_marker_text(
            label,
            source.get(role, ""),
            key=f"{key_prefix}_{role}",
        )
        if marker:
            out[role] = marker
    return out


def compact_str_dict(data: dict | None) -> dict:
    """Drop empty string values from a shallow dict."""
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if not (isinstance(value, str) and not value.strip())
    }


def _nested_dict(root: dict | None, *keys: str) -> dict:
    current: object = root
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return dict(current) if isinstance(current, dict) else {}


def filter_binding_prefills(stored: dict, defaults: dict) -> dict[str, str]:
    """Resolve UI prefills for SwimSpa-filter marker roles."""
    def_inputs = _nested_dict(defaults, "loxone_inputs")
    def_outputs = _nested_dict(defaults, "loxone_outputs")
    def_sched = _nested_dict(defaults, "filter_schedule", "loxone")
    cur_inputs = _nested_dict(stored, "loxone_inputs")
    cur_outputs = _nested_dict(stored, "loxone_outputs")
    cur_sched = _nested_dict(stored, "filter_schedule", "loxone")

    def _pref(cur: dict, default: dict, role: str) -> str:
        return str(cur.get(role) or default.get(role) or "")

    return {
        "loxone_target_hours_name": str(
            stored.get("loxone_target_hours_name")
            or defaults.get("loxone_target_hours_name")
            or ""
        ),
        "power_name": _pref(cur_inputs, def_inputs, "power_name"),
        "alternate_binary_power_name": _pref(
            cur_inputs, def_inputs, "alternate_binary_power_name"
        ),
        "enable_name": _pref(cur_outputs, def_outputs, "enable_name"),
        "native_start_hour_name": _pref(
            cur_sched, def_sched, "native_start_hour_name"
        ),
        "native_duration_hours_name": _pref(
            cur_sched, def_sched, "native_duration_hours_name"
        ),
    }


def assemble_filter_bindings(values: dict[str, str]) -> dict:
    """Build swimspa_filter_bindings nest from edited marker addresses."""
    bindings: dict = {}
    target_hours = str(values.get("loxone_target_hours_name") or "").strip()
    if target_hours:
        bindings["loxone_target_hours_name"] = target_hours
    inputs: dict = {"signal_type": "binary"}
    power_name = str(values.get("power_name") or "").strip()
    alt_power = str(values.get("alternate_binary_power_name") or "").strip()
    if power_name:
        inputs["power_name"] = power_name
    if alt_power:
        inputs["alternate_binary_power_name"] = alt_power
    if len(inputs) > 1:
        bindings["loxone_inputs"] = inputs
    enable_name = str(values.get("enable_name") or "").strip()
    if enable_name:
        bindings["loxone_outputs"] = {"enable_name": enable_name}
    sched_lox: dict = {}
    native_start = str(values.get("native_start_hour_name") or "").strip()
    native_dur = str(values.get("native_duration_hours_name") or "").strip()
    if native_start:
        sched_lox["native_start_hour_name"] = native_start
    if native_dur:
        sched_lox["native_duration_hours_name"] = native_dur
    if sched_lox:
        bindings["filter_schedule"] = {"loxone": sched_lox}
    return bindings
