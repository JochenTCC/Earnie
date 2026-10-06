# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **HA-Loxone-Bridge-Builder:** standalone tool (no Earnie/EHAL runtime dependency) to auto-generate HA `rest_command:`/`automation:` YAML for numeric HA→Loxone writes. Design draft: [backlog/HA-Loxone-Bridge-Builder-Draft.md](HA-Loxone-Bridge-Builder-Draft.md). **Not part of Version 2.6.** A different audience (any HA+Loxone install). Do not share code with **2.6.b** / **2.6.e** (those map HA entities onto a fixed EHAL vocabulary inside Earnie). Deferred Loxone Virtual-In/Out XML in the draft is also not the Version 2.+1 “Earnie → Loxone template XML” item.
- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog

### Version 2.7 — Multiple storages and export power limitation

**Order:** **2.7.i** (release regression suite) is independent and can start any time — ideally **P1** lands before the 2.7 release so it guards the multi-storage changes. Official **2.6.0** is on `main`; finish remaining letters here, then merge. Do not bump `version.py` to a publishable 2.7 without approval. Shadow client (**2.7.f**) is done — dogfood the rest of 2.7 against Prod with **2.6.o** feed. **2.7.a** (code + Loxone wiring + live dogfood), **2.7.b** (Thermals P2), **2.7.c** (multi-ESS), **2.7.j** (additional ESS parameters), former **2.7.d** (one-way storage type, folded into **2.7.g**/**2.7.h**), **2.7.g** (single-use powerstation reserve), **2.7.h** (standby-backup; code done, productive verification pending — see [Bugfixes](Backlog-Bugfixes.md) Verifications Pending), and **2.7.k** (ENTSO-E live prices) → [Erledigt](Backlog-Erledigt.md).

- **Note:** Savings study done (2026-10-05, private `Earnie-env-home/studies/powerstation-savings-2025.md`, home plant, 2025). Cash bill: virtual reserves/floors are flat or more expensive (about 2–21 €/year). Physical packs save about 4–18 €/year (150 W on 1024 Wh: 18 €; late Trockner starts about 21 €). Bill savings alone do not carry **2.7.h**; a virtual floor is not worth more than the 15 kWh battery alone. Outage value is not priced. **2.7.g** shipped for UX; **2.7.h** implemented (physical only; virtual floor declined) — productive Earnie dogfood still open.

- [ ] **2.7.m — Per-battery EHAL mapping (EHAL-Com)** (runs **before 2.7.l**; unblocks the full **2.7.h** dogfood; prerequisite structure for **Inverter P4**)
  - **Gap (code reading, 2026-10-06):** EHAL-Com mapping (`build_entity_rows` / `apply_entity_bindings` in `ui/ehal_loxone_mapping.py`, used by `ui/ehal_ha_mapping.py`) knows only plant + consumers. The single house battery is mapped via flat ESS fields on **plant**; further batteries and physical powerstations cannot be mapped (no editor for `batteries[].ehal_bindings`). `aggregate_ha_entities` (`house_config/ha_ehal_bindings.py`) takes plant-flat fields only, so `ess.{slug}.*` never reaches `HaAdapter`. `migrate_plant_ess_to_components` (`runtime_store/migrate_v4.py`) already moves flat ESS onto `batteries[].ehal_bindings` — the UI/live path never followed.
  - **Goal:** every battery (house + physical powerstation) is its own mapping entity with Pattern B `ess.{slug}.*`; the plant row keeps grid/PV/consumption only. Independent of the inverter topology (slug = battery id); **Inverter P4** later adds inverter rows under the owning battery.
  - [ ] **2.7.m-1 — Entity rows + persistence:** `build_entity_rows` adds `kind: battery` rows (fields = ESS role fields as `ess.{slug}.*`, bindings from `batteries[].ehal_bindings`); `apply_entity_bindings` writes to `components.json` (`components_store`), not `house_profiles.json`; ESS fields leave the plant row (HA + Loxone UI); Shadow overlay (`upsert_entity_bindings`) learns battery entities.
  - [ ] **2.7.m-2 — Live path:** `aggregate_ha_entities` (and the Loxone equivalent) include `ess.{slug}.*` so adapters read/write per battery; flat aliases for the primary battery stay for legacy callers; powerstation resolution uses own bindings only (see Bugfix "Physical powerstation ESS writes fall back to the house battery's plant-flat entity").
  - [ ] **2.7.m-3 — Dependents:** required-field check (`sens_ess_soc`) and `render_function_status` / control-capability warnings evaluate battery bindings; per-battery sign (`sens_ess_power` sign is plant-wide today; default inherit, optional override); capability `supports_ess_source_select` derived per battery; `setup_readiness` consistent.
  - [ ] **2.7.m-4 — Config migration:** one-off script `scripts/migrate_ess_bindings_once.py` (`--config-dir`, `--dry-run`; deleted after use) moves plant-flat `sens_ess_*` / `set_ess_*` / `get_ess_*` onto the single house battery (reuse `migrate_plant_ess_to_components`; ambiguous with >1 battery ⇒ abort with hint). May be merged with the **2.7.l** one-off script if both land together. Stay on `earnie_data_model` **4**; fail-fast with a hint when flat ESS bindings are found after the switch.
  - Docs: `docs/ui/ehal-com.md` (mapping sections, §C.2 note on per-battery bindings), `docs/konfiguration/batterie-pv.md` (German), `docs/spec/ehal.md` implementation notes. Tests: mapping rows/persistence, aggregate with two batteries, apply to components, migration script.
  - **Open decisions:** (1) house battery loses its ESS fields on the plant row (recommended; avoids double maintenance) or stays as an alias there; (2) Loxone: per-battery Merker names (`Earnie_Speicher_…`) vs shared plant Merker for the EcoFlow bridge.

- [ ] **2.7.l — Inverter entity (PV × battery topology)** (epic **Inverter**; EHAL/EHAL-Com doc draft: [`backlog/EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md))
  - **Problem:** `pv_systems[]` and `batteries[]` are unrelated lists; the scenario picks both by id. Nothing says which PV strings and batteries share an inverter. The MILP has one summed PV node, so inverter AC/DC limits (clipping), hybrid vs. AC-coupled batteries and several inverters with their own battery cannot be modelled. Balkonkraftwerk storage (EcoFlow etc.) has the inverter built into the battery and takes PV directly.
  - **Model:** new `inverters[]` in `components.json`. PV systems and batteries reference it via `inverter_id` (n:1, reference on the child). The scenario keeps `pv_system_ids[]` / `battery_ids[]`; the inverters in play follow from them (no `inverter_ids[]`).
    - `type`: `hybrid` (PV + battery on the DC side, limit applies to the sum) | `pv_string` (PV only) | `battery` (battery only / AC-coupled)
    - `max_ac_power_kw` (clipping + discharge; absent = no cap), `max_pv_input_kw` (DC/MPPT cap, optional), `max_ac_charge_kw` (grid charging through the inverter, optional), `efficiency` (later), `control` (`full` | `limits_only` | `read_only`)
    - `ac_connection`: `grid_tied` (AC side on the house bus) | `island` (AC side feeds only attached loads; PV of that inverter does not count in the house balance). Replaces `batteries[].kind` (`isolated` ⇒ island, "never Automatik" derives from it, `optimizer/battery.py`); `kind` and the "Topologie" field are removed.
    - **Built-in inverter** (EcoFlow, Balkonkraftwerk storage, physical powerstation): the inverter stays a normal entity, with `owned_by: <battery_id>`. UI/lifecycle only — created, shown (section "Integrierter Wechselrichter" in the battery form) and deleted together with the battery; PV systems pick it in their inverter select like any other. Optimizer and EHAL see no special case. Device presets (e.g. "EcoFlow Delta 3") create battery + inverter + bindings in one step.
    - Virtual powerstations (carve-out of the house battery) have no inverter. Physical powerstations get an owned `island` inverter.
    - EHAL: new role `inverter`, Pattern B `inverter.{slug}.*` on `inverters[].ehal_bindings`; role is optional. `sens_pv_production_active` stays the required global field (sum). Details: draft file above.
  - **Data model:** stay on `earnie_data_model` **4** (nowhere in production except the dev install). Detection by version number is impossible, so detect structurally (`batteries[]`/`pv_systems[]` present and `inverters` key missing, or any `batteries[].kind`) and **fail fast** with a hint to run the one-off script. No permanent compat shim in the loader. **One-off script** `scripts/migrate_inverters_once.py` (`--config-dir`, `--dry-run`; deleted after use) per config dir (`earnie_env*/config`, `greenfield/config`, `share/config` examples, `tests/fixtures/backtesting/`): create one `hybrid` inverter `wr_main` without `max_ac_power_kw` (no clipping ⇒ behaviour unchanged), attach all PV systems and all `kind: battery_inverter` house batteries; `kind: isolated` ⇒ own `island` inverter; drop `kind`; migrate `ess.*` bindings untouched. After migration the regression suite (**2.7.i**) must be green without re-recording. Debug dumps under `debug-dumps/` are pinned to the old build — migrate only the ones still used for replay. After editing `house_sim/core/` or fixtures: `python -m scripts.sync_house_sim_integration`.
  - [ ] **Inverter P1 — schema + resolution:** `components.schema.json`, `inverter_id` on PV/battery, `entity_resolution` (`_planning_inverters`, validation: unknown id, `owned_by` consistency, battery without inverter, hybrid with island PV), one-off migration script, fail-fast check, tests.
  - [ ] **Inverter P2 — UI + docs:** inverter editor in the house configurator, inverter select in PV and battery forms, built-in inverter section + presets, remove "Topologie"; German docs (`batterie-pv.md` replaces § Topologie).
  - [ ] **Inverter P3 — MILP:** per-inverter PV node (forecast per PV system passed through), AC clipping `pv_w + p_discharge_w ≤ max_ac_w`, DC cap, grid charge only where `max_ac_charge_kw`/hybrid allows, island inverters outside the house balance. First step is clipping + battery assignment (in scope of 2.7.l); efficiency paths are a separate follow-up. Golden-master cases with a clipping inverter added (**2.7.i**).
  - [ ] **Inverter P4 — EHAL:** role `inverter` (`share/ehal/roles/inverter.json`), fields `sens_inv_power_ac`, `sens_inv_power_pv`, `get_inv_max_ac_power`, `get_inv_max_pv_power`, `set_inv_ac_power_limit`, `supports_inv_power_limit`; schemas, `ehal/` loader, HA/Loxone/OpenEMS mapping, EHAL-Com Live/mapping rows; export-limit "unconstrained" formula per inverter; update `docs/spec/ehal.md` + `docs/ui/ehal-com.md` from the draft.
  - [ ] **Inverter P5 — follow-ups (separate items once P1–P4 land):** DC/AC efficiency paths, curtailment via `set_inv_ac_power_limit`, multi-inverter live attribution of `sens_pv_production_active`.
  - **Deferred (not part of 2.7.l):** device catalog for inverters and batteries (commercially available models with rated powers, capacity, efficiency, limits) so parameters need not be typed by hand. The P2 presets (e.g. "EcoFlow Delta 3") are only hand-written seeds; the catalog would replace them later. Own backlog item when it is picked up.
  - **Decided:** wire `schema_version` stays **4** (2.7 unreleased, new fields optional); AC/DC clipping is part of **Inverter P3** (not deferred); epic `Inverter` added to `roadmap-nomenclature.mdc`.

- [ ] **2.7.i — Release regression suite (golden-master cases, public + private data)** (epic **Regression**; independent of **2.7.a–h**; spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md))
  - Goal: Earnie's behaviour must not change unnoticed between releases. Frozen inputs (config, consumption, prices, PV forecast, start state) → offline deterministic run → compact metrics → compare against committed golden. Runs **before a release / publish**, never per commit (pytest marker `regression`, deselected by default).
  - Data split: runner + synthetic/own cases in the public repo (`tests/regression/cases/`); customer cases in a **private repo** `Earnie-regression-private` (never in the public repo or its history). Public issues reference a case only by ID (`REG-<issue>-<slug>`); report records the SHA of the private repo.
  - Compare in three tiers: hard invariants (fail) → metrics with tolerance, default ±0.5 % (fail) → plan diff (info only). Intended changes re-record the golden via `--update-golden` with justification in the commit.
  - Levels: **L1** cycle replay, **L2** backtest window (simulated state carried through), **L3** live replay (recorded production cycles, each from measured state; spec §15). Order: **R-Rec → R0 → P1 → L3 → P2 → P3.**
  - [ ] **Regression R-Rec — cycle recorder (first):** always-on production recorder, ring buffer `runtime/recorder/cycles_YYYY-MM-DD.jsonl.gz`, `recorder_retention_days` default 7, on by default; captures `optimization_matrix` + `planning_window` directly before `prepare_optimization_matrix` in `main.py`, start state, config hash, written setpoints, plan hash, override/outage flags; failures never affect the production run. Acceptance: record → replay == live. **Debug dumps automatically include the matching recorder window** (decided; manifest records window + config hashes, older dumps stay valid, dump dialog privacy text updated), so every user report is a potential golden case. Privacy note in `docs/einrichtung/betrieb.md` (spec §14).
  - [ ] **Regression R0 — solver determinism / tolerance study (after R-Rec):** production default is **HiGHS**, and `solve_with_strict_fallback` is wall-clock dependent (strict 3 s → fallback `gapRel` 10 %), so the plan depends on CPU speed/load. Measure stage reached, spread of cost/plan hash across solver × mode × load × perturbation (20 reps per case) on full 96-slot recorder cases; decide regression solver mode (deterministic, no wall-clock limit) and derive per-metric tolerances from the measured spread (spec §16).
  - [ ] **Regression P1 — MVP:** case format + schema, runner for L1 (cycle replay) and L2 (backtest window), `--update-golden`, markdown report; 4–6 public cases (winter, summer, negative prices, EV deadline, heat storage); migrate the existing `tests/fixtures/prod_dumps/` cases; tolerances and solver mode from R0; release-checklist item. Pre-check: existing public fixtures contain no entity names / location / third-party data.
  - [ ] **Regression L3 — live replay:** replay runner for recorder windows (replay vs. recorded, replay vs. golden replay), case creation from a selected time window, exclusion/reporting of cycles flagged as override/outage/manual (spec §15).
  - [ ] **Regression P2 — customer data:** private repo + private-root support (skip when missing), `--intake` (debug-dump ZIP → case folder + ID), case-ID / issue-reference convention, SHAs in the report.
  - [ ] **Regression P3 — gate + scrub:** CI job `regression` before `promote` in `release-publish.yml` (deploy-key secret), whitelist-based scrubber for customer → public repro cases (names/IDs, location, GDPR consent note), optional metric trend across releases.
  - **Open decisions:** soft vs. hard gate (proposal: soft first); customer-facing data-handling wording beyond the private repo; solver (HiGHS `highspy` version, CBC if used) identical on dev machine / Docker / CI; regression solver mode (deterministic vs. production path).

### Version 2.+1 (maybe also part of 2.7?)

- [ ] **Monitor charts — pan-to-load spike** (feasibility + usability → go/no-go; independent of **2.7.a–c** / **2.7.g–h**)
  - **Today:** display range depends on device (`ui/s2_viewport.py`: phone = 24 h segments, desktop/tablet = SA₀→SA₂). Charts get only the data of that default range. Panning with the Plotly drag/pan tool beyond it shows an empty chart. Navigation is via buttons / date picker (`ui/history_navigation.py`, `ui/s2_navigation.py`).
  - **Option A — pan-driven lazy loading:** panning replaces the nav buttons. Data for newly visible ranges is fetched step by step and appended to the charts.
  - **Option B — coupling:** keep the buttons, but sync them with the pan position (pan past the edge → switch segment/cycle; button → move the Plotly x-range). Optionally preload neighbouring segments (±1) so short pans never show empty areas.
  - **Feasibility to check:** Streamlit `st.plotly_chart` does not return `relayout` (x-range) events — only selections. Needs a custom component, `streamlit-plotly-events`-style bridge or a debounced rerun trigger. Check rerun cost/latency per pan, keeping all S-2 charts (flow, SoC, cumulative, consumer stack) on the same x-axis, zone/SA marker decorations outside the default range, and memory/load time on the Pi/Synology.
  - **Usability to check:** touch pan vs page scroll on phones, discoverability vs explicit buttons, behaviour at log start / live edge ("Heute"), loading indicator while data is fetched.
  - **Outcome:** short spike on a branch (prototype for one chart, then all), test on desktop + phone, then decide: A, B, preload-only, or keep status quo. Record decision here before any productive implementation.
  
  - [ ] Enable multiple EV / Wallboxes *(reuse Pattern B namespacing approach from **2.7.c** multi-ESS)*
  - Parametrize EVs as now (+ sensors)
  - Parametrize Wallboxes 
    - Max power
    - sensor / control commands
  - Assignment is done when EV is connected to a wallbox:
    - both devices report connection
    - confirm assignment by test charging
    - Assignment is removed when disconnecting
    - Cancel assignments and re-bind in case of shutdown


### Version 2.+1 — Introducing nested data models / Epics **Adaptation** & **Thermals** (architecture first)

- [ ] Optimize Pool temperature to a certain value on time. Set desired temperature and using time. Combine it with RC model
  - Chart: comparison actual vs modeled — **reuse** the virtual heat-content / weekly Ist-vs-Modell chart from **2.7.b** (pool branch of §3.5); include ambient and heating activity
- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Move Loxone markers to data model - remove flat definition in config.json where possible
  - **Note:** Thin marker↔role prep and UI editability are in **2.3.f**; EHAL core / DACH adapters / Loxone-EHAL extraction in **2.4** (`2.4.e`). This chapter owns nesting / structure, not the EHAL interface rewrite.
  - **Pool nesting:** Merge today’s separate consumers **Pool-Filter** into **Pool-Heizung** (drop the bridge/synthetic `swimspa_filter` / `pool_filter` sibling). Introduce a combined **pool** model: outer entity = one house-profile consumer; inner parts = RC thermal (Heizung) + generic flex (Filter hours / Freigabe / native window). EHAL bindings and MILP stay role-scoped to the inners; UI/planning show one Pool.
- [ ] **Recommendation mode smart/adaptive devices** (follow-up to recommendation mode manual devices)
  - Adaptive re runtime/energy per run; smart devices instead of manual input
  - Adaptation algo maintains `appliance_recommendation.default_power_kw` from Loxone power markers (`loxone_inputs.power_name`) on house-profile generics — reserved so far, no live use
  - Use Loxone power markers also for Sankey-Diagram for further differentation of defined consumers
- [ ] **Adaptation P3** — Adaptation algorithm (PV pilot)
  - Common structure for parameter adaptation of various forecast models:
    - Reference value (target for adaptation)
    - Variable parameters (with bounds)
    - Time horizon (e.g. 24 h for PV/freezer, 1 year for swim spa/house)
    - Start parameters from `config.json`; adaptation history **separate**; correct live parameters only when needed (rhythm oriented to horizon)

- [ ] **Thermals P3** — Thermal parameter adaptation (on Adaptation P1; after **Thermals P2** / **2.7.b**)
  - Prerequisite: virtual heat-content sensor + Ist/Modell chart (**2.7.b** / Entwicklungsplan §3.5)
  - Reference: `Q_meas` (or `T_meas`); variables: `heat_loss_kw_per_k` and further linear model parameters (optional effective C); horizon per consumer (24 h / 1 year)
- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)
- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2** / **2.7.b**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)


### Version 2.+1 - Improvements for HA (HouseSim)

**Naming:** simulator stages are **HouseSim S1–S4** (formerly "HA Lab P1–P4"). **HA Lab** now means only the `ha_lab/` Compose stack (Earnie + HAOS + evcc, [ha-lab-setup.md](../docs/spec/ha-lab-setup.md)).

- [ ] **PV forecast from HA (alternative source)** — Add possibility to take PV prognosis directly from HA when available, as an alternative to Earnie's own `data/pv_forecast.py` (forecast.solar). Config toggle per scenario/plant (own vs. HA entity), entity mapped via `ehal_bindings` like other HA sensors.
  - **Open question — scope:** likely fits the **48h online optimization** (live HA connection, fresh entity value each cycle) but unclear for the **Szenarien-Explorer** (SE runs fixed/reproducible input series; a live HA forecast entity breaks reproducibility unless a snapshot/recording mechanism is added) — clarify before implementation whether SE stays forecast.solar-only or gets a recorded-snapshot path.
  - Checked 2026-09-29: no other note of this idea in `backlog/Backlog-Bugfixes.md`, `backlog/Backlog-Erledigt.md`, `docs/spec/`, `.cursor/plans/`, or the external Entwicklungsdokumente (`Entwicklungs-Plan-Earnie-cons.md`, HA add-on/compat docs) — this stub is the only prior record.
- [ ] **HouseSim S3** — CI harness: short simulated windows, not N live `main.py` days. Load each archetype → golden map → `HaAdapter` → check criteria of concept doc §3.5 (setpoint effect on next read, degrade on write errors, SoC/PV/temperature in a plausible band) for **all** archetypes; the static 2.6.a fixture stays the fast job. Diagnose-JSON → fixture converter only when support needs it.
- [ ] **HouseSim wallbox write-back** — Wallbox setpoints act on the simulated physics instead of only the scenario override: `set_evcs_max_current` / mode writes (go-e / Wattpilot `amp` + `frc`, evcc `max_current` + enable) → charge power = current × voltage × phases while an EV is connected (`car_arrives` / `car_leaves`), capped by the EV's acceptance. Mock REST (S1–S3) and S4 integration; tests on `evcc_en`, `fronius_de`, `huawei_en` (`sma_keba` stays the read-only wallbox case). Prerequisite for **HouseSim scenario import**.
- [ ] **HouseSim scenario import** (idea, after wallbox write-back; prefers **2.7.c** multi-ESS + **2.7.g**/**2.7.h** powerstation model) — S4 config flow reads a finished Earnie scenario (`house_config` with consumers, PV, batteries) and builds the simulated house from it: one device per configured component with a matching archetype, physics parameters from the scenario instead of manual `house_params`. Consumers beyond battery + PV need their physics in the core first (wallbox: item above; heat pump: open). Concept doc §5 S4 „optional später“.


### Version 2.+1 - Enhance Loxone Auto Binding functionality

- [ ] When importing from existing Loxone config is working the other way round would also be possible:
    - User has a complete HK with live scenario in place in Earnie
    - Earnie generates pre-filled Loxone Template XML files (with correct ids, (multiple) evs, (multiple) consumers, **(multiple) batteries after 2.7.c**) for importing into Loxone config.


### Version 2.+1 - POC for EEG-ready Earnie

Main Goal of this version is to get a proof-of-concept for an evolved Earnie that is able to optimize EEGs (Energie-Erzeuger-Gemeinschaft)
- See Entwicklungsplan\eeg-earnie-recherche-zusammenfassung.md for current research
- [ ] Implement a POC for EEG simulation *(benefits from **2.7.a** export-limit model and **2.7.c** multi-ESS)*


### Version 2.+1 — Add-on Version 1.0 (Earnie northbound state)

Deferred from the **2.6** HA-coupling cycle. Prefer after southbound mapping UX is usable (**2.6.h**). Not the separate item “EHAL adaptation for MQTT” below.

- [ ] **Add-on Version 1.0.** From the [add-on plan](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie_HomeAssistant_Addon_Dokumentation.md): MQTT Discovery, native Home Assistant entities for Earnie state, HA Energy-dashboard integration, Supervisor health check. Earnie publishing its own state. Checked on the existing Synology HAOS. Stable vs pre-release install is the [add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md), not this item.


### Version 2.+1

- [ ] In case of big diff between PV prognosis and actual PV energy Earnie should use a correction factor for optimization at least for the next QH in order to prevent unneeded forced charging or other actions (has to be specified more concrete how)
- [ ] Check possibility for automatically learn consumer schedules (for known consumers) and nominal power (for all consumers) from sens_power_act to substitute or improve manual settings
- [ ] **Banner der Wahrheit — Layer C enforcement** *(after soft first approach `2.4.q`; follow-up from `2.4.i` spike)*
  - Cosign/Sigstore in release CI + startup verifier + production signing keys
  - Watermark vs refuse-to-start decision; offline public-key path
  - Spec: `[docs/spec/hardware-registry-layer-c.md](../docs/spec/hardware-registry-layer-c.md)`
- [ ] Make also an EHAL adaption for MQTT
- [ ] **Shadow Mode S4** *(after **2.7.f**)* — Prod-vs-Shadow decision diff per slot; offline replay of `feed-*.jsonl` as backtest input. Spec [`docs/spec/shadow-mode.md`](../docs/spec/shadow-mode.md) §11 S4
- [ ] **Data & tariff fidelity - Part 2**
  - Keep official EPEX unconnected unless a paid/internal use case appears
  - Check possibilities to automatic tariffs.json update to existing installations
- [ ] Check possibilities to show decimal numbers according to regional settings (e.g. use "," as decimal sign for Germany)
- [ ] Simulate restrictions for energy export dependent on current grid situation in SE (and maybe Live) — **after 2.7.a** (consumes Live/MILP/EHAL export-cap model; do not redefine caps here)


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)

## Findings from former Research

- [x] **Live price prognosis — Energy-Charts `public_power_forecast` trial (archived):** full implementation including async `runtime/cache` warmup lives on branch `archive/energy-charts-forecast-research` only — not for merge to `main`. Product power features remain archive hour-of-day.