"""Manuelle Geräte: Empfehlungsmodus (günstigste Startzeit im Empfehlungshorizont).

Rein beratend: Nennleistung und Laufzeit kommen aus dem Hausprofil (Hauskonfigurator).
Pro Gerät wird die günstigste Startstunde nach Netzbezugskosten im konfigurierten
Empfehlungshorizont ermittelt.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from config import reinit_config
from optimizer import schedule as optimization_schedule
from optimizer.appliance_recommendation import (
    STAR_MAX,
    DEFAULT_HORIZON_H,
    ApplianceRecommendation,
    StarThresholdSettings,
    recommend_start_times,
)
from runtime_store import appliance_schedules
from runtime_store.live_display_loader import (
    is_persisted_display_fresh,
    load_live_display_snapshot,
    planning_matrix_from_snapshot,
    snapshot_age_seconds,
    snapshot_completed_at,
)
from ui.chart_colors import COLOR_COST_SAVINGS, COLOR_COST_SAVINGS_NEGATIVE
from ui.help_hint import render_page_title_with_help
from ui.runtime_config import invalidate_live_optimization_cache

_DEVICES_HELP = (
    "Empfehlungsmodus für manuelle Geräte (Waschmaschine, Trockner, "
    "Geschirrspüler): günstigste Startstunde im konfigurierten "
    "Empfehlungshorizont (Hausprofil) nach reinen Netzbezugskosten. "
    "Optional kann eine Startstunde in die nächste Optimierung einfließen "
    "(Nennleistung × Laufzeit)."
)
_DEFAULT_RUNTIME_H = 2.0
_DELTA_COLUMN = "Delta"
_DELTA_EPS = 0.005


def _appliance_power_kw(appliance: dict) -> float:
    return float(appliance.get("default_power_kw") or 0.0)


def _appliance_runtime_h(appliance: dict) -> float:
    return float(appliance.get("default_runtime_h") or _DEFAULT_RUNTIME_H)


def _appliance_loxone_power_name(appliance: dict) -> str:
    inputs = appliance.get("loxone_inputs")
    if isinstance(inputs, dict):
        name = str(inputs.get("power_name", "")).strip()
        if name:
            return name
    return str(appliance.get("loxone_power_name", "")).strip()


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
            "Keine manuellen Geräte konfiguriert — type:generic mit "
            "earnie_role: manual im Hausprofil oder Legacy-Block "
            "'appliances' in config.json (siehe config.example.json)."
        )
        return
    st.caption(
        "Empfehlungshorizont je Gerät aus dem Hausprofil · "
        "Nennleistung/Laufzeit im Hauskonfigurator · "
        "Häkchen in der Tabelle = Optimierungsplan."
    )
    matrix = _load_planning_matrix()
    if not matrix:
        return
    _render_star_threshold_settings()
    for appliance in appliances:
        _render_appliance(appliance, matrix)
        st.divider()


def _load_planning_matrix() -> list | None:
    """Letzte Planungsmatrix aus main.py-Persistenz (kein Live-Matrix-Build)."""
    snapshot = load_live_display_snapshot()
    if snapshot is None:
        st.info("Warte auf ersten main.py-Durchlauf — keine Planungsdaten verfügbar.")
        return None

    completed = snapshot_completed_at(snapshot)
    matrix = planning_matrix_from_snapshot(snapshot)
    if not matrix:
        st.warning("Persistierter Snapshot enthält keine Planungsmatrix.")
        return None

    age_sec = snapshot_age_seconds(completed)
    age_min = int(age_sec // 60) if age_sec is not None else None
    label = completed[:16].replace("T", " ") if completed else "unbekannt"

    if is_persisted_display_fresh(completed):
        st.caption(
            f"Planungsdaten vom letzten main.py-Lauf (**{label}**"
            + (f", vor {age_min} min" if age_min is not None else "")
            + ")."
        )
    else:
        st.warning(
            f"Daten veraltet — main.py seit **{label}** nicht aktiv "
            f"(>{optimization_schedule.PERSISTED_DISPLAY_MAX_AGE_SECONDS // 3600} h). "
            "Empfehlungen basieren auf dem letzten bekannten Plan."
        )
    return matrix


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
    power_kw = _appliance_power_kw(appliance)
    runtime_h = _appliance_runtime_h(appliance)
    horizon_h = _recommendation_horizon_h(appliance)
    st.caption(
        f"Nennleistung: **{power_kw:.2f} kW** · Laufzeit: **{runtime_h:.2f} h** · "
        f"Empfehlungshorizont: **{horizon_h} h** (Hausprofil)"
    )
    if appliance.get("power_source") == "loxone":
        merker = _appliance_loxone_power_name(appliance)
        if merker:
            st.caption(
                f"Loxone-Merker: `{merker}` (für künftige Live-Adaption; "
                "Empfehlung nutzt Nennleistung aus dem Profil)"
            )
    if power_kw <= 0:
        st.warning("Keine gültige Leistung im Hausprofil — Empfehlung nicht möglich.")
        return
    _render_recommendation(appliance, matrix, power_kw, runtime_h)


def _recommendation_horizon_h(appliance: dict) -> int:
    horizon = appliance.get("recommendation_horizon_h")
    if horizon is not None:
        return max(1, int(horizon))
    return DEFAULT_HORIZON_H


def _render_recommendation(
    appliance: dict,
    matrix: list,
    power_kw: float,
    runtime_h: float,
) -> None:
    appliance_id = appliance["id"]
    horizon_h = _recommendation_horizon_h(appliance)
    try:
        rec = recommend_start_times(
            matrix,
            power_kw,
            runtime_h,
            horizon_h=horizon_h,
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
_REC_TABLE_COL_WIDTHS = [1, 1, 1, 1]
# Spaltenbreiten (rem) — Plan | Start | Güte | Delta
_REC_TABLE_COL_REM = (1.55, 5.0, 6.0, 5.0)


def _recommendation_table_css() -> str:
    col_rules = "\n".join(
        f"""[class*="st-key-appliance_rec_table_"] [data-testid="stColumn"]:nth-child({index}) {{
    width: {width_rem}rem !important;
    flex-basis: {width_rem}rem !important;
    max-width: {width_rem}rem;
}}"""
        for index, width_rem in enumerate(_REC_TABLE_COL_REM, start=1)
    )
    return f"""
<style>
[class*="st-key-appliance_rec_table_"] {{
    width: fit-content !important;
    max-width: 100%;
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stVerticalBlock"] {{
    gap: 0.4rem !important;
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stHorizontalBlock"] {{
    width: fit-content !important;
    max-width: 100%;
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 0.2rem !important;
    min-height: 0.8em;
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stHorizontalBlock"]:first-child {{
    padding-bottom: 1.3rem; 
    margin-bottom: 0.0rem;
    border-bottom: 1px solid rgba(49, 51, 63, 0.18);
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stColumn"] {{
    flex: 0 0 auto !important;
    flex-grow: 0 !important;
    min-width: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
}}
{col_rules}
[class*="st-key-appliance_rec_table_"] [data-testid="stMarkdown"] p {{
    margin-top: 0;
    margin-bottom: 0;
    line-height: 0.8;
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stCheckbox"] label {{
    min-height: 0;
    padding: 0;
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stCheckbox"] {{
    padding: 0;
    margin: 0;
}}
[class*="st-key-appliance_rec_table_"] [data-testid="stColumn"]:nth-child(1) [data-testid="stVerticalBlock"] {{
    justify-content: center;
}}
@media (max-width: 768px) {{
    [class*="st-key-appliance_rec_table_"] [data-testid="stHorizontalBlock"] {{
        overflow-x: auto;
    }}
}}
.stApp[data-theme="dark"] [class*="st-key-appliance_rec_table_"] [data-testid="stHorizontalBlock"]:first-child {{
    border-bottom-color: rgba(250, 250, 250, 0.15);
}}
</style>
"""


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


def _inject_recommendation_table_css() -> None:
    st.markdown(_recommendation_table_css(), unsafe_allow_html=True)


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
        "Häkchen vor der Startzeit = sofort in die nächste Optimierung; "
        "entfernen löscht den Plan."
    )
    _inject_recommendation_table_css()
    best_cost = rec.cheapest.cost_eur
    with st.container(key=f"appliance_rec_table_{appliance_id}", width="content"):
        header = st.columns(
            _REC_TABLE_COL_WIDTHS, gap="xxsmall", vertical_alignment="center"
        )
        header[0].markdown("")
        header[1].markdown("**Startzeit**")
        header[2].markdown("**Ranking**")
        header[3].markdown(f"**{_DELTA_COLUMN}**")
        for index, option in enumerate(rec.options):
            delta = _delta_to_best_eur(option.cost_eur, best_cost)
            row = st.columns(
                _REC_TABLE_COL_WIDTHS, gap="xxsmall", vertical_alignment="center"
            )
            row[0].checkbox(
                "Planen",
                label_visibility="collapsed",
                key=_plan_checkbox_key(appliance_id, index),
                on_change=_on_plan_checkbox_change,
                args=(appliance_id, index, rec, power_kw, runtime_h),
            )
            row[1].markdown(f"**{option.start_datetime:%H:%M}**")
            row[2].markdown(_stars_text(option.stars))
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
        f"{best.cost_eur:.2f} € · Delta (sofort): "
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
