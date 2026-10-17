# awattar_client.py
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
import config
from data.market_prices import awattar_fetch_window, normalize_price_slot

def _fetch_awattar_payload(feed_key: str, start_ms: int, end_ms: int) -> Any:
    """Raw aWATTar JSON (or text) via the shadow-aware transport."""
    from runtime_store.shadow.mode import is_shadow_mode
    from runtime_store.shadow.replay import replay_ext_payload
    from runtime_store.shadow.transport import ext_get, safe_record

    def _live() -> Any:
        response = requests.get(
            config.get('AWATTAR_URL'),
            params={'start': start_ms, 'end': end_ms},
            timeout=config.get_global_timeout(),
        )
        try:
            data = response.json()
        except ValueError:
            data = response.text
        # Family B: Shadow fallback must not record; Prod records.
        if is_shadow_mode():
            response.raise_for_status()
            return data
        if response.status_code >= 400:
            safe_record(
                feed_key,
                ok=False,
                status=int(response.status_code),
                payload=data,
                error=f"HTTP {response.status_code}",
            )
            response.raise_for_status()
        safe_record(
            feed_key, ok=True, payload=data, status=int(response.status_code)
        )
        return data

    return ext_get(
        replay=lambda: replay_ext_payload(feed_key),
        live=_live,
        allow_live_fallback=True,
    )


def _parse_awattar_payload(data: Any) -> Optional[List[Dict[str, Any]]]:
    """Convert the aWATTar payload to sorted price slots; None on unexpected structure."""
    # Validierung der API-Struktur
    if not isinstance(data, dict) or 'data' not in data:
        print("🚨 Fehler: Unerwartete API-Struktur von Awattar (Key 'data' fehlt).")
        return None

    planning_tz = ZoneInfo(config.get_planning_timezone())
    prices: List[Dict[str, Any]] = []
    for entry in data['data']:
        # Absicherung gegen fehlerhafte Felder im JSON
        if 'start_timestamp' not in entry or 'marketprice' not in entry:
            continue

        dt = normalize_price_slot(
            datetime.fromtimestamp(entry['start_timestamp'] / 1000, tz=planning_tz)
        )

        # Umrechnung von EUR/MWh in Cent/kWh: (X / 10)
        price_cent = entry['marketprice'] / 10

        prices.append({
            "timestamp": dt,
            "hour": dt.hour,
            "price_buy": round(price_cent, 2)
        })

    prices.sort(key=lambda item: item["timestamp"])
    return prices


def fetch_awattar_prices(
    planning_end: datetime | None = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Holt die aktuellen Marktpreise von Awattar.

    planning_end: optionales Ende des Planungshorizonts (z. B. zweiter Sonnenuntergang).
    """
    feed_key = "ext:prices:awattar"
    try:
        start, end = awattar_fetch_window(planning_end)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int((end + timedelta(hours=1)).timestamp() * 1000)
        data = _fetch_awattar_payload(feed_key, start_ms, end_ms)
        return _parse_awattar_payload(data)

    except requests.exceptions.Timeout:
        print(f"🚨 Timeout beim Abrufen der Awattar-Preise ({config.get_global_timeout()}s überschritten).")
        from runtime_store.shadow.transport import safe_record

        safe_record(feed_key, ok=False, error="timeout")
        return None
    except requests.exceptions.HTTPError as http_err:
        print(f"🚨 HTTP-Fehler beim Abrufen der Awattar-Preise: {http_err}")
        from runtime_store.shadow.transport import safe_record

        safe_record(feed_key, ok=False, error=str(http_err))
        return None
    except Exception as e:
        print(f"🚨 Unvorhergesehener Fehler im awattar_client: {e}")
        from runtime_store.shadow.transport import safe_record

        safe_record(feed_key, ok=False, error=str(e))
        return None


if __name__ == "__main__":
    # Schneller Integrationstest bei direkter Ausführung
    print("Starte Testabruf aWATTar...")
    res = fetch_awattar_prices()
    if res:
        print(f"Erfolgreich {len(res)} Preispunkte geladen.")
        print(f"Erster Datenpunkt: {res[0]}")
    else:
        print("Testabruf fehlgeschlagen.")
