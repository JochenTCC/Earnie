# House simulator (`house_sim/`) — HouseSim S1–S4

**Status:** current (Energy-Optimizer **2.6.a** / HouseSim S1; bindings **2.6.g** entity-scoped; **HouseSim S4** custom integration; **Binding P5d** contract push harness)  
**Purpose:** Fixture-based house physics for HA binding tests — as a **mock REST** bench (S1, retired pull path), a **contract push** harness (P5d), as a real HA custom integration (S4), and as the generated-archetype **HA contract testbed** ([`ha-contract-testbed.md`](ha-contract-testbed.md)).

## What this is (and is not)

| Mode | What it is |
| --- | --- |
| **S1 mock** (`python -m house_sim --mode fixture`) | A **mock for Home Assistant REST**, not a running HAOS. Implements the few endpoints `HaAdapter` needs (Mode A goldens). |
| **Contract push** (`python -m house_sim --mode contract`) | **Binding P5d:** entities from Earnie activated keys; periodic push to `/ehal/telemetry/…` and `status.json` setpoints. No `entity_id` stored in Earnie bindings. |
| **S4 integration** (`earnie_house_sim`) | A **custom integration** inside a real HAOS (Synology dogfood or `ha_lab/haos-docker`) or the HA container of the testbed. Native `sensor` / `number` / `switch` entities; Earnie exchanges data with it over the push contract (HA → `:8541`, `status.json` → HA). Production Earnie code unchanged. |
| **HA contract testbed** (generated archetype) | An archetype **generated from an Earnie configuration pack** (`house_sim/archetype_gen.py`), loaded by S4 from `<config>/earnie_house_sim/archetypes/`, plus the carrier YAML with all `ENTITY_*` filled. Runs in a plain HA container with an automated check. Plan, runbook, support playbook: [`ha-contract-testbed.md`](ha-contract-testbed.md). |

**Not the same as:** [`ha-lab-setup.md`](ha-lab-setup.md) / `ha_lab/` (Compose Earnie+HAOS+evcc = "HA Lab"). Do not put this simulator under `ha_lab/`. Simulator stages are **HouseSim S1–S4** (formerly "HA Lab P1–P4").

### Contract mode vs Mode A goldens

| | **Contract mode (P5d)** | **Mode A goldens (S1/S2)** |
| --- | --- | --- |
| Entity source | Activated `ehal_bindings` keys from a pack (or minimal test pack) | Hand-authored `fixtures/<name>/entities.json` + `ehal.ha.entities.json` |
| HA `entity_id` | Deterministic `sensor.earnie_<slug>` / `number.earnie_<slug>` | Vendor-like ids (`sensor.evcc_…`, …) |
| Earnie bindings | Keys only (empty values) — **no** stored `entity_id` | Golden map merges field→entity into bindings (pull path) |
| Transport | Push to Earnie inbox + poll `status.json` | REST pull via `HaAdapter` (retired for P5 gate; pull removal = **P5e**) |
| Vendor fixtures | Deferred — not required for the P5 gate | `evcc_en`, `fronius_de`, `huawei_en`, `sma_keba` |

Code: `house_sim/contract.py`, `house_sim/push_harness.py`. YAML placeholder fill for tests: `fill_yaml_placeholders` / `fill_carrier_yaml_for_contract`.

**Concept (German):** [Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument.md) §5 S4.

---

## Layout

```text
house_sim/
  core/                 # pure Python (no HA, no Earnie imports)
  fixtures/<name>/      # archetypes (single source) — Mode A goldens
  mock_rest.py          # S1 HTTP mock (pull bench)
  contract.py           # P5d: entities from activated keys
  push_harness.py       # P5d: push client + status.json apply
  stepper.py            # S1 adapter: StateStore → core setpoints
  ha_integration/
    custom_components/earnie_house_sim/
      _core/            # GENERATED copy of core/ (never hand-edit)
      fixtures/         # GENERATED copy of fixtures/
      …                 # config_flow, coordinator, platforms, services
```

Sync after editing `house_sim/core/` or `house_sim/fixtures/`:

```powershell
.venv\Scripts\python.exe -m scripts.sync_house_sim_integration
```

Pytest fails with a pointer to that command if the copy drifts (`tests/test_house_sim_s4_packaging.py`).

---

## S1 — mock REST bench

| Piece | Role |
| --- | --- |
| `house_sim/fixtures/evcc_en/` | One hand-authored archetype + golden field→entity map (Mode A) |
| `house_sim/mock_rest.py` | `GET /api/states`, `GET /api/states/{id}`, `POST /api/services/{domain}/{service}` + Bearer |
| `house_sim/core/` + `stepper.py` | SoC coulomb counter, synthetic PV kW series, optional thermal, cumulative energy (`total_increasing`) |
| Pytest | Real `HaAdapter` HTTP against the mock |

Out of scope for S1: `simulation/engine.py::run_simulation()`, `data/pv_forecast.py`, fake clock in `main.py`, EV/heat-pump physics. Suggest-and-confirm (**2.6.b**) reuses this fixture. Slot-Ist energy maps (**2.6.c**): golden keys `sens_pv_energy` / `sens_grid_energy_import` / `sens_grid_energy_export` (plant `ehal_bindings` after **2.6.g**).

### Run the mock, then start Earnie

1. Start the mock (leave this process running).
2. Start Earnie with `ehal.backend=ha` (Earnie no longer uses an HA URL / token — this mock bench belongs to the retired pull path, see the contract mode below for push). Optional `sign` under `ehal.ha` in `config.json`. Merge the golden field→entity IDs into **`plant.ehal_bindings`** in `house_profiles.json` (EV keys go on the first EV consumer when present). Do **not** rely on flat `ehal.ha.entities` for new installs.

| Setting | Value |
| --- | --- |
| Base URL (`EHAL_HA_BASE_URL`) | `http://127.0.0.1:8124` |
| Token (`EHAL_HA_TOKEN`) | `house-sim-bench-token` |
| Golden map | `house_sim/fixtures/evcc_en/ehal.ha.entities.json` (fixture format; merge keys into entity-scoped bindings) |

Token constant: `house_sim.mock_rest.DEFAULT_BENCH_TOKEN`.

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m house_sim --mode fixture --fixture evcc_en --port 8124
```

Closed-loop ticks without a long-lived server:

```powershell
.venv\Scripts\python.exe -m house_sim --mode fixture --fixture evcc_en --ticks 3 --dt-h 0.25
```

### Contract mode (Binding P5d)

Start Earnie with push token (`EARNIE_PILOT_PUSH_TOKEN`) and daemon HTTP on **8541**, then:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:EARNIE_PILOT_PUSH_TOKEN='your-token'
.venv\Scripts\python.exe -m house_sim --mode contract --earnie-url http://127.0.0.1:8541 --interval 10
```

One-shot smoke (N cycles then exit):

```powershell
.venv\Scripts\python.exe -m house_sim --mode contract --token your-token --cycles 1
```

Default pack is the minimal activated-key fixture in `house_sim.contract.minimal_contract_docs` (plant grid/PV + house battery). Entity ids are local to HouseSim; Earnie bindings stay empty.

### Pytest (S1 + core + packaging + contract)

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m scripts.run_pytest `
  tests/test_house_sim_contract.py `
  tests/test_ha_carrier_yaml_gen.py `
  tests/test_house_sim_mock_rest.py `
  tests/test_house_sim_stepper.py `
  tests/test_house_sim_ha_adapter_loop.py `
  tests/test_house_sim_core_scenarios.py `
  tests/test_house_sim_s4_packaging.py `
  tests/test_house_sim_s2_archetypes.py `
  tests/test_ha_adapter.py -q --tb=short
```

`tests/test_house_sim_ha_adapter_loop.py` is skipped until **Binding P5e** removes pull (`reason: Binding P5d: pull retired pending P5e`). Prefer `tests/test_house_sim_contract.py` for the push path.

---

## S2 — vendor archetypes

Three more hand-authored archetypes on the same physics (Mode A golden maps). Each has a `meta.json` with sources, what was checked against the integration code, and what is still unverified.

| Archetype | Hardware (HA integration) | What it exercises |
| --- | --- | --- |
| `fronius_de` | Fronius GEN24 Plus + BYD HVS (Core `fronius`), Fronius Wattpilot (HACS `goecharger_api2`) | German entity ids/names, energy counters in **Wh**, **no ESS setpoints** (read-only integration), wallbox mode as `select` |
| `huawei_en` | Huawei SUN2000 + LUNA2000 + DTSU666 (HACS `huawei_solar`), go-e Gemini (HACS `goecharger_api2`) | **Vendor sign** (meter + = export, battery + = charge → `negate`), only charge/discharge **limits** (no active-power entity), SoC named "state of capacity", battery totals with `state_class: total` |
| `sma_keba` | SMA Sunny Tripower Smart Energy (Core `sma`), KEBA P30 (Core `keba`), user template/Modbus helpers | Mixed language, **kW** power and a **kW setpoint** (`input_number.batterie_sollleistung`), SMA split channels (supplied/absorbed, charge/discharge) behind signed template helpers, distractor `…_grid_power` (inverter AC), wallbox without writable current, no heat pump |

Core behaviour added for S2:

- **Unit-aware projection:** physics is written in each entity's `unit_of_measurement` (W/kW, Wh/kWh); a unit of the wrong quantity (e.g. kWh on a power field) raises. Fixture counter states in Wh are read as kWh.
- **Vendor sign:** `sign: {field: "negate"}` in the golden map makes the projection write the vendor sign; `HaAdapter` negates back to EHAL.
- **Unit-aware setpoints:** mapped setpoint entities in kW are read as W by the stepper.
- **`ess_fallback: "self_consumption"`** (house_params): without a mapped `set_ess_active_power`, the battery follows PV surplus / deficit within limits (`ess_max_charge_w` / `ess_max_discharge_w` or mapped limit entities) and never overshoots 0/100 % SoC. If neither a mapped limit nor the matching house param is set, the step raises — there is no silent kW default.
- **`derived_entities`** (house_params): `{entity_id: grid_import_power_w | grid_export_power_w | ess_charge_power_w | ess_discharge_power_w | grid_power_w | ess_power_w}` for unsigned split channels.
- Grid balance uses the EHAL sign: `grid = load − pv − ess` (discharge lowers import). Before S2 the battery term had the wrong sign.
- Mock REST rejects `number`/`input_number` values outside `min`/`max` and `select` options outside `options`, like HA.
- S4: `select` platform; sensor `state_class: total`.

Earnie side: HA bindings are unit-aware (`integrations/ha_units.py`) — only physically compatible entities are proposed/saved, and `HaAdapter` converts reads and setpoint writes using the entity's `unit_of_measurement` at runtime, so `sma_keba`'s kW setpoint is written in kW. Known gap: wallbox writes (`amp` / `frc`) do not yet act on physics (wallbox power is still a scenario override).

---

## S4 — custom integration `earnie_house_sim`

Dev/dogfood only — **not** shipped with the Earnie add-on. No PyPI package, no symlinks.

### Install on HAOS

For a Docker HA on the dev PC use `python -m scripts.ha_testbed install` (copies the integration, patches `configuration.yaml`, restarts HA); see [`ha-contract-testbed.md`](ha-contract-testbed.md). By hand on a HAOS:

1. Sync (from the Energy-Optimizer repo root): `python -m scripts.sync_house_sim_integration`
2. Copy `house_sim/ha_integration/custom_components/earnie_house_sim/` to HA `/config/custom_components/earnie_house_sim/` (Samba / SSH add-on).
3. Restart Home Assistant → Settings → Devices & services → Add integration → **Earnie House Simulator**.
4. Config flow: archetype (shipped: `evcc_en`, `fronius_de`, `huawei_en`, `sma_keba`; generated ones from `/config/earnie_house_sim/archetypes/<name>/`, see `scripts.ha_testbed_build`; a name used by both roots aborts the flow), PV source **synthetic** (fixture series) or **weather** (existing `weather.*` entity that exposes `cloud_coverage`; scaled by `pv_kwp` and `sun.sun` elevation). Missing `cloud_coverage` is rejected in the flow.
5. Connect Earnie over the push contract: `ehal.backend=ha`, `EARNIE_PILOT_PUSH_TOKEN` in `config/.env`, activate the signals in the Signalliste, generate the carrier YAML (EHAL-Com or `scripts.ha_carrier_yaml_gen`) and map the `ENTITY_*` placeholders to the sim entities — for a generated archetype `placeholders.json` already holds the mapping. There is no pull path and no HA URL / token in Earnie any more; do not merge the golden map into bindings.

### Entity ID note (`input_number` → `number`)

A custom integration cannot register `input_number`. Fixture rows `input_number.ess_*` become **`number.ess_*`** (same object id). Sensors, `number.evcc_loadpoint_1_max_current`, and `switch.evcc_loadpoint_1_enable` keep their archetype ids. The mock bench still uses `input_number.*` for S1 regression.

### Services

Domain `earnie_house_sim`: scenarios `cloud_pass`, `car_arrives`, `car_leaves`, `load_spike`, `set_soc`; faults `set_unavailable`, `reject_writes`, `setpoint_lag`, `unit_flip` (PV only: a kW entity is shown ×1000, a W entity ÷1000, unit attribute unchanged). Wallbox power is a scenario override only (no EV SoC model in this pass).

### Persistence

Energy counters (`total_increasing`) and SoC are stored across HA restarts. After restart the wall clock resumes from “now” (downtime is not integrated as one jump).

### Manual acceptance (Synology / HA Lab)

- Integration loads; config flow with `evcc_en` creates devices and entities.
- Earnie reads PV, SoC, grid±, energy; slot Ist from ΔkWh looks plausible.
- Battery setpoint from Earnie moves SoC / grid on the next tick.
- `reject_writes` → Earnie `_record_write_error` / capability degrade; `set_unavailable` does not crash Earnie.
- Counters stay monotonic after HA restart.

---

## Fixture layout

```text
house_sim/fixtures/<name>/
  entities.json           # vendor signature (HA state objects) + optional devices[]
  ehal.ha.entities.json   # golden field→entity_id map + optional sign
  house_params.json       # battery_kwh, load, optional thermal RC, ess_fallback, derived_entities
  pv_series.json          # short synthetic kW series
  meta.json               # S2+: provenance (sources, verified, unverified)
```

`evcc_en` includes `switch.evcc_loadpoint_1_enable` (not mapped — negative case) and no heat-pump entity. Optional `devices` list is used by S4 for HA device registry; the mock loader ignores it for HTTP shape.
