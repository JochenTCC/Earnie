# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **HA-Loxone-Bridge-Builder:** standalone tool (no Earnie/EHAL runtime dependency) to auto-generate HA `rest_command:`/`automation:` YAML for numeric HA→Loxone writes. Design draft: [backlog/HA-Loxone-Bridge-Builder-Draft.md](HA-Loxone-Bridge-Builder-Draft.md). **Not part of Version 2.6.** A different audience (any HA+Loxone install). Do not share code with **2.6.b** / **2.6.e** (those map HA entities onto a fixed EHAL vocabulary inside Earnie). Deferred Loxone Virtual-In/Out XML in the draft is also not the Version 2.+1 “Earnie → Loxone template XML” item.
  - **POC (2026-10-14):** EcoFlow Delta 3 bridge, both directions, Loxone → HA via webhook (no PyLoxone). Generator `tools/ha_loxone_bridge/` (fixed JSON mapping, no scan / matching yet); tests `tests/test_ha_loxone_bridge.py`; user doc `docs/einrichtung/ha-loxone-bridge.md`. Live acceptance pending (see Bugfixes: Delta 3 bridge self-write).
- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog

### Version 2.7 — Multiple storages and export power limitation

**Order:** Epic **Regression** (R-Rec → R0 reduced → P1 → P2; formerly letter **2.7.i**; L3 + P3 stay in 2.8; **R-Rec** + **R0** + **P1** + **P2** → [Erledigt](Backlog-Erledigt.md)) shipped for 2.7 so it guards multi-storage changes and customer reports can be captured as cases. Official **2.6.0** is on `main`; finish the remaining 2.7 letters on `main`. Do not bump `version.py` to a publishable 2.7 without approval. Shadow client (**2.7.f**) is done — dogfood the rest of 2.7 against Prod with **2.6.o** feed. **2.7.a** (code + Loxone wiring + live dogfood), **2.7.b** (Thermals P2), **2.7.c** (multi-ESS), **2.7.j** (additional ESS parameters), former **2.7.d** (one-way storage type, folded into **2.7.g**/**2.7.h**), **2.7.g** (single-use powerstation reserve), **2.7.h** (standby-backup code + entity-scoped Quellenwahl done; productive dogfood after operator EcoFlow bridge rewire — see Bugfixes), **2.7.k** (ENTSO-E live prices), **2.7.p** (virtual PS consumer-start release), **2.7.q** (push-only write + Signal list), **2.7.r** (HA live I/O contract), **2.7.n** (Sessions A–F; field registry + generic Loxone read), **EHAL unit conversion — no hardcoding** (read + write registry), and **2.7.l** (Inverter P1–P5) → [Erledigt](Backlog-Erledigt.md).
- **Note (deferred from 2.7.n):** Plant PV sum stays bare `sens_pv_production_active`; first entity-scoped `pv.{pv_system_id}.sens_pv_production_active` shipped with live attribution (Inverter follow-ups). Prefer `grid.meter.get_export_power_limit` / `set_export_power_limit` over today’s `*_grid_export_power_limit` (explicit rename + alias-on-load). Binding walkthroughs marked STALE (historical).
- **Note:** `/jdev/sps/io` Merker HTTP removed from production Python (VO push + LoxAPP3 presence) → [Erledigt](Backlog-Erledigt.md).
- **Note:** Loxone vs HA EHAL mapping review + shared `ehal/field_catalog.py` → [EHAL-Mapping-Review.md](EHAL-Mapping-Review.md) / [Erledigt](Backlog-Erledigt.md).
- **Note:** SH-backend concentration review + Binding rollback cleanup + EHAL Loxone-agnostic naming → [Erledigt](Backlog-Erledigt.md) / [`SH-Backend-Concentration-Review.md`](SH-Backend-Concentration-Review.md).
- **Note:** SH concentration Phase A–D → [Erledigt](Backlog-Erledigt.md).
- **Note:** Binding P5 path rename (`/ehal/telemetry/…` + `/ehal/loxone/telemetry/…` alias) → [Erledigt](Backlog-Erledigt.md).
- **Note:** Rename Pattern B → entity-scoped bindings → [Erledigt](Backlog-Erledigt.md).
- **Note:** **2.7.l** Inverter P1–P5 → [Erledigt](Backlog-Erledigt.md); draft [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md). Open: follow-ups below. Device catalog deferred (own item when picked up).
- **Note:** Shadow architecture review + **R1**–**R4** → [Erledigt](Backlog-Erledigt.md) / [`Shadow-Architecture-Review.md`](Shadow-Architecture-Review.md); spec §11.1 / §12. S4 Soll/Soll stays **2.+1**.
- **Note:** Plant topology (balance nodes / Bilanzierungspunkte, control rule): theses [`Plant-Topology-Theses.md`](Plant-Topology-Theses.md), reviews [`Plant-Topology-Theses-Review-Claude.md`](Plant-Topology-Theses-Review-Claude.md) / [`Plant-Topology-Theses-Review-Grok.md`](Plant-Topology-Theses-Review-Grok.md), decision record [`Plant-Topology-Conclusion.md`](Plant-Topology-Conclusion.md) (2026-10-12). Work items: epic **Topology** below.

- **Note:** Epic **Regression** 2.7 scope (**R-Rec** → **R0** → **P1** → **P2**) → [Erledigt](Backlog-Erledigt.md). Continuation (**L3** + **P3**) in Version 2.8. Spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md).
- **Note:** R0 / P1 L1 goldens used recorder-format cycles **seeded from historical backtesting windows** (scrubbed for public commit). **From now on:** substitute with **newer live `runtime/recorder/` cycles ASAP** before trusting goldens as production-representative; re-check tolerances if spread changes. Production-path sample as an extra gate case remains an R0 follow-up.
  
- **Note:** Epic **ThermalHorizon** P1–P5 (`2.7.0-dev.57`, PR #37) → [Erledigt](Backlog-Erledigt.md). Spec [`docs/spec/thermal-horizon-simulation.md`](../docs/spec/thermal-horizon-simulation.md). Profiling session (NAS timing + acceleration ranking) → [Erledigt](Backlog-Erledigt.md).

- **Note:** Epic **EarlyStart** (spec [`docs/spec/early-start-scheduling.md`](../docs/spec/early-start-scheduling.md)): **P0** (punctuality log) and **P1** (adaptive lead 15–90 s, plan for the tick, write at the tick; no state projection — owner decision 2026-10-15) and the **prefetch** follow-up → [Erledigt](Backlog-Erledigt.md). Success is judged from the `Pünktlichkeit:` line in `earnie.log` / `runtime/cycle_stats.jsonl`. Dropped with P1 scope: SoC/thermal/EV projection to T, pre-commit SoC drift check, MILP solver deadline (MILP < 1 s on NAS since dev.57).
- [ ] **Clock-skew diagnostics** (spec early-start-scheduling §7; no longer part of EarlyStart): estimate the host clock offset from the HTTP `Date` header of requests already made (no extra request); offset > 2 s → warning with NTP hint, optional `clock_skew_sec` in `cycle_stats.jsonl`. No early-start gate — the hold writes at the system-clock tick either way. Low priority while the NAS runs NTP.

- [ ] Full orchestration of model version migration
  - Target is that after an update - the user is guided through migration as flawless as possible
  - Users with older Earnie versions shall be guided through the migration after software update and be informed before!
  - If Earnie recognizes that data should be migrated it asks if migration shall be done and give hints for manual to-dos (if needed)
  - Prepare a complete v3 config data set for regression testing from Earnie_env_home history
  - For all future version increments we need the same capability for Earnie (save this as a rule)

- [ ] first alpha quality review
- [ ] alpha release

- [ ] Anonymous install counter (daily ping, no ID)

- **Note:** Plant topology epic **Topology** — **P1** + **P2** + Powerstation AC wording → [Erledigt](Backlog-Erledigt.md). **P3–P5** (widen acceptance, MILP change, balance nodes) remain under **Version 2.+1 — Plant topology**. Decision record [`Plant-Topology-Conclusion.md`](Plant-Topology-Conclusion.md). `inverters[].ac_connection: island` = bus participation (not “off the grid”); flag stays until the port model in 2.+1 / P5.

### Version 2.8
  
- [ ] Enable multiple EV / Wallboxes *(reuse entity-scoped namespacing approach from **2.7.c** multi-ESS)*
- Parametrize EVs as now (+ sensors)
- Parametrize Wallboxes 
  - Max power
  - sensor / control commands
- Assignment is done when EV is connected to a wallbox:
  - both devices report connection
  - confirm assignment by test charging
  - Assignment is removed when disconnecting
  - Cancel assignments and re-bind in case of shutdown

- [ ] Implement max-power dependent tariff - see Earnie-Projekt\Entwicklungsplan\Offen\Earnie-Leistungstarif-AT-2027-Entwicklungsdokument.md; the tariff model and the penalty ladder come from Edbert, see the **Capacity charge** sub-item of the **Edbert integration** item (Version 2.+1, last block); this item keeps the Earnie side (state, MILP, planning loop)

- [ ] **Regression L3 + P3 — live replay, gate + scrub** (continuation of epic **Regression** after R-Rec / R0 / P1 / P2 → [Erledigt](Backlog-Erledigt.md) in Version 2.7; spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md))
  - [ ] **Regression L3 — live replay:** replay runner for recorder windows (replay vs. recorded, replay vs. golden replay), case creation from a selected time window, exclusion/reporting of cycles flagged as override/outage/manual (spec §15).
  - [ ] **Regression P3 — gate + scrub:** CI job `regression` before `promote` in `release-publish.yml` (deploy-key secret), whitelist-based scrubber for customer → public repro cases (names/IDs, location, GDPR consent note), optional metric trend across releases; soft → hard gate decision.

- [ ] **Monitor charts — pan-to-load spike** (feasibility + usability → go/no-go; independent of **2.7.a–c** / **2.7.g–h**)
  - **Today:** display range depends on device (`ui/s2_viewport.py`: phone = 24 h segments, desktop/tablet = SA₀→SA₂). Charts get only the data of that default range. Panning with the Plotly drag/pan tool beyond it shows an empty chart. Navigation is via buttons / date picker (`ui/history_navigation.py`, `ui/s2_navigation.py`).
  - **Option A — pan-driven lazy loading:** panning replaces the nav buttons. Data for newly visible ranges is fetched step by step and appended to the charts.
  - **Option B — coupling:** keep the buttons, but sync them with the pan position (pan past the edge → switch segment/cycle; button → move the Plotly x-range). Optionally preload neighbouring segments (±1) so short pans never show empty areas.
  - **Feasibility to check:** Streamlit `st.plotly_chart` does not return `relayout` (x-range) events — only selections. Needs a custom component, `streamlit-plotly-events`-style bridge or a debounced rerun trigger. Check rerun cost/latency per pan, keeping all S-2 charts (flow, SoC, cumulative, consumer stack) on the same x-axis, zone/SA marker decorations outside the default range, and memory/load time on the Pi/Synology.
  - **Usability to check:** touch pan vs page scroll on phones, discoverability vs explicit buttons, behaviour at log start / live edge ("Heute"), loading indicator while data is fetched.
  - **Outcome:** short spike on a branch (prototype for one chart, then all), test on desktop + phone, then decide: A, B, preload-only, or keep status quo. Record decision here before any productive implementation.

  **Naming:** simulator stages are **HouseSim S1–S4** (formerly "HA Lab P1–P4"). **HA Lab** now means only the `ha_lab/` Compose stack (Earnie + HAOS + evcc, [ha-lab-setup.md](../docs/spec/ha-lab-setup.md)).

- [ ] **PV forecast from HA (alternative source)** — Add possibility to take PV prognosis directly from HA when available, as an alternative to Earnie's own `data/pv_forecast.py` (forecast.solar). Config toggle per scenario/plant (own vs. HA entity), entity mapped via `ehal_bindings` like other HA sensors.
  - **Open question — scope:** likely fits the **48h online optimization** (live HA connection, fresh entity value each cycle) but unclear for the **Szenarien-Explorer** (SE runs fixed/reproducible input series; a live HA forecast entity breaks reproducibility unless a snapshot/recording mechanism is added) — clarify before implementation whether SE stays forecast.solar-only or gets a recorded-snapshot path.
  - Checked 2026-09-29: no other note of this idea in `backlog/Backlog-Bugfixes.md`, `backlog/Backlog-Erledigt.md`, `docs/spec/`, `.cursor/plans/`, or the external Entwicklungsdokumente (`Entwicklungs-Plan-Earnie-cons.md`, HA add-on/compat docs) — this stub is the only prior record.
- [ ] **HouseSim S3** — CI harness: short simulated windows, not N live `main.py` days. Load each archetype → golden map → `HaAdapter` → check criteria of concept doc §3.5 (setpoint effect on next read, degrade on write errors, SoC/PV/temperature in a plausible band) for **all** archetypes; the static 2.6.a fixture stays the fast job. Diagnose-JSON → fixture converter only when support needs it.
- [ ] **HouseSim wallbox write-back** — Wallbox setpoints act on the simulated physics instead of only the scenario override: `set_evcs_max_current` / mode writes (go-e / Wattpilot `amp` + `frc`, evcc `max_current` + enable) → charge power = current × voltage × phases while an EV is connected (`car_arrives` / `car_leaves`), capped by the EV's acceptance. Mock REST (S1–S3) and S4 integration; tests on `evcc_en`, `fronius_de`, `huawei_en` (`sma_keba` stays the read-only wallbox case). Prerequisite for **HouseSim scenario import**.
- [ ] **HouseSim scenario import** (idea, after wallbox write-back; prefers **2.7.c** multi-ESS + **2.7.g**/**2.7.h** powerstation model) — S4 config flow reads a finished Earnie scenario (`house_config` with consumers, PV, batteries) and builds the simulated house from it: one device per configured component with a matching archetype, physics parameters from the scenario instead of manual `house_params`. Consumers beyond battery + PV need their physics in the core first (wallbox: item above; heat pump: open). Concept doc §5 S4 „optional später“.
- [ ] **HA-Loxone bridge generator — second device: Roborock mop/vacuum robot** (follow-up of the Bridge-Builder POC with the EcoFlow Delta 3, see [HA-Loxone-Bridge-Builder-Draft.md](HA-Loxone-Bridge-Builder-Draft.md) and [`docs/einrichtung/ha-loxone-bridge.md`](../docs/einrichtung/ha-loxone-bridge.md))
  - When the Roborock (HA Roborock integration) is wired to Loxone / Earnie, build the HA ↔ Loxone bridge with `tools/ha_loxone_bridge/` instead of hand-written YAML — first test of the generator on a device other than the Delta 3.
  - Check which signals are needed (e.g. battery level, state, start / return-to-dock) and whether the generator covers them: today only `sensor` / `number` / `input_number` (both directions) and `switch` / `input_boolean` (Loxone → HA). A `vacuum` / `button` / `select` domain would be a generator extension — decide per signal, do not bend the mapping.
  - Record findings (missing features, mapping-file friction, Loxone template issues) in the Bridge-Builder draft.


### Version 2.+1 — Plant topology (epic **Topology** P3–P5, moved from 2.7 on 2026-10-14)

- **Note:** Continuation of the epic **Topology** (Version 2.7: P1 done, P2 + wording follow-up open). Decision record [`Plant-Topology-Conclusion.md`](Plant-Topology-Conclusion.md); order stays P3 → P4 → P5. Until P3 + P4 land, P1 rejects multi-house-ESS and foreign self-consumption loops on the live path (Szenarien-Explorer and backtesting unaffected). Ideally the Regression epic (R-Rec) guards the P4 MILP change.
  - [ ] **Topology P3 — per-ESS setpoint writes** (closes the **2.7.c** gap: today only the primary house battery receives setpoints): mode/target per house battery from `milp_plan["ess"]`, entity-scoped `ess.{id}.set_*` for every mappable grid-tied house battery (template `write_cycle_powerstation_setpoints`; `write_mapped_fields` on HA/OpenEMS; Loxone exchange IDs exist). Plant `set_grid_export_power_limit` unchanged. Lifts the P1 one-battery rule for `control: full` secondaries with own bindings (together with P4).
  - [ ] **Topology P4 — reactive regulator in the MILP:** residual includes Earnie-commanded ESS; the one battery with `regulates_on: grid` that Earnie does not command is pinned to the residual split (multi-ESS generalisation of `_add_self_consumption_coupling`); never-Automatik policy for Earnie-commanded batteries when another loop exists at the node. Accepts the foreign self-consumption battery (case b′) and two Earnie-commanded clusters (case c) instead of rejecting them.
  - [ ] **Topology P5 — balance nodes + attribution:** optional `components.json` → `balance_nodes[]` (`id`, `label`, `parent`, `ehal_bindings`, optional `update_interval_s`), `inverters[].node_id` / `consumers[].node_id` (default root); connections derived (upstream, devices, children, load residual); validation (exactly one root when present, no cycles, references resolve); wire `node.<id>.sens_node_power_active` / `sens_node_energy_import` / `sens_node_energy_export` for sub-nodes, root stays `grid.meter.*` (supersedes "more `grid.<Kennung>` meters may follow" in `ehal.md` / `qualified_ids.py`); `regulates_on` accepts a `node_id`; code evaluates the root only, per-node residuals as attribution rows on the Live page; one-shot migration if the root's grid bindings move from `plant` onto the root node. **Includes the `ac_connection` rename:** value `island` → a name that states bus participation, not grid connectivity (candidates `attached_only` — matches `attached_consumer_ids` — or `load_side`; pick at implementation; `grid_tied` stays). Touches `house_config/inverter.py` (`AC_ISLAND`, `allows_automatik`), `inverter_lifecycle.py`, `battery_kind.py`, `entity_resolution.py`, `milp_inverter.py`, `export_power_limit.py`, `pv_attribution.py`, `topology_live.py`, `share/config/components.schema.json` enum, UI option/labels, `docs/spec/ehal.md` and German user docs, tests. One-shot migration (`scripts.migrate_topology_once` or sibling, data model stays 4) plus fail-fast loader that rejects the old value with the migrate hint; no dual-read. Skip or fold into the port model if **Topology follow-up — Powerstation ports** is picked up first.
  - **Note:** Later, separate items (not phases): opt-in approximation when no root meter is readable; scoped tariff per child node (second billing meter, §14a); pass-through constraint for a declared series master; AC-side coverage via `sens_inv_power_ac` instead of DC·η.
  - [ ] **Topology follow-up — Powerstation ports instead of `ac_connection`:** decide together with **Topology P5** whether the scalar `grid_tied` | `island` is replaced by device ports (AC-in as one-way load at the root, one or more AC-out ports with own `attached_consumer_ids` and optional per-port source select / measurement) — also fits the series master (pass-through limit, Later item). Do not model a powerstation as a balance node: the child-node connection is a wire from the parent, the pack is a device with a converter in between, so the root would count the attached load twice. Only build when a second use case (several uncoupled AC outputs with separate planning or metering, series master) exists; for one output `attached_consumer_ids` suffices.
- [ ] **Inverter follow-ups** (postponed from **2.7.l**; epic **Inverter**). Design: [`docs/spec/conversion-losses.md`](../docs/spec/conversion-losses.md). Done: η split + live PV attribution → [Erledigt](Backlog-Erledigt.md).
  - [ ] Later: curtailment live weights (`attribute_plant_pv_to_inverters_w` → `allocate_inv_ac_limits_kw`)
- **Note:** Deferred (not part of 2.7.l): device catalog for inverters and batteries (commercially available models with rated powers, capacity, efficiency, limits) so parameters need not be typed by hand. The P2 presets (e.g. "EcoFlow Delta 3") are only hand-written seeds; the catalog would replace them later. Own backlog item when it is picked up.

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


### Version 2.+1 - Enhance Auto Binding functionality

- [ ] **Binding — EHAL-Com signal contract, both directions** (epic **Binding**; revised 2026-10-08 after the push-only decisions; analysis + overlaps: [`backlog/EHAL-Binding-UX-Draft.md`](EHAL-Binding-UX-Draft.md), start with §0)
  - **Principle (decided 2026-10-08):** **Earnie defines the signals (qualified EHAL IDs); the smarthome backend (SB) maps them to its own objects.** Loxone: read = push (VO path carries the ID, done in 2.7.o), write = `status.json` + VI (archived **2.7.q**). Earnie stores no SB names for Loxone. Home Assistant: **Weg B** — same contract over HTTP in both directions; live transport → **2.7.r**; mapping / YAML package comfort → P5. EHAL-Com shows the contract (which signals Earnie needs and why), the match status and the export.
  - **Problem (old, partly solved):** the SB-name model (import derived EHAL field and entity from the name, typos dropped signals, EHAL-Com did not show what exists) is gone for Loxone (**2.7.q**). What stays open: entities are identified by an `id` the user never sees (P6), and users need to see which signals are required, received and exportable.
  - **Row (Signal list):** qualified EHAL ID · meaning (with entity) · required by (function, optional / required) · match status · export. Match status is derived at render time, never persisted: Loxone read = last received (age) / never; Loxone write = last fetched by the Miniserver; HA (Weg B) = last received / last fetched; legacy HA pull = mapped `entity_id`. Colour always with a symbol.
  - [x] **Binding P0 — Spikes (reduced):** (a) Loxone Config round trip of our VI/VO XML — **done** (templates follow the Config export shape; Q4 VI v2 + generators); (b) `LoxAPP3.json` content — **obsolete** (the ID arrives in the push); (c) which persisted files key by entity id — **done** ([`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md); **Alias table: yes**); (d) bound but missing Merker — **obsolete** after 2.7.q.
  - [x] **Binding P1 — Qualified EHAL ID + parser:** delivered by **2.7.n-2** (builders + `parse_qualified_id` + round-trips + `docs/spec/ehal.md`). Import still creates entities from Merker / EFM names.
  - [x] **Binding P2 — Signal list + match status (Loxone slice):** **2.7.q Q7**. Later: backend-neutral table incl. HA, per-entity counters, optional-field activation polish.
  - [x] **Binding P3 — Export (Loxone slice):** Q7 UI ZIP + q.C CLI gens; "needed" = activated bindings. HA YAML comfort packaging stays P5; live I/O transport → **2.7.r**.
  - [ ] **Binding P4 — Import hardening + discovery:** preview before entities are created (list of new entities, Bezeichnung / Kennung editable) instead of silent `apply_typed_matches`; did-you-mean for near-miss `Earnie_*` names in the import; **discovery inbox** of unknown incoming IDs (the receiver exists; list them next to the contract); battery / PV / inverter import = stub vs bind-only. Dropped: the separate signal-catalog file (push itself carries the IDs). Comfort / HITL — not a 2.7 I/O blocker.
  - [ ] **Binding P5 — Home Assistant Weg B comfort (after 2.7.r):** full YAML package (rest_command + automations + REST sensors) **pre-filled from today's bindings**; migrate without retyping; Add-on (HA add-on repo, Add-on Version 1.0) can ship the package; Signal-list HA match status polish; retire REST pull adapter (`HaAdapter`, `ha_units`, HouseSim S1–S4, HA Lab golden maps) and HA mapping chapter after proven parity. Live transport / inbox / `status.json` parity is **2.7.r** (not this phase). Align with MQTT adapter / Add-on 1.0 (a third carrier for the same contract).
  - [ ] **Binding P6 — Kennung (entity id) as editable variable:** field next to Bezeichnung on every entity form, prefilled from the label, uniqueness guarded, lock as in `entity_id_lock`; explicit "Kennung ändern" with cascade dry-run and a report of the **Loxone VO / VI addresses (and HA package entries) that now deviate**; generalise `clean_entity_ids` to `rename_entity_id`; unify the `slug_id` UI paths. Lock-on-first-change for battery / PV / consumers / EVs is committed (`house_config/entity_id_lock.py`, Session C); this phase adds the rename cascade + VO/HA deviation report. **Inverter P2** reuses `entity_id_lock` without waiting for this cascade; Pool nesting still prefers the cascade before broad Kennung edits.
  - **Note:** Order: **2.7.q** / **2.7.n** / path rename / **2.7.r** archived. Comfort stays here: P4 / P5-rest / P6 (P6 may start anytime for Kennung UX). **Inverter P4**, Multi-EV / Wallboxes, Pool nesting, **Add-on Version 1.0** and the MQTT adapter touch the same grammar — see draft §6.
  - **Decided:** Kennung is **editable** (P6), defaulting from the Bezeichnung. Rename only as an explicit action with cascade dry-run. **P0c (2026-10-10):** history / runtime state / shadow / ledgers / cons_data **are** keyed by id → alias table **yes** (alias-on-read for history; rewrite-on-rename for small live files; dumps/fixtures re-record) — see [`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md). No separate immutable `uid`. Because the Kennung is now part of the wire contract (it sits in the Loxone VO address), a rename needs a matching change in Loxone Config; the maintainer accepts this as not worse than before (2026-10-08). Epic `Binding` is registered in `roadmap-nomenclature.mdc`.
  - **Open decisions:** import of battery / PV / inverter as stub vs bind-only (before P4); HA unit handling on the wire (before / inside **2.7.r**).
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
  - Own / time-variable tariffs: see the **Edbert integration** item below
- [ ] **Edbert integration — use the Edbert library for tariffs and market prices** *(Edbert is developed in the separate public repo [`JochenTCC/edbert`](https://github.com/JochenTCC/edbert); its backlog owns the work; architecture decision 2026-10-12: development document §9.3, Edbert `docs/spec/architecture.md`)*
  - **Architecture:** Edbert *library* (tariff editing, persistence, rule engine, grid fee, market-price chain, price series for future **and** past, forecaster interface) is always part of the Earnie deployment and used through the direct API `edbert.api`. The Edbert *product* (MQTT, editor page for users without Earnie) only delivers the future. Only Edbert supplies tariff data
  - **Engine (after Edbert `0.1.a`/`0.1.b`):** replace the tariff resolution in `data/tariff_pricing.py` / `house_config/tariffs_store.py` and the rule logic in `data/grid_fees.py` by Edbert's rule engine and `tariff_price_series`, for live **and** the SE (past periods; the monthly-table fallback exact → prior year → prior month stays, as a coded warning); the MILP keeps receiving `k_act` / `k_push_act` per 15-min slot (no model change). Regression: SNAP results unchanged, VKW Strom Duo summer window as a real window with the monthly mean still 9.15 ct
  - **Market prices:** replace Earnie's own chain (`data/live_market_prices.py`, `integrations/entsoe_client.py`, Energy-Charts part of `data/data_loader.py`, `integrations/awattar_client.py`, `data/live_price_cache.py`) by Edbert's market module (one implementation, no pandas). Needs from Edbert: price series with `market_cent` and forecast method per slot (maps to `price_source` exact / mirrored / predicted), range queries with a long-range cache for the SE
  - **Forecast:** Earnie's OLS model is handed to Edbert as an in-process forecaster object (no key; the key only guards plug-ins loaded through entry points in the product); horizon at most 72 h, `mirror` and `hold` remain as free methods
  - **Weather:** the weather access is built as an independent, caching function for both tools (shared library, built when the OLS plug-in is wired in; location open, proposal: standalone package without Earnie imports in this repo first, own repo later)
  - **Data (with `0.1.a`):** `user_tariffs.json` next to `tariffs.json` (config pack, path resolution, add-on persistence); optional `region` in the house profile for holiday logic
  - **Editor (after `0.1.c`):** embed Edbert's editor in the Szenarienkonfigurator; UI language follows Earnie (German), Edbert supports `de`/`en`
  - **Catalog (after `0.1.d`, legal review first):** decide the fate of the public `share/config/tariffs.json` (stays as frozen seed vs. new entries only via Edbert's catalog channel); extend `LICENSE.md` § 3 for tariff contributions
  - **Packaging and license (open decisions):** how Earnie consumes the Edbert library (PyPI release, pinned git tag, or vendored copy) incl. Docker image and Home Assistant add-on; license compatibility (Edbert: PolyForm Noncommercial; Earnie: own source-available license, same owner, separate grant possible)
  - **Capacity charge AT 2027 (after Edbert `0.+1`; Edbert spec section 5b, draft):** the monthly peak-based grid fee (SNE-G-V, per grid area from 2027) is modeled in Edbert as a `capacity` block next to the slot prices, never as a cent/kWh surcharge; Edbert stays stateless. Earnie's part:
    - **State:** supply the month-to-date peak (highest clock-aligned 15-min average import power of the calendar month at the grid connection, as the meter measures it) on every Edbert call; source EHAL/HA sensor or Earnie's own 15-min import log; a missing state is never taken as `0` (coded error from Edbert, no fallback)
    - **MILP:** peak variable `P_peak >= P_import,t` for all slots of the horizon and `P_peak >= peak_so_far`; objective adds the remaining capacity cost from Edbert's ladder (convex piecewise-linear: minimum, band limit 10 kW, higher rate above; two linear segments, no binaries while Edbert reports the bands convex); the cost is once per month, not per slot; a horizon that crosses the month boundary gets a second ladder starting at peak `0`
    - **Planning loop:** the horizon (1 to 2 days) is shorter than the billing month, so the per-slot MILP alone would refuse every exceedance; a slow loop sets a monthly peak budget from Edbert's ladder, `days_remaining` and the expected load (EV, heat pump), and raises the budget after a measured exceedance (the "reached" rungs of the ladder); what-if queries pass a planned peak as state
    - **Expected PV for the rest of the month (discussion 2026-10-14; algorithm draft: [`Capacity-Peak-Budget-Draft.md`](Capacity-Peak-Budget-Draft.md)):** the peak budget needs the PV outlook until month end, but not as a mean: the monthly peak is set by the worst days (dull, cold, heat pump and EV at the same time)
      - Per calendar month, sample real historical days from the Open-Meteo archive (last 3–5 years, house location): daily PV yield and temperature **from the same day** (joint sample, not separate averages; dull winter days are often cold days); use the distribution (e.g. P10/P50), never hour-by-hour averages across years (they smooth away exactly the days that set the peak)
      - Rest of month = forecast days (Open-Meteo forecast; check how many days are reliable) + historical sample days for the remaining days → probability that a peak budget holds until month end
      - Trade-off (ratchet): a higher peak costs one ladder step **once per month**, after that import up to this peak is free for the rest of the month. Compare the step cost with the summed benefit over the remaining days (cheaper import slots for battery/EV, PV sold at a higher feed-in price instead of stored). Early in the month a higher peak pays off more easily, late in the month hardly at all; once the month peak is set, use the headroom up to it actively
      - **SE:** run several real years (weather and prices from the same year) and show the spread of monthly peaks per calendar month (e.g. January 6.8–9.1 kW) instead of one "typical" value; 2022 (energy crisis) must be excludable or prices normalised to a current level
    - **SE and invoice:** monthly peaks from the 15-min consumption data, capacity cost per month as its own invoice line via Edbert's `capacity_charge_eur`; current user docs say "Leistungspreis ist nicht modelliert" (`docs/konfiguration/preise.md`, `docs/referenz/tarife-quellen.md`, `docs/ui/betriebsmodi.md`) and change with this
    - **Open until the final SNE-V 2027:** billing formula, minimum (2 kW or share of contracted power), introduction date per grid area; Edbert's research item tracks the check; keep this item, the standalone item *Implement max-power dependent tariff* (Version 2.8) and the Leistungstarif development document (L1→L5) consistent
  - **Note:** The former Earnie items *User-defined tariffs — T1…T4/T4b* are superseded by Edbert `0.1.a`–`0.1.d` and by this item.
- [ ] Check possibilities to show decimal numbers according to regional settings (e.g. use "," as decimal sign for Germany)
- [ ] Simulate restrictions for energy export dependent on current grid situation in SE (and maybe Live) — **after 2.7.a** (consumes Live/MILP/EHAL export-cap model; do not redefine caps here)


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)

## Findings from former Research

- [x] **Live price prognosis — Energy-Charts `public_power_forecast` trial (archived):** full implementation including async `runtime/cache` warmup lives on branch `archive/energy-charts-forecast-research` only — not for merge to `main`. Product power features remain archive hour-of-day.