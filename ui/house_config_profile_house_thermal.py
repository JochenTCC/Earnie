"""House-profile section „Gebäude / Wärmebedarf“ with the switch „Heizung betrachten“.

The building's thermal properties belong to the house (``house_config.house_thermal``). Off
(default for a new house): the section's fields and the „Haus Wärme“ consumer are hidden and
not planned; the stored values are kept and come back when the switch is turned on again.
"""
from __future__ import annotations

import streamlit as st

from house_config.house_thermal import (
    HEATING_ENABLED_KEY,
    HOUSE_THERMAL_KEY,
    PERSONS_KEY,
    default_house_thermal,
)
from house_config.profile_schema_defaults import profile_default
from house_config.thermal_labels import building_class_option_label
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
)
from ui.house_config_profile_session import _scoped_key

# Run-local copy of the section's values for the consumer forms rendered after it.
_STATE_KEY = "house_heating_state"
_MASS_LABELS = {
    "leicht": "Leicht (50 Wh/m²K)",
    "mittel": "Mittel (90 Wh/m²K)",
    "schwer": "Schwer (130 Wh/m²K)",
}


def house_heating_state(session_scope: str) -> dict:
    """Values of the section in this run (``heating_enabled``, ``persons``, ``thermal``)."""
    state = st.session_state.get(_scoped_key(session_scope, _STATE_KEY))
    if not isinstance(state, dict):
        raise RuntimeError(
            "Hausprofil: Abschnitt „Gebäude / Wärmebedarf“ muss vor den Verbrauchern rendern."
        )
    return state


def thermal_preview_fields(state: dict) -> dict:
    """Building fields of a „Haus Wärme“ preview (kWh/a), as the loader places them."""
    from house_config.house_thermal import consumer_thermal_from_house

    thermal = state.get(HOUSE_THERMAL_KEY) or default_house_thermal()
    return consumer_thermal_from_house(thermal, int(state[PERSONS_KEY]))


def _render_building_fields(stored: dict, *, session_scope: str) -> dict:
    from optimizer.thermal_house import BUILDING_MASS_C_WH_PER_M2K

    out: dict = {
        "living_area_m2": float(
            labeled_number_input(
                "Wohnfläche (m²)",
                min_value=0.0,
                value=float(stored["living_area_m2"]),
                key=_scoped_key(session_scope, "house_thermal_area"),
            )
        ),
    }
    out["building_class"] = int(
        labeled_selectbox(
            "Gebäudeklasse",
            options=[1, 2, 3, 4],
            index=int(stored["building_class"]) - 1,
            format_func=building_class_option_label,
            key=_scoped_key(session_scope, "house_thermal_class"),
        )
    )
    mass_options = list(BUILDING_MASS_C_WH_PER_M2K.keys())
    out["building_mass"] = labeled_selectbox(
        "Bauweise (Wärmespeicher)",
        options=mass_options,
        index=mass_options.index(stored["building_mass"]),
        format_func=lambda key: _MASS_LABELS.get(key, key),
        key=_scoped_key(session_scope, "house_thermal_mass"),
    )
    st.caption(
        "DIN V 18599-2: wirksame Wärmekapazität C = Wert × Wohnfläche "
        "(für Aufheizen/Auskühlen in Übergangszeiten)."
    )
    use_exact_hwb = labeled_checkbox(
        "Genaue HWB-Angabe",
        value="hwb_kwh_m2" in stored,
        key=_scoped_key(session_scope, "house_thermal_hwb_use"),
    )
    if use_exact_hwb:
        from data.heating_need import specific_heating_kwh_m2

        default_hwb = float(
            stored.get("hwb_kwh_m2") or specific_heating_kwh_m2(out["building_class"])
        )
        out["hwb_kwh_m2"] = float(
            labeled_number_input(
                "HWB (kWh/m²a)",
                min_value=0.1,
                value=default_hwb,
                step=1.0,
                key=_scoped_key(session_scope, "house_thermal_hwb"),
            )
        )
    return out


def _render_comfort_fields(stored: dict, out: dict, *, session_scope: str) -> None:
    out["target_temp_c"] = float(
        labeled_number_input(
            "Solltemperatur (°C)",
            value=float(stored["target_temp_c"]),
            step=0.5,
            key=_scoped_key(session_scope, "house_thermal_target_temp"),
        )
    )
    out["house_tolerance_c"] = float(
        labeled_number_input(
            "Heizband Toleranz (K)",
            min_value=0.05,
            value=float(stored["house_tolerance_c"]),
            step=0.1,
            key=_scoped_key(session_scope, "house_thermal_tolerance"),
        )
    )
    out["heating_limit_c"] = float(
        labeled_number_input(
            "Heizgrenze (°C Außentemperatur)",
            value=float(stored["heating_limit_c"]),
            step=0.5,
            help="Oberhalb dieser Tagesmitteltemperatur wird nicht geheizt.",
            key=_scoped_key(session_scope, "house_thermal_heating_limit"),
        )
    )
    h_value = float(stored.get("house_heat_loss_kw_per_k") or 0.0)
    h_input = labeled_number_input(
        "Haus-Verlustkoeffizient H (kW/K, 0 = auto aus HWB)",
        min_value=0.0,
        value=h_value,
        step=0.01,
        format="%.3f",
        key=_scoped_key(session_scope, "house_thermal_h"),
    )
    if float(h_input) > 0.0:
        out["house_heat_loss_kw_per_k"] = float(h_input)
    out["absent_mode_enabled"] = bool(
        labeled_checkbox(
            "Absenken wenn abwesend",
            value=bool(stored["absent_mode_enabled"]),
            key=_scoped_key(session_scope, "house_thermal_absent_use"),
            help=(
                "Bei wirksamem Abwesenheitsmodus (Live): Solltemperatur − Absenkung, "
                "Warmwasser 0."
            ),
        )
    )
    out["absent_temp_reduction_c"] = float(
        labeled_number_input(
            "Temperaturabsenkung wenn abwesend (K)",
            min_value=0.0,
            value=float(stored["absent_temp_reduction_c"]),
            step=0.5,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, "house_thermal_absent_reduction"),
        )
    )


def render_house_heating_section(*, session_scope: str, existing: dict, persons: int) -> dict:
    """Switch plus building fields; returns ``heating_enabled``, ``persons``, ``thermal``.

    ``persons`` comes from the field „Personen im Haushalt“ next to the Jahresverbrauch (SUSI
    P6). ``thermal`` is ``None`` for a house that never had the section on. With the switch
    off the stored block passes through unchanged.
    """
    st.subheader("Gebäude / Wärmebedarf")
    enabled = bool(
        labeled_checkbox(
            "Heizung betrachten",
            value=bool(existing.get(HEATING_ENABLED_KEY, profile_default(HEATING_ENABLED_KEY))),
            key=_scoped_key(session_scope, "house_heating_enabled"),
            help=(
                "Ein: Earnie plant die Heizung (Verbraucher „Haus Wärme“) mit den "
                "Gebäudedaten dieses Abschnitts. Aus: Heizung wird nicht geplant, ihr "
                "Verbrauch bleibt in der Grundlast; eingegebene Werte bleiben gespeichert."
            ),
        )
    )
    stored_thermal = existing.get(HOUSE_THERMAL_KEY)
    if not enabled:
        st.caption(
            "Heizung wird nicht betrachtet: kein Verbraucher „Haus Wärme“, der "
            "Heizungsverbrauch bleibt in der Grundlast."
        )
        state = {
            HEATING_ENABLED_KEY: False,
            PERSONS_KEY: int(persons),
            HOUSE_THERMAL_KEY: stored_thermal,
        }
    else:
        stored = stored_thermal or default_house_thermal()
        thermal = _render_building_fields(stored, session_scope=session_scope)
        _render_comfort_fields(stored, thermal, session_scope=session_scope)
        state = {
            HEATING_ENABLED_KEY: True,
            PERSONS_KEY: int(persons),
            HOUSE_THERMAL_KEY: thermal,
        }
    st.session_state[_scoped_key(session_scope, _STATE_KEY)] = state
    return state


def house_heating_payload(state: dict) -> dict:
    """Profile keys of the section for the house-profile save."""
    out = {HEATING_ENABLED_KEY: state[HEATING_ENABLED_KEY], PERSONS_KEY: state[PERSONS_KEY]}
    if state.get(HOUSE_THERMAL_KEY) is not None:
        out[HOUSE_THERMAL_KEY] = dict(state[HOUSE_THERMAL_KEY])
    return out
