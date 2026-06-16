# app.py
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import importlib
import os

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

def update_config_file(kwp, tilt, azimuth, k_push):
    """Schreibt Parameter atomar in eine JSON-Datei statt den Python-Code zu manipulieren."""
    settings_path = "runtime_settings.json"
    temp_path = f"{settings_path}.tmp"
    
    data = {
        "PV_KWP": float(kwp),
        "PV_TILT": int(tilt),
        "PV_AZIMUTH": int(azimuth),
        "K_PUSH": float(k_push)
    }
    
    try:
        # Erst in temporäre Datei schreiben
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        
        # Atomares Ersetzen auf OS-Ebene (verhindert Datei-Korruption bei Absturz)
        os.replace(temp_path, settings_path)
        st.success("✅ Einstellungen erfolgreich und sicher gespeichert!")
        return True
    except Exception as e:
        st.error(f"🚨 Fehler beim Speichern der Einstellungen: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

# ==============================================================================
# SIDEBAR: EINSTELLUNGEN & TUNING-ANZEIGE
# ==============================================================================
st.sidebar.title("⚙️ Anlagenkonfiguration")
st.sidebar.markdown("Änderungen werden direkt in der `config.py` hinterlegt.")

# Eingabefelder mit aktuellen Werten aus der config.py vorbefüllen
kwp_val = st.sidebar.number_input("Anlagenleistung (kWp)", value=float(config.PV_KWP), step=0.1, format="%.2f")
tilt_val = st.sidebar.number_input("Ausrichtung: Neigung (Tilt °)", value=int(config.PV_TILT), step=1)
azimuth_val = st.sidebar.number_input("Ausrichtung: Azimut (Azimuth °)", value=int(config.PV_AZIMUTH), step=1)
k_push_val = st.sidebar.number_input("Einspeisevergütung (Cent/kWh)", value=float(config.K_PUSH), step=0.1, format="%.2f")

if st.sidebar.button("Einstellungen speichern"):
    if update_config_file(kwp_val, tilt_val, azimuth_val, k_push_val):
        st.sidebar.success("✅ Parameter erfolgreich gespeichert!")
        # Modul neu laden, damit die Änderungen sofort im aktuellen Lauf greifen
        importlib.reload(config)
        st.rerun()

# --- ADAPTIVES PV-TUNING ANZEIGE ---
st.sidebar.markdown("---")
st.sidebar.subheader("📈 Adaptives PV-Tuning")

# Berechne den aktuellen Faktor aus der historischen CSV der letzten 14 Tage
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

# Faktor visuell ansprechend als Metrik ausgeben
st.sidebar.metric(
    label="Aktueller Korrekturfaktor",
    value=f"{tuning_factor:.2f}",
    delta=delta_text,
    delta_color=delta_color
)

st.sidebar.caption(
    "Errechnet aus dem automatischen Abgleich zwischen Forecast.Solar "
    "und deinen realen Loxone-Zählerständen der vergangenen 2 Wochen."
)


# ==============================================================================
# MAIN PAGE: CONTROL CENTER COCKPIT
# ==============================================================================
st.title("🔋 Ernie Energy Control Center")
st.markdown("Echtzeit-Cockpit und Vorhersage-Simulation des synchronisierten 24-Stunden-Horizonts.")

# 1. Live-Daten aus dem Miniserver abrufen
current_soc = loxone_client.fetch_loxone_soc()
if current_soc is None:
    current_soc = 50.0  # Sicherer Fallback-Wert für die UI, falls Loxone offline ist
    st.warning("⚠️ Live-Batteriestand konnte nicht von Loxone geladen werden. Simulation läuft mit 50% Fallback-SoC.")
else:
    st.info(f"⚡ Aktueller Batterie-Ladezustand (Live-SoC): **{current_soc}%**")

# 2. Marktdaten von aWATTar abrufen
market_data = awattar_client.fetch_awattar_prices()

if not market_data:
    st.error("🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. Abbruch der Simulation.")
else:
    # 3. Prognose-Vektoren laden (Hier fließt das Tuning im Hintergrund bereits ein!)
    forecast_consumption, forecast_pv, optimization_matrix = profile_manager.get_forecast_vectors(market_data)
        
    # 4. 24h-Horizont-Simulation anstoßen
    df = pd.DataFrame(optimizer.simulate_24h_horizon(optimization_matrix, current_soc))
    
    # ==============================================================================
    # PLOTLY CHART ERSTELLEN
    # ==============================================================================
    fig = go.Figure()
    
    # Primäre Y-Achse: Leistungen (kW)
    fig.add_trace(go.Scatter(
        x=df["Uhrzeit"], 
        y=df["PV-Prognose (kW)"], 
        name="PV-Ertrag Prognose (kW)", 
        line=dict(color='#f1c40f', width=2),
        fill='tozeroy',                             # Füllt die Fläche bis zur 0-Linie
        fillcolor='rgba(241, 196, 15, 0.2)',        # Gelb mit 20% Deckkraft (transparent)
        yaxis="y1"
    ))
    
    fig.add_trace(go.Scatter(
        x=df["Uhrzeit"], 
        y=df["Verbrauch-Prognose (kW)"], 
        name="Historischer Verbrauch (kW)", 
        line=dict(color='#3498db', width=2, dash='dash'),
        yaxis="y1"
    ))

    fig.add_trace(go.Bar(
        x=df["Uhrzeit"],
        y=df["Geplante Batterie-Aktion (kW)"],
        name="Geplante Batterie-Aktion (kW)",
        marker=dict(
            color='rgba(46, 204, 113, 0.5)',        # Angenehmes Grün mit 50% Deckkraft
            line=dict(color='#2ecc71', width=1.5)   # Solider grüner Rahmen um die Balken
        ),
        yaxis="y1"
    ))
    
    # Sekundäre Y-Achse: Preise & SoC
    fig.add_trace(go.Scatter(
        x=df["Uhrzeit"], 
        y=df["Strompreis (Cent/kWh)"], 
        name="Börsenstrompreis (Cent)", 
        line=dict(color='#e74c3c', width=3, shape='hv'),
        yaxis="y2"
    ))
    
    fig.add_trace(go.Scatter(
        x=df["Uhrzeit"], 
        y=df["Simulierter SoC (%)"], 
        name="Simulierter Speicher-SoC (%)", 
        line=dict(color='#9b59b6', width=2, dash='dot'),
        yaxis="y2"
    ))
    
    # Layout-Konfiguration für zwei getrennte Achsen
    fig.update_layout(
        title="Synchronisierter 24-Stunden-Zeithorizont (Leistung vs. Preis & SoC)",
        xaxis=dict(title="Uhrzeit (Stunden-Slots)"),
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(title="Preis (Cent/kWh) / SoC (%)", side="right", overlaying="y", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=80, b=40)
    )
    
    # Visualisierung im Dashboard mit zukunftssicherer Breite (stretch)
    st.plotly_chart(fig, width='stretch')
    
    # ==============================================================================
    # DATATABLE DETAILS
    # ==============================================================================
    st.subheader("📋 Simulations-Details (Nächste 24 Stunden)")
    st.markdown("Hier sind die exakten mathematischen Stundenslots aufgelistet, die als Grundlage für den Chart dienen:")
    st.dataframe(df, width='stretch')