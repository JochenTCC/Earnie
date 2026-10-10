# EHAL — Earnie Hardware Access Layer (schema_version 4)

**Status:** current (schema_version 4; Pattern B bindings shipped; `set_ess_source_select` for 2.7.h)  
**History (backlog):** `2.4.a` (M1) → `2.4.j` (wire rename) → `2.4.k` (entity mapping) → `2.4.o` (Design C1 `set_ess_active_power`) → `2.7.h` (source select)  
**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 §2.2, §2.5 Phase 1, §2.6  
**Canonical field names:** `[docs/ui/ehal-com.md](../ui/ehal-com.md)` §B / §C  
**Schemas:** `[share/ehal/](../../share/ehal/)`  
**Python:** `[ehal/](../../ehal/)`  
**Lab mapping (OpenEMS):** `[openems-testing-platform-todo.md](openems-testing-platform-todo.md)`  
**Lab setup (Compose + Earnie ↔ OpenEMS):** `[openems-lab-setup.md](openems-lab-setup.md)`  
**Lab setup (Compose + Earnie ↔ HA + evcc):** `[ha-lab-setup.md](ha-lab-setup.md)`

## Purpose and naming

**EHAL** (Earnie Hardware Access Layer) is the only southbound contract between Earnie Core (48h optimizer / Live) and hardware hubs. Wire format is normalized JSON: **Telemetry**, **Setpoints**, and **Capability-Flags**.

Do **not** call this layer “SAM” (Businessplan “SAM” = market size only).

Earnie Core remains the sole strategic optimizer. Hubs provide I/O and device catalogs only. Adapters **translate**; they do not embed competing surplus/spot strategies into the math core.

## Core contract


| Rule          | Detail                                                                                                                                                                                                                                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Consumption   | Optimizer / Live consume **only** EHAL types from `ehal` / these schemas                                                                                                                                                                                                                                                             |
| Hub isolation | No OpenEMS, Home Assistant, evcc, or Loxone types in the math core                                                                                                                                                                                                                                                                   |
| Adapter duty  | Map hub channels/entities → EHAL; normalize signs and units inside the adapter                                                                                                                                                                                                                                                       |
| Transport     | Network only (REST / WebSocket / JSON). No linking or copying hub source into Earnie repos (Separate Works / AGPL shield for OpenEMS)                                                                                                                                                                                                |
| Loxone today  | Default `ehal.backend=loxone` uses `[integrations/loxone_adapter.py](../../integrations/loxone_adapter.py)` for plant telemetry/setpoints; marker names live in `plant.ehal_bindings` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings` (Pattern B; ESS per battery, **2.7.m**). Legacy `loxone_blocks` / unprefixed `*_name` dual-read is removed (fail-fast). Mapping UI: EHAL-Com |
| HA today      | `ehal.backend=ha` uses `[integrations/ha_adapter.py](../../integrations/ha_adapter.py)`; entity IDs in the same Pattern B maps (aggregated live, incl. `ess.{slug}.*`). URL/token in `config/.env` (`EHAL_HA_*`); optional `sign` in `ehal.ha` (**2.6.i**). Flat `ehal.ha.entities` is one-shot migrated and cleared (**2.6.g**).                          |




## Qualified EHAL IDs (2.7.n-2)

Exchange / display form of every signal on the Loxone push wire and in `status.json` Check keys. Implemented in `ehal/qualified_ids.py` (builders + `parse_qualified_id`).

| Form | Example | Notes |
| ---- | ------- | ----- |
| Plant bare | `sens_temperature_outside`, `sens_pv_production_active` | House-wide fields without a device Kennung; PV stays bare until a deferred `pv.*` namespace |
| Grid meter | `grid.meter.sens_grid_power_active` | First Kennung `meter`; more `grid.<Kennung>.*` meters may follow. Plant **storage** keeps bare kind keys |
| Battery | `ess.<Kennung>.sens_ess_soc` | Pattern B |
| Consumer by type | `consumer.<slug>.set_enable`, `heatpump.<slug>.*`, `pool.<slug>.*` (incl. `pool_filter`) | Emitted namespaces; legacy `flex.<slug>.*` accepted on parse only |
| EV split | `evcs.<slug>.set_evcs_max_current`, `ev.<slug>.sens_evcs_soc_act` | Same Kennung; namespace chosen by field kind |
| Inverter (reserved) | `inv.<slug>.*` | **2.7.l P4** |
| Heartbeat | `heartbeat` | Link proof; not a field kind |

`parse_qualified_id(id)` → `ParsedQualifiedId(namespace, kennung, kind, raw)` or `None`. Plant bare and `heartbeat` have `namespace` / `kennung` = `None`. Round-trip: builders → parse → `format_qualified_id` restores the exchange string. Field kinds are not renamed in 2.7.n.

## Schema version and envelope

Every Telemetry, Setpoint, and Capabilities document uses the same envelope fields:


| Field            | Type              | Required | Meaning                                                                                                  |
| ---------------- | ----------------- | -------- | -------------------------------------------------------------------------------------------------------- |
| `schema_version` | integer           | yes      | Wire version; **current =** `4` (`set_ess_source_select` / 2.7.h; Design C1 was **2.4.o** / v3; `sens_`* freeze **2.4.j** / v2; M1 was `1`) |
| `ts`             | string (ISO-8601) | yes      | Sample / write time with timezone (`Z` or offset). Prefer UTC.                                           |
| `adapter_id`     | string            | yes      | Stable adapter instance id (e.g. `openems-lab`, `earnie-hems`)                                           |


**Frozen choice:** `ts` is **ISO-8601 with timezone**, not epoch milliseconds.

## Units and sign convention (frozen)

EHAL base units (adapters normalize hub-native units into these):


| Quantity / domain                                                                                                                                  | Unit   | Sign / range                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------- |
| Active power telemetry (`sens_grid_power_active`, `sens_pv_production_active`, `sens_evcs_active_power`, `sens_ess_power`, `sens_power_consumers`) | **W**  | See below                                                                             |
| ESS charge/discharge **limits**, `set_grid_export_power_limit` / `get_grid_export_power_limit`, `get_ess_max_charge_power` / `get_ess_max_discharge_power` | **W**  | Non-negative **magnitudes** (true caps); direction is in the field name, not the sign |
| `set_ess_active_power`                                                                                                                             | **W**  | Signed; `+` = discharge, `−` = charge (omit on Automatik)                             |
| Energy counters / capacity (`sens_pv_energy`, `sens_grid_energy_import` / `_export`, `sens_ess_energy_charge` / `_discharge`, `sens_energy_total`, `sens_evcs_bat_capacity`) | **kWh** | Cumulative or capacity ≥ `0`; HA may convert Wh → kWh at the boundary                 |
| `sens_ess_soc` / EV SoC fields                                                                                                                     | **%**  | `0`…`100`                                                                             |
| `set_evcs_max_current` / `get_evcs_nominal_current`                                                                                                | **A**  | Non-negative                                                                          |
| Temperature (`sens_temperature_outside`, pool water/setpoint/tolerance, heat-storage `sens_temperature_heat_storage` / `_low`)                     | **°C** | Celsius only (no °F on the wire); adapters must convert hub °F if ever present        |
| Duration (`get_filter_remaining_hours`, `get_filter_native_duration_hours`, …)                                                                     | **h**  | Hours; non-negative                                                                   |
| Modes / flags (`set_ess_mode`, `set_evcs_mode`, `sens_absent_mode`, `sens_evcs_connected`, …)                                                       | —      | Dimensionless (enums or `0`/`1`); no physical unit                                    |


**Export limit "unconstrained" (2.7.a / 2.7.c):** sticky backends always receive a number on `set_grid_export_power_limit`. When no cap applies, Earnie writes the plant's physical export maximum = **sum of PV nameplate (kWp)** + **sum of max discharge power of every selected battery that supports forced discharge** (`battery_control = full`; skip `limits_only` / `read_only`). Fallback when both are unknown: `1 000 000` W. ESS bindings use Pattern B `ess.{slug}.*` on `batteries[].ehal_bindings`.

**Grid (**`sens_grid_power_active`**):** `+` = grid **import** (Bezug), `−` = **export** (Einspeisung). Adapters normalize hub-native signs before emit.

**PV (**`sens_pv_production_active`**):** production ≥ `0` (W). Interval energy = ∫ power × Δt (no cumulative counter on the wire).

**EVCS (**`sens_evcs_active_power`**):** charge power ≥ `0` (W) when charging; `0` when idle.

**ESS (**`sens_ess_power`**, optional):** OpenEMS-aligned — `+` = **discharge**, `−` = **charge**. Adapters whose source uses the opposite convention (e.g. Victron: + charge) must invert at the boundary. Loxone battery Merker already use `+` = discharge (no inversion).

**Reference power balance (normative):** all power signs are chosen so that every flow *into the house* is positive. Ignoring inverter losses:

```
P_cons = P_PV + P_Grid + P_Bat
         (sens_power_consumers = sens_pv_production_active + sens_grid_power_active + sens_ess_power)
```

| Term | Field | `+` | `−` |
|------|-------|-----|-----|
| `P_PV` | `sens_pv_production_active` | production | — (≥ 0) |
| `P_Grid` | `sens_grid_power_active` | import (Bezug) | export (Einspeisung) |
| `P_Bat` | `sens_ess_power` | discharge | charge |
| `P_cons` | `sens_power_consumers` | house load | — (≥ 0) |

Every adapter, derived value (`sens_power_consumers` when not mapped), Live dict and Loxone Merker follows this convention; hub-native signs are normalized at the adapter boundary. Example: Huawei registers 37113 (grid, `+` = export) and 37765 (battery, `+` = charge) must both be negated.

**Hub unit conversion (registry):** static hub ↔ EHAL conversion lives in optional `loxone` / `openems` blocks on fields in `share/ehal/roles/*.json` (schema `device_roles.schema.json`). `factor` / `sign` always mean hub → EHAL; `ehal/field_registry.py` exposes `apply_loxone_read` / `apply_loxone_write` (and OpenEMS equivalents). Writes clamp in EHAL space then invert; `omit_if` / `read_required` are read-only. Top-level role `required` remains mapping completeness. HA keeps runtime unit factors in `integrations/ha_units.py` (entity `unit_of_measurement`; Binding P5 parity later).

**House load (**`sens_power_consumers`**, optional):** prefer mapped Merker; else derive from grid/PV/ESS balance.

## Telemetry-API (schema_version 4)


| Field                         | Required | Unit   | Notes                                                                                                      |
| ----------------------------- | -------- | ------ | ---------------------------------------------------------------------------------------------------------- |
| `sens_grid_power_active`      | yes      | W      | PCC active power; sign as above                                                                            |
| `sens_pv_production_active`   | yes      | W      | ≥ 0                                                                                                        |
| `sens_ess_soc`                | yes      | %      | Home battery SoC                                                                                           |
| `sens_ess_power`              | no       | W      | Optional; sign as above                                                                                    |
| `sens_evcs_active_power`      | no       | W      | ≥ 0 when present                                                                                           |
| `sens_power_consumers`        | no       | W      | House load; Merker or derive                                                                               |
| `sens_evcs_connected`         | no       | bool   | EV plugged in                                                                                              |
| `sens_evcs_soc_act`           | no       | %      | Vehicle SoC                                                                                                |
| `get_evcs_nominal_current`    | no       | A      | Nominal / max current                                                                                      |
| `sens_evcs_bat_capacity`      | no       | kWh    | EV battery capacity                                                                                        |
| `get_evcs_ready_by_time`      | no       | string | Ready-by deadline (Loxone: AlarmClock SpecialState10 via `/all`, Tna text backup; binding = baustein name) |
| `get_evcs_limit_soc`          | no       | %      | Charge limit SoC                                                                                           |
| `get_evcs_soc_min_immediate`  | no       | %      | ASAP min SoC floor; ≤0 or absent = inactive; clamped to limit SoC                                          |
| `get_grid_export_power_limit` | no       | W      | Optional inbound max export from grid/HEMS (magnitude; negative or ≥ 1 000 000 = no cap) (2.7.a)           |
| `get_ess_soc_min`             | no       | %      | Optional discharge cut-off SoC (device config; MILP when `limits_from_live`) (2.7.j)                        |
| `get_ess_soc_max`             | no       | %      | Optional charge cut-off SoC (device config; MILP when `limits_from_live`) (2.7.j)                           |
| `get_ess_max_charge_power`    | no       | W      | Optional device max charge power magnitude (2.7.j)                                                         |
| `get_ess_max_discharge_power` | no       | W      | Optional device max discharge power magnitude (2.7.j)                                                      |


Machine schema: `[share/ehal/telemetry.schema.json](../../share/ehal/telemetry.schema.json)`.

## Setpoint-API (schema_version 4)

Setpoints are **math limits / forced power / modes**, not a full inner-loop controller. Realtime enforcement stays in the subsystem (OpenEMS / HA / inverter).

**Design C1:** force lives in `set_ess_active_power`; charge/discharge fields are **true caps**. OpenEMS uses active power + limits and **ignores** `set_ess_mode`.

**Sticky backends (Loxone / HA entity holds):** Merker/entities keep the **last written value**. Omitting `set_ess_active_power` on the wire does **not** clear a stale Sollleistung. Earnie therefore **always writes** `set_ess_mode` **on every ESS cycle**. **Automatik / inverter free =** `set_ess_mode = 0` — Config must treat mode 0 as “ignore Sollleistung / release force,” even if `Earnie_Batterie_Sollleistung` still holds an old number. Do **not** infer Automatik from absent/`null` active power alone on sticky paths.


| Field                           | Required in doc | Unit          | Notes                                                                                                                                                                                           |
| ------------------------------- | --------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set_ess_active_power`          | no*             | W             | Forced ESS power (`+` discharge, `−` charge); **omit** on Automatik (OpenEMS: no Equals)                                                                                                        |
| `set_ess_charge_power_limit`    | no*             | W             | Max charge power (magnitude ≥ 0)                                                                                                                                                                |
| `set_ess_discharge_power_limit` | no*             | W             | Max discharge power (magnitude ≥ 0)                                                                                                                                                             |
| `set_ess_mode`                  | no*             | string/number | Sticky-backend control; **0 = Automatik**; battery only (export caps via `set_grid_export_power_limit`); OpenEMS ignores                                                                        |
| `set_ess_source_select`         | no*             | enum 0\|1     | Route locally-attached loads: **0 = grid** pass-through (charge allowed), **1 = battery-only** island. Wire as Pattern B `ess.{id}.set_ess_source_select` on physical powerstation `standby_backup` only (2.7.h); omit for house ESS / plant. OpenEMS unused. |
| `set_grid_export_power_limit`   | no*             | W             | Max grid export, non-negative magnitude (like ESS limits); `0` = no export; unconstrained = plant maximum (PV kWp sum + max discharge of force-dischargeable ESS; fallback 1 000 000 W) (2.7.a) |
| `set_evcs_max_current`          | no*             | A             | EV charge current setpoint / max current                                                                                                                                                        |
| `set_evcs_mode`                 | no*             | enum          | `off`                                                                                                                                                                                           |


A setpoint document must include **at least one** of these fields (plus envelope). Partial updates are allowed; omitted fields mean “leave unchanged” at the adapter (except Automatik → omit `set_ess_active_power` so Equals is not forced; sticky backends still rely on **mode = 0**).

Machine schema: `[share/ehal/setpoint.schema.json](../../share/ehal/setpoint.schema.json)`.

## Battery controllability (`batteries[].control`, 2.6.n)

Installation property in `components.json` (default `full`). Drives MILP constraints, mode derivation, and whether ESS setpoints are written — independent of the live adapter, so simulation / backtesting / scenario comparison stay consistent.


| `control`     | MILP                                                                                   | Modes / writes                            |
| ------------- | -------------------------------------------------------------------------------------- | ----------------------------------------- |
| `full`        | Bidirectional (grid charge + battery export allowed)                                   | Zwangsladen / Zwangsentladen when planned |
| `limits_only` | Charge ≤ PV, discharge ≤ load; no charge while importing, no discharge while exporting | Automatik / Entladesperre only (limits)   |
| `read_only`   | Self-consumption coupling (residual split)                                             | No ESS setpoints                          |


**Capability cross-check:** EHAL-Com / Live warn when `control` asks for more than bound functions allow (`ess_limits` / `ess_active`).

### HA vendor force: `plant.ha_ess_force`

When there is no `set_ess_active_power` entity (typical `huawei_solar`), configure:

```json
"plant": {
  "ha_ess_force": {
    "driver": "huawei_solar",
    "device_id": "<HA device registry id of the LUNA/battery>",
    "duration_min": 20
  }
}
```

With Elevate permissions enabled in [wlcrs/huawei_solar](https://github.com/wlcrs/huawei_solar), the HA adapter calls `huawei_solar.forcible_charge` / `forcible_discharge` (power W, duration minutes, re-issued each control cycle) and `stop_forcible_charge` on Automatik / Entladesperre. Together with both limit entities this makes `ess_active` available so the plant can use `control: full`. HouseSim archetype `huawei_en` golden map stays limits-only; force is covered by adapter / mock-service tests.

## Capability-Flags (schema_version 4)


| Field                          | Required | Meaning                                                                   |
| ------------------------------ | -------- | ------------------------------------------------------------------------- |
| `supports_ess_write`           | yes      | ESS setpoints (active power and/or limits) can be written                 |
| `supports_evcs_current`        | yes      | `set_evcs_max_current` can be written                                     |
| `supports_ess_source_select`   | no       | `set_ess_source_select` can be written (standby_backup powerstation)      |


`supports_ess_write` and `supports_evcs_current` remain required; `supports_ess_source_select` may be omitted (treated as false).

Machine schema: `[share/ehal/capabilities.schema.json](../../share/ehal/capabilities.schema.json)`.

## Update interval and stale behavior


| Topic                                      | Freeze                                                                                                           |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| Minimum telemetry cadence toward Core      | **60 s**                                                                                                         |
| Faster internal polling                    | Allowed inside the adapter                                                                                       |
| Stale samples                              | Core must tolerate unchanged values until the next sample; adapters should still refresh `ts` when re-publishing |
| Missing **optional** telemetry             | Omit field or set `null` per schema (`sens_ess_power`, `sens_evcs_`*, …)                                         |
| Missing **required** `sens_ess_soc` (Live) | Abort the Live run (same hard requirement as today’s house SOC)                                                  |
| Missing required power telemetry           | Do not invent zeros; surface error / skip overlay as documented by the Live path                                 |




## Write failures and degrade

On failed setpoint writes (OEM locks, read-only REST, missing HA write entities):

1. Catch the error; **do not crash** the optimizer.
2. Log with enough context for support (adapter_id, field, hub status/message).
3. Flip the matching capability flag (`supports_ess_write=false` and/or `supports_evcs_current=false`).
4. Emit **Write-Error-Telemetry** (see below) so UI can show a user hint.
5. Continue with read-only / degraded control for that subsystem.



### Write-Error-Telemetry shape

Envelope fields plus:


| Field           | Type            | Required | Meaning                                     |
| --------------- | --------------- | -------- | ------------------------------------------- |
| `failed_fields` | array of string | yes      | EHAL setpoint field names that failed       |
| `message`       | string          | yes      | Human-readable summary (may be shown in UI) |
| `hub_status`    | string or null  | no       | Hub HTTP/RPC status or code if available    |
| `retryable`     | boolean         | yes      | Hint whether a later write may succeed      |


Machine schema: `[share/ehal/write_error.schema.json](../../share/ehal/write_error.schema.json)`.

## Fehlertoleranz (M1 defaults)


| Situation                      | Behavior                                                                 |
| ------------------------------ | ------------------------------------------------------------------------ |
| Optional telemetry absent      | Omit / null; Core continues                                              |
| Required `sens_ess_soc` absent | Live abort                                                               |
| Setpoint write fails           | Log + capability degrade + Write-Error-Telemetry; optimizer continues    |
| Capability false from start    | Skip writes for that family; no repeated error spam beyond periodic hint |
| Schema validation fail         | Reject document; adapter must not pass invalid JSON to Core              |


Numeric hub-tolerance thresholds beyond the above are left to adapter implementation notes (OpenEMS / HA sections below).

## OpenEMS light alignment

Fields map to known OpenEMS Edge channels (semantic reference). Channel architecture, Compose, and lab write tests: `[openems-lab-setup.md](openems-lab-setup.md)`.


| EHAL field                      | OpenEMS (prototype)                                                                                                                         |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_grid_power_active`        | `_sum/GridActivePower` (normalize: `+` = import)                                                                                            |
| `sens_pv_production_active`     | `_sum/ProductionActivePower`                                                                                                                |
| `sens_ess_soc`                  | `ess0/Soc` / `_sum/EssSoc`                                                                                                                  |
| `sens_ess_power`                | ESS ActivePower (OpenEMS sign; already EHAL-aligned)                                                                                        |
| `sens_evcs_active_power`        | EVCS / EVSE active power channels                                                                                                           |
| `set_ess_active_power`          | e.g. `SetActivePowerEquals` (signed W; omit on Automatik)                                                                                   |
| `set_ess_charge_power_limit`    | e.g. `SetActivePowerGreaterOrEquals` (adapter maps magnitude)                                                                               |
| `set_ess_discharge_power_limit` | e.g. `SetActivePowerLessOrEquals`                                                                                                           |
| `set_ess_mode`                  | *(ignored by OpenEMS)*                                                                                                                      |
| `get_ess_soc_min` / `get_ess_soc_max` / `get_ess_max_charge_power` / `get_ess_max_discharge_power` | *(optional 2.7.j; omit when no Edge channel — Core uses HK fallback)* |
| `set_evcs_max_current`          | EVCS Max Current                                                                                                                            |
| `sens_absent_mode`              | Optional side-channel: `plant.ehal_bindings.sens_absent_mode` = `componentId/ChannelId` (no fixed Edge default; not in core telemetry wire) |




### Deferred device classes


| Class            | When                                                                                                                                                                                                                                                                                                                                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Heatpump         | Not on the core EHAL plant wire; stub role (`share/ehal/roles/heatpump.json`) + Loxone recipe/VO (`share/loxone/recipes/heatpump.json`, `VO_Earnie_Heatpump.xml`). Live: `thermal_annual` consumer `ehal_bindings` for `flex.*` plus `sens_temperature_heat_storage` / `sens_temperature_heat_storage_low` (HA entity IDs or Loxone Merker via Pattern B HITL) |
| Generic consumer | Flex fields mapped via `consumers[].ehal_bindings` (storage often still `flex.{slug}.*`); Live/VO exchange uses **`consumer.{Kennung}.*`** (2.7.n), incl. **`sens_consumer_active`** (2.7.p). Stub role + recipe; VO Merker `Earnie_Verbraucher_<Slug>_Aktiv`                                                                                                                                                                                    |




## Device roles and hardware profiles

**Mapping aids / contribution seeds**, not a new Live I/O path.


| Artifact                | Path                                                                                                                 | Purpose                                                                              |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Device-role schema      | `[share/ehal/device_roles.schema.json](../../share/ehal/device_roles.schema.json)`                                   | Groups M1 fields by role; optional per-field `loxone` / `openems` conversion blocks |
| Field registry          | `[ehal/field_registry.py](../../ehal/field_registry.py)`                                                             | Loads hub blocks; `apply_loxone_read` / `apply_loxone_write` (+ OpenEMS apply)       |
| Role instances          | `[share/ehal/roles/](../../share/ehal/roles/)`                                                                       | One JSON per `role_id`                                                               |
| Hardware-profile schema | `[share/hardware_profiles/hardware_profile.schema.json](../../share/hardware_profiles/hardware_profile.schema.json)` | SunSpec / proprietary Modbus outline → EHAL bindings                                 |
| Outline examples        | `[share/hardware_profiles/examples/](../../share/hardware_profiles/examples/)`                                       | `sunspec_inverter_ess.outline.json`, `huawei_via_loxone.outline.json`                |
| Loxone recipes          | `[share/loxone/recipes/](../../share/loxone/recipes/)`                                                               | JSON Merker / Baustein tips → `ehal_bindings` (no `.loxone` binary)                  |
| Python loader           | `[ehal/profiles.py](../../ehal/profiles.py)`                                                                         | `list_*` / `load_*` + HITL `role_field_labels` / `group_fields_by_role`              |


**Rules:** Stub roles use `kind: stub`. Flex (`flex.`*) and plant fields are mapped on EHAL-Com into `plant` / `consumers[].ehal_bindings`; all ESS including Quellenwahl into `batteries[].ehal_bindings` as `ess.{slug}.*` (**2.7.m**; `set_ess_source_select` only on physical `standby_backup`). HITL groups mapping rows by role label. Wire includes `set_ess_mode`, EV `sens_`* / `set_evcs_*` / `get_*`, and optional `sens_power_consumers`.

## Out of scope (this freeze)

- MQTT / Matter as first-class hubs
- HA WebSocket state subscription / direct evcc REST adapter (deferred; REST HA path shipped)
- ARP scan / profile upload. Modbus/SunSpec **outline** schemas under `share/hardware_profiles/` — not a runtime Modbus client (direct Modbus profiles: Entwicklungsplan **M4**).



## Implementation notes — OpenEMS

- Adapter: `integrations/openems_adapter.py` (REST only). Live façade: `integrations/ehal_live.py`.
- Compose lab: `docker/compose/openems-lab.yml`. Config snippet: `share/config/ehal.openems.snippet.json`. Step-by-step: `[openems-lab-setup.md](openems-lab-setup.md)`.
- Cadence: Core expects ≥ 60 s telemetry refresh; adapter may poll faster.
- EVCS: EHAL `set_evcs_max_current` (A) → OpenEMS `evcs0/SetChargePowerLimit` (W) via house-profile V/phases.
- Optional absent / holiday: set `plant.ehal_bindings.sens_absent_mode` to `componentId/ChannelId` (read via `read_channel`; no HITL plant mapper yet).
- Southbound silent gate: reuse `loxone_silent_mode` for OpenEMS writes as well.
- Write failures → `runtime/ehal_write_error.json` + UI banner on EHAL-Com / Daemon page.



## Implementation notes — Home Assistant + evcc

- Adapter: `integrations/ha_adapter.py` (REST only: `/api/states`, `/api/services/...`). Prefer HA entities from evcc.
- Config: `ehal.backend=ha`; URL/token in `config/.env` (`EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN`); optional `sign` under `ehal.ha` in `config.json`. Entity IDs live in `plant.ehal_bindings` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings` (Pattern B; ESS per battery). Live aggregation (`aggregate_ha_entities`): plant grid/PV/export + optional energy counters + `sens_absent_mode`; battery Pattern B `ess.{slug}.*` (incl. `ess.{id}.set_ess_source_select` on physical standby_backup) with primary flat ESS aliases for non-Quellenwahl kinds; first EV only `sens_evcs_active_power` / `set_evcs_max_current` / `set_evcs_mode`. Extra Pattern B keys (outdoor temp, full EV SoC/connected, flex/pool) may be saved in HITL but are ignored by `HaAdapter` until wired. Legacy flat `ehal.ha.entities` is migrated once and cleared. Snippet: `share/config/ehal.ha.snippet.json` (backend / `adapter_id` / `sign` only — no secrets).
- Compose lab: `docker/compose/ha-lab.yml` (Earnie :8506 + HA :8123 + evcc :7070). Setup: `[ha-lab-setup.md](ha-lab-setup.md)`. German A2/B: `[../einrichtung/ha-evcc.md](../einrichtung/ha-evcc.md)`.
- HITL mapping UI: Streamlit EHAL-Com expander → `ui/ehal_ha_mapping.py` (entity picker plant / battery / consumer → scan `/api/states` once per session → **heuristic propose** for empty fields only → user confirms → house or `components.json` per entity; **no LLM**). Heuristic: `integrations/ha_ehal_mapping.py` (domain / `device_class` / unit / token-boundary name hints with vendor synonyms; unique best score or leave empty; physical-quantity filter via `ha_units`). Live path: Pattern B / `aggregate_ha_entities` → `HaAdapter`; Live tables use entity-centric Mapping columns like Loxone.
- Optional slot-Ist energy maps (not on the EHAL power wire): `sens_pv_energy`, `sens_grid_energy_import`, `sens_grid_energy_export` on `plant.ehal_bindings` → `integrations/ha_meter_energy.py` + sampler ΔkWh overlay (same contract as Loxone; see `[loxone-meter-energy-slot-ist.md](loxone-meter-energy-slot-ist.md)`).
- Sign mode per field: `ehal` (already aligned) or `negate` — still in `ehal.ha.sign` (config). Units: kW states converted to W; energy Wh→kWh on the side channel.
- Setpoints: typically `number.set_value` on mapped entities (Amps for EVCS; W for ESS limits).
- Optimizer exclusivity + single Modbus writer: see German checklist in `ha-evcc.md`.
- Same Live façade / write-error path as OpenEMS (`is_ehal_network_backend()`).



## Implementation notes — Loxone

- Adapter: `integrations/loxone_adapter.py` (HTTP markers via `loxone_client`). Live façade: `integrations/ehal_live.py` (`get_adapter()` includes Loxone).
- Default config: missing/`none`/`loxone` → `EHAL_BACKEND=loxone`, `adapter_id` default `loxone-home`. Marker names live in `plant.ehal_bindings` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings` (Pattern B); empty legacy `loxone_blocks` may remain but is not the mapping source.
- Telemetry: kW markers → W; Loxone battery **+discharge** → EHAL `sens_ess_power` **+discharge** (`× 1000`, no inversion); grid pass-through as EHAL `+` import; field names §C (`sens_`*).
- Capabilities: `supports_ess_write` when charge/discharge markers exist; `supports_evcs_current` when EV current write path works.
- Live writes: ESS limits / `set_ess_mode` / EV current+mode / flex enable via adapter + `ehal_bindings`.
- Removed from live semantics (wire rename): ESS `target_soc`, EV `soc_at_plug_in`, PV cumulative counter, Sofortladen countdown Merker.



## Implementation notes — Loxone one-click mapping

- Onboarding helper **inside** the Loxone-EHAL path — not a live I/O replacement.
- Structure scan (`integrations/loxone_structure.py`): supports **compare-all** (LoxAPP3 + HTTP-Probe + optional **MCP 17.1**) for lab/compare; MCP helpers remain in `integrations/` for later re-integration.
- **EHAL-Com UI:** mapping names come from **HTTP-Probe only** (`sources=(http_probe,)`). MCP URL input, Ollama button, Quellenvergleich, and source picker are not in the shipping UI.
- **Greenfield HTTP marker probe:** `integrations/loxone_greenfield_import.probe_marker_names` hits known `greenfield_device_map.json` names via `/jdev/sps/io/{name}`. `LL.Code` `200` or `403` = present; `404` = missing. Union with LoxAPP3 names for typed Merker match. EFM meters still need LoxAPP3.
- HITL UI: `ui/ehal_loxone_mapping.py` on EHAL-Com (backend Loxone). Heuristic proposals + manual selects; confirm writes `plant` / `consumers[].ehal_bindings` via house profiles and ESS via `batteries[].ehal_bindings` on `components.json`. Field rows grouped by device role.
- Optional LLM (code retained, **not** exposed in UI): local **Ollama** HTTP (`/api/chat`, JSON). Not bundled in Earnie image / LoxBerry ZIP.
- EFM interpretation C (meter tree → Hausprofil consumers + optional flex power): research note `[efm-auto-sync-2.4.l.md](efm-auto-sync-2.4.l.md)`; library `integrations/loxone_efm_meters.py` via greenfield `merge_efm` (Smarthome-Backend Loxone-Import).



## Implementation notes — device / hardware profiles

- Schemas + examples only for Live; adapters keep hardcoded maps.
- HITL labels/grouping via `ehal.profiles.role_field_labels` / `group_fields_by_role` (Loxone + HA mapping UIs).
- Contribution entry: [CONTRIBUTING.md](../../CONTRIBUTING.md) §4.
