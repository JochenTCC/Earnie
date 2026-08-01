"""Plotly charts and KPI renderers for Analyse Verbrauch & Kosten."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from ui.chart_colors import (
    COLOR_BASELOAD,
    COLOR_GRID_IMPORT,
    COLOR_PV,
    MUTED_BATTERY_CHARGE_GRID,
    MUTED_BATTERY_CHARGE_PV,
    MUTED_BATTERY_EXPORT,
    MUTED_BATTERY_LOAD,
    flex_bar_chart_color,
)
from ui.consumer_cost_analysis_data import (
    BASELOAD_ID,
    CostAnalysisSeries,
    CostAnalysisSlot,
    PeriodTotals,
    aggregate_slots,
    cost_analysis_consumers,
    filter_slots_calendar_month,
    filter_slots_calendar_year,
    filter_slots_iso_week,
)
from ui.consumption_validation_charts import format_iso_week_label


def _label(labels: Mapping[str, str], consumer_id: str) -> str:
    return labels.get(consumer_id, consumer_id)


def _consumer_color(consumer_id: str, consumers_by_id: Mapping[str, Mapping[str, Any]]) -> str:
    if consumer_id == BASELOAD_ID:
        return COLOR_BASELOAD
    consumer = consumers_by_id.get(consumer_id)
    if consumer is None:
        return COLOR_GRID_IMPORT
    return flex_bar_chart_color(consumer)


def _consumers_by_id() -> dict[str, Mapping[str, Any]]:
    return {str(c["id"]): c for c in cost_analysis_consumers()}


def _ordered_consumer_ids(slots: Sequence[CostAnalysisSlot]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        for share in slot.shares:
            if share.consumer_id in seen:
                continue
            seen.add(share.consumer_id)
            order.append(share.consumer_id)
    if BASELOAD_ID in order:
        order.remove(BASELOAD_ID)
        order.insert(0, BASELOAD_ID)
    return order


def week_usage_vs_price_pv_chart(
    slots: Sequence[CostAnalysisSlot],
    *,
    labels: Mapping[str, str],
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    """Stacked consumer kWh bars with PV (kW) and price overlays."""
    fig = go.Figure()
    if not slots:
        fig.update_layout(title="Keine Daten")
        return fig

    x_values = [slot.slot_start for slot in slots]
    consumer_ids = _ordered_consumer_ids(slots)
    by_id = _consumers_by_id()
    energy_by_id: dict[str, list[float]] = {cid: [] for cid in consumer_ids}
    for slot in slots:
        share_map = {s.consumer_id: s for s in slot.shares}
        for cid in consumer_ids:
            share = share_map.get(cid)
            if share is None:
                energy_by_id[cid].append(0.0)
            else:
                energy_by_id[cid].append(
                    share.pv_kwh + share.battery_kwh + share.grid_kwh
                )

    for cid in consumer_ids:
        fig.add_bar(
            name=_label(labels, cid),
            x=x_values,
            y=energy_by_id[cid],
            marker_color=_consumer_color(cid, by_id),
            yaxis="y",
        )

    fig.add_scatter(
        name="PV (kW)",
        x=x_values,
        y=[slot.pv_kw for slot in slots],
        mode="lines",
        line=dict(color=COLOR_PV, width=2),
        yaxis="y",
    )
    fig.add_scatter(
        name="Importpreis",
        x=x_values,
        y=[slot.price_cent for slot in slots],
        mode="lines",
        line=dict(color=COLOR_GRID_IMPORT, width=2, dash="dot"),
        yaxis="y2",
    )
    fig.update_layout(
        title=f"Verbrauch vs. Preis & PV — {format_iso_week_label(iso_year, iso_week)}",
        barmode="stack",
        height=380,
        margin=dict(l=40, r=50, t=50, b=40),
        yaxis=dict(title="kWh / kW", side="left"),
        yaxis2=dict(
            title="Cent/kWh",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(type="date", tickformat="%a %d.%m. %H:%M"),
    )
    return fig


def week_source_mix_chart(
    slots: Sequence[CostAnalysisSlot],
    *,
    labels: Mapping[str, str],
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    """Stacked PV / battery / grid energy per consumer for the week."""
    totals = aggregate_slots(slots)
    fig = go.Figure()
    consumer_ids = list(totals.by_consumer.keys())
    if BASELOAD_ID in consumer_ids:
        consumer_ids.remove(BASELOAD_ID)
        consumer_ids.insert(0, BASELOAD_ID)
    x_labels = [_label(labels, cid) for cid in consumer_ids]
    fig.add_bar(
        name="PV",
        x=x_labels,
        y=[totals.by_consumer[cid].pv_kwh for cid in consumer_ids],
        marker_color=COLOR_PV,
    )
    fig.add_bar(
        name="Batterie",
        x=x_labels,
        y=[totals.by_consumer[cid].battery_kwh for cid in consumer_ids],
        marker_color=MUTED_BATTERY_LOAD,
    )
    fig.add_bar(
        name="Netz",
        x=x_labels,
        y=[totals.by_consumer[cid].grid_kwh for cid in consumer_ids],
        marker_color=COLOR_GRID_IMPORT,
    )
    fig.update_layout(
        title=f"Herkunft je Verbraucher — {format_iso_week_label(iso_year, iso_week)}",
        barmode="stack",
        height=340,
        margin=dict(l=40, r=20, t=50, b=40),
        yaxis_title="kWh",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def week_cost_chart(
    slots: Sequence[CostAnalysisSlot],
    *,
    labels: Mapping[str, str],
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    """Per-consumer grid-attributed € for the week (option I)."""
    totals = aggregate_slots(slots)
    fig = go.Figure()
    consumer_ids = list(totals.by_consumer.keys())
    if BASELOAD_ID in consumer_ids:
        consumer_ids.remove(BASELOAD_ID)
        consumer_ids.insert(0, BASELOAD_ID)
    by_id = _consumers_by_id()
    fig.add_bar(
        name="Netzanteil-Kosten",
        x=[_label(labels, cid) for cid in consumer_ids],
        y=[totals.by_consumer[cid].cost_euro for cid in consumer_ids],
        marker_color=[_consumer_color(cid, by_id) for cid in consumer_ids],
    )
    fig.update_layout(
        title=(
            f"Kosten (nur Netzanteil) — {format_iso_week_label(iso_year, iso_week)}"
        ),
        height=320,
        margin=dict(l=40, r=20, t=50, b=40),
        yaxis_title="€",
        showlegend=False,
    )
    return fig


def battery_flow_chart(totals: PeriodTotals, *, title: str) -> go.Figure:
    """Stacked charge (PV/grid) and discharge (load/export) for the period."""
    categories = ["Laden", "Entladen"]
    fig = go.Figure()
    fig.add_bar(
        name="PV",
        x=categories,
        y=[totals.charge_from_pv_kwh, 0.0],
        marker_color=MUTED_BATTERY_CHARGE_PV,
    )
    fig.add_bar(
        name="Netz (Laden)",
        x=categories,
        y=[totals.charge_from_grid_kwh, 0.0],
        marker_color=MUTED_BATTERY_CHARGE_GRID,
    )
    fig.add_bar(
        name="Verbrauch",
        x=categories,
        y=[0.0, totals.discharge_to_load_kwh],
        marker_color=MUTED_BATTERY_LOAD,
    )
    fig.add_bar(
        name="Netz (Einspeisung)",
        x=categories,
        y=[0.0, totals.export_from_battery_kwh],
        marker_color=MUTED_BATTERY_EXPORT,
    )
    fig.update_layout(
        title=title,
        barmode="stack",
        height=280,
        margin=dict(l=40, r=20, t=50, b=40),
        yaxis_title="kWh",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def battery_flow_balance_caption(totals: PeriodTotals) -> str:
    """German note comparing stacked charge vs discharge totals."""
    charge = float(totals.battery_charge_kwh)
    discharge = float(totals.battery_discharge_kwh)
    delta = charge - discharge
    return (
        f"Laden {charge:.2f} kWh · Entladen {discharge:.2f} kWh · Δ {delta:+.2f} kWh. "
        "Kleine Abweichungen sind normal (SoC-Änderung, Standby der Batterie)."
    )


def _format_coverage(series: CostAnalysisSeries) -> str:
    if series.data_start is None or series.data_end is None:
        return "Keine Produktiv-Log-Daten."
    start = series.data_start.strftime("%d.%m.%Y %H:%M")
    end = series.data_end.strftime("%d.%m.%Y %H:%M")
    return (
        f"Datengrundlage Produktiv-Log: {start} – {end} "
        f"({len(series.slots)} Slots). Kosten ≈ Netzanteil × Importpreis "
        f"(PV/Batterie am Verbrauchsort 0 €; keine Rechnungskorrektur)."
    )


def render_period_kpis(
    series: CostAnalysisSeries,
    *,
    week_slots: Sequence[CostAnalysisSlot],
    iso_year: int,
    iso_week: int,
    now: datetime,
) -> None:
    """Week / month / year rough totals and per-consumer cost table."""
    week = aggregate_slots(week_slots)
    month_slots = filter_slots_calendar_month(
        series.slots, year=now.year, month=now.month
    )
    year_slots = filter_slots_calendar_year(series.slots, year=now.year)
    month = aggregate_slots(month_slots)
    year = aggregate_slots(year_slots)

    st.caption(_format_coverage(series))
    c1, c2, c3 = st.columns(3)
    c1.metric(
        f"KW {iso_week}/{iso_year}",
        f"{week.cost_euro:.2f} €",
        help=f"{week.energy_kwh:.1f} kWh · {week.slot_count} Slots",
    )
    c2.metric(
        f"Monat {now.month:02d}/{now.year}",
        f"{month.cost_euro:.2f} €",
        help=f"{month.energy_kwh:.1f} kWh · {month.slot_count} Slots",
    )
    c3.metric(
        f"Jahr {now.year}",
        f"{year.cost_euro:.2f} €",
        help=f"{year.energy_kwh:.1f} kWh · {year.slot_count} Slots",
    )

    rows = []
    for cid, share in sorted(week.by_consumer.items(), key=lambda item: item[0]):
        rows.append(
            {
                "Verbraucher": _label(series.consumer_labels, cid),
                "kWh": round(share.pv_kwh + share.battery_kwh + share.grid_kwh, 2),
                "PV kWh": round(share.pv_kwh, 2),
                "Batterie kWh": round(share.battery_kwh, 2),
                "Netz kWh": round(share.grid_kwh, 2),
                "Kosten €": round(share.cost_euro, 2),
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")


def render_week_analysis(
    series: CostAnalysisSeries,
    *,
    iso_year: int,
    iso_week: int,
    now: datetime,
) -> None:
    """Week charts, KPIs, and battery panel for the selected ISO week."""
    week_slots = filter_slots_iso_week(
        series.slots, iso_year=iso_year, iso_week=iso_week
    )
    if not week_slots:
        st.info(
            f"Keine Log-Slots für {format_iso_week_label(iso_year, iso_week)}."
        )
        return

    labels = series.consumer_labels
    st.plotly_chart(
        week_usage_vs_price_pv_chart(
            week_slots, labels=labels, iso_year=iso_year, iso_week=iso_week
        ),
        width="stretch",
    )
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            week_source_mix_chart(
                week_slots, labels=labels, iso_year=iso_year, iso_week=iso_week
            ),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            week_cost_chart(
                week_slots, labels=labels, iso_year=iso_year, iso_week=iso_week
            ),
            width="stretch",
        )

    render_period_kpis(
        series,
        week_slots=week_slots,
        iso_year=iso_year,
        iso_week=iso_week,
        now=now,
    )
    week_totals = aggregate_slots(week_slots)
    st.plotly_chart(
        battery_flow_chart(
            week_totals,
            title=f"Batterie-Energieflüsse — {format_iso_week_label(iso_year, iso_week)}",
        ),
        width="stretch",
    )
    st.caption(battery_flow_balance_caption(week_totals))
