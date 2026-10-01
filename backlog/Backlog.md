# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **HA-Loxone-Bridge-Builder:** standalone tool (no Earnie/EHAL runtime dependency) to auto-generate HA `rest_command:`/`automation:` YAML for numeric HA→Loxone writes. Design draft: [backlog/HA-Loxone-Bridge-Builder-Draft.md](HA-Loxone-Bridge-Builder-Draft.md). **Not part of Version 2.6.** A different audience (any HA+Loxone install). Do not share code with **2.6.b** / **2.6.e** (those map HA entities onto a fixed EHAL vocabulary inside Earnie). Deferred Loxone Virtual-In/Out XML in the draft is also not the Version 2.+1 “Earnie → Loxone template XML” item.
- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog

### Version 2.6 - Enhancements for HA coupling

**Versioning note:** Official **2.6.0** is the HA-coupling MINOR (supersedes **2.5.3** on `:latest`). Alpha compose still pins last community candidate **`2.6.0-alpha.12`** until the next pre-release bump. This branch keeps `version.py` at **`2.7.0-dev`** until an approved 2.7 bump.

**Next:** On this branch: **2.7.c** … **2.7.e**. Shadow Prod recorder (**2.6.o**), Shadow client (**2.7.f**), **2.7.a** (export limit + dogfood), **2.7.b** (Thermals P2), user-fixed tariffs, and absent EHAL on all backends (**2.6.p**) are done. Official **2.6.0** is on `main`.

**Scope:** easier HA coupling for Earnie. HA entity IDs live on `plant` / `consumers[].ehal_bindings` (Pattern B, Loxone-parity HITL). The generic HA↔Loxone bridge stays under Research Items. Add-on 1.0 (Earnie publishing its own state) is deferred to **Version 2.+1**.

**Documents:**

- [House simulator spec](../docs/spec/house-sim.md) — HouseSim S1–S4 (archetypes, core, S4 integration)
- [EHAL spec — Pattern B / Loxone HITL](../docs/spec/ehal.md) — same `plant` / `consumers[].ehal_bindings` as Loxone **2.4.k**
- [Add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md) — add-on packaging items; channel work is now **2.6.k**

### Version 2.7 — Multiple storages and export power limitation

**Order:** **2.7.c** → **2.7.g** → **2.7.h** → **2.7.e**; **2.7.i** (release regression suite) is independent and can start any time — ideally **P1** lands before the 2.7 release so it guards the multi-storage changes. Official **2.6.0** is on `main`; finish remaining letters here, then merge. Do not bump `version.py` to a publishable 2.7 without approval. Shadow client (**2.7.f**) is done — dogfood the rest of 2.7 against Prod with **2.6.o** feed. **2.7.a** (code + Loxone wiring + live dogfood), **2.7.b** (Thermals P2), and former **2.7.d** (one-way storage type, folded into **2.7.g**/**2.7.h**) → [Erledigt](Backlog-Erledigt.md).

- [ ] **2.7.c — Multiple isolated battery / battery+inverter entities** (bidirectional)
  - Isolated battery modes: charging / discharging / standby
  - batt+inverter modes: optimizing / charging / discharging
  - All batteries participate in optimization
  - **Export limit "unconstrained" value (from 2.7.a):** `live_unconstrained_export_kw()` in `optimizer/live_export_limit.py` writes PV kWp sum + max discharge of the single battery (only when `battery_control = full`). With multi-ESS, sum the max discharge power of **every** battery that supports forced discharge (skip `limits_only` / `read_only` / physical powerstations from **2.7.g**/**2.7.h** that cannot feed the house grid); update `docs/spec/ehal.md` + `docs/einrichtung/loxone-anbindung.md` accordingly
  - EHAL / Pattern B namespacing for multi-ESS (design reusable by **2.+1** multiple EV / Wallboxes)
  - Downstream: Loxone template XML gen and HouseSim scenario import should gain multi-battery support after this letter
  - Add two new EHAL values:
    - SOC-Min [%]
    - SOC-Max [%]
    - Add a check in HK whether these parameters shall be written by Earnie to configured value in house-config
      - When checked, the values are set to smarthome-backend
      - When not checked, values are taken into account for MILP


- [ ] improve prognosis for EV coming back (connecting for charging)
  - Take schedule from config as start
  - If scheduled time passed without connected EV calculate last possible start time for charging to fullfill ReadyAt condition - 1h buffer and take this as new internal connecting schedule.
  - Only skip charging completely when no new ReadyAt date was delivered bei smarthome-backend

- [ ] Prepare and execute a small study about saving potentials for 2.7.g and 2.7.h

- [ ] **2.7.g — Powerstation reserve for single-use manual devices** (`role: single_use`; depends on **2.7.c**; shares data model with **2.7.h**)
  - Idea: give each `earnie_role: manual` consumer (washing machine, dryer, …) a dedicated energy reserve inside the multi-ESS pool ("virtual powerstation"), pre-charged opportunistically in cheap slots and handed off whenever the device is actually switched on — instead of only showing a start-time recommendation (`optimizer/appliance_recommendation.py`, 1–5 star ranking) that the user must act on manually. Only feasible with at least one storage in the system. Worst case (reserve not sufficient) falls back to today's behaviour: grid draw, no regression.
  - Reuses the EV **SOC-Min-Sofort** pattern (`docs/konfiguration/flexible-verbraucher.md`, `optimizer/charging_urgent.py`) generalized from "reach X % SoC by `ready_by`" to "keep N kWh reserved, no deadline, ASAP-refill in cheap slots after each trigger" — new per-consumer reserve target (kWh) plus a state machine (empty → charging → standby/full → discharging on trigger → empty), not a single global `min_soc`.
  - Trigger detection: for consumers with `loxone_inputs.power_name` already configured, a threshold crossing on that existing power signal; for purely manual devices without a meter, the existing **Manuelle Geräte** app button stays the trigger.
  - Energy-per-run learning: use the `loxone_inputs.power_name` history (already read for `power_source: loxone`) to replace the fixed `default_power_kw` × `default_runtime_h` estimate over time; keep the manual value as fallback.
  - Multi-reserve prioritization (several manual devices charging reserves at once) deferred to **2.+1** — simple equal-share rule for v1 is enough, since the worst case stays grid draw either way; a later learned/heuristic priority is a pure refinement, not a blocker.
  - **Shared data model** (with **2.7.h**): `type: powerstation`, `backing: "virtual" | "physical"`, `attached_consumer_id`, `role: "single_use" | "standby_backup"` — this item implements `role: single_use`. Do **not** introduce a separate `batteries[].direction: one_way` flag; physical one-way storages (e.g. EcoFlow Delta 3) are `backing: physical` instances of this pattern.
  - **Physical (`backing: physical`) instance:** chargeable on command, handed off automatically to its one dedicated attached consumer without an explicit discharge command (hardware cannot feed the house grid). MILP must never plan a forced/automatic discharge and must not count their SoC as grid-offset capacity — normal case of the reserve pattern, not a separate exclusion rule. `set_ess_source_select` / island-mode is **optional** for this role (hard requirement only for **2.7.h**). Bonus: the storage's own power sensor (`sens_ess_power` / "Total Out Power", already bridged for the Delta 3) doubles as a free per-consumer meter for energy-per-run learning.
  - Spec write-up: `Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §3.4.1 in the `Earnie-Projekt` docs repo.

- [ ] **2.7.h — Powerstation smart standby-backup for continuous loads** (`role: standby_backup`; shares data model with **2.7.g**; depends on **2.7.c**, benefits from **2.7.g** landing first)
  - Idea: for consumers that run more or less continuously (PC, smart-home hub, router, NAS, …) — no single "run" event, no fixed energy-per-run — route their supply between grid and a pre-charged powerstation reserve on a rolling per-slot basis, driven by price: expensive slots draw from the reserve, cheap slots pass through from grid (optionally recharging the reserve in parallel). A price-aware mini-UPS, not just outage backup.
  - Unlike **2.7.g** (a reserve *target* reached ASAP and drawn down on a trigger), this is a rolling MILP **constraint** per slot — closer to the existing whole-house battery price-arbitrage logic than to the SOC-Min-Sofort pattern, and it needs `set_ess_source_select` as a **hard requirement**, not an optional refinement: Earnie must actively flip the attached consumer(s) between grid pass-through and battery-only island every time the price crosses the threshold.
  - Reserve sizing is power × number of expensive hours to bridge in the horizon, not an energy-per-run estimate — no energy-per-run learning needed here (unlike **2.7.g**).
  - **Virtual (main-ESS-backed) instance:** largely redundant with the existing whole-house price optimization — the only real addition is a *protected* minimum reserve carved out for these consumers so general house/export decisions can't draw it down. Needs a go/no-go: for a virtual powerstation, is a per-consumer floor worth it over simply raising the house battery's global `min_soc`?
  - **Physical (`backing: physical`) instance:** genuine new value as an independent, dedicated partial UPS — potentially outage resilience (grid/inverter failure) on top of price optimization, depending on hardware. Seamless (no-reboot) transfer switching is a per-device hardware capability to verify — not every powerstation switches sources without a brief interruption. Reference hardware: EcoFlow Delta 3 bridged HA `hassio-ecoflow-cloud` → Loxone (`docs/referenz/loxone-signals.md`).
  - **EHAL `set_ess_source_select`** (Write, enum `0` = grid / `1` = battery): routes locally-attached consumers between grid passthrough (storage may charge in parallel) and battery-only island supply (no grid draw, no charging); irrelevant/omit for bidirectional house ESS — needs `ehal.md` §Setpoint-API + `share/ehal/setpoint.schema.json` update (schema_version bump). Capability-Flag `supports_ess_source_select` in `share/ehal/capabilities.schema.json`.
  - **EcoFlow Delta 3 mapping:** HA switch `switch.<device>_grid_bypass` (internal key `ban_bypass_en`) maps 1:1 by boolean identity — switch ON = "grid bypass disabled" = battery-only = EHAL `1`; switch OFF = "grid bypass enabled" (charges from AC, loads pass through) = EHAL `0`. Verified against `hassio-ecoflow-cloud` source (`switch.py::BypassBanScalarSwitch`); note the field name itself is confusingly inverted. Existing HA-adapter `sign: ehal|negate` (`share/config/ehal.ha.snippet.json`) only covers **signed power fields** — boolean/enum fields need a separate invert convention when polarity does not line up.
  - **Bridging path** when Earnie stays on `ehal.backend=loxone` (no native HA southbound): Merker `Earnie_Speicher_Quellenwahl`, written by Earnie via `VI_Earnie_Plant.xml`-style poll, mirrored to HA via a Virtual-Output webhook — same pattern as `set_ess_charge_power_limit` in `docs/referenz/loxone-signals.md`.
  - Spec write-up: `Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §3.4.2 in the `Earnie-Projekt` docs repo.

- [ ] **2.7.e — Monitor charts — pan-to-load spike** (feasibility + usability → go/no-go; independent of **2.7.a–c** / **2.7.g–h**)
  - **Today:** display range depends on device (`ui/s2_viewport.py`: phone = 24 h segments, desktop/tablet = SA₀→SA₂). Charts get only the data of that default range. Panning with the Plotly drag/pan tool beyond it shows an empty chart. Navigation is via buttons / date picker (`ui/history_navigation.py`, `ui/s2_navigation.py`).
  - **Option A — pan-driven lazy loading:** panning replaces the nav buttons. Data for newly visible ranges is fetched step by step and appended to the charts.
  - **Option B — coupling:** keep the buttons, but sync them with the pan position (pan past the edge → switch segment/cycle; button → move the Plotly x-range). Optionally preload neighbouring segments (±1) so short pans never show empty areas.
  - **Feasibility to check:** Streamlit `st.plotly_chart` does not return `relayout` (x-range) events — only selections. Needs a custom component, `streamlit-plotly-events`-style bridge or a debounced rerun trigger. Check rerun cost/latency per pan, keeping all S-2 charts (flow, SoC, cumulative, consumer stack) on the same x-axis, zone/SA marker decorations outside the default range, and memory/load time on the Pi/Synology.
  - **Usability to check:** touch pan vs page scroll on phones, discoverability vs explicit buttons, behaviour at log start / live edge ("Heute"), loading indicator while data is fetched.
  - **Outcome:** short spike on a branch (prototype for one chart, then all), test on desktop + phone, then decide: A, B, preload-only, or keep status quo. Record decision here before any productive implementation.

- [ ] **2.7.i — Release regression suite (golden-master cases, public + private data)** (epic **Regression**; independent of **2.7.a–h**; spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md))
  - Goal: Earnie's behaviour must not change unnoticed between releases. Frozen inputs (config, consumption, prices, PV forecast, start state) → offline deterministic run → compact metrics → compare against committed golden. Runs **before a release / publish**, never per commit (pytest marker `regression`, deselected by default).
  - Data split: runner + synthetic/own cases in the public repo (`tests/regression/cases/`); customer cases in a **private repo** `Earnie-regression-private` (never in the public repo or its history). Public issues reference a case only by ID (`REG-<issue>-<slug>`); report records the SHA of the private repo.
  - Compare in three tiers: hard invariants (fail) → metrics with tolerance, default ±0.5 % (fail) → plan diff (info only). Intended changes re-record the golden via `--update-golden` with justification in the commit.
  - [ ] **Regression P1 — MVP:** case format + schema, runner for L1 (cycle replay) and L2 (backtest window), `--update-golden`, markdown report; 4–6 public cases (winter, summer, negative prices, EV deadline, heat storage); migrate the existing `tests/fixtures/prod_dumps/` cases; verify solver determinism (same case twice, two machines; CBC pinned); release-checklist item. Pre-check: existing public fixtures contain no entity names / location / third-party data.
  - [ ] **Regression P2 — customer data:** private repo + private-root support (skip when missing), `--intake` (debug-dump ZIP → case folder + ID), case-ID / issue-reference convention, SHAs in the report.
  - [ ] **Regression P3 — gate + scrub:** CI job `regression` before `promote` in `release-publish.yml` (deploy-key secret), whitelist-based scrubber for customer → public repro cases (names/IDs, location, GDPR consent note), optional metric trend across releases.
  - **Open decisions:** soft vs. hard gate (proposal: soft first); customer-facing data-handling wording beyond the private repo; CBC version identical on dev machine / Docker / CI.

### Version 2.+1 (maybe also part of 2.7?)

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
