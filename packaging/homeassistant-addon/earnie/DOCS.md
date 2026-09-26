# Earnie — Home Assistant Add-on

Energiemanagement und Optimierung für Smart Homes, betrieben als Supervisor-Add-on (primär für **Home Assistant Green** / HA OS, `aarch64`; `amd64` zusätzlich für Dev-/Test-VMs).

Dieses Add-on ist ein dünner Wrapper um das bestehende, produktiv genutzte Earnie-Image (`ghcr.io/jochentcc/earnie-energy`) — dieselbe Anwendung wie in den Docker-Compose-Stacks (Synology, LoxBerry, Proxmox), nur verpackt für den HA Supervisor.

## Installation

1. **Einstellungen → Apps** → ⋮ → **Repositories** → `https://github.com/JochenTCC/ha-addon-earnie` hinzufügen.
2. **Earnie** in der Liste öffnen → **Installieren**.
3. Optional: Optionen ausfüllen (siehe unten) → **Start**.
4. Web-UI über die **HA-Seitenleiste** (Ingress) oder den Button **OPEN WEB UI** auf der Add-on-Seite — **ohne** Host-Port `:8501` / IP-Lookup.
   Optional (Fortgeschritten): direkter LAN-Zugriff `http://<home-assistant-ip>:8501` (nginx → Streamlit).

**Nach dem Start ca. 20–40 Sekunden warten**, bis Streamlit bereit ist. Öffnest du die UI zu früh, zeigt Ingress oft **„Bad Gateway / 502“** oder eine kurze Hinweis-Seite „Earnie startet noch“ — das ist normal. Seite nach wenigen Sekunden neu laden.

## Konfiguration

Alle Optionen sind **optional**. Wer nichts einträgt, konfiguriert Earnie weiterhin dateibasiert unter `/data/earnie_env/config` (Samba-/SSH-Add-on).

Beim **ersten Start** legt Earnie `config.json` an und setzt im Add-on-Kontext automatisch `ehal.backend=ha` (leere URL/Token → Supervisor-Proxy). Port-Optionen werden bei jedem Start in `config.json` geschrieben (`ui.streamlit_port`, `system.ehal_loxone_http_port`).

| Option | Beschreibung | Standard |
|---|---|---|
| `streamlit_port` | In `config.json` `ui.streamlit_port` (Host/UI-Port `8501`); Streamlit lauscht im Add-on intern auf `8502` hinter nginx | `8501` |
| `ehal_loxone_http_port` | `EARNIE_EHAL_LOXONE_HTTP_PORT` und `config.json` `system.ehal_loxone_http_port` | `8541` |
| `ui_modes` | Aktive UI-Modi, kommagetrennt | `sunset2sunset,scenario_explorer,live_environment` |
| `auto_start_main` | Startet `main.py` automatisch mit dem Add-on | `true` |
| `timezone` | Zeitzone (`TZ`) | `Europe/Vienna` |

Loxone- und HA-Zugangsdaten gehören in die Earnie-Oberfläche (**Smarthome-Backend**) bzw. in `config/.env` — nicht in die Supervisor-Optionen.

Mit `homeassistant_api: true` spricht Earnie die Core-API über `http://supervisor/core` und `SUPERVISOR_TOKEN` an (kein manuelles Long-Lived Access Token).

## Ports

| Port | Zweck |
|---|---|
| Ingress (`ingress_port` 8501) | Primäre Web-UI in der HA-Oberfläche (nginx → Streamlit `:8502`) |
| `8501/tcp` | Optionaler Direktzugriff (derselbe nginx) |
| `8541/tcp` | EHAL Loxone-HTTP — nur bei `ehal.backend=loxone` |

## Persistenz

Config und Laufzeitdaten liegen unter `/data/earnie_env/` (`EARNIE_ENV_PATH`) — übersteht Neustarts, Updates und Supervisor-Backups.

## Verhältnis zum EHAL-HA-Adapter

Dieses Add-on lässt Earnie **innerhalb** von Home Assistant laufen. Der EHAL-HA-Adapter (`ehal.backend=ha`) nutzt im Add-on bevorzugt den Supervisor-Proxy.

## Einschränkungen (Feature-Stufe 0.2)

Die Add-on-`version:` folgt der Earnie-App (z. B. `2.6.0-alpha.1`). „0.2“ meint hier den ausgelieferten Options-/Ingress-Umfang, nicht die SemVer-Nummer.

- Add-on-Optionen decken nur gängige Werte ab; volle Haus-/Entity-Konfiguration bleibt in-App / dateibasiert.
- Keine MQTT Discovery / native HA-Entitäten / Energy-Dashboard-Integration (Add-on **1.0** → Earnie-Backlog **Version 2.+1**, nicht Teil von 2.6).

Ausführliche Anwenderdokumentation: [`docs/einrichtung/homeassistant-addon.md`](https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/homeassistant-addon.md) im Hauptrepo.
