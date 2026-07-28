# EHAL — Earnie Hardware Access Layer (M1 freeze)

**Backlog:** `2.4.a` (Phase 1 / M1 spec)  
**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 §2.2, §2.5 Phase 1, §2.6  
**Schemas:** [`share/ehal/`](../../share/ehal/)  
**Python:** [`ehal/`](../../ehal/)  
**Lab mapping (OpenEMS):** [`openems-testing-platform-todo.md`](openems-testing-platform-todo.md)  
**Lab setup (Compose + Earnie ↔ OpenEMS):** [`openems-lab-setup.md`](openems-lab-setup.md)  
**Lab setup (Compose + Earnie ↔ HA + evcc):** [`ha-lab-setup.md`](ha-lab-setup.md)

## Purpose and naming

**EHAL** (Earnie Hardware Access Layer) is the only southbound contract between Earnie Core (48h optimizer / Live) and hardware hubs. Wire format is normalized JSON: **Telemetry**, **Setpoints**, and **Capability-Flags**.

Do **not** call this layer “SAM” (Businessplan “SAM” = market size only).

Earnie Core remains the sole strategic optimizer. Hubs provide I/O and device catalogs only. Adapters **translate**; they do not embed competing surplus/spot strategies into the math core.

## Core contract

| Rule | Detail |
|------|--------|
| Consumption | Optimizer / Live consume **only** EHAL types from `ehal` / these schemas |
| Hub isolation | No OpenEMS, Home Assistant, evcc, or Loxone types in the math core |
| Adapter duty | Map hub channels/entities → EHAL; normalize signs and units inside the adapter |
| Transport | Network only (REST / WebSocket / JSON). No linking or copying hub source into Earnie repos (Separate Works / AGPL shield for OpenEMS) |
| Loxone today | Default `ehal.backend=loxone` uses [`integrations/loxone_adapter.py`](../../integrations/loxone_adapter.py) for M1 plant telemetry; Huawei extras + flex remain on `loxone_client` (not first-class EHAL fields) |

## Schema version and envelope

Every Telemetry, Setpoint, and Capabilities document uses the same envelope fields:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | integer | yes | Wire version; **M1 = `1`** |
| `ts` | string (ISO-8601) | yes | Sample / write time with timezone (`Z` or offset). Prefer UTC. |
| `adapter_id` | string | yes | Stable adapter instance id (e.g. `openems-lab`, `ha-home`) |

**Frozen choice:** `ts` is **ISO-8601 with timezone**, not epoch milliseconds.

## Units and sign convention (frozen)

| Domain | Unit | Sign / range |
|--------|------|----------------|
| Active power telemetry (`grid_power_active`, `pv_production_active`, `evcs_active_power`, `ess_power`) | **W** | See below |
| `ess_soc` | **%** | `0`…`100` |
| ESS charge/discharge **limits** | **W** | Non-negative **magnitudes** |
| `set_evcs_max_current` | **A** | Non-negative |

**Grid (`grid_power_active`):** `+` = grid **import** (Bezug), `−` = **export** (Einspeisung). Adapters normalize hub-native signs before emit.

**PV (`pv_production_active`):** production ≥ `0` (W).

**EVCS (`evcs_active_power`):** charge power ≥ `0` (W) when charging; `0` when idle.

**ESS (`ess_power`, optional):** OpenEMS-aligned — `+` = **discharge**, `−` = **charge**. Adapters that use the opposite convention (e.g. current Loxone Live: + charge) must invert at the boundary.

## Telemetry-API (M1)

| Field | Required | Unit | Notes |
|-------|----------|------|-------|
| `grid_power_active` | yes | W | PCC active power; sign as above |
| `pv_production_active` | yes | W | ≥ 0 |
| `ess_soc` | yes | % | Home battery SoC |
| `ess_power` | no | W | Optional; sign as above |
| `evcs_active_power` | no | W | ≥ 0 when present |

Machine schema: [`share/ehal/telemetry.schema.json`](../../share/ehal/telemetry.schema.json).

## Setpoint-API (M1)

Setpoints are **math limits / schedules**, not realtime inner-loop control. Realtime enforcement stays in the subsystem (OpenEMS / HA / inverter).

| Field | Required in doc | Unit | Notes |
|-------|-----------------|------|-------|
| `set_ess_charge_power_limit` | no* | W | Max charge power (magnitude ≥ 0) |
| `set_ess_discharge_power_limit` | no* | W | Max discharge power (magnitude ≥ 0) |
| `set_evcs_max_current` | no* | A | Max EV charge current (magnitude ≥ 0) |

\*A setpoint document must include **at least one** of these fields (plus envelope). Partial updates are allowed; omitted fields mean “leave unchanged” at the adapter.

Machine schema: [`share/ehal/setpoint.schema.json`](../../share/ehal/setpoint.schema.json).

## Capability-Flags (M1)

| Field | Required | Meaning |
|-------|----------|---------|
| `supports_ess_write` | yes | ESS limit setpoints can be written |
| `supports_evcs_current` | yes | `set_evcs_max_current` can be written |

Additional boolean flags may be added in later `schema_version` values without removing these two.

Machine schema: [`share/ehal/capabilities.schema.json`](../../share/ehal/capabilities.schema.json).

## Update interval and stale behavior

| Topic | Freeze |
|-------|--------|
| Minimum telemetry cadence toward Core | **60 s** |
| Faster internal polling | Allowed inside the adapter |
| Stale samples | Core must tolerate unchanged values until the next sample; adapters should still refresh `ts` when re-publishing |
| Missing **optional** telemetry | Omit field or set `null` per schema (`ess_power`, `evcs_active_power`) |
| Missing **required** `ess_soc` (Live) | Abort the Live run (same hard requirement as today’s house SOC) |
| Missing required power telemetry | Do not invent zeros; surface error / skip overlay as documented by the Live path |

## Write failures and degrade

On failed setpoint writes (OEM locks, read-only REST, missing HA write entities):

1. Catch the error; **do not crash** the optimizer.
2. Log with enough context for support (adapter_id, field, hub status/message).
3. Flip the matching capability flag (`supports_ess_write=false` and/or `supports_evcs_current=false`).
4. Emit **Write-Error-Telemetry** (see below) so UI can show a user hint.
5. Continue with read-only / degraded control for that subsystem.

### Write-Error-Telemetry shape

Envelope fields plus:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `failed_fields` | array of string | yes | EHAL setpoint field names that failed |
| `message` | string | yes | Human-readable summary (may be shown in UI) |
| `hub_status` | string or null | no | Hub HTTP/RPC status or code if available |
| `retryable` | boolean | yes | Hint whether a later write may succeed |

Machine schema: [`share/ehal/write_error.schema.json`](../../share/ehal/write_error.schema.json).

## Fehlertoleranz (M1 defaults)

| Situation | Behavior |
|-----------|----------|
| Optional telemetry absent | Omit / null; Core continues |
| Required `ess_soc` absent | Live abort |
| Setpoint write fails | Log + capability degrade + Write-Error-Telemetry; optimizer continues |
| Capability false from start | Skip writes for that family; no repeated error spam beyond periodic hint |
| Schema validation fail | Reject document; adapter must not pass invalid JSON to Core |

Numeric hub-tolerance thresholds beyond the above are left to adapter implementation notes in **2.4.b** / **2.4.c**.

## OpenEMS light alignment (desk-check for 2.4.a)

M1 fields are chosen so they map to known OpenEMS Edge channels (semantic reference). **Deep** channel architecture, Compose, and lab write tests belong to **2.4.b**.

| EHAL field | OpenEMS (prototype) |
|------------|---------------------|
| `grid_power_active` | `_sum/GridActivePower` (normalize: `+` = import) |
| `pv_production_active` | `_sum/ProductionActivePower` |
| `ess_soc` | `ess0/Soc` / `_sum/EssSoc` |
| `ess_power` | ESS ActivePower (OpenEMS sign; already EHAL-aligned) |
| `evcs_active_power` | EVCS / EVSE active power channels |
| `set_ess_charge_power_limit` | e.g. `SetActivePowerGreaterOrEquals` / Equals (adapter maps magnitude) |
| `set_ess_discharge_power_limit` | e.g. `SetActivePowerLessOrEquals` |
| `set_evcs_max_current` | EVCS Max Current |

### Deferred device classes

| Class | When |
|-------|------|
| Heatpump | Not in M1 EHAL wire; **2.4.g** ships a stub role template (`share/ehal/roles/heatpump.json`); later Thermals / flex-consumer may promote fields |
| Generic consumer | Today Loxone flex markers (still pre-EHAL after **2.4.e**); **2.4.g** stub role + Loxone recipe (`share/ehal/roles/consumer.json`, `share/loxone/recipes/consumer.json`) |

## Device roles and hardware profiles (2.4.g)

M2 schema slice — **mapping aids / contribution seeds**, not a new Live I/O path. Full Community Bounty engine remains Entwicklungsplan **M4**.

| Artifact | Path | Purpose |
|----------|------|---------|
| Device-role schema | [`share/ehal/device_roles.schema.json`](../../share/ehal/device_roles.schema.json) | Groups M1 fields by role (`grid`, `pv`, `ess`, `evcs`; stubs `consumer`, `heatpump`) |
| Role instances | [`share/ehal/roles/`](../../share/ehal/roles/) | One JSON per `role_id` |
| Hardware-profile schema | [`share/hardware_profiles/hardware_profile.schema.json`](../../share/hardware_profiles/hardware_profile.schema.json) | SunSpec / proprietary Modbus outline → EHAL bindings |
| Outline examples | [`share/hardware_profiles/examples/`](../../share/hardware_profiles/examples/) | `sunspec_inverter_ess.outline.json`, `huawei_via_loxone.outline.json` |
| Loxone recipes | [`share/loxone/recipes/`](../../share/loxone/recipes/) | JSON Merker / Baustein tips → `loxone_blocks` (no `.loxone` binary) |
| Python loader | [`ehal/profiles.py`](../../ehal/profiles.py) | `list_*` / `load_*` + HITL `role_field_labels` / `group_fields_by_role` |

**Rules:** Do not invent new M1 wire fields here. Stub roles use `kind: stub`. Huawei `target_soc` / `control_cmd` stay `loxone_extra:*` in hardware outlines. HITL on EHAL-Com groups mapping rows by role label; confirm/save behavior unchanged.

## Out of scope (this freeze)

- MQTT / Matter as first-class hubs
- HA WebSocket state subscription / direct evcc REST adapter (deferred; REST HA path is **2.4.c**)
- Loxone extras as first-class EHAL fields: `target_soc`, `control_cmd`, flex enable, EV **kW** setpoint (remain on `loxone_client` after **2.4.e** M1 extraction)
- Community Bounty engine / ARP scan / profile upload (Entwicklungsplan **M4**). First Modbus/SunSpec **outline** schemas shipped in **2.4.g** under `share/hardware_profiles/` — not a runtime Modbus client.

## Implementation notes (2.4.b OpenEMS)

- Adapter: `integrations/openems_adapter.py` (REST only). Live façade: `integrations/ehal_live.py`.
- Compose lab: `docker/compose/openems-lab.yml`. Config snippet: `share/config/ehal.openems.snippet.json`. Step-by-step: [`openems-lab-setup.md`](openems-lab-setup.md).
- Cadence: Core still expects ≥ 60 s telemetry refresh; adapter may poll faster.
- EVCS: EHAL `set_evcs_max_current` (A) → OpenEMS `evcs0/SetChargePowerLimit` (W) via house-profile V/phases.
- Southbound silent gate: reuse `loxone_silent_mode` for OpenEMS writes as well.
- Write failures → `runtime/ehal_write_error.json` + UI banner on Loxone-Kommunikation / Daemon page.

## Implementation notes (2.4.c Home Assistant + evcc)

- Adapter: `integrations/ha_adapter.py` (REST only: `/api/states`, `/api/services/...`). Prefer HA entities from evcc.
- Config: `ehal.backend=ha` + `ehal.ha` (`base_url`, `token`, `entities`, optional `sign`). Snippet: `share/config/ehal.ha.snippet.json`.
- Compose lab: `docker/compose/ha-lab.yml` (Earnie :8506 + HA :8123 + evcc :7070). Setup: [`ha-lab-setup.md`](ha-lab-setup.md). German A2/B: [`../einrichtung/ha-evcc.md`](../einrichtung/ha-evcc.md).
- HITL mapping UI: Streamlit EHAL-Com expander → `ui/ehal_ha_mapping.py` (entity scan → persist mapping; no LLM in 2.4.c).
- Sign mode per field: `ehal` (already aligned) or `negate`. Units: kW states converted to W.
- Setpoints: typically `number.set_value` on mapped entities (Amps for EVCS; W for ESS limits).
- Optimizer exclusivity + single Modbus writer: see German checklist in `ha-evcc.md`.
- Same Live façade / write-error path as OpenEMS (`is_ehal_network_backend()`).

## Implementation notes (2.4.e Loxone)

- Adapter: `integrations/loxone_adapter.py` (HTTP markers via `loxone_client`). Live façade: `integrations/ehal_live.py` (`get_adapter()` includes Loxone).
- Default config: missing/`none`/`loxone` → `EHAL_BACKEND=loxone`, `adapter_id` default `loxone-home`. Marker names stay on `loxone_blocks.*` / `LOXONE_*` (no nesting rewrite).
- Telemetry: kW markers → W; Loxone battery **+charge** → EHAL `ess_power` **+discharge** (`× −1000`); grid pass-through as EHAL `+` import.
- Capabilities: `supports_ess_write` when charge/discharge markers exist; **`supports_evcs_current=false`** (EV stays on flex `power_setpoint_name`).
- Live writes for Loxone: still `send_huawei_modbus_states` + `send_flexible_consumer_states` (`is_ehal_network_backend()` remains openems|ha only). Adapter `write_setpoints` maps ESS limits for contract/future use; does **not** replace `target_soc` / `control_cmd`.
- Extras still outside M1 EHAL: `target_soc`, `control_cmd`, flex enable, EV kW, FTP/PV-counter, optimizer marker reads (EV/thermal/events).

## Implementation notes (2.4.f Loxone one-click mapping)

- Onboarding helper **inside** the Loxone-EHAL path — not a live I/O replacement. Spec: Entwicklungsplan §3.1.
- Structure scan (`integrations/loxone_structure.py`): **research compare-all** — LoxAPP3.json, HTTP marker probe, and optional official **MCP 17.1** `tools/list` each run as independent variants (default: all). UI shows comparison; mapping names default to **union**. No production winner locked yet — decide after lab data. `sources=(…)` may restrict variants for tests only.
- HITL UI: `ui/ehal_loxone_mapping.py` on EHAL-Com (backend Loxone). Proposals as EHAL fields; confirm writes flat `loxone_blocks` via `save_main_config`. Field rows grouped by device role (**2.4.g**).
- Optional LLM: local **Ollama** HTTP (`/api/chat`, JSON). Not bundled in Earnie image / LoxBerry ZIP. Without Ollama: heuristic propose + manual selects.
- EFM interpretation C (meter tree → Hausprofil consumers/CSV): backlog **2.4.i**; manual blueprint remains `.cursor/plans/energieflussmonitor_hausprofil_blueprint_a.plan.md`.

## Implementation notes (2.4.g device / hardware profiles)

- Schemas + examples only for Live; adapters keep hardcoded maps.
- HITL labels/grouping via `ehal.profiles.role_field_labels` / `group_fields_by_role` (Loxone + HA mapping UIs).
- Contribution entry: [CONTRIBUTING.md](../../CONTRIBUTING.md) §4.

## Phase 4 / 2.4.h — multi-system config-switch proof

Acceptance for **2.4.h** (docs + automated proof):

- Mocked three-way contract: `tests/test_ehal_contract_backends.py` — same Core-facing `read_live_power_kw` for `openems` / `ha` / `loxone`; `get_adapter()` routing by `EHAL_BACKEND` only; ESS setpoint parity for network backends; documented Loxone write asymmetry (`is_ehal_network_backend` = openems|ha only; Live ESS/flex still via `loxone_client`).
- German operator docs: [docs/einrichtung/adapter-wahl.md](../einrichtung/adapter-wahl.md).
- Connector recipe expanded in [CONTRIBUTING.md](../../CONTRIBUTING.md) §3 and the checklist below.

Optional live lab matrix (Compose OpenEMS/HA + prod Loxone HITL) remains a soft check for release **2.4.0**, not a gate for this chapter.

## Connector-author checklist

1. Translate hub entities → EHAL only; no hub types in Core.
2. Normalize signs and units (W / % / A) before emit.
3. Publish Capability-Flags; degrade on write failure.
4. Network API only; separate containers from Earnie Core.
5. Setpoints = limits; leave realtime control to the hub.
6. Validate outgoing/incoming documents with `share/ehal/*.schema.json` or `ehal.validate_*`.
7. **Config switch only:** Core must work when only `ehal.backend` (+ hub credentials/mapping) changes — extend `tests/test_ehal_contract_backends.py`.
8. **Touch list for a new hub:**
   - `integrations/<hub>_adapter.py` (`read_telemetry` / `write_setpoints` / `capabilities`)
   - `integrations/ehal_live.py` (`is_*_backend`, `get_*_adapter`, `get_adapter`)
   - `settings/config_loaders.py` (`load_ehal_params`), `runtime_store/ehal_setup.py`, and usually `ui/ehal_connection.py`
   - Unit tests + contract-test cases
9. Mapping aids (roles / Loxone recipes / hardware-profile outlines) → §4 / `ehal.profiles` — not Live I/O.
10. See also [CONTRIBUTING.md](../../CONTRIBUTING.md) §3.
