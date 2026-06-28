"""Live-Sankey-Diagramm für den Echtzeit-Leistungsfluss."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

import config
from data import live_consumption
from integrations import loxone_client
from runtime_store import run_state
from ui.runtime_config import reload_runtime_config
from ui import sankey_produktiv as produktiv

_FLEX_SANKEY_COLORS = ("#e67e22", "#9b59b6", "#1abc9c", "#e74c3c", "#34495e")
_MIN_FLOW_KW = produktiv.MIN_REAL_FLOW_KW


def _grid_label(grid_kw: float) -> str:
    if grid_kw >= 0:
        return f"🔌 Stromnetz (Bezug: {grid_kw:.2f} kW)"
    return f"🔌 Stromnetz (Einspeisung: {abs(grid_kw):.2f} kW)"


def _grid_color(grid_kw: float) -> str:
    return "crimson" if grid_kw >= 0 else "#95a5a6"


def _battery_color(battery_kw: float) -> str:
    if battery_kw < 0:
        return "forestgreen"
    if battery_kw > 0:
        return "crimson"
    return "#95a5a6"


def _live_battery_label(current_soc: float, battery_kw: float) -> str:
    if battery_kw >= 0:
        return f"🔋 Batterie ({current_soc:.1f} % - Entladen: {battery_kw:.2f} kW)"
    return f"🔋 Batterie ({current_soc:.1f} % - Laden: {abs(battery_kw):.2f} kW)"


def _battery_label(current_soc: float, battery_kw: float, main_state: dict | None) -> str:
    if produktiv.has_produktiv_run(main_state):
        return produktiv.battery_node_label(current_soc, battery_kw, main_state)
    return _live_battery_label(current_soc, battery_kw)


def _flex_label(consumer: dict, live_kw: float, main_state: dict | None) -> str:
    if produktiv.has_produktiv_run(main_state):
        return produktiv.flex_node_label(
            consumer["name"],
            live_kw,
            consumer["id"],
            main_state,
        )
    return f"⚡ {consumer['name']} ({live_kw:.2f} kW)"


class _SankeyLinks:
    def __init__(self) -> None:
        self.sources: list[int] = []
        self.targets: list[int] = []
        self.values: list[float] = []
        self.colors: list[str] = []
        self.hover: list[str] = []

    def add(
        self,
        source: int,
        target: int,
        value: float,
        *,
        color: str | None = None,
        hover: str | None = None,
    ) -> None:
        self.sources.append(source)
        self.targets.append(target)
        self.values.append(value)
        self.colors.append(color or produktiv._DEFAULT_LINK_COLOR)
        self.hover.append(hover if hover is not None else f"{value:.2f} kW")


def _append_sources_to_system(links: _SankeyLinks, data: dict, system_idx: int) -> None:
    if data["pv"] > _MIN_FLOW_KW:
        links.add(0, system_idx, data["pv"], hover=f"PV: {data['pv']:.2f} kW")
    if data["grid"] > _MIN_FLOW_KW:
        links.add(1, system_idx, data["grid"], hover=f"Netz Bezug: {data['grid']:.2f} kW")
    if data["battery"] > _MIN_FLOW_KW:
        links.add(2, system_idx, data["battery"], hover=f"Batterie Entladen: {data['battery']:.2f} kW")


def _append_return_flows(links: _SankeyLinks, data: dict, system_idx: int) -> None:
    if data["grid"] < -_MIN_FLOW_KW:
        links.add(
            system_idx,
            1,
            abs(data["grid"]),
            hover=f"Netz Einspeisung: {abs(data['grid']):.2f} kW",
        )
    if data["battery"] < -_MIN_FLOW_KW:
        links.add(
            system_idx,
            2,
            abs(data["battery"]),
            hover=f"Batterie Laden: {abs(data['battery']):.2f} kW",
        )


def _prepare_sankey_data(
    data: dict,
    current_soc: float,
    breakdown: dict | None = None,
    main_state: dict | None = None,
) -> tuple[list[str], _SankeyLinks, list[str]]:
    """Sankey: Energiebilanz; optional Auflösung Haus → Grundlast + flexible Verbraucher."""
    lbl_pv = f"☀️ PV-Anlage ({data['pv']:.2f} kW)"
    lbl_grid = _grid_label(data["grid"])
    lbl_bat = _battery_label(current_soc, data["battery"], main_state)
    c_grid = _grid_color(data["grid"])
    c_bat = _battery_color(data["battery"])
    links = _SankeyLinks()

    if breakdown:
        consumers = config.get_flexible_consumers()
        lbl_baseload = f"🏠 Grundlast ({breakdown['baseload_kw']:.2f} kW)"
        flex_labels = [
            _flex_label(
                consumer,
                float((breakdown.get("flex_kw") or {}).get(consumer["id"], 0.0) or 0.0),
                main_state,
            )
            for consumer in consumers
        ]

        labels = [lbl_pv, lbl_grid, lbl_bat, "⚙️ System-Knoten", lbl_baseload, *flex_labels]
        system_idx = 3
        baseload_idx = 4
        flex_start = 5

        node_colors = ["#f1c40f", c_grid, c_bat, "#7f8c8d", "#3498db"]
        overlay = produktiv.has_produktiv_run(main_state)
        for i, consumer in enumerate(consumers):
            palette = _FLEX_SANKEY_COLORS[i % len(_FLEX_SANKEY_COLORS)]
            live_kw = float((breakdown.get("flex_kw") or {}).get(consumer["id"], 0.0) or 0.0)
            if overlay:
                palette = produktiv.flex_node_color(palette, live_kw, consumer["id"], main_state)
            node_colors.append(palette)

        _append_sources_to_system(links, data, system_idx)

        if breakdown["baseload_kw"] > _MIN_FLOW_KW:
            links.add(
                system_idx,
                baseload_idx,
                breakdown["baseload_kw"],
                hover=f"Grundlast: {breakdown['baseload_kw']:.2f} kW",
            )
        for i, consumer in enumerate(consumers):
            live_kw = float((breakdown.get("flex_kw") or {}).get(consumer["id"], 0.0) or 0.0)
            link_kw, is_placeholder = produktiv.flex_sankey_link(
                live_kw,
                consumer["id"],
                main_state,
            )
            if link_kw is None:
                continue
            links.add(
                system_idx,
                flex_start + i,
                link_kw,
                color=(
                    produktiv._SOLL_PLACEHOLDER_LINK_COLOR
                    if is_placeholder
                    else produktiv._DEFAULT_LINK_COLOR
                ),
                hover=produktiv.flex_link_hover(
                    live_kw,
                    consumer["id"],
                    main_state,
                    is_placeholder,
                ),
            )
        _append_return_flows(links, data, system_idx)

        return labels, links, node_colors

    lbl_house = f"🏠 Wohnhaus ({data['house']:.2f} kW)"
    labels = [lbl_pv, lbl_grid, lbl_bat, lbl_house, "⚙️ System-Knoten"]

    if data["pv"] > _MIN_FLOW_KW:
        links.add(0, 4, data["pv"])
    if data["grid"] > _MIN_FLOW_KW:
        links.add(1, 4, data["grid"])
    if data["battery"] > _MIN_FLOW_KW:
        links.add(2, 4, data["battery"])
    if data["house"] > _MIN_FLOW_KW:
        links.add(4, 3, data["house"], hover=f"Wohnhaus: {data['house']:.2f} kW")
    _append_return_flows(links, data, 4)

    colors = ["#f1c40f", c_grid, c_bat, "#3498db", "#7f8c8d"]
    return labels, links, colors


def _sankey_height(breakdown: dict | None, main_state: dict | None) -> int:
    if not breakdown:
        return 280
    overlay = produktiv.has_produktiv_run(main_state)
    per_consumer = 40 if overlay else 25
    return 300 + len(config.get_flexible_consumers()) * per_consumer


def _create_live_flow_sankey(
    data: dict,
    current_soc: float,
    breakdown: dict | None = None,
    main_state: dict | None = None,
) -> go.Figure:
    """Erstellt ein dynamisches Energiefluss-Diagramm."""
    labels, links, colors = _prepare_sankey_data(
        data,
        current_soc=current_soc,
        breakdown=breakdown,
        main_state=main_state,
    )
    overlay = produktiv.has_produktiv_run(main_state)
    font_size = 11 if overlay and breakdown else 12

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=18 if overlay else 15,
                    thickness=20,
                    label=labels,
                    color=colors,
                ),
                link=dict(
                    source=links.sources,
                    target=links.targets,
                    value=links.values,
                    color=links.colors,
                    customdata=links.hover,
                    hovertemplate="%{customdata}<extra></extra>",
                ),
                valueformat=".2f",
                valuesuffix=" kW",
            )
        ]
    )

    fig.update_layout(
        height=_sankey_height(breakdown, main_state),
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(color="black", size=font_size),
    )
    return fig


@st.fragment(run_every=10)
def render_live_power_flow(current_soc: float) -> None:
    """Rendert die Live-Leistungsfluss-Ansicht mit CSS-Fix gegen den Text-Glow."""
    reload_runtime_config()
    st.write("### ⚡ Energiefluss (Live)")

    main_state = run_state.load_run_state()
    st.caption(produktiv.produktiv_caption(main_state))

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

    if main_state and main_state.get("consumption_snapshot"):
        age = run_state.age_seconds(main_state)
        if age is not None and age <= produktiv.PRODUKTIV_RUN_FRESH_SEC:
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
        main_state=main_state,
    )
    st.plotly_chart(fig, width="stretch", key="live_power_flow_sankey")
