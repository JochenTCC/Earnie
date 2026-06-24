"""Plotly-Charts für 24h-Optimierungsdarstellung."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from optimizer import battery as bat

_COLOR_BASELINE = "#7f8c8d"
_COLOR_OPTIMIZED = "#e67e22"


def get_bar_colors(df: pd.DataFrame) -> list[str]:
    """Batterie-Balkenfarbe je Steuerbefehl (Modus)."""
    colors = []
    for cmd in df["Steuerbefehl"]:
        text = str(cmd)
        if text.startswith("Zwangsladen"):
            colors.append("forestgreen")
        elif text.startswith("Zwangsentladen"):
            colors.append("crimson")
        elif "Entladesperre" in text:
            colors.append("darkorange")
        elif text == "Baseline":
            colors.append("lightgray")
        elif text.startswith("Baseline (Ziel)"):
            colors.append("lightgray")
        else:
            colors.append("dodgerblue")
    return colors


def _active_consumer_bar_columns(df: pd.DataFrame) -> list[tuple[dict, str]]:
    """Verbraucher-Spalten mit sichtbaren Planwerten (> 0 kWh über den Tag)."""
    active = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = f"{consumer['name']} (kW)"
        if col in df.columns and df[col].sum() > 0:
            active.append((consumer, col))
    return active


def _chart_slot_x(length: int) -> pd.Series:
    """Numerische Slot-Positionen 0..n-1 (eine Einheit = eine Stunde)."""
    return pd.Series(range(length), dtype=float)


def _chart_line_x(slot_x: pd.Series) -> pd.Series:
    """Linien um 30 min zurück auf Slot-Mitte, passend zu den Stunden-Balken."""
    return slot_x - 0.5


def _extended_line_xy(
    slot_x: pd.Series,
    y: pd.Series,
    tail_y: float | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Verlängert Linien um 1 h für die -0.5-Verschiebung (Ende des letzten Slots)."""
    if y.empty:
        return _chart_line_x(slot_x), y
    tail_slot = float(slot_x.iloc[-1]) + 1.0
    extended_slot = pd.concat(
        [slot_x, pd.Series([tail_slot])],
        ignore_index=True,
    )
    end_y = y.iloc[-1] if tail_y is None else tail_y
    extended_y = pd.concat([y, pd.Series([end_y])], ignore_index=True)
    return _chart_line_x(extended_slot), extended_y


def _soc_tail_y_from_row(row: pd.Series) -> float | None:
    """SoC am Ende der Stunde aus geplanter Batterieaktion (Optimierer/Huawei-Logik)."""
    if "Geplante Batterie-Aktion (kW)" not in row.index:
        return None
    params = config.get_battery_params()
    new_soc, _ = bat.apply_soc_change(
        float(row["Simulierter SoC (%)"]),
        float(row["Geplante Batterie-Aktion (kW)"]),
        params["battery_capacity_kwh"],
        params["efficiency"],
        params["min_soc"],
        params["max_soc"],
    )
    return round(new_soc, 1)


def _extended_soc_line_xy(
    slot_x: pd.Series,
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    soc = df["Simulierter SoC (%)"]
    tail_y = _soc_tail_y_from_row(df.iloc[-1]) if not df.empty else None
    return _extended_line_xy(slot_x, soc, tail_y=tail_y)


def _extended_hover_labels(uhrzeit: pd.Series) -> list[str]:
    """Hover-Labels für verlängerte Linien (letzte Uhrzeit einmal wiederholt)."""
    if uhrzeit.empty:
        return []
    return pd.concat(
        [uhrzeit, pd.Series([uhrzeit.iloc[-1]])],
        ignore_index=True,
    ).tolist()


def _line_hover(uhrzeit: pd.Series, y_format: str) -> dict:
    return dict(
        customdata=_extended_hover_labels(uhrzeit),
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>%{fullData.name}: "
            f"%{{y:{y_format}}}<extra></extra>"
        ),
    )


def _bar_hover(uhrzeit: pd.Series, y_format: str) -> dict:
    return dict(
        customdata=uhrzeit,
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>%{fullData.name}: "
            f"%{{y:{y_format}}}<extra></extra>"
        ),
    )


def _chart_xaxis_config(uhrzeit: pd.Series) -> dict:
    tickvals = list(range(len(uhrzeit)))
    return dict(
        title="Uhrzeit (Stunden-Slots / Intervalle)",
        type="linear",
        tickmode="array",
        tickvals=tickvals,
        ticktext=uhrzeit.tolist(),
        range=[-0.5, len(uhrzeit) - 0.5],
    )


def _consumer_bar_x(
    slot_x: pd.Series,
    index: int,
    count: int,
    bar_width: float,
    base_offset: float,
) -> pd.Series:
    """X-Position je Stunde: nebeneinander und mit Batterie im selben Slot zentriert."""
    if count <= 1:
        return slot_x + base_offset
    shift = (index - (count - 1) / 2) * bar_width
    return slot_x + base_offset + shift


def add_power_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    bar_colors: list[str],
    slot_x: pd.Series,
) -> None:
    battery_bar_width = 0.9
    bar_offset = 0.05
    uhrzeit = df["Uhrzeit"]
    active_consumers = _active_consumer_bar_columns(df)
    consumer_count = len(active_consumers)
    consumer_bar_width = (
        battery_bar_width / consumer_count if consumer_count else battery_bar_width
    )
    if "PV-Prognose (kW)" in df.columns:
        pv_x, pv_y = _extended_line_xy(slot_x, df["PV-Prognose (kW)"])
        fig.add_trace(go.Scatter(
            x=pv_x,
            y=pv_y,
            name="PV",
            line=dict(color="#f1c40f", width=2),
            fill="tozeroy",
            fillcolor="rgba(241, 196, 15, 0.15)",
            yaxis="y",
            **_line_hover(uhrzeit, ".2f"),
        ))

    if "Verbrauch-Prognose (kW)" in df.columns:
        load_x, load_y = _extended_line_xy(slot_x, df["Verbrauch-Prognose (kW)"])
        fig.add_trace(go.Scatter(
            x=load_x,
            y=load_y,
            name="Verbrauch",
            line=dict(color="#3498db", width=2, dash="dash"),
            yaxis="y",
            **_line_hover(uhrzeit, ".2f"),
        ))

    fig.add_trace(go.Bar(
        x=slot_x + bar_offset,
        y=df["Geplante Batterie-Aktion (kW)"],
        name="Batterie",
        marker=dict(color=bar_colors),
        opacity=0.75,
        width=battery_bar_width,
        yaxis="y",
        **_bar_hover(uhrzeit, ".2f"),
    ))

    for index, (consumer, col) in enumerate(active_consumers):
        fig.add_trace(go.Bar(
            x=_consumer_bar_x(
                slot_x, index, consumer_count, consumer_bar_width, bar_offset
            ),
            y=df[col],
            name=consumer["name"],
            opacity=0.65,
            width=consumer_bar_width,
            yaxis="y",
            **_bar_hover(uhrzeit, ".2f"),
        ))


def add_optimized_soc_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    slot_x: pd.Series,
    yaxis: str = "y2",
) -> None:
    uhrzeit = df["Uhrzeit"]
    soc_x, soc_y = _extended_soc_line_xy(slot_x, df)
    fig.add_trace(go.Scatter(
        x=soc_x,
        y=soc_y,
        name="SoC",
        mode="lines",
        line=dict(color=_COLOR_OPTIMIZED, width=2.5),
        yaxis=yaxis,
        **_line_hover(uhrzeit, ".1f"),
    ))


def add_baseline_soc_traces(
    fig: go.Figure,
    baseline_df: pd.DataFrame | None,
    matched_baseline_df: pd.DataFrame | None,
    yaxis: str = "y2",
) -> None:
    if baseline_df is not None and not baseline_df.empty:
        baseline_slot_x = _chart_slot_x(len(baseline_df))
        baseline_x, baseline_y = _extended_soc_line_xy(baseline_slot_x, baseline_df)
        fig.add_trace(go.Scatter(
            x=baseline_x,
            y=baseline_y,
            name="SoC BL Profil",
            mode="lines",
            line=dict(color=_COLOR_BASELINE, width=2.5, dash="dash"),
            yaxis=yaxis,
            **_line_hover(baseline_df["Uhrzeit"], ".1f"),
        ))
    if matched_baseline_df is not None and not matched_baseline_df.empty:
        matched_slot_x = _chart_slot_x(len(matched_baseline_df))
        matched_x, matched_y = _extended_soc_line_xy(matched_slot_x, matched_baseline_df)
        fig.add_trace(go.Scatter(
            x=matched_x,
            y=matched_y,
            name="SoC BL Ziel",
            mode="lines",
            line=dict(color=_COLOR_BASELINE, width=2.5, dash="dot"),
            yaxis=yaxis,
            **_line_hover(matched_baseline_df["Uhrzeit"], ".1f"),
        ))


def _scale_series_to_0_100(values: pd.Series) -> pd.Series:
    """Lineare Skalierung auf 0–100 (für gemeinsame Achse mit SoC)."""
    lo = float(values.min())
    hi = float(values.max())
    if hi - lo < 1e-6:
        return pd.Series([50.0] * len(values), index=values.index)
    return (values - lo) / (hi - lo) * 100.0


def add_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    slot_x: pd.Series,
    yaxis: str = "y2",
) -> None:
    """Strompreis auf der SoC-Achse (0–100), Hover zeigt Cent/kWh."""
    uhrzeit = df["Uhrzeit"]
    price_cent = df["Strompreis (Cent/kWh)"]
    price_scaled = _scale_series_to_0_100(price_cent)
    price_x, price_y = _extended_line_xy(slot_x, price_scaled)
    cent_labels = pd.concat(
        [price_cent, pd.Series([price_cent.iloc[-1]])],
        ignore_index=True,
    ).tolist()
    fig.add_trace(go.Scatter(
        x=price_x,
        y=price_y,
        name="Preis",
        mode="lines",
        line=dict(color="red", width=2.5, shape="hv"),
        yaxis=yaxis,
        customdata=cent_labels,
        hovertemplate=(
            "Uhrzeit: %{text}<br>Preis: %{customdata:.2f} Cent/kWh<extra></extra>"
        ),
        text=_extended_hover_labels(uhrzeit),
    ))


def add_cumulative_cost_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    slot_x: pd.Series,
    hourly_matched_cost_euro: list[float],
    hourly_optimized_cost_euro: list[float],
) -> None:
    """Kumulierte Stromkosten: BL Ziel und optimiert."""
    if not hourly_matched_cost_euro or not hourly_optimized_cost_euro:
        return
    length = len(slot_x)
    matched_cum = pd.Series(hourly_matched_cost_euro[:length], dtype=float).cumsum()
    optimized_cum = pd.Series(hourly_optimized_cost_euro[:length], dtype=float).cumsum()
    matched_x, matched_y = _extended_line_xy(slot_x, matched_cum)
    optimized_x, optimized_y = _extended_line_xy(slot_x, optimized_cum)
    fig.add_trace(go.Scatter(
        x=matched_x,
        y=matched_y,
        name="Kosten BL Ziel",
        mode="lines",
        line=dict(color=_COLOR_BASELINE, width=2.5, shape="hv"),
        customdata=_extended_hover_labels(uhrzeit),
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>Kosten BL Ziel (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=optimized_x,
        y=optimized_y,
        name="Kosten optimiert",
        mode="lines",
        line=dict(color=_COLOR_OPTIMIZED, width=2.5, shape="hv"),
        customdata=_extended_hover_labels(uhrzeit),
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>Kosten optimiert (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    ))


def add_cumulative_consumption_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    slot_x: pd.Series,
    hourly_matched_kwh: list[float],
    hourly_optimized_kwh: list[float],
    yaxis: str = "y2",
) -> None:
    """Kumulierter Gesamtverbrauch (Grundlast + Flex) auf separater Achse."""
    if not hourly_matched_kwh or not hourly_optimized_kwh:
        return
    length = len(slot_x)
    matched_cum = pd.Series(hourly_matched_kwh[:length], dtype=float).cumsum()
    optimized_cum = pd.Series(hourly_optimized_kwh[:length], dtype=float).cumsum()
    matched_x, matched_y = _extended_line_xy(slot_x, matched_cum)
    optimized_x, optimized_y = _extended_line_xy(slot_x, optimized_cum)
    fig.add_trace(go.Scatter(
        x=matched_x,
        y=matched_y,
        name="Verbrauch BL Ziel",
        mode="lines",
        line=dict(color=_COLOR_BASELINE, width=2.5, dash="dash", shape="hv"),
        yaxis=yaxis,
        customdata=_extended_hover_labels(uhrzeit),
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>Verbrauch BL Ziel (kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=optimized_x,
        y=optimized_y,
        name="Verbrauch optimiert",
        mode="lines",
        line=dict(color=_COLOR_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
        yaxis=yaxis,
        customdata=_extended_hover_labels(uhrzeit),
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>Verbrauch optimiert (kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    ))


def _chart_legend() -> dict:
    return dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        x=0.5,
        xanchor="center",
        font=dict(size=10),
    )


def render_power_soc_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
) -> None:
    """Leistungen (PV, Verbrauch, Batterie, Flex) und SoC-Verläufe."""
    bar_colors = get_bar_colors(df)
    slot_x = _chart_slot_x(len(df))
    fig = go.Figure()

    add_power_traces(fig, df, bar_colors, slot_x)
    add_optimized_soc_trace(fig, df, slot_x)
    add_baseline_soc_traces(fig, baseline_df, matched_baseline_df)
    add_price_on_soc_axis_trace(fig, df, slot_x)

    fig.update_layout(
        title="24-Stunden-Zeithorizont (Leistung, SoC & Preis)",
        xaxis=_chart_xaxis_config(df["Uhrzeit"]),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(
            title="SoC (%) / Preis (skaliert 0–100)",
            side="right",
            overlaying="y",
            showgrid=False,
            range=[0, 100],
        ),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=50, b=110),
    )
    st.caption(
        "Preis rot auf der rechten Achse: relativ auf 0–100 skaliert "
        "(Hover zeigt Cent/kWh)."
    )
    st.plotly_chart(fig, width="stretch")


def render_cumulative_cost_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
) -> None:
    """Kumulierte Stromkosten und Verbrauch BL Ziel vs. optimiert."""
    slot_x = _chart_slot_x(len(df))
    fig = go.Figure()
    has_costs = bool(hourly_matched_baseline_cost_euro and hourly_optimized_cost_euro)
    has_consumption = bool(
        hourly_matched_baseline_consumption_kwh and hourly_optimized_consumption_kwh
    )

    if has_costs:
        add_cumulative_cost_traces(
            fig,
            df["Uhrzeit"],
            slot_x,
            hourly_matched_baseline_cost_euro or [],
            hourly_optimized_cost_euro or [],
        )
    if has_consumption:
        add_cumulative_consumption_traces(
            fig,
            df["Uhrzeit"],
            slot_x,
            hourly_matched_baseline_consumption_kwh or [],
            hourly_optimized_consumption_kwh or [],
        )

    layout = dict(
        title="Kumulierte Kosten & Verbrauch",
        xaxis=_chart_xaxis_config(df["Uhrzeit"]),
        yaxis=dict(title="Kosten (€, kumuliert)"),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=50, b=110),
    )
    if has_consumption:
        layout["yaxis2"] = dict(
            title="Verbrauch (kWh, kumuliert)",
            side="right",
            overlaying="y",
            showgrid=False,
        )
    fig.update_layout(**layout)
    if has_costs or has_consumption:
        st.caption(
            "Durchgezogene Linien: Kosten. Gestrichelte Linien (rechte Achse): "
            "Gesamtverbrauch Grundlast + Flex. BL Ziel: historisches Profil skaliert."
        )
    st.plotly_chart(fig, width="stretch")


def render_price_savings_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
) -> None:
    """Alias für kumulierte Kosten- und Verbrauchslinien."""
    render_cumulative_cost_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
    )


def render_optimization_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    hourly_savings_euro: list[float] | None = None,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
) -> None:
    """Zeichnet Leistung/SoC/Preis und kumulierte Kosten/Verbrauch in zwei Charts."""
    render_power_soc_chart(df, baseline_df, matched_baseline_df)
    render_price_savings_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
    )
