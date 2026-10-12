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

**Order:** Epic **Regression** (R-Rec / P1; formerly letter **2.7.i**) is independent and can start any time — ideally its MVP lands before the 2.7 release so it guards the multi-storage changes. Official **2.6.0** is on `main`; finish the remaining 2.7 letters on `main`. Do not bump `version.py` to a publishable 2.7 without approval. Shadow client (**2.7.f**) is done — dogfood the rest of 2.7 against Prod with **2.6.o** feed. **2.7.a** (code + Loxone wiring + live dogfood), **2.7.b** (Thermals P2), **2.7.c** (multi-ESS), **2.7.j** (additional ESS parameters), former **2.7.d** (one-way storage type, folded into **2.7.g**/**2.7.h**), **2.7.g** (single-use powerstation reserve), **2.7.h** (standby-backup code + entity-scoped Quellenwahl done; productive dogfood after operator EcoFlow bridge rewire — see Bugfixes), **2.7.k** (ENTSO-E live prices), **2.7.p** (virtual PS consumer-start release), **2.7.q** (push-only write + Signal list), **2.7.r** (HA live I/O contract), **2.7.n** (Sessions A–F; field registry + generic Loxone read), **EHAL unit conversion — no hardcoding** (read + write registry), and **2.7.l** (Inverter P1–P5) → [Erledigt](Backlog-Erledigt.md).
- **Note (deferred from 2.7.n):** `pv.{Kennung}.*` later — keep PV bare on the plant wire. Prefer `grid.meter.get_export_power_limit` / `set_export_power_limit` over today’s `*_grid_export_power_limit` (explicit rename + alias-on-load). Binding walkthroughs marked STALE (historical).
- **Note:** `/jdev/sps/io` Merker HTTP removed from production Python (VO push + LoxAPP3 presence) → [Erledigt](Backlog-Erledigt.md).
- **Note:** Loxone vs HA EHAL mapping review + shared `ehal/field_catalog.py` → [EHAL-Mapping-Review.md](EHAL-Mapping-Review.md) / [Erledigt](Backlog-Erledigt.md).
- **Note:** SH-backend concentration review + Binding rollback cleanup + EHAL Loxone-agnostic naming → [Erledigt](Backlog-Erledigt.md) / [`SH-Backend-Concentration-Review.md`](SH-Backend-Concentration-Review.md).
- **Note:** SH concentration Phase A–D → [Erledigt](Backlog-Erledigt.md).
- **Note:** Binding P5 path rename (`/ehal/telemetry/…` + `/ehal/loxone/telemetry/…` alias) → [Erledigt](Backlog-Erledigt.md).
- **Note:** Rename Pattern B → entity-scoped bindings → [Erledigt](Backlog-Erledigt.md).
- **Note:** **2.7.l** Inverter P1–P5 → [Erledigt](Backlog-Erledigt.md); draft [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md). Open: follow-ups below. Device catalog deferred (own item when picked up).

- [ ] **Inverter follow-ups** (postponed from **2.7.l**; epic **Inverter**): DC/AC efficiency paths; multi-inverter live attribution of `sens_pv_production_active`.
- **Note:** Deferred (not part of 2.7.l): device catalog for inverters and batteries (commercially available models with rated powers, capacity, efficiency, limits) so parameters need not be typed by hand. The P2 presets (e.g. "EcoFlow Delta 3") are only hand-written seeds; the catalog would replace them later. Own backlog item when it is picked up.

- **Note:** Shadow architecture review (proposal) + **R1** policy façade → [Erledigt](Backlog-Erledigt.md) / [`Shadow-Architecture-Review.md`](Shadow-Architecture-Review.md); spec §11.1 / §12. Open implementation = **R2–R4** below.
- [ ] **Shadow R2 — Single Loxone input contract:** feed-only VO telemetry; `meta.json` capability; retire Prod-inbox file fallback after gate; never reintroduce Merker-superset. Details: [review](Shadow-Architecture-Review.md) §3 R2.
- [ ] **Shadow R3 — Transport intercept:** shared record/replay helpers; complete `assert_not_shadow_backend` on probes; extract daemon orchestration from `main.py`. Details: [review](Shadow-Architecture-Review.md) §3 R3.
- [ ] **Shadow R4 — Feed gaps:** ENTSO-E (and other missing `ext:*`) record/replay; S4 Soll/Soll stays **2.+1**. Details: [review](Shadow-Architecture-Review.md) §3 R4.
- [ ] Anonymous install counter (daily ping, no ID)

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

- [ ] Implement max-power dependent tariff - see Earnie-Projekt\Entwicklungsplan\Offen\Earnie-Leistungstarif-AT-2027-Entwicklungsdokument.md

- [ ] ** Release regression suite (golden-master cases, public + private data)** (epic **Regression**; independent of **2.7.a–h**; spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md))
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
  - Own / time-variable tariffs: see the four **User-defined tariffs** items below (spec: `Earnie-Projekt\Entwicklungsplan\Offen\Earnie-Benutzertarife-Entwicklungsdokument.md`)
- [ ] **User-defined tariffs — T1: rules engine + `user_tariffs.json`** *(spec: see Part 2 above, §4 and §9)*
  - Extract the rule engine from `data/grid_fees.py` into a shared module; add `rules[]`, `price_floor_cent_kwh`, `price_cap_cent_kwh`, `requires[]`, `source`, `last_verified` to import/export tariffs (additive, existing entries stay valid)
  - Rules act on 15-min slots, first matching rule wins; `holidays` option (`treat_as`: sunday | weekday | own) via the `holidays` package (new dependency, MIT, offline); optional `region` in the house profile (required only with holiday logic)
  - Loader for `user_tariffs.json` (merge with `tariffs.json`, ID collision = error, `user_` prefix); config pack, path resolution and add-on persistence must include the file
  - Reserve `applies_to` (only `"main"` allowed); reject `tiers` and other unsupported features loudly (no silent fallback)
  - Tests/fixtures: VKW Strom Duo summer window (regression: monthly average still 9.15 ct), Octopus Go, Westnetz §14a Modul 3
- [ ] **User-defined tariffs — T2: house-profile `netznutzung` rules + `tariff_price_series`** *(after T1)*
  - Allow `rules[]` in `netznutzung` when `area_id` is null (§14a Modul 3 HT/ST/NT)
  - Single `tariff_price_series(tariff, slots, epex, house)` interface for MILP, SE and editor preview
- [ ] **User-defined tariffs — T3: tariff editor + import I1/I2** *(after T2)*
  - Form model, validation and preview data in the tariff package without UI; Streamlit is the first front end; stepwise disclosure, price preview, shadow-rule warning, invoice check
  - Import: copy catalog tariff as template, JSON file/paste
- [ ] **User-defined tariffs — T4/T4b: contribution path + signed catalog access** *(after T3; legal review first)*
  - Opt-in upload with payload preview, `individual` flag, no free text and no personal data; extend `LICENSE.md` § 3 for tariff contributions
  - Signed catalog package with validity date, manual import; credit for accepted contributions or small one-time fee; automatic updates / yearly subscription later
- [ ] Check possibilities to show decimal numbers according to regional settings (e.g. use "," as decimal sign for Germany)
- [ ] Simulate restrictions for energy export dependent on current grid situation in SE (and maybe Live) — **after 2.7.a** (consumes Live/MILP/EHAL export-cap model; do not redefine caps here)


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)

## Findings from former Research

- [x] **Live price prognosis — Energy-Charts `public_power_forecast` trial (archived):** full implementation including async `runtime/cache` warmup lives on branch `archive/energy-charts-forecast-research` only — not for merge to `main`. Product power features remain archive hour-of-day.