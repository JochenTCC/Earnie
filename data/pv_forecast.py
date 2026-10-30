# pv_forecast.py
"""PV forecast per PV system: forecast.solar, else Open-Meteo tilted irradiance.

Order per system: forecast.solar (API, in-memory cache, disk cache across restarts,
Shadow: Prod feed) → Open-Meteo ``global_tilted_irradiance`` for the system's tilt and
azimuth → :class:`PvForecastUnavailableError` (the cycle aborts; no invented curve).
"""
import json
import os
import requests
from datetime import datetime, timedelta
from typing import List, Optional
import config
from runtime_store.cycle_duration_stats import (
    EVENT_PV_FORECAST_FETCH,
    record_event as record_cycle_event,
)
from runtime_store.persist_paths import runtime_path
from runtime_store.planning_clock import planning_now

SOURCE_FORECAST_SOLAR = "forecast_solar"
SOURCE_OPEN_METEO = "open_meteo"
SOURCE_NONE = "none"

# Prod records the forecast.solar feed only on a real API call (15-min guard, longer under
# a rate limit); the Shadow default of 120 s would discard it between two calls.
SHADOW_FEED_MAX_AGE_SEC = 3 * 3600
DISK_CACHE_FILENAME = "pv_forecast_cache.json"
DISK_CACHE_MAX_AGE = timedelta(hours=6)

# =========================================================================
# GLOBALE CACHE-VARIABLEN (Für Rate-Limiting & API-Schonung)
# =========================================================================
# Per URL (one per PV system): a shared stamp let the first fetched system starve the others.
_LAST_API_CALL_BY_URL: dict[str, datetime] = {}
_CACHED_HOURLY_WATTS_BY_URL: dict[str, dict] = {}
_DISK_CACHE_CHECKED_URLS: set[str] = set()
_RATE_LIMIT_RETRY_AT: Optional[datetime] = None
_LAST_FETCH_SOURCE: str = "api"
_SOURCE_BY_SYSTEM: dict[str, str] = {}


class PvForecastUnavailableError(RuntimeError):
    """Neither forecast.solar nor Open-Meteo delivered a forecast for a PV system."""


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
        "source_by_system": dict(_SOURCE_BY_SYSTEM),
        "open_meteo_systems": sorted(
            sid for sid, src in _SOURCE_BY_SYSTEM.items() if src == SOURCE_OPEN_METEO
        ),
    }


def _disk_cache_path() -> str:
    return runtime_path(DISK_CACHE_FILENAME)


def _read_disk_cache_file() -> dict:
    path = _disk_cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"[WARN] PV-Prognose-Cache {path} nicht lesbar ({exc}) — wird ignoriert.")
        return {}
    return data if isinstance(data, dict) else {}


def _save_disk_cache(url: str, hourly_watts: dict, fetched_at: datetime) -> None:
    """Persist the last successful forecast.solar answer per URL (survives restarts)."""
    data = _read_disk_cache_file()
    data[url] = {"fetched_at": fetched_at.isoformat(), "watts": hourly_watts}
    path = _disk_cache_path()
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"[WARN] PV-Prognose-Cache {path} nicht schreibbar ({exc}).")


def _load_disk_cache(url: str, now_time: datetime) -> Optional[dict]:
    """Disk entry for *url* if at most ``DISK_CACHE_MAX_AGE`` old; seeds the API guard."""
    entry = _read_disk_cache_file().get(url)
    if not isinstance(entry, dict):
        return None
    watts = entry.get("watts")
    try:
        fetched_at = datetime.fromisoformat(str(entry.get("fetched_at")))
    except ValueError:
        return None
    if not isinstance(watts, dict) or not watts:
        return None
    age = _as_naive_local(now_time) - _as_naive_local(fetched_at)
    if age > DISK_CACHE_MAX_AGE:
        print(
            f"[info] PV-Prognose-Cache auf der Festplatte zu alt "
            f"({age.total_seconds() / 3600:.1f} h) — wird nicht genutzt."
        )
        return None
    _CACHED_HOURLY_WATTS_BY_URL[url] = watts
    _LAST_API_CALL_BY_URL[url] = _as_naive_local(fetched_at)
    print(
        f"[cache] forecast.solar-Cache von der Festplatte geladen "
        f"(Abruf {fetched_at.isoformat()}, {len(watts)} Zeitstempel)."
    )
    return watts


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
    url: str,
    now_time: datetime,
    cached: Optional[dict],
) -> tuple[bool, Optional[dict]]:
    """Rate-limit (per IP) / 15-min cooldown (per URL). Returns (should_return, value)."""
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

    last_call = _LAST_API_CALL_BY_URL.get(url)
    if last_call and (now_cmp - _as_naive_local(last_call)) < timedelta(minutes=15):
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
    global _RATE_LIMIT_RETRY_AT

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
    _LAST_API_CALL_BY_URL[url] = now_time
    _RATE_LIMIT_RETRY_AT = None
    _set_fetch_source("api")
    _save_disk_cache(url, hourly_watts, now_time)
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

    from runtime_store.shadow.mode import is_shadow_mode
    from runtime_store.shadow.replay import replay_ext_payload
    from runtime_store.shadow.transport import ext_get

    cached = _CACHED_HOURLY_WATTS_BY_URL.get(url)
    # Prod only: Shadow reads the Prod feed and must not seed Prod's API guard.
    if cached is None and not is_shadow_mode() and url not in _DISK_CACHE_CHECKED_URLS:
        _DISK_CACHE_CHECKED_URLS.add(url)
        cached = _load_disk_cache(url, now_time)

    feed_key = f"ext:pv_forecast:{_shadow_url_hash(url)}"

    def _replay() -> dict | None:
        # Never call forecast.solar from Shadow (shared IP rate limit with Prod).
        data = replay_ext_payload(feed_key, max_age_s=SHADOW_FEED_MAX_AGE_SEC)
        if isinstance(data, dict):
            hourly_watts = data.get("result", {}).get("watts", {})
            if hourly_watts:
                return hourly_watts
        return None

    def _live() -> Optional[dict]:
        should_return, early = _pre_fetch_cached_or_none(url, now_time, cached)
        if should_return:
            return early
        record_cycle_event(EVENT_PV_FORECAST_FETCH)
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

    hit = ext_get(replay=_replay, live=_live, allow_live_fallback=False)
    if is_shadow_mode():
        if hit is not None:
            _CACHED_HOURLY_WATTS_BY_URL[url] = hit
            _set_fetch_source("shadow_feed")
            return hit
        if cached is not None:
            _set_fetch_source("cache")
            return cached
        _set_fetch_source("shadow_missing")
        return None
    return hit


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
    from runtime_store.shadow.transport import safe_record

    safe_record(key, ok=ok, payload=payload, status=status, error=error)


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


def _open_meteo_pv_vector(
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    kwp: float,
    target_hours: list,
) -> list[float]:
    """PV kW per target slot from Open-Meteo ``global_tilted_irradiance`` (forecast).

    Same orientation convention as forecast.solar (azimuth 0° = south, -90° = east).
    Hourly GTI is the mean of the preceding hour, so slot hour ``h`` takes the value
    stamped ``h + 1`` (as ``scripts/pv_forecast_compare.py``). kW = GTI / 1000 × kWp
    (``irradiance_wm2_to_pv_kw``, same conversion as the Open-Meteo archive path).
    """
    from data.open_meteo_solar_archive import irradiance_wm2_to_pv_kw
    from data.outdoor_forecast import get_hourly_tilted_irradiance_forecast_wm2
    from optimizer.slot_duration import floor_to_hour_slot

    start = floor_to_hour_slot(min(target_hours))
    end = floor_to_hour_slot(max(target_hours))
    wall_hours = int((end - start).total_seconds() // 3600) + 1
    wm2 = get_hourly_tilted_irradiance_forecast_wm2(
        horizon=wall_hours + 1,
        tilt_deg=tilt,
        azimuth_deg=azimuth,
        latitude=lat,
        longitude=lon,
        start=start,
    )
    kw_by_hour = {
        start + timedelta(hours=i): irradiance_wm2_to_pv_kw(wm2[i + 1], kwp)
        for i in range(wall_hours)
    }
    return [kw_by_hour[floor_to_hour_slot(dt)] for dt in target_hours]


def _forecast_one_system(
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    kwp: float,
    target_hours: list,
) -> tuple[list[float], str]:
    """Returns (vector, source); raises :class:`PvForecastUnavailableError`."""
    if kwp <= 0.0:
        return [0.0] * len(target_hours), SOURCE_NONE

    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}"
    hourly_watts = _check_and_fetch_api_data(url, kwp)
    if hourly_watts:
        pv_vector, success = _map_hourly_data_to_vector(hourly_watts, target_hours)
        if success:
            return pv_vector, SOURCE_FORECAST_SOLAR
        reason = (
            f"Daten ohne passende Zeitstempel für {len(target_hours)} Zielstunden "
            f"(Quelle {_LAST_FETCH_SOURCE})"
        )
    else:
        reason = f"keine Daten (Quelle {_LAST_FETCH_SOURCE})"

    print(
        f"[WARN] forecast.solar: {reason} — PV-Prognose für Neigung {tilt}°, "
        f"Azimut {azimuth}° aus Open-Meteo-Einstrahlung."
    )
    try:
        vector = _open_meteo_pv_vector(
            lat=lat,
            lon=lon,
            tilt=tilt,
            azimuth=azimuth,
            kwp=kwp,
            target_hours=target_hours,
        )
    except Exception as exc:
        raise PvForecastUnavailableError(
            f"Keine PV-Prognose für Anlage (Neigung {tilt}°, Azimut {azimuth}°, "
            f"{kwp} kWp): forecast.solar {reason}; Open-Meteo: {exc}"
        ) from exc
    return vector, SOURCE_OPEN_METEO


def _sum_vectors(vectors: list[list[float]], length: int) -> list[float]:
    total = [0.0] * length
    for vector in vectors:
        for idx, value in enumerate(vector):
            total[idx] = round(total[idx] + float(value), 3)
    return total


def _planning_pv_systems_for_forecast() -> list[dict]:
    systems = config.get_planning_pv_systems()
    if systems:
        return systems
    kwp = float(config.get("PV_KWP", cast=float) or 0.0)
    if kwp <= 0.0:
        return []
    return [
        {
            "id": "pv",
            "label": "PV",
            "pv_kwp": kwp,
            "pv_tilt": float(config.get("PV_TILT", cast=float) or 0.0),
            "pv_azimuth": float(config.get("PV_AZIMUTH", cast=float) or 0.0),
        }
    ]


def get_hourly_pv_forecast_by_system_for_hours(
    target_hours: list,
) -> dict[str, List[float]]:
    """Per-PV-system forecast (kW) keyed by system id (Inverter P3 pass-through).

    Raises :class:`PvForecastUnavailableError` when a system has neither
    forecast.solar nor Open-Meteo data; the source per system is in
    :func:`get_api_status` (``source_by_system``).
    """
    global _SOURCE_BY_SYSTEM

    if not target_hours:
        raise ValueError(
            "get_hourly_pv_forecast_by_system_for_hours erfordert "
            "mindestens eine Zielstunde."
        )

    _SOURCE_BY_SYSTEM = {}
    systems = _planning_pv_systems_for_forecast()
    if not systems:
        return {}

    lat = float(config.get("LATITUDE", cast=float))
    lon = float(config.get("LONGITUDE", cast=float))
    by_system: dict[str, List[float]] = {}
    sources: dict[str, str] = {}
    for system in systems:
        sid = str(system.get("id") or "").strip() or "pv"
        vector, source = _forecast_one_system(
            lat=lat,
            lon=lon,
            tilt=float(system.get("pv_tilt", 0.0) or 0.0),
            azimuth=float(system.get("pv_azimuth", 0.0) or 0.0),
            kwp=float(system.get("pv_kwp", 0.0) or 0.0),
            target_hours=target_hours,
        )
        by_system[sid] = vector
        sources[sid] = source

    _SOURCE_BY_SYSTEM = sources
    substituted = sorted(sid for sid, src in sources.items() if src == SOURCE_OPEN_METEO)
    if substituted:
        print(
            f"[WARN] PV-Prognose aus Open-Meteo statt forecast.solar für "
            f"{', '.join(substituted)} ({len(substituted)}/{len(systems)} Anlage(n))."
        )
    return by_system


def sum_pv_forecast_by_system(
    by_system: dict[str, List[float]],
    length: int,
) -> List[float]:
    """Sum per-system PV series into one plant vector (kW)."""
    if length < 0:
        raise ValueError("sum_pv_forecast_by_system: length muss ≥ 0 sein.")
    if not by_system:
        return [0.0] * length
    return _sum_vectors(list(by_system.values()), length)


def get_hourly_pv_forecast_for_hours(target_hours: list) -> List[float]:
    """
    PV-Prognose (kW) für die übergebenen Stunden-Slots.
    Summiert forecast.solar-Abrufe über alle Live-Szenario-PV-Anlagen.
    """
    if not target_hours:
        raise ValueError("get_hourly_pv_forecast_for_hours erfordert mindestens eine Zielstunde.")

    by_system = get_hourly_pv_forecast_by_system_for_hours(target_hours)
    return sum_pv_forecast_by_system(by_system, len(target_hours))


def get_hourly_pv_forecast() -> List[float]:
    """
    Holt die stündliche PV-Prognose für die nächsten 24 Stunden (ab der aktuellen Stunde).
    Schützt die forecast.solar API durch ein integriertes 15-Minuten-Caching.
    """
    now = planning_now().replace(minute=0, second=0, microsecond=0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    return get_hourly_pv_forecast_for_hours(target_hours)


if __name__ == "__main__":
    # Schneller Integrationstest
    print("Starte Testabruf PV-Forecast...")
    res = get_hourly_pv_forecast()
    print(f"Vektor-Länge: {len(res)} Elemente.")
    print(f"Vektor-Werte (nächste 24h ab jetzt): {res}")
