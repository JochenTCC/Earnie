# pv_forecast.py
import requests
from datetime import datetime, timedelta
from typing import List, Optional
import config

# =========================================================================
# GLOBALE CACHE-VARIABLEN (Für Rate-Limiting & API-Schonung)
# =========================================================================
_LAST_API_CALL: Optional[datetime] = None
_CACHED_HOURLY_WATTS_BY_URL: dict[str, dict] = {}
_RATE_LIMIT_RETRY_AT: Optional[datetime] = None
_LAST_FETCH_SOURCE: str = "api"
_USING_SYNTHETIC_FALLBACK: bool = False


def _as_naive_local(value: datetime) -> datetime:
    """Normalize aware API timestamps for comparison with ``datetime.now()``."""
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _parse_retry_at(response: requests.Response) -> Optional[datetime]:
    """Liest Retry-At aus Header oder JSON-Body einer 429-Antwort."""
    header_value = response.headers.get("X-Ratelimit-Retry-At")
    if header_value:
        try:
            return _as_naive_local(datetime.fromisoformat(header_value.strip()))
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
        return _as_naive_local(datetime.fromisoformat(str(retry_at).strip()))
    except ValueError:
        return None


def get_api_status() -> dict:
    """Snapshot des letzten forecast.solar-Abrufs für Logging/Diagnose."""
    retry_at = _RATE_LIMIT_RETRY_AT
    return {
        "retry_at": retry_at.isoformat() if retry_at else None,
        "source": _LAST_FETCH_SOURCE,
        "cache_available": bool(_CACHED_HOURLY_WATTS_BY_URL),
        "using_synthetic_fallback": _USING_SYNTHETIC_FALLBACK,
    }


def _set_fetch_source(source: str) -> None:
    global _LAST_FETCH_SOURCE
    _LAST_FETCH_SOURCE = source


def _return_cached_or_none(
    cached: Optional[dict],
    *,
    reason: str,
    empty_source: str = "error_no_cache",
) -> Optional[dict]:
    """Bei Abruf-Fehler Cache behalten (kein saisonaler Fallback trotz Warm-Cache)."""
    if cached:
        _set_fetch_source("cache_after_error")
        print(
            f"[cache] forecast.solar {reason} — nutze letzten erfolgreichen Cache "
            f"({len(cached)} Zeitstempel)."
        )
        return cached
    _set_fetch_source(empty_source)
    print(f"[FEHLER] forecast.solar {reason} — kein Cache, späterer Fallback.")
    return None


def _pre_fetch_cached_or_none(
    now_time: datetime,
    cached: Optional[dict],
) -> tuple[bool, Optional[dict]]:
    """Rate-limit / 15-min cooldown. Returns (should_return, value)."""
    global _RATE_LIMIT_RETRY_AT

    now_cmp = _as_naive_local(now_time)
    retry_at = _RATE_LIMIT_RETRY_AT
    if retry_at is not None:
        retry_at = _as_naive_local(retry_at)
        _RATE_LIMIT_RETRY_AT = retry_at

    if retry_at and now_cmp < retry_at:
        _set_fetch_source("rate_limited")
        print(
            f"[cache] forecast.solar Rate-Limit aktiv bis "
            f"{retry_at.isoformat()}. Nutze lokalen Cache."
        )
        return True, cached

    if retry_at and now_cmp >= retry_at:
        _RATE_LIMIT_RETRY_AT = None

    if _LAST_API_CALL and (now_cmp - _as_naive_local(_LAST_API_CALL)) < timedelta(
        minutes=15
    ):
        if cached is not None:
            _set_fetch_source("cache")
            print(
                "[cache] forecast.solar-Schutz: Letzter API-Aufruf vor weniger als 15 min. "
                "Nutze lokalen Cache."
            )
            return True, cached
    return False, None


def _store_hourly_watts_from_response(
    url: str,
    response: requests.Response,
    cached: Optional[dict],
    now_time: datetime,
) -> Optional[dict]:
    """Parse API response, update URL cache on success, else fall back to cache."""
    global _LAST_API_CALL, _RATE_LIMIT_RETRY_AT

    feed_key = f"ext:pv_forecast:{_shadow_url_hash(url)}"
    if response.status_code == 429:
        retry_at = _parse_retry_at(response)
        if retry_at:
            _RATE_LIMIT_RETRY_AT = retry_at
        retry_msg = retry_at.isoformat() if retry_at else "unbekannt"
        print(
            f"[FEHLER] forecast.solar Rate-Limit (HTTP 429). "
            f"Nächster API-Aufruf erlaubt ab {retry_msg}."
        )
        _shadow_ext_record(
            feed_key,
            ok=False,
            status=429,
            payload=_safe_body(response),
            error="rate_limited",
        )
        return _return_cached_or_none(
            cached, reason="HTTP 429", empty_source="rate_limited"
        )

    try:
        data = response.json()
    except ValueError:
        data = response.text
    if response.status_code >= 400:
        _shadow_ext_record(
            feed_key,
            ok=False,
            status=int(response.status_code),
            payload=data,
            error=f"HTTP {response.status_code}",
        )
        response.raise_for_status()
    _shadow_ext_record(
        feed_key, ok=True, payload=data, status=int(response.status_code)
    )
    hourly_watts = data.get("result", {}).get("watts", {}) if isinstance(data, dict) else {}
    if not hourly_watts:
        print("[FEHLER] forecast.solar: leeres watts-Ergebnis.")
        return _return_cached_or_none(cached, reason="leeres watts")
    _CACHED_HOURLY_WATTS_BY_URL[url] = hourly_watts
    _LAST_API_CALL = now_time
    _RATE_LIMIT_RETRY_AT = None
    _set_fetch_source("api")
    return hourly_watts


def _record_fetch_failure_and_cache(
    url: str,
    cached: Optional[dict],
    *,
    error: str,
    reason: str,
    log_message: str,
    empty_source: str = "error_no_cache",
) -> Optional[dict]:
    print(log_message)
    _shadow_ext_record(
        f"ext:pv_forecast:{_shadow_url_hash(url)}",
        ok=False,
        error=error,
    )
    return _return_cached_or_none(cached, reason=reason, empty_source=empty_source)


def _check_and_fetch_api_data(url: str, kwp: float) -> Optional[dict]:
    """Prüft Cache-Gültigkeit und holt ggf. neue API-Daten (Cache pro URL)."""
    now_time = datetime.now()
    cached = _CACHED_HOURLY_WATTS_BY_URL.get(url)
    should_return, early = _pre_fetch_cached_or_none(now_time, cached)
    if should_return:
        return early

    try:
        response = requests.get(url, timeout=config.get_global_timeout())
        return _store_hourly_watts_from_response(url, response, cached, now_time)
    except requests.exceptions.Timeout:
        return _record_fetch_failure_and_cache(
            url,
            cached,
            error="timeout",
            reason="Timeout",
            log_message=(
                f"[FEHLER] Timeout beim PV-Forecast "
                f"({config.get_global_timeout()}s überschritten)."
            ),
        )
    except requests.exceptions.HTTPError as http_err:
        return _record_fetch_failure_and_cache(
            url,
            cached,
            error=str(http_err),
            reason=f"HTTPError:{http_err}",
            log_message=f"[FEHLER] HTTP-Fehler beim PV-Forecast-Abruf: {http_err}.",
        )
    except Exception as e:
        return _record_fetch_failure_and_cache(
            url,
            cached,
            error=str(e),
            reason=f"Exception:{e}",
            log_message=f"[FEHLER] Unerwarteter Fehler beim PV-Forecast: {e}.",
        )


def _shadow_url_hash(url: str) -> str:
    from runtime_store.shadow.feed import url_hash

    return url_hash(url)


def _safe_body(response) -> object:
    try:
        return response.json()
    except ValueError:
        return getattr(response, "text", None)


def _shadow_ext_record(
    key: str,
    *,
    ok: bool,
    payload: object = None,
    status: int | None = None,
    error: str | None = None,
) -> None:
    try:
        from runtime_store.shadow.hooks import record_transport

        record_transport(key, ok=ok, payload=payload, status=status, error=error)
    except Exception:  # noqa: BLE001
        pass


def _map_hourly_data_to_vector(hourly_watts: dict, target_hours: list) -> tuple[list, bool]:
    """Map API hourly watts onto target slots (QH inherits parent clock hour)."""
    from optimizer.slot_duration import floor_to_hour_slot

    pv_vector = [0.0] * len(target_hours)
    success_count = 0

    for idx, target_dt in enumerate(target_hours):
        key_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        if key_str not in hourly_watts:
            parent = floor_to_hour_slot(target_dt)
            key_str = parent.strftime("%Y-%m-%d %H:%M:%S")
        if key_str in hourly_watts:
            watts = hourly_watts[key_str]
            pv_vector[idx] = round(watts / 1000.0, 3)
            success_count += 1

    if success_count > 0:
        print(
            f"[OK] PV-Ertragsprognose erfolgreich bereitgestellt "
            f"({success_count}/{len(target_hours)} Slots gemappt. Max: {max(pv_vector)} kW)."
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


def _forecast_one_system(
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    kwp: float,
    target_hours: list,
) -> tuple[list[float], bool]:
    """Returns (vector, used_api). used_api False means seasonal fallback."""
    if kwp <= 0.0:
        return [0.0] * len(target_hours), True

    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}"
    hourly_watts = _check_and_fetch_api_data(url, kwp)
    if hourly_watts:
        pv_vector, success = _map_hourly_data_to_vector(hourly_watts, target_hours)
        if success:
            return pv_vector, True
        print(
            "[WARN] API-/Cache-Daten empfangen, aber keine passenden Zeitstempel für "
            f"die {len(target_hours)} Zielstunden gefunden. Nutze Fallback."
        )
    return _generate_seasonal_fallback(target_hours, kwp), False


def _sum_vectors(vectors: list[list[float]], length: int) -> list[float]:
    total = [0.0] * length
    for vector in vectors:
        for idx, value in enumerate(vector):
            total[idx] = round(total[idx] + float(value), 3)
    return total


def get_hourly_pv_forecast_for_hours(target_hours: list) -> List[float]:
    """
    PV-Prognose (kW) für die übergebenen Stunden-Slots.
    Summiert forecast.solar-Abrufe über alle Live-Szenario-PV-Anlagen.
    """
    global _USING_SYNTHETIC_FALLBACK

    if not target_hours:
        raise ValueError("get_hourly_pv_forecast_for_hours erfordert mindestens eine Zielstunde.")

    lat = float(config.get("LATITUDE", cast=float))
    lon = float(config.get("LONGITUDE", cast=float))
    systems = config.get_planning_pv_systems()
    if not systems:
        kwp = float(config.get("PV_KWP", cast=float) or 0.0)
        if kwp <= 0.0:
            _USING_SYNTHETIC_FALLBACK = False
            return [0.0] * len(target_hours)
        systems = [
            {
                "id": "pv",
                "label": "PV",
                "pv_kwp": kwp,
                "pv_tilt": float(config.get("PV_TILT", cast=float) or 0.0),
                "pv_azimuth": float(config.get("PV_AZIMUTH", cast=float) or 0.0),
            }
        ]

    vectors: list[list[float]] = []
    any_fallback = False
    for system in systems:
        vector, used_api = _forecast_one_system(
            lat=lat,
            lon=lon,
            tilt=float(system.get("pv_tilt", 0.0) or 0.0),
            azimuth=float(system.get("pv_azimuth", 0.0) or 0.0),
            kwp=float(system.get("pv_kwp", 0.0) or 0.0),
            target_hours=target_hours,
        )
        vectors.append(vector)
        if not used_api:
            any_fallback = True

    _USING_SYNTHETIC_FALLBACK = any_fallback
    pv_vector = _sum_vectors(vectors, len(target_hours))
    if any_fallback:
        print(
            f"[info] Synthetischer PV-Fallback (teilweise/gesamt) — "
            f"Summen-Max: {max(pv_vector):.2f} kW über {len(systems)} Anlage(n)."
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
