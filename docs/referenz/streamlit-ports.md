# Streamlit-Ports — Stacks und Plattformen

Übersicht, welcher **Host-Port** zu welchem Betriebsmodell gehört. Im Container lauscht Streamlit intern fast immer auf **8501** (`ui.streamlit_port`); das Compose-Mapping `HOST:CONTAINER` kann abweichen.

Konfiguration im Container/venv: `config.json` → `ui.streamlit_port` oder `EARNIE_UI_STREAMLIT_PORT`.

## Port-Zuordnung

| Port | Stack / Betrieb | Plattform | Daemon (`main.py`) | UI-Zugriff | Compose / Start |
|------|-----------------|-----------|--------------------|------------|-----------------|
| **8501** | **Produktion** | Synology NAS, LoxBerry, Proxmox LXC | im Container `earnie-productive` (Auto-Start) | LAN: `http://<host>:8501`; Synology extern: HTTPS :443 → Reverse Proxy → 8501 | `docker/compose/synology_productive.yml`, `loxberry_productive.yml`, `proxmox_productive.yml`; LoxBerry auch via [Plugin](../einrichtung/loxberry-plugin.md) |
| **8511** | **Alpha** | Synology NAS, LoxBerry, Proxmox LXC | im Container `earnie-alpha` (Auto-Start) | LAN: `http://<host>:8511` | `docker/compose/synology-alpha.yml`, `loxberry-alpha.yml`, `proxmox-alpha.yml` (Volumes: `earnie_env_alpha/`) |
| **8521** | **Lokaler Dev-Stack (Docker)** | Windows/Linux Dev-PC | im Container `earnie` (Auto-Start) | `http://localhost:8521` | `docker/compose/dev.yml` (`8521:8501`) |
| **8531** | **Lokal ohne Docker (venv)** | Dev-PC (venv) | `python main.py` (lokal) oder UI **Optimierer-Dienst** | `http://localhost:8531` (`EARNIE_UI_STREAMLIT_PORT`; Schema-Default im Container bleibt 8501) | `python -m scripts.run_streamlit`, VS Code „Streamlit app.py (:8531 lokal)“ |
| **8502** | **Greenfield (Docker)** | Dev-PC (Docker) | im Container `earnie-greenfield` (Auto-Start) | `http://localhost:8502` | `docker/compose/greenfield.yml` (`8502:8501`) |
| **8532** | **Greenfield (venv)** | Dev-PC (venv) | `python main.py` mit `greenfield/config` | `http://localhost:8532` | VS Code „Streamlit app.py (Greenfield :8532)“ |
| **8503** | **OpenEMS-Lab (Docker)** | Dev-PC / Pi (Docker) | im Container `earnie-openems-lab` (Auto-Start) | `http://localhost:8503` | `docker/compose/openems-lab.yml` (`8503:8501`); Setup: [openems-lab](../einrichtung/openems-lab.md) |
| **8504** | **Lokal gegen NAS-Daten** | Dev-PC (venv) | **auf der NAS** (im Prod-Container `earnie-productive`) | `http://localhost:8504` | VS Code „Streamlit app.py (NAS)“ — liest `config`/`runtime` per UNC/SMB von der NAS (früher oft :8503; Port freigeben wegen OpenEMS-Lab) |
| **8506** | **HA + evcc Lab (Docker)** | Dev-PC / Pi (Docker) | im Container `earnie-ha-lab` (Auto-Start) | `http://localhost:8506` | `docker/compose/ha-lab.yml` (`8506:8501`); Setup: [ha-evcc](../einrichtung/ha-evcc.md) |

## Parallelbetrieb auf dem Dev-PC

Typisch gleichzeitig möglich:

- NAS-Produktion unter `http://<nas-ip>:8501` und optional Alpha unter `http://<nas-ip>:8511` (remote; getrennte Volumes)
- Lokaler Dev-Stack Docker unter `http://localhost:8521` und/oder venv unter `http://localhost:8531`
- Greenfield unter `http://localhost:8502` (Docker) oder `http://localhost:8532` (venv)
- OpenEMS-Lab unter `http://localhost:8503` (Docker; Earnie + OpenEMS)
- HA + evcc Lab unter `http://localhost:8506` (Docker; Earnie + Home Assistant + evcc)
- Optional: lokales Cockpit gegen NAS-Log unter `http://localhost:8504` (nur UI lokal, Daemon bleibt auf der NAS)

**Nicht** parallel starten: zwei Prozesse auf dem **selben** Host-Port (z. B. zwei venv-Streamlit-Instanzen beide auf 8531).

## Umgebungsvariable

```text
EARNIE_UI_STREAMLIT_PORT=8503
```

Überschreibt `ui.streamlit_port` aus `config.json` (siehe `ui/streamlit_server.py`).

## Geplant (Backlog 7g)

| Port | Stack | Status |
|------|-------|--------|
| **8504** (Vorschlag) | Silent-Stack (Prod-Loxone lesen) | noch offen |
| **8505** (Vorschlag) | Simuliert-Stack | noch offen |

Konkrete Ports für 7g werden beim Umsetzen hier ergänzt.

## Siehe auch

- [Container](../einrichtung/container.md) — Deployment Synology/LoxBerry
- [Proxmox LXC](../einrichtung/proxmox-lxc.md) — LXC + Docker Compose
- [Greenfield Dev-Stack](../einrichtung/greenfield-dev-stack.md)
- [Betrieb](../einrichtung/betrieb.md) — `main.py` vs. Streamlit
