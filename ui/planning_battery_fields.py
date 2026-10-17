"""Battery tab field renderers (core, limits, wear, inverter, Powerstation meta).

Split out of ``ui.planning_battery_form``.
"""
from __future__ import annotations

import streamlit as st

from house_config.battery_control import (
    BATTERY_CONTROL_VALUES,
    CONTROL_LABELS_DE,
    DEFAULT_BATTERY_CONTROL,
)
from house_config.powerstation import (
    BACKING_VIRTUAL,
    primary_house_battery,
    virtual_powerstation_fill_fields,
)
from house_config.topology_regulates import REGULATES_ON_GRID, REGULATES_ON_NONE
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_multiselect,
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)
from ui.house_config_io import list_batteries
from ui.planning_battery_inverter import (
    default_inverter_id_for_new_house,
    owned_inverter_for_battery,
    render_builtin_inverter_section,
    render_inverter_select,
)
from ui.planning_battery_state import _scoped_key



def _manual_consumer_options() -> tuple[list[str], dict[str, str]]:
    """Manual consumer ids from house profiles for Powerstation attachment."""
    from ui.house_config_io import load_house_profiles

    options: list[str] = [""]
    labels: dict[str, str] = {"": "— Verbraucher wählen —"}
    try:
        doc = load_house_profiles()
    except Exception:
        return options, labels
    # load_house_profiles_document normalizes profiles to dict[id → profile].
    raw_profiles = doc.get("profiles") or {}
    if isinstance(raw_profiles, dict):
        profile_iter = raw_profiles.values()
    elif isinstance(raw_profiles, list):
        profile_iter = raw_profiles
    else:
        profile_iter = []
    for profile in profile_iter:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            if str(consumer.get("earnie_role") or "").strip().lower() != "manual":
                continue
            cid = str(consumer.get("id") or "").strip()
            if not cid or cid in labels:
                continue
            options.append(cid)
            clabel = str(consumer.get("label") or cid).strip() or cid
            labels[cid] = f"{clabel} ({cid})"
    return options, labels


def _ensure_attached_options(
    options: list[str],
    labels: dict[str, str],
    current_ids: list[str],
) -> None:
    for cid in current_ids:
        if cid and cid not in options:
            options.append(cid)
            labels[cid] = f"{cid} (nicht in Hausprofil)"


def _render_attached_consumers(
    session_scope: str, *, backing: str
) -> list[str]:
    """Virtual: multi-select; physical: single consumer (one-way pack)."""
    attached_options, attached_labels = _manual_consumer_options()
    # Drop empty placeholder for multiselect; keep for single select.
    multi_options = [cid for cid in attached_options if cid]
    if backing == BACKING_VIRTUAL:
        current_ids = [
            str(cid).strip()
            for cid in (
                st.session_state.get(
                    _scoped_key(session_scope, "planning_battery_attached_ids"),
                    [],
                )
                or []
            )
            if str(cid or "").strip()
        ]
        _ensure_attached_options(multi_options, attached_labels, current_ids)
        # Session key seeded in _seed_battery_widget_state (no default= with key).
        selected = labeled_multiselect(
            "Angeschlossene Verbraucher",
            options=multi_options,
            format_func=lambda value: attached_labels.get(value, value or "—"),
            key=_scoped_key(session_scope, "planning_battery_attached_ids"),
            help="Virtuell: gemeinsame Energiereserve für mehrere manuelle Geräte.",
        )
        st.caption(
            "Powerstations nicht in Szenario-`battery_ids`. Mehrere Verbraucher "
            "teilen sich den Carve-out — oder Zuordnung unter Hausprofil → "
            "manuelles Gerät → Unterstützung „Energiereserve“."
        )
        return [str(cid).strip() for cid in (selected or []) if str(cid).strip()]

    current_attached = str(
        st.session_state.get(
            _scoped_key(session_scope, "planning_battery_attached"), ""
        )
        or ""
    ).strip()
    _ensure_attached_options(attached_options, attached_labels, [current_attached])
    index_default = (
        attached_options.index(current_attached)
        if current_attached in attached_options
        else 0
    )
    attached = labeled_selectbox(
        "Angeschlossener Verbraucher",
        options=attached_options,
        index=index_default,
        format_func=lambda value: attached_labels.get(value, value or "—"),
        key=_scoped_key(session_scope, "planning_battery_attached"),
        help="Physisch: ein Gerät pro One-Way-Pack.",
    )
    st.caption(
        "Powerstations nicht in Szenario-`battery_ids`. Verbraucher optional "
        "hier wählen — oder später unter Hausprofil → manuelles Gerät → "
        "Unterstützung „Energiereserve“ die Powerstation zuordnen "
        "(verknüpft automatisch)."
    )
    cid = str(attached or "").strip()
    return [cid] if cid else []


def _render_powerstation_meta(session_scope: str) -> tuple[str, str, list[str]]:
    """Backing / role / attached consumers. Returns (backing, role, ids)."""
    backing_label = labeled_selectbox(
        "Backing",
        options=["Virtuell (Carve-out)", "Physisch"],
        key=_scoped_key(session_scope, "planning_battery_backing"),
    )
    backing = "physical" if backing_label == "Physisch" else BACKING_VIRTUAL
    role_label = labeled_selectbox(
        "Rolle",
        options=["Single-use (manuell)", "Standby-Backup"],
        key=_scoped_key(session_scope, "planning_battery_role"),
        help=(
            "Standby-Backup (preisbewusste Mini-UPS für Dauerläufer) erfordert "
            "Backing „Physisch“ und EHAL-Quellenwahl (`ess.<id>.set_ess_source_select`). "
            "Virtuell wird zur Laufzeit ignoriert — ggf. globales SOC-Min der Hausbatterie erhöhen."
        ),
    )
    role = "standby_backup" if role_label == "Standby-Backup" else "single_use"
    if role == "standby_backup" and backing != "physical":
        st.warning(
            "Standby-Backup ist nur mit physischer Powerstation aktiv. "
            "Virtuelle Instanzen werden übersprungen (kein geschützter Floor)."
        )
    elif role == "standby_backup" and backing == "physical":
        from ui.setup_readiness import standby_backup_readiness_messages

        for msg in standby_backup_readiness_messages():
            if "Quellenwahl" in msg or "set_ess_source_select" in msg:
                st.info(msg)
                break
    attached_ids = _render_attached_consumers(session_scope, backing=backing)
    return backing, role, attached_ids


def _render_battery_power_efficiency(
    session_scope: str, *, bat_type: str
) -> tuple[float, float, float]:
    max_charge = labeled_number_input(
        "Max. Ladeleistung (kW)",
        min_value=0.1,
        step=0.1,
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "planning_battery_charge_power"),
    )
    discharge_kwargs: dict = {
        "min_value": 0.0 if bat_type == "powerstation" else 0.1,
        "step": 0.1,
        "ratios": WIDE_LABEL_RATIOS,
        "key": _scoped_key(session_scope, "planning_battery_discharge_power"),
    }
    if bat_type == "powerstation":
        discharge_kwargs["help"] = (
            "Bei physischer Powerstation 0 = kein Hausnetz-Rückspeisen."
        )
    max_discharge = labeled_number_input(
        "Max. Entladeleistung (kW)",
        **discharge_kwargs,
    )
    efficiency = labeled_number_input(
        "Wirkungsgrad Chemie (η_batt)",
        min_value=0.5,
        max_value=1.0,
        step=0.01,
        key=_scoped_key(session_scope, "planning_battery_efficiency"),
        help="Einweg-Faktor Zellchemie. Pfad η_path = η_inv · η_batt "
        "(η_inv am Wechselrichter).",
    )
    return max_charge, max_discharge, efficiency


def _virtual_ps_inherited_ui_fields(
    *,
    capacity: float,
    exclude_id: str = "",
) -> tuple[dict, dict | None]:
    """Map inherited JSON fields onto form keys; return (fields, primary_house)."""
    primary = primary_house_battery(list_batteries(), exclude_id=exclude_id)
    fill = virtual_powerstation_fill_fields(
        primary_house=primary,
        capacity_kwh=float(capacity or 0.0),
    )
    fields = {
        "max_charge": float(fill["battery_max_charge_power_kw"]),
        "max_discharge": float(fill["battery_max_discharge_power_kw"]),
        "efficiency": float(fill["battery_efficiency"]),
        "limits_from_live": bool(fill["limits_from_live"]),
        "min_soc": float(fill["battery_min_soc"]),
        "max_soc": float(fill["battery_max_soc"]),
        "threshold_percent": float(fill["threshold_power"]) * 100.0,
        "standby_power": float(fill["standby_power_kw"]),
        "control": fill["control"],
        "battery_wear": dict(fill["battery_wear"]),
        "inverter_id": "",
    }
    return fields, primary


def _render_battery_core_fields(session_scope: str) -> dict:
    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "planning_battery_label"),
    )
    type_label = labeled_selectbox(
        "Typ",
        options=["Hausbatterie", "Powerstation"],
        key=_scoped_key(session_scope, "planning_battery_type"),
    )
    bat_type = "powerstation" if type_label == "Powerstation" else "house"
    backing = BACKING_VIRTUAL
    role = "single_use"
    attached_ids: list[str] = []
    if bat_type == "powerstation":
        backing, role, attached_ids = _render_powerstation_meta(session_scope)
    is_virtual_ps = bat_type == "powerstation" and backing == BACKING_VIRTUAL
    capacity_kwargs: dict = {
        "min_value": 0.1,
        "step": 0.5,
        "key": _scoped_key(session_scope, "planning_battery_capacity"),
    }
    if is_virtual_ps:
        capacity_kwargs["help"] = "Max. Reserve / Carve-out auf der Hausbatterie."
    capacity = labeled_number_input("Kapazität (kWh)", **capacity_kwargs)
    attached_fields = {
        "attached_consumer_ids": list(attached_ids),
        "attached_consumer_id": attached_ids[0] if attached_ids else "",
    }
    if is_virtual_ps:
        return {
            "label": label,
            "type": bat_type,
            "backing": backing,
            "role": role,
            **attached_fields,
            "capacity": capacity,
            "is_virtual_ps": True,
        }
    max_charge, max_discharge, efficiency = _render_battery_power_efficiency(
        session_scope, bat_type=bat_type
    )
    return {
        "label": label,
        "type": bat_type,
        "backing": backing,
        "role": role,
        **attached_fields,
        "capacity": capacity,
        "max_charge": max_charge,
        "max_discharge": max_discharge,
        "efficiency": efficiency,
        "is_virtual_ps": False,
    }


def _render_battery_regulates_on(session_scope: str) -> str:
    regulates_labels = {
        REGULATES_ON_GRID: "Netz-Zähler (Eigenverbrauch / Zero-Export)",
        REGULATES_ON_NONE: "Keiner (nur Setpoints)",
    }
    regulates_label = labeled_selectbox(
        "Eigener Regler auf",
        options=list(regulates_labels.values()),
        help="Welche Messung der Geräteeigene Regler nutzt, wenn Earnie "
        "nicht zwingt (regulates_on). Unabhängig von Steuerbarkeit.",
        key=_scoped_key(session_scope, "planning_battery_regulates_on"),
    )
    label_to_regulates = {v: k for k, v in regulates_labels.items()}
    return label_to_regulates.get(str(regulates_label), REGULATES_ON_GRID)


def _render_battery_limit_fields(
    session_scope: str, *, bat_type: str = "house"
) -> dict:
    limits_from_live = labeled_checkbox(
        "Grenzwerte im Live-Betrieb vom Wechselrichter / Speicher übernehmen",
        help="SOC-Min/Max und Max. Lade-/Entladeleistung aus EHAL-Telemetrie "
        "(get_ess_*); sonst Hauskonfigurator. Fehlendes Mapping → HK-Fallback.",
        key=_scoped_key(session_scope, "planning_battery_limits_from_live"),
    )
    min_soc = labeled_number_input(
        "Minimaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        key=_scoped_key(session_scope, "planning_battery_min_soc"),
    )
    max_soc = labeled_number_input(
        "Maximaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        key=_scoped_key(session_scope, "planning_battery_max_soc"),
    )
    threshold_percent = labeled_number_input(
        "Leistungs-Schwelle (%)",
        min_value=1.0,
        max_value=100.0,
        help="Anteil der größeren von Max. Lade-/Entladeleistung.",
        key=_scoped_key(session_scope, "planning_battery_threshold"),
    )
    standby_power = labeled_number_input(
        "Standby-Leistung (kW)",
        min_value=0.0,
        step=0.01,
        help="Dauerhafte AC-Eigenleistung der Batterie (24/7 Verbrauch).",
        key=_scoped_key(session_scope, "planning_battery_standby"),
    )
    control_labels = [CONTROL_LABELS_DE[v] for v in sorted(BATTERY_CONTROL_VALUES)]
    control_label = labeled_selectbox(
        "Steuerbarkeit",
        options=control_labels,
        help="full = Zwangsladen/-entladen; limits_only = nur Grenzen; "
        "read_only = Eigenverbrauch ohne Setpoints.",
        key=_scoped_key(session_scope, "planning_battery_control"),
    )
    label_to_control = {v: k for k, v in CONTROL_LABELS_DE.items()}
    control = label_to_control.get(str(control_label), DEFAULT_BATTERY_CONTROL)
    out = {
        "limits_from_live": limits_from_live,
        "min_soc": min_soc,
        "max_soc": max_soc,
        "threshold_percent": threshold_percent,
        "standby_power": standby_power,
        "control": control,
    }
    if str(bat_type or "house").strip().lower() == "house":
        out["regulates_on"] = _render_battery_regulates_on(session_scope)
    return out


def _render_battery_wear_fields(session_scope: str) -> dict:
    wear_enabled = labeled_checkbox(
        "Verschleiß berücksichtigen",
        key=_scoped_key(session_scope, "planning_battery_wear_enabled"),
    )
    if not wear_enabled:
        return {"enabled": False}
    wear_replacement_cost = labeled_number_input(
        "Ersatzkosten (€)",
        min_value=0.01,
        step=50.0,
        key=_scoped_key(session_scope, "planning_battery_wear_replacement_cost"),
    )
    wear_expected_cycles = labeled_number_input(
        "Erwartete Vollzyklen",
        min_value=1.0,
        step=100.0,
        key=_scoped_key(session_scope, "planning_battery_wear_expected_cycles"),
    )
    wear_cycle_fraction = labeled_number_input(
        "Anteil zyklenbedingter Kosten",
        min_value=0.01,
        max_value=1.0,
        step=0.05,
        help="Rest wird als Kalenderalterung angenommen (nicht separat modelliert).",
        key=_scoped_key(session_scope, "planning_battery_wear_cycle_fraction"),
    )
    return {
        "enabled": True,
        "replacement_cost_euro": wear_replacement_cost,
        "expected_cycles": wear_expected_cycles,
        "cycle_cost_fraction": wear_cycle_fraction,
    }


def _render_battery_inverter_ui(
    session_scope: str,
    fields: dict,
    *,
    battery_id: str,
) -> tuple[str, dict | None]:
    """Return (inverter_id, optional builtin inverter payload)."""
    bat_type = str(fields.get("type") or "house").strip().lower()
    backing = str(fields.get("backing") or BACKING_VIRTUAL).strip().lower()
    if bat_type == "powerstation" and backing == BACKING_VIRTUAL:
        st.caption("Virtuelle Powerstation: kein eigener Wechselrichter.")
        return "", None
    if bat_type == "powerstation" and backing != BACKING_VIRTUAL:
        owned = owned_inverter_for_battery(battery_id)
        builtin = render_builtin_inverter_section(
            session_scope, battery_id=battery_id, inverter=owned
        )
        inv_id = str((owned or {}).get("id") or "").strip()
        return inv_id, builtin
    current = str(
        fields.get("inverter_id")
        or st.session_state.get(
            _scoped_key(session_scope, "planning_battery_inverter_id"), ""
        )
        or default_inverter_id_for_new_house()
    ).strip()
    inv_id = render_inverter_select(
        session_scope,
        battery_id=battery_id,
        current_id=current,
    )
    return inv_id, None


def _render_battery_fields(
    session_scope: str,
    *,
    exclude_id: str = "",
    battery_id: str = "",
) -> dict:
    fields = _render_battery_core_fields(session_scope)
    if fields.get("is_virtual_ps"):
        inherited, primary = _virtual_ps_inherited_ui_fields(
            capacity=float(fields.get("capacity") or 0.0),
            exclude_id=exclude_id,
        )
        fields.update(inherited)
        if primary is None:
            st.warning(
                "Virtuelle Powerstation braucht eine Hausbatterie als "
                "Carve-out-Basis. Fehlende Werte werden mit Standardwerten "
                "gefüllt."
            )
        else:
            house_label = str(
                primary.get("label") or primary.get("id") or "Hausbatterie"
            ).strip()
            st.caption(
                f"Lade-/Entladeleistung, Wirkungsgrad, SoC und Grenzen werden "
                f"von der Hausbatterie „{house_label}“ übernommen "
                f"(Carve-out, keine eigene Hardware)."
            )
        fields["inverter_id"] = ""
        fields["builtin_inverter"] = None
        return fields
    fields.update(
        _render_battery_limit_fields(
            session_scope, bat_type=str(fields.get("type") or "house")
        )
    )
    fields["battery_wear"] = _render_battery_wear_fields(session_scope)
    inv_id, builtin = _render_battery_inverter_ui(
        session_scope, fields, battery_id=battery_id
    )
    fields["inverter_id"] = inv_id
    fields["builtin_inverter"] = builtin
    return fields
