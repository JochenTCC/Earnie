# pv_forecast.py
import requests
from datetime import datetime, timedelta
from typing import List, Optional
import config

# =========================================================================
# GLOBALE CACHE-VARIABLEN (Für Rate-Limiting & API-Schonung)
# =========================================================================
_LAST_API_CALL: Optional[datetime] = None
_CACHED_HOURLY_WATTS: Optional[dict] = None
_RATE_LIMIT_RETRY_AT: Optional[datetime] = None
_LAST_FETCH_SOURCE: str = "api"
_USING_SYNTHETIC_FALLBACK: bool = False


def _parse_retry_at(response: requests.Response) -> Optional[datetime]:
    """Liest Retry-At aus Header oder JSON-Body einer 429-Antwort."""
    header_value = response.headers.get("X-Ratelimit-Retry-At")
    if header_value:
        try:
            return datetime.fromisoformat(header_value.strip())
        except ValueError:
            pass

    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    message = payload.get("message") or {}
    ratelimit = message.get("ratelimit") or {}
    retry_at = ratelimit.get("retry-at")
    if not retry_at:
        return None
    try:
        return datetime.fromisoformat(str(retry_at).strip())
    except ValueError:
        return None


def get_api_status() -> dict:
    """Snapshot des letzten forecast.solar-Abrufs für Logging/Diagnose."""
    retry_at = _RATE_LIMIT_RETRY_AT
    return {
        "retry_at": retry_at.isoformat() if retry_at else None,
        "source": _LAST_FETCH_SOURCE,
        "cache_available": _CACHED_HOURLY_WATTS is not None,
        "using_synthetic_fallback": _USING_SYNTHETIC_FALLBACK,
    }


def _set_fetch_source(source: str) -> None:
    global _LAST_FETCH_SOURCE
    _LAST_FETCH_SOURCE = source


def _check_and_fetch_api_data(url: str, kwp: float) -> Optional[dict]:
    """Prüft Cache-Gültigkeit und holt ggf. neue API-Daten."""
    global _LAST_API_CALL, _CACHED_HOURLY_WATTS, _RATE_LIMIT_RETRY_AT

    now_time = datetime.now()

    if _RATE_LIMIT_RETRY_AT and now_time < _RATE_LIMIT_RETRY_AT:
        _set_fetch_source("rate_limited")
        print(
            f"[cache] forecast.solar Rate-Limit aktiv bis "
            f"{_RATE_LIMIT_RETRY_AT.isoformat()}. Nutze lokalen Cache."
        )
        return _CACHED_HOURLY_WATTS

    if _RATE_LIMIT_RETRY_AT and now_time >= _RATE_LIMIT_RETRY_AT:
        _RATE_LIMIT_RETRY_AT = None

    if _LAST_API_CALL and (now_time - _LAST_API_CALL) < timedelta(minutes=15):
        _set_fetch_source("cache")
        print(
            "[cache] forecast.solar-Schutz: Letzter API-Aufruf vor weniger als 15 min. "
            "Nutze lokalen Cache."
        )
        return _CACHED_HOURLY_WATTS

    try:
        response = requests.get(url, timeout=config.get_global_timeout())
        if response.status_code == 429:
            retry_at = _parse_retry_at(response)
            if retry_at:
                _RATE_LIMIT_RETRY_AT = retry_at
            _set_fetch_source("rate_limited")
            retry_msg = retry_at.isoformat() if retry_at else "unbekannt"
            print(
                f"[FEHLER] forecast.solar Rate-Limit (HTTP 429). "
                f"Nächster API-Aufruf erlaubt ab {retry_msg}. Nutze Fallback."
            )
            return _CACHED_HOURLY_WATTS

        response.raise_for_status()
        data = response.json()
        hourly_watts = data.get("result", {}).get("watts", {})
        _CACHED_HOURLY_WATTS = hourly_watts
        _LAST_API_CALL = now_time
        _RATE_LIMIT_RETRY_AT = None
        _set_fetch_source("api")
        return hourly_watts
    except requests.exceptions.Timeout:
        print(
            f"[FEHLER] Timeout beim PV-Forecast ({config.get_global_timeout()}s überschritten). "
            "Nutze Fallback."
        )
    except requests.exceptions.HTTPError as http_err:
        print(f"[FEHLER] HTTP-Fehler beim PV-Forecast-Abruf: {http_err}. Nutze Fallback.")
    except Exception as e:
        print(f"[FEHLER] Unerwarteter Fehler beim PV-Forecast: {e}. Nutze Fallback.")

    return None


def _map_hourly_data_to_vector(hourly_watts: dict, target_hours: list) -> tuple[list, bool]:
    """Mappt API-Daten auf die Zielstunden. Returns (pv_vector, success)."""
    pv_vector = [0.0] * len(target_hours)
    success_count = 0

    for idx, target_dt in enumerate(target_hours):
        key_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        if key_str in hourly_watts:
            watts = hourly_watts[key_str]
            pv_vector[idx] = round(watts / 1000.0, 3)
            success_count += 1

    if success_count > 0:
        print(
            f"[OK] PV-Ertragsprognose erfolgreich bereitgestellt "
            f"({success_count}/{len(target_hours)} Stunden gemappt. Max: {max(pv_vector)} kW)."
        )
        return pv_vector, True

    return pv_vector, False


def _generate_seasonal_fallback(target_hours: list, kwp: float) -> list:
    """Generiert eine saisonale Fallback-Prognose."""
    pv_vector = [0.0] * len(target_hours)
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


def get_hourly_pv_forecast_for_hours(target_hours: list) -> List[float]:
    """
    PV-Prognose (kW) für die übergebenen Stunden-Slots.
    Nutzt forecast.solar API-Daten oder saisonalen Fallback ohne Korrekturfaktor.
    """
    global _USING_SYNTHETIC_FALLBACK

    if not target_hours:
        raise ValueError("get_hourly_pv_forecast_for_hours erfordert mindestens eine Zielstunde.")

    lat = config.get("LATITUDE", cast=float)
    lon = config.get("LONGITUDE", cast=float)
    tilt = config.get("PV_TILT", cast=float)
    azimuth = config.get("PV_AZIMUTH", cast=float)
    kwp = config.get("PV_KWP", cast=float)

    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}"
    hourly_watts = _check_and_fetch_api_data(url, kwp)

    if hourly_watts:
        pv_vector, success = _map_hourly_data_to_vector(hourly_watts, target_hours)
        if success:
            _USING_SYNTHETIC_FALLBACK = False
            return pv_vector
        print(
            "[WARN] API-/Cache-Daten empfangen, aber keine passenden Zeitstempel für "
            f"die {len(target_hours)} Zielstunden gefunden. Nutze Fallback."
        )

    _USING_SYNTHETIC_FALLBACK = True
    pv_vector = _generate_seasonal_fallback(target_hours, kwp)
    print(
        f"[info] Synthetischer PV-Fallback-Vektor generiert "
        f"(Saisonaler Max-Peak: {max(pv_vector):.2f} kW)."
    )
    return pv_vector


def get_hourly_pv_forecast() -> List[float]:
    """
    Holt die stündliche PV-Prognose für die nächsten 24 Stunden (ab der aktuellen Stunde).
    Schützt die forecast.solar API durch ein integriertes 15-Minuten-Caching.
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    return get_hourly_pv_forecast_for_hours(target_hours)


if __name__ == "__main__":
    # Schneller Integrationstest
    print("Starte Testabruf PV-Forecast...")
    res = get_hourly_pv_forecast()
    print(f"Vektor-Länge: {len(res)} Elemente.")
    print(f"Vektor-Werte (nächste 24h ab jetzt): {res}")
