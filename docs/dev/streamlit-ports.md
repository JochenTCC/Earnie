# Streamlit Ports – Stacks and Platforms

This overview shows which **host port** belongs to which operating model. Inside the container Streamlit almost always listens on **8501** (`ui.streamlit_port`). The Compose mapping `HOST:CONTAINER` may differ.

In the container and in the venv, `config.json` → `ui.streamlit_port` or the environment variable `EARNIE_UI_STREAMLIT_PORT` sets the port.

## Port assignment

| Port | Stack / operation | Platform | Daemon (`main.py`) | UI access | Compose / start |
|------|-------------------|----------|--------------------|-----------|-----------------|
| **8501** | **Production** | Synology NAS, LoxBerry, Proxmox LXC, Home Assistant (add-on), Windows PC (**VMware `vctl`**), **local without Docker (venv)** | in the `earnie-productive` container (auto-start) or locally `python main.py` / UI **Optimizer service** | LAN: `http://<host>:8501`; local `vctl`/venv: `http://localhost:8501`; Synology external: HTTPS :443 → reverse proxy → 8501; **HA add-on:** see the note below the table | `docker/compose/synology_productive.yml`, `loxberry_productive.yml`, `proxmox_productive.yml`; LoxBerry also via the [plugin](../einrichtung/loxberry-plugin.md) (host port in the admin UI or `plugin.env` `STREAMLIT_PORT`); Home Assistant via the [add-on](../einrichtung/homeassistant-addon.md); local: `python -m scripts.run_streamlit`, VS Code "Streamlit app.py (:8501 lokal)" (`EARNIE_UI_STREAMLIT_PORT=8501`); PC/`vctl`: [vmware-vctl.md](../einrichtung/vmware-vctl.md) |
| **8541** | **Production – EHAL Loxone request HTTP** | Synology NAS, LoxBerry, Proxmox LXC, Home Assistant (add-on) | Daemon in the same container (`Earnie_Request_Optimize` / telemetry incl. heartbeat / entity-scoped `GET /ehal/loxone/status.json`) | LAN: `http://<host>:8541` (no Streamlit) | Compose: `8541:8541` next to Streamlit; also in the LoxBerry plugin [`packaging/loxberry/data/docker/docker-compose.yml`](../../packaging/loxberry/data/docker/docker-compose.yml) and the HA add-on [`packaging/homeassistant-addon/earnie/config.yaml`](../../packaging/homeassistant-addon/earnie/config.yaml); config `system.ehal_loxone_http_port` (default 8541); VI `VI_Earnie_*.xml`, VO `VO_Earnie_Status.xml` |
| **8511** | **Alpha** | Synology NAS, LoxBerry, Proxmox LXC | in the `earnie-alpha` container (auto-start) | LAN: `http://<host>:8511` | `docker/compose/synology-alpha.yml`, `loxberry-alpha.yml`, `proxmox-alpha.yml` (volumes: `earnie_env_alpha/`) |
| **8551** | **Alpha – EHAL Loxone request HTTP** | Synology NAS, LoxBerry, Proxmox LXC | Daemon in the Alpha container | LAN: `http://<host>:8551` → container **8541** | Alpha Compose: `8551:8541` |
| **8521** | **Local dev stack (Docker)** | Windows/Linux dev PC | in the `earnie` container (auto-start) | `http://localhost:8521` | `docker/compose/dev.yml` (`8521:8501`) |
| **8502** | **Greenfield (Docker)** | Dev PC (Docker) | in the `earnie-greenfield` container (auto-start) | `http://localhost:8502` | `docker/compose/greenfield.yml` (`8502:8501`) |
| **8542** | **Greenfield – EHAL Loxone request HTTP** | Dev PC (Docker) | Daemon in the Greenfield container | `http://localhost:8542` → container **8541** | `greenfield.yml` (`8542:8541`); VO address on the dev PC possibly `:8542` |
| **8532** | **Greenfield (venv)** | Dev PC (venv) | `python main.py` with `greenfield/config` | `http://localhost:8532` | VS Code "Streamlit app.py (Greenfield :8532)" |
| **8503** | **OpenEMS lab (Docker)** | Dev PC / Pi (Docker) | in the `earnie-openems-lab` container (auto-start) | `http://localhost:8503` | `docker/compose/openems-lab.yml` (`8503:8501`); setup: [openems-lab](../einrichtung/openems-lab.md) |
| **8504** | **Local against NAS data** | Dev PC (venv) | **on the NAS** (in the `earnie-productive` production container) | `http://localhost:8504` | VS Code "Streamlit app.py (NAS)"; reads `config`/`runtime` from the NAS via UNC/SMB (formerly often :8503; that port stays free for the OpenEMS lab) |
| **8506** | **HA + evcc lab (Docker)** | Dev PC / Pi (Docker) | in the `earnie-ha-lab` container (auto-start) | `http://localhost:8506` | `docker/compose/ha-lab.yml` (`8506:8501`); setup: [ha-evcc](../einrichtung/ha-evcc.md) |

> **Note (Home Assistant add-on):** The UI opens primarily via **Ingress** (sidebar or OPEN WEB UI). The host port `8501` is optional. There, nginx forwards requests to Streamlit internally on **8502**.

## Parallel operation on the dev PC

These stacks typically run at the same time:

- **NAS:** production at `http://<nas-ip>:8501`, optionally Alpha at `http://<nas-ip>:8511` (remote, with separate volumes).
- **Local dev stack:** Docker at `http://localhost:8521` and/or venv at `http://localhost:8501`.
- **Greenfield:** `http://localhost:8502` (Docker) or `http://localhost:8532` (venv).
- **OpenEMS lab:** `http://localhost:8503` (Docker with Earnie and OpenEMS).
- **HA + evcc lab:** `http://localhost:8506` (Docker with Earnie, Home Assistant and evcc).
- **Local cockpit against the NAS log (optional):** `http://localhost:8504`. Only the UI runs locally, the daemon stays on the NAS.

Two processes cannot be started in parallel on the **same** host port. This applies e.g. to two venv Streamlit instances on 8501, or to the dev Docker on 8521 and a second instance on the same port.

## Environment variable

```text
EARNIE_UI_STREAMLIT_PORT=8503
```

The variable overrides `ui.streamlit_port` from `config.json` (see `ui/streamlit_server.py`). The schema default is **8501**.

## See also

- [Container](../einrichtung/container.md) – deployment on Synology and LoxBerry
- [Proxmox LXC](../einrichtung/proxmox-lxc.md) – LXC with Docker Compose
- [VMware Workstation `vctl`](../einrichtung/vmware-vctl.md) – Windows PC without Docker Desktop
- [Greenfield dev stack](../einrichtung/greenfield-dev-stack.md)
- [Operation](../einrichtung/betrieb.md) – `main.py` and Streamlit compared
