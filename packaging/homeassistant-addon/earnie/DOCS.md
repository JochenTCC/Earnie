# Earnie — Home Assistant Add-on

Energiemanagement und Optimierung für Smart Homes, betrieben als Supervisor-Add-on (primär für **Home Assistant Green** / HA OS, `aarch64`; `amd64` zusätzlich für Dev-/Test-VMs).

Dieses Add-on ist ein dünner Wrapper um das bestehende, produktiv genutzte Earnie-Image (`ghcr.io/jochentcc/earnie-energy`) — dieselbe Anwendung wie in den Docker-Compose-Stacks (Synology, LoxBerry, Proxmox), nur verpackt für den HA Supervisor.

## Installation

1. **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories** → `https://github.com/JochenTCC/ha-addon-earnie` hinzufügen.
2. **Earnie** in der Liste öffnen → **Installieren**.
3. Optional: Optionen ausfüllen (siehe unten) → **Start**.
4. Web-UI über den Button **OPEN WEB UI** auf der Add-on-Seite, oder direkt `http://<home-assistant>:8501`.

## Konfiguration

Alle Optionen sind **optional**. Wer nichts einträgt, konfiguriert Earnie stattdessen dateibasiert wie gewohnt: `config.json` und Sidecars direkt unter `/data/earnie_env/config` im Add-on-Datenverzeichnis pflegen (per Samba-/SSH-Add-on erreichbar).

| Option | Beschreibung | Standard |
|---|---|---|
| `loxone_user` | Benutzername für die Loxone Miniserver-Anbindung (`ehal.backend=loxone`) | leer |
| `loxone_pass` | Passwort dazu (verschlüsselt im Optionen-UI dargestellt) | leer |
| `loxone_ip` | IP/Hostname des Loxone Miniservers | leer |
| `streamlit_port` | Interner Streamlit-Port | `8501` |
| `ehal_loxone_http_port` | Reserviert für den EHAL-Loxone-HTTP-Daemon (aktuell noch ohne Env-Wirkung — Port bleibt `8541`, über `config.json` `system.ehal_loxone_http_port` änderbar) | `8541` |
| `ui_modes` | Aktive UI-Modi, kommagetrennt (`sunset2sunset`, `scenario_explorer`, `live_environment`, …) | `sunset2sunset,scenario_explorer,live_environment` |
| `auto_start_main` | Startet den Optimierungsdienst (`main.py`) automatisch mit dem Add-on | `true` |
| `timezone` | Zeitzone für Planung/Anzeige | `Europe/Vienna` |

Loxone-Zugangsdaten, die hier eingetragen werden, überschreiben eine eventuell vorhandene `earnie_env/config/.env` (Env gewinnt).

## Ports

| Port | Zweck |
|---|---|
| `8501/tcp` | Earnie Web-UI (Streamlit) |
| `8541/tcp` | EHAL Loxone-HTTP (Request-Optimize, `/alive`, Pattern-B-Status) — nur relevant bei `ehal.backend=loxone` |

## Persistenz

Config und Laufzeitdaten liegen im Add-on-eigenen Datenverzeichnis unter `/data/earnie_env/` (Konvention `EARNIE_ENV_PATH`) — identisch zur Struktur `earnie_env/config` und `earnie_env/runtime` aus den anderen Deployments. Das übersteht Add-on-Neustarts, -Updates und Supervisor-Backups.

## Verhältnis zum EHAL-HA-Adapter

Dieses Add-on lässt Earnie **innerhalb** von Home Assistant laufen. Der bestehende EHAL-HA-Adapter (`ehal.backend=ha`) ist unabhängig davon und lässt Earnie stattdessen **außerhalb** von HA laufen und die HA-REST-API ansprechen — beide Betriebsarten schließen sich nicht aus.

## Einschränkungen (Version 0.1)

- Keine Ingress-Einbindung — die UI läuft auf einem eigenen Port (`8501`), nicht eingebettet in die HA-Oberfläche.
- Konfiguration über die Add-on-Optionen deckt nur die gängigsten Werte ab; volle Konfiguration bleibt dateibasiert.
- Keine MQTT Discovery / native HA-Entitäten / Energy-Dashboard-Integration (geplant für Version 1.0).

Ausführliche Anwenderdokumentation: [`docs/einrichtung/homeassistant-addon.md`](https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/homeassistant-addon.md) im Hauptrepo.
