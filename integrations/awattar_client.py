# awattar_client.py
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
import config

def fetch_awattar_prices() -> Optional[List[Dict[str, Any]]]:
    """
    Holt die aktuellen Marktpreise von Awattar.
    
    Returns:
        Optional[List[Dict[str, Any]]]: Eine Liste von Dictionaries mit Preisdaten,
                                       oder None im Fehlerfall.
    """
    try:
        # Timeout aus config setzen, um unendliches Blockieren der Schleife zu verhindern
        response = requests.get(config.get('AWATTAR_URL'), timeout=config.get_global_timeout())
        response.raise_for_status()
        data = response.json()
        
        # Validierung der API-Struktur
        if 'data' not in data:
            print("🚨 Fehler: Unerwartete API-Struktur von Awattar (Key 'data' fehlt).")
            return None
            
        prices: List[Dict[str, Any]] = []
        for entry in data['data']:
            # Absicherung gegen fehlerhafte Felder im JSON
            if 'start_timestamp' not in entry or 'marketprice' not in entry:
                continue
                
            dt = datetime.fromtimestamp(entry['start_timestamp'] / 1000)
            
            # Umrechnung von EUR/MWh in Cent/kWh: (X / 10)
            price_cent = entry['marketprice'] / 10
            
            prices.append({
                "timestamp": dt,
                "hour": dt.hour,
                "price_buy": round(price_cent, 2)
            })
            
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