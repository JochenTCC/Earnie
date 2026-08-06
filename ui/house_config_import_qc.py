"""Post-import power QC plot and SE-horizon messaging for Hauskonfigurator CSVs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from house_config.consumption_csv import (
    MIN_HOURS_FULL_YEAR,
    derive_total_from_balance,
    import_span_adequate_for_se,
    load_hourly_profile_csv,
    normalize_profile_csv_file,
    profile_rows_bounds,
    shared_import_span_hours,
)
from ui.chart_colors import COLOR_BASELOAD, COLOR_BATTERY, COLOR_GRID, PV_YELLOW_PALETTE

_PV_COLOR = PV_YELLOW_PALETTE[0]


def _load_profile_rows(path: str) -> list[tuple[str, float]] | None:
    from runtime_store.persist_paths import resolve_config_prefixed_path

    if not path or not Path(resolve_config_prefixed_path(path)).is_file():
        return None
    try:
        return load_hourly_profile_csv(path)
    except ValueError:
        try:
            return normalize_profile_csv_file(path)
        except (ValueError, OSError):
            return None
    except (OSError, FileNotFoundError):
        return None


def _series_xy(rows: list[tuple[str, float]]) -> tuple[list[pd.Timestamp], list[float]]:
    xs = [
        pd.Timestamp(ts.replace(" ", "T", 1)[:19])
        for ts, _ in rows
    ]
    ys = [float(kw) for _, kw in rows]
    return xs, ys


def _add_power_trace(
    fig: go.Figure,
    *,
    name: str,
    rows: list[tuple[str, float]] | None,
    color: str,
    width: float = 1.5,
) -> None:
    if not rows:
        return
    xs, ys = _series_xy(rows)
    fig.add_scatter(
        name=name,
        x=xs,
        y=ys,
        mode="lines",
        line=dict(width=width, color=color, shape="hv"),
    )


def balance_gesamt_for_chart(
    pv_rows: list[tuple[str, float]] | None,
    battery_rows: list[tuple[str, float]] | None,
    grid_rows: list[tuple[str, float]] | None,
    *,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> tuple[list[tuple[str, float]] | None, int]:
    """Derive Gesamtverbrauch when PV + Netz are available (Batterie optional)."""
    if not pv_rows or not grid_rows:
        return None, 0
    try:
        total, clipped = derive_total_from_balance(
            pv_rows,
            battery_rows,
            grid_rows,
            invert_pv=invert_pv,
            invert_battery=invert_battery,
            invert_grid=invert_grid,
        )
    except ValueError:
        return None, 0
    return total, clipped


def load_balance_gesamt_series(
    pv_path: str,
    battery_path: str,
    grid_path: str,
    *,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> tuple[list[tuple[str, float]] | None, int]:
    """Load PV/Batterie/Netz CSVs and derive Gesamtverbrauch for charts."""
    return balance_gesamt_for_chart(
        _load_profile_rows(pv_path),
        _load_profile_rows(battery_path),
        _load_profile_rows(grid_path),
        invert_pv=invert_pv,
        invert_battery=invert_battery,
        invert_grid=invert_grid,
    )


def import_power_qc_figure(
    verbrauch_rows: list[tuple[str, float]] | None,
    pv_rows: list[tuple[str, float]] | None,
    battery_rows: list[tuple[str, float]] | None = None,
    grid_rows: list[tuple[str, float]] | None = None,
) -> go.Figure:
    """Full-horizon power plot (union of available series).

    Bilanz imports typically pass PV / Batterie / Netz plus derived Gesamtverbrauch.
    """
    fig = go.Figure()
    _add_power_trace(fig, name="PV-Erzeugungsprofil [kW]", rows=pv_rows, color=_PV_COLOR)
    _add_power_trace(fig, name="Batterie", rows=battery_rows, color=COLOR_BATTERY)
    _add_power_trace(fig, name="Netz", rows=grid_rows, color=COLOR_GRID)
    _add_power_trace(
        fig,
        name="Lastprofil [kW] (Gesamt)",
        rows=verbrauch_rows,
        color=COLOR_BASELOAD,
        width=2.0,
    )
    fig.update_layout(
        title="Importierte Leistung (vollständiger Zeitraum)",
        xaxis_title="Zeit",
        yaxis_title="kW",
        height=400,
        margin=dict(l=40, r=20, t=50, b=80),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            xanchor="left",
            x=0.0,
        ),
    )
    return fig


def _se_window_from_data_max(data_max: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    from data.data_loader import last_complete_month_end

    end = last_complete_month_end(pd.Timestamp(data_max))
    start = (end.to_period("M") - 11).to_timestamp().normalize()
    return start, end


def _march_in_window(start: pd.Timestamp, end: pd.Timestamp) -> int | None:
    """Prefer March overlapping [start, end]; else first calendar month in window."""
    cursor = start.to_period("M")
    end_period = end.to_period("M")
    first_month: int | None = None
    while cursor <= end_period:
        if first_month is None:
            first_month = int(cursor.month)
        if int(cursor.month) == 3:
            return 3
        cursor += 1
    return first_month


def _shared_bounds(
    *series: list[tuple[str, float]] | None,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    bounds_list = [
        profile_rows_bounds(rows or [])
        for rows in series
        if rows
    ]
    bounds_list = [b for b in bounds_list if b is not None]
    if not bounds_list:
        return None
    start = max(b[0] for b in bounds_list)
    end = min(b[1] for b in bounds_list)
    if start > end:
        return None
    return start, end


def render_import_power_qc(
    *,
    preview_id: str,
    verbrauch_path: str,
    pv_path: str,
    battery_path: str = "",
    grid_path: str = "",
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> None:
    """Plot + SE horizon warning/caption after Verbrauch / PV / Bilanz import."""
    verbrauch_rows = _load_profile_rows(verbrauch_path)
    pv_rows = _load_profile_rows(pv_path)
    battery_rows = _load_profile_rows(battery_path)
    grid_rows = _load_profile_rows(grid_path)
    derived, clipped = balance_gesamt_for_chart(
        pv_rows,
        battery_rows,
        grid_rows,
        invert_pv=invert_pv,
        invert_battery=invert_battery,
        invert_grid=invert_grid,
    )
    if derived is not None:
        verbrauch_rows = derived
        if clipped:
            st.warning(
                f"{clipped} Stunden mit negativem P_Ges auf 0 gekappt "
                "(Vorzeichen prüfen)."
            )
        else:
            st.caption(
                "Lastprofil [kW] (Gesamt) aus Bilanz berechnet: "
                "`P_Ges = P_PV + P_Batt + P_Grid` "
                "(fehlende Batterie = 0 kW)."
            )
    if (
        verbrauch_rows is None
        and pv_rows is None
        and battery_rows is None
        and grid_rows is None
    ):
        if verbrauch_path:
            st.warning(f"Lastprofil-CSV nicht gefunden: `{verbrauch_path}`")
        if pv_path:
            st.warning(f"PV-CSV nicht gefunden: `{pv_path}`")
        if battery_path:
            st.warning(f"Batterie-CSV nicht gefunden: `{battery_path}`")
        if grid_path:
            st.warning(f"Netz-CSV nicht gefunden: `{grid_path}`")
        return

    span_bounds = _shared_bounds(verbrauch_rows, pv_rows, battery_rows, grid_rows)
    if span_bounds is not None:
        span_h = int(
            (span_bounds[1] - span_bounds[0]).total_seconds() // 3600
        ) + 1
    else:
        span_h = shared_import_span_hours(verbrauch_rows, pv_rows)
    bounds = span_bounds
    months_approx = span_h / (MIN_HOURS_FULL_YEAR / 12.0) if span_h else 0.0
    if bounds is not None:
        st.caption(
            f"Zeitraum (Schnittmenge der geladenen Serien): "
            f"{bounds[0].strftime('%Y-%m-%d')} – {bounds[1].strftime('%Y-%m-%d')} "
            f"({span_h} h, ca. {months_approx:.1f} Monate)."
        )
    st.plotly_chart(
        import_power_qc_figure(
            verbrauch_rows,
            pv_rows,
            battery_rows=battery_rows,
            grid_rows=grid_rows,
        ),
        width="stretch",
        key=f"house_profile_import_qc_{preview_id}",
    )

    adequate = import_span_adequate_for_se(verbrauch_rows, pv_rows)
    if not adequate:
        st.warning(
            "Szenario-Explorer benötigt mindestens 12 Monate Daten. "
            "Kurze CSV-Importe dienen nur der visuellen Kontrolle (QC). "
            "Im SE werden synthetische Verbrauchs- und PV-Werte genutzt "
            "(Hausprofil / Open-Meteo) — nicht die kurze Meter-CSV."
        )
        return

    assert bounds is not None
    se_start, se_end = _se_window_from_data_max(bounds[1])
    se_start = max(se_start, bounds[0])
    test_month = _march_in_window(se_start, se_end)
    month_label = (
        f"Testmonat SE: März ({test_month:02d})"
        if test_month == 3
        else f"Testmonat SE: {test_month:02d} (März nicht im Fenster)"
    )
    st.info(
        f"SE-Zeitraum (letzte 12 vollständige Monate bis Datenende): "
        f"{se_start.strftime('%Y-%m-%d')} – {se_end.strftime('%Y-%m-%d')}. "
        f"{month_label}."
    )
