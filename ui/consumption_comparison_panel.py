"""Gemeinsame Streamlit-UI für Ist-vs.-Modell-Verbrauchsvergleich (Legacy-Wrapper)."""
from __future__ import annotations

from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display
from ui.consumption_display.navigation import render_iso_week_navigation as _render_iso_week_navigation


def render_iso_week_navigation(
    series: list[tuple[str, float]],
    *,
    key_prefix: str,
    reset_token: str | None = None,
) -> tuple[int, int] | None:
    """ISO-KW-Navigation (← / Label / →); gibt gewählte (iso_year, iso_week) zurück."""
    timestamps = [ts for ts, _ in series]
    return _render_iso_week_navigation(
        timestamps,
        key_prefix=key_prefix,
        reset_token=reset_token,
    )


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
    """Delegiert an ``render_consumption_display`` (Modus csv_validation)."""
    del actual_monthly, actual_series_label
    render_consumption_display(
        ConsumptionDisplayMode.CSV_VALIDATION,
        key_prefix=key_prefix,
        profile=modeled_profile,
        csv_series=series,
        annual_kwh=annual_kwh,
        reset_token=reset_token,
        actual_total_label=actual_total_label,
    )
