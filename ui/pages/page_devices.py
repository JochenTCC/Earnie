"""Manuelle Geräte: Empfehlungsmodus (günstigste Startzeit im 6-h-Horizont).

Rein beratend (Schritt 3b, Backlog Z. 27): pro Gerät wird die Leistung
(Loxone-Merker oder manuelles Eingabefeld) und die Laufzeit erfasst und
darüber die günstigste Startstunde nach Netzbezugskosten ermittelt.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from config import reinit_config
from data import profile_manager
from integrations import awattar_client
from optimizer.appliance_recommendation import (
    STAR_MAX,
    DEFAULT_HORIZON_H,
    ApplianceRecommendation,
    StarThresholdSettings,
    recommend_start_times,
)
from runtime_store import appliance_schedules
from ui.chart_colors import COLOR_COST_SAVINGS, COLOR_COST_SAVINGS_NEGATIVE
from ui.help_hint import render_page_title_with_help
from ui.runtime_config import invalidate_live_optimization_cache

_DEVICES_HELP = (
    "Empfehlungsmodus für manuelle Geräte (Waschmaschine, Trockner, "
    "Geschirrspüler): günstigste Startstunde im nächsten 6-h-Horizont nach "
    "reinen Netzbezugskosten. Optional kann eine Startstunde in die "
    "nächste Optimierung einfließen (Nennleistung × Laufzeit)."
)
_DEFAULT_RUNTIME_H = 2.0
_DELTA_COLUMN = "Delta zu bestem Zeitpunkt (€)"
_DELTA_EPS = 0.005


def _delta_to_best_eur(cost_eur: float, best_cost_eur: float) -> float:
    """Mehrkosten gegenüber der günstigsten Startstunde (positiv = teurer)."""
    return cost_eur - best_cost_eur


def _delta_cell_color(delta_eur: float) -> str:
    if delta_eur > _DELTA_EPS:
        return f"color: {COLOR_COST_SAVINGS_NEGATIVE}"
    if delta_eur < -_DELTA_EPS:
        return f"color: {COLOR_COST_SAVINGS}"
    return "color: inherit"


def render() -> None:
    render_page_title_with_help(
        "🔌 Manuelle Geräte", _DEVICES_HELP, key="devices_scope_help"
    )
    appliances = config.get_appliances()
    if not appliances:
        st.info(
            "Keine manuellen Geräte konfiguriert — 'appliances'-Block in "
            "config.json ergänzen (siehe config.example.json)."
        )
        return
    st.caption(
        f"Horizont {DEFAULT_HORIZON_H} h · Häkchen in der Tabelle = Optimierungsplan."
    )
    matrix = _load_planning_matrix()
    if not matrix:
        return
    _render_star_threshold_settings()
    for appliance in appliances:
        _render_appliance(appliance, matrix)
        st.divider()


def _load_planning_matrix() -> list | None:
    """Stündliche Live-Planungsmatrix (Preis je Slot) oder None mit Fehlermeldung."""
    try:
        window = profile_manager.compute_live_planning_window()
        market_data = awattar_client.fetch_awattar_prices(planning_end=window.end)
    except Exception as exc:  # noqa: BLE001 — UI: jede Datenquelle als Fehler zeigen
        st.error(f"Planungsdaten konnten nicht geladen werden: {exc}")
        return None
    if not market_data:
        st.error("aWATTar-Börsenpreise konnten nicht geladen werden.")
        return None
    try:
        return profile_manager.build_live_planning_matrix(market_data, window)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Planungsmatrix konnte nicht erstellt werden: {exc}")
        return None


def _star_threshold_settings() -> StarThresholdSettings:
    raw = config.get_appliance_recommendation_settings()
    return StarThresholdSettings(
        abs_margin_cent=float(raw["abs_margin_cent"]),
        pct_stars_4=float(raw["pct_stars_4"]),
        pct_stars_1=float(raw["pct_stars_1"]),
    )


def _render_star_threshold_settings() -> None:
    settings = config.get_appliance_recommendation_settings()
    with st.expander("Sterne-Schwellen", expanded=False):
        st.caption(
            "5 Sterne wenn kein Slot des Laufs mehr als die absolute k_act-Marge "
            "über dem günstigsten Horizont-Preis liegt; sonst prozentuale Mehrkosten."
        )
        with st.form(key="appliance_star_thresholds_form"):
            margin = st.number_input(
                "Absolute Marge (Cent/kWh)",
                min_value=0.0,
                value=float(settings["abs_margin_cent"]),
                step=0.01,
                format="%.2f",
            )
            pct_4 = st.number_input(
                "Bis 4 Sterne (%) Mehrkosten",
                min_value=0.1,
                value=float(settings["pct_stars_4"]),
                step=0.5,
                format="%.1f",
            )
            pct_1 = st.number_input(
                "Ab 1 Stern (%) Mehrkosten",
                min_value=0.1,
                value=float(settings["pct_stars_1"]),
                step=0.5,
                format="%.1f",
            )
            save = st.form_submit_button("Schwellen in config.json speichern")
        if save:
            try:
                config.update_appliance_recommendation_settings(
                    {
                        "abs_margin_cent": margin,
                        "pct_stars_4": pct_4,
                        "pct_stars_1": pct_1,
                    }
                )
                reinit_config()
                st.success("Sterne-Schwellen gespeichert.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Speichern fehlgeschlagen: {exc}")


def _render_appliance(appliance: dict, matrix: list) -> None:
    st.markdown(f"#### {appliance['name']}")
    appliance_id = appliance["id"]
    default_kw = float(appliance.get("default_power_kw") or 0.0)
    default_runtime = float(appliance.get("default_runtime_h") or _DEFAULT_RUNTIME_H)
    with st.form(key=f"appliance_form_{appliance_id}"):
        col_power, col_runtime = st.columns(2)
        power_kw = col_power.number_input(
            "Nennleistung (kW)",
            min_value=0.0,
            value=default_kw,
            step=0.1,
            key=f"appliance_power_{appliance_id}",
        )
        runtime_h = col_runtime.number_input(
            "Laufzeit (h)",
            min_value=0.25,
            value=default_runtime,
            step=0.25,
            key=f"appliance_runtime_{appliance_id}",
        )
        if appliance["power_source"] == "loxone" and default_kw > 0:
            hint = f"Hinweis: {default_kw:.2f} kW (aus Config"
            merker = appliance.get("loxone_power_name")
            if merker:
                hint += f"; Merker '{merker}' für spätere Adaption"
            col_power.caption(f"{hint})")
        save_defaults = st.form_submit_button("In config.json speichern")
    if save_defaults:
        _save_appliance_defaults(appliance_id, power_kw, runtime_h)
    if power_kw is None or power_kw <= 0:
        st.warning("Keine gültige Leistung — Empfehlung nicht möglich.")
        return
    _render_recommendation(appliance, matrix, power_kw, runtime_h)


def _save_appliance_defaults(appliance_id: str, power_kw: float, runtime_h: float) -> None:
    try:
        config.update_appliance_defaults(
            appliance_id, power_kw=float(power_kw), runtime_h=float(runtime_h)
        )
        reinit_config()
        st.success("Parameter in config.json gespeichert.")
    except Exception as exc:  # noqa: BLE001 — UI-Feedback
        st.error(f"Speichern fehlgeschlagen: {exc}")


def _render_recommendation(
    appliance: dict,
    matrix: list,
    power_kw: float,
    runtime_h: float,
) -> None:
    appliance_id = appliance["id"]
    try:
        rec = recommend_start_times(
            matrix,
            power_kw,
            runtime_h,
            horizon_h=DEFAULT_HORIZON_H,
            star_settings=_star_threshold_settings(),
        )
    except ValueError as exc:
        st.warning(str(exc))
        return
    _render_cheapest_caption(rec)
    _render_recommendation_table(appliance_id, rec, power_kw, runtime_h)
    if rec.skipped_start_slots:
        st.caption(
            f"{rec.skipped_start_slots} spätere Startstunde(n) entfallen — "
            "Planungsdaten reichen nicht für die volle Laufzeit."
        )


def _schedule_matches_option(schedule: dict, option_start) -> bool:
    from datetime import datetime

    from data.planning_window import align_to_planning_timezone

    start_raw = schedule.get("start_at")
    if not start_raw:
        return False
    scheduled = align_to_planning_timezone(
        datetime.fromisoformat(str(start_raw)), config.get_planning_timezone()
    )
    option = align_to_planning_timezone(option_start, config.get_planning_timezone())
    return scheduled == option


_PLAN_CHECKBOX_PREFIX = "appliance_plan_"


def _plan_checkbox_key(appliance_id: str, index: int) -> str:
    return f"{_PLAN_CHECKBOX_PREFIX}{appliance_id}_{index}"


def _init_plan_checkbox_state(
    appliance_id: str,
    rec: ApplianceRecommendation,
    active: dict | None,
) -> None:
    for index, option in enumerate(rec.options):
        key = _plan_checkbox_key(appliance_id, index)
        if key not in st.session_state:
            st.session_state[key] = bool(
                active and _schedule_matches_option(active, option.start_datetime)
            )


def _on_plan_checkbox_change(
    appliance_id: str,
    index: int,
    rec: ApplianceRecommendation,
    power_kw: float,
    runtime_h: float,
) -> None:
    key = _plan_checkbox_key(appliance_id, index)
    try:
        if st.session_state.get(key):
            for other_index in range(len(rec.options)):
                if other_index != index:
                    st.session_state[_plan_checkbox_key(appliance_id, other_index)] = False
            appliance_schedules.save_schedule(
                appliance_id,
                start_at=rec.options[index].start_datetime,
                power_kw=power_kw,
                runtime_h=runtime_h,
            )
            invalidate_live_optimization_cache()
            return
        active = appliance_schedules.active_schedule_for(appliance_id)
        option = rec.options[index]
        if active and _schedule_matches_option(active, option.start_datetime):
            appliance_schedules.remove_schedule(appliance_id)
            invalidate_live_optimization_cache()
    except OSError as exc:
        st.session_state[key] = not bool(st.session_state.get(key))
        st.error(f"Plan konnte nicht gespeichert werden: {exc}")


def _render_recommendation_table(
    appliance_id: str,
    rec: ApplianceRecommendation,
    power_kw: float,
    runtime_h: float,
) -> None:
    active = appliance_schedules.active_schedule_for(appliance_id)
    _init_plan_checkbox_state(appliance_id, rec, active)
    if active:
        st.caption(
            f"Aktiver Optimierungsplan bis **{active['expires_at'][:16].replace('T', ' ')}** "
            f"({active['power_kw']} kW × {active['runtime_h']} h)."
        )
    st.caption(
        "Häkchen hinter der Startzeit = sofort in die nächste Optimierung; "
        "entfernen löscht den Plan."
    )
    best_cost = rec.cheapest.cost_eur
    header = st.columns([1.4, 1.0, 0.9, 1.4])
    header[0].markdown("**Start**")
    header[1].markdown("**Güte**")
    header[2].markdown("**Kosten (€)**")
    header[3].markdown(f"**{_DELTA_COLUMN}**")
    for index, option in enumerate(rec.options):
        delta = _delta_to_best_eur(option.cost_eur, best_cost)
        row = st.columns([1.4, 1.0, 0.9, 1.4])
        with row[0]:
            time_col, check_col = st.columns([0.75, 0.25], gap="small")
            time_col.markdown(f"**{option.start_datetime:%H:%M}**")
            check_col.checkbox(
                "Planen",
                label_visibility="collapsed",
                key=_plan_checkbox_key(appliance_id, index),
                on_change=_on_plan_checkbox_change,
                args=(appliance_id, index, rec, power_kw, runtime_h),
            )
        row[1].markdown(_stars_text(option.stars))
        row[2].markdown(f"{option.cost_eur:.2f}")
        row[3].markdown(
            f'<span style="{_delta_cell_color(delta)}">{delta:+.2f}</span>',
            unsafe_allow_html=True,
        )


def _render_cheapest_caption(rec: ApplianceRecommendation) -> None:
    best = rec.cheapest
    delta = _delta_to_best_eur(rec.immediate.cost_eur, best.cost_eur)
    color = _delta_cell_color(delta)
    st.markdown(
        f"Günstigste Startzeit: **{best.start_datetime:%H:%M} Uhr** · "
        f"{best.cost_eur:.2f} € · {_DELTA_COLUMN} (sofort): "
        f'<span style="{color}">{delta:+.2f} €</span>',
        unsafe_allow_html=True,
    )


def _stars_text(stars: int) -> str:
    return "★" * stars + "☆" * (STAR_MAX - stars)


def _recommendation_dataframe(rec: ApplianceRecommendation) -> pd.DataFrame:
    best_cost = rec.cheapest.cost_eur
    return pd.DataFrame(
        [
            {
                "Start": f"{option.start_datetime:%H:%M}",
                "Güte": _stars_text(option.stars),
                "Kosten (€)": round(option.cost_eur, 2),
                _DELTA_COLUMN: round(
                    _delta_to_best_eur(option.cost_eur, best_cost), 2
                ),
            }
            for option in rec.options
        ]
    )


def _style_recommendation_dataframe(
    rec: ApplianceRecommendation,
) -> pd.io.formats.style.Styler:
    df = _recommendation_dataframe(rec)

    def _color_delta(val: float) -> str:
        return _delta_cell_color(float(val))

    return df.style.format({_DELTA_COLUMN: "{:+.2f}"}).map(
        _color_delta, subset=[_DELTA_COLUMN]
    )
