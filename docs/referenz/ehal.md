# EHAL — Earnie Hardware Access Layer (schema_version 4)

**Status:** current, `schema_version` 4.

- The plant-flat `sens_ess_soc` is retired. SoC exists only as `ess.{id}.sens_ess_soc`.
- Entity-scoped bindings are shipped (formerly "Pattern B").
- `set_ess_source_select` was added in 2.7.h.
- The optional, entity-scoped role `inverter` was added in 2.7.l.

**History (backlog):** `2.4.a` (M1) → `2.4.j` (wire rename) → `2.4.k` (entity mapping) → `2.4.o` (Design C1 `set_ess_active_power`) → `2.7.h` (source select) → `2.7.l` (inverter entity)

**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 §2.2, §2.5 Phase 1, §2.6

| Topic | Link |
| ----- | ---- |
| Canonical field names | [docs/ui/ehal-com.md](../ui/ehal-com.md) §B / §C |
| Schemas | [share/ehal/](../../share/ehal) |
| Python | [ehal/](../../ehal) |
| Lab mapping (OpenEMS) | [openems-testing-platform-todo.md](../dev/openems-testing-platform-todo.md) |
| Lab setup (Compose, Earnie ↔ OpenEMS) | [openems-lab-setup.md](../dev/openems-lab-setup.md) |
| Lab setup (Compose, Earnie ↔ HA + evcc) | [ha-lab-setup.md](../dev/ha-lab-setup.md) |

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
| Loxone today  | Default `ehal.backend=loxone` uses `[integrations/loxone_adapter.py](../../integrations/loxone_adapter.py)` for plant telemetry/setpoints. Entity-scoped keys on `plant` / `consumers[]` / `batteries[].ehal_bindings` / `inverters[].ehal_bindings` are **activation flags** (empty Merker values after **2.7.q Q8**); wire I/O is VO push + `status.json` under qualified IDs. ESS reads/writes use `ess.{id}.*` on batteries (no `LOXONE_*` loud-name config slots, no plant-flat ESS alias merge). Structure/greenfield presence uses LoxAPP3 (no Merker HTTP in production Python). Mapping UI: EHAL-Com. |
| HA today      | `ehal.backend=ha`; **push-only** (same HTTP contract as Loxone). HA pushes activated reads to `GET /ehal/telemetry/<qualified-id>/<value>` (token); setpoints on `GET /ehal/status.json` (alias `/ehal/loxone/status.json`). Listener: `system.ehal_loxone_http_port` (default **8541**). Entity-scoped `ehal_bindings` are **activation flags** (empty values — Earnie stores no HA `entity_id`). Carrier YAML from EHAL-Com (`ENTITY_*` placeholders + periodic push). `ehal.ha.transport` and REST pull are removed (migration `dm4.ha_pull_removal`). Optional `sign` / `boolean_invert` under `ehal.ha`; URL/token in `config/.env` (`EHAL_HA_*`) where still required by the loader / Supervisor proxy. |
| Inverter today | Optional role `inverter`: bindings `inv.{id}.*` on `inverters[].ehal_bindings` (entity-scoped, same storage idea as `ess.{id}.*`). Without mapped inverter fields the plant behaves as before; `sens_pv_production_active` stays the plant PV sum. |




## Qualified EHAL IDs (2.7.n-2)

Exchange / display form of every signal on the push/exchange wire and in `status.json` keys (Loxone VO; HA **push** uses the same qualified IDs). Implemented in `ehal/qualified_ids.py` (builders + `parse_qualified_id`).

| Form | Example | Notes |
| ---- | ------- | ----- |
| Plant bare | `sens_temperature_outside`, `sens_pv_production_active` | House-wide fields without a device Kennung; plant PV sum stays bare; per-PV-system power uses `pv.{id}.*` |
| Grid meter | `grid.meter.sens_grid_power_active` | First Kennung `meter`; more `grid.<Kennung>.*` meters may follow. Plant **storage** keeps bare kind keys |
| Battery | `ess.<Kennung>.sens_ess_soc` | Entity-scoped binding key |
| Consumer by type | `consumer.<slug>.set_enable`, `heatpump.<slug>.*`, `pool.<slug>.*` (incl. `pool_filter`) | Storage and exchange; legacy `flex.<slug>.*` accepted on parse / dual-read until migrated |
| EV split | `evcs.<slug>.set_evcs_max_current`, `ev.<slug>.sens_evcs_soc_act` | Same Kennung; namespace chosen by field kind |
| Inverter | `inv.<Kennung>.*` | Entity-scoped on `inverters[].ehal_bindings` (**2.7.l P4**) |
| Heartbeat (read) | `heartbeat_smarthome` | Link proof Hub→Earnie; not a field kind |
| Heartbeat (write) | `heartbeat_earnie` | Earnie→Hub Unix watchdog in `status.json`; not a field kind |
| Request optimize | `request_optimize` | Daemon HTTP wake receipt (`POST /ehal/loxone/request_optimize`); not a field kind |

`parse_qualified_id(id)` → `ParsedQualifiedId(namespace, kennung, kind, raw)` or `None`. Plant bare, heartbeats, and `request_optimize` have `namespace` / `kennung` = `None`. Round-trip: builders → parse → `format_qualified_id` restores the exchange string. Field kinds are not renamed in 2.7.n.

## Schema version and envelope

Every Telemetry, Setpoint, and Capabilities document uses the same envelope fields:


| Field            | Type              | Required | Meaning                                                                                                  |
| ---------------- | ----------------- | -------- | -------------------------------------------------------------------------------------------------------- |
| `schema_version` | integer           | yes      | Wire version; **current =** `4` (`set_ess_source_select` / 2.7.h; Design C1 was **2.4.o** / v3; `sens_*` freeze **2.4.j** / v2; M1 was `1`) |
| `ts`             | string (ISO-8601) | yes      | Sample / write time with timezone (`Z` or offset). Prefer UTC.                                           |
| `adapter_id`     | string            | yes      | Stable adapter instance id (e.g. `openems-lab`, `earnie-hems`)                                           |


**Frozen choice:** `ts` is **ISO-8601 with timezone**, not epoch milliseconds.

## Units and sign convention (frozen)

EHAL base units (adapters normalize hub-native units into these):


| Quantity / domain                                                                                                                                  | Unit   | Sign / range                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------- |
| Active power telemetry (`sens_grid_power_active`, `sens_pv_production_active`, `sens_evcs_active_power`, `sens_ess_power`, `sens_inv_power_ac`, `sens_inv_power_pv`, `sens_power_consumers`) | **W**  | See below                                                                             |
| ESS charge/discharge **limits**, `set_grid_export_power_limit` / `get_grid_export_power_limit`, `get_ess_max_charge_power` / `get_ess_max_discharge_power`, `get_inv_max_ac_power` / `get_inv_max_pv_power`, `set_inv_ac_power_limit` | **W**  | Non-negative **magnitudes** (true caps); direction is in the field name, not the sign |
| `set_ess_active_power`                                                                                                                             | **W**  | Signed; `+` = discharge, `−` = charge (omit on Automatik)                             |
| Energy counters / capacity (`sens_pv_energy`, `sens_grid_energy_import` / `_export`, `sens_ess_energy_charge` / `_discharge`, `sens_energy_total`, `sens_evcs_bat_capacity`) | **kWh** | Cumulative or capacity ≥ `0`; HA may convert Wh → kWh at the boundary                 |
| `sens_ess_soc` / EV SoC fields                                                                                                                     | **%**  | `0`…`100`                                                                             |
| `set_evcs_max_current` / `get_evcs_nominal_current`                                                                                                | **A**  | Non-negative                                                                          |
| Temperature (`sens_temperature_outside`, pool water/setpoint/tolerance, heat-storage `sens_temperature_heat_storage` / `_low`)                     | **°C** | Celsius only (no °F on the wire); adapters must convert hub °F if ever present        |
| Duration (`get_filter_remaining_hours`, `get_filter_native_duration_hours`, …)                                                                     | **h**  | Hours; non-negative                                                                   |
| Modes / flags (`set_ess_mode`, `set_evcs_mode`, `sens_absent_mode`, `sens_evcs_connected`, …)                                                       | —      | Dimensionless (enums or `0`/`1`); no physical unit                                    |


**Export limit "unconstrained" (2.7.a / 2.7.c / 2.7.l):** sticky backends always receive a number on `set_grid_export_power_limit`. When no cap applies, Earnie writes the plant's physical export maximum = Σ over **grid-tied** inverters of `min(max_ac_power_kw, PV kWp of its PV systems capped by max_pv_input_kw + max discharge of its force-dischargeable batteries)`; an inverter without `max_ac_power_kw` contributes the uncapped sum (previous behaviour). `island` inverters contribute nothing. Fallback when all unknown: `1 000 000` W. ESS bindings use entity-scoped `ess.{slug}.*` on `batteries[].ehal_bindings`; inverter bindings use `inv.{id}.*` on `inverters[].ehal_bindings`.

**Grid** (`sens_grid_power_active`)**:** `+` = grid **import** (Bezug), `−` = **export** (Einspeisung). Adapters normalize hub-native signs before emit.

**PV** (`sens_pv_production_active`)**:** production ≥ `0` (W). Interval energy = ∫ power × Δt (no cumulative counter on the wire). Bare `sens_pv_production_active` is the plant **AC** sum. Optional entity-scoped fields: `pv.{pv_system_id}.sens_pv_production_active` on `pv_systems[].ehal_bindings` and `inv.{id}.sens_inv_power_pv` on inverters.

When the plant field is unmapped and every **grid-tied** inverter that owns ≥1 PV system has inverter PV (mapped, or fully derived from its PV systems), post-read attribution sets plant = Σ (inverter PV · η_inv). Island inverters are excluded. Incomplete maps fail loud. Curtailment still uses forecast shares (live-weight switch deferred).

**EVCS** (`sens_evcs_active_power`)**:** charge power ≥ `0` (W) when charging; `0` when idle.

**ESS** (`sens_ess_power`, optional)**:** OpenEMS-aligned — `+` = **discharge**, `−` = **charge**. Adapters whose source uses the opposite convention (e.g. Victron: `+` = charge) must invert at the boundary. Loxone battery Merker already use `+` = discharge (no inversion).

**Reference power balance (normative):** all power signs are chosen so that every flow *into the house* is positive. Ignoring inverter losses:

```text
P_cons = P_PV + P_Grid + P_Bat
         (sens_power_consumers = sens_pv_production_active + sens_grid_power_active + sens_ess_power)
```

Per-inverter values refine `P_PV` / `P_Bat`; they never replace the plant-level identity.

| Term | Field | `+` | `−` |
|------|-------|-----|-----|
| `P_PV` | `sens_pv_production_active` | production | — (≥ 0) |
| `P_Grid` | `sens_grid_power_active` | import (Bezug) | export (Einspeisung) |
| `P_Bat` | `sens_ess_power` | discharge | charge |
| `P_cons` | `sens_power_consumers` | house load | — (≥ 0) |

Every adapter, derived value (`sens_power_consumers` when not mapped), and Live dict follows this convention; hub-native signs are normalized at the adapter boundary. Example: Huawei registers 37113 (grid, `+` = export) and 37765 (battery, `+` = charge) must both be negated.

**Hub unit conversion (registry):** static hub ↔ EHAL conversion lives in optional `loxone` / `openems` blocks on fields in `share/ehal/roles/*.json` (schema `device_roles.schema.json`). `factor` / `sign` always mean hub → EHAL; `ehal/field_registry.py` exposes `apply_loxone_read` / `apply_loxone_write` (and OpenEMS equivalents). Writes clamp in EHAL space then invert; `omit_if` / `read_required` are read-only. Top-level role `required` remains mapping completeness. HA keeps runtime unit factors in `integrations/ha_units.py` (entity `unit_of_measurement`; Binding P5 parity later).

**House load** (`sens_power_consumers`, optional)**:** a mapped hub channel / binding is preferred; otherwise the value is derived from the grid/PV/ESS balance.

## Telemetry-API (schema_version 4)


| Field                         | Required | Unit   | Notes                                                                                                      |
| ----------------------------- | -------- | ------ | ---------------------------------------------------------------------------------------------------------- |
| `sens_grid_power_active`      | yes      | W      | PCC active power; sign as above                                                                            |
| `sens_pv_production_active`   | yes*     | W      | ≥ 0; *always required on the telemetry document (`telemetry.schema.json`). The **mapping** may be omitted when Live derives it from complete grid-tied inv/pv maps (`with_live_pv_attribution`); validation then runs on the derived value, and Live fails loud if it cannot be derived. |
| `pv.{id}.sens_pv_production_active` | no | W | ≥ 0; optional per-PV-system DC power. Entity-scoped binding / push key only; **not** a property of the telemetry document (the schema has `additionalProperties: false`) |
| `ess.{id}.sens_ess_soc`       | Live yes | %      | Home battery SoC; **not** on the plant telemetry document (entity-scoped binding / push only)              |
| `sens_ess_power`              | no       | W      | Optional; sign as above                                                                                    |
| `sens_evcs_active_power`      | no       | W      | ≥ 0 when present                                                                                           |
| `sens_power_consumers`        | no       | W      | House load; mapped binding or derive                                                                       |
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
| `inv.{id}.sens_inv_power_ac`  | no       | W      | Per inverter; `+` = feeds the AC bus (2.7.l)                                                               |
| `inv.{id}.sens_inv_power_pv`  | no       | W      | ≥ 0 (2.7.l)                                                                                                |
| `inv.{id}.get_inv_max_ac_power` | no     | W      | Device AC rating, magnitude (2.7.l)                                                                        |
| `inv.{id}.get_inv_max_pv_power` | no     | W      | DC/MPPT limit, magnitude (2.7.l)                                                                           |


Machine schema: `[share/ehal/telemetry.schema.json](../../share/ehal/telemetry.schema.json)`.

## Setpoint-API (schema_version 4)

Setpoints are **math limits / forced power / modes**, not a full inner-loop controller. Realtime enforcement stays in the subsystem (OpenEMS / HA / inverter).

**Design C1:** force lives in `set_ess_active_power`; charge/discharge fields are **true caps**. OpenEMS uses active power + limits and **ignores** `set_ess_mode`.

**Sticky backends (hub/entity holds):** sticky hubs keep the **last written value**. Omitting `set_ess_active_power` on the wire does **not** clear a stale setpoint. Earnie therefore **always writes** `set_ess_mode` **on every ESS cycle**. **Automatik / inverter free =** `set_ess_mode = 0` — Config must treat mode 0 as “ignore Sollleistung / release force,” even if a sticky channel (Loxone example: `Earnie_Batterie_Sollleistung`) still holds an old number. Do **not** infer Automatik from absent/`null` active power alone on sticky paths.


| Field                           | Required in doc | Unit          | Notes                                                                                                                                                                                           |
| ------------------------------- | --------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set_ess_active_power`          | no*             | W             | Forced ESS power (`+` discharge, `−` charge); **omit** on Automatik (OpenEMS: no Equals)                                                                                                        |
| `set_ess_charge_power_limit`    | no*             | W             | Max charge power (magnitude ≥ 0)                                                                                                                                                                |
| `set_ess_discharge_power_limit` | no*             | W             | Max discharge power (magnitude ≥ 0)                                                                                                                                                             |
| `set_ess_mode`                  | no*             | string/number | Sticky-backend control; **0 = Automatik**; battery only (export caps via `set_grid_export_power_limit`); OpenEMS ignores                                                                        |
| `set_ess_source_select`         | no*             | enum 0\|1     | Route locally-attached loads: **0 = grid** pass-through (charge allowed), **1 = battery-only** island. Wire as entity-scoped `ess.{id}.set_ess_source_select` on physical powerstation `standby_backup` only (2.7.h); omit for house ESS / plant. OpenEMS unused. |
| `set_grid_export_power_limit`   | no*             | W             | Max grid export, non-negative magnitude (like ESS limits); `0` = no export; unconstrained = plant maximum (per grid-tied inverter; fallback 1 000 000 W) (2.7.a / 2.7.l) |
| `inv.{id}.set_inv_ac_power_limit` | no*           | W             | Max AC output of this inverter (magnitude ≥ 0). Curtailment tool: Live writes when plant `p_pv_curtail[t0] > 0` (proportional to inverter PV forecast); otherwise sticky release to rating. OpenEMS: see alignment table. |
| `set_evcs_max_current`          | no*             | A             | EV charge current setpoint / max current                                                                                                                                                        |
| `set_evcs_mode`                 | no*             | enum          | `off` \| `pv` \| `now`                                                                                                                                                                          |


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

## Inverter topology (`inverters[]`, 2.7.l)

An inverter is a first-class device in `components.json` → `inverters[]`. PV systems and batteries point to it via `inverter_id`. Built-in inverters (EcoFlow, Balkonkraftwerk storage) are normal inverters with `owned_by: <battery_id>` — no special case on the wire.

**Entity fields:** `id`, `label`, `type` (`hybrid` | `pv_string` | `battery`), `max_ac_power_kw`, `max_pv_input_kw`, `max_ac_charge_kw`, `efficiency`, `control` (`full` | `limits_only` | `read_only`), `ac_connection` (`grid_tied` | `island`), `owned_by`, `ehal_bindings`.

**References:** `pv_systems[].inverter_id`, `batteries[].inverter_id` (n:1). Scenario selects `pv_system_ids[]` / `battery_ids[]`; inverters in play follow from them.


| `type` | PV | Battery | Limits |
| --- | --- | --- | --- |
| `hybrid` | DC side | DC side | `pv + discharge ≤ max_ac`; PV ≤ `max_pv_input` |
| `pv_string` | yes | — | PV ≤ `max_ac` |
| `battery` | — | AC-coupled | charge/discharge ≤ `max_ac` |


`ac_connection`: **bus participation, not grid connectivity.** `grid_tied` = AC side on the house bus; `island` = AC side feeds only attached loads (not the house AC bus), its PV is not part of the house balance, battery never runs in Automatik (replaces `batteries[].kind = isolated`). An `island` inverter may still have a grid-fed AC input as a one-way load (typical powerstation); that is not “off the grid”.

Built-in inverters (`owned_by`): lifecycle/UI flag only; created and deleted with the battery. Virtual powerstations have no inverter (carve-out of the house battery).

`control` per inverter gates `set_inv_ac_power_limit` the same way `batteries[].control` gates ESS writes; EHAL-Com warns when `control` asks for more than bound functions allow.

A battery attached to an inverter with `type: pv_string` is **rejected** (schema / topology validation).

## Plant topology (Topology P1–P2)

Decision record: [`backlog/Plant-Topology-Conclusion.md`](../../backlog/Plant-Topology-Conclusion.md). Earnie balances at exactly one **root balance node** = one tariff boundary. Sub-nodes (`balance_nodes[]`, wire `node.*`) arrive in Topology P5 (Version 2.+1); until then the root meter stays `grid.meter.*` on `plant.ehal_bindings`.

**Model (condensed M1–M9):**

| Id | Rule |
| --- | --- |
| M1 | One root = one tariff boundary; user asserts it (`plant.grid_meter`) |
| M2 | A balance node = one upstream connection + n branches; a meter is a measurement on a connection |
| M3 | Scope and control are modelled, copper is not (documented v1 limits for series/pass-through) |
| M4 | Sub-nodes are attribution only; devices behind them stay in the root MILP (P5) |
| M5 | Read per device, control per actuator; generator side of the root must be covered (P2) |
| M6 | At most one active closed-loop **grid** regulator per node (`regulates_on`, not `control`) |
| M7 | A second billing meter is a second economic node — non-goal in v1 (`single_tariff`) |
| M8 | Island / standby stay as today (`ac_connection: island` = bus participation, not “off-grid”) |
| M9 | No readable root → refuse (assertion in v1; opt-in approximation later) |

**Config (P1):**

- `plant.grid_meter`: `{ "at_house_connection": true, "single_tariff": true }` — both must be `true` on the **live path** (daemon + EHAL-Com). Absent or `false` → refuse. SE / backtesting may omit.
- `batteries[].regulates_on`: `"grid"` \| `"none"`, **required** on `type: house` (no silent default). Powerstations must not carry the field. Meaning: which measurement the device’s **own** controller uses when Earnie does not force it. `control: read_only` does **not** mean “does not regulate.”
- Optional `inverters[].regulates_on` (absent ≡ `none`) for a dynamic feed-in limiter on the root meter.

Migration (data model stays **4**): `python -m scripts.migrate_topology_once --config-dir <config-dir>` sets `regulates_on: grid` on every house battery, seeds `plant.grid_meter` true/true, and prints the operator confirm wording. Loader rejects the old shape (fail-fast, no dual-read).

**Live-path validation only** (not SE / backtesting):

| Rule | Behaviour |
| --- | --- |
| (i) Root loops | Count of **grid-tied** house batteries with `regulates_on: grid` plus inverters with `regulates_on: grid` ≤ 1; else refuse (names P3/P4). Island packs are excluded from the count. |
| (ii) Multi house-ESS | At most one grid-tied house battery in the live plan until P3 + P4; second → refuse (no warn-and-exclude). |
| (iii) Single foreign loop | One `read_only` / `limits_only` house battery with `regulates_on: grid` stays accepted (today’s self-consumption pin). |

**Config / live balance (P2 — generator-side coverage):**

- Plant `sens_ess_power` := Σ over grid-tied house batteries of `ess.{id}.sens_ess_power`. Missing binding/value for any eligible battery → fail loud. Battery-less plants omit ESS → `0`.
- When more than one grid-tied inverter owns PV: plant `sens_pv_production_active` is always derived as Σ inv/pv · η_inv (mapped plant PV is ignored); incomplete `inv.*`/`pv.*` coverage fails loud.
- Derived load: `plant.balance_tolerance_pct` (default **5**) and `plant.balance_tolerance_w` (default **100**). Raw `PV + grid + ESS` below `−max(w, pct/100 · P_PV)` → telemetry error (not silent `0`); within tolerance → clamp to `0`.
- Live attribution uses required inverter `efficiency` (η_inv); no soft default.

**Accepted topologies (v1 after P1+P2):** (a)/(a′) one hybrid (+ read-only PV strings with coverage); (d)/(g)/(h) with documented limits; island / standby. **Rejected on live:** (b′) foreign self-consumption beside another loop, (c)/(c′) multi house-ESS / dual vendor loops, (e) no root assertion, (f) second tariff (`single_tariff: false`). Full table: Conclusion §2. P3–P5 (Version 2.+1) widen acceptance (per-ESS writes, reactive MILP, balance nodes).

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
| `supports_inv_power_limit`     | no       | `set_inv_ac_power_limit` can be written (2.7.l curtailment write loop)   |


`supports_ess_write` and `supports_evcs_current` remain required; `supports_ess_source_select` and `supports_inv_power_limit` may be omitted (treated as false).

Machine schema: `[share/ehal/capabilities.schema.json](../../share/ehal/capabilities.schema.json)`.

## Update interval and stale behavior


| Topic                                      | Freeze                                                                                                           |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| Minimum telemetry cadence toward Core      | **60 s**                                                                                                         |
| Faster internal polling                    | Allowed inside the adapter                                                                                       |
| Stale samples                              | Core must tolerate unchanged values until the next sample; adapters should still refresh `ts` when re-publishing |
| Missing **optional** telemetry             | Omit field or set `null` per schema (`sens_ess_power`, `sens_evcs_*`, …)                                         |
| Missing primary `ess.{id}.sens_ess_soc` (Live) | Abort the Live run (house SoC is entity-scoped only; no plant-flat alias)                                     |
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

<a id="fehlertoleranz-m1-defaults"></a>

## Fault tolerance (M1 defaults)


| Situation                      | Behavior                                                                 |
| ------------------------------ | ------------------------------------------------------------------------ |
| Optional telemetry absent      | Omit / null; Core continues                                              |
| Primary `ess.{id}.sens_ess_soc` absent | Live abort                                                         |
| Setpoint write fails           | Log + capability degrade + Write-Error-Telemetry; optimizer continues    |
| Capability false from start    | Skip writes for that family; no repeated error spam beyond periodic hint |
| Schema validation fail         | Reject document; adapter must not pass invalid JSON to Core              |


Numeric hub-tolerance thresholds beyond the above are left to adapter implementation notes (OpenEMS / HA sections below).

## OpenEMS light alignment

Fields map to known OpenEMS Edge channels (semantic reference). Channel architecture, Compose, and lab write tests: `[openems-lab-setup.md](../dev/openems-lab-setup.md)`.


| EHAL field                      | OpenEMS (prototype)                                                                                                                         |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_grid_power_active`        | `_sum/GridActivePower` (normalize: `+` = import)                                                                                            |
| `sens_pv_production_active`     | `_sum/ProductionActivePower`                                                                                                                |
| `ess.{id}.sens_ess_soc`         | `ess0/Soc` / `_sum/EssSoc` (primary; not on plant telemetry doc)                                                                              |
| `sens_ess_power`                | ESS ActivePower (OpenEMS sign; already EHAL-aligned)                                                                                        |
| `sens_evcs_active_power`        | EVCS / EVSE active power channels                                                                                                           |
| `set_ess_active_power`          | e.g. `SetActivePowerEquals` (signed W; omit on Automatik)                                                                                   |
| `set_ess_charge_power_limit`    | e.g. `SetActivePowerGreaterOrEquals` (adapter maps magnitude)                                                                               |
| `set_ess_discharge_power_limit` | e.g. `SetActivePowerLessOrEquals`                                                                                                           |
| `set_ess_mode`                  | *(ignored by OpenEMS)*                                                                                                                      |
| `get_ess_soc_min` / `get_ess_soc_max` / `get_ess_max_charge_power` / `get_ess_max_discharge_power` | *(optional 2.7.j; omit when no Edge channel — Core uses HK fallback)* |
| `set_evcs_max_current`          | EVCS Max Current                                                                                                                            |
| `sens_absent_mode`              | Optional side-channel: `plant.ehal_bindings.sens_absent_mode` = `componentId/ChannelId` (no fixed Edge default; not in core telemetry wire) |
| `sens_inv_power_ac`             | ESS `ess0/ActivePower` (hybrid) / meter `…/ActivePower` (prototype; verify before freezing) |
| `sens_inv_power_pv`             | `charger0/ActualPower` (DC string on hybrid) / PV-inverter `…/ActivePower` |
| `get_inv_max_ac_power`          | `ess0/MaxApparentPower` |
| `get_inv_max_pv_power`          | *(optional / absent)* |
| `set_inv_ac_power_limit`        | PV-inverter `…/ActivePowerLimit` (where available); else unused |




### Deferred device classes


| Class            | When                                                                                                                                                                                                                                                                                                                                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Heatpump         | Not on the core EHAL plant wire; stub role (`share/ehal/roles/heatpump.json`) + Loxone recipe/VO (`share/loxone/recipes/heatpump.json`, `VO_Earnie_Heatpump.xml`). Live: `thermal_annual` consumer `ehal_bindings` for `flex.*` plus `sens_temperature_heat_storage` / `sens_temperature_heat_storage_low` (HA entity IDs or Loxone Merker via entity-scoped HITL) |
| Generic consumer | Flex fields mapped via `consumers[].ehal_bindings` as **`consumer.{Kennung}.*`** (same as Live/VO), incl. **`sens_consumer_active`**. Legacy `flex.{slug}.*` accepted until config migration. Stub role + recipe; VO Merker `Earnie_Verbraucher_<Slug>_Aktiv`                                                                                                                                                                                    |




## Device roles and hardware profiles

**Mapping aids / contribution seeds**, not a new Live I/O path.


| Artifact                | Path                                                                                                                 | Purpose                                                                              |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Device-role schema      | `[share/ehal/device_roles.schema.json](../../share/ehal/device_roles.schema.json)`                                   | Groups M1 fields by role; optional per-field `loxone` / `openems` conversion blocks |
| Field registry          | `[ehal/field_registry.py](../../ehal/field_registry.py)`                                                             | Loads hub blocks; `apply_loxone_read` / `apply_loxone_write` (+ OpenEMS apply)       |
| Role instances          | `[share/ehal/roles/](../../share/ehal/roles)`                                                                       | One JSON per `role_id`                                                               |
| Hardware-profile schema | `[share/hardware_profiles/hardware_profile.schema.json](../../share/hardware_profiles/hardware_profile.schema.json)` | SunSpec / proprietary Modbus outline → EHAL bindings                                 |
| Outline examples        | `[share/hardware_profiles/examples/](../../share/hardware_profiles/examples)`                                       | `sunspec_inverter_ess.outline.json`, `huawei_via_loxone.outline.json`                |
| Loxone recipes          | `[share/loxone/recipes/](../../share/loxone/recipes)`                                                               | JSON Merker / Baustein tips → `ehal_bindings` (no `.loxone` binary)                  |
| Python loader           | `[ehal/profiles.py](../../ehal/profiles.py)`                                                                         | `list_*` / `load_*` + HITL `role_field_labels` / `group_fields_by_role`              |


**Rules:** Stub roles use `kind: stub`. Flex (`flex.*`) and plant fields are mapped on EHAL-Com into `plant` / `consumers[].ehal_bindings`; all ESS including Quellenwahl into `batteries[].ehal_bindings` as `ess.{slug}.*` (**2.7.m**; `set_ess_source_select` only on physical `standby_backup`). Optional inverter role: `inv.{id}.*` on `inverters[].ehal_bindings` (`share/ehal/roles/inverter.json`; same entity-scoped idea as ESS). HITL groups mapping rows by role label. Wire includes `set_ess_mode`, EV `sens_*` / `set_evcs_*` / `get_*`, and optional `sens_power_consumers`.

## Out of scope (this freeze)

- MQTT / Matter as first-class hubs
- HA WebSocket state subscription / direct evcc REST adapter (deferred; REST HA path shipped)
- ARP scan / profile upload. Modbus/SunSpec **outline** schemas under `share/hardware_profiles/` — not a runtime Modbus client (direct Modbus profiles: Entwicklungsplan **M4**).
- Live curtailment weights from measured inv PV (forecast shares remain; helper `attribute_plant_pv_to_inverters_w` ready).



## Implementation notes — OpenEMS

- Adapter: `integrations/openems_adapter.py` (REST only). Live façade: `integrations/ehal_live.py`.
- Compose lab: `docker/compose/openems-lab.yml`. Config snippet: `share/config/ehal.openems.snippet.json`. Step-by-step: `[openems-lab-setup.md](../dev/openems-lab-setup.md)`.
- Cadence: Core expects ≥ 60 s telemetry refresh; adapter may poll faster.
- EVCS: EHAL `set_evcs_max_current` (A) → OpenEMS `evcs0/SetChargePowerLimit` (W) via house-profile V/phases.
- Optional absent / holiday: set `plant.ehal_bindings.sens_absent_mode` to `componentId/ChannelId` (read via `read_channel`; no HITL plant mapper yet).
- Optional inverter: bindings on `inverters[].ehal_bindings` as `inv.{id}.*` (capability `supports_inv_power_limit` reported false until mapped; curtailment write when mapped + `control=full`).
- Southbound silent gate: reuse `silent_mode` (`local_settings.json`) for OpenEMS writes as well.
- Write failures → `runtime/ehal_write_error.json` + UI banner on EHAL-Com / Daemon page.



## Implementation notes — Home Assistant + evcc

### Transport (push-only)

Home Assistant uses the **same Earnie↔SB HTTP contract as Loxone**. There is **no** `ehal.ha.transport` key and **no** REST pull of `/api/states` for live telemetry.

| Direction | Live I/O |
| --------- | -------- |
| **Read (HA → Earnie)** | HA automations / `rest_command` push activated telemetry to `GET /ehal/telemetry/<qualified-EHAL-id>/<value>` (token, inbox freshness, zero rule, last-known — same as Loxone). |
| **Write (Earnie → HA)** | HA polls `GET /ehal/status.json` (canonical; `/ehal/loxone/status.json` kept as alias) for setpoints under qualified keys; payload includes `heartbeat_earnie`. |
| **Listener** | `integrations/loxone_request_http.py` on `system.ehal_loxone_http_port` (default **8541**). |
| **Token** | Optional `EARNIE_PUSH_TOKEN` (alias `EARNIE_PILOT_PUSH_TOKEN`): when set, required via header `X-Earnie-Token`, `/t/<token>/…`, or `?t=`; when unset, open LAN push (same as Loxone). |
| **Cadence** | Every read signal at least every `EARNIE_PILOT_PUSH_REPEAT_S` (default **10 s**). Silent power while the heartbeat link is fresh → assumed **0** (`STATE_ZERO_ASSUMED_SILENT`); **energy counters are never assumed 0**. See [Loxone Signals — push cadence](loxone-signals.md#push-cadence-sb-neutral). |
| **Migration** | Leftover `ehal.ha.transport` is removed by `dm4.ha_pull_removal`; a leftover key afterwards fails loud with a migration hint. Stored HA `entity_id` values are discarded (activation keys kept). |

Adapter: `integrations/ha_adapter.py` (push inbox + `status.json` only). Carrier YAML: `integrations/ha_carrier_yaml.py` / `python -m scripts.ha_carrier_yaml_gen` / EHAL-Com download.

### Units on the HA telemetry wire

Values in the telemetry URL path must already be in **canonical EHAL units** (§ Units table): active power **W**, energy **kWh**, SoC/fills **%**, EVCS current **A**, etc. Earnie does not receive HA `unit_of_measurement` on push — the **HA carrier** (generated Jinja) converts native entity units before calling `/ehal/telemetry/…` (W/kW/MW → W, Wh/kWh/MWh → kWh, %, A; unknown unit → no push + HA log). Setpoints in `status.json` use the same EHAL numeric units as Loxone (e.g. ESS limits in **W**).

### Config and binding UI

- Config: `ehal.backend=ha`; optional `sign` / `boolean_invert` under `ehal.ha` in `config.json`. Snippet: `share/config/ehal.ha.snippet.json` (no `transport`). URL/token in `config/.env` (`EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN`) where the loader / Supervisor proxy still requires them.
- Bindings: `plant.ehal_bindings` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings` / `inverters[].ehal_bindings` — **activation keys only** (empty values). Required keys are activated on Hauskonfigurator save (`dm4.required_signal_activation` for existing packs). Earnie stores **no** HA `entity_id`.
- Contract UI: EHAL-Com **Signalliste** (all backends) + **HA YAML-Paket** download (`ENTITY_*` placeholders, periodic `time_pattern` push, heartbeat, `status.json` REST sensor, setpoint automations including `ha_ess_force`). No HA entity-mapping chapter on EHAL-Com.
- Live aggregation (`aggregate_ha_entities`): activated keys → push-read / setpoint qualified IDs (plant grid/PV/export, battery `ess.{slug}.*`, inverter `inv.{id}.*`, EV/flex, optional energy counters).
- Compose lab: `docker/compose/ha-lab.yml`. Setup: `[ha-lab-setup.md](../dev/ha-lab-setup.md)`. German overview: `[../einrichtung/ha-evcc.md](../einrichtung/ha-evcc.md)`.
- Optimizer exclusivity + Modbus: `ha-evcc.md`. Same Live façade / write-error path as OpenEMS (`is_ehal_network_backend()`).



## Implementation notes — Loxone

- Adapter: `integrations/loxone_adapter.py` (HTTP markers via `loxone_client`). Live façade: `integrations/ehal_live.py` (`get_adapter()` includes Loxone).
- Default config: missing/`none`/`loxone` → `EHAL_BACKEND=loxone`, `adapter_id` default `loxone-home`. Entity-scoped keys on `plant` / `consumers[]` / `batteries[].ehal_bindings` / `inverters[].ehal_bindings` are activation flags (empty Merker values after Q8). Non-empty `config.loxone_blocks` is rejected (run `python -m scripts.migrate_ehal_bindings`).
- Telemetry: kW markers → W via the role `loxone` blocks (`ehal/field_registry.py`); Loxone battery **+discharge** → EHAL `sens_ess_power` **+discharge** (no inversion); grid pass-through as EHAL `+` import; field names §C (`sens_*`). Optional inverter Merker names TBD (`Earnie_WR_…`; recipe `share/loxone/recipes/inverter.json`). Helper: `qualified_inverter_id()`.
- Capabilities: `supports_ess_write` when charge/discharge markers exist; `supports_evcs_current` when EV current write path works; `supports_inv_power_limit` when `inv.{id}.set_inv_ac_power_limit` is mapped (Live curtailment write loop).
- Live writes: ESS limits / `set_ess_mode` via primary-battery entity-scoped `ess.{id}.*`; EV current+mode / flex enable via `status.json` qualified IDs; binding keys activate (Merker value optional).
- Removed from live semantics (wire rename): ESS `target_soc`, EV `soc_at_plug_in`, PV cumulative counter, Sofortladen countdown Merker.



## Implementation notes — Loxone one-click mapping

- Onboarding helper **inside** the Loxone-EHAL path — not a live I/O replacement.
- Structure scan (`integrations/loxone_structure.py`): supports **compare-all** (LoxAPP3 + candidate presence against LoxAPP3, source id `http_probe`, + optional **MCP 17.1**) for lab/compare; MCP helpers remain in `integrations/` for later re-integration.
- **EHAL-Com UI:** mapping names come from the LoxAPP3-presence variant (`sources=(http_probe,)`). MCP URL input, Ollama button, Quellenvergleich, and source picker are not in the shipping UI.
- **Greenfield presence probe:** `integrations/loxone_greenfield_import.probe_marker_names` classifies known `greenfield_device_map.json` names against LoxAPP3 control names (no Merker HTTP). EFM meters still need LoxAPP3.
- Contract UI on EHAL-Com: **Signalliste** for all backends (qualified IDs, Pflicht/optional/aktiviert, match status; Loxone VO/VI export; HA YAML package). Activation keys live on `plant` / `consumers[].ehal_bindings` / `batteries[].ehal_bindings` / `inverters[].ehal_bindings` (`components.json` for ESS and inverters). The older HITL helpers `ui/ehal_loxone_mapping.py` / `ui/ehal_ha_mapping.py` are not mounted on the page.
- Optional LLM (code retained, **not** exposed in UI): local **Ollama** HTTP (`/api/chat`, JSON). Not bundled in Earnie image / LoxBerry ZIP.
- EFM interpretation C (meter tree → Hausprofil consumers + optional flex power): research note `[efm-auto-sync.md](../dev/done/efm-auto-sync.md)`; library `integrations/loxone_efm_meters.py` via greenfield `merge_efm` (Smarthome-Backend Loxone-Import).



## Implementation notes — device / hardware profiles

- Schemas + examples only for Live; adapters keep hardcoded maps.
- HITL labels/grouping via `ehal.profiles.role_field_labels` / `group_fields_by_role` (Loxone + HA mapping UIs).
- Contribution entry: [CONTRIBUTING.md](../../CONTRIBUTING.md) §4.
