"""Consumer expander shell and type dispatch for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import (
    _SESSION_CONSUMERS_KEY,
    _clear_consumer_widget_keys,
    _consumer_type_options,
    _scoped_key,
    _type_index,
)
from ui.house_config_profile_generic import _render_generic_fields
from ui.house_config_profile_ev import _render_ev_fields, _seed_ev_defaults_on_type_switch
from ui.house_config_profile_thermal import (
    _consumer_expander_title,
    _render_thermal_annual_fields,
    _render_thermal_rc_fields,
)
from ui.house_config_profile_csv import _render_consumer_profile_csv_fields

import streamlit as st

from house_config.thermal_labels import CONSUMER_TYPE_LABELS
from ui.form_layout import (
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)
















































































def _render_consumer_form(
    consumer: dict,
    index: int,
    *,
    latitude: float,
    longitude: float,
    session_scope: str,
    default_pv_tilt: float = 18.0,
    default_pv_azimuth: float = 0.0,
) -> dict:
    expander_title, annual, c_type = _consumer_expander_title(
        consumer, index, session_scope=session_scope
    )
    # Expand first consumer only when it has no saved id yet (new/empty form).
    has_saved_data = bool(str(consumer.get("id") or "").strip())
    default_expanded = index == 0 and not has_saved_data
    # Stable open-state across label/annual/type remounts; suffix forces label refresh.
    open_key = _scoped_key(session_scope, f"hc_consumer_exp_open_{index}")
    exp_key = _scoped_key(
        session_scope,
        f"hc_consumer_expander_{index}_{int(round(annual))}_{c_type}",
    )
    if exp_key not in st.session_state and open_key in st.session_state:
        st.session_state[exp_key] = bool(st.session_state[open_key])
    exp_col, remove_col = st.columns([4, 1], vertical_alignment="top")
    with remove_col:
        if st.button(
            "Entfernen",
            key=_scoped_key(session_scope, f"hc_remove_{index}"),
        ):
            consumers = list(st.session_state[_SESSION_CONSUMERS_KEY])
            del consumers[index]
            st.session_state[_SESSION_CONSUMERS_KEY] = consumers
            _clear_consumer_widget_keys(session_scope)
            st.rerun()
    with exp_col:
        exp = st.expander(
            expander_title,
            expanded=bool(st.session_state.get(exp_key, default_expanded)),
            key=exp_key,
            on_change="rerun",
        )
        if exp.open is not None:
            st.session_state[open_key] = bool(exp.open)
        with exp:
            return _render_consumer_form_body(
                consumer,
                index,
                latitude=latitude,
                longitude=longitude,
                session_scope=session_scope,
                default_pv_tilt=default_pv_tilt,
                default_pv_azimuth=default_pv_azimuth,
            )
    # Unreachable when expander runs; keep type-checkers happy if body returns.
    return dict(consumer)

def _render_consumer_identity_fields(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> tuple[str, str, float]:
    type_options = _consumer_type_options(index)
    current_type = str(consumer.get("type", "generic"))
    if index > 0 and current_type == "thermal_annual":
        st.warning(
            "Typ „Haus Wärme“ ist nur für Verbraucher 1 erlaubt. "
            "Bitte einen anderen Typ wählen."
        )
    c_type = labeled_selectbox(
        "Typ",
        options=type_options,
        index=_type_index(current_type, type_options),
        format_func=lambda value: CONSUMER_TYPE_LABELS.get(value, value),
        key=_scoped_key(session_scope, f"hc_type_{index}"),
    )
    c_label = labeled_text_input(
        "Bezeichnung",
        value=consumer.get("label", ""),
        key=_scoped_key(session_scope, f"hc_label_{index}"),
    )
    nominal = labeled_number_input(
        "Nennleistung (kW)",
        min_value=0.0,
        value=float(consumer.get("nominal_power_kw", 0.0)),
        key=_scoped_key(session_scope, f"hc_nom_{index}"),
    )
    return c_type, c_label, float(nominal)


def _dispatch_consumer_type_fields(
    consumer: dict,
    index: int,
    c_type: str,
    nominal: float,
    *,
    session_scope: str,
    location: dict,
) -> dict:
    if c_type == "generic":
        return _render_generic_fields(
            consumer, index, nominal, session_scope=session_scope
        )
    if c_type == "ev":
        return _render_ev_fields(consumer, index, session_scope=session_scope)
    if c_type == "thermal_rc":
        return _render_thermal_rc_fields(consumer, index, session_scope=session_scope)
    return _render_thermal_annual_fields(
        consumer,
        index,
        session_scope=session_scope,
        location=location,
    )


def _render_consumer_form_body(
    consumer: dict,
    index: int,
    *,
    latitude: float,
    longitude: float,
    session_scope: str,
    default_pv_tilt: float = 18.0,
    default_pv_azimuth: float = 0.0,
) -> dict:
    consumer = _seed_ev_defaults_on_type_switch(
        consumer, index, session_scope=session_scope
    )
    c_type, c_label, nominal = _render_consumer_identity_fields(
        consumer, index, session_scope=session_scope
    )
    item: dict = {
        "label": c_label,
        "type": c_type,
        "nominal_power_kw": nominal,
    }
    item.update(
        _dispatch_consumer_type_fields(
            consumer,
            index,
            c_type,
            nominal,
            session_scope=session_scope,
            location={
                "latitude": latitude,
                "longitude": longitude,
                "default_pv_tilt": default_pv_tilt,
                "default_pv_azimuth": default_pv_azimuth,
            },
        )
    )
    item.update(
        _render_consumer_profile_csv_fields(
            consumer,
            index,
            session_scope=session_scope,
            nominal_power_kw=float(nominal),
        )
    )
    return item
