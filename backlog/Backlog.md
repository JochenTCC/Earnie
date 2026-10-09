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

**Order:** **2.7.n** sessions **B → C**; **D** parallel with B/C; then **E → F**; then **2.7.l**. **2.7.i** is independent and can start any time — ideally **P1** lands before the 2.7 release so it guards the multi-storage changes. Official **2.6.0** is on `main`; finish the remaining 2.7 letters on `main`. Do not bump `version.py` to a publishable 2.7 without approval. Shadow client (**2.7.f**) is done — dogfood the rest of 2.7 against Prod with **2.6.o** feed. **2.7.a** (code + Loxone wiring + live dogfood), **2.7.b** (Thermals P2), **2.7.c** (multi-ESS), **2.7.j** (additional ESS parameters), former **2.7.d** (one-way storage type, folded into **2.7.g**/**2.7.h**), **2.7.g** (single-use powerstation reserve), **2.7.h** (standby-backup; code done, productive verification pending — see [Bugfixes](Backlog-Bugfixes.md) Verifications Pending), **2.7.k** (ENTSO-E live prices), **2.7.p** (virtual PS consumer-start release), and **2.7.q** (push-only write + Signal list; Q6 meter-energy **Verified live**) → [Erledigt](Backlog-Erledigt.md). Done under **2.7.n** and archived: **Session A** (retire Merker poll reads; **Verified live** 2026-10-09), n-1 halves (duplicate `PLANT_FIELDS` / Pattern B proposals; second-battery SoC refuse), n-2 builders/parser/spec (core), battery/PV Kennung lock.

- [ ] **2.7.n — Binding 1.0: stable identifiers + generic EHAL read path** (slice of epic **Binding**; write side + Signal list = archived **2.7.q**; draft: [`backlog/EHAL-Binding-UX-Draft.md`](EHAL-Binding-UX-Draft.md) §9)
  - **Goal:** freeze the identifier contract (qualified EHAL IDs, Pattern B namespaces, stable Kennung) and make the Loxone **read conversion** data-driven, so **2.7.l** (inverter) and later wallbox / EV work add rows instead of code. Full Binding tools (HA, import hardening, Kennung cascade) stay in **2.+1** (P4–P6). Storage stays unchanged; no data migration.
  - **Problem (read path):** every EHAL **read** field is still wired by hand in `integrations/loxone_adapter.py` (`LoxoneConfig` + per-field branches: kW→W, clamps, required/optional). Example: commit `32bb5b8f` (2.7.j) touched many places for four new read fields. Risk: session F (n-5) touches the production read path — gate on session E. The **write** path is already push-only / generic (**2.7.q**, archived).
  - **Note:** Push-only VO path since **2.7.o**; Merker name optional on bindings. Maintainer decisions 2026-10-08: no Merker names on the wire after 2.7.q; Kennung rename risk accepted as "not worse than before", so n-3 is not escalated. **P0d** (bound but missing Merker) is obsolete after push-only — dropped.
  - **Note (stale companion docs):** [`Binding-Walkthrough-Ist.md`](Binding-Walkthrough-Ist.md), [`Binding-Walkthrough-Soll.md`](Binding-Walkthrough-Soll.md), and draft §9 still mention obsolete P0d / “generic write” / former n-6 — scrub in a later pass.
  - **Sessions (order):** B → C; D parallel; E → F; then **2.7.l P1**. If F is not ready for the 2.7 release, ship B–E and move F to 2.+1. **Session A** → [Erledigt](Backlog-Erledigt.md) (**Verified live** 2026-10-09).

  - [ ] **Session B — Binding P0c spike** (was n-1 leftover): inventory which persisted files key by entity id (history, run_state, shadow, dumps, fixtures). Deliverable: short list + **yes/no alias table**. Unblocks session C alias question and Inverter P1 note. (n-1 bugfixes already in Erledigt; P0d dropped.)

  - [ ] **Session C — 2.7.n-3 Kennung lock for consumers / EVs** (Binding P6 core): lock-on-first-change via `house_config/entity_id_lock.py` on consumer/EV upsert paths (same pattern as battery/PV, already committed). Full “Kennung ändern” cascade stays in 2.+1. Alias table only if session B said yes.

  - [ ] **Session D — 2.7.n-2a wire cleanup** (n-2 core done): builders + `parse_qualified_id` + round-trip tests (`ehal/qualified_ids.py`, `tests/test_qualified_ids.py`) and `docs/spec/ehal.md` § Qualified EHAL IDs are in. Open: loud write / `status.json` emit `grid.meter.set_grid_export_power_limit` (align Live-Schreiben / VI; plant storage keeps bare keys). Re-open n-2 only if a Signal-list gap finds a missing kind.
    - **Deferred (PV namespace):** `pv.{Kennung}.*` later; keep PV bare on the plant wire; do not invent a Kennung yet.
    - **Deferred (kind rename):** prefer `grid.meter.get_export_power_limit` / `set_export_power_limit` over today’s `*_grid_export_power_limit`; needs explicit rename + alias-on-load in one change (templates, role JSON, Live, docs) — not this session.

  - [ ] **Session E — 2.7.n-4 characterization extend** (gate for F): extend `tests/test_loxone_read_characterization.py` with per-battery reads, optional ESS `get_*`, missing/stale push-inbox / required errors. Baseline already pins kW→W, clamps, required missing, export-limit omit. Must stay green through session F. Write half = **2.7.q Q1** (done).

  - [ ] **Session F — 2.7.n-5 field registry + generic Loxone read:** unit (Loxone / EHAL), factor, sign, clamp, required per field in `share/ehal/roles/*.json`; replace `LoxoneConfig` fields and per-field branches in `integrations/loxone_adapter.py` with registry-driven read (inbox by qualified ID → conversion → required / optional); per-battery reads via qualified ID. No Merker name (push-only since 2.7.o).
  - **Scope limits (F):** Loxone only (HA parity = Binding P5; OpenEMS unchanged); no multi-EV runtime; no field renames. Signal list / export already in **2.7.q**.
  - **Gate:** F merges only with E green. If F is late for 2.7, A–E ship alone and F moves to 2.+1.
  - **Decided (namespaces):** by device type, no cryptic `flex.`: `ess`, `evcs`, `ev`, `inv` (2.7.l), **`grid`** (first Kennung `meter` → `grid.meter.*`), `heatpump`, `pool`, `consumer`. Remaining plant house-wide fields stay bare (outside temp, absent, **PV until deferred `pv.*`**). Storage stays as saved (`flex.{slug}.*` and bare plant grid keys); renaming stored keys is a separate alias-on-load step. Wire already emits `consumer.` / `heatpump.` / `pool.`, not `flex.`. Builders: `ehal/qualified_ids.py`.
  - **Decided:** `ev.` + `evcs.`; `sens_evcs_connected` valid in both and **not** renamed in 2.7.n. Wire titles from qualified ID (2.7.q); legacy Merker / EFM names on **import** only.
  - **Decided (grid):** exchange `grid.meter.<kind>` for the named grid fields; more `grid.<Kennung>.*` meters may follow. Plant storage/bindings keep bare kind keys.

- [ ] Remove any rollback legacy code from former chapters 
- [ ] Check if there are any remaining automatic unit or sign conversions in loxone-push or loxone-Write
- [ ] Make a code review comparing EHAL field mapping / binding for Loxone and HA - search for similarities in different codes and search for duplications and potentials for reuse / unification
- [ ] Improve readability of Live-Lesen by different colors (search if this topic is mentioned already elsewhere)
  - for optional readings
    - Display in gray
    - Show the fallback default value if available (with hint)
  - propose colors for other states of Live Lesn values  
- [ ] Check caching of Loxone push readings also for non-numeric values (e.g. ev.e_auto.get_evcs_ready_by_time) in order to make these values survive a restart of main.py

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
  - **Note (epic Binding, see [draft](EHAL-Binding-UX-Draft.md)):** **P1** — before the migration script assigns ids (`wr_main`, `owned_by`), run **Binding P0c** (which persisted files key by entity id). **P2** — inverter forms get the Kennung logic of `entity_id_lock` from the start (**Binding P6**); do not add a fifth `slug_id` variant in the UI. **P4** — Loxone Merker names, `status.json` keys and VO paths for inverters wait for **Binding P1** (naming grammar); if P4 lands first, only bindings + Live rows, no name suggestions or templates.

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


### Version 2.+1 - Enhance Auto Binding functionality

- [ ] **Binding — EHAL-Com signal contract, both directions** (epic **Binding**; revised 2026-10-08 after the push-only decisions; analysis + overlaps: [`backlog/EHAL-Binding-UX-Draft.md`](EHAL-Binding-UX-Draft.md), start with §0)
  - **Principle (decided 2026-10-08):** **Earnie defines the signals (qualified EHAL IDs); the smarthome backend (SB) maps them to its own objects.** Loxone: read = push (VO path carries the ID, done in 2.7.o), write = `status.json` + VI (archived **2.7.q**). Earnie stores no SB names for Loxone. Home Assistant: **Weg B** — same contract over HTTP in both directions, the mapping lives in HA (generated YAML package); see P5. EHAL-Com shows the contract (which signals Earnie needs and why), the match status and the export.
  - **Problem (old, partly solved):** the SB-name model (import derived EHAL field and entity from the name, typos dropped signals, EHAL-Com did not show what exists) is gone for Loxone (**2.7.q**). What stays open: entities are identified by an `id` the user never sees (P6), and users need to see which signals are required, received and exportable.
  - **Row (Signal list):** qualified EHAL ID · meaning (with entity) · required by (function, optional / required) · match status · export. Match status is derived at render time, never persisted: Loxone read = last received (age) / never; Loxone write = last fetched by the Miniserver; HA (Weg B) = last received / last fetched; legacy HA pull = mapped `entity_id`. Colour always with a symbol.
  - [ ] **Binding P0 — Spikes (reduced):** (a) Loxone Config round trip of our VI/VO XML — **done** (templates follow the Config export shape; Q4 VI v2 + generators); (b) `LoxAPP3.json` content — **obsolete** (the ID arrives in the push); (c) which persisted files key by entity id — **open**, decides the rename cascade and alias table; (d) bound but missing Merker — **obsolete** after 2.7.q.
  - [x] **Binding P1 — Qualified EHAL ID + parser:** delivered by **2.7.n-2** (builders + `parse_qualified_id` + round-trips + `docs/spec/ehal.md`). Import still creates entities from Merker / EFM names.
  - [x] **Binding P2 — Signal list + match status (Loxone slice):** **2.7.q Q7**. Later: backend-neutral table incl. HA, per-entity counters, optional-field activation polish.
  - [x] **Binding P3 — Export (Loxone slice):** Q7 UI ZIP + q.C CLI gens; "needed" = activated bindings. HA YAML stays P5.
  - [ ] **Binding P4 — Import hardening + discovery:** preview before entities are created (list of new entities, Bezeichnung / Kennung editable) instead of silent `apply_typed_matches`; did-you-mean for near-miss `Earnie_*` names in the import; **discovery inbox** of unknown incoming IDs (the receiver exists; list them next to the contract); battery / PV / inverter import = stub vs bind-only. Dropped: the separate signal-catalog file (push itself carries the IDs).
  - [ ] **Binding P5 — Home Assistant, Weg B (decided 2026-10-08):** HA talks to Earnie through the same HTTP contract as Loxone. HA → Earnie: automations call `rest_command` to a backend-neutral receiver (`/ehal/telemetry/<ID>/<v>`, the `/ehal/loxone/telemetry/` path stays as alias; token per backend; heartbeat per link). Earnie → HA: HA polls `status.json` (REST sensors) with the qualified keys and its own automations act on them. Earnie generates a **YAML package** (rest_command + automations + REST sensors) and **pre-fills the `entity_id`s from today's bindings**, so existing installs migrate without retyping. The mapping then lives in HA; units are converted there (decide: canonical EHAL units on the wire vs a `unit` parameter, because Earnie cannot know the HA entity's unit). Reuse inbox freshness / zero rule / last-known; the Add-on (HA add-on repo, Add-on Version 1.0) can ship the package. The REST pull adapter (`HaAdapter`, `ha_units`, HouseSim S1–S4, HA Lab golden maps) and the HA mapping chapter stay until parity is proven; then retire. Align with MQTT adapter / Add-on 1.0 (a third carrier for the same contract).
  - [ ] **Binding P6 — Kennung (entity id) as editable variable:** field next to Bezeichnung on every entity form, prefilled from the label, uniqueness guarded, lock as in `entity_id_lock`; explicit "Kennung ändern" with cascade dry-run and a report of the **Loxone VO / VI addresses (and HA package entries) that now deviate**; generalise `clean_entity_ids` to `rename_entity_id`; unify the four `slug_id` UI paths. Battery / PV id-lock is committed (`house_config/entity_id_lock.py`); this phase extends it to consumers / EVs and adds the rename cascade. Before **Inverter P2** and Pool nesting.
  - **Note:** Order: **2.7.q** Q1–Q8 (archived) and **2.7.n-2** builders landed; next → P4; P6 may start now; P5 after P4. Residual Merker poll reads = **2.7.n Session A** (archived, **Verified live** 2026-10-09). **Inverter P4**, Multi-EV / Wallboxes, Pool nesting, **Add-on Version 1.0** and the MQTT adapter touch the same grammar — see draft §6.
  - **Decided:** Kennung is **editable** (P6), defaulting from the Bezeichnung. Rename only as an explicit action with cascade dry-run; if **P0c** shows history / dumps / fixtures keyed by id, an alias table (`old → new`) applied on read — no separate immutable `uid` unless P0c shows broad dependence. Because the Kennung is now part of the wire contract (it sits in the Loxone VO address), a rename needs a matching change in Loxone Config; the maintainer accepts this as not worse than before (2026-10-08). Epic `Binding` is registered in `roadmap-nomenclature.mdc`.
  - **Open decisions:** import of battery / PV / inverter as stub vs bind-only (before P4); HA unit handling on the wire (before P5).
  - **Decided (2.7.q Q8):** Loxone empty-string keys in `ehal_bindings` are activation flags (not a separate field list); Signal list may own activation later.


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
- [ ] **Anonymous install counter (daily ping, no ID)** — *Draft, to be specified before implementation.* Goal: know roughly how many Earnie instances run (HA add-on, LoxBerry, Docker) without processing personal data.
  - **Today:** no telemetry, update check or install ID in the code. Outbound calls go only to data providers (aWATTar, ENTSO-E, Open-Meteo, forecast.solar), which see the users' IPs, not the maintainer. Distribution stats (GHCR pulls, GitHub release downloads) are only a rough proxy: auto-updates and CI pulls distort them and they say nothing about running instances.
  - **Principle:** *count, do not recognise.* At most one request per 24 h per instance, **no persistent ID**, no cross-day linking. The server only increments a per-day counter (optionally per `version` / `channel` / `platform`) and stores neither IP nor request log. Result = number of pings per day ≈ active instances (approximate by design).
  - **Payload (whitelist, nothing else):** `v` (Earnie version), `channel` (stable / prerelease), `platform` (`ha` / `loxberry` / `docker`). **Never:** config, hostnames, location / timezone, device or entity names, consumption / PV / tariff data, counts of devices. Energy data reveals presence and behaviour — keep the payload coarse.
  - **Client sketch:** small module (e.g. `runtime_store` timestamp of the last ping, throttle 24 h persisted so restarts do not double-count), called from the daemon loop; short timeout, failures swallowed silently (never affects optimisation or live operation); no ping in tests, backtesting / SE runs, HouseSim, CI or `-dev` builds; switch in `config.json` (+ `share/config/config.schema.json`), shown in the UI with a one-line explanation.
  - **Server sketch:** minimal counter endpoint (static-style, no application logs, IP logging off or truncated at the hoster); hosting choice open.
  - **GDPR / legal notes (to be confirmed with a data protection officer or lawyer before release):** without an ID the payload is not meant to identify anyone, but the IP is technically processed by the hoster for the request → document it, minimise (no logs, short retention), prefer a EU hoster with a processing agreement. A persistent ID (even random) would be pseudonymous = personal data → consent (Art. 6(1)(a) GDPR) and possibly § 25 TDDDG; deliberately **not** part of this item. German user doc: new section "Datenschutz / anonyme Installationszählung" (what is sent, why, how to switch off) in the same change (`german-user-docs.mdc`); mention in add-on `DOCS.md` of both channels.
  - **Open decisions:** default **opt-in** (safest, lower numbers) vs. **opt-out** with prominent notice (better numbers, needs the legal check); endpoint host / domain (e.g. under the `earnie-hems.com` domain already used for support); whether per-`version` counters are worth it (useful to see update uptake, finer = more re-identification risk for rare versions → consider dropping rare buckets); optional later upgrade to an opt-in ID for exact weekly / monthly actives (separate item).
  - **Tests:** throttle (24 h, restart), disabled by default in tests / dev / HouseSim, payload whitelist (no extra keys), failure never raises, config switch honoured.


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)

## Findings from former Research

- [x] **Live price prognosis — Energy-Charts `public_power_forecast` trial (archived):** full implementation including async `runtime/cache` warmup lives on branch `archive/energy-charts-forecast-research` only — not for merge to `main`. Product power features remain archive hour-of-day.