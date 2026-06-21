"""Live-Sankey-Diagramm für den Echtzeit-Leistungsfluss."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

import config
import live_consumption
import loxone_client
import run_state
from ui.runtime_config import reload_runtime_config

_FLEX_SANKEY_COLORS = ("#e67e22", "#9b59b6", "#1abc9c", "#e74c3c", "#34495e")


def _prepare_sankey_data(
    data: dict,
    current_soc: float,
    breakdown: dict | None = None,
) -> tuple[list[str], list[int], list[int], list[float], list[str]]:
    """Sankey: Energiebilanz; optional Auflösung Haus → Grundlast + flexible Verbraucher."""
    lbl_pv = f"☀️ PV-Anlage ({data['pv']:.2f} kW)"
    if data["grid"] >= 0:
        lbl_grid = f"🔌 Stromnetz (Bezug: {data['grid']:.2f} kW)"
    else:
        lbl_grid = f"🔌 Stromnetz (Einspeisung: {abs(data['grid']):.2f} kW)"
    if data["battery"] >= 0:
        lbl_bat = f"🔋 Batterie ({current_soc:.1f}% - Entladen: {data['battery']:.2f} kW)"
    else:
        lbl_bat = f"🔋 Batterie ({current_soc:.1f}% - Laden: {abs(data['battery']):.2f} kW)"

    c_grid = "crimson" if data["grid"] >= 0 else "#95a5a6"
    c_bat = (
        "forestgreen"
        if data["battery"] < 0
        else "crimson"
        if data["battery"] > 0
        else "#95a5a6"
    )

    sources, targets, values = [], [], []
    min_flow = 0.01

    if breakdown:
        consumers = config.get_flexible_consumers()
        lbl_baseload = f"🏠 Grundlast ({breakdown['baseload_kw']:.2f} kW)"
        flex_labels = []
        for consumer in consumers:
            kw = float((breakdown.get("flex_kw") or {}).get(consumer["id"], 0.0) or 0.0)
            flex_labels.append(f"⚡ {consumer['name']} ({kw:.2f} kW)")

        labels = [lbl_pv, lbl_grid, lbl_bat, "⚙️ System-Knoten", lbl_baseload, *flex_labels]
        system_idx = 3
        baseload_idx = 4
        flex_start = 5

        node_colors = ["#f1c40f", c_grid, c_bat, "#7f8c8d", "#3498db"]
        node_colors.extend(
            _FLEX_SANKEY_COLORS[i % len(_FLEX_SANKEY_COLORS)] for i in range(len(consumers))
        )

        if data["pv"] > min_flow:
            sources.append(0)
            targets.append(system_idx)
            values.append(data["pv"])
        if data["grid"] > min_flow:
            sources.append(1)
            targets.append(system_idx)
            values.append(data["grid"])
        if data["battery"] > min_flow:
            sources.append(2)
            targets.append(system_idx)
            values.append(data["battery"])

        if breakdown["baseload_kw"] > min_flow:
            sources.append(system_idx)
            targets.append(baseload_idx)
            values.append(breakdown["baseload_kw"])
        for i, consumer in enumerate(consumers):
            kw = float((breakdown.get("flex_kw") or {}).get(consumer["id"], 0.0) or 0.0)
            if kw > min_flow:
                sources.append(system_idx)
                targets.append(flex_start + i)
                values.append(kw)
        if data["grid"] < -min_flow:
            sources.append(system_idx)
            targets.append(1)
            values.append(abs(data["grid"]))
        if data["battery"] < -min_flow:
            sources.append(system_idx)
            targets.append(2)
            values.append(abs(data["battery"]))

        return labels, sources, targets, values, node_colors

    lbl_house = f"🏠 Wohnhaus ({data['house']:.2f} kW)"
    labels = [lbl_pv, lbl_grid, lbl_bat, lbl_house, "⚙️ System-Knoten"]

    if data["pv"] > min_flow:
        sources.append(0)
        targets.append(4)
        values.append(data["pv"])
    if data["grid"] > min_flow:
        sources.append(1)
        targets.append(4)
        values.append(data["grid"])
    if data["battery"] > min_flow:
        sources.append(2)
        targets.append(4)
        values.append(data["battery"])
    if data["house"] > min_flow:
        sources.append(4)
        targets.append(3)
        values.append(data["house"])
    if data["grid"] < -min_flow:
        sources.append(4)
        targets.append(1)
        values.append(abs(data["grid"]))
    if data["battery"] < -min_flow:
        sources.append(4)
        targets.append(2)
        values.append(abs(data["battery"]))

    colors = ["#f1c40f", c_grid, c_bat, "#3498db", "#7f8c8d"]
    return labels, sources, targets, values, colors


def _create_live_flow_sankey(
    data: dict,
    current_soc: float,
    breakdown: dict | None = None,
) -> go.Figure:
    """Erstellt ein dynamisches Energiefluss-Diagramm."""
    labels, sources, targets, values, colors = _prepare_sankey_data(
        data, current_soc=current_soc, breakdown=breakdown
    )
    height = 280 + (len(config.get_flexible_consumers()) * 25 if breakdown else 0)

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(pad=15, thickness=20, label=labels, color=colors),
                link=dict(
                    source=sources,
                    target=targets,
                    value=values,
                    color="rgba(180, 180, 180, 0.25)",
                ),
                valueformat=".2f",
                valuesuffix=" kW",
            )
        ]
    )

    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(color="black", size=12),
    )
    return fig


@st.fragment(run_every=10)
def render_live_power_flow(current_soc: float) -> None:
    """Rendert die Live-Leistungsfluss-Ansicht mit CSS-Fix gegen den Text-Glow."""
    reload_runtime_config()
    st.write("### ⚡ Echtzeit-Leistungsfluss (Live)")

    st.markdown(
        """
        <style>
        .js-plotly-plot .sankey-node text {
            text-shadow: none !important;
            stroke: none !important;
            fill: black !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    data = loxone_client.fetch_loxone_live_power()
    if data is None:
        st.warning("⚠️ Live-Leistungswerte konnten nicht von Loxone geladen werden.")
        return

    main_state = run_state.load_run_state()
    if main_state and main_state.get("consumption_snapshot"):
        age = run_state.age_seconds(main_state)
        if age is not None and age <= 120:
            snapshot = main_state["consumption_snapshot"]
        else:
            flex_kw = loxone_client.fetch_flexible_consumers_live_kw()
            snapshot = live_consumption.build_consumption_snapshot(data, flex_kw)
    else:
        flex_kw = loxone_client.fetch_flexible_consumers_live_kw()
        snapshot = live_consumption.build_consumption_snapshot(data, flex_kw)

    fig = _create_live_flow_sankey(
        data,
        current_soc=current_soc,
        breakdown=snapshot,
    )
    st.plotly_chart(fig, width="stretch", key="live_power_flow_sankey")
