# Streamlit-Ports – Stacks und Plattformen

Die Übersicht zeigt, welcher **Host-Port** zu welchem Betriebsmodell gehört. Im Container lauscht Streamlit intern fast immer auf **8501** (`ui.streamlit_port`). Das Compose-Mapping `HOST:CONTAINER` kann davon abweichen.

Im Container und in der venv steuern `config.json` → `ui.streamlit_port` oder die Umgebungsvariable `EARNIE_UI_STREAMLIT_PORT` den Port.

## Port-Zuordnung

| Port | Stack / Betrieb | Plattform | Daemon (`main.py`) | UI-Zugriff | Compose / Start |
|------|-----------------|-----------|--------------------|------------|-----------------|
| **8501** | **Produktivbetrieb** | Synology NAS, LoxBerry, Proxmox LXC, Home Assistant (Add-on), Windows-PC (**VMware `vctl`**), **lokal ohne Docker (venv)** | im Container `earnie-productive` (Auto-Start) bzw. lokal `python main.py` / UI **Optimierer-Dienst** | LAN: `http://<host>:8501`; lokal `vctl`/venv: `http://localhost:8501`; Synology extern: HTTPS :443 → Reverse Proxy → 8501; **HA-Add-on:** siehe Hinweis unter der Tabelle | `docker/compose/synology_productive.yml`, `loxberry_productive.yml`, `proxmox_productive.yml`; LoxBerry auch über das [Plugin](../einrichtung/loxberry-plugin.md) (Host-Port in der Admin-UI bzw. `plugin.env` `STREAMLIT_PORT`); Home Assistant über das [Add-on](../einrichtung/homeassistant-addon.md); lokal: `python -m scripts.run_streamlit`, VS Code „Streamlit app.py (:8501 lokal)“ (`EARNIE_UI_STREAMLIT_PORT=8501`); PC/`vctl`: [vmware-vctl.md](../einrichtung/vmware-vctl.md) |
| **8541** | **Produktivbetrieb – EHAL Loxone request HTTP** | Synology NAS, LoxBerry, Proxmox LXC, Home Assistant (Add-on) | Daemon im selben Container (`Earnie_Request_Optimize` / Telemetry inkl. Heartbeat / entity-scoped `GET /ehal/loxone/status.json`) | LAN: `http://<host>:8541` (kein Streamlit) | Compose: `8541:8541` neben Streamlit; auch im LoxBerry-Plugin [`packaging/loxberry/data/docker/docker-compose.yml`](../../packaging/loxberry/data/docker/docker-compose.yml) und im HA-Add-on [`packaging/homeassistant-addon/earnie/config.yaml`](../../packaging/homeassistant-addon/earnie/config.yaml); Config `system.ehal_loxone_http_port` (Default 8541); VI `VI_Earnie_*.xml`, VO `VO_Earnie_Status.xml` |
| **8511** | **Alpha** | Synology NAS, LoxBerry, Proxmox LXC | im Container `earnie-alpha` (Auto-Start) | LAN: `http://<host>:8511` | `docker/compose/synology-alpha.yml`, `loxberry-alpha.yml`, `proxmox-alpha.yml` (Volumes: `earnie_env_alpha/`) |
| **8551** | **Alpha – EHAL Loxone request HTTP** | Synology NAS, LoxBerry, Proxmox LXC | Daemon im Alpha-Container | LAN: `http://<host>:8551` → Container **8541** | Alpha-Compose: `8551:8541` |
| **8521** | **Lokaler Dev-Stack (Docker)** | Windows/Linux Dev-PC | im Container `earnie` (Auto-Start) | `http://localhost:8521` | `docker/compose/dev.yml` (`8521:8501`) |
| **8502** | **Greenfield (Docker)** | Dev-PC (Docker) | im Container `earnie-greenfield` (Auto-Start) | `http://localhost:8502` | `docker/compose/greenfield.yml` (`8502:8501`) |
| **8542** | **Greenfield – EHAL Loxone request HTTP** | Dev-PC (Docker) | Daemon im Greenfield-Container | `http://localhost:8542` → Container **8541** | `greenfield.yml` (`8542:8541`); VO-Adresse auf dem Dev-PC ggf. `:8542` |
| **8532** | **Greenfield (venv)** | Dev-PC (venv) | `python main.py` mit `greenfield/config` | `http://localhost:8532` | VS Code „Streamlit app.py (Greenfield :8532)“ |
| **8503** | **OpenEMS-Lab (Docker)** | Dev-PC / Pi (Docker) | im Container `earnie-openems-lab` (Auto-Start) | `http://localhost:8503` | `docker/compose/openems-lab.yml` (`8503:8501`); Einrichtung: [openems-lab](../einrichtung/openems-lab.md) |
| **8504** | **Lokal gegen NAS-Daten** | Dev-PC (venv) | **auf der NAS** (im Produktiv-Container `earnie-productive`) | `http://localhost:8504` | VS Code „Streamlit app.py (NAS)“; liest `config`/`runtime` per UNC/SMB von der NAS (früher oft :8503; dieser Port bleibt für das OpenEMS-Lab frei) |
| **8506** | **HA + evcc Lab (Docker)** | Dev-PC / Pi (Docker) | im Container `earnie-ha-lab` (Auto-Start) | `http://localhost:8506` | `docker/compose/ha-lab.yml` (`8506:8501`); Einrichtung: [ha-evcc](../einrichtung/ha-evcc.md) |

> **Hinweis (Home-Assistant-Add-on):** Die Oberfläche öffnet sich vorrangig über **Ingress** (Seitenleiste bzw. OPEN WEB UI). Der Host-Port `8501` ist nur optional. Dort reicht nginx die Anfragen an Streamlit intern auf **8502** weiter.

## Parallelbetrieb auf dem Dev-PC

Diese Stacks laufen typischerweise gleichzeitig:

- **NAS:** Produktivbetrieb unter `http://<nas-ip>:8501`, optional Alpha unter `http://<nas-ip>:8511` (remote, mit getrennten Volumes).
- **Lokaler Dev-Stack:** Docker unter `http://localhost:8521` und/oder venv unter `http://localhost:8501`.
- **Greenfield:** `http://localhost:8502` (Docker) oder `http://localhost:8532` (venv).
- **OpenEMS-Lab:** `http://localhost:8503` (Docker mit Earnie und OpenEMS).
- **HA + evcc Lab:** `http://localhost:8506` (Docker mit Earnie, Home Assistant und evcc).
- **Lokales Cockpit gegen NAS-Log (optional):** `http://localhost:8504`. Nur die Oberfläche läuft lokal, der Daemon bleibt auf der NAS.

Zwei Prozesse auf **demselben** Host-Port lassen sich nicht parallel starten. Das gilt z. B. für zwei venv-Streamlit-Instanzen auf 8501 oder für den Dev-Docker auf 8521 und eine zweite Instanz auf demselben Port.

## Umgebungsvariable

```text
EARNIE_UI_STREAMLIT_PORT=8503
```

Die Variable überschreibt `ui.streamlit_port` aus `config.json` (siehe `ui/streamlit_server.py`). Der Schema-Default ist **8501**.

## Siehe auch

- [Container](../einrichtung/container.md) – Deployment auf Synology und LoxBerry
- [Proxmox LXC](../einrichtung/proxmox-lxc.md) – LXC mit Docker Compose
- [VMware Workstation `vctl`](../einrichtung/vmware-vctl.md) – Windows-PC ohne Docker Desktop
- [Greenfield Dev-Stack](../einrichtung/greenfield-dev-stack.md)
- [Betrieb](../einrichtung/betrieb.md) – `main.py` und Streamlit im Vergleich
