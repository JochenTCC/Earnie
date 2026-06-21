# app.py
import logging
import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import importlib
import time
from datetime import date, datetime, timedelta

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
import live_optimization_debug
import optimization_schedule
import run_state
from simulation_engine import HISTORICAL_REFERENCE_ID
from version import __version__

logger = logging.getLogger("app")

st.set_page_config(
    page_title="Ernie Energy Control Center",
    page_icon="🔋",
    layout="wide"
)


def _inject_compact_numeric_css() -> None:
    """Kleinere Schrift für Metrik-Zahlen und Tabellen."""
    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] {
            font-size: 0.95rem;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.7rem;
        }
        div[data-testid="stDataFrame"] div[data-testid="stTable"] {
            font-size: 0.8rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
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
    return {
        0: "Normal",
        1: "Zwangs-Laden",
        2: "Halten",
        3: "Zwangs-Entladen",
    }.get(int(mode), str(mode))


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
        f"Daten read-only aus `{run_state.RUN_STATE_FILE}`"
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


def _extended_line_xy(slot_x: pd.Series, y: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Verlängert Linien um 1 h (letzter Wert wiederholt) für die -0.5-Verschiebung."""
    if y.empty:
        return _chart_line_x(slot_x), y
    tail_slot = float(slot_x.iloc[-1]) + 1.0
    extended_slot = pd.concat(
        [slot_x, pd.Series([tail_slot])],
        ignore_index=True,
    )
    extended_y = pd.concat([y, pd.Series([y.iloc[-1]])], ignore_index=True)
    return _chart_line_x(extended_slot), extended_y


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


def add_power_traces(fig, df, bar_colors, slot_x: pd.Series):
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
            line=dict(color='#f1c40f', width=2),
            fill='tozeroy',
            fillcolor='rgba(241, 196, 15, 0.15)',
            yaxis="y",
            **_line_hover(uhrzeit, ".2f"),
        ))

    if "Verbrauch-Prognose (kW)" in df.columns:
        load_x, load_y = _extended_line_xy(slot_x, df["Verbrauch-Prognose (kW)"])
        fig.add_trace(go.Scatter(
            x=load_x,
            y=load_y,
            name="Verbrauch",
            line=dict(color='#3498db', width=2, dash='dash'),
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


def add_price_soc_traces(fig, df, slot_x: pd.Series):
    uhrzeit = df["Uhrzeit"]
    price_x, price_y = _extended_line_xy(slot_x, df["Strompreis (Cent/kWh)"])
    fig.add_trace(go.Scatter(
        x=price_x,
        y=price_y,
        name="Preis",
        mode="lines",
        line=dict(color="red", width=3, shape="hv"),
        yaxis="y2",
        **_line_hover(uhrzeit, ".2f"),
    ))

    soc_x, soc_y = _extended_line_xy(slot_x, df["Simulierter SoC (%)"])
    fig.add_trace(go.Scatter(
        x=soc_x,
        y=soc_y,
        name="SoC",
        mode="lines",
        line=dict(color="gold", width=2.5, dash="dash"),
        yaxis="y2",
        **_line_hover(uhrzeit, ".1f"),
    ))


def render_optimization_chart(df, baseline_df=None):
    """Zeichnet Leistungen (PV, Verbrauch, Batterie) und Preise/SoC über zwei Y-Achsen."""
    bar_colors = get_bar_colors(df)
    slot_x = _chart_slot_x(len(df))
    fig = go.Figure()

    add_power_traces(fig, df, bar_colors, slot_x)
    if baseline_df is not None and not baseline_df.empty:
        baseline_slot_x = _chart_slot_x(len(baseline_df))
        baseline_x, baseline_y = _extended_line_xy(
            baseline_slot_x,
            baseline_df["Simulierter SoC (%)"],
        )
        fig.add_trace(go.Scatter(
            x=baseline_x,
            y=baseline_y,
            name="SoC BL",
            mode="lines",
            line=dict(color="darkgrey", width=2.5, dash="dash"),
            yaxis="y2",
            **_line_hover(baseline_df["Uhrzeit"], ".1f"),
        ))

    add_price_soc_traces(fig, df, slot_x)

    fig.update_layout(
        title="Synchronisierter 24-Stunden-Zeithorizont (Leistung vs. Preis & SoC)",
        xaxis=_chart_xaxis_config(df["Uhrzeit"]),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(title="Preis (Cent/kWh) / SoC (%)", side="right", overlaying="y", showgrid=False),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            x=0.5,
            xanchor="center",
            font=dict(size=10),
        ),
        margin=dict(l=40, r=40, t=50, b=110),
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


def _normalized_savings_euro(
    baseline_cost: float,
    optimized_cost: float,
    baseline_kwh: float,
    optimized_kwh: float,
) -> float | None:
    """
    Ersparnis auf gleichen Verbrauch normiert (Dreisatz auf Baseline-kWh).
    Bei Δ Verbrauch = 0 entspricht das der unbereinigten Ersparnis.
    """
    if abs(optimized_kwh - baseline_kwh) < 1e-6:
        return optimized_cost - baseline_cost
    if optimized_kwh <= 0:
        return None
    normalized_optimized_cost = optimized_cost * (baseline_kwh / optimized_kwh)
    return normalized_optimized_cost - baseline_cost


def render_savings_metrics(savings: dict):
    """Rendert die finanzielle Metriken-Übersicht im Dashboard auf einheitlicher Zeitbasis."""
    st.subheader("💶 Optimierungs-Einsparungen")
    baseline_cost = savings.get('baseline_cost_euro', 0.0)
    optimized_cost = savings.get('optimized_cost_euro', 0.0)
    baseline_kwh = savings.get('baseline_consumption_kwh', 0.0)
    optimized_kwh = savings.get('optimized_consumption_kwh', 0.0)

    optimized_rows = savings.get('optimized_rows', [])
    _, _, cost_without_pv_24h_euro = _calculate_scaled_consumption_and_cost(optimized_rows)

    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)
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
    normalized_savings = _normalized_savings_euro(
        baseline_cost, optimized_cost, baseline_kwh, optimized_kwh
    )
    col6.metric(
        "Ersparnis",
        f"{display_savings:.2f} €",
        delta=f"{display_savings:.2f} €",
        delta_color="inverse",
    )
    col7.metric(
        "Δ Verbrauch",
        f"{optimized_kwh - baseline_kwh:+.1f} kWh",
        help="Differenz optimierter minus Baseline-Verbrauch.",
    )
    if normalized_savings is None:
        col8.metric(
            "Norm. Ersparnis",
            "—",
            help="Nicht berechenbar (optimierter Verbrauch ist 0 kWh).",
        )
    else:
        col8.metric(
            "Norm. Ersparnis",
            f"{normalized_savings:.2f} €",
            help=(
                "Kostenvergleich bei gleichem Verbrauch (Baseline-kWh): "
                "optimierte Kosten per Dreisatz auf Baseline-Verbrauch hoch-/runtergerechnet. "
                "Bei Δ Verbrauch = 0 identisch mit „Ersparnis“."
            ),
        )


def fetch_market_data():
    market_data = awattar_client.fetch_awattar_prices()
    if not market_data:
        st.error("🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. Abbruch der Simulation.")
        return None
    return market_data


def _quarter_hour_slot_key() -> str:
    return optimization_schedule.quarter_hour_slot_key()


def _apply_main_run_to_live_df(
    optimized_df: pd.DataFrame,
    main_state: dict | None,
) -> pd.DataFrame:
    """Stunde 0 aus main.py übernehmen, wenn der Produktiv-Durchlauf zum Slot passt."""
    if optimized_df is None or optimized_df.empty or not main_state:
        return optimized_df
    if not optimization_schedule.completed_at_in_current_slot(main_state.get("completed_at")):
        return optimized_df
    rows = optimizer.overlay_main_run_on_rows(optimized_df.to_dict("records"), main_state)
    return pd.DataFrame(rows)


def _render_live_optimization_results(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    *,
    simulation_table_title: str | None = "📋 Simulations-Details (Nächste 24 Stunden)",
) -> None:
    render_savings_metrics(savings_info)
    render_optimization_chart(optimized_df, baseline_df)
    render_applied_targets(savings_info)
    if simulation_table_title:
        render_simulation_details(optimized_df, title=simulation_table_title)


def _live_optimization_cache_key(current_slot: str, main_state: dict | None) -> str:
    completed = (main_state or {}).get("completed_at", "")
    return f"{current_slot}|{completed}"


def _render_pending_live_sync(wait_sec: int, reason: str) -> bool:
    """Zeigt vorherige Simulation, solange auf main.py gewartet wird."""
    cached_df = st.session_state.get("live_optimization_df")
    cached_savings = st.session_state.get("live_savings_info")
    if cached_df is None or cached_savings is None or cached_df.empty:
        return False

    baseline_df = pd.DataFrame(cached_savings.get("baseline_rows", []))
    _render_live_optimization_results(cached_savings, cached_df, baseline_df)
    if reason == "delay":
        st.caption(
            f"⏳ **Synchronisation mit main.py:** Aktualisierung in ca. **{wait_sec} s** "
            f"(1 Min nach Viertelstunden-Wechsel)."
        )
    else:
        st.caption(
            f"⏳ **Warte auf main.py-Durchlauf** für den aktuellen Slot "
            f"(noch ca. **{wait_sec} s**)."
        )
    return True


def _persist_simulation_debug(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    *,
    kind: str,
    initial_soc: float,
    main_state: dict | None = None,
    quarter_hour_slot: str | None = None,
    sync_reason: str | None = None,
    optimized_df_raw: pd.DataFrame | None = None,
    target_date: str | None = None,
    historical_meta: dict | None = None,
) -> None:
    """Schreibt Simulationsergebnis als JSON in runtime/ (Debug / Nachrechnen)."""
    try:
        payload = live_optimization_debug.build_debug_payload(
            savings_info,
            optimized_df.to_dict("records"),
            baseline_df.to_dict("records"),
            kind=kind,
            initial_soc=initial_soc,
            main_state=main_state,
            quarter_hour_slot=quarter_hour_slot,
            sync_reason=sync_reason,
            optimized_rows_raw=(
                optimized_df_raw.to_dict("records") if optimized_df_raw is not None else None
            ),
            target_date=target_date,
            historical_meta=historical_meta,
        )
        live_optimization_debug.save_debug_snapshot(payload, kind=kind)
    except OSError as exc:
        logger.warning("Debug-Snapshot konnte nicht gespeichert werden: %s", exc)


def render_plausibility_debug_panel(main_state: dict | None) -> None:
    """Zeigt Abgleich main.py vs. App-Simulation und Pfad zum Debug-Snapshot."""
    debug = live_optimization_debug.load_debug_snapshot(kind="live")
    if not debug or debug.get("simulation_kind") != "live":
        return

    path = live_optimization_debug.debug_file_path("live")
    plaus = debug.get("plausibility") or {}

    with st.expander("🔍 Plausibilität main.py ↔ App-Simulation"):
        st.caption(
            f"Debug-Snapshot: `{path}` · Slot **{debug.get('quarter_hour_slot', '?')}** · "
            f"Sync: **{debug.get('sync_reason', '?')}**"
        )
        if main_state and debug.get("main_run_completed_at") != main_state.get("completed_at"):
            st.warning(
                "Der gespeicherte Snapshot stammt von einem anderen main.py-Lauf als dem aktuellen Panel."
            )

        if plaus.get("available"):
            if plaus.get("aligned"):
                st.success("Stunde 0 (nach main.py-Overlay) stimmt mit dem Produktiv-Durchlauf überein.")
            else:
                st.error("Abweichungen in Stunde 0 (nach Overlay):")
                for issue in plaus.get("issues", []):
                    st.markdown(f"- {issue}")

        plaus_raw = debug.get("plausibility_before_overlay") or {}
        if plaus_raw.get("available") and not plaus_raw.get("aligned"):
            st.info(
                "Vor dem main.py-Overlay wich die reine App-Simulation in Stunde 0 ab — "
                "das ist erwartbar, wenn main.py die maßgeblichen Produktivwerte liefert."
            )
            with st.container():
                st.markdown("**Roh-Simulation Stunde 0 vs. main.py:**")
                for issue in plaus_raw.get("issues", []):
                    st.markdown(f"- {issue}")

        st.caption(
            "Die Datei enthält `main_run`, `simulation_rows_raw`, `simulation_rows` (24h) "
            "und `baseline_rows` zum gemeinsamen Nachrechnen."
        )


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
    render_applied_targets(savings_info)
    _persist_simulation_debug(
        savings_info,
        optimized_df,
        baseline_df,
        kind="historical_day",
        initial_soc=initial_soc,
        target_date=selected_date.isoformat(),
        historical_meta=meta,
    )
    render_simulation_details(
        optimized_df,
        title=f"📋 Simulations-Details ({selected_date.strftime('%d.%m.%Y')})",
    )


def setup_auto_refresh():
    """Seiten-Refresh beim Wechsel in den nächsten Viertelstunden-Slot."""
    current_slot = optimization_schedule.quarter_hour_slot_key()

    if "last_refresh_slot" not in st.session_state:
        st.session_state.last_refresh_slot = current_slot
        return

    if st.session_state.last_refresh_slot != current_slot:
        st.session_state.last_refresh_slot = current_slot
        st.rerun()


@st.fragment(run_every=timedelta(seconds=10))
def render_optimization_savings_and_chart(current_soc: float):
    """MILP-Simulation: Einsparungen und Chart (Refresh nach main.py-Sync)."""
    _reload_runtime_config()
    current_slot = optimization_schedule.quarter_hour_slot_key()
    main_state = run_state.load_run_state()
    cache_key = _live_optimization_cache_key(current_slot, main_state)
    cached_key = st.session_state.get("live_optimization_cache_key")

    if (
        cached_key == cache_key
        and st.session_state.get("live_optimization_df") is not None
        and st.session_state.get("live_savings_info") is not None
        and not st.session_state["live_optimization_df"].empty
    ):
        cached_savings = st.session_state["live_savings_info"]
        cached_df = _apply_main_run_to_live_df(
            st.session_state["live_optimization_df"], main_state
        )
        baseline_df = pd.DataFrame(cached_savings.get("baseline_rows", []))
        _render_live_optimization_results(cached_savings, cached_df, baseline_df)
        return

    ready, reason, wait_sec = optimization_schedule.live_simulation_readiness(
        (main_state or {}).get("completed_at"),
    )
    if not ready:
        if _render_pending_live_sync(wait_sec, reason):
            return
        st.info(
            f"⏳ Live-Simulation startet nach Synchronisation mit **main.py** "
            f"(noch ca. **{wait_sec} s**)."
        )
        return

    market_data = fetch_market_data()
    if market_data is None:
        return

    _, _, matrix = profile_manager.get_forecast_vectors(market_data)

    snapshot = None
    if main_state and main_state.get("consumption_snapshot"):
        age = run_state.age_seconds(main_state)
        if age is not None and age <= optimization_schedule.QUARTER_HOUR_SECONDS * 1.5:
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
    optimized_df_raw = optimized_df.copy()
    optimized_df = _apply_main_run_to_live_df(optimized_df, main_state)
    st.session_state["live_optimization_cache_key"] = cache_key
    st.session_state["live_optimization_df"] = optimized_df
    st.session_state["live_savings_info"] = savings_info

    _persist_simulation_debug(
        savings_info,
        optimized_df,
        baseline_df,
        kind="live",
        initial_soc=sim_soc,
        main_state=main_state,
        quarter_hour_slot=current_slot,
        sync_reason=reason,
        optimized_df_raw=optimized_df_raw,
    )

    sync_note = ""
    if reason == "main_synced":
        sync_note = " · synchron mit main.py"
    elif reason == "fallback":
        sync_note = " · main.py für diesen Slot nicht verfügbar (Live-Fallback)"

    if main_state:
        st.caption(
            f"📡 **Aktuelle Stunde:** Verbrauch aus "
            f"{'main.py' if main_state.get('consumption_snapshot') and snapshot == main_state.get('consumption_snapshot') else 'Loxone live'} · "
            f"SoC für Simulation: **{sim_soc:.1f} %** (main.py) · "
            f"Stunde 0 = Produktiv-Durchlauf main.py — übrige Stunden simuliert{sync_note}."
        )
    elif snapshot:
        st.caption(
            f"📡 **Aktuelle Stunde (Live):** Grundlast {snapshot['baseload_kw']:.2f} kW · "
            f"Gesamt {snapshot['house_kw']:.2f} kW · PV {snapshot['pv_kw']:.2f} kW — "
            f"Rest des Horizonts aus Profil-Prognose{sync_note}."
        )

    _render_live_optimization_results(savings_info, optimized_df, baseline_df)
    render_plausibility_debug_panel(main_state)


def render_cached_simulation_details():
    """Simulations-Tabelle aus dem letzten Optimierungs-Fragment-Lauf."""
    df = st.session_state.get("live_optimization_df")
    if df is not None and not df.empty:
        render_simulation_details(df)


@st.fragment(run_every=10)
def render_countdown_block():
    """Countdown bis zur nächsten Viertelstunde (synchron zu main.py)."""
    _reload_runtime_config()

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

    remaining = max(0, int(optimization_schedule.seconds_until_next_quarter_hour()))
    app_wait = max(0, int(optimization_schedule.seconds_until_app_refresh_ready()))
    next_run = optimization_schedule.next_quarter_hour_datetime()
    last_time = time.strftime("%H:%M:%S", time.localtime(last_optimization))

    st.markdown("---")
    st.caption(
        f"🔄 **Optimierungs-Takt:** Viertelstunden (:00 / :15 / :30 / :45) | "
        f"⏱️ Letzter Lauf ({sync_label}): **{last_time}**"
    )
    st.caption(
        f"⏳ **Nächster main.py-Takt:** `{next_run.strftime('%H:%M')}` "
        f"(in `{remaining}` s) · **App-Sync** ca. 1 Min danach"
        + (f" (noch `{app_wait}` s)" if app_wait > 0 else "")
    )

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
    # BEHOBEN: API-Migration von use_container_width=True auf width='stretch'
    st.plotly_chart(fig, width='stretch', key="live_power_flow_sankey")

################################    

def main():
    _inject_compact_numeric_css()
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
        setup_auto_refresh()
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
    render_optimization_savings_and_chart(current_soc)
    render_live_power_flow(current_soc)
    render_main_run_sync_panel()
    render_cached_simulation_details()
    render_countdown_block()


if __name__ == "__main__":
    main()