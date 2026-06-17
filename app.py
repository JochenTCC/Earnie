# app.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import importlib
import time

# Bestehende Projektmodule importieren
import config
import loxone_client
import awattar_client
import profile_manager
import optimizer
import pv_tuner  # Adaptives PV-Tuning-Modul einbinden

st.set_page_config(
    page_title="Ernie Energy Control Center",
    page_icon="🔋",
    layout="wide"
)

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
        "und deinen realen Loxone-Zählerständen der vergangenen 2 Wochen."
    )


def render_parameter_input():
    st.sidebar.header("⚙️ System-Parameter")
    st.sidebar.markdown("Änderungen werden direkt über das Konfigurationsmodul angewendet.")

    render_config_form(get_runtime_settings())
    render_pv_tuning_sidebar()


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


def render_savings_metrics(savings: dict):
    st.subheader("💶 Optimierungs-Einsparungen")
    baseline_cost = savings.get('baseline_cost_euro', 0.0)
    optimized_cost = savings.get('optimized_cost_euro', 0.0)
    savings_euro = savings.get('savings_euro', 0.0)
    
    # Berechne Gesamtverbrauch und Kosten ohne PV aus den Reihen
    optimized_rows = savings.get('optimized_rows', [])
    total_consumption_kwh = 0.0
    cost_without_pv_cents = 0.0
    if optimized_rows:
        for row in optimized_rows:
            consumption = row.get("Verbrauch-Prognose (kW)", 0.0)
            price_cent = row.get("Strompreis (Cent/kWh)", 0.0)
            total_consumption_kwh += consumption
            cost_without_pv_cents += consumption * price_cent
        
        cost_without_pv_euro = cost_without_pv_cents / 100.0
        
        # Hochrechnung auf 24h falls nur weniger als 24h vorhanden
        num_hours = len(optimized_rows)
        consumption_24h = total_consumption_kwh * (24 / num_hours) if num_hours > 0 else 0.0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Ohne PV (Netzbe­zug)", f"{cost_without_pv_euro:.2f} €", help="Kosten bei 100% Netzbezug ohne PV-Anlage")
    col2.metric("Baseline-Kosten", f"{baseline_cost:.2f} €")
    col3.metric("Optimierte Kosten", f"{optimized_cost:.2f} €")

    if savings_euro >= 0:
        display_value = f"-{savings_euro:.2f} €"
        delta_value = f"-{savings_euro:.2f} €"
        delta_color = "inverse"
    else:
        display_value = f"+{abs(savings_euro):.2f} €"
        delta_value = f"+{abs(savings_euro):.2f} €"
        delta_color = "normal"

    col4.metric("Ersparnis", display_value, delta=delta_value, delta_color=delta_color)
    col5.metric("Verbrauch 24h", f"{consumption_24h:.1f} kWh", help=f"Tatsächlich gemessen: {total_consumption_kwh:.1f} kWh über {len(optimized_rows)} Stunden")


def fetch_market_data():
    market_data = awattar_client.fetch_awattar_prices()
    if not market_data:
        st.error("🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. Abbruch der Simulation.")
        return None
    return market_data


def render_simulation_details(df):
    st.subheader("📋 Simulations-Details (Nächste 24 Stunden)")
    st.markdown("Hier sind die exakten mathematischen Stundenslots aufgelistet, die als Grundlage für den Chart dienen:")
    st.dataframe(df, width='stretch')


def setup_auto_refresh():
    """Initialisiert den automatischen Refresh-Mechanismus basierend auf LOOP_TIMEOUT."""
    loop_timeout = config.get('LOOP_TIMEOUT', default=720, cast=int)
    
    # Initialisiere den Refresh-Timer in session_state, falls noch nicht vorhanden
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()
    
    # Überprüfe, ob genug Zeit seit dem letzten Refresh vergangen ist
    time_since_refresh = time.time() - st.session_state.last_refresh
    
    if time_since_refresh >= loop_timeout:
        # Zeit für einen Refresh
        st.session_state.last_refresh = time.time()
        st.rerun()

@st.fragment(run_every=config.get('LOOP_TIMEOUT', default=720, cast=int))
def render_optimization_block(current_soc: float):
    """Führt die rechenintensive Optimierung im großen LOOP_TIMEOUT-Takt aus."""
    st.subheader("📈 Last- & Preisverlauf")
    market_data = fetch_market_data()
    if market_data is None:
        return

    _, _, matrix = profile_manager.get_forecast_vectors(market_data)
    savings_info = optimizer.calculate_optimization_savings(matrix, current_soc)
    
    optimized_df = pd.DataFrame(savings_info['optimized_rows'])
    baseline_df = pd.DataFrame(savings_info['baseline_rows'])

    render_savings_metrics(savings_info)
    render_optimization_chart(optimized_df, baseline_df)
    render_simulation_details(optimized_df)
    
    # Zeitstempel für den Countdown-Block bereitstellen
    st.session_state.last_optimization = time.time()

@st.fragment(run_every=10)
def render_countdown_block():
    """Aktualisiert alle 10 Sekunden exklusiv die Anzeige des Countdowns."""
    loop_timeout = config.get('LOOP_TIMEOUT', default=720, cast=int)
    
    if 'last_optimization' not in st.session_state:
        st.session_state.last_optimization = time.time()
        
    elapsed = time.time() - st.session_state.last_optimization +0.1
    remaining = max(0, int(loop_timeout - elapsed))
    
    last_time = time.strftime("%H:%M:%S", time.localtime(st.session_state.last_optimization))
     
    st.markdown("---")
    st.caption(
        f"🔄 **Optimierungs-Takt:** Alle {int(loop_timeout/60)} Min ({loop_timeout}s) | "
        f"⏱️ Letzte Optimierung: **{last_time}**"
    )
    st.caption(f"⏳ **Nächste Berechnung in:** `{remaining}` Sekunden (Countdown aktualisiert alle 10s)")

def main():
    st.title("🔋 Ernie Energy Control Center")
    st.markdown("Echtzeit-Cockpit und Vorhersage-Simulation des synchronisierten 24-Stunden-Horizonts.")

    # 1. Parameter-Eingabemaske in der Sidebar (statisch)
    render_parameter_input()

    # Live SoC abrufen
    current_soc = loxone_client.fetch_loxone_soc()
    if current_soc is None:
        current_soc = 50.0
        st.warning("⚠️ Live-Batteriestand konnte nicht von Loxone geladen werden. Simulation läuft mit 50% Fallback-SoC.")
    else:
        st.info(f"⚡ Aktueller Batterie-Ladezustand (Live-SoC): **{current_soc}%**")

    # 2. Steuerung der beiden entkoppelten Refresh-Kreisläufe
    render_optimization_block(current_soc)
    render_countdown_block()

if __name__ == "__main__":
    main()