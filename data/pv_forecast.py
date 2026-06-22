# pv_forecast.py
import requests
from datetime import datetime, timedelta
from typing import List, Optional
import config
from . import pv_tuner  # PV-Tuning

# =========================================================================
# GLOBALE CACHE-VARIABLEN (Für Rate-Limiting & API-Schonung)
# =========================================================================
_LAST_API_CALL: Optional[datetime] = None
_CACHED_HOURLY_WATTS: Optional[dict] = None


def _check_and_fetch_api_data(url: str, kwp: float) -> Optional[dict]:
    """Prüft Cache-Gültigkeit und holt ggf. neue API-Daten."""
    global _LAST_API_CALL, _CACHED_HOURLY_WATTS
    
    now_time = datetime.now()
    
    if _LAST_API_CALL and (now_time - _LAST_API_CALL) < timedelta(minutes=15):
        print("⏳ forecast.solar-Schutz: Letzter API-Aufruf vor weniger als 15 min. Nutze lokalen Cache.")
        return _CACHED_HOURLY_WATTS
    
    try:
        _LAST_API_CALL = now_time
        response = requests.get(url, timeout=config.get_global_timeout())
        response.raise_for_status()
        data = response.json()
        hourly_watts = data.get('result', {}).get('watts', {})
        _CACHED_HOURLY_WATTS = hourly_watts
        return hourly_watts
    except requests.exceptions.Timeout:
        print(f"🚨 Timeout beim PV-Forecast ({config.get_global_timeout()}s überschritten). Nutze Fallback.")
    except requests.exceptions.HTTPError as http_err:
        print(f"🚨 HTTP-Fehler beim PV-Forecast-Abruf: {http_err}. Nutze Fallback.")
    except Exception as e:
        print(f"🚨 Unerwarteter Fehler beim PV-Forecast: {e}. Nutze Fallback.")
    
    return None


def _map_hourly_data_to_vector(hourly_watts: dict, target_hours: list) -> tuple[list, bool]:
    """Mappt API-Daten auf die Zielstunden. Returns (pv_vector, success)."""
    pv_vector = [0.0] * 24
    success_count = 0
    
    for idx, target_dt in enumerate(target_hours):
        key_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        if key_str in hourly_watts:
            watts = hourly_watts[key_str]
            pv_vector[idx] = round(watts / 1000.0, 3)
            success_count += 1
    
    if success_count > 0:
        print(f"✅ PV-Ertragsprognose erfolgreich bereitgestellt ({success_count}/24 Stunden gemappt. Max: {max(pv_vector)} kW).")
        return pv_vector, True
    
    return pv_vector, False


def _generate_seasonal_fallback(target_hours: list, kwp: float) -> list:
    """Generiert eine saisonale Fallback-Prognose."""
    pv_vector = [0.0] * 24
    current_month = datetime.now().month
    
    if current_month in [11, 12, 1]:
        max_peak = kwp * 0.15
    elif current_month in [2, 3, 10]:
        max_peak = kwp * 0.40
    else:
        max_peak = kwp * 0.65

    for idx, target_dt in enumerate(target_hours):
        hour = target_dt.hour
        if 6 <= hour <= 18:
            normalized_time = (hour - 12) / 6
            simulated_kw = max_peak * (1 - (normalized_time ** 2))
            pv_vector[idx] = round(max(0.0, simulated_kw), 3)
    
    return pv_vector


def _apply_tuning_factor(pv_vector: list) -> list:
    """Wendet den adaptiven PV-Tuning-Faktor an."""
    tuning_factor = pv_tuner.calculate_tuning_factor(days_back=14)
    print(f"📈 Adaptives PV-Tuning: Wende Korrekturfaktor von {tuning_factor} an.")
    
    tuned_vector = [round(max(0.0, val * tuning_factor), 3) for val in pv_vector]
    print(f"ℹ️ Synthetischer PV-Fallback-Vektor generiert (Saisonaler Max-Peak: {max(tuned_vector):.2f} kW).")
    
    return tuned_vector


def get_hourly_pv_forecast() -> List[float]:
    """
    Holt die stündliche PV-Prognose für die nächsten 24 Stunden (ab der aktuellen Stunde).
    Gibt eine Liste mit exakt 24 Float-Werten (in kW) zurück.
    Schützt die forecast.solar API durch ein integriertes 15-Minuten-Caching.
    Wendet das adaptive PV-Tuning konsistent auf API-Daten und Fallbacks an.
    """
    lat = config.get('LATITUDE', cast=float)
    lon = config.get('LONGITUDE', cast=float)
    tilt = config.get('PV_TILT', cast=float)
    azimuth = config.get('PV_AZIMUTH', cast=float)
    kwp = config.get('PV_KWP', cast=float)

    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}"
    
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    
    hourly_watts = _check_and_fetch_api_data(url, kwp)
    
    # 1. Versuch: API- / Cache-Daten mappen
    if hourly_watts:
        pv_vector, success = _map_hourly_data_to_vector(hourly_watts, target_hours)
        if success:
            # NEU: Auch die erfolgreichen API-Daten werden nun getuned
            return _apply_tuning_factor(pv_vector)
        print("⚠️ API-/Cache-Daten empfangen, aber keine passenden Zeitstempel für die nächsten 24h gefunden. Nutze Fallback.")

    # 2. Versuch (Fallback): Saisonaler Vektor generieren
    pv_vector = _generate_seasonal_fallback(target_hours, kwp)
    return _apply_tuning_factor(pv_vector)


if __name__ == "__main__":
    # Schneller Integrationstest
    print("Starte Testabruf PV-Forecast...")
    res = get_hourly_pv_forecast()
    print(f"Vektor-Länge: {len(res)} Elemente.")
    print(f"Vektor-Werte (nächste 24h ab jetzt): {res}")