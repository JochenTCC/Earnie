"""Backtesting-Auswertung aus scripts/run_backtesting.py."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from simulation import backtesting_log
from simulation.engine import HISTORICAL_REFERENCE_ID


@st.cache_data(ttl=60, show_spinner="Lade Backtesting-Log...")
def load_backtesting_data():
    return backtesting_log.load_backtesting_log()


def render_backtesting_controls(meta: dict, hourly: pd.DataFrame) -> tuple[str, str | None]:
    """Detailansicht-Steuerung im Seiten-Body (ersetzt die frühere Sidebar)."""
    st.subheader("📊 Backtesting-Log")
    created = meta.get("created_at", "")[:19].replace("T", " ")
    period = meta.get("period", {})
    st.caption(
        f"Erstellt: {created} UTC · "
        f"Zeitraum: {period.get('start', '?')} – {period.get('end', '?')} "
        f"({period.get('windows', '?')} Fenster)"
    )

    labels = meta.get("labels", {})
    scenario_ids = meta.get("scenario_ids", hourly["scenario_id"].unique().tolist())
    scenario_labels = [labels.get(sid, sid) for sid in scenario_ids]
    months = sorted(hourly["ts"].dt.to_period("M").astype(str).unique())

    col_scenario, col_month = st.columns(2)
    selected_label = col_scenario.selectbox(
        "Szenario (Detailansicht)",
        scenario_labels,
        index=0,
    )
    selected_id = scenario_ids[scenario_labels.index(selected_label)]

    month_filter = col_month.selectbox(
        "Monat (Detailansicht)",
        ["Gesamter Zeitraum"] + months,
    )
    month_key = None if month_filter == "Gesamter Zeitraum" else month_filter
    return selected_id, month_key


def render_backtesting_summary(meta: dict) -> None:
    st.subheader("💶 Gesamtkosten-Vergleich")
    summary = meta.get("summary", {})
    totals = summary.get("total_eur", {})
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    ref_total = totals.get(ref_id)

    cols = st.columns(min(len(totals), 4))
    for idx, (sid, total) in enumerate(totals.items()):
        col = cols[idx % len(cols)]
        label = labels.get(sid, sid)
        if sid == ref_id:
            col.metric(label, f"{total:.2f} €", help="Historischer Verbrauch ohne Optimierung")
        elif ref_total is not None:
            savings = ref_total - total
            col.metric(
                label,
                f"{total:.2f} €",
                delta=f"{savings:+.2f} € vs Referenz",
                delta_color="normal" if savings >= 0 else "inverse",
            )
        else:
            col.metric(label, f"{total:.2f} €")


def render_backtesting_monthly_table(meta: dict) -> None:
    st.subheader("📅 Monatlicher Kostenvergleich")
    monthly = meta.get("summary", {}).get("monthly_eur", {})
    if not monthly:
        st.info("Keine Monatswerte im Log.")
        return
    df = pd.DataFrame(monthly).T.round(2)
    df.index.name = "Monat"
    st.dataframe(df, width="stretch")

    ref_label = meta.get("labels", {}).get(
        meta.get("reference_id", HISTORICAL_REFERENCE_ID),
        "Referenz",
    )
    if ref_label in df.columns:
        chart_df = df.drop(columns=[c for c in df.columns if c.startswith("Einsparung")], errors="ignore")
        st.bar_chart(chart_df, height=350)


def render_backtesting_plausibility(meta: dict, scenario_id: str) -> None:
    plausi = meta.get("plausibility", {}).get(scenario_id)
    if not plausi:
        return
    label = meta.get("labels", {}).get(scenario_id, scenario_id)
    st.subheader(f"✅ Plausibilisierung – {label}")
    ok = plausi.get("ok_count", 0)
    total = plausi.get("total_windows", 0)
    failed = plausi.get("failed_count", 0)
    st.caption(
        f"{ok}/{total} Fenster OK "
        f"(Toleranz: {plausi.get('tolerance_kwh')} kWh oder "
        f"{plausi.get('tolerance_rel', 0) * 100:.0f} % relativ)"
    )
    if failed:
        st.warning(f"{failed} Fenster ausserhalb der Toleranz")
        st.dataframe(
            pd.DataFrame(plausi.get("failures", [])),
            width="stretch",
            hide_index=True,
        )


def render_backtesting_hourly_chart(
    hourly: pd.DataFrame,
    scenario_id: str,
    month_key: str | None,
) -> None:
    df = hourly[hourly["scenario_id"] == scenario_id].copy()
    if month_key:
        df = df[df["ts"].dt.to_period("M").astype(str) == month_key]
    if df.empty:
        st.warning("Keine Stundenwerte für die Auswahl.")
        return

    label = df["scenario_label"].iloc[0]
    st.subheader(f"📈 Stundenverlauf – {label}" + (f" ({month_key})" if month_key else ""))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["ts"],
        y=df["sim_cost"],
        name="Stromkosten (€/h)",
        marker_color="steelblue",
        yaxis="y",
    ))
    if "sim_soc" in df.columns and df["sim_soc"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["ts"],
            y=df["sim_soc"],
            name="SoC (%)",
            line=dict(color="gold", width=2),
            yaxis="y2",
        ))
    fig.update_layout(
        xaxis_title="Zeit",
        yaxis=dict(title="Kosten (€)", side="left"),
        yaxis2=dict(title="SoC (%)", side="right", overlaying="y", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=40, t=40, b=40),
        height=400,
    )
    st.plotly_chart(fig, width="stretch")

    with st.expander("Stundendetails"):
        st.dataframe(
            df.sort_values("ts", ascending=False),
            width="stretch",
            hide_index=True,
        )


def render_backtesting_block() -> None:
    if not backtesting_log.log_exists():
        st.warning(
            "Kein Backtesting-Log gefunden. Bitte zuerst "
            "`python -m scripts.run_backtesting` ausführen "
            "(erzeugt `backtesting_log.json` und `backtesting_hourly.csv`)."
        )
        return

    try:
        meta, hourly = load_backtesting_data()
    except Exception as e:
        st.error(f"Backtesting-Log konnte nicht geladen werden: {e}")
        return

    selected_id, month_key = render_backtesting_controls(meta, hourly)
    render_backtesting_summary(meta)
    render_backtesting_monthly_table(meta)

    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    if selected_id != ref_id:
        render_backtesting_plausibility(meta, selected_id)

    render_backtesting_hourly_chart(hourly, selected_id, month_key)
