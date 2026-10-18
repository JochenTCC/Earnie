# HA + evcc lab setup — Earnie ↔ Home Assistant

**Status:** current  
**Purpose:** Bring up and configure the **combined** Compose stack (`earnie` + `homeassistant` + `evcc`) so you can prove Earnie talks to Home Assistant over the **push HTTP contract** (HA → Earnie telemetry on **:8541**, HA polls `status.json` for setpoints). REST pull of `/api/states` for live I/O is **removed**.

**Audience:** Operator of the lab on a Dev-PC or Pi. Containers may already be running; this guide finishes **HA onboarding**, **token**, **evcc**, **Earnie HA Anbindung** (`.env` + activated signals + carrier YAML), and a **communication check**.

**German user overview (A2 vs B):** [`docs/einrichtung/ha-evcc.md`](../einrichtung/ha-evcc.md)

**Related:**

| Doc | Role |
| --- | --- |
| [`docker/compose/ha-lab.yml`](../../docker/compose/ha-lab.yml) | Reference Compose |
| [`ehal.md`](../referenz/ehal.md) | Frozen EHAL contract + HA push notes |
| [`ehal-com.md`](../ui/ehal-com.md) | Signalliste + HA YAML download |
| [`house-sim.md`](house-sim.md) | HouseSim contract / push harness (`house_sim/`, not this Compose stack) |
| [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) | Config fragment to merge into Earnie `config.json` (no `transport`) |
| [`ha_lab/evcc/evcc.yaml`](../../ha_lab/evcc/evcc.yaml) | Committed lab stub (const meters / demo charger) |
| [`ha_lab/evcc/evcc.example.yaml`](../../ha_lab/evcc/evcc.example.yaml) | Commented Earnie-mode template |
| [`openems-lab-setup.md`](openems-lab-setup.md) | Sibling Path C (OpenEMS) — config-switch peer |

---

## Goal (done when)

1. Host can open HA UI on **:8123**, finish onboarding, and create a **Long-Lived Access Token** (still useful for HA Developer tools / optional Earnie `.env`).
2. Earnie listens on **:8541** with `EARNIE_PILOT_PUSH_TOKEN` set; HA can reach that port (Compose service name or host).
3. Required EHAL signals are **activated** (Hauskonfigurator / migration); HA helpers or evcc entities exist for those fields.
4. Carrier YAML is generated, `ENTITY_*` placeholders filled, package loaded in HA; periodic push reaches Earnie.
5. Live cycle with `ehal.backend=ha` shows SoC / powers in EHAL-Com **Live-Lesen** (push inbox — not “Kein Zugriff auf EHAL SoC”).
6. Optional write path: setpoints appear in `GET /ehal/status.json`; HA automations apply them when silent mode is **off**.

---

## Architecture (who talks to whom)

```text
Browser ──► :8506 ──► earnie-ha-lab (Streamlit + main.py)
                              ▲
                              │ :8541  GET /ehal/telemetry/<qid>/<v>   (HA rest_command)
                              │ :8541  GET /ehal/status.json          (HA REST sensor / poll)
                              │
Host/PC ──► :8123 ──► homeassistant  (entities + generated earnie_ha_carrier.yaml)
                              ▲
                              │ entities (MQTT discovery / HA integration / helpers)
Host/PC ──► :7070 ──► evcc (device I/O sidecar — not Earnie’s API target)
```

| Audience | Earnie daemon HTTP (push) | Optional HA REST (credentials / Dev tools) |
| --- | --- | --- |
| HA **inside** Compose → Earnie | `http://earnie-ha-lab:8541` | Earnie `.env` may still hold `EHAL_HA_BASE_URL=http://homeassistant:8123` |
| HA on host → Earnie on host | `http://localhost:8541` (or LAN IP) | `http://localhost:8123` |
| curl / browser on the **Docker host** | Earnie UI `:8506`, daemon `:8541`, HA `:8123` | — |
| Another PC on the LAN | `http://<lab-host-lan-ip>:8541` | `http://<lab-host-lan-ip>:8123` |

**Volumes (bind mounts from repo root):**

| Host path | Container |
| --- | --- |
| `./ha_lab/config` | `/app/config` (Earnie) |
| `./ha_lab/runtime` | `/app/runtime` (Earnie) |
| `./ha_lab/homeassistant` | `/config` (HA) |
| `./ha_lab/evcc/evcc.yaml` | `/etc/evcc.yaml` (evcc, read-only) |

If `ha_lab/config` only contains `.gitkeep`, Earnie has **no** `ehal` block yet — Live still uses the Loxone path and cannot talk to HA.

**Compliance:** Separate Works containers. Earnie uses HTTP/`requests` only — no HA or evcc Python libs in the Earnie image. Prefer **stable HA entities** (often from evcc); do **not** point Earnie at evcc’s native REST/MQTT API in this lab.

---

## 0. Prerequisites and first start

- Docker Desktop / Engine with Compose v2
- Free host ports **8506**, **8541**, **8123**, **7070** (see [`streamlit-ports.md`](streamlit-ports.md))
- Stop stacks that collide on those ports (OpenEMS lab uses **8503**; prod often **8501**)

From **repo root**:

```powershell
mkdir ha_lab\config, ha_lab\runtime, ha_lab\homeassistant, ha_lab\evcc -Force
# ha_lab\evcc\evcc.yaml is already in the repo (lab stub). To reset from the template:
# Copy-Item ha_lab\evcc\evcc.example.yaml ha_lab\evcc\evcc.yaml -Force
docker compose --project-directory . -f docker/compose/ha-lab.yml up -d --build
docker compose --project-directory . -f docker/compose/ha-lab.yml ps
```

Expect containers: `earnie-ha-lab`, `earnie_homeassistant`, `earnie_evcc` — all running (or restarting while HA first-boot finishes). One-shot `earnie_hacs_init` downloads HACS into `ha_lab/homeassistant/custom_components/hacs` (idempotent), then exits `0`; HA waits for it before start.

| Service | URL |
| --- | --- |
| Earnie Streamlit | http://localhost:8506 |
| Home Assistant | http://localhost:8123 |
| evcc UI | http://localhost:7070 |

Pinned images (see compose): HA `ghcr.io/home-assistant/home-assistant:2025.7.0`, evcc `evcc/evcc:0.207.0`. Bump only after a known-good lab smoke.

---

## 1. Home Assistant onboarding

HA config persists under `ha_lab/homeassistant/` (empty on first run → first-boot wizard).

### 1.1 Open the UI

1. Wait until http://localhost:8123 answers (first start can take 1–3 minutes; watch `docker logs earnie_homeassistant`).
2. Browser: **Create my smart home** / create owner account (name, username, password). Store credentials in your password manager — this lab volume is local but not encrypted for you.
3. **Location:** set a plausible home location (timezone should match Earnie / Compose `TZ=Europe/Vienna` when possible).
4. Skip or accept analytics as you prefer — not required for EHAL.
5. Finish the wizard until you reach the HA overview / dashboard.

### 1.2 Lab-only tips

- You do **not** need cloud / Nabu Casa for Earnie REST.
- Keep the install offline-capable: Earnie only needs LAN reachability to `:8123`.
- If you wipe the lab: stop Compose, delete contents of `ha_lab/homeassistant/` (keep the directory), start again → new onboarding.

### 1.3 Optional: Mosquitto for evcc → HA (recommended when using real/template meters)

evcc commonly publishes entities via **MQTT discovery**. On a greenfield lab:

1. **Settings → Add-ons → Add-on store** (Supervisor / HA OS).  
   **Note:** The official `home-assistant` **Container** image used in this Compose is **not** full HA OS — there is **no** Supervisor add-on store.
2. For this Compose (Container install), run a **separate MQTT broker** on the Docker network (e.g. add an `eclipse-mosquitto` service later) **or** use the dry-run helper path in §3.3 without MQTT.
3. If you already run Mosquitto elsewhere, note host/port for `evcc.yaml` `mqtt:` (from evcc container, broker hostname is often `homeassistant` only if Mosquitto is co-located — otherwise use the Mosquitto service name / host LAN IP).

---

## 2. Long-Lived Access Token (LLAT)

Earnie authenticates with a **Bearer** token. Do **not** put interactive user passwords in `config.json`.

### 2.1 Create the token

1. In HA, open your **user profile** (bottom-left avatar / your name).
2. Open the **Security** tab (wording may be “Long-lived access tokens” under profile).
3. Under **Long-Lived Access Tokens** → **Create Token**.
4. Name it clearly, e.g. `earnie-ha-lab`.
5. **Copy the token immediately** — HA shows it **once**. If you lose it, delete the token and create a new one.

### 2.2 Smoke-test the token from the Docker host

PowerShell:

```powershell
$token = "<paste-token-here>"
Invoke-RestMethod -Uri "http://localhost:8123/api/" -Headers @{ Authorization = "Bearer $token" }
```

Expect JSON roughly like `{ "message": "API running." }`.

HTTP 401 → wrong/expired token or missing `Bearer ` prefix.  
Connection refused → HA not ready or wrong port.

### 2.3 Where Earnie stores the token

- Prefer Streamlit **Daemon Control → Smarthome-Backend** for `ehal.backend=ha` + URL/token (writes `EHAL_HA_*` into `config/.env`; optional `sign` stays in `config.json` → `ehal.ha`). Do **not** set `ehal.ha.transport` (removed).
- Activate signals via the Hauskonfigurator (required keys) and the EHAL-Com **Signalliste** (optional toggles). Earnie stores empty activation flags — no HA `entity_id`.
- Download / generate the **HA YAML package** (§5) and bind real entities in HA by replacing `ENTITY_*`.
- Or merge [`ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) for `backend` / `adapter_id` / `sign` only — the snippet has **no** `token` / `base_url` / `transport` keys.

Treat `config/.env` as secret-bearing. Do not commit lab tokens (`EARNIE_PILOT_PUSH_TOKEN`, `EHAL_HA_TOKEN`).

---

## 3. Configure evcc (Earnie mode)

### 3.1 Role of evcc in this stack

| Does | Does not |
| --- | --- |
| Talk to meters / inverter / wallbox (Modbus, OCPP, templates, …) | Own 48h spot / surplus optimization while Earnie is in charge |
| Expose stable readings + writable limits into **Home Assistant** | Serve as Earnie’s southbound API (Earnie → HA only) |

**Modbus rule:** exactly **one** writing southbound owner per physical bus/device (typically **evcc**, not Earnie + another HA Modbus integration in parallel).

### 3.2 Files

| File | Use |
| --- | --- |
| `ha_lab/evcc/evcc.yaml` | Mounted into the container — **edit this** for the running lab |
| `ha_lab/evcc/evcc.example.yaml` | Documented Earnie-mode skeleton (MQTT hints, no smart planner) |

After editing `evcc.yaml`:

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml restart evcc
docker logs earnie_evcc --tail 80
```

Open http://localhost:7070 — UI should load; fix YAML errors from the logs if the container restarts in a loop.

### 3.3 Path A — Dry-run without hardware (HA helpers)

Use this to prove Earnie ↔ HA **push** **before** wiring real devices:

1. In HA: **Settings → Devices & services → Helpers** (or YAML `input_number` / `sensor` templates).
2. Create helpers that cover required reads / writes, for example:
   - `sensor` or template sensors: grid W, PV W, battery SoC %, optional battery power W, EVCS power W  
   - `input_number` / `number`: charge limit W, discharge limit W, EVCS max current A
3. Skip evcc entity exposure for this path (evcc stub can keep running idle).
4. Activate the matching EHAL signals in Earnie, generate the carrier YAML (§5), and put the helper `entity_id`s into the `ENTITY_*` placeholders.

Sign convention in EHAL: `sens_grid_power_active` **+** = import; `sens_ess_power` **+** = discharge. Prefer helpers that already match; otherwise adjust the Jinja / entity choice in the package (Earnie does not pull HA units at runtime).

### 3.4 Path B — Lab stub / templates in `evcc.yaml`

The committed stub uses `custom` const **meters** (0 W, SoC 50 %) and the built-in **`demo-charger`** template (status A). It is enough to keep the **evcc process** healthy; it does **not** automatically create HA entities until you add MQTT/integration.

Do **not** use `type: custom` with `maxcurrent: source: const` or a `maxcurrentout` key — evcc 0.207 fails decode (`cannot create charger type 'custom': decoding failed`). For a hand-rolled custom charger, `maxcurrent` / `enable` must be writable plugins (`js` / `script` / `http` / `mqtt`); see the upstream `demo-charger` template.

To grow toward real templates (see evcc docs for current template names):

- Replace `meters` / `chargers` with `type: template` + manufacturer templates, **or** keep `custom` getters for meters and a valid custom/demo charger.
- Set loadpoint `mode: now` (or another mode that still allows **external maxcurrent** writes). Avoid surplus / min+PV / smart-cost modes that fight Earnie.
- **Do not** enable site tariff planners as Earnie’s price source — leave tariffs empty or diagnostic-only.

### 3.5 Expose evcc entities into Home Assistant

Pick one lab approach:

**Option 1 — MQTT discovery (common)**

1. Run Mosquitto reachable from both HA and evcc (§1.3).
2. In `evcc.yaml`, configure `mqtt:` (broker, topic prefix, credentials if any).
3. In HA, add the **MQTT** integration pointing at that broker.
4. Restart evcc; confirm new `sensor.evcc_*` / `number.evcc_*` (names vary by version/loadpoint title) under **Developer tools → States**.

**Option 2 — Community HA ↔ evcc integration (recommended by evcc docs)**

Upstream points to the community integration **[marq24/ha-evcc](https://github.com/marq24/ha-evcc)**
(“evcc☀️🚘- Solar Charging”), also documented at
[docs.evcc.io → Home Assistant](https://docs.evcc.io/en/integrations/home-assistant).
There is **no** built-in core HA integration for this lab pin; treat HACS / manual
`custom_components` as the normal path.

**Lab constraint (this Compose):** the image is HA **Container**, not HA OS —
there is **no** Supervisor add-on store. Compose seeds **HACS files** via the
one-shot `hacs-init` service (`ha_lab/homeassistant/custom_components/hacs`);
you still activate HACS once in the UI (GitHub device OAuth). Fallback without
HACS: copy upstream `custom_components/evcc_intg` into that same tree yourself.

1. **Prerequisites**
   - evcc healthy (§3.2): UI answers on host `:7070`; logs show site + loadpoint.
   - From inside the HA container, evcc must be reachable on the Compose network.
   - Confirm HACS files exist (after §0 `up`): host path
     `ha_lab/homeassistant/custom_components/hacs/manifest.json`, or
     `docker logs earnie_hacs_init` shows download complete / already present.
   - If HA was already running before `hacs-init` added files, restart it once:
     `docker compose --project-directory . -f docker/compose/ha-lab.yml restart homeassistant`.

2. **Activate HACS in HA (once)**
   - Clear browser cache / hard refresh if HACS does not appear in the picker.
   - **Settings → Devices & services → Add integration** → **HACS**.
   - Acknowledge the prompts → complete **GitHub device OAuth**
     ([HACS initial configuration](https://www.hacs.xyz/docs/use/configuration/basic/)).

3. **Install the evcc integration**
   - **Preferred:** HACS → search `evcc` → install **evcc☀️🚘- Solar Charging** (marq24) →
     **restart Home Assistant**.
   - **Without HACS:** copy upstream `custom_components/evcc_intg/` into
     `ha_lab/homeassistant/custom_components/evcc_intg/`, then restart HA
     (`docker compose … restart homeassistant`).

4. **Add the integration**
   - **Settings → Devices & services → Add integration** → search `evcc`.
   - **URL (critical for this lab):** use the Docker service name, **not** `localhost`:

     ```text
     http://evcc:7070
     ```

     (`localhost:7070` is only valid on the Docker **host** browser, not from the
     `homeassistant` container.)
   - Give a short unique name (becomes the `entity_id` prefix, e.g. `evcc_…`).
   - Optional: area. Admin password only if you need extra meter/vehicle entities
     from newer integration versions — store only if you accept HA holding that
     credential.

5. **Verify entities**
   - **Settings → Devices & services → evcc** → open the device(s).
   - **Developer tools → States** and filter by your prefix / `evcc`.
   - Expect site meters (grid / PV / battery SoC & power) and loadpoint entities
     (charge power, max current / mode as `number`/`select` where exposed).
   - Names vary by integration version and the name you chose — **copy the exact
     `entity_id`s**; do not assume the placeholders in
     [`share/config/ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json).

6. **Wire into the carrier YAML (§5 / §5.1)**
   - Prefer stable entities that survive HA/evcc restarts.
   - Reads: grid W, PV W, SoC % (required); ESS power / EVCS power optional.
   - Writes (if present): charge/discharge limits, loadpoint max current.
   - Sign: EHAL grid **+** = import, ESS **+** = discharge; choose entities / Jinja
     so the pushed value matches.
   - When the integration is already green: follow **§5.1** (copy IDs → YAML
     placeholders → accept table).

7. **Earnie-mode cautions**
   - Do **not** use HA automations that write the same setpoint entities Earnie owns
     (except the generated carrier setpoint automations).
   - Keep evcc loadpoint mode compatible with external max-current (§3.4 / §3.6) —
     no competing surplus / smart-cost planner.
   - Live path is HA → Earnie **push** on **:8541** plus HA poll of `status.json`;
     Earnie must not call the evcc API directly.

8. **If discovery fails**
   - From the HA network: reachability check to `http://evcc:7070` inside the
     `homeassistant` container (e.g. `wget` / `curl` if available).
   - Wrong URL (`localhost`, host LAN IP without Docker routing) is the usual cause.
   - Fall back to **Option 1** (MQTT) or **§3.3** helpers.

**Option 3 — Manual REST sensors / template sensors** (fallback)

Only if discovery is blocked: mirror a few values with HA REST/template sensors. Prefer Options 1–2 for A2 realism.

### 3.6 Earnie-mode checklist (optimizer exclusivity)

- [ ] evcc: no surplus / smart-cost / spot charge planner fighting Earnie
- [ ] Loadpoint allows Earnie to set max current (via HA `number` / equivalent)
- [ ] Battery charge/discharge limits (if used) only via mapped write entities
- [ ] No HA automations writing the same setpoint entities Earnie owns
- [ ] Spot prices + 48h schedule come from **Earnie** only
- [ ] **Modbus:** one writing owner per bus/device (typically evcc)

---

## 4. Earnie config (`ha_lab/`)

### 4.1 Bootstrap if empty

With empty `ha_lab/config` + `ha_lab/runtime`, restart Earnie so the entrypoint can run bootstrap:

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml restart earnie
```

Expect on the host:

| Path | Expectation |
| --- | --- |
| `ha_lab/config/config.json` | Exists |
| `ha_lab/config/.env` | Exists (Loxone verify is off via Compose env) |
| `ha_lab/runtime/local_settings.json` | Exists |

### 4.2 Enable HA backend

Either:

1. **UI (preferred):** **Smarthome-Backend** for `ehal.backend=ha` + URL/token → `config/.env`; optional `ehal.ha.sign`. Activate components in the Hauskonfigurator so required EHAL keys exist.
2. **Manual merge:** copy the `ehal` object from [`ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json) into `ha_lab/config/config.json` (backend + `sign` only — **no** `transport`). Put URL/token and `EARNIE_PILOT_PUSH_TOKEN` into `ha_lab/config/.env`. Do **not** store HA `entity_id`s in Earnie bindings (activation keys only).

Inside Compose, if `EHAL_HA_*` is set, `EHAL_HA_BASE_URL` is typically:

```text
http://homeassistant:8123
```

Silent gate: `loxone_silent_mode` also blocks HA setpoint publish (same as OpenEMS). Turn silent **off** only when you intend to write.

---

## 5. Push carrier YAML (lab path)

Live I/O is **push-only**. There is no HA entity-mapping UI on EHAL-Com.

1. Ensure Earnie listens on **`system.ehal_loxone_http_port`** (default **8541**) and `EARNIE_PILOT_PUSH_TOKEN` is set in `ha_lab/config/.env`.
2. Confirm required signals are activated (Signalliste: Pflicht = ja, aktiviert = ja). Toggle optional signals as needed.
3. Generate the carrier package (UI: **EHAL-Com → HA Push-Carrier → YAML-Paket**, or CLI):

```powershell
.venv\Scripts\python.exe -m scripts.ha_carrier_yaml_gen --config-dir ha_lab\config --host earnie-ha-lab --port 8541 --out ha_lab\homeassistant\packages\earnie_ha_carrier.yaml
```

4. In the YAML, replace every `ENTITY_*` placeholder with a real HA `entity_id` (helpers Path A, or marq24/evcc entities §5.1). Keep the generated **periodic** automations (`time_pattern` = repeat interval, default **10 s**) — do not switch them to “on change only” (silent power would be assumed 0 while the heartbeat is fresh; energy is never assumed 0).
5. Load the package in HA (`packages:` / include) and restart HA if needed. Jinja already converts W/kW/MW → W and Wh/kWh/MWh → kWh before the push URL.
6. **Read check:** values appear in EHAL-Com **Live-Lesen** (inbox age / push state).
7. **Write check:** with silent mode off, setpoints land in `GET /ehal/status.json`; Schreibtest success = published ledger + HA fetched status.json (`published_fetched_at`). `ha_ess_force` is emitted as YAML setpoint automation(s) when configured.

Cadence details: [`loxone-signals.md` § push cadence](../referenz/loxone-signals.md#push-cadence-sb-neutral). Contract overview: [`ehal.md`](../referenz/ehal.md) § Home Assistant.

### 5.1 After marq24 ha-evcc is connected (lab follow-up)

Use this when HACS + **evcc☀️🚘- Solar Charging** are already installed and the
integration reaches `http://evcc:7070` (§3.5 Option 2). Goal: stable HA
`sensor`/`number` entities wired into the **carrier YAML** (Path A helpers smoke is **not**
enough for this follow-up).

**A — Copy exact `entity_id`s from HA**

1. HA → **Developer tools → States**. Filter by the name you gave the
   integration (often `evcc`) or by `evcc`.
2. Prefer entities that survive HA/evcc restarts (integration device entities,
   not one-off helpers).
3. With the committed lab stub (`ha_lab/evcc/evcc.yaml`), expect **const**
   values (grid/PV/charge power **0 W**, battery SoC **50 %**). That is enough
   to prove the path; non-zero values need real meters or a richer stub.
4. Typical roles (names **vary** by integration version and the unique name you
   chose — **never** paste snippet placeholders blindly):

| Role | Domain | What to look for in States |
| --- | --- | --- |
| Grid power | `sensor` | site / grid power (W or kW) |
| PV power | `sensor` | PV / solar power |
| Battery SoC | `sensor` | battery SoC (%) |
| Battery power | `sensor` | battery power (optional) |
| Loadpoint charge power | `sensor` | loadpoint / charge power (optional) |
| Max charge current | `number` | loadpoint max current (A) — write path |
| Battery charge/discharge limits | `number` | only if the integration exposes them |

**B — Wire into the YAML package (§5)**

1. Earnie http://localhost:8506 → **EHAL-Com** → activate required signals → download / regenerate YAML.
2. Host for Compose HA → Earnie: `earnie-ha-lab`, port **8541**, plus the push token.
3. Replace `ENTITY_*` for at least the required reads (`sens_grid_power_active`, `sens_pv_production_active`, `ess.{id}.sens_ess_soc`).
4. Optional: power, EVCS current, ESS limit numbers if present.
5. Sign: EHAL grid **+** = import, ESS **+** = discharge — pick entities / Jinja so the pushed value matches.
6. Reload HA package → Live-Lesen shows SoC ~50 and powers ~0 with the lab stub.

**C — Accept (follow-up done)**

| Check | Pass |
| --- | --- |
| HA States shows the entities used in `ENTITY_*` | yes |
| Periodic push reaches Earnie (Live-Lesen OK / push state) | yes |
| `ha_lab/config/config.json` has `ehal.backend=ha`; **no** `ehal.ha.transport` | yes |
| Live / logs: no “Kein Zugriff auf EHAL SoC” (§6.3) | yes |
| Optimizer exclusivity still true (§3.6) | yes |

Write setpoints remain optional for this follow-up; keep silent mode **on**
until you intentionally test writes (§6.4).

---

## 6. Communication check

### 6.1 Host → Earnie daemon (push)

```powershell
$token = "<EARNIE_PILOT_PUSH_TOKEN>"
Invoke-RestMethod -Uri "http://localhost:8541/ehal/telemetry/heartbeat/1?t=$token"
Invoke-RestMethod -Uri "http://localhost:8541/ehal/status.json?t=$token"
```

### 6.2 Host → HA API (optional Dev tools)

```powershell
$token = "<LLAT>"
Invoke-RestMethod -Uri "http://localhost:8123/api/" -Headers @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Uri "http://localhost:8123/api/states/sensor.YOUR_SOC_ENTITY" -Headers @{ Authorization = "Bearer $token" }
```

### 6.3 Earnie Live

1. Confirm `ehal.backend` is `ha` in `ha_lab/config/config.json` and `ehal.ha.transport` is absent.  
2. Watch logs: `docker logs earnie-ha-lab --tail 100 -f`  
3. Expect SoC / live power in Live-Lesen from the push inbox (no “Kein Zugriff auf EHAL SoC”).  
4. With silent mode **off**, a cycle publishes ESS/EVCS setpoints to `status.json`; HA automations apply them. Failures → Streamlit EHAL write-error banner + `ha_lab/runtime/ehal_write_error.json`.

### 6.4 Negative write / cadence test

- Point a setpoint automation at a read-only entity (or break the service call) → expect write-error document / failed apply — same degrade path as OpenEMS.
- Stop periodic push for a power signal while heartbeat stays fresh → Live-Lesen shows assumed **0** (`0 angenommen (verstummt)`). Energy counters must not invent 0 when silent.

---

## 7. Config switch vs OpenEMS

Same Earnie Core: change only `ehal.backend` (`ha` vs `openems` vs `loxone`) and the matching hub block. Mocked parity: `tests/test_ehal_contract_backends.py`.

Do **not** run OpenEMS lab and HA lab on the same host ports without remapping.

---

## 8. Stop / reset

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml down
```

Bind mounts (`ha_lab/…`) are kept. To factory-reset HA only, remove files under `ha_lab/homeassistant/` and start again.

---

## Out of scope here

- HA WebSocket state subscription
- Direct evcc REST/MQTT adapter from Earnie (lab-only option deferred)
- REST pull / HITL entity-mapping UI (removed)
- Shipping the YAML package inside the HA add-on image (tracked for Add-on 1.0 in the separate [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) repo; lab uses download / CLI gen)
