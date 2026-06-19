# profile_manager.py
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple
import loxone_client
import pv_forecast
import config


def _load_and_resample_csv(filepath: str, is_wp: bool = False, wp_power: float = 1.6) -> pd.Series:
    """Lädt eine Loxone-CSV, bereinigt sie und aggregiert sie robust über ein Minutenraster auf 1-Stunden-Mittelwerte."""
    if not filepath or not os.path.exists(filepath):
        return pd.Series(dtype=float)
        
    try:
        # Einlesen mit Berücksichtigung des deutschen Dezimaltrennzeichens (Komma)
        df = pd.read_csv(filepath, sep=';', decimal=',', header=0)
        
        # Falls die Datei keine Kopfzeile hat und 3 Spalten besitzt (alter loxone_client Standard):
        if df.shape[1] == 3 and not any("datum" in str(col).lower() or "uhrzeit" in str(col).lower() for col in df.columns):
            df = pd.read_csv(filepath, sep=';', decimal=',', names=['timestamp', 'label', 'value'], header=None)
        else:
            # Spalten passend umbenennen für eine einheitliche Verarbeitung
            if df.shape[1] == 2:
                df.columns = ['timestamp', 'value']
            elif df.shape[1] == 3:
                df.columns = ['timestamp', 'label', 'value']
                
        # Zeitstempel konvertieren (Loxone Standardformat bevorzugt testen)
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='%d.%m.%Y %H:%M', errors='coerce')
        if df['timestamp'].isna().all():
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            
        df.dropna(subset=['timestamp', 'value'], inplace=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df.dropna(subset=['value'], inplace=True)
        
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        
        # 1-Minuten-Raster zur feingranularen Überbrückung von Event-Lücken (Forward-Fill)
        s_minutely = df['value'].resample('1min').ffill()
        
        # Falls Wärmepumpe: Status (0/1) mit Nennleistung multiplizieren
        if is_wp:
            s_minutely = s_minutely * wp_power
            
        # Zurück auf Stunden-Mittelwerte (Stunden-Verbrauch/Lastäquivalent)
        return s_minutely.resample('1h').mean()
        
    except Exception as e:
        print(f"⚠️ Fehler beim Verarbeiten von {filepath}: {e}")
        return pd.Series(dtype=float)


def generate_consumption_profile() -> bool:
    """Lädt alle Logs, isoliert die nackte Grundlast und berechnet das Profil neu."""
    path_total = config.get('PATH_CONSUMPTION_TOTAL', cast=str) or loxone_client.fetch_loxone_csv_file()
    path_eauto = config.get('PATH_E_AUTO', cast=str)
    path_pool = config.get('PATH_POOL', cast=str)
    path_wp = config.get('PATH_WP', cast=str)
    wp_power = config.get('WP_NOMINAL_POWER_KW', cast=float)

    if not path_total or not os.path.exists(path_total):
        print("⚠️ Profil-Update abgebrochen: Haupt-Logdatei für Gesamtverbrauch fehlt.")
        return False

    try:
        print("⏳ Verarbeite Verbrauchsdaten und isoliere die Haus-Grundlast...")
        
        # 1. Alle Zeitreihen laden und stündlich synchronisieren
        s_total = _load_and_resample_csv(path_total)
        s_eauto = _load_and_resample_csv(path_eauto)
        s_pool = _load_and_resample_csv(path_pool)
        s_wp = _load_and_resample_csv(path_wp, is_wp=True, wp_power=wp_power)

        if s_total.empty:
            print("⚠️ Gesamtverbrauch-Zeitreihe konnte nicht geladen werden oder ist leer.")
            return False

        # 2. DataFrame über den Hauptzeitindex aufbauen
        df = pd.DataFrame({'Total': s_total})
        
        df['E_Auto'] = s_eauto if not s_eauto.empty else 0.0
        df['Pool'] = s_pool if not s_pool.empty else 0.0
        df['WP'] = s_wp if not s_wp.empty else 0.0
        
        # Fehlende Abschnitte zwischen verschiedenen Log-Zeiträumen abfangen
        df.fillna({'E_Auto': 0.0, 'Pool': 0.0, 'WP': 0.0}, inplace=True)

        # 3. Nackte Grundlast berechnen (Verhinderung negativer Werte bei Loxone-Messversatz)
        df['BaseLoad'] = df['Total'] - df['E_Auto'] - df['Pool'] - df['WP']
        df['BaseLoad'] = df['BaseLoad'].clip(lower=0.0)

        # 4. Zeitmerkmale extrahieren
        df['Month'] = df.index.month
        df['Weekday'] = df.index.weekday
        df['Hour'] = df.index.hour
        
        # 5. Profil aus bereinigter Grundlast aggregieren
        profile = df.groupby(['Month', 'Weekday', 'Hour'])['BaseLoad'].mean().reset_index()
        profile.rename(columns={'BaseLoad': 'Consumption'}, inplace=True)
        profile['Consumption'] = profile['Consumption'].round(3)
        
        profile.to_csv('consumption_profiles.csv', index=False, sep=';')
        print("✅ 'consumption_profiles.csv' erfolgreich aus der bereinigten Grundlast neu berechnet!")
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
        file_time = os.path.getmtime(profile_path)
        file_date = datetime.fromtimestamp(file_time)
        current_date = datetime.now()
        
        if file_date.month != current_date.month or file_date.year != current_date.year:
            print(f"ℹ️ Neuer Monat erkannt (Letztes Profil von: {file_date.strftime('%d.%m.%Y')}).")
            should_update = True
            
    if should_update:
        generate_consumption_profile()


def _load_consumption_profile(target_hours: List) -> List[float]:
    """Lädt das Verbrauchsprofil für die Zielstunden."""
    profile_path = 'consumption_profiles.csv'
    forecast_consumption = []
    global_hour_defaults = {h: 0.5 for h in range(24)}

    if os.path.exists(profile_path):
        try:
            df_profiles = pd.read_csv(profile_path, sep=';')
            lookup = df_profiles.set_index(['Month', 'Weekday', 'Hour'])['Consumption'].to_dict()
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

    return forecast_consumption


def _build_optimization_matrix(market_data: list, forecast_consumption: list, forecast_pv: list) -> list:
    """Erstellt die Optimierungs-Matrix mit Preis-, Verbrauchs- und PV-Daten."""
    optimization_matrix = []
    
    fix_aufschlag = config.get('FIX_AUFSCHLAG_CENT', cast=float)
    netzverlust = config.get('NETZVERLUST_FAKTOR', cast=float)
    mwst_faktor = config.get('MWST_AUSTRIA_FAKTOR', cast=float)

    for i, item in enumerate(market_data[:24]):    
        hour = item['hour']
        
        try:
            epex_price_cent = float(item['price_buy'])
            brutto_price_cent = (epex_price_cent * netzverlust + fix_aufschlag) * mwst_faktor
            brutto_price_cent = round(brutto_price_cent, 4)
        except (TypeError, ValueError) as e:
            print(f"🚨 Fehler bei Brutto-Berechnung für Stunde {hour}: {e}. Nutze Rohwert.")
            brutto_price_cent = item['price_buy']

        optimization_matrix.append({
            "hour": hour,
            "k_act": brutto_price_cent,
            "expected_p_act": forecast_consumption[i],
            "expected_p_pv": forecast_pv[i]
        })
    
    return optimization_matrix[:24]


def get_forecast_vectors(market_data) -> Tuple[List[float], List[float], List[dict]]:
    """
    Lädt das passende historische Verbrauchsprofil und die PV-Prognose 
    für die NÄCHSTEN 24 STUNDEN (rollierender Horizont ab der aktuellen Stunde).
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    
    forecast_consumption = _load_consumption_profile(target_hours)
    forecast_pv = pv_forecast.get_hourly_pv_forecast()
    optimization_matrix = _build_optimization_matrix(market_data, forecast_consumption, forecast_pv)

    return forecast_consumption[:24], forecast_pv[:24], optimization_matrix[:24]


# ==============================================================================
# NEU: EXTRAKTION DER GRUNDLAST UND TAGESSUMMEN FÜR DEN OPTIMIZER (SIMULATION)
# ==============================================================================
def get_historical_day_data(target_date) -> Tuple[List[float], dict]:
    """
    Extrahiert für ein bestimmtes Datum (datetime.date, datetime oder String 'YYYY-MM-DD') 
    die 24-stündige reale Grundlast (BaseLoad) sowie die Tages-Gesamtsummen (kWh) 
    der steuerbaren Verbraucher (E-Auto, SwimSpa/Pool, Wärmepumpe).
    """
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()
        
    path_total = config.get('PATH_CONSUMPTION_TOTAL', cast=str) or loxone_client.fetch_loxone_csv_file()
    path_eauto = config.get('PATH_E_AUTO', cast=str)
    path_pool = config.get('PATH_POOL', cast=str)
    path_wp = config.get('PATH_WP', cast=str)
    wp_power = config.get('WP_NOMINAL_POWER_KW', cast=float)

    # 1. Zeitreihen exakt laden und stündlich synchronisieren
    s_total = _load_and_resample_csv(path_total)
    s_eauto = _load_and_resample_csv(path_eauto)
    s_pool = _load_and_resample_csv(path_pool)
    s_wp = _load_and_resample_csv(path_wp, is_wp=True, wp_power=wp_power)

    if s_total.empty:
        print(f"⚠️ Keine historischen Daten vorhanden für das Datum {target_date}.")
        return [0.5] * 24, {'ev_kwh': 0.0, 'spa_kwh': 0.0, 'wp_kwh': 0.0}

    # 2. Synchronisierten DataFrame aufbauen
    df = pd.DataFrame({'Total': s_total})
    df['E_Auto'] = s_eauto if not s_eauto.empty else 0.0
    df['Pool'] = s_pool if not s_pool.empty else 0.0
    df['WP'] = s_wp if not s_wp.empty else 0.0
    df.fillna({'E_Auto': 0.0, 'Pool': 0.0, 'WP': 0.0}, inplace=True)

    # 3. Nackte reale Grundlast für diesen Tag isolieren
    df['BaseLoad'] = df['Total'] - df['E_Auto'] - df['Pool'] - df['WP']
    df['BaseLoad'] = df['BaseLoad'].clip(lower=0.0)

    # 4. Auf den Zieltag filtern und robust auf 24 diskrete Stunden reindexen
    df_day = df[df.index.date == target_date]
    full_day_range = pd.date_range(
        start=f"{target_date} 00:00:00", 
        end=f"{target_date} 23:00:00", 
        freq='1h'
    )
    df_day = df_day.reindex(full_day_range, fill_value=0.0)

    # 5. Tages-Summen berechnen (Da Stunden-Mittelwerte der Leistung (kW), entspricht die Summe direkt kWh)
    historical_totals = {
        'ev_kwh': round(float(df_day['E_Auto'].sum()), 3),
        'spa_kwh': round(float(df_day['Pool'].sum()), 3),
        'wp_kwh': round(float(df_day['WP'].sum()), 3)
    }

    # 6. Reales 24-Stunden Grundlast-Profil als Liste extrahieren
    actual_baseload = df_day['BaseLoad'].round(3).tolist()

    return actual_baseload, historical_totals