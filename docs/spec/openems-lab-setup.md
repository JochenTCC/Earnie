# OpenEMS lab setup — Earnie ↔ OpenEMS communication

**Purpose:** Bring up and configure the **combined** Compose stack (`earnie` + `openems-edge` + `openems-ui`) so you can prove Earnie talks to OpenEMS over REST only (EHAL M1 / backlog **2.4.b**).

**Audience:** Operator of the lab on a Dev-PC or Pi. Containers may already be running; this guide finishes **configuration** and a **communication check**.

**Related:**


| Doc                                                                                      | Role                                                                            |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `[docker/compose/openems-lab.yml](../../docker/compose/openems-lab.yml)`                 | Reference Compose                                                               |
| `[openems-testing-platform-todo.md](openems-testing-platform-todo.md)`                   | OpenEMS-only plant checklist (simulators, REST channels) — first verified on Pi |
| `[ehal.md](ehal.md)`                                                                     | Frozen EHAL contract                                                            |
| `[share/config/ehal.openems.snippet.json](../../share/config/ehal.openems.snippet.json)` | Config fragment to merge into Earnie `config.json`                              |


---



## Goal (done when)

1. Host can `GET` OpenEMS REST on **:8084** (grid / SoC JSON).
2. Earnie container resolves `http://openems-edge:8084` and reads the same channels.
3. Live cycle with `ehal.backend=openems` logs a successful SoC read (not “Kein Zugriff auf EHAL/OpenEMS SoC”).
4. Optional write path: ESS setpoint via REST from host, then via Earnie when silent mode is **off**.

---



## Architecture (who talks to whom)

```text
Browser ──► :8503 ──► earnie-openems-lab (Streamlit + main.py)
                              │
                              │ Docker DNS: http://openems-edge:8084
                              ▼
Host/PC ──► :8084 ──► openems_edge (REST Controller.Api.Rest.*)
Host/PC ──► :8088 ──► openems_ui   (nginx → Edge WS :8085)
Host/PC ──► :8080 ──► openems_edge (Felix configMgr)
```


| Audience                              | OpenEMS REST base URL                                                                   |
| ------------------------------------- | --------------------------------------------------------------------------------------- |
| Earnie **inside** Compose             | `http://openems-edge:8084` (service name — **not** `localhost`, **not** `openems_edge`) |
| curl / browser on the **Docker host** | `http://127.0.0.1:8084` or `http://localhost:8084`                                      |
| Another PC on the LAN                 | `http://<HOST_LAN_IP>:8084` (example historically: `192.168.178.34`)                    |


**Volumes (bind mounts from repo root):**


| Host path                                                          | Container                                    |
| ------------------------------------------------------------------ | -------------------------------------------- |
| `./openems_lab/config`                                             | `/app/config` (Earnie)                       |
| `./openems_lab/runtime`                                            | `/app/runtime` (Earnie)                      |
| Docker named volumes `*_openems-edge-conf` / `*_openems-edge-data` | Edge config + data (simulators persist here) |


If `openems_lab/config` only contains `.gitkeep`, Earnie has **no** `ehal` block yet — Live still uses the Loxone path and cannot talk to OpenEMS.

---



## 0. Prerequisites

- [x] Docker Compose stack up from **repo root**:

```powershell
docker compose --project-directory . -f docker/compose/openems-lab.yml ps
```

Expect: `earnie-openems-lab`, `openems_edge`, `openems_ui` — all running.

- [ ] Port map (critical): **8084 on Edge only**

```text
openems_edge  … 8080->8080, 8084->8084, 8085->8085
openems_ui    … 8088->80, 8443->443
earnie-openems-lab … 8503->8501
```

- [x] Stop any older Earnie stack that also binds **8501** / confuses you (`ernie-optimizer-ui`, etc.). Lab UI is **[http://localhost:8503](http://localhost:8503)**.
- [ ] Set `OPENEMS_UI_WEBSOCKET_HOST` to the **LAN IP of the Docker host** (browser must reach Edge WS). Default in Compose may still be `192.168.178.34` — override if your PC/Pi IP differs:

```powershell
$env:OPENEMS_UI_WEBSOCKET_HOST = "<YOUR_LAN_IP>"
docker compose --project-directory . -f docker/compose/openems-lab.yml up -d
```

---



## 1. Earnie config (`openems_lab/`)



### 1.1 Let bootstrap create files (if empty)

With empty `openems_lab/config` + `openems_lab/runtime`, restart Earnie once so the entrypoint runs `bootstrap_runtime`:

```powershell
docker compose --project-directory . -f docker/compose/openems-lab.yml restart earnie
```

Then confirm on the **host** (bind mount):


| Path                                      | Expectation                                    |
| ----------------------------------------- | ---------------------------------------------- |
| `openems_lab/config/config.json`          | Exists (from `config.minimal.json`)            |
| `openems_lab/config/.env`                 | Exists (placeholders OK; Loxone verify is off) |
| `openems_lab/runtime/local_settings.json` | Exists                                         |


If files still missing: check logs (`docker logs earnie-openems-lab`) and that Compose was started with `--project-directory .` from the Energy-Optimizer repo root.

### 1.2 Enable OpenEMS EHAL backend

Merge the snippet into `openems_lab/config/config.json` (top-level key `ehal`, next to `ui` / `system` / …):

```json
"ehal": {
  "backend": "openems",
  "adapter_id": "openems-lab",
  "openems": {
    "base_url": "http://openems-edge:8084",
    "username": "x",
    "password": "admin",
    "ess_component": "ess0",
    "evcs_component": "evcs0"
  }
}
```

Canonical copy: `[share/config/ehal.openems.snippet.json](../../share/config/ehal.openems.snippet.json)`.

**Do not** use `http://localhost:8084` inside the Earnie container — that points at the container itself, not Edge.

### 1.3 Silent mode (writes)

For **read-only** communication check, silent mode can stay on.

For **write** acceptance (ESS / EVCS setpoints from Live):

- Set `openems_lab/runtime/local_settings.json` → `"loxone_silent_mode": false`  
(same flag gates OpenEMS southbound writes; see `[ehal.md](ehal.md)` implementation notes).



### 1.4 Restart Earnie after config edit

```powershell
docker compose --project-directory . -f docker/compose/openems-lab.yml restart earnie
```

Config is loaded at process start — editing JSON alone is not enough.

### 1.5 Live planning (needed for a full Live cycle)

SoC read from OpenEMS is enough to prove the adapter path. A **full** optimization cycle still needs a usable Live scenario (house profile, battery, tariffs) — same idea as [Greenfield](../einrichtung/greenfield-dev-stack.md): complete Hauskonfigurator + Live scenario under **[http://localhost:8503](http://localhost:8503)**. Without that, Live may fail later for planning reasons even when OpenEMS REST works.

---



## 2. OpenEMS Edge — simulated plant + REST API

Edge named volumes start **empty** on a new host. If this Edge was never configured (or volumes were recreated), install the plant again.

**UI:** [http://localhost:8088/](http://localhost:8088/) — login **admin** / **admin** (Settings → Install components).  
**Felix:** [http://localhost:8080/system/console/configMgr](http://localhost:8080/system/console/configMgr) — **admin** / **admin**.

Install in order (IDs matter). Full checklist and channel notes: `[openems-testing-platform-todo.md](openems-testing-platform-todo.md)` §3.

### 2.1 Core


| Component                    | ID / notes                 |
| ---------------------------- | -------------------------- |
| Scheduler All Alphabetically | `scheduler0`               |
| Controller Debug Log         | `ctrlDebugLog0` (optional) |
| Controller Api Websocket     | Port **8085** (UI ↔ Edge)  |




### 2.2 Simulators (minimal Earnie plant)


| Component                            | ID               | Notes                                                         |
| ------------------------------------ | ---------------- | ------------------------------------------------------------- |
| Simulator DataSource: CSV Predefined | `datasource0`    | e.g. household summer profile                                 |
| Simulator GridMeter Acting           | `meter0`         | Datasource `datasource0`                                      |
| Simulator DataSource: CSV Predefined | `datasource1`    | PV-ish / varying                                              |
| Simulator ProductionMeter Acting     | `meter1`         | Datasource `datasource1`                                      |
| Simulator EssSymmetric Reacting      | `ess0`           | Defaults OK                                                   |
| Controller Ess Balancing             | `ctrlBalancing0` | Ess `ess0`, Grid-Meter `meter0` (optional for telemetry-only) |
| Simulator Evcs                       | `evcs0`          | Required for 2.4.b EVCS path                                  |




### 2.3 REST API (required for Earnie)


| Component                           | Factory                         | Notes                                                                         |
| ----------------------------------- | ------------------------------- | ----------------------------------------------------------------------------- |
| Controller Api Rest/Json Read-Write | `Controller.Api.Rest.ReadWrite` | Port **8084**; Basic auth `x` + password of OpenEMS user (`admin` for writes) |


Without this controller, host port 8084 may be open but REST returns connection errors / empty — Earnie cannot talk.

---



## 3. Communication checks (do in order)

Use `curl.exe` on Windows PowerShell (`curl` alone is `Invoke-WebRequest`).

### 3.1 Host → Edge REST (OpenEMS alone)

```powershell
curl.exe -u x:admin http://127.0.0.1:8084/rest/channel/_sum/GridActivePower
curl.exe -u x:admin http://127.0.0.1:8084/rest/channel/_sum/ProductionActivePower
curl.exe -u x:admin http://127.0.0.1:8084/rest/channel/_sum/EssSoc
curl.exe -u x:admin http://127.0.0.1:8084/rest/channel/ess0/Soc
curl.exe -u x:admin http://127.0.0.1:8084/rest/channel/evcs0/ActivePower
```

**Pass:** JSON with a numeric `"value"`.  
**Fail:** connection refused → Edge/port map; 401 → auth; 404 → component/REST controller missing.

Optional write (admin):

```powershell
curl.exe -X POST -u x:admin -H "Content-Type: application/json" -d '{"value": 1000}' http://127.0.0.1:8084/rest/channel/ess0/SetActivePowerEquals
curl.exe -u x:admin http://127.0.0.1:8084/rest/channel/ess0/ActivePower
```



### 3.2 Earnie container → Edge (Docker DNS)

```powershell
docker exec earnie-openems-lab wget -qO- --user=x --password=admin http://openems-edge:8084/rest/channel/ess0/Soc
```

If `wget` is missing, try:

```powershell
docker exec earnie-openems-lab python -c "import requests; r=requests.get('http://openems-edge:8084/rest/channel/ess0/Soc', auth=('x','admin'), timeout=10); print(r.status_code, r.text)"
```

**Pass:** same SoC JSON as on the host.  
**Fail here but 3.1 OK:** wrong `base_url` in config, or Earnie not on the Compose network with Edge.

### 3.3 Earnie Live / adapter path

```powershell
docker logs earnie-openems-lab --tail 200
```

Or follow:

```powershell
docker compose --project-directory . -f docker/compose/openems-lab.yml logs -f earnie
```


| Log signal                                               | Meaning                                                     |
| -------------------------------------------------------- | ----------------------------------------------------------- |
| `Kein Zugriff auf EHAL/OpenEMS SoC`                      | Backend is openems, but REST/SoC failed                     |
| `Optimierung abgebrochen: Kein Zugriff auf Loxone SoC`   | `ehal.backend` **not set to** `openems` (still Loxone path) |
| Live continues after SoC / live power lines              | Read path OK                                                |
| `Sende EHAL ESS-Limits an OpenEMS`                       | Write path attempted (silent mode off)                      |
| `Silent-Modus aktiv: … ohne Schreibzugriffe auf OpenEMS` | Reads OK; writes gated                                      |


UI: **[http://localhost:8503](http://localhost:8503)** → Daemon / Loxone-Kommunikation — watch for EHAL write-error banner (`runtime/ehal_write_error.json`).

### 3.4 Optional: adapter smoke from inside Earnie

Only after `ehal` is in `config.json` and Edge plant exists. Prefer observing `main.py` logs (above). Unit tests use mocks and do **not** hit the lab (`tests/test_openems_adapter.py`).

---



## 4. Acceptance checklist

- [ ] `docker ps`: three lab containers; ports as in §0
- [ ] `openems_lab/config/config.json` contains `ehal.backend=openems` and `base_url=http://openems-edge:8084`
- [ ] OpenEMS: `ess0`, meters, REST ReadWrite on 8084; preferably `evcs0`
- [ ] Host curl SoC / grid returns JSON (§3.1)
- [ ] `docker exec` from Earnie to `openems-edge:8084` returns JSON (§3.2)
- [ ] Earnie logs show OpenEMS SoC success, not Loxone SoC abort (§3.3)
- [ ] (Optional) Write test host + Live with `loxone_silent_mode: false`

---



## 5. Troubleshooting


| Symptom                            | Likely cause                                   | Fix                                                      |
| ---------------------------------- | ---------------------------------------------- | -------------------------------------------------------- |
| `:8084` connect then reset / HTML  | 8084 mapped on **UI** nginx                    | Move `8084:8084` to `openems-edge` only; recreate        |
| UI `:8088` 404, Felix OK           | Stale `openems-ui-conf` volume                 | Recreate UI volumes (see platform TODO §2)               |
| Earnie SoC abort, Loxone message   | Missing / wrong `ehal` block                   | Merge snippet; restart `earnie`                          |
| Earnie SoC abort, OpenEMS message  | Edge plant / REST / auth / URL                 | Fix §2 + §3.1–3.2                                        |
| `base_url` localhost in container  | Wrong URL                                      | Use `http://openems-edge:8084`                           |
| UI live view blank                 | `WEBSOCKET_HOST` not LAN IP                    | Set `OPENEMS_UI_WEBSOCKET_HOST`, recreate UI             |
| Writes never sent                  | Silent mode                                    | `local_settings.json` → `loxone_silent_mode: false`      |
| Empty `openems_lab/config` on disk | Compose not from repo root / wrong project-dir | Re-up with `--project-directory .` from Energy-Optimizer |


---



## 6. Stack lifecycle

```powershell
# Start / rebuild
docker compose --project-directory . -f docker/compose/openems-lab.yml up -d --build

# Stop (named OpenEMS volumes retained; bind mounts kept)
docker compose --project-directory . -f docker/compose/openems-lab.yml down

# Wipe Edge plant (destructive — re-do §2)
docker compose --project-directory . -f docker/compose/openems-lab.yml down
docker volume ls
# docker volume rm <project>_openems-edge-conf <project>_openems-edge-data …
```

---



## Quick references

- OpenEMS Docker: [https://openems.github.io/openems.io/openems/latest/edge/deploy/docker.html](https://openems.github.io/openems.io/openems/latest/edge/deploy/docker.html)  
- Simulated components: [https://openems.github.io/openems.io/openems/latest/edge/core.d/io.openems.edge.simulator.html](https://openems.github.io/openems.io/openems/latest/edge/core.d/io.openems.edge.simulator.html)  
- REST API: [https://openems.github.io/openems.io/openems/latest/edge/controller.d/io.openems.edge.controller.api.rest.html](https://openems.github.io/openems.io/openems/latest/edge/controller.d/io.openems.edge.controller.api.rest.html)  
- Backlog: `backlog/Backlog.md` → `2.4.b`

