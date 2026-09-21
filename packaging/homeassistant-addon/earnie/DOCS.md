# Earnie — Home Assistant Add-on

Energiemanagement und Optimierung für Smart Homes, betrieben als Supervisor-Add-on (primär für **Home Assistant Green** / HA OS, `aarch64`; `amd64` zusätzlich für Dev-/Test-VMs).

Dieses Add-on ist ein dünner Wrapper um das bestehende, produktiv genutzte Earnie-Image (`ghcr.io/jochentcc/earnie-energy`) — dieselbe Anwendung wie in den Docker-Compose-Stacks (Synology, LoxBerry, Proxmox), nur verpackt für den HA Supervisor.

## Installation

1. **Einstellungen → Apps** → ⋮ → **Repositories** → `https://github.com/JochenTCC/ha-addon-earnie` hinzufügen.
2. **Earnie** in der Liste öffnen → **Installieren**.
3. Optional: Optionen ausfüllen (siehe unten) → **Start**.
4. Web-UI über die **HA-Seitenleiste** (Ingress) oder den Button **OPEN WEB UI** auf der Add-on-Seite — **ohne** Host-Port `:8501` / IP-Lookup.
   Optional (Fortgeschritten): direkter LAN-Zugriff `http://<home-assistant-ip>:8501`.

**Erwarte nach dem Start ca. 30 Sekunden**, bis Streamlit erreichbar ist.

## Konfiguration

Alle Optionen sind **optional**. Wer nichts einträgt, konfiguriert Earnie weiterhin dateibasiert unter `/data/earnie_env/config` (Samba-/SSH-Add-on).

Beim **ersten Start** legt Earnie `config.json` an und setzt im Add-on-Kontext automatisch `ehal.backend=ha` (leere URL/Token → Supervisor-Proxy). Port-Optionen werden bei jedem Start in `config.json` geschrieben (`ui.streamlit_port`, `system.ehal_loxone_http_port`).

| Option | Beschreibung | Standard |
|---|---|---|
| `streamlit_port` | Streamlit-Port (Env + `config.json` `ui.streamlit_port`) | `8501` |
| `ehal_loxone_http_port` | EHAL-Loxone-HTTP-Port → `config.json` `system.ehal_loxone_http_port` | `8541` |
| `ui_modes` | Aktive UI-Modi, kommagetrennt | `sunset2sunset,scenario_explorer,live_environment` |
| `auto_start_main` | Startet `main.py` automatisch mit dem Add-on | `true` |
| `timezone` | Zeitzone (`TZ`) | `Europe/Vienna` |

Loxone-Zugangsdaten gehören in die Earnie-Oberfläche (**Smarthome-Backend**) bzw. in `config.json` — nicht in die Supervisor-Optionen.

Mit `homeassistant_api: true` spricht Earnie die Core-API über `http://supervisor/core` und `SUPERVISOR_TOKEN` an (kein manuelles Long-Lived Access Token).

## Ports

| Port | Zweck |
|---|---|
| Ingress (`ingress_port` 8501) | Primäre Web-UI in der HA-Oberfläche |
| `8501/tcp` | Optionaler Direktzugriff (LAN) |
| `8541/tcp` | EHAL Loxone-HTTP — nur bei `ehal.backend=loxone` |

## Persistenz

Config und Laufzeitdaten liegen unter `/data/earnie_env/` (`EARNIE_ENV_PATH`) — übersteht Neustarts, Updates und Supervisor-Backups.

## Verhältnis zum EHAL-HA-Adapter

Dieses Add-on lässt Earnie **innerhalb** von Home Assistant laufen. Der EHAL-HA-Adapter (`ehal.backend=ha`) nutzt im Add-on bevorzugt den Supervisor-Proxy.

## Einschränkungen (Version 0.2)

- Add-on-Optionen decken nur gängige Werte ab; volle Haus-/Entity-Konfiguration bleibt in-App / dateibasiert.
- Keine MQTT Discovery / native HA-Entitäten / Energy-Dashboard-Integration (geplant für Version 1.0).

Ausführliche Anwenderdokumentation: [`docs/einrichtung/homeassistant-addon.md`](https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/homeassistant-addon.md) im Hauptrepo.
