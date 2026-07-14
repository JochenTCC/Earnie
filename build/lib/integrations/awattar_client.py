# awattar_client.py
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
import config
from data.market_prices import awattar_fetch_window, normalize_price_slot

def fetch_awattar_prices(
    planning_end: datetime | None = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Holt die aktuellen Marktpreise von Awattar.

    planning_end: optionales Ende des Planungshorizonts (z. B. zweiter Sonnenuntergang).
    """
    try:
        start, end = awattar_fetch_window(planning_end)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int((end + timedelta(hours=1)).timestamp() * 1000)
        response = requests.get(
            config.get('AWATTAR_URL'),
            params={'start': start_ms, 'end': end_ms},
            timeout=config.get_global_timeout(),
        )
        response.raise_for_status()
        data = response.json()
        
        # Validierung der API-Struktur
        if 'data' not in data:
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

    except requests.exceptions.Timeout:
        print(f"🚨 Timeout beim Abrufen der Awattar-Preise ({config.get_global_timeout()}s überschritten).")
        return None
    except requests.exceptions.HTTPError as http_err:
        print(f"🚨 HTTP-Fehler beim Abrufen der Awattar-Preise: {http_err}")
        return None
    except Exception as e:
        print(f"🚨 Unvorhergesehener Fehler im awattar_client: {e}")
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