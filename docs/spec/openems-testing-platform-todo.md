# TODO — OpenEMS testing platform (Earnie 2.4 / M1)

**Purpose:** Local lab stack for **2.4.b** (OpenEMS EHAL prototype).  
**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §2.2, §2.5 Phase 2, §2.6; backlog `2.4.b`.  
**EHAL wire contract (frozen):** [`docs/spec/ehal.md`](ehal.md) — schemas in `share/ehal/`, Python package `ehal`. Adapters must emit/consume only that contract.  
**Goal:** Run `openems-edge` so Earnie can talk **network API only** (REST/WS) — Separate Works / AGPL shield. No OpenEMS source or libraries in Earnie repos.  
**Host IP:** `192.168.178.34` (Pi lab; on a Dev-PC use that machine’s LAN IP / `localhost`)

**Combined Compose + Earnie ↔ OpenEMS setup (step-by-step):** [`openems-lab-setup.md`](openems-lab-setup.md) — use this when `earnie-openems-lab` + Edge + UI are already up but not configured for communication.  
German pointer: [`docs/einrichtung/openems-lab.md`](../einrichtung/openems-lab.md).

This TODO remains the **OpenEMS plant / REST channel** checklist (first verified on Raspberry Pi).


| Service                   | URL                                                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| OpenEMS UI                | [http://192.168.178.34:8088/](http://192.168.178.34:8088/)                                                 |
| Felix configMgr           | [http://192.168.178.34:8080/system/console/configMgr](http://192.168.178.34:8080/system/console/configMgr) |
| Edge WebSocket / JSON-RPC | `192.168.178.34:8085`                                                                                      |
| REST/JSON API (default)   | [http://192.168.178.34:8084/rest/…](http://192.168.178.34:8084/rest/channel/_sum/EssSoc)                   |
| UI HTTPS (optional)       | [https://192.168.178.34:8443/](https://192.168.178.34:8443/)                                               |


---



## Preferred platform

- [x] **Primary:** Raspberry Pi 4 (4 GB min; **8 GB preferred**) or Pi 5 — matches Entwicklungsplan (“Pi 4 + Docker Compose”)
- [x] **Alternative:** NAS with reliable Linux Docker on **amd64** or **arm64** (only if Pi is unavailable)
- [x] 64-bit OS (Raspberry Pi OS 64-bit recommended)
- [x] SSH access; stable LAN IP `**192.168.178.34**`
- [ ] Storage: USB SSD preferred over SD for Compose volumes (optional early on)

**Later on same host (not required for first OpenEMS bring-up):** `earnie-core`; then **2.4.c** Home Assistant + evcc.

---



## 1. Host preparation

- [x] Install Docker Engine + Compose plugin ([docs.docker.com](https://docs.docker.com/engine/install/))
- [x] Verify: `docker --version`, `docker compose version`
- [x] Confirm architecture is `amd64` or `arm64` (`ls`  → `x86_64` / `aarch64`)

---



## 2. OpenEMS Edge + UI (Docker Compose)

Official guide: [Deploy OpenEMS Edge to Docker](https://openems.github.io/openems.io/openems/latest/edge/deploy/docker.html)  
Images: `[openems/edge](https://hub.docker.com/r/openems/edge)`, `[openems/ui-edge](https://hub.docker.com/r/openems/ui-edge)`

- [ ] Create a directory (e.g. `~/openems-lab`) with `docker-compose.yml`:

```yaml
services:
  openems-edge:
    image: openems/edge:latest   # prefer pinning a release tag, e.g. 2026.2.0
    container_name: openems_edge
    hostname: openems_edge
    restart: unless-stopped
    volumes:
      - openems-edge-conf:/var/opt/openems/config:rw
      - openems-edge-data:/var/opt/openems/data:rw
    ports:
      - 8080:8080   # Apache Felix console
      - 8084:8084   # REST/JSON API (Controller.Api.Rest.*)
      - 8085:8085   # UI WebSocket / JSON-RPC

  openems-ui:
    image: openems/ui-edge:latest
    container_name: openems_ui
    hostname: openems_ui
    restart: unless-stopped
    volumes:
      - openems-ui-conf:/etc/nginx:rw
      - openems-ui-log:/var/log/nginx:rw
    environment:
      # Browser must resolve this — use the NAS/Pi LAN IP, not the Docker service name
      - WEBSOCKET_HOST=192.168.178.34
      - WEBSOCKET_PORT=8085
    ports:
      # Host:container — avoid 80/443 (often taken by NAS DSM, nginx, Traefik, …)
      - 8088:80
      - 8443:443

volumes:
  openems-edge-conf:
  openems-edge-data:
  openems-ui-conf:
  openems-ui-log:
```

**Port map check (**`docker ps`**):** REST **8084** must be on `openems_edge`, not on `openems_ui`. Example of a wrong layout (causes connect-then-reset on `:8084`):

```text
openems_edge  … 8080->8080, 8085->8085          # missing 8084
openems_ui    … 8084->8084, 8088->80, …         # 8084 wrongly here → nginx, not REST
```

Fix in `docker-compose.yml`: put `8084:8084` under `openems-edge` **only**; remove `8084` from `openems-ui`. Then `docker compose up -d` and confirm:

```text
openems_edge  … 8080->8080, 8084->8084, 8085->8085
openems_ui    … 8088->80, 8443->443
```

**UI 404 on** `:8088` **(Felix on** `:8080` **OK):** Edge is fine; UI nginx config is usually broken or stale (common after the first failed bind on 443). Fix on the host:

```bash
docker compose stop openems-ui
docker compose rm -f openems-ui
docker volume rm "$(docker volume ls -q | grep openems-ui-conf)"
docker volume rm "$(docker volume ls -q | grep openems-ui-log)"
# Or, if project-named volumes: docker volume rm <project>_openems-ui-conf <project>_openems-ui-log
docker compose up -d openems-ui
docker logs openems_ui
```

Also set `WEBSOCKET_HOST=192.168.178.34` (as above). In Felix, ensure **Controller Api Websocket** exists with port `8085`. Check websocket: `curl -sI http://192.168.178.34:8085` → expect something like `404 WebSocket Upgrade Failure` (means the port is alive).

- [x] `docker compose up -d`
- [x] Confirm both containers are up: `docker ps` (expect `openems_edge` with `8080`, `8084`, `8085`; `openems_ui` with `8088->80`)
- [x] Reach **OpenEMS UI**: `http://192.168.178.34:8088/`
  - **guest** (default password / leave as suggested): OK for live view / monitoring only
  - **admin** (password `admin`): needed for Settings → **Install components**, simulator setup, and API controllers — use this for the lab
  - Prefer UI → Settings → **Install components** for lab config once logged in as admin
- [x] Reach Felix (exact path): `http://192.168.178.34:8080/system/console/configMgr`
  - Credentials: `admin` / `admin`
  - If the browser login dialog fails (esp. Edge/Chrome): try Firefox, or `http://admin:admin@192.168.178.34:8080/system/console/configMgr`
  - Bare `/system/console` may **404**; use **`/system/console/configMgr`**
- [x] UI reachable on `:8088` (port map fixed; `8084` on Edge only)
- [ ] Pin image tags once a known-good release is chosen (avoid silent `latest` drift) — reference Compose uses **`2026.7.0`** (`docker/compose/openems-lab.yml`); re-pin after lab validation if Edge was started earlier with `latest`

---



## 3. Simulated plant (no real hardware)

Follow: [Getting Started](https://openems.github.io/openems.io/openems/latest/gettingstarted.html), [Simulated components](https://openems.github.io/openems.io/openems/latest/edge/core.d/io.openems.edge.simulator.html)  
Install via UI (admin) → Settings → **Install components**, or via Felix `configMgr`. **Order matters** (IDs are referenced by later components).

### 3.1 Core (not under Simulators)

- [x] **Scheduler All Alphabetically** — ID `scheduler0` (create if missing)
- [x] **Controller Debug Log** — ID `ctrlDebugLog0` (optional; helpful for sanity checks)
- [x] **Controller Api Websocket** — port `8085` (required for UI ↔ Edge) under [http://192.168.178.34:8080/system/console/configMgr](http://192.168.178.34:8080/system/console/configMgr)



### 3.2 Simulators — minimal Earnie plant (grid + PV + battery)

- [x] **Simulator DataSource: CSV Predefined** — ID `datasource0`  
  - Source e.g. `H0_HOUSEHOLD_SUMMER_WEEKDAY_STANDARD_LOAD_PROFILE` (household load)
- [x] **Simulator GridMeter Acting** — ID `meter0`  
  - Datasource-ID: `datasource0`
- [x] **Simulator DataSource: CSV Predefined** (second instance) — ID `datasource1`  
  - Pick a production-style / PV-capable predefined source if available; otherwise any varying profile is OK for lab
- [x] **Simulator ProductionMeter Acting** (PV) — ID e.g. `meter1`  
  - Datasource-ID: `datasource1`
- [x] **Simulator EssSymmetric Reacting** (battery) — ID `ess0`  
  - Defaults OK
- [x] **Controller Ess Balancing** — factory PID `Controller.Ess.Balancing` (legacy/docs also say `Controller.Symmetric.Balancing`; UI may show **ESS Balancing** / **Controller Ess Balancing**)  
  - Prefer **Felix** search for `Balancing` if UI Install list is hard to navigate: [http://192.168.178.34:8080/system/console/configMgr](http://192.168.178.34:8080/system/console/configMgr)  
  - Ess-ID: `ess0`  
  - Grid-Meter-ID: `meter0`  
  - ID e.g. `ctrlBalancing0`  
  - **Optional for Earnie API tests:** only needed so the simulated battery actually charges/discharges; telemetry channels exist without it



### 3.3 Earnie network API (not Simulators)

- [x] **Controller Api Rest/Json Read-Write** — factory `Controller.Api.Rest.ReadWrite`  
  - Port **8084** (default); publish `8084:8084` under **`openems-edge` only** (not UI) then `docker compose up -d`  
  - Felix search: `Rest` / `Controller.Api.Rest.ReadWrite`  
  - Auth: Basic; username often `x`, password = OpenEMS user password (`user` = guest, `admin` = admin)



### 3.4 Simulated EVCS (required for 2.4.b)

- [x] **Simulator Evcs** — ID `evcs0` (factory e.g. `Simulator.Evcs` / UI **Simulators → Evcs**)
  - Lab verified 2026-07-27: `evcs0/ActivePower` (RO, W), `evcs0/Status`, `evcs0/SetChargePowerLimit` (RW, **W**)
  - EHAL `set_evcs_max_current` is in **A**; Earnie adapter converts A→W via house-profile voltage/phases before writing `SetChargePowerLimit`
  - `evcs0/ChargePower` may be absent — use `ActivePower` for `evcs_active_power`
- [x] Skip for now: Backend, Influx, real Modbus/OEM devices, Simulator App (batch JSON-RPC) unless needed



### 3.5 Sanity check — REST from another machine (e.g. your PC)

Docs: [API REST](https://openems.github.io/openems.io/openems/latest/edge/controller.d/io.openems.edge.controller.api.rest.html)  
Base: `http://192.168.178.34:8084/rest` — use password `admin` for write tests.

**Verified 2026-07-27 (PC → lab):**
- Read `_sum/GridActivePower` → JSON OK (e.g. `value: -77`; OpenEMS: − = sell-to-grid)
- Write `ess0/SetActivePowerEquals` `{"value": 1000}` → `{}` / 200
- Read `ess0/ActivePower` → `value: 1000` (discharge)

#### Read (grid / PV / SoC)

From PowerShell or any shell on your PC:

```bash
curl -u x:admin http://192.168.178.34:8084/rest/channel/_sum/GridActivePower
curl -u x:admin http://192.168.178.34:8084/rest/channel/_sum/ProductionActivePower
curl -u x:admin http://192.168.178.34:8084/rest/channel/_sum/EssSoc
curl -u x:admin http://192.168.178.34:8084/rest/channel/ess0/Soc
```

Or open in browser (after login prompt):  
`http://192.168.178.34:8084/rest/channel/_sum/EssSoc`

Expect JSON with a numeric `"value"` (W or %). Optional dump:

```bash
curl -u x:admin "http://192.168.178.34:8084/rest/channel/.*/Active.*Power"
```

- [x] Confirm **read** of grid / PV / SoC returns JSON with values (not 401/404/connection refused)



#### Write (ESS limit / power setpoint)

Prefer a limit channel (EHAL-like) or equals setpoint:

```powershell
# PowerShell (use curl.exe + single-quoted JSON body)
curl.exe -X POST -u x:admin -H "Content-Type: application/json" -d '{"value": 1000}' http://192.168.178.34:8084/rest/channel/ess0/SetActivePowerEquals

# Limit-style (if present):
curl.exe -X POST -u x:admin -H "Content-Type: application/json" -d '{"value": 2000}' http://192.168.178.34:8084/rest/channel/ess0/SetActivePowerLessOrEquals
curl.exe -X POST -u x:admin -H "Content-Type: application/json" -d '{"value": -2000}' http://192.168.178.34:8084/rest/channel/ess0/SetActivePowerGreaterOrEquals
```

```bash
# Linux / Pi SSH (bash)
curl -X POST -u x:admin -H "Content-Type: application/json" \
  -d '{"value": 1000}' \
  http://127.0.0.1:8084/rest/channel/ess0/SetActivePowerEquals
```

(On PowerShell, `curl` alone is `Invoke-WebRequest` — always use `curl.exe`. Do **not** use `\"` escaping inside PowerShell double quotes for the JSON body.)

Success: HTTP **200**. Then re-read `ess0/ActivePower` / UI monitor.

#### OEM-style write lock (negativtest)

- [x] Confirm **write** of at least one ESS setpoint returns 200  
- [ ] Simulate lock / no-write on lab (optional manual): `Controller.Api.Rest.ReadOnly` or guest password `user` → expect **403**; Earnie adapter unit-tested for 403 → log + `supports_ess_write=false` + `runtime/ehal_write_error.json` / UI hint

PowerShell one-liner alternative for read:

```powershell
curl.exe -u x:admin http://192.168.178.34:8084/rest/channel/_sum/GridActivePower
```



### Target channels → EHAL (frozen contract: [`ehal.md`](ehal.md); Entwicklungsplan §2.4.1)


| EHAL field                      | OpenEMS (prototype)                                   |
| ------------------------------- | ----------------------------------------------------- |
| `grid_power_active`             | `_sum/GridActivePower` (normalize sign: `+` = import) |
| `pv_production_active`          | `_sum/ProductionActivePower`                          |
| `ess_soc`                       | `ess0/Soc` / `_sum/EssSoc`                            |
| `ess_power` (optional)          | `ess0/ActivePower` / `_sum/EssActivePower` (+ = discharge) |
| `evcs_active_power`             | `evcs0/ActivePower` (W, ≥ 0)                              |
| `set_ess_charge_power_limit`    | `ess0/SetActivePowerGreaterOrEquals` (value = −|W|)       |
| `set_ess_discharge_power_limit` | `ess0/SetActivePowerLessOrEquals` (value = +|W|)          |
| `set_evcs_max_current`          | A→W then `evcs0/SetChargePowerLimit` (W)                  |


---



## 4. Compliance checklist (binding for 2.4.b)

- [x] OpenEMS runs only as **separate container** — not linked into Earnie Python (`docker/compose/openems-lab.yml`)
- [x] No OpenEMS source fragments or jars copied into Energy-Optimizer / Earnie repos
- [x] Earnie ↔ OpenEMS = network only (REST; WS optional later)
- [x] Adapter reports capability flags (`supports_ess_write`, …) and degrades on failed writes (`integrations/openems_adapter.py`)

---



## 5. Earnie side (after OpenEMS lab is green)

**Operator guide (config + communication checks):** [`openems-lab-setup.md`](openems-lab-setup.md)

- [x] Reference Compose: [`docker/compose/openems-lab.yml`](../../docker/compose/openems-lab.yml) (`earnie` + `openems-edge` + `openems-ui`; backlog “earnie-core” = `earnie` service)
- [x] Python OpenEMS-EHAL adapter (network client only) — `integrations/openems_adapter.py` + `integrations/ehal_live.py`
- [x] Map minimal field set above; Live consumes EHAL under `ehal.backend=openems` (see `share/config/ehal.openems.snippet.json`)
- [x] Negativtests: write lock → log + UI hint + capability degrade (unit-tested with mocked HTTP 403; lab: guest password / ReadOnly REST)
- [x] Lab acceptance on combined Compose: follow [`openems-lab-setup.md`](openems-lab-setup.md) §4 (Earnie reads SoC via `openems-edge:8084`)

*(Implementation: backlog `2.4.b`. EHAL schemas frozen under `2.4.a` / [`ehal.md`](ehal.md).)*

---



## Out of scope for this platform TODO

- Home Assistant + evcc (**2.4.c** / A2 DACH default)
- Loxone-EHAL extraction (**2.5**)
- Real FEMS/OEM hardware (optional later; expect write locks)
- MQTT/Matter as first-class hubs

---



## Quick references

- Backlog: `backlog/Backlog.md` → Version 2.4 / `2.4.b`
- Entwicklungsplan: `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md`
- OpenEMS Docker: [https://openems.github.io/openems.io/openems/latest/edge/deploy/docker.html](https://openems.github.io/openems.io/openems/latest/edge/deploy/docker.html)
- OpenEMS Getting Started (simulator): [https://openems.github.io/openems.io/openems/latest/gettingstarted.html](https://openems.github.io/openems.io/openems/latest/gettingstarted.html)

