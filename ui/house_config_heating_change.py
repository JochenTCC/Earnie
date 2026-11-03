"""Hauskonfigurator: warning before a reference-system change is saved.

Design ``docs/dev/heating-system-variants.md`` § Decision (changing the reference system). A
change of ``heat_source.type`` of the referenced catalog entry, compared with the saved house
file, holds the auto-save while the house has consumption data from the old system:

- measured CSV data: remove the CSV data or keep the heating system;
- only ``annual_kwh``: adjust the annual consumption (confirm the value in the form) or keep
  the heating system.

There is no third option. Heat-pump type, efficiency, power, storage and rod are calibration
and save without a warning; a change reverted before saving is no change.
"""
from __future__ import annotations

import streamlit as st

from ui.house_config_historical_csv import session_keys
from ui.house_config_profile_session import _SESSION_CONSUMERS_KEY, _scoped_key

_ACCEPT_PREFIX = "house_heating_change_ok::"
# Heat-source widgets of the „Heizsystem“ section (ui/house_config_profile_thermal_annual.py).
_HEAT_SOURCE_WIDGETS = (
    "hc_heat_source_{index}",
    "hc_wp_{index}",
    "hc_heat_eff_use_{index}",
    "hc_heat_eff_{index}",
    "hc_fuel_price_use_{index}",
    "hc_fuel_price_{index}",
)


def _type_label(source_type: str) -> str:
    from ui.house_config_profile_thermal_annual import _HEAT_SOURCE_LABELS

    return _HEAT_SOURCE_LABELS.get(source_type, source_type)


def _kwh(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _token(change: dict) -> str:
    return f"{change['consumer_id']}:{change['old_heat_source'].get('type')}->{change['new_type']}"


def _pending_change(
    *, is_new: bool, profile_id: str, resolved: list[dict]
) -> dict | None:
    if is_new:
        return None
    from house_config.heating_systems import (
        load_heating_systems_for_house,
        read_raw_json,
        reference_heat_source_changes,
    )
    from runtime_store.persist_paths import resolve_house_profiles_json_path

    path = resolve_house_profiles_json_path()
    changes = reference_heat_source_changes(
        resolved,
        saved_house_doc=read_raw_json(path),
        heating_systems=load_heating_systems_for_house(path),
        profile_id=profile_id,
    )
    return changes[0] if changes else None


def _accept(accept_key: str, token: str) -> None:
    st.session_state[accept_key] = token


def _remove_csv_data(
    accept_key: str, token: str, preview_id: str, index: int, use_key: str
) -> None:
    """Drop the measured data of the old system: house load CSVs and the consumer's meter."""
    from ui.house_config_historical_modes import _component_upload_keys

    keys = session_keys(preview_id)
    for name in ("verbrauch", "battery", "grid"):
        st.session_state[keys[name]] = ""
        # The path inputs re-sync from their pending key before they render.
        st.session_state[_component_upload_keys(keys[name])["pending"]] = ""
    consumers = st.session_state.get(_SESSION_CONSUMERS_KEY) or []
    if index < len(consumers):
        consumers[index]["use_profile_csv"] = False
    # The checkbox re-seeds from the consumer.
    st.session_state.pop(use_key, None)
    _accept(accept_key, token)


def _keep_heating_system(session_scope: str, index: int, old_heat_source: dict) -> None:
    """Restore the saved heat source in the form (widgets re-seed from the consumer)."""
    consumers = st.session_state.get(_SESSION_CONSUMERS_KEY) or []
    if index < len(consumers):
        consumer = consumers[index]
        consumer["heat_source"] = dict(old_heat_source)
        if isinstance(consumer.get("thermal"), dict):
            consumer["thermal"]["heat_source"] = dict(old_heat_source)
    for pattern in _HEAT_SOURCE_WIDGETS:
        st.session_state.pop(_scoped_key(session_scope, pattern.format(index=index)), None)


def render_reference_change_gate(
    *,
    session_scope: str,
    is_new: bool,
    profile_id: str,
    annual_kwh: float,
    resolved: list[dict],
    hist: dict,
    preview_id: str,
) -> bool:
    """Warning with the two choices; True while the change holds the auto-save."""
    from house_config.heating_systems import consumption_data_kind

    accept_key = _ACCEPT_PREFIX + session_scope
    change = _pending_change(is_new=is_new, profile_id=profile_id, resolved=resolved)
    if change is None:
        st.session_state.pop(accept_key, None)
        return False
    token = _token(change)
    if st.session_state.get(accept_key) == token:
        return False
    kind = consumption_data_kind(
        {"annual_kwh": annual_kwh, "consumers": resolved, **hist}, change["consumer_id"]
    )
    if kind is None:
        return False
    old_label = _type_label(str(change["old_heat_source"].get("type")))
    new_label = _type_label(change["new_type"])
    index = int(change["index"])
    if kind == "csv":
        st.warning(
            f"Heizsystem geändert ({old_label} → {new_label}), noch nicht gespeichert: Die "
            f"CSV-Messdaten des Hauses stammen vom bisherigen Heizsystem ({old_label}) und "
            "passen nicht zum neuen. Messdaten entfernen oder Heizsystem beibehalten."
        )
        keep_col, change_col = st.columns(2)
        change_col.button(
            "Messdaten entfernen",
            key=_scoped_key(session_scope, "house_heating_change_remove_csv"),
            on_click=_remove_csv_data,
            args=(
                accept_key,
                token,
                preview_id,
                index,
                _scoped_key(session_scope, f"hc_use_profile_csv_{index}"),
            ),
        )
    else:
        st.warning(
            f"Heizsystem geändert ({old_label} → {new_label}), noch nicht gespeichert: Der "
            f"Jahresverbrauch ({_kwh(annual_kwh)} kWh/a) gilt für das bisherige Heizsystem "
            f"({old_label}). Jahresverbrauch oben an das neue Heizsystem anpassen und "
            "übernehmen, oder Heizsystem beibehalten. Ist der Wert schon eine Schätzung für "
            "das neue Heizsystem (z. B. Neubau), ihn unverändert übernehmen."
        )
        keep_col, change_col = st.columns(2)
        change_col.button(
            "Jahresverbrauch übernehmen",
            key=_scoped_key(session_scope, "house_heating_change_accept_annual"),
            on_click=_accept,
            args=(accept_key, token),
        )
    keep_col.button(
        "Heizsystem beibehalten",
        key=_scoped_key(session_scope, "house_heating_change_keep"),
        on_click=_keep_heating_system,
        args=(session_scope, index, change["old_heat_source"]),
    )
    return True
