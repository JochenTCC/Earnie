"""Hausprofil tab: the field groups beside the consumers (location, grid, sun, heating,
cooling, absence) and the household size / reference lines.

Split from ``ui.house_config_profile_form``, which re-exports every name here.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.form_layout import form_group, labeled_checkbox, labeled_number_input
from ui.house_config_profile_session import _scoped_key
from ui.house_config_profile_thermal import (
    _render_location_core,
    _render_nne_arbeitspreis,
    _render_pv_default_row,
)


def _render_household_size(existing: dict, *, session_scope: str) -> dict:
    """Personen im Haushalt next to the Jahresverbrauch; the reference line follows later.

    Returns ``persons`` and ``slot``, a container filled by ``_render_household_reference``
    once the consumers (and their annual kWh) are known.
    """
    from house_config.house_thermal import PERSONS_KEY
    from house_config.profile_schema_defaults import profile_default

    persons = int(
        labeled_number_input(
            "Personen im Haushalt",
            min_value=1,
            value=int(existing.get(PERSONS_KEY, profile_default(PERSONS_KEY))),
            help=(
                "Für den Richtwert Haushaltsstrom und den Warmwasserbedarf der Heizung."
            ),
            key=_scoped_key(session_scope, "house_persons"),
        )
    )
    return {"persons": persons, "slot": st.container()}


def _render_household_reference(
    household: dict,
    annual_kwh: float,
    preview_consumers: list,
    heating: dict,
    *,
    cooling_kwh: float = 0.0,
) -> None:
    """SUSI P6: household electricity of the profile vs. the reference value per persons."""
    from house_config.household_reference import (
        DEVIATION_WARN_FRACTION,
        household_comparison,
    )

    persons = household["persons"]
    comparison = household_comparison(
        annual_kwh, persons, preview_consumers, cooling_kwh=cooling_kwh
    )
    deviation_pct = int(round(comparison["deviation"] * 100))
    reference = comparison["reference_kwh"]
    persons_text = f"{persons} Person" if persons == 1 else f"{persons} Personen"
    with household["slot"]:
        if annual_kwh <= 0.0:
            st.caption(
                f"Richtwert Haushaltsstrom (SUSI, {persons_text}): {reference:.0f} kWh/a."
            )
            return
        excluded = ""
        if comparison["excluded_labels"]:
            excluded = (
                f" ohne {', '.join(comparison['excluded_labels'])} "
                f"({comparison['excluded_kwh']:.0f} kWh/a)"
            )
        st.caption(
            f"Haushaltsstrom laut Profil: {comparison['household_kwh']:.0f} kWh/a "
            f"(Jahresverbrauch{excluded}) · Richtwert (SUSI, {persons_text}): "
            f"{reference:.0f} kWh/a · Abweichung {deviation_pct:+d} %"
        )
        if not heating["heating_enabled"]:
            st.caption(
                "„Heizung betrachten“ ist aus: ein Heizungsstrom ist im Haushaltsstrom "
                "enthalten."
            )
        if comparison["warn"]:
            st.warning(
                f"Der Haushaltsstrom weicht um {deviation_pct:+d} % vom Richtwert "
                f"für {persons_text} ab (mehr als ±{DEVIATION_WARN_FRACTION * 100:.0f} %). "
                "Jahresverbrauch, Personenzahl und Verbraucher prüfen."
            )


# Groups of the Hausprofil tab (docs/dev/house-profile-layout.md, stage 1). The keys give
# each group a stable identity, so a changing status in the title keeps it open or closed.
GROUP_KEYS = {
    "consumption": "house_profile_group_consumption",
    "location": "house_profile_group_location",
    "grid": "house_profile_group_grid",
    "sun": "house_profile_group_sun",
    "heating": "house_profile_group_heating",
    "cooling": "house_profile_group_cooling",
    "consumers": "house_profile_group_consumers",
    "absence": "house_profile_group_absence",
}
# „Historische Messdaten (CSV)“: ``ui.house_config_historical_csv._HISTORY_GROUP_KEY``.


def _session_value(session_scope: str, name: str, default=None):
    """Value of a scoped form widget as of this run (before the widget renders)."""
    return st.session_state.get(_scoped_key(session_scope, name), default)


def _on_off(enabled: bool) -> str:
    return "an" if enabled else "aus"


def _render_location_group(session_scope: str) -> dict:
    with form_group("Standort", key=GROUP_KEYS["location"], expanded=True, required=True):
        return _render_location_core(session_scope=session_scope)


def _render_grid_group(session_scope: str, location: dict) -> None:
    """Group „Netzanschluss & Netzentgelt“: Netzbereich, then the plant-wide settings."""
    from ui.house_config_plant import (
        render_plant_export_limit,
        render_plant_grid_meter_assertions,
    )

    with form_group(
        "Netzanschluss & Netzentgelt", key=GROUP_KEYS["grid"], expanded=True, required=True
    ):
        location["netznutzung"] = _render_nne_arbeitspreis(
            session_scope=session_scope, land=location["land"], region=location["region"]
        )
        with st.container(border=True):
            st.markdown("**Anlagenweit – gilt für alle Profile**")
            render_plant_export_limit()
            render_plant_grid_meter_assertions()


def _render_sun_group(ctx: dict, location: dict) -> None:
    """Group „Sonne & Horizont“: horizon and the PV suggestion values.

    Rendered before the consumers: their collector and preview read these fields.
    """
    from data.solar_horizon import HORIZON_SOURCE_KEY, SOURCE_MANUAL
    from ui.house_config_profile_horizon import horizon_enabled_key, render_horizon_section

    session_scope = ctx["session_scope"]
    horizon_on = st.session_state.get(
        horizon_enabled_key(session_scope),
        ctx["existing"].get(HORIZON_SOURCE_KEY) == SOURCE_MANUAL,
    )
    with form_group(
        "Sonne & Horizont",
        key=GROUP_KEYS["sun"],
        status=f"Horizont {_on_off(bool(horizon_on))}",
    ):
        location.update(
            render_horizon_section(
                ctx["existing"],
                session_scope=session_scope,
                latitude=location["latitude"],
                longitude=location["longitude"],
            )
        )
        st.markdown("**Vorschlagswerte für neue PV-Felder und den Solarkollektor**")
        location["default_pv_tilt"], location["default_pv_azimuth"] = _render_pv_default_row(
            session_scope=session_scope
        )
        from ui.house_config_plant import render_plant_pv_forecast_source

        with st.container(border=True):
            st.markdown("**Anlagenweit – gilt für alle Profile**")
            render_plant_pv_forecast_source()


def _render_heating_group(ctx: dict, *, persons: int, annual_kwh: float) -> dict:
    from house_config.house_thermal import HEATING_ENABLED_KEY
    from house_config.profile_schema_defaults import profile_default
    from ui.house_config_profile_house_thermal import render_house_heating_section

    session_scope = ctx["session_scope"]
    enabled = _session_value(
        session_scope,
        "house_heating_enabled",
        ctx["existing"].get(HEATING_ENABLED_KEY, profile_default(HEATING_ENABLED_KEY)),
    )
    with form_group("Heizung", key=GROUP_KEYS["heating"], status=_on_off(bool(enabled))):
        return render_house_heating_section(
            session_scope=session_scope,
            existing=ctx["existing"],
            persons=persons,
            annual_kwh=annual_kwh,
        )


def _render_cooling_group(ctx: dict, heating: dict) -> dict:
    from house_config.house_cooling import COOLING_ENABLED_KEY
    from ui.house_config_profile_cooling import render_house_cooling_section

    session_scope = ctx["session_scope"]
    enabled = _session_value(
        session_scope,
        "house_cooling_enabled",
        ctx["existing"].get(COOLING_ENABLED_KEY, False),
    )
    with form_group("Kühlung", key=GROUP_KEYS["cooling"], status=_on_off(bool(enabled))):
        cooling = render_house_cooling_section(
            session_scope=session_scope, existing=ctx["existing"], heating=heating
        )
    heating[COOLING_ENABLED_KEY] = cooling[COOLING_ENABLED_KEY]
    return cooling


def _render_absence_group(session_scope: str) -> bool:
    absent_now = bool(_session_value(session_scope, "house_absent_mode", False))
    with form_group(
        "Abwesenheit",
        key=GROUP_KEYS["absence"],
        status="Abwesend / Urlaub aktiv" if absent_now else "",
    ):
        absent_mode = labeled_checkbox(
            "Abwesend / Urlaub",
            key=_scoped_key(session_scope, "house_absent_mode"),
            help=(
                "Earnie-seitiger Abwesenheitsmodus (Live). "
                "Wirkt zusammen mit dem Smarthome-Signal sens_absent_mode (ODER)."
            ),
        )
        _render_absent_mode_status(profile_absent=bool(absent_mode))
        st.caption(
            "Die Heizungs-Absenkung steht in der Gruppe „Heizung“ (Regelung), "
            "„Inaktiv wenn abwesend“ beim jeweiligen Verbraucher."
        )
    return bool(absent_mode)


def _render_absent_mode_status(*, profile_absent: bool) -> None:
    from optimizer.absent_mode import ehal_read_state, effective_absent_mode, read_ehal_absent_mode

    ehal_labels = {
        "unbound": "nicht gebunden",
        "unreadable": "nicht lesbar",
        "on": "an",
        "off": "aus",
    }
    try:
        ehal_live, bound = read_ehal_absent_mode()
    except Exception as exc:  # noqa: BLE001 — shown and logged, the form goes on
        # A crash is "not readable", never "not bound": the binding may well exist.
        logging.getLogger(__name__).warning("EHAL absent_mode read failed: %s", exc)
        effective = effective_absent_mode(profile_absent, None)
        st.caption(
            f"Smarthome (EHAL): **{ehal_labels['unreadable']}** ({exc}) · "
            f"Wirksam (Live): **{'aktiv' if effective else 'inaktiv'}**"
        )
        return
    state = ehal_read_state(ehal_live, bound=bound)
    effective = effective_absent_mode(profile_absent, ehal_live)
    st.caption(
        f"Smarthome (EHAL): **{ehal_labels[state]}** · "
        f"Wirksam (Live): **{'aktiv' if effective else 'inaktiv'}**"
    )
    if bound:
        st.caption(
            "Smarthome kann Abwesenheit aktiv halten, auch wenn der Earnie-Schalter aus ist."
        )
