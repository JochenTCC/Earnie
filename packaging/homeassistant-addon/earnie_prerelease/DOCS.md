# Earnie — Home Assistant Add-on

Energiemanagement und Optimierung für Smart Homes, betrieben als Supervisor-Add-on (primär für **Home Assistant Green** / HA OS, `aarch64`; `amd64` zusätzlich für Dev-/Test-VMs).

**`amd64` braucht eine CPU mit x86-64-v2** (SSE4.2, POPCNT). In Proxmox-VMs den CPU-Typ auf `host` (oder `x86-64-v2-AES`) stellen – mit `kvm64`/`qemu64` bricht das Add-on beim Start mit einer entsprechenden Meldung ab. Details: [Voraussetzungen](https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/homeassistant-addon.md#voraussetzungen-gono-go).

Dieses Add-on nutzt vorgebaute Images (`ghcr.io/jochentcc/earnie-addon-{arch}`) — dieselbe Anwendung wie in den Docker-Compose-Stacks, verpackt für den HA Supervisor.

## Installation

1. **Einstellungen → Apps** → ⋮ → **Repositories** → `https://github.com/JochenTCC/ha-addon-earnie` hinzufügen.
2. **Earnie** (Stabil) oder **Earnie (Vorabversion)** öffnen → **Installieren**.
3. Optional: Optionen ausfüllen (siehe unten) → **Start**.
4. Web-UI über die **HA-Seitenleiste** (Ingress) oder **OPEN WEB UI**.

**Nach dem Start ca. 20–40 Sekunden warten.** Nie Stabil und Vorab gleichzeitig starten.

## Konfiguration

Alle Optionen sind **optional**. Dateibasierte Config unter `/config` (Samba: `/addon_configs/<hash>_earnie/`).

Beim **ersten Start** legt Earnie `config.json` an und setzt `ehal.backend=ha`. Ältere Installs mit Config unter `/data/earnie_env/config` werden einmalig nach `/config` migriert.

| Option | Beschreibung | Standard |
|---|---|---|
| `streamlit_port` | Host/UI-Port `8501`; Streamlit intern `8502` hinter nginx | `8501` |
| `ehal_loxone_http_port` | EHAL Loxone-HTTP-Port | `8541` |
| `ui_modes` | Aktive UI-Modi, kommagetrennt | `sunset2sunset,scenario_explorer,live_environment` |
| `auto_start_main` | Startet `main.py` automatisch | `true` |
| `timezone` | Zeitzone (`TZ`) | `Europe/Vienna` |

## Persistenz

| Pfad | Inhalt |
|---|---|
| `/config/` | `config.json`, Sidecars, `.env` |
| `/data/earnie_env/runtime/` | Historie, Logs, State |

Ausführliche Anwenderdokumentation: [`docs/einrichtung/homeassistant-addon.md`](https://github.com/JochenTCC/Earnie/blob/main/docs/einrichtung/homeassistant-addon.md).
