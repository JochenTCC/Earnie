# app.py
import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import importlib
import time
from datetime import date

# Bestehende Projektmodule importieren
import config
import loxone_client
import awattar_client
import profile_manager
import consumer_targets
import optimizer
import pv_tuner  # Adaptives PV-Tuning-Modul einbinden
import backtesting_log
import live_consumption
import run_state
from simulation_engine import HISTORICAL_REFERENCE_ID
from version import __version__

st.set_page_config(
    page_title="Ernie Energy Control Center",
    page_icon="🔋",
    layout="wide"
)

UI_MODE_KEYS = ("live", "historical", "backtesting")
UI_MODE_LABELS = {
    "live": "Echtzeit",
    "historical": "Historischer Tag",
    "backtesting": "Backtesting",
}


def get_enabled_ui_modes() -> list[str]:
    """
    Aktivierte UI-Modi aus ENERGY_OPTIMIZER_UI_MODES (kommagetrennt: live,historical,backtesting).
    Ohne Variable: alle Modi (Entwicklung).
    """
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if not raw:
        return [UI_MODE_LABELS[k] for k in UI_MODE_KEYS]
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    enabled = [UI_MODE_LABELS[k] for k in UI_MODE_KEYS if k in requested]
    return enabled or [UI_MODE_LABELS["live"]]


def _reload_runtime_config() -> None:
    """config.json vor UI-Aktualisierung neu laden (Änderungen aus main.py / Editor)."""
    config.reload_config()


def _mode_label(mode: int) -> str:
    return {0: "Normal", 1: "Zwangs-Laden", 2: "Halten"}.get(int(mode), str(mode))


def render_main_run_sync_panel() -> dict | None:
    """Zeigt den letzten erfolgreichen Produktiv-Durchlauf von main.py."""
    state = run_state.load_run_state()
    if not state or not state.get("success"):
        st.info(
            "Noch kein Produktiv-Durchlauf von **main.py** gespeichert "
            f"(`{run_state.RUN_STATE_FILE}`)."
        )
        return None

    completed = state.get("completed_at", "")
    age = run_state.age_seconds(state)
    age_txt = f"{int(age)} s" if age is not None and age < 120 else (
        f"{int(age // 60)} min" if age is not None else "?"
    )

    st.markdown("#### 🛰️ Produktiv-Durchlauf (main.py)")
    st.caption(
        f"Letzter Lauf: **{completed}** · vor **{age_txt}** · "
        "Daten read-only aus `optimizer_run_state.json`"
    )

    cols = st.columns(5)
    cols[0].metric("SoC", f"{state.get('soc_percent', 0):.1f} %")
    cols[1].metric("Modus", _mode_label(state.get("mode", 0)))
    cols[2].metric("Ziel-Leistung", f"{state.get('target_power_kw', 0):.2f} kW")
    cols[3].metric("Ziel-SoC", f"{state.get('target_soc_percent', 0):.0f} %")
    cols[4].metric("PV (letzte h)", f"{state.get('pv_delta_kwh', 0):.3f} kWh")

    flex_live = state.get("flex_live_kw") or {}
    flex_opt = state.get("consumer_powers_kw") or {}
    if flex_live or flex_opt:
        flex_cols = st.columns(max(1, len(config.get_flexible_consumers())))
        for idx, consumer in enumerate(config.get_flexible_consumers()):
            cid = consumer["id"]
            live_kw = float(flex_live.get(cid, 0.0) or 0.0)
            opt_kw = float(flex_opt.get(cid, 0.0) or 0.0)
            flex_cols[idx].metric(
                consumer["name"],
                f"{live_kw:.2f} kW live",
                delta=f"Soll {opt_kw:.2f} kW",
            )

    return state


def update_config_file(settings_dict):
    """Aktualisiert alle übergebenen Parameter über die zentrale Laufzeit-Schnittstelle der config.py."""
    try:
        # 1. Werte in die JSON-Konfiguration schreiben
        config.update_runtime_settings(settings_dict)
        
        # 2. BEHOBEN: Modul im RAM neu laden, damit Streamlit die JSON-Änderungen sofort übernimmt
        importlib.reload(config)
        
        st.success("✅ Alle Parameter erfolgreich gespeichert und im System aktualisiert!")
    except Exception as e:
        st.error(f"🚨 Fehler beim Speichern der Konfiguration: {e}")

def get_runtime_settings() -> dict:
    return config.get_runtime_settings()

def _calculate_scaled_consumption_and_cost(optimized_rows: list) -> tuple[float, float, float]:
    """Berechnet den Gesamtverbrauch und die Kosten ohne PV, skaliert auf einen 24h-Horizont."""
    total_consumption_kwh = 0.0
    cost_without_pv_cents = 0.0
    
    for row in optimized_rows:
        consumption = row.get("Verbrauch-Prognose (kW)", 0.0)
        price_cent = row.get("Strompreis (Cent/kWh)", 0.0)
        total_consumption_kwh += consumption
        cost_without_pv_cents += consumption * price_cent
        
    cost_without_pv_euro = cost_without_pv_cents / 100.0
    num_hours = len(optimized_rows)
    scaling_factor = (24 / num_hours) if num_hours > 0 else 0.0
    
    consumption_24h = total_consumption_kwh * scaling_factor
    cost_without_pv_24h_euro = cost_without_pv_euro * scaling_factor
    
    return total_consumption_kwh, consumption_24h, cost_without_pv_24h_euro


def render_pv_config_inputs(settings: dict):
    st.markdown("#### ☀️ PV-Anlage")
    kwp = st.number_input("PV Leistung (kWp)", min_value=0.0, value=float(settings['PV_KWP']), step=0.1, format="%.2f")
    tilt = st.number_input("Dachneigung (°)", min_value=0, max_value=90, value=int(settings['PV_TILT']))
    azimuth = st.number_input(
        "Ausrichtung (Azimut °)",
        min_value=-180,
        max_value=180,
        value=int(settings['PV_AZIMUTH']),
        help="0=Süd, -90=Ost, 90=West"
    )
    k_push = st.number_input(
        "Einspeisevergütung (Cent/kWh)",
        min_value=0.0,
        value=float(settings['K_PUSH_CENT']),
        step=0.1,
        format="%.2f"
    )
    return kwp, tilt, azimuth, k_push


def render_battery_config_inputs(settings: dict):
    st.markdown("#### 🔋 Batterie-Speicher")
    bat_capacity = st.number_input(
        "Speicher-Kapazität (kWh)",
        min_value=0.1,
        value=float(settings['BATTERY_CAPACITY_KWH']),
        step=0.5,
        format="%.1f"
    )
    bat_min_soc = st.number_input(
        "Minimaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(settings['BATTERY_MIN_SOC']),
        step=1.0
    )
    bat_max_soc = st.number_input(
        "Maximaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(settings['BATTERY_MAX_SOC']),
        step=1.0
    )
    bat_max_power = st.number_input(
        "Max. Lade-/Entladeleistung (kW)",
        min_value=0.1,
        value=float(settings['BATTERY_MAX_POWER_KW']),
        step=0.1,
        format="%.2f"
    )
    return bat_capacity, bat_min_soc, bat_max_soc, bat_max_power


def render_config_form(settings: dict):
    with st.sidebar.form("config_form"):
        kwp, tilt, azimuth, k_push = render_pv_config_inputs(settings)
        bat_capacity, bat_min_soc, bat_max_soc, bat_max_power = render_battery_config_inputs(settings)

        submit_btn = st.form_submit_button("Alle Änderungen übernehmen")
        if submit_btn:
            update_config_file({
                "PV_KWP": kwp,
                "PV_TILT": tilt,
                "PV_AZIMUTH": azimuth,
                "K_PUSH_CENT": k_push,
                "BATTERY_CAPACITY_KWH": bat_capacity,
                "BATTERY_MIN_SOC": bat_min_soc,
                "BATTERY_MAX_SOC": bat_max_soc,
                "BATTERY_MAX_POWER_KW": bat_max_power
            })
            st.rerun()


def render_pv_tuning_sidebar():
    st.sidebar.markdown("---")
    st.sidebar.subheader("📈 Adaptives PV-Tuning")

    try:
        tuning_factor = pv_tuner.calculate_tuning_factor(days_back=14)
        deviation_pct = (tuning_factor - 1.0) * 100

        if tuning_factor == 1.0:
            delta_text = "Keine Abweichung (Basis)"
            delta_color = "off"
        elif tuning_factor > 1.0:
            delta_text = f"+{deviation_pct:.1f}% Mehrertrag vs. Prognose"
            delta_color = "normal"
        else:
            delta_text = f"{deviation_pct:.1f}% Minderertrag vs. Prognose"
            delta_color = "inverse"

        st.sidebar.metric(
            label="Aktueller Korrekturfaktor",
            value=f"{tuning_factor:.2f}",
            delta=delta_text,
            delta_color=delta_color
        )
    except Exception as e:
        st.sidebar.warning(f"⚠️ Tuning-Faktor konnte nicht berechnet werden: {e}")

    st.sidebar.caption(
        "Errechnet aus dem automatischen Abgleich zwischen Forecast.Solar "
        "und deine realen Loxone-Zählerständen der vergangenen 2 Wochen."
    )


def render_parameter_input(mode: str):
    if mode == "Backtesting":
        return
    st.sidebar.header("⚙️ System-Parameter")
    st.sidebar.markdown("Änderungen werden direkt über das Konfigurationsmodul angewendet.")

    render_config_form(get_runtime_settings())
    if mode == "Echtzeit":
        render_pv_tuning_sidebar()


def render_mode_selector() -> str:
    enabled_modes = get_enabled_ui_modes()
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if raw and not any(
        part.strip().lower() in UI_MODE_LABELS
        for part in raw.split(",")
        if part.strip()
    ):
        st.sidebar.warning(
            "Ungültige ENERGY_OPTIMIZER_UI_MODES – verwende nur Echtzeit."
        )

    if len(enabled_modes) == 1:
        mode = enabled_modes[0]
        st.session_state.app_mode = mode
        return mode

    st.sidebar.header("🕒 Betriebsmodus")
    default_idx = 0
    previous = st.session_state.get("app_mode")
    if previous in enabled_modes:
        default_idx = enabled_modes.index(previous)

    help_parts = []
    if UI_MODE_LABELS["historical"] in enabled_modes:
        help_parts.append("Historisch: beliebiger Tag aus den letzten 12 Monaten.")
    if UI_MODE_LABELS["backtesting"] in enabled_modes:
        help_parts.append(
            "Backtesting: Ergebnisse aus run_backtesting.py (backtesting_log.json)."
        )

    mode = st.sidebar.radio(
        "Optimierung für:",
        enabled_modes,
        index=default_idx,
        help=" ".join(help_parts) if help_parts else None,
    )
    st.session_state.app_mode = mode
    return mode


def render_historical_inputs() -> tuple[date, float]:
    min_date, max_date = profile_manager.get_historical_date_picker_bounds(months_back=12)
    default_date = max_date
    settings = get_runtime_settings()
    soc_min = float(settings["BATTERY_MIN_SOC"])
    soc_max = float(settings["BATTERY_MAX_SOC"])

    selected_date = st.sidebar.date_input(
        "Simulations-Tag",
        value=default_date,
        min_value=min_date,
        max_value=max_date,
        help=f"Wählbar: {min_date.strftime('%d.%m.%Y')} bis {max_date.strftime('%d.%m.%Y')}",
    )
    initial_soc = st.sidebar.slider(
        "Start-SoC für die Simulation (%)",
        min_value=soc_min,
        max_value=soc_max,
        value=soc_min,
        step=1.0,
        help=f"Erlaubter Bereich laut config.json: {soc_min:.0f}–{soc_max:.0f} %",
    )
    return selected_date, initial_soc


@st.cache_data(ttl=60, show_spinner="Lade Backtesting-Log...")
def load_backtesting_data():
    return backtesting_log.load_backtesting_log()


def render_backtesting_sidebar(meta: dict, hourly: pd.DataFrame) -> tuple[str, str | None]:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Backtesting-Log")
    created = meta.get("created_at", "")[:19].replace("T", " ")
    st.sidebar.caption(f"Erstellt: {created} UTC")
    period = meta.get("period", {})
    st.sidebar.caption(
        f"Zeitraum: {period.get('start', '?')} – {period.get('end', '?')} "
        f"({period.get('windows', '?')} Fenster)"
    )

    labels = meta.get("labels", {})
    scenario_ids = meta.get("scenario_ids", hourly["scenario_id"].unique().tolist())
    scenario_labels = [labels.get(sid, sid) for sid in scenario_ids]
    selected_label = st.sidebar.selectbox(
        "Szenario (Detailansicht)",
        scenario_labels,
        index=0,
    )
    selected_id = scenario_ids[scenario_labels.index(selected_label)]

    months = sorted(hourly["ts"].dt.to_period("M").astype(str).unique())
    month_filter = st.sidebar.selectbox(
        "Monat (Detailansicht)",
        ["Gesamter Zeitraum"] + months,
    )
    month_key = None if month_filter == "Gesamter Zeitraum" else month_filter
    return selected_id, month_key


def render_backtesting_summary(meta: dict):
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


def render_backtesting_monthly_table(meta: dict):
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


def render_backtesting_plausibility(meta: dict, scenario_id: str):
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


def render_backtesting_hourly_chart(hourly: pd.DataFrame, scenario_id: str, month_key: str | None):
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


def render_backtesting_block():
    if not backtesting_log.log_exists():
        st.warning(
            "Kein Backtesting-Log gefunden. Bitte zuerst "
            "`python run_backtesting.py` ausführen "
            "(erzeugt `backtesting_log.json` und `backtesting_hourly.csv`)."
        )
        return

    try:
        meta, hourly = load_backtesting_data()
    except Exception as e:
        st.error(f"Backtesting-Log konnte nicht geladen werden: {e}")
        return

    selected_id, month_key = render_backtesting_sidebar(meta, hourly)
    render_backtesting_summary(meta)
    render_backtesting_monthly_table(meta)

    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    if selected_id != ref_id:
        render_backtesting_plausibility(meta, selected_id)

    render_backtesting_hourly_chart(hourly, selected_id, month_key)


@st.cache_data(ttl=3600, show_spinner="Lade historische Tagesdaten...")
def load_historical_matrix(target_date: date):
    return profile_manager.build_historical_optimization_matrix(target_date)


def get_bar_colors(df):
    return [
        "forestgreen" if "Zwangsladen" in cmd else
        "crimson" if "Entladesperre" in cmd or "Entladen" in cmd else
        "dodgerblue"
        for cmd in df["Steuerbefehl"]
    ]


def add_power_traces(fig, df, bar_colors):
    if "PV-Prognose (kW)" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["Uhrzeit"],
            y=df["PV-Prognose (kW)"],
            name="PV-Ertrag Prognose (kW)",
            line=dict(color='#f1c40f', width=2),
            fill='tozeroy',
            fillcolor='rgba(241, 196, 15, 0.15)',
            yaxis="y"
        ))

    if "Verbrauch-Prognose (kW)" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["Uhrzeit"],
            y=df["Verbrauch-Prognose (kW)"],
            name="Historischer Verbrauch (kW)",
            line=dict(color='#3498db', width=2, dash='dash'),
            yaxis="y"
        ))

    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = f"{consumer['name']} (kW)"
        if col in df.columns and df[col].sum() > 0:
            fig.add_trace(go.Bar(
                x=df["Uhrzeit"],
                y=df[col],
                name=col,
                opacity=0.65,
                offsetgroup=consumer["id"],
                yaxis="y"
            ))

    fig.add_trace(go.Bar(
        x=df["Uhrzeit"],
        y=df["Geplante Batterie-Aktion (kW)"],
        name="Batterie-Aktion (kW)",
        marker=dict(color=bar_colors),
        opacity=0.75,
        offset=0.05,
        width=0.9,
        offsetgroup="bars",
        yaxis="y"
    ))


def add_price_soc_traces(fig, df):
    fig.add_trace(go.Scatter(
        x=df["Uhrzeit"],
        y=df["Strompreis (Cent/kWh)"],
        name="Brutto-Strompreis (Cent)",
        mode="lines",
        line=dict(color="red", width=3, shape="hv"),
        yaxis="y2"
    ))

    fig.add_trace(go.Scatter(
        x=df["Uhrzeit"],
        y=df["Simulierter SoC (%)"],
        name="Simulierter Speicher-SoC (%)",
        mode="lines",
        line=dict(color="gold", width=2.5, dash="dash"),
        yaxis="y2"
    ))


def render_optimization_chart(df, baseline_df=None):
    """Zeichnet Leistungen (PV, Verbrauch, Batterie) und Preise/SoC über zwei Y-Achsen."""
    bar_colors = get_bar_colors(df)
    fig = go.Figure()

    add_power_traces(fig, df, bar_colors)
    if baseline_df is not None and not baseline_df.empty:
        fig.add_trace(go.Scatter(
            x=baseline_df["Uhrzeit"],
            y=baseline_df["Simulierter SoC (%)"],
            name="Baseline SoC (%)",
            mode="lines",
            line=dict(color="darkgrey", width=2.5, dash="dash"),
            yaxis="y2"
        ))

    add_price_soc_traces(fig, df)

    fig.update_layout(
        title="Synchronisierter 24-Stunden-Zeithorizont (Leistung vs. Preis & SoC)",
        xaxis=dict(title="Uhrzeit (Stunden-Slots / Intervalle)", type="category"),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(title="Preis (Cent/kWh) / SoC (%)", side="right", overlaying="y", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=80, b=40)
    )

    st.plotly_chart(fig, width='stretch')


def render_applied_targets(savings: dict):
    """Zeigt Baseline- und Optimierungsenergie je Verbraucher in einer Tabelle."""
    comparison = savings.get("energy_comparison") or []
    if not comparison:
        return

    st.markdown("**⚡ Energievergleich Baseline vs. Optimierung (24h)**")
    st.caption(
        "Optimierung: je Verbraucher ein 24h-Ziel über das gesamte Simulationsfenster "
        "(auch bei Kalendertagwechsel nur einmal gezählt)."
    )

    def _format_optimization_cell(kwh: float, source: str) -> str:
        if source:
            return f"{kwh:.1f} kWh ({source})"
        return f"{kwh:.1f} kWh"

    st.dataframe(
        pd.DataFrame([
            {
                "Verbraucher": row["name"],
                "Baseline (kWh)": row["baseline_kwh"],
                "Optimierung": _format_optimization_cell(
                    row["optimization_kwh"],
                    row.get("optimization_source", ""),
                ),
            }
            for row in comparison
        ]),
        width="stretch",
        hide_index=True,
    )


def render_savings_metrics(savings: dict):
    """Rendert die finanzielle Metriken-Übersicht im Dashboard auf einheitlicher Zeitbasis."""
    st.subheader("💶 Optimierungs-Einsparungen")
    baseline_cost = savings.get('baseline_cost_euro', 0.0)
    optimized_cost = savings.get('optimized_cost_euro', 0.0)
    baseline_kwh = savings.get('baseline_consumption_kwh', 0.0)
    optimized_kwh = savings.get('optimized_consumption_kwh', 0.0)

    optimized_rows = savings.get('optimized_rows', [])
    _, _, cost_without_pv_24h_euro = _calculate_scaled_consumption_and_cost(optimized_rows)

    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    col1.metric(
        "Ohne PV (24h hochger.)",
        f"{cost_without_pv_24h_euro:.2f} €",
        help="Hochgerechnete Kosten bei 100 % Netzbezug ohne PV-Anlage auf einen vollen 24h-Horizont.",
    )
    col2.metric("Baseline-Kosten", f"{baseline_cost:.2f} €")
    col3.metric(
        "Baseline-Verbrauch",
        f"{baseline_kwh:.1f} kWh",
        help="Summe des stündlichen Gesamtverbrauchs in der Baseline (ohne Lastverschiebung).",
    )
    col4.metric("Optimierte Kosten", f"{optimized_cost:.2f} €")
    col5.metric(
        "Optimierter Verbrauch",
        f"{optimized_kwh:.1f} kWh",
        help="Summe Grundlast + Flex über alle Stunden im 24h-Fenster (je Zeile 1 h).",
    )

    display_savings = optimized_cost - baseline_cost
    col6.metric(
        "Ersparnis",
        f"{display_savings:.2f} €",
        delta=f"{display_savings:.2f} €",
        delta_color="normal" if display_savings <= 0 else "inverse",
    )
    col7.metric(
        "Δ Verbrauch",
        f"{optimized_kwh - baseline_kwh:+.1f} kWh",
        help="Differenz optimierter minus Baseline-Verbrauch.",
    )

    render_applied_targets(savings)


def fetch_market_data():
    market_data = awattar_client.fetch_awattar_prices()
    if not market_data:
        st.error("🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. Abbruch der Simulation.")
        return None
    return market_data


def render_simulation_details(df, title: str = "📋 Simulations-Details (Nächste 24 Stunden)"):
    st.subheader(title)
    st.markdown("Hier sind die exakten mathematischen Stundenslots aufgelistet, die als Grundlage für den Chart dienen:")
    st.dataframe(df, width='stretch')


def render_historical_day_info(meta: dict):
    totals = meta['historical_totals']
    target_date = meta['target_date']
    date_label = target_date.strftime('%d.%m.%Y') if hasattr(target_date, 'strftime') else str(target_date)

    st.subheader(f"📅 Historische Tagesdaten: {date_label}")
    cols = st.columns(3 + len(totals))
    cols[0].metric("Gesamtverbrauch (real)", f"{meta.get('total_kwh', meta['baseload_kwh']):.1f} kWh")
    cols[1].metric("Grundlast", f"{meta['baseload_kwh']:.1f} kWh")
    cols[2].metric("PV-Ertrag (real)", f"{meta['pv_kwh']:.1f} kWh")
    for idx, consumer in enumerate(config.get_flexible_consumers(), start=3):
        kwh = totals.get(consumer['id'], 0.0)
        cols[idx].metric(f"{consumer['name']} (real)", f"{kwh:.1f} kWh")
    st.caption(
        "Baseline-Kosten nutzen den geloggten Gesamtverbrauch. "
        "Die Optimierung plant Grundlast plus steuerbare Verbraucher zu den **geloggten** Tageszielen "
        "(unabhängig von daily_target_source in config.json)."
    )


def render_historical_optimization_block(selected_date: date, initial_soc: float):
    try:
        matrix, meta = load_historical_matrix(selected_date)
    except Exception as e:
        st.error(f"🚨 Historische Daten konnten nicht geladen werden: {e}")
        return

    if not matrix or sum(row.get('expected_p_act', 0) for row in matrix) == 0:
        st.warning(
            f"⚠️ Für den {selected_date.strftime('%d.%m.%Y')} wurden keine Daten in "
            "cons_data_hourly.csv gefunden."
        )
        return

    render_historical_day_info(meta)

    with st.spinner("Berechne Optimierung für den historischen Tag..."):
        savings_info = optimizer.calculate_optimization_savings(
            matrix,
            initial_soc,
            consumer_daily_targets_kwh=meta.get("consumer_daily_targets_kwh"),
        )

    optimized_df = pd.DataFrame(savings_info['optimized_rows'])
    baseline_df = pd.DataFrame(savings_info['baseline_rows'])

    planned_lines = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = f"{consumer['name']} (kW)"
        if col in optimized_df.columns:
            planned = optimized_df[col].sum()
            if planned > 0:
                planned_lines.append(f"**{consumer['name']}**: {planned:.1f} kWh")
    if planned_lines:
        st.info("🏭 Geplante flexible Verbraucher: " + " | ".join(planned_lines))

    render_savings_metrics(savings_info)
    render_optimization_chart(optimized_df, baseline_df)
    render_simulation_details(
        optimized_df,
        title=f"📋 Simulations-Details ({selected_date.strftime('%d.%m.%Y')})",
    )


def setup_auto_refresh():
    """Initialisiert den automatischen Refresh-Mechanismus basierend auf LOOP_TIMEOUT."""
    loop_timeout = config.get('LOOP_TIMEOUT', default=900, cast=int)
    
    # Initialisiere den Refresh-Timer in session_state, falls noch nicht vorhanden
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()
    
    # Überprüfe, ob genug Zeit seit dem letzten Refresh vergangen ist
    time_since_refresh = time.time() - st.session_state.last_refresh
    
    if time_since_refresh >= loop_timeout:
        # Zeit für einen Refresh
        st.session_state.last_refresh = time.time()
        st.rerun()

@st.fragment(run_every=config.get('LOOP_TIMEOUT', default=900, cast=int))
def render_optimization_block(current_soc: float):
    """What-if-Simulation; aktuelle Stunde optional aus main.py oder Live-Loxone."""
    _reload_runtime_config()
    main_state = run_state.load_run_state()

    market_data = fetch_market_data()
    if market_data is None:
        return

    _, _, matrix = profile_manager.get_forecast_vectors(market_data)

    snapshot = None
    if main_state and main_state.get("consumption_snapshot"):
        age = run_state.age_seconds(main_state)
        if age is not None and age <= config.get("LOOP_TIMEOUT", default=900, cast=int) * 1.5:
            snapshot = main_state["consumption_snapshot"]

    if snapshot is None:
        snapshot = live_consumption.fetch_live_consumption_snapshot()

    if snapshot:
        matrix = live_consumption.apply_live_snapshot_to_matrix(matrix, snapshot, hour_index=0)

    sim_soc = float(main_state.get("soc_percent", current_soc)) if main_state else current_soc
    targets = consumer_targets.resolve_consumer_daily_targets(matrix=matrix)
    savings_info = optimizer.calculate_optimization_savings(
        matrix,
        sim_soc,
        consumer_daily_targets_kwh=targets,
    )
    
    optimized_df = pd.DataFrame(savings_info['optimized_rows'])
    baseline_df = pd.DataFrame(savings_info['baseline_rows'])

    if main_state:
        st.caption(
            f"📡 **Aktuelle Stunde:** Verbrauch aus "
            f"{'main.py' if main_state.get('consumption_snapshot') and snapshot == main_state.get('consumption_snapshot') else 'Loxone live'} · "
            f"SoC für Simulation: **{sim_soc:.1f} %** (main.py) — übrige Stunden aus Profil."
        )
    elif snapshot:
        st.caption(
            f"📡 **Aktuelle Stunde (Live):** Grundlast {snapshot['baseload_kw']:.2f} kW · "
            f"Gesamt {snapshot['house_kw']:.2f} kW · PV {snapshot['pv_kw']:.2f} kW — "
            "Rest des Horizonts aus Profil-Prognose."
        )

    render_savings_metrics(savings_info)
    render_optimization_chart(optimized_df, baseline_df)
    render_simulation_details(optimized_df)


@st.fragment(run_every=10)
def render_countdown_block():
    """Countdown synchron zum letzten main.py-Durchlauf (Fallback: App-Session)."""
    _reload_runtime_config()
    loop_timeout = config.get('LOOP_TIMEOUT', default=900, cast=int)

    main_state = run_state.load_run_state()
    main_epoch = run_state.completed_at_epoch(main_state)
    if main_epoch is not None:
        last_optimization = main_epoch
        sync_label = "main.py"
    elif 'last_optimization' in st.session_state:
        last_optimization = st.session_state.last_optimization
        sync_label = "App"
    else:
        last_optimization = time.time()
        sync_label = "App"

    elapsed = time.time() - last_optimization
    remaining = max(0, int(loop_timeout - elapsed))
    last_time = time.strftime("%H:%M:%S", time.localtime(last_optimization))

    st.markdown("---")
    st.caption(
        f"🔄 **Optimierungs-Takt:** Alle {int(loop_timeout/60)} Min ({loop_timeout}s) | "
        f"⏱️ Letzter Lauf ({sync_label}): **{last_time}**"
    )
    st.caption(f"⏳ **Nächster Takt in:** `{remaining}` s (aktualisiert alle 10s)")

#### LEISTUNGSFLUSS DARSTELLUNG

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
        for idx, consumer in enumerate(consumers):
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

    # Legacy: ein aggregierter Hausknoten
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


def _render_live_consumption_metrics(snapshot: dict) -> None:
    """Kacheln: Grundlast + flexible Verbraucher (nur Anzeige)."""
    consumers = config.get_flexible_consumers()
    cols = st.columns(1 + len(consumers))
    cols[0].metric("Grundlast (live)", f"{snapshot['baseload_kw']:.2f} kW")
    for idx, consumer in enumerate(consumers, start=1):
        kw = float((snapshot.get("flex_kw") or {}).get(consumer["id"], 0.0) or 0.0)
        cols[idx].metric(consumer["name"], f"{kw:.2f} kW")


@st.fragment(run_every=10)
def render_live_power_flow(current_soc: float):
    """Rendert die Live-Leistungsfluss-Ansicht mit CSS-Fix gegen den Text-Glow."""
    _reload_runtime_config()
    st.write("### ⚡ Echtzeit-Leistungsfluss (Live)")
    
    # CSS-Injektion: Entfernt restlos den hardcodierten Plotly-Textschatten
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
        unsafe_allow_html=True
    )
    
    data = loxone_client.fetch_loxone_live_power()
    if data is None:
        st.warning("⚠️ Live-Leistungswerte konnten nicht von Loxone geladen werden.")
        return

    main_state = run_state.load_run_state()
    use_main_snapshot = False
    if main_state and main_state.get("consumption_snapshot"):
        age = run_state.age_seconds(main_state)
        if age is not None and age <= 120:
            snapshot = main_state["consumption_snapshot"]
            use_main_snapshot = True
        else:
            flex_kw = loxone_client.fetch_flexible_consumers_live_kw()
            snapshot = live_consumption.build_consumption_snapshot(data, flex_kw)
    else:
        flex_kw = loxone_client.fetch_flexible_consumers_live_kw()
        snapshot = live_consumption.build_consumption_snapshot(data, flex_kw)

    _render_live_consumption_metrics(snapshot)
    src = "main.py" if use_main_snapshot else "Loxone live"
    st.caption(
        f"Gesamtverbrauch: **{snapshot['house_kw']:.2f} kW** "
        f"(Grundlast + flexible Verbraucher · Quelle: {src})"
    )

    fig = _create_live_flow_sankey(
        data,
        current_soc=current_soc,
        breakdown=snapshot,
    )
    # BEHOBEN: API-Migration von use_container_width=True auf width='stretch'
    st.plotly_chart(fig, width='stretch', key="live_power_flow_sankey")

################################    

def main():
    st.title("🔋 Ernie Energy Control Center")
    st.caption(f"Version {__version__}")
    mode = render_mode_selector()

    if mode == "Historischer Tag":
        st.markdown(
            "Historische **24-Stunden-Optimierung** mit Daten aus **cons_data_hourly.csv** "
            "(Grundlast, PV) und historischen Marktpreisen."
        )
    elif mode == "Backtesting":
        st.markdown(
            "Auswertung des **Backtesting-Logs** aus `run_backtesting.py` "
            "(Referenz ohne Optimierung vs. optimierte Szenarien)."
        )
    else:
        _reload_runtime_config()
        st.markdown("Echtzeit-Cockpit und Vorhersage-Simulation des synchronisierten 24-Stunden-Horizonts.")

    render_parameter_input(mode)

    if mode == "Backtesting":
        render_backtesting_block()
        return

    if mode == "Historischer Tag":
        selected_date, initial_soc = render_historical_inputs()
        render_historical_optimization_block(selected_date, initial_soc)
        return

    current_soc = loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
    render_main_run_sync_panel()
    st.markdown("#### 🔮 What-if-Simulation (24h)")
    st.caption(
        "Unabhängige MILP-Simulation in der App; Produktiv-Steuerung läuft in **main.py**."
    )
    render_live_power_flow(current_soc)
    render_optimization_block(current_soc)
    render_countdown_block()


if __name__ == "__main__":
    main()