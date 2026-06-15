# pv_forecast.py
import requests
from datetime import datetime, timedelta
from typing import List
import config
import pv_tuner  # Importieren des neuen Moduls für das PV-Tuning

def get_hourly_pv_forecast() -> List[float]:
    """
    Holt die stündliche PV-Prognose für die nächsten 24 Stunden (ab der aktuellen Stunde).
    Gibt eine Liste mit exakt 24 Float-Werten (in kW) zurück.
    Erlaubt tagübergreifende Daten (heute/morgen), um die Nacht- und Folgetags-Optimierung zu sichern.
    """
    # Parameter aus der config laden
    lat = getattr(config, 'LATITUDE', 47.41)
    lon = getattr(config, 'LONGITUDE', 9.74)
    tilt = getattr(config, 'PV_TILT', 18)
    azimuth = getattr(config, 'PV_AZIMUTH', 28)
    kwp = getattr(config, 'PV_KWP', 6.0)

    # API-URL für die stündliche Abschätzung (Kostenlose Nutzung ohne Key)
    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}"
    
    # Wir bereiten die Zielfenster-Zeitstempel vor (Jetzt + die nächsten 23 Stunden)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    
    # Resultat-Vektor mit 0.0 kW vorinitialisieren
    pv_vector = [0.0] * 24

    try:
        # Robustes Timeout aus config nutzen
        response = requests.get(url, timeout=config.GLOBAL_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        # Das Feld 'watts' enthält die stündlichen Leistungswerte
        # Key-Format der API: "2026-06-15 08:00:00"
        hourly_watts = data.get('result', {}).get('watts', {})
        
        success_count = 0
        for idx, target_dt in enumerate(target_hours):
            # Formatieren, um den passenden Key im API-Response zu finden
            key_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
            
            if key_str in hourly_watts:
                watts = hourly_watts[key_str]
                # Umrechnung von Watt in Kilowatt (kW) und runden
                pv_vector[idx] = round(watts / 1000.0, 3)
                success_count += 1
        
        if success_count > 0:
            print(f"✅ PV-Ertragsprognose live abgerufen ({success_count}/24 Stunden gemappt. Max: {max(pv_vector)} kW).")
            return pv_vector
        else:
            print("⚠️ API-Daten empfangen, aber keine passenden Zeitstempel für die nächsten 24h gefunden. Nutze Fallback.")
            
    except requests.exceptions.Timeout:
        print(f"🚨 Timeout beim PV-Forecast ({config.GLOBAL_TIMEOUT}s überschritten). Nutze Fallback.")
    except requests.exceptions.HTTPError as http_err:
        print(f"🚨 HTTP-Fehler beim PV-Forecast-Abruf: {http_err}. Nutze Fallback.")
    except Exception as e:
        print(f"🚨 Unerwarteter Fehler beim PV-Forecast: {e}. Nutze Fallback.")

    # =========================================================================
    # ROBUSTER FALLBACK-ALGORITHMUS (Saisonal angepasst)
    # =========================================================================
    # Wenn die API blockiert oder gedrosselt wird, generieren wir eine synthetische
    # Parabel-Kurve basierend auf der Jahreszeit, damit der Optimizer nicht abstürzt.
    current_month = datetime.now().month
    
    # Schätzung der max. Peak-Leistung im Fallback je nach Monat (Winter vs. Sommer)
    if current_month in [11, 12, 1]:     # Tiefer Winter
        max_peak = kwp * 0.15 
    elif current_month in [2, 3, 10]:    # Übergangszeit
        max_peak = kwp * 0.40
    else:                                # Sommerhalbjahr
        max_peak = kwp * 0.65

    for idx, target_dt in enumerate(target_hours):
        hour = target_dt.hour
        # Eine einfache Parabel-Simulationskurve zwischen 6:00 und 18:00 Uhr
        if 6 <= hour <= 18:
            # Normierter Wert zwischen -1 und 1 (Peak um 12:00 Uhr ist 0)
            normalized_time = (hour - 12) / 6
            # Parabel berechnen: max * (1 - x^2)
            simulated_kw = max_peak * (1 - (normalized_time ** 2))
            pv_vector[idx] = round(max(0.0, simulated_kw), 3)
            
    # Bevor die Liste am Ende der Funktion zurückgegeben wird, tunen wir sie:
    tuning_factor = pv_tuner.calculate_tuning_factor(days_back=14)
    print(f"📈 Adaptives PV-Tuning: Wende Korrekturfaktor von {tuning_factor} an.")
    
    # Alle Werte im Vektor mit dem Faktor multiplizieren (und Abdeckelung bei 0)
    tuned_pv_vector = [round(max(0.0, val * tuning_factor), 3) for val in pv_vector]

    print(f"ℹ️ Synthetischer PV-Fallback-Vektor generiert (Saisonaler Max-Peak: {max(tuned_pv_vector):.2f} kW).")
    return tuned_pv_vector

if __name__ == "__main__":
    # Schneller Integrationstest
    print("Starte Testabruf PV-Forecast...")
    res = get_hourly_pv_forecast()
    print(f"Vektor-Länge: {len(res)} Elemente.")
    print(f"Vektor-Werte (nächste 24h ab jetzt): {res}")

    # In pv_forecast.py anpassen:

