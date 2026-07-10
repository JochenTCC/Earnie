"""Gemeinsame Streamlit-UI für Ist-vs.-Modell-Verbrauchsvergleich."""
from __future__ import annotations

import streamlit as st

from ui.consumption_validation_charts import (
    format_iso_week_label,
    iso_weeks_in_series,
    modeled_monthly_kwh,
    monthly_comparison_chart,
    timeseries_comparison_from_series,
)


def render_iso_week_navigation(
    series: list[tuple[str, float]],
    *,
    key_prefix: str,
    reset_token: str | None = None,
) -> tuple[int, int] | None:
    """ISO-KW-Navigation (← / Label / →); gibt gewählte (iso_year, iso_week) zurück."""
    weeks = iso_weeks_in_series(series)
    if not weeks:
        return None

    week_idx_key = f"{key_prefix}_week_idx"
    week_reset_key = f"{key_prefix}_week_reset"
    token = reset_token if reset_token is not None else str(len(series))
    if st.session_state.get(week_reset_key) != token:
        st.session_state[week_reset_key] = token
        st.session_state[week_idx_key] = 0
    week_idx = int(st.session_state.get(week_idx_key, 0))
    week_idx = max(0, min(week_idx, len(weeks) - 1))
    st.session_state[week_idx_key] = week_idx
    iso_year, iso_week = weeks[week_idx]
    week_label = format_iso_week_label(iso_year, iso_week)
    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap="small",
        vertical_alignment="center",
    ):
        if st.button(
            "←",
            disabled=week_idx <= 0,
            key=f"{key_prefix}_week_back",
            help="Vorherige Kalenderwoche",
            type="secondary",
            width="content",
        ):
            st.session_state[week_idx_key] = week_idx - 1
            st.rerun()
        st.markdown(f"**{week_label}**")
        if st.button(
            "→",
            disabled=week_idx >= len(weeks) - 1,
            key=f"{key_prefix}_week_forward",
            help="Nächste Kalenderwoche",
            type="secondary",
            width="content",
        ):
            st.session_state[week_idx_key] = week_idx + 1
            st.rerun()
    return iso_year, iso_week


def render_consumption_comparison_panel(
    *,
    actual_monthly: dict[str, float],
    modeled_profile: dict,
    series: list[tuple[str, float]],
    key_prefix: str,
    annual_kwh: float | None = None,
    actual_total_label: str = "Ist-Jahresverbrauch (CSV)",
    actual_series_label: str = "Ist (CSV)",
    reset_token: str | None = None,
) -> None:
    """Metriken, Monatsbalken, KW-Navigation und Stundenlinie."""
    model_monthly = modeled_monthly_kwh(modeled_profile)
    actual_total = sum(actual_monthly.values())
    model_total = sum(model_monthly.values())
    col_a, col_b = st.columns(2)
    col_a.metric(actual_total_label, f"{actual_total:.0f} kWh")
    col_b.metric("Modell-Jahresverbrauch", f"{model_total:.0f} kWh")
    if annual_kwh is not None and annual_kwh > 0:
        if abs(actual_total - annual_kwh) / annual_kwh > 0.15:
            st.info(
                f"Hinweis: Konfigurierter Jahresverbrauch ({annual_kwh:.0f} kWh) "
                f"weicht vom Ist ({actual_total:.0f} kWh) ab."
            )
    st.plotly_chart(monthly_comparison_chart(actual_monthly, model_monthly), width="stretch")

    week = render_iso_week_navigation(
        series,
        key_prefix=key_prefix,
        reset_token=reset_token,
    )
    if week is None:
        return
    iso_year, iso_week = week
    st.plotly_chart(
        timeseries_comparison_from_series(
            series,
            modeled_profile,
            iso_year=iso_year,
            iso_week=iso_week,
            actual_label=actual_series_label,
        ),
        width="stretch",
    )
