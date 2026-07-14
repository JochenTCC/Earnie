"""Streamlit-Orchestrierung für die gemeinsame Verbrauchs-UI."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from ui.consumption_display.adapters import (
    actual_monthly_from_csv,
    bundle_from_cons_data,
    bundle_from_csv_validation,
    bundle_from_modeled_profile,
)
from ui.consumption_display.aggregation import annual_kwh_actual, annual_kwh_from_bundle
from ui.consumption_display.charts import (
    csv_validation_monthly_chart,
    stacked_monthly_chart,
    week_scenario_consumer_timeseries_chart,
    week_timeseries_chart,
)
from ui.consumption_display.navigation import render_iso_week_navigation
from ui.consumption_display.types import (
    ConsumptionDisplayMode,
    ConsumptionSeriesBundle,
    ScenarioConsumerOverlayBundle,
)


def render_consumption_display(
    mode: ConsumptionDisplayMode,
    *,
    key_prefix: str,
    profile: dict | None = None,
    csv_series: list[tuple[str, float]] | None = None,
    cons_data: pd.DataFrame | None = None,
    reset_token: str | None = None,
    nav_bounds: tuple[datetime, datetime] | None = None,
    annual_kwh: float | None = None,
    actual_total_label: str = "Ist-Jahresverbrauch (CSV)",
    scenario_consumer_overlays: ScenarioConsumerOverlayBundle | None = None,
) -> None:
    """Einheitliche Verbrauchsvisualisierung für drei Modi."""
    bundle = _build_bundle(
        mode,
        profile=profile,
        csv_series=csv_series,
        cons_data=cons_data,
    )
    token = reset_token if reset_token is not None else str(bundle.hour_count())
    _render_metrics(mode, bundle, annual_kwh=annual_kwh, actual_total_label=actual_total_label)
    _render_monthly_chart(mode, bundle, csv_series=csv_series)
    week = render_iso_week_navigation(
        bundle.timestamps,
        key_prefix=key_prefix,
        reset_token=token,
        nav_bounds=nav_bounds,
    )
    if week is not None:
        iso_year, iso_week = week
        if scenario_consumer_overlays is not None:
            st.plotly_chart(
                week_scenario_consumer_timeseries_chart(
                    bundle.timestamps,
                    scenario_consumer_overlays,
                    iso_year=iso_year,
                    iso_week=iso_week,
                ),
                width="stretch",
            )
        else:
            st.plotly_chart(
                week_timeseries_chart(bundle, iso_year=iso_year, iso_week=iso_week),
                width="stretch",
            )


def _build_bundle(
    mode: ConsumptionDisplayMode,
    *,
    profile: dict | None,
    csv_series: list[tuple[str, float]] | None,
    cons_data: pd.DataFrame | None,
) -> ConsumptionSeriesBundle:
    if mode == ConsumptionDisplayMode.CSV_VALIDATION:
        if profile is None or csv_series is None:
            raise ValueError("csv_validation erfordert profile und csv_series.")
        return bundle_from_csv_validation(csv_series, profile)
    if mode == ConsumptionDisplayMode.CONS_DATA:
        if cons_data is None:
            raise ValueError("cons_data erfordert cons_data DataFrame.")
        return bundle_from_cons_data(cons_data)
    if mode == ConsumptionDisplayMode.MODELED_PROFILE:
        if profile is None:
            raise ValueError("modeled_profile erfordert profile.")
        return bundle_from_modeled_profile(profile)
    raise ValueError(f"Unbekannter Modus: {mode}")


def _render_metrics(
    mode: ConsumptionDisplayMode,
    bundle: ConsumptionSeriesBundle,
    *,
    annual_kwh: float | None,
    actual_total_label: str,
) -> None:
    if mode == ConsumptionDisplayMode.CSV_VALIDATION:
        actual_total = annual_kwh_actual(bundle)
        model_total = annual_kwh_from_bundle(bundle)
        col_a, col_b = st.columns(2)
        col_a.metric(actual_total_label, f"{actual_total:.0f} kWh")
        col_b.metric("Modell-Jahresverbrauch", f"{model_total:.0f} kWh")
        if annual_kwh is not None and annual_kwh > 0:
            if abs(actual_total - annual_kwh) / annual_kwh > 0.15:
                st.info(
                    f"Hinweis: Konfigurierter Jahresverbrauch ({annual_kwh:.0f} kWh) "
                    f"weicht vom Ist ({actual_total:.0f} kWh) ab."
                )
        return
    if mode == ConsumptionDisplayMode.MODELED_PROFILE:
        st.metric("Modell-Jahresverbrauch", f"{annual_kwh_from_bundle(bundle):.0f} kWh")


def _render_monthly_chart(
    mode: ConsumptionDisplayMode,
    bundle: ConsumptionSeriesBundle,
    *,
    csv_series: list[tuple[str, float]] | None,
) -> None:
    if mode == ConsumptionDisplayMode.CSV_VALIDATION:
        if csv_series is None:
            return
        actual_monthly = actual_monthly_from_csv(csv_series)
        st.plotly_chart(
            csv_validation_monthly_chart(bundle, actual_monthly),
            width="stretch",
        )
        return
    title = (
        "Monatsverbrauch: cons_data (kWh)"
        if mode == ConsumptionDisplayMode.CONS_DATA
        else "Monatsverbrauch: Modell (kWh)"
    )
    st.plotly_chart(stacked_monthly_chart(bundle, title=title), width="stretch")
