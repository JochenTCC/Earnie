"""Consumer expander shell and type dispatch for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import (
    _SESSION_CONSUMERS_KEY,
    _bump_consumer_widget_gen,
    _clear_consumer_widget_keys,
    _consumer_type_options,
    _other_consumers_have_thermal_annual,
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
from ui.house_config_profile_points import _render_points_fields

import streamlit as st

from house_config.entity_id_lock import (
    FORCE_ID_FROM_LABEL_KEY,
    ID_PROVISIONAL_LABEL_KEY,
    is_id_locked,
)
from house_config.house_gains import INTERNAL_GAIN_FACTOR_KEY, default_consumer_gain_factor
from house_config.id_slug import slug_id
from house_config.thermal_labels import CONSUMER_TYPE_LABELS
from ui.form_layout import (
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)
















































































def _render_consumer_form(
    consumer: dict,
    index: int,
    *,
    consumers: list[dict],
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
            session_consumers = list(st.session_state[_SESSION_CONSUMERS_KEY])
            del session_consumers[index]
            st.session_state[_SESSION_CONSUMERS_KEY] = session_consumers
            _bump_consumer_widget_gen(session_scope)
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
                consumers=consumers,
                latitude=latitude,
                longitude=longitude,
                session_scope=session_scope,
                default_pv_tilt=default_pv_tilt,
                default_pv_azimuth=default_pv_azimuth,
            )
    # Unreachable when expander runs; keep type-checkers happy if body returns.
    return dict(consumer)

def _render_consumer_id_from_label(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    label: str,
) -> bool:
    """One-shot: set frozen id from current Bezeichnung (existing ugly ids)."""
    stable_id = str(consumer.get("id") or "").strip()
    label_s = str(label or "").strip()
    if not label_s or not stable_id:
        return False
    desired = slug_id(label_s)
    if desired == stable_id:
        return False
    help_txt = (
        f"Aktuelle ID `{stable_id}` → aus Bezeichnung `{desired}` "
        "(EHAL-Slug; danach fest)."
    )
    return bool(
        st.button(
            "ID aus Bezeichnung übernehmen",
            key=_scoped_key(session_scope, f"hc_id_from_label_{index}"),
            help=help_txt,
        )
    )


def _render_consumer_identity_fields(
    consumer: dict,
    index: int,
    *,
    consumers: list[dict],
    session_scope: str,
) -> tuple[str, str, float, bool]:
    from ui.house_config_profile_house_thermal import house_heating_state

    type_options = _consumer_type_options(
        consumers,
        index,
        heating_enabled=bool(house_heating_state(session_scope)["heating_enabled"]),
    )
    current_type = str(consumer.get("type", "generic"))
    if (
        current_type == "thermal_annual"
        and _other_consumers_have_thermal_annual(consumers, index)
    ):
        st.warning(
            "Nur ein Verbraucher vom Typ „Haus Wärme“ ist erlaubt. "
            "Bitte einen anderen Typ wählen."
        )
    type_key = _scoped_key(session_scope, f"hc_type_{index}")
    label_key = _scoped_key(session_scope, f"hc_label_{index}")
    c_type = labeled_selectbox(
        "Typ",
        options=type_options,
        index=_type_index(current_type, type_options),
        format_func=lambda value: CONSUMER_TYPE_LABELS.get(value, value),
        key=type_key,
    )
    c_label = labeled_text_input(
        "Bezeichnung",
        value=consumer.get("label", ""),
        key=label_key,
    )
    force_id = _render_consumer_id_from_label(
        consumer, index, session_scope=session_scope, label=c_label
    )
    if c_type == "thermal_annual":
        # Generation field: rendered in the „Heizsystem“ section (same widget key).
        return c_type, c_label, float(consumer.get("nominal_power_kw", 0.0)), force_id
    if c_type == "ev":
        # Data model 6: the EV's power follows from its charge currents (EV fields).
        return c_type, c_label, 0.0, force_id
    nominal = labeled_number_input(
        "Nennleistung (kW)",
        min_value=0.0,
        value=float(consumer.get("nominal_power_kw", 0.0)),
        key=_scoped_key(session_scope, f"hc_nom_{index}"),
    )
    return c_type, c_label, float(nominal), force_id


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


def _render_internal_gain_factor(
    consumer: dict, c_type: str, index: int, *, session_scope: str
) -> float:
    """Share of the consumer's electric energy that heats the house (SUSI P2)."""
    stored = consumer.get(INTERNAL_GAIN_FACTOR_KEY)
    same_type = str(consumer.get("type") or "generic") == c_type
    value = (
        float(stored)
        if same_type and stored not in (None, "")
        else default_consumer_gain_factor(c_type, consumer.get("id"))
    )
    return float(
        labeled_number_input(
            "Interner Gewinn (Wärme)",
            min_value=0.0,
            max_value=1.0,
            value=value,
            step=0.1,
            # Type in the key: a type switch starts from the new type's default.
            key=_scoped_key(session_scope, f"hc_gain_{c_type}_{index}"),
            help=(
                "Anteil (0–1) der elektrischen Energie, der als Wärme im beheizten Haus landet "
                "und den Heizbedarf senkt. Haushaltsgeräte 0,8; E-Auto, Pool und Geräte außen 0."
            ),
        )
    )


def _render_consumer_form_body(
    consumer: dict,
    index: int,
    *,
    consumers: list[dict],
    latitude: float,
    longitude: float,
    session_scope: str,
    default_pv_tilt: float = 18.0,
    default_pv_azimuth: float = 0.0,
) -> dict:
    consumer = _seed_ev_defaults_on_type_switch(
        consumer, index, session_scope=session_scope
    )
    # Seed Bezeichnung for deferred id lock (new / unlocked entities).
    if not str(consumer.get("id") or "").strip() or not is_id_locked(consumer):
        seed = str(
            consumer.get(ID_PROVISIONAL_LABEL_KEY) or consumer.get("label") or ""
        ).strip()
        if seed and not str(consumer.get(ID_PROVISIONAL_LABEL_KEY) or "").strip():
            consumer[ID_PROVISIONAL_LABEL_KEY] = seed
    c_type, c_label, nominal, force_id = _render_consumer_identity_fields(
        consumer, index, consumers=consumers, session_scope=session_scope
    )
    item: dict = {
        "label": c_label,
        "type": c_type,
    }
    if c_type != "ev":
        item["nominal_power_kw"] = nominal
    # „Haus Wärme“: the absent-mode setback is a house setting („Gebäude / Wärmebedarf“).
    if c_type != "thermal_annual":
        item["absent_mode_enabled"] = labeled_checkbox(
            "Inaktiv wenn abwesend",
            value=bool(consumer.get("absent_mode_enabled", False)),
            key=_scoped_key(session_scope, f"hc_absent_opt_in_{index}"),
            help=(
                "Bei wirksamem Abwesenheitsmodus (Live): Verbraucher ohne "
                "Live-Optimierung. Die Heizungs-Absenkung steht im Abschnitt "
                "„Gebäude / Wärmebedarf“."
            ),
        )
    provisional = str(consumer.get(ID_PROVISIONAL_LABEL_KEY) or "").strip()
    has_id = bool(str(consumer.get("id") or "").strip())
    if provisional and (not has_id or not is_id_locked(consumer)):
        item[ID_PROVISIONAL_LABEL_KEY] = provisional
    if force_id:
        item[FORCE_ID_FROM_LABEL_KEY] = True
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
    item.update(_render_points_fields(consumer, index, c_type, session_scope=session_scope))
    item.update(
        _render_consumer_profile_csv_fields(
            consumer,
            index,
            session_scope=session_scope,
            nominal_power_kw=_form_power_kw(item),
        )
    )
    # Last field of every consumer form (all types except „Haus Wärme“).
    if c_type != "thermal_annual":
        item[INTERNAL_GAIN_FACTOR_KEY] = _render_internal_gain_factor(
            consumer, c_type, index, session_scope=session_scope
        )
    return item


def _form_power_kw(item: dict) -> float:
    """kW of the form item; an EV's is its pair maximum, 0 without a usable wallbox."""
    if item.get("type") == "ev":
        from ui.house_config_profile_ev import ev_form_pair

        pair = ev_form_pair(item)
        return float(pair["max_power_kw"]) if pair is not None else 0.0
    return float(item["nominal_power_kw"])
