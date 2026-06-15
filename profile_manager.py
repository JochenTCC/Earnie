# profile_manager.py
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple
import loxone_client
import pv_forecast

def generate_consumption_profile() -> bool:
    """Lädt aktuelle Logdaten und berechnet die Profil-CSV neu."""
    local_csv = loxone_client.fetch_loxone_csv_file()
    if not local_csv or not os.path.exists(local_csv):
        print("⚠️ Profil-Update abgebrochen: Logdatei konnte nicht geladen werden.")
        return False

    try:
        df = pd.read_csv(local_csv, sep=';', names=['timestamp', 'label', 'value'], header=None)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df.dropna(subset=['timestamp', 'value'], inplace=True)

        df['Month'] = df['timestamp'].dt.month
        df['Weekday'] = df['timestamp'].dt.weekday
        df['Hour'] = df['timestamp'].dt.hour
        
        profile = df.groupby(['Month', 'Weekday', 'Hour'])['value'].mean().reset_index()
        profile.rename(columns={'value': 'Consumption'}, inplace=True)
        profile['Consumption'] = profile['Consumption'].round(3)
        
        profile.to_csv('consumption_profiles.csv', index=False, sep=';')
        print("✅ 'consumption_profiles.csv' erfolgreich neu berechnet!")
        return True
    except Exception as e:
        print(f"🚨 Fehler bei der Profilberechnung: {e}")
        return False

def check_and_update_profile_if_new_month() -> None:
    """Überprüft, ob ein neuer Monat begonnen hat, und triggert ggf. das Profil-Update."""
    profile_path = 'consumption_profiles.csv'
    should_update = False
    
    if not os.path.exists(profile_path):
        print("ℹ️ Kein Verbrauchsprofil gefunden. Initialisiere erste Berechnung...")
        should_update = True
    else:
        # Prüfen, ob die Datei aus einem älteren Monat stammt
        file_time = os.path.getmtime(profile_path)
        file_date = datetime.fromtimestamp(file_time)
        current_date = datetime.now()
        
        if file_date.month != current_date.month or file_date.year != current_date.year:
            print(f"ℹ️ Neuer Monat erkannt (Letztes Profil von: {file_date.strftime('%d.%m.%Y')}).")
            should_update = True
            
    if should_update:
        generate_consumption_profile()

def get_forecast_vectors() -> Tuple[List[float], List[float]]:
    """
    Lädt das passende historische Verbrauchsprofil und die PV-Prognose 
    für die NÄCHSTEN 24 STUNDEN (rollierender Horizont ab der aktuellen Stunde).
    
    Returns:
        Tuple[List[float], List[float]]: (Verbrauchs_Vektor, PV_Vektor) jeweils exakt 24 Elemente.
    """
    profile_path = 'consumption_profiles.csv'
    
    # Zeitfenster definieren: Jetzt (auf Stunde gerundet) + die nächsten 23 Stunden
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    
    forecast_consumption: List[float] = []
    global_hour_defaults = {h: 0.5 for h in range(24)} # Fallback falls alles fehlschlägt (0.5 kW)

    if os.path.exists(profile_path):
        try:
            df_profiles = pd.read_csv(profile_path, sep=';')
            
            # Extrem schneller O(1) Lookup über Dictionary statt Pandas-Filterung in der Schleife
            # Key: (Month, Weekday, Hour) -> Value: Consumption
            lookup = df_profiles.set_index(['Month', 'Weekday', 'Hour'])['Consumption'].to_dict()
            
            # Grober Fallback (Nur nach Stunde gruppiert) falls ein Wochentag im Monat fehlt
            hour_fallback = df_profiles.groupby('Hour')['Consumption'].mean().to_dict()
            
            for dt in target_hours:
                key = (dt.month, dt.weekday(), dt.hour)
                
                if key in lookup:
                    forecast_consumption.append(float(lookup[key]))
                elif dt.hour in hour_fallback:
                    forecast_consumption.append(float(hour_fallback[dt.hour]))
                else:
                    forecast_consumption.append(global_hour_defaults.get(dt.hour, 0.5))
                    
        except Exception as e:
            print(f"🚨 Fehler beim Verarbeiten des Verbrauchsprofils: {e}. Nutze statische Defaults.")
            forecast_consumption = [global_hour_defaults[dt.hour] for dt in target_hours]
    else:
        print("ℹ️ Keine 'consumption_profiles.csv' vorhanden. Nutze Standard-Verbrauchswerte.")
        forecast_consumption = [global_hour_defaults[dt.hour] for dt in target_hours]

    # Live PV-Prognose abrufen (liefert bereits die nächsten 24h relativ ab 'now')
    forecast_pv = pv_forecast.get_hourly_pv_forecast()
    
    # Sicherheits-Slicing auf exakt 24 Elemente
    return forecast_consumption[:24], forecast_pv[:24]