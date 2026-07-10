"""Charts für Plausibilisierung einzelner Backtesting-Fenster."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from simulation.engine import window_slot_datetimes

_COCKPIT_HINT = (
    "Cockpit-Energiebilanz nicht verfügbar (keine Live-Optimierungshistorie "
    "für historische Backtesting-Fenster)."
)


def failure_window_label(failure: dict) -> str:
    window_end = str(failure.get("window_end", "?"))
    diff_kwh = float(failure.get("diff_kwh", 0.0) or 0.0)
    return f"{window_end} · Δ {diff_kwh:+.2f} kWh"


def slice_cons_data_for_window(cons_df: pd.DataFrame, window_end_iso: str) -> pd.DataFrame:
    """24h-Verbrauchsslots zum Plausibilitäts-Fensterende."""
    window_end = datetime.fromisoformat(window_end_iso.replace("Z", "+00:00"))
    if window_end.tzinfo is not None:
        window_end = window_end.replace(tzinfo=None)
    slots = window_slot_datetimes(window_end)
    idx = pd.DatetimeIndex(slots)
    if cons_df.empty:
        return pd.DataFrame(columns=cons_df.columns)
    aligned = cons_df.copy()
    if aligned.index.tz is not None:
        aligned.index = aligned.index.tz_localize(None)
    return aligned.reindex(idx)


def plausibility_window_consumption_chart(
    cons_slice: pd.DataFrame,
    failure: dict,
) -> go.Figure:
    """Historischer 24h-Verlauf und Soll/Ist-Summen aus dem Failure-Eintrag."""
    fig = go.Figure()
    if not cons_slice.empty and "total_kw" in cons_slice.columns:
        x_labels = [ts.strftime("%d.%m. %H:%M") for ts in cons_slice.index]
        fig.add_scatter(
            name="total_kw (historisch)",
            x=x_labels,
            y=cons_slice["total_kw"].fillna(0.0).astype(float).tolist(),
            mode="lines",
        )
        if "baseload_kw" in cons_slice.columns:
            fig.add_scatter(
                name="baseload_kw (historisch)",
                x=x_labels,
                y=cons_slice["baseload_kw"].fillna(0.0).astype(float).tolist(),
                mode="lines",
            )
    historical = float(failure.get("historical_kwh", 0.0) or 0.0)
    optimized = float(failure.get("optimized_kwh", 0.0) or 0.0)
    fig.add_bar(
        name="24h-Summen",
        x=["historisch", "optimiert"],
        y=[historical, optimized],
        yaxis="y2",
        opacity=0.35,
    )
    fig.update_layout(
        title=f"Fensterende {failure.get('window_end', '?')}",
        xaxis_title="Zeit",
        yaxis=dict(title="kW"),
        yaxis2=dict(title="kWh (24h)", overlaying="y", side="right", showgrid=False),
        height=380,
        margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


def cockpit_hint_caption() -> str:
    return _COCKPIT_HINT
