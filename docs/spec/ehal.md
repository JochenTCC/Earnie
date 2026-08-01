# EHAL — Earnie Hardware Access Layer (schema_version 3)

**Backlog:** `2.4.a` (M1) → **`2.4.j`** (wire rename) → **`2.4.o`** (Design C1 `set_ess_active_power`)  
**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 §2.2, §2.5 Phase 1, §2.6  
**Canonical field names:** [`docs/ui/ehal-com.md`](../ui/ehal-com.md) §B / §C  
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
| Loxone today | Default `ehal.backend=loxone` uses [`integrations/loxone_adapter.py`](../../integrations/loxone_adapter.py) for plant telemetry/setpoints; during **2.4.j** config may still dual-read legacy `loxone_blocks` / house-profile `*_name` (entity mapping UI is **2.4.k**) |

## Schema version and envelope

Every Telemetry, Setpoint, and Capabilities document uses the same envelope fields:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | integer | yes | Wire version; **current = `3`** (Design C1 in **2.4.o**; `sens_*` freeze was **2.4.j** / v2; M1 was `1`) |
| `ts` | string (ISO-8601) | yes | Sample / write time with timezone (`Z` or offset). Prefer UTC. |
| `adapter_id` | string | yes | Stable adapter instance id (e.g. `openems-lab`, `ha-home`) |

**Frozen choice:** `ts` is **ISO-8601 with timezone**, not epoch milliseconds.

## Units and sign convention (frozen)

| Domain | Unit | Sign / range |
|--------|------|----------------|
| Active power telemetry (`sens_grid_power_active`, `sens_pv_production_active`, `sens_evcs_active_power`, `sens_ess_power`, `sens_power_consumers`) | **W** | See below |
| `sens_ess_soc` / EV SoC fields | **%** | `0`…`100` |
| ESS charge/discharge **limits** | **W** | Non-negative **magnitudes** (true caps) |
| `set_ess_active_power` | **W** | Signed; `+` = discharge, `−` = charge (omit on Automatik) |
| `set_evcs_max_current` / `get_evcs_nominal_current` | **A** | Non-negative |

**Grid (`sens_grid_power_active`):** `+` = grid **import** (Bezug), `−` = **export** (Einspeisung). Adapters normalize hub-native signs before emit.

**PV (`sens_pv_production_active`):** production ≥ `0` (W). Interval energy = ∫ power × Δt (no cumulative counter on the wire).

**EVCS (`sens_evcs_active_power`):** charge power ≥ `0` (W) when charging; `0` when idle.

**ESS (`sens_ess_power`, optional):** OpenEMS-aligned — `+` = **discharge**, `−` = **charge**. Adapters that use the opposite convention (e.g. Loxone Live: + charge) must invert at the boundary.

**House load (`sens_power_consumers`, optional):** prefer mapped Merker; else derive from grid/PV/ESS balance.

## Telemetry-API (schema_version 3)

| Field | Required | Unit | Notes |
|-------|----------|------|-------|
| `sens_grid_power_active` | yes | W | PCC active power; sign as above |
| `sens_pv_production_active` | yes | W | ≥ 0 |
| `sens_ess_soc` | yes | % | Home battery SoC |
| `sens_ess_power` | no | W | Optional; sign as above |
| `sens_evcs_active_power` | no | W | ≥ 0 when present |
| `sens_power_consumers` | no | W | House load; Merker or derive |
| `sens_evcs_connected` | no | bool | EV plugged in |
| `sens_evcs_soc_act` | no | % | Vehicle SoC |
| `get_evcs_nominal_current` | no | A | Nominal / max current |
| `sens_evcs_bat_capacity` | no | kWh | EV battery capacity |
| `get_evcs_ready_by_time` | no | string | Ready-by deadline (Loxone: AlarmClock Tna via `/all`, binding = baustein name) |
| `get_evcs_limit_soc` | no | % | Charge limit SoC |

Machine schema: [`share/ehal/telemetry.schema.json`](../../share/ehal/telemetry.schema.json).

## Setpoint-API (schema_version 3)

Setpoints are **math limits / forced power / modes**, not a full inner-loop controller. Realtime enforcement stays in the subsystem (OpenEMS / HA / inverter).

**Design C1:** force lives in `set_ess_active_power`; charge/discharge fields are **true caps**. OpenEMS uses active power + limits and **ignores** `set_ess_mode`.

**Sticky backends (Loxone / HA entity holds):** Merker/entities keep the **last written value**. Omitting `set_ess_active_power` on the wire does **not** clear a stale Sollleistung. Earnie therefore **always writes `set_ess_mode` on every ESS cycle**. **Automatik / inverter free = `set_ess_mode = 0`** — Config must treat mode 0 as “ignore Sollleistung / release force,” even if `Earnie_Batterie_Sollleistung` still holds an old number. Do **not** infer Automatik from absent/`null` active power alone on sticky paths.

| Field | Required in doc | Unit | Notes |
|-------|-----------------|------|-------|
| `set_ess_active_power` | no* | W | Forced ESS power (`+` discharge, `−` charge); **omit** on Automatik (OpenEMS: no Equals) |
| `set_ess_charge_power_limit` | no* | W | Max charge power (magnitude ≥ 0) |
| `set_ess_discharge_power_limit` | no* | W | Max discharge power (magnitude ≥ 0) |
| `set_ess_mode` | no* | string/number | Sticky-backend control (Huawei Steuerbefehl); **0 = Automatik**; OpenEMS ignores |
| `set_evcs_max_current` | no* | A | EV charge current setpoint / max current |
| `set_evcs_mode` | no* | enum | `off` \| `pv` \| `now` |

\*A setpoint document must include **at least one** of these fields (plus envelope). Partial updates are allowed; omitted fields mean “leave unchanged” at the adapter (except Automatik → omit `set_ess_active_power` so Equals is not forced; sticky backends still rely on **mode = 0**).

Machine schema: [`share/ehal/setpoint.schema.json`](../../share/ehal/setpoint.schema.json).

## Capability-Flags (schema_version 3)

| Field | Required | Meaning |
|-------|----------|---------|
| `supports_ess_write` | yes | ESS setpoints (active power and/or limits) can be written |
| `supports_evcs_current` | yes | `set_evcs_max_current` can be written |

Additional boolean flags may be added in later `schema_version` values without removing these two.

Machine schema: [`share/ehal/capabilities.schema.json`](../../share/ehal/capabilities.schema.json).

## Update interval and stale behavior

| Topic | Freeze |
|-------|--------|
| Minimum telemetry cadence toward Core | **60 s** |
| Faster internal polling | Allowed inside the adapter |
| Stale samples | Core must tolerate unchanged values until the next sample; adapters should still refresh `ts` when re-publishing |
| Missing **optional** telemetry | Omit field or set `null` per schema (`sens_ess_power`, `sens_evcs_*`, …) |
| Missing **required** `sens_ess_soc` (Live) | Abort the Live run (same hard requirement as today’s house SOC) |
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
| Required `sens_ess_soc` absent | Live abort |
| Setpoint write fails | Log + capability degrade + Write-Error-Telemetry; optimizer continues |
| Capability false from start | Skip writes for that family; no repeated error spam beyond periodic hint |
| Schema validation fail | Reject document; adapter must not pass invalid JSON to Core |

Numeric hub-tolerance thresholds beyond the above are left to adapter implementation notes in **2.4.b** / **2.4.c**.

## OpenEMS light alignment (desk-check for 2.4.a)

M1 fields are chosen so they map to known OpenEMS Edge channels (semantic reference). **Deep** channel architecture, Compose, and lab write tests belong to **2.4.b**.

| EHAL field | OpenEMS (prototype) |
|------------|---------------------|
| `sens_grid_power_active` | `_sum/GridActivePower` (normalize: `+` = import) |
| `sens_pv_production_active` | `_sum/ProductionActivePower` |
| `sens_ess_soc` | `ess0/Soc` / `_sum/EssSoc` |
| `sens_ess_power` | ESS ActivePower (OpenEMS sign; already EHAL-aligned) |
| `sens_evcs_active_power` | EVCS / EVSE active power channels |
| `set_ess_active_power` | e.g. `SetActivePowerEquals` (signed W; omit on Automatik) |
| `set_ess_charge_power_limit` | e.g. `SetActivePowerGreaterOrEquals` (adapter maps magnitude) |
| `set_ess_discharge_power_limit` | e.g. `SetActivePowerLessOrEquals` |
| `set_ess_mode` | *(ignored by OpenEMS)* |
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

**Rules:** Stub roles use `kind: stub` (`flex.*` remain stubs until **2.4.k** mapping). HITL on EHAL-Com groups mapping rows by role label. **2.4.j** promotes `set_ess_mode`, EV `sens_*` / `set_evcs_*` / `get_*`, and `sens_power_consumers` onto the wire; marker editors and entity-centric storage are **2.4.k**.

## Out of scope (this freeze)

- MQTT / Matter as first-class hubs
- HA WebSocket state subscription / direct evcc REST adapter (deferred; REST HA path is **2.4.c**)
- Flex first-class wire rename (C.4 stubs stay `flex.*` through **2.4.j**; mapped in **2.4.k**)
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
- Telemetry: kW markers → W; Loxone battery **+charge** → EHAL `sens_ess_power` **+discharge** (`× −1000`); grid pass-through as EHAL `+` import; field names §C (`sens_*`).
- Capabilities: `supports_ess_write` when charge/discharge markers exist; `supports_evcs_current` flips true when EV current write path works (**2.4.j**).
- Live writes: ESS limits / `set_ess_mode` / EV current+mode via adapter + transitional legacy markers; flex stubs still house-profile until **2.4.k**.
- Removed from live semantics (**2.4.j**): ESS `target_soc`, EV `soc_at_plug_in`, PV cumulative counter, Sofortladen countdown Merker.

## Implementation notes (2.4.f Loxone one-click mapping)

- Onboarding helper **inside** the Loxone-EHAL path — not a live I/O replacement. Spec: Entwicklungsplan §3.1.
- Structure scan (`integrations/loxone_structure.py`): still supports **compare-all** (LoxAPP3 + HTTP-Probe + optional **MCP 17.1**). MCP path: resolve `connect.loxonecloud.com/…/mcp` (GET 307) → headless OAuth 2.1 (`LOXONE_USER`/`LOXONE_PASS`) → `tools/list` → `control_find` / `control_describe` (seed from configured `loxone_blocks` and/or LoxAPP3 names; avoid empty/wildcard queries that return EFM `"Rest"` meters; filter low-value hits). Unwrap MCP `content`/`structuredContent`. `sources=(…)` restricts variants.
- **EHAL-Com UI (2.4.o):** mapping names come from **HTTP-Probe only** (`sources=(http_probe,)`). MCP URL input, Ollama button, Quellenvergleich, and source picker are removed from the UI; MCP/Ollama helpers remain in `integrations/` for later re-integration.
- **Greenfield HTTP marker probe (2.4.n):** `integrations/loxone_greenfield_import.probe_marker_names` hits known `greenfield_device_map.json` names via `/jdev/sps/io/{name}`. `LL.Code` `200` or `403` = present (403 common for Virtual HTTP In without App visualization); `404` = missing. Union with LoxAPP3 names for typed Merker match — visualization not required for Earnie_* discovery. EFM meters still need LoxAPP3.
- HITL UI: `ui/ehal_loxone_mapping.py` on EHAL-Com (backend Loxone). Heuristic proposals + manual selects; confirm writes `plant` / `consumers[].ehal_bindings` via house profiles. Field rows grouped by device role (**2.4.g**).
- Optional LLM (code retained, not exposed in UI): local **Ollama** HTTP (`/api/chat`, JSON). Not bundled in Earnie image / LoxBerry ZIP.
- EFM interpretation C (meter tree → Hausprofil consumers + optional `flex.power_name`): **2.4.l** — research note [`docs/spec/efm-auto-sync-2.4.l.md`](efm-auto-sync-2.4.l.md); HITL `integrations/loxone_efm_meters.py` + `ui/ehal_efm_import.py` on EHAL-Com. Manual blueprint remains `.cursor/plans/energieflussmonitor_hausprofil_blueprint_a.plan.md`.

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
