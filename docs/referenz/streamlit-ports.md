# Streamlit-Ports — Stacks und Plattformen

Übersicht, welcher **Host-Port** zu welchem Betriebsmodell gehört. Im Container lauscht Streamlit intern fast immer auf **8501** (`ui.streamlit_port`); das Compose-Mapping `HOST:CONTAINER` kann abweichen.

Konfiguration im Container/venv: `config.json` → `ui.streamlit_port` oder `EARNIE_UI_STREAMLIT_PORT`.

## Port-Zuordnung

| Port | Stack / Betrieb | Plattform | Worker | UI-Zugriff | Compose / Start |
|------|-----------------|-----------|--------|------------|-----------------|
| **8501** | **Produktion** | Synology NAS, LoxBerry, Proxmox LXC | `optimizer-worker` auf dem Gerät | LAN: `http://<host>:8501`; Synology extern: HTTPS :443 → Reverse Proxy → 8501 | `docker/compose/synology.yml`, `docker/compose/loxberry.yml`, `docker/compose/proxmox.yml` |
| **8501** | **Lokaler Dev-Stack (Docker)** | Windows/Linux Dev-PC | `earnie-optimizer-worker` (lokal) | `http://localhost:8501` | `docker/compose/dev.yml` (`8501:8501`) |
| **8501** | **Lokal ohne Docker (venv)** | Dev-PC (venv) | `python main.py` (lokal) | `http://localhost:8501` (Standard `ui.streamlit_port`) | `python -m scripts.run_streamlit`, VS Code „Streamlit app.py (:8501 lokal)“ |
| **8502** | **Greenfield (Docker)** | Dev-PC (Docker) | `earnie-greenfield-worker` | `http://localhost:8502` | `docker/compose/greenfield.yml` (`8502:8501`) |
| **8511** | **Greenfield (venv)** | Dev-PC (venv) | `python main.py` mit `greenfield/config` | `http://localhost:8511` | VS Code „Streamlit app.py (LOKAL, Greenfield :8511)“ |
| **8512** | **Silent Migration Test** | Dev-PC (venv) | optional lokal oder nur UI | `http://localhost:8512` | VS Code „Streamlit app.py (Silent Migration :8512)“ — siehe [Silent Migration Test](../einrichtung/silent-migration-test.md) |
| **8503** | **Lokal gegen NAS-Daten** | Dev-PC (venv) | **auf der NAS** (`optimizer-worker` im Prod-Container) | `http://localhost:8503` | VS Code „Streamlit app.py (NAS :8503)“ — liest `config`/`runtime` per UNC/SMB von der NAS |

## Parallelbetrieb auf dem Dev-PC

Typisch gleichzeitig möglich:

- NAS-Produktion unter `http://<nas-ip>:8501` (remote)
- Greenfield unter `http://localhost:8502` (Docker) oder `8511` (venv)
- Lokales Cockpit gegen NAS-Log unter `http://localhost:8503` (nur UI lokal, Worker bleibt auf der NAS)

**Nicht** parallel starten: zwei Prozesse auf dem **selben** Host-Port (z. B. zwei venv-Streamlit-Instanzen beide auf 8501).

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
