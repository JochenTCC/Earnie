"""HITL: Energieflussmonitor / Zähler → Hausprofil consumers (2.4.l)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.loxone_efm_meters import (
    apply_consumer_imports,
    apply_plant_power_suggestions,
    extract_efm_meters,
    propose_consumer_imports,
)
from integrations.loxone_structure import fetch_loxapp3_json
from ui.ehal_loxone_mapping import (
    consumers_for_profile,
    resolve_live_profile_id,
)
from ui.house_config_io import load_house_profiles, save_house_profiles

_SESSION_PROPOSALS = "ehal_efm_proposals"


def _action_label(action: str) -> str:
    return {
        "create": "Neu anlegen",
        "match": "Vorhanden (aktualisieren)",
        "skip_plant": "Anlage (kein Verbraucher)",
        "skip_residual": "Rest → Basislast",
        "skip_group": "Gruppe (übersprungen)",
    }.get(action, action)


def _load_proposals(profile_id: str) -> list[dict[str, Any]]:
    doc = fetch_loxapp3_json(
        host=str(config.get("LOXONE_IP") or ""),
        username=str(config.get("LOXONE_USER") or ""),
        password=str(config.get("LOXONE_PASS") or ""),
        timeout_sec=30.0,
    )
    house = load_house_profiles()
    existing = consumers_for_profile(house, profile_id)
    candidates = extract_efm_meters(doc)
    return [p.as_dict() for p in propose_consumer_imports(candidates, existing)]


def _render_proposal_rows(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    st.caption(
        "CSV-Export bleibt manuell (Einzelserie). "
        "`flex.enable_name` / `flex.power_setpoint_name` kommen nicht vom Zähler."
    )
    for idx, row in enumerate(proposals):
        action = str(row.get("action") or "")
        name = str(row.get("name") or "")
        cols = st.columns([3, 2, 1, 1])
        with cols[0]:
            st.markdown(f"**{name}**  \n`{_action_label(action)}` · CSV-Stem `{row.get('csv_stem')}`")
        with cols[1]:
            st.caption(
                f"power=`{row.get('power_address') or '—'}`"
                + (f" · plant=`{row.get('plant_field')}`" if row.get("plant_field") else "")
            )
        include = False
        bind_power = False
        bind_plant = False
        with cols[2]:
            if action in {"create", "match"}:
                include = st.checkbox(
                    "Import",
                    value=action == "create",
                    key=f"efm_imp_{idx}",
                )
                bind_power = st.checkbox(
                    "flex.power_name",
                    value=True,
                    key=f"efm_pwr_{idx}",
                    disabled=not include,
                )
            elif action == "skip_plant":
                bind_plant = st.checkbox(
                    "Plant binden",
                    value=False,
                    key=f"efm_plant_{idx}",
                )
        with cols[3]:
            if action == "skip_residual":
                st.caption("kein Consumer")
        if include and action in {"create", "match"}:
            selected.append({**row, "bind_power": bind_power})
        elif bind_plant and action == "skip_plant":
            selected.append({**row, "bind_plant": True})
    return selected


def _persist_imports(profile_id: str, selected: list[dict[str, Any]]) -> int:
    house = load_house_profiles()
    house = apply_consumer_imports(house, profile_id=profile_id, selected=selected)
    house = apply_plant_power_suggestions(house, selected=selected)
    save_house_profiles(house)
    return sum(1 for row in selected if str(row.get("action") or "") in {"create", "match"})


def render_efm_consumer_import_section() -> None:
    """EHAL-Com expander: discover Zähler and import generic consumers."""
    st.caption(
        "LoxAPP3 Energieflussmonitor / Zähler → generische Verbraucher im Live-Hausprofil "
        "(optional `flex.power_name` = Zähler-Bezeichnung)."
    )
    house = load_house_profiles()
    profile_id = resolve_live_profile_id(house)
    if not profile_id:
        st.warning("Kein Live-Hausprofil — Import nicht möglich.")
        return
    if st.button("Zähler aus LoxAPP3 laden", key="efm_load_btn"):
        try:
            st.session_state[_SESSION_PROPOSALS] = _load_proposals(profile_id)
            st.success("Zähler geladen.")
        except Exception as exc:  # noqa: BLE001 — show Miniserver/auth errors in UI
            st.error(f"LoxAPP3-Laden fehlgeschlagen: {exc}")
            return
    proposals = list(st.session_state.get(_SESSION_PROPOSALS) or [])
    if not proposals:
        st.info("Noch keine Vorschläge — „Zähler aus LoxAPP3 laden“.")
        return
    selected = _render_proposal_rows(proposals)
    if st.button("Auswahl übernehmen", key="efm_apply_btn", type="primary"):
        if not selected:
            st.warning("Nichts ausgewählt.")
            return
        n = _persist_imports(profile_id, selected)
        st.success(f"{n} Verbraucher angelegt/aktualisiert (Plant-Felder falls gewählt).")
        st.session_state.pop(_SESSION_PROPOSALS, None)
        st.rerun()
