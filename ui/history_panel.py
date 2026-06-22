"""Panel für vergangene Produktiv-Optimierungen."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from runtime_store import optimization_history


def _history_days_options() -> dict[str, int | None]:
    return {
        "Letzte 24 Stunden": 1,
        "Letzte 3 Tage": 3,
        "Letzte 7 Tage": 7,
        "Letzte 14 Tage": 14,
        "Letzte 30 Tage": 30,
        "Alles verfügbare": None,
    }


def _format_history_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    display = df.copy()
    display["Zeitpunkt"] = pd.to_datetime(display["completed_at"]).dt.strftime("%d.%m.%Y %H:%M")
    display = display.rename(columns={
        "soc_percent": "SoC (%)",
        "mode_label": "Modus",
        "target_power_kw": "Ziel-Leistung (kW)",
        "target_soc_percent": "Ziel-SoC (%)",
        "market_price_cent": "Preis (Cent/kWh)",
        "forecast_pv_kw": "PV-Prognose (kW)",
        "forecast_consumption_kw": "Grundlast-Prognose (kW)",
        "battery_plan_kw": "Batterieplan (kW)",
        "flex_summary": "Flexible Verbraucher (Soll)",
        "source": "Quelle",
    })
    columns = [
        "Zeitpunkt", "SoC (%)", "Modus", "Ziel-Leistung (kW)", "Ziel-SoC (%)",
        "Batterieplan (kW)", "PV-Prognose (kW)", "Grundlast-Prognose (kW)",
        "Preis (Cent/kWh)", "Flexible Verbraucher (Soll)", "Quelle",
    ]
    return display[[col for col in columns if col in display.columns]]


def _render_history_soc_chart(df: pd.DataFrame) -> None:
    if df.empty or len(df) < 2:
        return
    plot_df = df.sort_values("completed_at")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plot_df["completed_at"],
        y=plot_df["soc_percent"],
        mode="lines+markers",
        name="SoC (%)",
        line=dict(color="royalblue"),
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=10, r=10, t=30, b=10),
        title="SoC zum Optimierungszeitpunkt",
        yaxis_title="SoC (%)",
        xaxis_title="",
    )
    st.plotly_chart(fig, width="stretch", key="optimization_history_soc")


def render_optimization_history_panel() -> None:
    """Zeigt vergangene Produktiv-Optimierungen aus main.py."""
    st.markdown("#### 📜 Vergangene Optimierungen (Produktiv)")
    options = _history_days_options()
    labels = list(options.keys())
    choice = st.selectbox("Zeitraum", labels, index=labels.index("Letzte 7 Tage"), key="opt_history_days")
    history_df = optimization_history.load_optimization_history(days_back=options[choice])

    jsonl_path = optimization_history.history_file_path()
    legacy_path = optimization_history.LEGACY_CSV_FILE
    st.caption(
        f"Quellen: `{jsonl_path}` · Legacy `{legacy_path}` "
        f"· {len(history_df)} Durchläufe im gewählten Zeitraum"
    )

    if history_df.empty:
        st.info(
            "Noch keine Produktiv-Historie vorhanden. Nach dem nächsten **main.py**-Durchlauf "
            f"erscheinen Einträge in `{jsonl_path}`. Ältere Läufe aus `{legacy_path}` "
            "werden ebenfalls angezeigt, sofern die Datei existiert."
        )
        return

    _render_history_soc_chart(history_df)
    st.dataframe(_format_history_table(history_df), width="stretch", hide_index=True)

    with st.expander("Details zu einem Durchlauf"):
        detail_labels = [
            pd.Timestamp(ts).strftime("%d.%m.%Y %H:%M")
            for ts in history_df["completed_at"]
        ]
        selected_idx = st.selectbox(
            "Durchlauf",
            range(len(detail_labels)),
            format_func=lambda i: detail_labels[i],
            key="opt_history_detail",
        )
        row = history_df.iloc[selected_idx]
        completed = pd.Timestamp(row["completed_at"]).to_pydatetime()
        raw = optimization_history.load_history_entry_at(completed)
        if raw:
            st.json(raw)
        else:
            st.write(row.to_dict())
