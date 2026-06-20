# app_test_data.py
import streamlit as st
import pandas as pd
from datetime import datetime
import config
import loxone_log_import

# Streamlit Seitenkonfiguration
st.set_page_config(page_title="Last-Isolierung Test", layout="wide")

st.title("📊 Verbraucher-Isolierung & Grundlast-Test")
st.markdown("Dieses Dashboard validiert die saubere Trennung der Großverbraucher von der Haus-Grundlast.")

# 1. Sidebar für die Datumsauswahl
st.sidebar.header("Einstellungen")

# Versuche ein sinnvolles Standarddatum zu setzen (z.B. aus dem Jahr 2026, da deine Logs bis dahin gehen)
default_date = datetime(2026, 5, 15)
selected_date = st.sidebar.date_input("Simulations-Tag auswählen:", default_date)

# 2. Daten laden und aufbereiten
@st.cache_data(ttl=60)
def load_and_process_day(target_date):
    # Basis-Pfade holen
    path_total = config.get('PATH_CONSUMPTION_TOTAL', cast=str)
    path_eauto = config.get('PATH_E_AUTO', cast=str)
    path_pool = config.get('PATH_POOL', cast=str)
    path_wp = config.get('PATH_WP', cast=str)
    wp_power = config.get('WP_NOMINAL_POWER_KW', cast=float)

    s_total = loxone_log_import.load_and_resample_csv(path_total)
    s_eauto = loxone_log_import.load_and_resample_csv(path_eauto)
    s_pool = loxone_log_import.load_and_resample_csv(path_pool)
    s_wp = loxone_log_import.load_and_resample_csv(path_wp, is_wp=True, wp_power=wp_power)

    if s_total.empty:
        return None, None

    # DataFrame zusammenstellen
    df = pd.DataFrame({'Total': s_total})
    df['E-Auto'] = s_eauto if not s_eauto.empty else 0.0
    df['SwimSpa'] = s_pool if not s_pool.empty else 0.0
    df['Wärmepumpe'] = s_wp if not s_wp.empty else 0.0
    df.fillna({'E-Auto': 0.0, 'SwimSpa': 0.0, 'Wärmepumpe': 0.0}, inplace=True)
    
    # Grundlast ermitteln
    df['Grundlast'] = df['Total'] - df['E-Auto'] - df['SwimSpa'] - df['Wärmepumpe']
    df['Grundlast'] = df['Grundlast'].clip(lower=0.0)

    # Auf ausgewählten Tag filtern
    df_day = df[df.index.date == target_date]
    full_day_range = pd.date_range(start=f"{target_date} 00:00:00", end=f"{target_date} 23:00:00", freq='1h')
    df_day = df_day.reindex(full_day_range, fill_value=0.0)
    
    # Index lesbar für das Diagramm machen (00:00 bis 23:00)
    df_day.index = [f"{h:02d}:00" for h in range(24)]
    
    # Energiesummen berechnen
    totals = {
        'total_kwh': df_day['Total'].sum(),
        'baseload_kwh': df_day['Grundlast'].sum(),
        'ev_kwh': df_day['E-Auto'].sum(),
        'spa_kwh': df_day['SwimSpa'].sum(),
        'wp_kwh': df_day['Wärmepumpe'].sum()
    }
    
    return df_day, totals

# Daten verarbeiten
df_plot, sums = load_and_process_day(selected_date)

if df_plot is None or len(df_plot) == 0 or (sums and sums['total_kwh'] == 0):
    st.warning(f"⚠️ Keine Daten für den {selected_date} in den CSV-Dateien gefunden.")
else:
    # 3. KPI Metriken (Numerische Tages-Summen)
    st.subheader("📋 Tages-Energiemengen (kWh)")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    col1.metric("Gesamt Brutto", f"{sums['total_kwh']:.2f} kWh")
    col2.metric("🏠 Reine Grundlast", f"{sums['baseload_kwh']:.2f} kWh")
    col3.metric("🚗 E-Auto", f"{sums['ev_kwh']:.2f} kWh")
    col4.metric("🏊 SwimSpa", f"{sums['spa_kwh']:.2f} kWh")
    col5.metric("🔥 Wärmepumpe", f"{sums['wp_kwh']:.2f} kWh")

    st.markdown("---")

    # 4. Grafische Darstellung
    st.subheader("📈 Stündlicher Leistungsverlauf (kW)")
    
    # Auswahl des Diagrammtyps
    chart_type = st.radio("Diagrammtyp:", ["Gestapelte Fläche (Visuelle Aufteilung)", "Linien-Diagramm (Einzelvergleich)"], horizontal=True)
    
    # DataFrame für das Diagramm vorbereiten (ohne die 'Total' Spalte, da sich die Stapelung daraus ergibt)
    chart_data = df_plot[['Grundlast', 'E-Auto', 'SwimSpa', 'Wärmepumpe']]
    
    if "Fläche" in chart_type:
        st.area_chart(chart_data)
    else:
        st.line_chart(df_plot[['Total', 'Grundlast', 'E-Auto', 'SwimSpa', 'Wärmepumpe']])

    # 5. Datentabelle im Detail zum Aufklappen
    with st.expander("🔍 Stündliche Rohdaten einsehen"):
        st.dataframe(df_plot.style.format("{:.3f} kW"), use_container_width=True)