# EHAL — Earnie Hardware Access Layer (M1 freeze)

**Backlog:** `2.4.a` (Phase 1 / M1 spec)  
**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 §2.2, §2.5 Phase 1, §2.6  
**Schemas:** [`share/ehal/`](../../share/ehal/)  
**Python:** [`ehal/`](../../ehal/)  
**Lab mapping (OpenEMS):** [`openems-testing-platform-todo.md`](openems-testing-platform-todo.md)  
**Lab setup (Compose + Earnie ↔ OpenEMS):** [`openems-lab-setup.md`](openems-lab-setup.md)

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
| Loxone today | Production Loxone path stays **pre-EHAL** until **2.5.a**; this freeze does not force cutover |

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
| Heatpump | Not in M1 EHAL; later Thermals / flex-consumer extension and/or **2.5.c** device-role templates |
| Generic consumer | Today Loxone flex markers; EHAL consumer roles with **2.5.a** / **2.5.c** |

## Out of scope (this freeze)

- MQTT / Matter as first-class hubs
- Loxone-EHAL extraction (**2.5**)
- HA adapter implementation (**2.4.c**)
- Loxone extras as first-class EHAL fields: `target_soc`, `control_cmd`, flex enable, EV **kW** setpoint (remain pre-EHAL / **2.5**)
- Modbus hardware-profile library (Entwicklungsplan M2 / M4)

## Implementation notes (2.4.b OpenEMS)

- Adapter: `integrations/openems_adapter.py` (REST only). Live façade: `integrations/ehal_live.py`.
- Compose lab: `docker/compose/openems-lab.yml`. Config snippet: `share/config/ehal.openems.snippet.json`. Step-by-step: [`openems-lab-setup.md`](openems-lab-setup.md).
- Cadence: Core still expects ≥ 60 s telemetry refresh; adapter may poll faster.
- EVCS: EHAL `set_evcs_max_current` (A) → OpenEMS `evcs0/SetChargePowerLimit` (W) via house-profile V/phases.
- Southbound silent gate: reuse `loxone_silent_mode` for OpenEMS writes as well.
- Write failures → `runtime/ehal_write_error.json` + UI banner on Loxone-Kommunikation / Daemon page.

## Connector-author checklist

1. Translate hub entities → EHAL only; no hub types in Core.
2. Normalize signs and units (W / % / A) before emit.
3. Publish Capability-Flags; degrade on write failure.
4. Network API only; separate containers from Earnie Core.
5. Setpoints = limits; leave realtime control to the hub.
6. Validate outgoing/incoming documents with `share/ehal/*.schema.json` or `ehal.validate_*`.
7. See also [CONTRIBUTING.md](../../CONTRIBUTING.md) § Connector / EHAL adapters.
