"""Führt historische Loxone-CSV-Logs mit dem aktuellen Logger-Format zusammen."""
from __future__ import annotations

import os
import pandas as pd

# Dateinamen definieren
HISTORICAL_FILE = 'Miniserver-Gen2_Energiemonitor_LeistungVerbrauch_20230323-20260615.csv'
NEW_LOGGER_FILE = 'Verbrauch.csv'
OUTPUT_FILE = 'Verbrauch_Merged.csv'

def merge_consumption_logs():
    print("🔄 Starte die Zusammenführung der Verbrauchsdaten...")
    
    if not os.path.exists(HISTORICAL_FILE) or not os.path.exists(NEW_LOGGER_FILE):
        print("🚨 Fehler: Eine der Dateien fehlt im Verzeichnis!")
        return

    # 1. Historischen Log einlesen (2 Spalten: Datum/Uhrzeit;Leistung Verbrauch [kW])
    print(f"📖 Lese historische Daten ein ({HISTORICAL_FILE})...")
    df_hist = pd.read_csv(HISTORICAL_FILE, sep=';', decimal=',')
    
    # Datum konvertieren (deutsches Format)
    df_hist['parsed_dt'] = pd.to_datetime(df_hist['Datum/Uhrzeit'], format='%d.%m.%Y %H:%M', errors='coerce')
    
    # In das dreispaltige Logger-Format transformieren
    df_hist_formatted = pd.DataFrame()
    df_hist_formatted['timestamp'] = df_hist['parsed_dt'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_hist_formatted['label'] = 'Verbrauchsdaten'
    df_hist_formatted['value'] = df_hist['Leistung Verbrauch [kW]'].round(3)
    
    # Ungültige Datumszeilen löschen (falls vorhanden)
    df_hist_formatted.dropna(subset=['timestamp'], inplace=True)

    # 2. Fast neuen Log einlesen (3 Spalten, bereits im richtigen Format)
    print(f"📖 Lese neuen Logger-Stand ein ({NEW_LOGGER_FILE})...")
    df_new = pd.read_csv(NEW_LOGGER_FILE, sep=';', names=['timestamp', 'label', 'value'])

    # 3. Verbinden & Chronologisch sortieren
    print("🔀 Kombiniere Datensätze und korrigiere Chronologie...")
    combined = pd.concat([df_hist_formatted, df_new], ignore_index=True)
    
    # Zeilen ohne echten Messwert filtern
    combined.dropna(subset=['value'], inplace=True)
    
    # Über Hilfsspalte chronologisch sortieren
    combined['sort_dt'] = pd.to_datetime(combined['timestamp'])
    combined = combined.sort_values(by='sort_dt').drop(columns=['sort_dt'])

    # 4. Speichern im exakten Loxone-Logger-Format (Ohne Header, Semikolon, Punkt als Dezimaltrenner)
    combined.to_csv(OUTPUT_FILE, sep=';', header=False, index=False)
    
    print("\n📊 --- Migrations-Statistik ---")
    print(f" Erster Datenpunkt: {combined['timestamp'].iloc[0]}")
    print(f" Letzter Datenpunkt: {combined['timestamp'].iloc[-1]}")
    print(f" Gesamtanzahl Zeilen: {len(combined)}")
    print(f"✅ Datei erfolgreich exportiert als: '{OUTPUT_FILE}'")

if __name__ == "__main__":
    merge_consumption_logs()