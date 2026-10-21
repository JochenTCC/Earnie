# HA contract testbed — carrier YAML ↔ HouseSim in a real Home Assistant

**Status:** plan — drafted 2026-10-21; P1–P5 (WP1–WP8) implemented 2026-10-21; open: first live run of the check, switch/select setpoints (finding 5)
**Purpose:** A permanent, reproducible test bench for the Home Assistant push contract (EHAL-Com) without owning a production HA install: generate the carrier YAML from *any* Earnie configuration, derive a matching simulated house from the same configuration, load both into a real HA container and verify the full loop (HA → Earnie telemetry, Earnie → `status.json` → HA setpoints). Secondary use: reproduce customer problems from their configuration pack.

Related: [`house-sim.md`](house-sim.md) (HouseSim S1–S4, contract mode), [`ha-lab-setup.md`](ha-lab-setup.md) (Compose lab), [`../ui/ehal-com.md`](../ui/ehal-com.md) (Signalliste, YAML package), `integrations/ha_carrier_yaml.py`.

---

## 1. Idea

```text
Earnie config (house_profiles.json + components.json)
   │  activated ehal_bindings keys (no entity_ids stored)
   ├──► build_carrier_yaml()          → carrier YAML with ENTITY_* placeholders
   └──► NEW archetype generator       → sim archetype (entities, physics map, params)
                │                            │
                │ deterministic ids          │
                └──► fill ENTITY_* ◄─────────┘
                            │
                            ▼
   HA container: custom_components/earnie_house_sim  +  packages/earnie_ha_carrier.yaml
                            │
        :8541 push ◄────────┴────────► status.json poll
                       Earnie (daemon + Streamlit)
```

The existing pieces already cover half of it:

| Piece | State |
| --- | --- |
| Carrier YAML from activated keys (`integrations/ha_carrier_yaml.py`, CLI `scripts.ha_carrier_yaml_gen`) | exists |
| Deterministic entity ids from activated keys (`house_sim/contract.py::build_contract`, `contract_entity_id`) | exists — but only feeds an in-memory `StateStore` for the **push harness** (no HA involved) |
| `ENTITY_*` fill (`fill_yaml_placeholders`, `fill_carrier_yaml_for_contract`) | exists (tests only) |
| Real HA entities + physics (`earnie_house_sim`, S4) | exists — but driven by hand-authored **vendor archetypes** (`evcc_en`, …) |
| HA container stack | exists (`docker/compose/ha-lab.yml`, HA `2025.7.0`) — also carries evcc/HACS that this bench does not need |

**Was missing (all built, § 3b–3e):** (a) archetype generator "activated keys → S4 archetype", (b) S4 loading an archetype from outside its shipped `fixtures/`, (c) the glue (compose, install script, checks), (d) the runbook.

## 2. Findings that shape the design

Read from the code, not yet run:

1. **Physics is keyed by flat field names.** `house_sim/core/archetype.py::TELEMETRY_PROJECTION` and `physics.py::ess_setpoints_from_lookup` look up `sens_grid_power_active`, `sens_pv_production_active`, `set_ess_active_power`, … in `ehal.ha.entities.json`. Telemetry additionally accepts `ess.<id>.<kind>` (`_entity_id_for_kind`); setpoints accept **flat keys only**. Earnie's qualified ids (`grid.meter.sens_grid_power_active`, `ess.house.set_ess_active_power`, `inv.<id>.*`, `consumer.<slug>.*`) therefore do not hit the physics. Either the generator emits the flat names for the physics-driven subset (no core change), or the core resolves qualified ids (cleaner, but core must stay hub-agnostic — no `ehal` import, resync via `scripts.sync_house_sim_integration`).
2. **Only a subset of signals is physical.** Projection covers grid power/energy, PV power/energy, ESS SoC/power, EVCS power, battery charge/discharge energy and the ESS setpoints. Everything else the contract can activate (consumer power, heat-pump temperatures, inverter AC/PV, `get_*` limits, `sens_absent_mode`, …) needs either a static value or a small generic model. Static is acceptable for a contract test; it must be explicit (no silent defaults — `no-implicit-fallbacks.mdc`).
3. **`house_params.json` needs real numbers** (battery capacity, load, initial SoC). Take them from the Earnie config where present, otherwise from explicit generator arguments. Missing → fail loud.
4. **S4 only lists archetypes under its shipped `fixtures/`** (`config_flow.py::_list_archetypes`). A generated archetype needs a second, writable location (e.g. `/config/earnie_house_sim/archetypes/<name>/`) or a flow option "archetype directory".
5. **Writes in the carrier are `number.set_value` only** (`_setpoint_automation`). Setpoints on `switch` / `select` targets (flex `set_enable`, `set_evcs_mode`, `set_ess_source_select`) are not applied by the generated YAML, although S4 provides `switch` and `select` platforms. A testbed with typed sim entities will expose this immediately → decide: generator emits `switch.turn_on/off` / `select.select_option` automations, or the contract states "numbers only". **Needs a product decision before WP1.**
6. **`sensor: - platform: rest`** (status sensor) is the legacy form. Verify it still loads on the pinned HA (`2025.7.0`) and on current stable before treating the YAML as customer-ready.
7. `ha-lab.yml` header comments still describe REST pull; stale doc, harmless.
8. `ha_lab/haos-docker` (qemux/homeassistant) needs KVM — poor fit on Windows Docker Desktop. The **HA Container image** (as in `ha-lab.yml`) is sufficient: it loads `custom_components/` and `packages/`; it only lacks Supervisor/add-ons, which this bench does not test.

What the bench proves and does not prove:

| Proves | Does not prove |
| --- | --- |
| Generator output is valid HA YAML and loads | Behaviour of a customer's real devices/integrations (unit quirks, vendor signs, sleeping inverters) |
| Push cadence, heartbeat, unit conversion in Jinja, `status.json` round-trip | Supervisor/add-on lifecycle (see add-on release-candidate procedure in `packaging/homeassistant-addon/README.md`) |
| Earnie reaction to stale/missing push, write rejection, unit flip (S4 fault services) | The manual `ENTITY_*` mapping step real users do (do that by hand once per release) |
| A customer's *activated signal set* works end-to-end | |

## 3. Work packages

Backlog: epic **HA Testbed** in `backlog/Backlog.md` (Version 2.7, under *Dogfood and finalize new HA binding*). Mapping: WP0 = P0, WP1+WP2 = P1, WP3+WP4 = P2, WP5 = P3, WP6 = P4, WP7+WP8 = P5.

Order matters: WP0 first (cheap, finds product-level gaps), then WP1–WP5, then WP6–WP7.

### WP0 — Baseline smoke with what exists (no code)
Run the runbook part A below with `evcc_en`. Output: a short findings list (YAML load errors, switch/select gap, `rest` sensor deprecation, host reachability). Decides finding 5 and 6 before any code is written.
*Done when:* Live-Lesen shows pushed values from HA for the `evcc_en` signal set and a Schreibtest ESS limit changes the sim `number`.

### WP1 — Archetype generator *(done 2026-10-21, see § 3b)*
New `house_sim/archetype_gen.py` + CLI `python -m scripts.house_sim_archetype_gen --config-dir <cfg> --out <dir> [--battery-kwh … --load-kw …]`.
- Input: `house_profiles.json`, `components.json` (same loader as `ha_carrier_yaml_gen`).
- Output directory in the existing archetype layout: `entities.json` (typed entities: `sensor`/`number`, later `switch`/`select`, units + device classes from `ehal.ha_units`, deterministic ids via `contract_entity_id`), `ehal.ha.entities.json` (flat keys for the physics-driven subset, see finding 1), `house_params.json`, `pv_series.json`, plus `placeholders.json` (`ehal_id → entity_id`, the single source for the fill step) and `meta.json` (generator version, source pack hash, list of static/non-physical entities).
- Reuses `build_contract` / `contract_entity_id`; no new id scheme.
- Fail loud on: stored `entity_id`s in bindings (already enforced), unit/quantity mismatch, missing battery capacity.
*Tests:* `tests/test_house_sim_archetype_gen.py` — minimal pack and a full pack (ESS + inverter + EV + heat pump + pool): every activated signal has an entity; ids unique; `load_archetype()` loads the output; `step_physics` runs; no `ENTITY_*` left after fill.

### WP2 — Core: qualified-id resolution *(skipped: WP1 emits flat keys, § 3b)*
Extend `_entity_id_for_kind` / `ess_setpoints_from_lookup` to resolve qualified ids (`grid.meter.*`, `ess.<id>.*`). Keep `house_sim/core/` free of `ehal` imports. Run `python -m scripts.sync_house_sim_integration`; `tests/test_house_sim_s4_packaging.py` must stay green. Skip this WP if the generator emits flat keys.

### WP3 — S4: external archetype directory *(done 2026-10-21, § 3c)*
`config_flow.py` / `coordinator.py`: additional archetype root `/config/earnie_house_sim/archetypes/` (listed next to the shipped ones, name collision = error). Platforms (`sensor`/`number`/`switch`/`select`) already build from `package.entities`, so no platform change expected. Resync + packaging test.

### WP4 — Fill + package output *(done 2026-10-21, § 3c)*
`python -m scripts.ha_testbed_build --config-dir <cfg> --out <testbed-dir> --earnie-host <host> --token <t>` runs: carrier YAML → fill from `placeholders.json` → `packages/earnie_ha_carrier.yaml`; archetype → `earnie_house_sim/archetypes/<name>/`; a `configuration.yaml` snippet (`homeassistant: packages: !include_dir_named packages`). Fails if any `ENTITY_*` placeholder survives.

### WP5 — Compose + install script *(done 2026-10-21 except REST onboarding, § 3d)*
- `docker/compose/ha-sim-testbed.yml`: `homeassistant` (pinned, same as lab) + optional `earnie` service; **no** evcc/HACS. Ports: HA 8123, Earnie UI 8506, Earnie daemon 8541 published to the host.
- `scripts/ha_testbed.py` with `up | down | install | status | reset`: copies `custom_components/earnie_house_sim`, writes the WP4 output into the HA config volume, patches `configuration.yaml` idempotently, restarts HA, and (optional, later) completes HA onboarding + creates the config entry via the HA REST API so no UI clicking is needed.

### WP6 — Automated check *(done 2026-10-21, § 3e)*
`python -m scripts.ha_testbed_check` (against a running bench):
1. HA reachable; sim entities exist with expected units.
2. Earnie inbox holds every activated read signal, fresh (< 2× push cadence); heartbeat OK.
3. Setpoint round-trip: publish a setpoint in Earnie (Schreibtest path, silent off) → `status.json` → sim `number` changes within N cycles.
4. Negative: `earnie_house_sim.reject_writes` → write-error document; `set_unavailable` → no crash; stop the carrier automation → Live-Lesen shows `0 angenommen (verstummt)` while energy counters never invent 0.
Report as pass/fail table; non-zero exit on failure. Optional pytest wrapper marked `ha_container` (skipped by default, runnable on demand/nightly — not part of the default quality gate).

### WP7 — Docs and backlog *(done 2026-10-21)*
German operator page under `docs/einrichtung/` is **not** needed (dev-only). Update `house-sim.md` (remove the stale "bind with 2.6.h UI / merge golden map" steps), `ha-lab-setup.md` header, and link this page from both. Backlog entries per `backlog.mdc` (IDs per `roadmap-nomenclature.mdc`; anonymize per `backlog-anonymize-users.mdc`).

### WP8 — Support playbook *(done 2026-10-21, see § 4 › Customer-problem reproduction)*
Customer sends `house_profiles.json` + `components.json` (contain activation flags only — no entity ids, no tokens; still review before sharing) → `ha_testbed_build` + `ha_testbed up` → run check. Document what that can and cannot reproduce (table in §2) and a template for "what to ask the customer" (HA version, which entities they bound, unit of each, their filled YAML with tokens removed, Earnie `runtime/` state).

### Risks / open decisions
| # | Item | Decide by |
| --- | --- | --- |
| 1 | switch/select setpoints in carrier (finding 5) | WP0 |
| 2 | Flat keys vs qualified resolution in core (finding 1) | **decided:** flat keys (§ 3b) |
| 3 | Non-physical signals: static values vs small generic models | **decided:** static, as `number` entities (§ 3b) |
| 4 | Legacy `platform: rest` sensor on current HA (finding 6) | WP0 |
| 5 | Pinned HA version vs "latest stable" matrix (nightly) | after WP6 |
| 6 | Docker Desktop on the dev PC; Windows firewall for 8541 when Earnie runs natively | WP0 |

---

## 3b. P1 decisions (archetype generator, 2026-10-21)

Implemented in `house_sim/archetype_gen.py`, CLI `python -m scripts.house_sim_archetype_gen --config-dir <cfg> --out <dir> [--battery-kwh … --load-kw … --initial-soc … --pv-points … --static KEY=VALUE]`, tests `tests/test_house_sim_archetype_gen.py`. Output: `entities.json`, `ehal.ha.entities.json`, `house_params.json`, `pv_series.json`, `placeholders.json` (`ehal_id → entity_id`, input of the fill step), `meta.json`.

1. **Flat keys, no core change (WP2 skipped).** The generator emits the flat physics names (`sens_grid_power_active`, `set_ess_active_power`, …) in `ehal.ha.entities.json`, mapped to the deterministic qualified-id entities (`contract_entity_id`). `house_sim/core/` and the S4 copy are untouched. Consequence: the physics sees exactly one battery and one PV source (see limits).
2. **Physical vs static.**
   - Physical: `grid.meter.sens_grid_power_active|energy_import|energy_export`, plant `sens_pv_energy`, the single `inv.<id>.sens_inv_power_pv` (mapped to physics `sens_pv_production_active`), `ess.<id>.sens_ess_soc|sens_ess_power|set_ess_active_power|set_ess_charge_power_limit|set_ess_discharge_power_limit|sens_ess_energy_charge|sens_ess_energy_discharge` of the one house battery, and the first (sorted) `*.sens_evcs_active_power`.
   - Everything else is static: reads from a table in the generator (`STATIC_READ_VALUES`), battery `get_ess_*` limits derived from the pack, `set_*` writes start at `0.0`. All of it is listed in `meta.json › static_signals` with value and source. A kind without a table entry aborts; `--static <ehal_id|kind>=<value>` supplies one.
   - S4 serves static values only from `number` entities (their value is seeded from the fixture state), so static **reads are `number` entities**, not sensors. Their ids still come from `contract_entity_id(..., write=True)`; `placeholders.json` is the only valid source for the fill. Alternative for later: a static-sensor path in the S4 coordinator (needs resync).
   - Physical limit setpoints start at the battery maximum from the pack (a `0` start would clamp the battery to idle until Earnie writes); `set_ess_active_power` starts at `0`. Without a `set_ess_active_power` binding the battery runs in `self_consumption` with `ess_max_*_w` from the pack.
3. **Fail loud.** Missing battery capacity (pack or `--battery-kwh`), base load (single profile `annual_kwh / 8760` or `--load-kw`), PV `kwp`, battery power limits where used, unknown static kind, stored `entity_id`s in bindings, slug/placeholder collisions, static unit not matching the field quantity. No other silent defaults; the only generator defaults are `--initial-soc 50`, PV peak = 0.8 × kWp and a 48-point sin² day (recorded in `meta.json`).
4. **Canonical packs only.** Aborts with a pointer to `scripts.migrate_config` when plant `sens_pv_production_active` is bound (retired), when an inverter with attached PV lacks `inv.<id>.sens_inv_power_pv`, or when a grid-tied house battery lacks `ess.<id>.sens_ess_soc` / `sens_ess_power` (F4, F14). Example pack: `ha_lab/config/` (untracked) generates 7 physical signals.

**Limits (P1):** exactly one house battery and at most one inverter PV signal (a second PV source would need a physics key, i.e. a core change); consumer loads are not simulated (base load only); setpoints are numbers only — switch/select setpoints (finding 5) stay undecided and would also need carrier support.

## 3c. P2 notes (S4 external archetype dir, build/fill, 2026-10-21)

- **Core helpers:** `house_sim/core/archetype.py` gained `list_archetypes(fixtures_dir, external_dir)` and `load_archetype_from_roots(...)` (hub-agnostic, synced into the S4 copy). The same name in both roots raises `ValueError`; dot/underscore directories are ignored.
- **S4:** the config flow lists shipped plus `<config>/earnie_house_sim/archetypes/*` (`EXTERNAL_ARCHETYPES_PARTS` in `const.py`) and aborts with `archetype_name_collision` on a clash; `async_setup_entry` loads from either root in the executor. Platforms are unchanged. **Not exercised in a running HA yet** (no HA in the test suite) — first real check is P3/P4.
- **Build:** `python -m scripts.ha_testbed_build --config-dir <cfg> --out <ha-config-dir> --earnie-host <host> --token <t> [--name earnie_pack --earnie-port 8541 --repeat-s … + generator options]`. Writes `packages/earnie_ha_carrier.yaml` (filled from `placeholders.json`, aborts if any `ENTITY_*` survives), `earnie_house_sim/archetypes/<name>/` and `earnie_testbed_configuration.snippet.yaml`. Everything is generated in memory first, so a failure writes nothing. `configuration.yaml` is never modified (P3 patches it). The archetype name must be `[a-z][a-z0-9_]*` and not a shipped name; a real `--token` is required (no placeholder default).
- Tests: `tests/test_ha_testbed_build.py`.

## 3d. P3 notes (compose + install script, 2026-10-21)

- `docker/compose/ha-sim-testbed.yml`: `homeassistant` (same pinned image as `ha-lab.yml`, a test keeps them equal; container `earnie_testbed_ha`, `host.docker.internal` mapped) and `earnie` behind the profile `earnie` (container `earnie-testbed`, publishes 8506 and 8541). No evcc, no HACS. Container names differ from the lab, so both stacks can coexist (HA port 8123 and the Earnie ports still clash if both run).
- Work dir `ha_lab/testbed/{homeassistant,config,runtime}` (gitignored; override with `--testbed-dir`). Typical flow:

```powershell
python -m scripts.ha_testbed_build --config-dir <cfg> --out ha_lab\testbed\homeassistant --earnie-host host.docker.internal --token <t>
python -m scripts.ha_testbed up            # add --with-earnie to run Earnie in Docker (host earnie-testbed)
python -m scripts.ha_testbed install       # integration copy + configuration.yaml + HA restart
python -m scripts.ha_testbed status
```

- `install` copies `house_sim/ha_integration/custom_components/earnie_house_sim` (the synced copy), patches `configuration.yaml` with `homeassistant: packages: !include_dir_named packages` (idempotent; aborts, before copying anything, when `packages:` is set to something else) and restarts the HA container only if it runs. `reset --yes [--all]` stops the stack and clears the HA dir (`--all`: also Earnie config/runtime); it deletes nothing when `compose down` fails.
- **Not implemented:** optional HA onboarding / config entry via REST. After the first start, create the HA owner and add *Earnie House Simulator → generated archetype* once in the UI; the volume keeps it. **Not run here:** `up` against a real Docker daemon (image pull); tests mock the Docker calls and `docker compose config` accepts the file.

## 3e. P4 notes (automated check, 2026-10-21)

`python -m scripts.ha_testbed_check --ha-token <HA long-lived token> [--config-dir <cfg>] [--runtime-dir …] [--repeat-s 10] [--timeout-s 90] [--skip-negative] [--require-all]`. It reads the generated archetype (`placeholders.json`, `entities.json`, `meta.json`) from `<testbed>/homeassistant/earnie_house_sim/archetypes/<name>/`, the Earnie push inbox file from `--runtime-dir` (default `<testbed>/runtime`; it must be the runtime dir of the Earnie that receives the push), and `status.json` from `--earnie-url` (default `http://127.0.0.1:8541`). The HA long-lived token is created once in the HA profile page; onboarding is still manual (P3).

| Check | Pass condition |
| --- | --- |
| pack unchanged (`--config-dir`) | pack hash equals `meta.source_pack_sha256` |
| HA entities | every generated entity exists, is not `unavailable`/`unknown`, unit equals `entities.json` |
| inbox | every activated read and `heartbeat_smarthome` last pushed within 2 × cadence + 2 s |
| round trip | publishes a test value (±500 W / ±1 A) for the first ESS limit / EVCS current setpoint via the shared ledger → `status.json` shows it → the HA `number` reaches it; the original value is published back afterwards |
| `reject_writes` | fresh `hub_write_failed` push in the inbox, number unchanged; after switching off, the value is applied |
| `set_unavailable` | SoC (or first analog read) entity becomes `unavailable` for 30 s, Earnie keeps `status.json` and heartbeat, the signal resumes |
| stopped push | HA push automations of one power and one energy signal are turned off (and back on): power derives `0 angenommen (verstummt)`, energy derives no 0 (`Lesefehler`, no value). Power is SKIP when its last pushed value was 0 |

Exit code 1 on any FAIL; SKIP (no token, no suitable setpoint/signal) fails only with `--require-all`. Optional `tests/test_ha_testbed_live.py` (marker `ha_container`) runs the same with `--require-all` and is skipped unless `HA_TESTBED_TOKEN` is set. `tests/test_ha_testbed_check.py` exercises all branches against a simulated bench. **Not run against a real HA + Earnie yet.** Known limits: the round trip assumes the optimizer is not overwriting the chosen setpoint during the test (silent mode / offline planning as in F5); the `set_unavailable` and stopped-push cases take 1–2 minutes at a 10 s cadence.

## 3a. WP0 findings (2026-10-21, partial run)

Setup used: lab compose, services `earnie` + `homeassistant` only (HA `2025.7.0`, Earnie `2.7.0-alpha.7` built from the working tree), Earnie config pack in `ha_lab/config` (grid + house battery `house` + one hybrid inverter), carrier YAML generated with `scripts.ha_carrier_yaml_gen` and filled with `evcc_en` entities, S4 integration copied after `scripts.sync_house_sim_integration` (no drift).

**Status (2026-10-21, final):** WP0 complete — read, write and fault paths run (see *Fault services*); only switch/select setpoints (finding 5) were not exercised.

**Status (2026-10-21, second run):** read path **verified end to end**, write path **verified end to end with a one-line YAML correction (F13)**; fault services (`reject_writes`, `set_unavailable`, `unit_flip`, `cloud_pass`, `set_soc`) and the *stopped push → assumed 0* case **not run** (need an HA token / UI; I did not create one). Switch/select setpoints (finding 5) **not reached**.

Verified: HA → Earnie push of grid power, PV (per inverter), SoC and ESS power arrives every ~10 s (`interval_ema_s` 9.8–10.0 in `ehal_push_inbox.json`, values 600 W / 900 W / 55 % in canonical units after Jinja conversion); EHAL-Com Live-Lesen shows `PV 0.87 · Haus 1.47 · Batterie 0.0 · Netz 0.6 kW`; with the F13 correction, setpoints in `status.json` (`ess.house.set_ess_active_power = -1500`, charge limit `2500`, discharge limit `3000`) reach the sim `number.*` entities within ~30 s and the SoC starts to rise (55.0 → 55.25 %).

| # | Finding | Kind | Evidence |
| --- | --- | --- | --- |
| F1 | **`ehal.backend=ha` requires `EHAL_HA_BASE_URL` and `EHAL_HA_TOKEN`, though the docs call them optional for the push path.** Without them `main.py` dies at startup in `push_safe_setpoints_on_startup` (`ValueError` from `_resolve_ha_credentials`). | bug / doc mismatch | Traceback when running `python main.py` in the container; docs: `ehal-com.md` §A, `ha-lab-setup.md` §2 |
| F2 | **The crash is invisible:** it is not in `runtime/earnie.log`, and Streamlit's `maybe_auto_start` prints `main.py Auto-Start OK`. Symptom for a user: HA keeps getting *connection refused* on 8541 minutes after a restart. | bug (diagnosability) | `earnie.log` ends after "Startup: sende sichere EHAL-Sollwerte…"; PID in `main.lock` is dead |
| F3 | **`setpoint_qualified_ids` (`integrations/ha_push_read.py:57`) drops entity-scoped setpoints.** It keeps only binding keys starting with `set_`, but battery/inverter bindings are `ess.<id>.set_*` / `inv.<id>.set_*`. Index is `{}` for a canonical pack, so `resolve_setpoint_qid` returns `''` and the HA adapter reports `Missing HA push setpoint binding for set_ess_charge_power_limit` (also `…discharge…`) at startup. If confirmed, **no ESS setpoint is ever published to `status.json` for entity-scoped batteries.** | probable bug (high impact) | In-container check: `setpoint_qualified_ids(house, components) == {}` while `write_signals_from_docs` lists the three `ess.house.set_*` writes; startup log line. Needs a regression test + fix before P4 |
| F4 | **A hand-written pack is not canonical:** Earnie starts in migration mode (`dm4.required_signal_activation`) because PV is required per inverter (`inv.<id>.sens_inv_power_pv`), not as plant `sens_pv_production_active`. Plant-level PV is derived. The generator in P1 must produce the migrated shape (or run the migration). | design note | `migrate_config --dry-run` diff; the carrier then needs `ENTITY_inv_wr_main_sens_inv_power_pv` |
| F5 | **Live scenario incomplete → planning offline** (`profiles: []`). The push inbox works, but optimizer cycles (and therefore real setpoints) need a live scenario with a house profile. The testbed pack needs one, or the check must drive writes via *Schreibtest*. | scope for P1/P4 | `main.py` warning "Live-Szenario unvollständig (Planung offline)" |
| F6 | **Carrier YAML loads on HA `2025.7.0`** (`rest_command`, legacy `sensor: platform: rest`, `automation:` merged with `automations.yaml` through a package). No schema errors. Resolves open decision 4 for the pinned version; re-check on current stable. | ok | HA log, no config errors after restart |
| F7 | Unavailable / missing source entity: Jinja uses `raw_state | float` without default for W/kW/MW branches → `ValueError` in the automation instead of the intended "skipped" log. Missing entity (unit empty) correctly logs "push skipped … incompatible unit". | minor bug | read of `_jinja_to_ehal_vars`; verify with `set_unavailable` |
| F8 | Setpoint automations trigger only on a *change* of the `status.json` attribute. After an HA restart or a manual change of the target entity the last setpoint is not re-applied until Earnie publishes a different value. Sticky backends elsewhere are re-asserted. | design question | `_setpoint_automation` trigger |
| F9 | ~~Start-order noise~~ → the `JSON result was not a dictionary…` warning is F13, not a race. Connection-refused errors right after a restart are real start-order races (compose has `earnie` depending on HA, not vice versa) and are benign once Earnie listens. | minor | HA log |
| F10 | `ha_lab/config/*` and `ha_lab/homeassistant/{custom_components,packages}` are **not gitignored** (only `.env`, `config.json` are) — a lab run leaves ~25 untracked files that are easy to commit by accident. | repo hygiene | `git status` |
| F11 | Container restart works as intended: bootstrap creates the pack, `migrate_config` runs inside the container (`docker exec … python -m scripts.migrate_config --config-dir /app/config`), HA resolves `earnie-ha-lab:8541`. Heartbeat from HA reaches the inbox (`new signal heartbeat_smarthome`). | ok | `earnie.log` |
| F12 | S4 reads fixture files inside the HA event loop (`load_archetype` from `HouseSimCoordinator.__init__`) → HA logs *Detected blocking call to read_text/open … inside the event loop*; works on 2025.7.0, may become an error in future HA versions. Fix: load in an executor job. | minor (sim) | HA log |
| F13 | **Critical: the carrier's `json_attributes_path: $` makes the status sensor attribute-less.** HA's `jsonpath("$")` returns `False` for any dict, so HA logs `JSON result was not a dictionary…` every 10 s and `sensor.earnie_ehal_status` never exposes `status.json` keys. **No setpoint automation can ever fire** (they trigger on those attributes). Correction: drop `json_attributes_path` (attributes are then read from the JSON root). Verified: after removing the line, setpoints flowed to the sim. Also F9 is this warning, not a start-order race. Fix in `integrations/ha_carrier_yaml.py::_status_sensor` + a test that the YAML has no `json_attributes_path: $`. | **bug (blocker for HA writes)** | `jsonpath({"a":1}, "$") == False` inside the HA container; before/after run |
| F14 | **Live-Lesen fails hard when an *optional* ESS power signal is missing:** `Cannot derive plant sens_ess_power: … missing ess.house.sens_ess_power`. The Signalliste lists `ess.house.sens_ess_power` as *optional / nein*, `dm4.required_signal_activation` does not add it, yet a grid-tied house battery requires it (`integrations/plant_balance.py::sum_grid_tied_house_ess_power_w`). Either mark it required (migration + Hauskonfigurator) or derive without it. | bug / inconsistency | UI error text; fixed in the lab by toggling the signal in the Signalliste |
| F15 | Direct edit of `components.json` on the bind mount was reverted by Earnie at container start (file rewritten at 19:21:06, one second after start) — the key I added by hand was dropped, the same key set through the Signalliste persisted. Edit the pack only through the UI/migration, or with Earnie stopped. | note | file mtime vs. start log |
| F16 | **Schreibtest lists no fields for HA push** (`Keine gemappten Schreib-Felder. Bindings auf EHAL-Com setzen.`) although three `ess.house.set_*` keys are activated; the docs say it lists all activated write fields. Same family as F3 (activation keys with empty values are treated as unmapped / filtered by the `set_` prefix). Blocks the manual write check on HA. | bug | UI |
| F17 | The publish ledger (`integrations/ehal_write.py`) is an in-memory dict loaded once per process; a write published from another process (UI, my debug script) appears in `ehal_published.json` but **not** in the daemon's `status.json` until the daemon restarts. Needs a check whether Streamlit-initiated writes (Schreibtest, once F16 is fixed) can reach HA at all. | to verify | `status.json` stayed `0.0` after my publish from a second process; after preloading the file and restarting the daemon it showed the values |
| F18 | Observed F8: after an HA restart the previously published values (2000 W) were **not** re-applied; only a value *change* in `status.json` fires the automation. A restart of HA or of the sim loses the limits until the next change. | confirmed | sim setpoints stayed at the initial 5000 W |
| F19 | Live-Schreiben lists the qualified rows empty and the same fields as bare `set_ess_*` rows with values; `set_ess_mode = 2.0` shows although no mode signal is activated. The write trace is recorded under bare names, the expected rows are qualified. | minor bug | UI after a real cycle |
| F20 | Schreibtest value field has `max = max_power_kw` of the live scenario's battery params; with an incomplete live scenario that is `0`, every value is invalid although the fields are listed as writable. | bug / UX | `input.max == 0` in the DOM |
| F21 | **No plausibility check on pushed values.** With the sim fault `unit_flip` the inverter PV arrived as 900 000 W (kW/W mix-up); Earnie accepted it and derived a house load of 873 600 W. The balance check only rejects too *negative* sums. A bound from the configured kWp / inverter maximum would catch it. | bug (robustness) | `unit_flip` run, 2026-10-21 |
| F22 | **Write failures are invisible to Earnie.** With `reject_writes` the setpoint automation fails (`earnie_house_sim reject_writes active`), Earnie shows `5/5 Schreibvorgänge erfolgreich` and no `ehal_write_error`; the docs promise a write-error degrade like OpenEMS. In HA the failure is only in the HA log, and with the re-assert logic (F8) it is repeated every 10 s with 4 ERROR lines per attempt. Retry self-heals: after `reject_writes` off the value was applied at once. Needs a feedback channel (HA → Earnie, e.g. a small "applied" readback signal) or a doc correction + quieter logging. | design gap | `reject_writes` run |
| F23 | The Live-Lesen **table with push states** (`0 angenommen (verstummt)`, age, `Zuletzt bekannt`) is not shown for the HA backend, only a summary line. After stopping one push the UI showed `Netz 0.0 · Haus 2.35 kW` with no hint that the grid value is assumed. | UX bug | UI during push stop |
| F24 | The "push skipped" log for `unavailable` says `unknown or incompatible unit_of_measurement`; the unit is fine, the state is `unavailable`. | wording | `set_unavailable` run |

**Fix status (2026-10-21, uncommitted):** fixed with tests — F13, F3, F16, F7, F2, F10 (gitignore); lab re-run after rebuild confirms no more `Missing HA push setpoint binding`, Schreibtest lists the 3 ESS fields, startup safe setpoints reach the sim. F14 decided and fixed (required signal for grid-tied house batteries, with migration). F17 and F8/F18 fixed afterwards (ledger shared between processes; setpoint automations re-assert at start/interval with a drift guard) and confirmed with a real optimizer cycle in the lab (ESS limits and 1452 W discharge reached the sim; Live-Leistung showed Batterie 1.45 kW). New: F19 (Live-Schreiben shows qualified rows empty and bare rows with values), F20 (Schreibtest max 0 W without a complete live scenario). F21 (plausibility bound) and F22 (write feedback `hub_write_failed`) fixed and lab-verified. F1 decided and fixed (no HA URL/token in Earnie; push-only). F12, F19, F20, F23 (re-diagnosed: statuses, not a missing table), F24 fixed and lab-verified. No open testbed findings besides the P1–P5 build. Tracked in `backlog/Backlog-Bugfixes.md`. Runbook step 7b (F13 workaround) is obsolete for packages generated after this fix.

**Fault services (2026-10-21, run by the operator in HA, observed in Earnie):**

| Fault | Observed | Verdict |
| --- | --- | --- |
| `set_unavailable` (SoC, 3 min) | HA: "push skipped" every 10 s, no crash (F7 fix works). Earnie: last SoC held, inbox age grows, no error; the 5-minute rule not reached. After the fault the push resumed by itself. | ok (wording F24) |
| `unit_flip` (PV) | PV 900 000 W accepted, derived load 873 600 W, no warning. Reset cleanly after `enabled: false`. | **F21** |
| `reject_writes` + new setpoint | Automation errors in HA, retried every 10 s; Earnie sees nothing. After `enabled: false` the value was applied immediately. | **F22** (retry works) |
| Push stop (grid automation disabled, heartbeat on) | After ~40 s Earnie assumes `0 W` grid, derived load jumps by the missing 874 W; UI shows no marker. | as specified by the zero rule; **F23** |
| `cloud_pass`, `set_soc` | not run (do not test the contract). | – |

Decisions this feeds: **finding 5 (switch/select)** and the **numbers-only contract** remain open (not reached); open decision 4 → resolved for 2025.7.0. Bug fixes needed **before** the testbed is built, in priority order: **F13** (HA writes never worked), **F3/F16** (setpoint index / Schreibtest), **F14**, **F1/F2**; F17 to verify. The testbed itself found all of these in one session — a strong argument for P1–P4.

**Lab side effects to clean up:** HA owner user `wp0` created via the onboarding REST endpoint (throwaway container, `ha_lab/homeassistant/.storage`); dummy `EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN` and `EARNIE_PILOT_PUSH_TOKEN=wp0-lab-token` in `ha_lab/config/.env` (gitignored). Reset: `docker compose … down` and delete `ha_lab/homeassistant/*` and `ha_lab/config/*` (keep `.gitkeep`).

## 4. Runbook

Commands are PowerShell from the repo root `Earnie/`. UTF-8 env for every Python call:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
```

### Part A — works today (manual, vendor archetype `evcc_en`)

Use this for WP0 and as the smoke test after the testbed exists. Pick **A1** (Earnie in Docker, simplest networking) or **A2** (Earnie native on Windows, faster iteration).

**1. Earnie configuration with a signal set the archetype can serve.** For `evcc_en`: plant grid power + PV power + house battery (SoC, `set_ess_active_power`, charge/discharge limits). Activate them in the Hauskonfigurator / Signalliste (required = ja, aktiviert = ja). The archetype also serves grid/PV energy, ESS power, EVCS power, `set_evcs_max_current`.

**2a. A1 — everything in Docker (lab compose, without evcc).**

```powershell
mkdir ha_lab\config, ha_lab\runtime, ha_lab\homeassistant -Force
docker compose --project-directory . -f docker/compose/ha-lab.yml up -d --build earnie homeassistant
docker compose --project-directory . -f docker/compose/ha-lab.yml ps
```

`depends_on` also runs the one-shot `hacs-init` (needs internet); `evcc` is not started. Earnie UI: http://localhost:8506, HA: http://localhost:8123. HA reaches Earnie as `earnie-ha-lab:8541`.

**2b. A2 — Earnie native, HA in Docker.** Start only HA (same command, service `homeassistant`). Start Earnie in two terminals: `python -m scripts.run_streamlit` and the daemon/`main.py` as usual for your dev setup (the daemon listens on 8541 — allow it in the Windows firewall for the Docker network). HA reaches Earnie as `host.docker.internal:8541`.

**3. Earnie backend + push token.** In Streamlit → Smarthome-Backend choose Home Assistant. Put `EARNIE_PILOT_PUSH_TOKEN=<token>` in the Earnie `config/.env` (A1: `ha_lab/config/.env`). `EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN` are documented as optional for the push path but are **required today** (finding F1) — put `EHAL_HA_BASE_URL=http://homeassistant:8123` and any dummy token in `.env`. After editing the pack, run `docker exec earnie-ha-lab python -m scripts.migrate_config --config-dir /app/config` (F4), then restart the container; check `runtime/earnie.log` for the line `EHAL request HTTP listening on 0.0.0.0:8541` **and** that the log continues past "Startup: sende sichere EHAL-Sollwerte" (F2).

**4. HA onboarding.** http://localhost:8123 → create the owner account, set location/timezone `Europe/Vienna`. No token is needed for the push path.

**5. Install the simulator integration.**

```powershell
.venv\Scripts\python.exe -m scripts.sync_house_sim_integration
Copy-Item -Recurse -Force house_sim\ha_integration\custom_components\earnie_house_sim ha_lab\homeassistant\custom_components\earnie_house_sim
docker restart earnie_homeassistant
```

HA → Settings → Devices & services → Add integration → **Earnie House Simulator** → archetype `evcc_en`, PV source *synthetic*, interval 5–10 s. Check Developer tools → States for `sensor.evcc_*`, `number.ess_*`.

**6. Generate the carrier YAML.** EHAL-Com → *HA Push-Carrier → YAML-Paket*, or:

```powershell
# A1 (HA inside the compose network)
.venv\Scripts\python.exe -m scripts.ha_carrier_yaml_gen --config-dir ha_lab\config --host earnie-ha-lab --port 8541 --token <token> --out ha_lab\homeassistant\packages\earnie_ha_carrier.yaml
# A2 (Earnie native): use --host host.docker.internal and your Earnie config dir
```

**7. Fill the `ENTITY_*` placeholders by hand** (this is the step real users do). Mapping for `evcc_en` — placeholder name = qualified EHAL id with non-alphanumerics → `_`:

| Placeholder | Entity |
| --- | --- |
| `ENTITY_grid_meter_sens_grid_power_active` (or flat `ENTITY_sens_grid_power_active`) | `sensor.evcc_grid_power` |
| `ENTITY_sens_pv_production_active` | `sensor.evcc_pv_power` |
| `ENTITY_ess_house_sens_ess_soc` | `sensor.evcc_battery_soc` |
| `ENTITY_ess_house_set_ess_active_power` | `number.ess_active_power_w` |
| `ENTITY_ess_house_set_ess_charge_power_limit` | `number.ess_charge_limit_w` |
| `ENTITY_ess_house_set_ess_discharge_power_limit` | `number.ess_discharge_limit_w` |
| `ENTITY_ess_house_set_evcs_max_current` / EV max current | `number.evcc_loadpoint_1_max_current` |

The exact placeholder names depend on your pack; open the YAML and search `ENTITY_`. Source of truth for the sim entities: `house_sim/fixtures/evcc_en/ehal.ha.entities.json` (note `input_number.*` → `number.*` in HA).

**7b. Work around F13 (until fixed in the generator):** delete the line `json_attributes_path: $` in the `sensor:` block of the YAML. Without this HA never exposes `status.json` and no setpoint is applied.

**8. Load the package.** HA `configuration.yaml` (in `ha_lab/homeassistant/`) must contain:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then Developer tools → YAML → *Check configuration*, and restart HA. Errors show up in Settings → System → Logs.

**9. Verify.**
- HA: `sensor.earnie_ehal_status` exists, state = heartbeat; automations `Earnie push …` show recent *last triggered*.
- Earnie EHAL-Com → **Live-Lesen**: required rows OK, age ≈ push interval (10 s); Signalliste *Match* shows receive age.
- Host check: `Invoke-RestMethod "http://localhost:8541/ehal/status.json?t=<token>"` (A1: publish 8541 on the earnie service or run it from inside the network).
- Write path: Optimierer-Dienst → Silent-Modus **off**; EHAL-Com → Live-Schreiben → *Schreibtest* → send an ESS charge limit → `number.ess_charge_limit_w` changes in HA within ~10–20 s (status sensor `scan_interval`); success column shows `published_fetched_at`.
- Fault tests (Developer tools → Actions): `earnie_house_sim.reject_writes`, `set_unavailable`, `unit_flip`, `set_soc`, `cloud_pass`; observe EHAL-Com status strings and `runtime/ehal_write_error.json`.

**10. Stop / reset.**

```powershell
docker compose --project-directory . -f docker/compose/ha-lab.yml down
# factory reset HA: delete contents of ha_lab\homeassistant (keep the folder)
```

### Part B — testbed flow (P1–P4)

```powershell
# 1. Earnie running with the configuration under test (activated signals, push token set)
# 2. Build bench inputs from that configuration
.venv\Scripts\python.exe -m scripts.ha_testbed_build --config-dir <earnie-config-dir> --out ha_lab\testbed\homeassistant --earnie-host host.docker.internal --token <token>
# 3. Start / install / reset the HA container
.venv\Scripts\python.exe -m scripts.ha_testbed up
.venv\Scripts\python.exe -m scripts.ha_testbed install
# 4. Automated verification
.venv\Scripts\python.exe -m scripts.ha_testbed_check --config-dir <earnie-config-dir> --ha-token <HA long-lived token>
```

Onboarding is manual (the optional REST automation is not built): after the first `up`, create the HA owner at http://localhost:8123, set location/timezone `Europe/Vienna`, and create a **long-lived token** (profile page) for the check. After `install`, add *Settings → Devices & services → Add integration → Earnie House Simulator → archetype `earnie_pack`* once; the volume persists it. Earnie itself either runs natively (`--earnie-host host.docker.internal`; allow 8541 in the Windows firewall; use `--runtime-dir` pointing at its runtime dir) or in the bench (`up --with-earnie`, pack in `ha_lab/testbed/config`, `EARNIE_PILOT_PUSH_TOKEN` in `ha_lab/testbed/config/.env`, build with `--earnie-host earnie-testbed`). Details per command: § 3b–3e. `python -m scripts.ha_testbed status` shows what is in place; `reset --yes` is the factory reset. **Once per release**, additionally run Part A step 7 by hand with an unfilled YAML to keep the user-facing mapping step honest.

### Customer-problem reproduction (WP8)

What the bench can and cannot reproduce is the table in § 2: it reproduces the customer's **activated signal set** and the Earnie/carrier/contract behaviour, not their devices.

1. **Get the pack.** `house_profiles.json` + `components.json` carry activation flags only (no entity ids, no tokens) — still open them before accepting. Also ask for the Earnie version and, if possible, `runtime/ehal_push_inbox.json`, `runtime/ehal_published.json` and the output of `GET /ehal/status.json`.
2. **Make it canonical.** Copy the files into a scratch dir and run `python -m scripts.migrate_config --config-dir <scratch>` if the pack is older (the generator aborts with a pointer when it is not canonical). Fill gaps the generator names (`--battery-kwh`, `--load-kw`, `--static <id>=<value>`); note them, they are test inputs, not facts about the customer.
3. **Build and run** (Part B): `ha_testbed_build` → `ha_testbed up` → `install` → HA onboarding/token/integration once → `ha_testbed_check`.
4. **Read the result.**
   - `ha_testbed_check` **fails**: the problem is in Earnie, the generator or the carrier YAML for that signal set → minimise to a test pack, fix, add a regression test (as the WP0 findings F3, F13, F14 were found).
   - It **passes**: the cause is probably device-, unit- or sign-specific → ask the questions below and add a matching vendor archetype (`house_sim/fixtures/`).
5. **Never share** the filled `packages/earnie_ha_carrier.yaml` unredacted: it contains the push token (replace it before attaching to a ticket).

**What to ask the customer** (template):

- Home Assistant version and install type (Container/OS/Supervised), Earnie version, `ehal.backend`.
- For every bound signal: the entity they mapped to `ENTITY_<id>`, its `unit_of_measurement`, its device class and sign convention (grid + = import? battery + = discharge?).
- Their filled carrier YAML with the token removed, and HA's `home-assistant.log` lines containing `earnie_ha_carrier` or `rest_command`.
- Which setpoints they expect HA to apply (entity domain: `number` is supported, `switch` / `select` are not — finding 5) and how the target is controlled (integration/service).
- What Earnie's EHAL-Com *Live-Lesen* / *Live-Schreiben* show (status strings, age column) and the time of the problem.
