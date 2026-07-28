# Home Assistant + evcc (DACH-Pfad A2 / B)

Produktiver Southbound für Gerätevolumen in DACH: Earnie spricht den **HA-EHAL-Adapter** (REST) an. **evcc** läuft als Sidecar unter Home Assistant und liefert typische Wallbox-/Zähler-/WR-Entities — Earnie schreibt auf **stabile HA-Entities**, nicht parallel direkt gegen die evcc-API.

Entwickler-Setup (Compose, Token, Mapping): [HA-Lab Spec](../spec/ha-lab-setup.md).

## Pfad A2 (Default) vs Pfad B

| Pfad | Ziel | Bundle |
| --- | --- | --- |
| **A2 (DACH-Default)** | Neues oder Gateway-Setup mit dynamischen Tarifen, Wallbox/PV/Zähler | Earnie + Home Assistant + evcc (Compose) |
| **B (Installed Base)** | Bestehendes Home Assistant | Earnie + Entity-Mapping; evcc optional ergänzen |

**Nicht verwechseln:** In der Verbrauchs-CSV-Dokumentation heißen „Pfad A / Pfad B“ etwas anderes (Baseload-CSV). Hier geht es nur um die **Geräte-Anbindung**.

OpenEMS bleibt Lab-/Industrie-Prototyp (**Pfad C**), nicht B2C-Default: [OpenEMS-Lab](openems-lab.md).

## Compose starten (A2)

```powershell
mkdir ha_lab\config, ha_lab\runtime, ha_lab\homeassistant, ha_lab\evcc
# ha_lab\evcc\evcc.yaml ist im Repo als Lab-Stub; bei Bedarf anpassen
docker compose --project-directory . -f docker/compose/ha-lab.yml up -d --build
```

| Service | URL |
| --- | --- |
| Earnie Streamlit | http://localhost:8506 |
| Home Assistant | http://localhost:8123 |
| evcc UI | http://localhost:7070 |

Persistenz Earnie: `ha_lab/config/` und `ha_lab/runtime/`. HA-Konfiguration: `ha_lab/homeassistant/`.

## Entity-Mapping (Human-in-the-Loop)

1. In Home Assistant ein **Long-Lived Access Token** anlegen.
2. Snippet [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) in `config.json` übernehmen bzw. in der UI setzen.
3. Streamlit-Seite **EHAL-Com** → Expander **HA Entity → EHAL Mapping**: Entities scannen, EHAL-Felder zuweisen, speichern.
4. Optional **Telemetrie testen**. LLM-gestützte Vorschläge folgen in Version **2.5**.

## Optimizer-Exklusivität (Checkliste)

Hub-lokale Surplus-/Preis-/Lade-Strategien dürfen Earnies 48h-Fahrplan nicht überschreiben:

- [ ] In **evcc**: keine eigenständige Surplus-/Spotpreis-Ladeplanung (kein Smart Cost / konkurrierender Planner)
- [ ] Loadpoint so, dass Earnie den Maxstrom (HA-`number`-Entity) setzen kann
- [ ] Keine HA-Automationen auf denselben Setpoint-Entities, die Earnie schreibt
- [ ] Spotpreise und Fahrpläne kommen aus **Earnie**, nicht aus dem Hub

## Modbus-Regel

Pro physischem Bus bzw. Gerät genau **ein** schreibender Southbound-Owner (typisch **evcc** *oder* eine HA-Integration inkl. Proxy). Keine parallelen Modbus-Clients auf demselben Wechselrichter.

## Pfad B (bestehendes HA)

1. Earnie so betreiben, dass er die bestehende HA-URL und ein Token erreicht (Docker-Netz / Host-IP).
2. Mapping-Assistent wie oben — native HA-Entities (Long-Tail), evcc optional.
3. Dieselbe Optimizer-Exklusivitäts- und Modbus-Checkliste anwenden.

## Stop

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml down
```
