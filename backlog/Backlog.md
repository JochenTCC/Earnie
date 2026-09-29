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

**Versioning note:** Official **2.5.3** ships the old Phase 1 (Options → `config.json` + Ingress; archived). Community channel: **`2.6.0-alpha.*`** on `main` (do not continue `2.5.3-alpha.N`). Alpha compose currently pins **`2.6.0-alpha.7`**. This branch keeps `version.py` at **`2.7.0-dev`** until post-2.6 approval.

**Next:** **2.6.o** recorder is on `main` (Prod feed dogfooding). Finish **2.6.r re-check** / community/official publish on `main` as needed. On this branch: **2.7.f** Shadow client first, then **2.7.a** dogfood … **2.7.e**.

#### 2.6.o — Shadow Mode S1: Prod feed recorder (before 2.6.r finish)

Spec: [`docs/spec/shadow-mode.md`](../docs/spec/shadow-mode.md) (Epic **Shadow**; S1 only here). Must ship in a **2.6** Prod build so Dev can later feed Shadow during **2.7**. Implemented on `main` (`v2.6.0-alpha.7`); leave open here until archived from `main` backlog.

- [ ] **2.6.o — Shadow Mode S1 (Prod recorder)**
  - Opt-in `"shadow_feed_enabled": true` (+ optional `"shadow_feed_retention_days"`, default 14) in Prod `local_settings.json`; default off; ignored + warning if `EARNIE_SHADOW=1`
  - Record raw backend responses at transport primitives (Loxone `fetch_loxone_raw_value` / `_fetch_loxone_io_all`, HA `HaAdapter._get_json`, OpenEMS GET, `ext:pv_forecast` / prices / outdoor, optimize-trigger events) — no secrets/auth in records
  - Feed layout under `{config_dir}/shadow_feed/` (`meta.json`, atomic `latest.json`, daily JSONL + retention); override `EARNIE_SHADOW_FEED_PATH`
  - Superset after cycle writes (soft-fail, ≤10 s budget): **HA default = config-referenced entities only** (not full `/api/states`); Loxone IOs / OpenEMS channels from shared bindings
  - Failure isolation: recorder never breaks Prod (wrap + rate-limited warnings)
  - Tests: per-primitive ok/error, no secrets, atomic `latest.json`, JSONL rotation/retention, recorder exception does not break `main()`
  - **Not in this letter:** Shadow replay / write block / UI / seed (**2.7.f**); Soll/Soll diff & offline JSONL replay (S4 → **2.+1**)

#### 2.6.r re-check — final pre-official quality gate (2026-09-26)

Completed steps (coverage, dead-code, KPI, docs, simplify) → [Backlog-Erledigt.md](Backlog-Erledigt.md) (`2.6.r re-check`).

- [ ] **2.6.r re-check** on `main` (Sonar CI unblock + QG remediations; no `version.py` bump)
  - [ ] SonarCloud snapshot — pre-fix QG **ERROR** (`new_reliability_rating` C, `new_security_rating` C, `new_coverage` 66%); last successful analysis was pre-remediation `@271a6a3`. CI red cause: pytest failed before scan (UNC share-root validation). Fixes on `main` awaiting analysis:
    - Fixed: CI blocker — accept Windows UNC + POSIX absolute `share_root` / `remote_share_root` on Linux runners (`scripts/remote_backtesting_support.py`); NOSONAR on post-`_safe_join` sinks (S2083 / S6549)
    - Fixed: `python:S1244` float eq in `integrations/ha_units.py` (new bug)
    - Fixed: `python:S1764` NaN check in `house_config/known_chart_display.py` (`math.isnan`)
    - Fixed: SHA-pin Actions in `release-publish.yml` + `qemu-image-smoke.yml`; job-level permissions (S8233)
    - Fixed: path/URL hardening in `scripts/report_repo_stats.py` (S8707 / S8703)
    - Fixed: `docker/Dockerfile` explicit COPY (S6470) + tighter `.dockerignore`
    - Ignore (sonar-project.properties multicriteria): LLM CLI S8707/S8705; pip unlock S8541/S8544 (local `.` package); lockfile S8565; container root S6471; Loxone/lab HTTP S5332
    - Marked intentional: mock REST HTTP (`house_sim/mock_rest.py`), HA add-on root (comment NOSONAR; inline on `FROM` breaks BuildKit)
    - Still open / accept: Sonar `new_coverage` 66% (informational — do not chase as in-gate); QG may stay ERROR on coverage alone until gate policy is relaxed in SonarCloud UI

**Scope:** easier HA coupling for Earnie. HA entity IDs live on `plant` / `consumers[].ehal_bindings` (Pattern B, Loxone-parity HITL). The generic HA↔Loxone bridge stays under Research Items. Add-on 1.0 (Earnie publishing its own state) is deferred to **Version 2.+1**.

**Documents:**

- [House simulator spec](../docs/spec/house-sim.md) — HouseSim S1–S4 (archetypes, core, S4 integration)
- [EHAL spec — Pattern B / Loxone HITL](../docs/spec/ehal.md) — same `plant` / `consumers[].ehal_bindings` as Loxone **2.4.k**
- [Add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md) — add-on packaging items; channel work is now **2.6.k**

- [ ] Manual Todo: Review updated docs (at least German ones)
- [ ] Update documents in Earnie-Projekt repo with current achievements / already implemented features

### Version 2.7 — Multiple storages and export power limitation

**Order:** **2.7.f** → **2.7.a** dogfood → **2.7.b** → **2.7.c** → **2.7.d** → **2.7.g** → **2.7.h** → **2.7.e**. Work on branch `feature/2.7` until official **2.6** is cut; merge after. Do not bump `version.py` to 2.7 until approved post-2.6. **2.7.f** first so Shadow can dogfood the rest of 2.7 against Prod with **2.6.o** feed.

- [ ] **2.7.f — Shadow Mode S2+S3: Dev client** (depends on Prod running **2.6.o** recorder)
  - Spec: [`docs/spec/shadow-mode.md`](../docs/spec/shadow-mode.md) — `EARNIE_SHADOW=1` only (`runtime_store.shadow.is_shadow_mode()`); implies silent; never a config key
  - **S2:** transport replay (§6.1–6.2), central write block + `shadow_writes.jsonl` (§6.3), config read-only / skip load-time migrations that write (§6.4), startup checks (§4.2), release guard (§4.4); own mandatory runtime dir + optional `scripts.shadow_seed_runtime`
  - Accept Prod’s `earnie_data_model` if in `COMPATIBLE_DATA_MODELS`; never migrate/re-stamp shared config. No Shadow `config_overlay` in v1 (Prod-rejected keys not testable)
  - **S3:** UI banner + feed health + would-write table; `EARNIE_UI_STREAMLIT_PORT`; German user docs (`docs/einrichtung/`) + `DEVELOPER.md`
  - Tests per spec §10; E2E with HouseSim as Prod backend
  - **Out of scope:** S4 Soll/Soll diff + offline JSONL backtest → **2.+1**; Shadow as 2nd HA add-on (scenario C)

- [ ] **2.7.a dogfood — Loxone productive + live test** (code done → [Erledigt](Backlog-Erledigt.md); after **2.7.f** preferred for Shadow dogfood)
  - Wire export-limit Merker / VI–VO in the productive Loxone config (`set_grid_export_power_limit`, optional inbound `get_grid_export_power_limit`; Einspeisesperre = limit `0`, `set_ess_mode` stays battery-only)
  - Bind in EHAL-Com; set a HK `plant.max_export_power_kw` and verify Live writes + MILP respect the cap
  - Live-test: static HK cap, inbound grid limit override, pay-to-export soft behaviour, release (unconstrained = PV kWp sum + battery max discharge kW)

- [ ] **2.7.b — Thermals P2** — Coupled single-node models
  - House ↔ heat storage ↔ solar system
  - House parameters from energy certificate (`EXAMPLE:/local/reference/energy-certificate.pdf` — not in repo)
  - Prepare air conditioning as thermal consumer
  - Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)
  - **Note:** Epic continues under **2.+1** (**Thermals P3**, heat pump Prio3 after **Thermals P2** / **2.7.b**). Heat storage here is thermal, not ESS multi-storage (**2.7.c**/**2.7.d**).

- [ ] **2.7.c — Multiple isolated battery / battery+inverter entities** (bidirectional)
  - Isolated battery modes: charging / discharging / standby
  - batt+inverter modes: optimizing / charging / discharging
  - All batteries participate in optimization
  - **Export limit "unconstrained" value (from 2.7.a):** `live_unconstrained_export_kw()` in `optimizer/live_export_limit.py` writes PV kWp sum + max discharge of the single battery (only when `battery_control = full`). With multi-ESS, sum the max discharge power of **every** battery that supports forced discharge (skip `limits_only` / `read_only` / one-way storages from **2.7.d**); update `docs/spec/ehal.md` + `docs/einrichtung/loxone-anbindung.md` accordingly
  - EHAL / Pattern B namespacing for multi-ESS (design reusable by **2.+1** multiple EV / Wallboxes)
  - Downstream: Loxone template XML gen and HouseSim scenario import should gain multi-battery support after this letter

- [ ] **2.7.d — One-way storage type** (depends on **2.7.c**)
  - E.g. EcoFlow Delta 3 bridged HA `hassio-ecoflow-cloud` → Loxone, see `docs/referenz/loxone-signals.md`: chargeable on command, **not** dischargeable on command, **cannot** feed the house grid
  - New component classification `batteries[].direction: "bidirectional" | "one_way"` in `components.json` schema (default `bidirectional`, backward compatible); MILP must never plan a forced/automatic discharge for `one_way` batteries and must not count their SoC as grid-offset capacity
  - New EHAL Setpoint field `set_ess_source_select` (Write, enum `0` = grid / `1` = battery): routes locally-attached consumers on a one-way storage between grid passthrough (storage may charge in parallel) and battery-only island supply (no grid draw, no charging); irrelevant/omit for bidirectional ESS — needs `ehal.md` §Setpoint-API + `share/ehal/setpoint.schema.json` update (schema_version bump)
  - New Capability-Flag `supports_ess_source_select` in `share/ehal/capabilities.schema.json`
  - Feasibility confirmed for EcoFlow Delta 3: HA switch `switch.<device>_grid_bypass` (internal key `ban_bypass_en`) maps 1:1 by boolean identity — switch ON = "grid bypass disabled" = battery-only = EHAL `1`; switch OFF = "grid bypass enabled" (charges from AC, loads pass through) = EHAL `0`. Verified against `hassio-ecoflow-cloud` source (`switch.py::BypassBanScalarSwitch`); note the field name itself is confusingly inverted
  - Schema note: existing HA-adapter `sign: ehal|negate` convention (`share/config/ehal.ha.snippet.json`) only covers **signed power fields**; a boolean/enum field needs a separate invert convention for devices whose polarity doesn't happen to line up
  - Bridging path when Earnie stays on `ehal.backend=loxone` (no native HA southbound): Merker `Earnie_Speicher_Quellenwahl`, written by Earnie via `VI_Earnie_Plant.xml`-style poll, mirrored to HA via a Virtual-Output webhook — same pattern as `set_ess_charge_power_limit` in `docs/referenz/loxone-signals.md`

- [ ] **2.7.g — Powerstation reserve for single-use manual devices** (supersedes parts of **2.7.d**; depends on **2.7.c**; shares data model with **2.7.h**)
  - Idea: give each `earnie_role: manual` consumer (washing machine, dryer, …) a dedicated energy reserve inside the multi-ESS pool ("virtual powerstation"), pre-charged opportunistically in cheap slots and handed off whenever the device is actually switched on — instead of only showing a start-time recommendation (`optimizer/appliance_recommendation.py`, 1–5 star ranking) that the user must act on manually. Only feasible with at least one storage in the system. Worst case (reserve not sufficient) falls back to today's behaviour: grid draw, no regression.
  - Reuses the EV **SOC-Min-Sofort** pattern (`docs/konfiguration/flexible-verbraucher.md`, `optimizer/charging_urgent.py`) generalized from "reach X % SoC by `ready_by`" to "keep N kWh reserved, no deadline, ASAP-refill in cheap slots after each trigger" — new per-consumer reserve target (kWh) plus a state machine (empty → charging → standby/full → discharging on trigger → empty), not a single global `min_soc`.
  - Trigger detection: for consumers with `loxone_inputs.power_name` already configured, a threshold crossing on that existing power signal; for purely manual devices without a meter, the existing **Manuelle Geräte** app button stays the trigger.
  - Energy-per-run learning: use the `loxone_inputs.power_name` history (already read for `power_source: loxone`) to replace the fixed `default_power_kw` × `default_runtime_h` estimate over time; keep the manual value as fallback.
  - Multi-reserve prioritization (several manual devices charging reserves at once) deferred to **2.+1** — simple equal-share rule for v1 is enough, since the worst case stays grid draw either way; a later learned/heuristic priority is a pure refinement, not a blocker.
  - **Converges with 2.7.d:** a real one-way storage (e.g. EcoFlow Delta 3) *is* a physical instance of this same reserve pattern — chargeable on command, handed off automatically to its one dedicated attached consumer without ever needing an explicit discharge command. That covers 2.7.d's core requirement ("MILP must never plan a forced/automatic discharge for `one_way` batteries") as the normal case of the reserve pattern rather than a separate exclusion rule, and makes `set_ess_source_select` / island-mode optional for **this role** (still a hard requirement for the standby-backup role, see **2.7.h**) instead of a blanket 2.7.d blocker. Bonus: the one-way storage's own power sensor (`sens_ess_power` / "Total Out Power", already bridged for the Delta 3) doubles as a free per-consumer meter, feeding the energy-per-run learning above without a separate Loxone power merker.
  - **Recommendation:** fold `batteries[].direction: "bidirectional" | "one_way"` from **2.7.d** into a shared reserve/powerstation model with a `role` field (`type: powerstation`, `backing: "virtual" | "physical"`, `attached_consumer_id`, `role: "single_use" | "standby_backup"` — this item implements `role: single_use`, **2.7.h** implements `role: standby_backup`) instead of maintaining three separate concepts (SOC-Min-Sofort-style reserve for virtual/single-use, `direction: one_way` for physical, an as-yet-undefined price-switch constraint for standby-backup).
  - Spec write-up: `Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §3.4.1 in the `Earnie-Projekt` docs repo.

- [ ] **2.7.h — Powerstation smart standby-backup for continuous loads** (`role: standby_backup`; shares data model with **2.7.g**; depends on **2.7.c**, benefits from **2.7.g** landing first)
  - Idea: for consumers that run more or less continuously (PC, smart-home hub, router, NAS, …) — no single "run" event, no fixed energy-per-run — route their supply between grid and a pre-charged powerstation reserve on a rolling per-slot basis, driven by price: expensive slots draw from the reserve, cheap slots pass through from grid (optionally recharging the reserve in parallel). A price-aware mini-UPS, not just outage backup.
  - Unlike **2.7.g** (a reserve *target* reached ASAP and drawn down on a trigger), this is a rolling MILP **constraint** per slot — closer to the existing whole-house battery price-arbitrage logic than to the SOC-Min-Sofort pattern, and it needs `set_ess_source_select` as a **hard requirement**, not an optional refinement: Earnie must actively flip the attached consumer(s) between grid pass-through and battery-only island every time the price crosses the threshold.
  - Reserve sizing is power × number of expensive hours to bridge in the horizon, not an energy-per-run estimate — no energy-per-run learning needed here (unlike **2.7.g**).
  - **Virtual (main-ESS-backed) instance:** largely redundant with the existing whole-house price optimization — the only real addition is a *protected* minimum reserve carved out for these consumers so general house/export decisions can't draw it down. Needs a go/no-go: for a virtual powerstation, is a per-consumer floor worth it over simply raising the house battery's global `min_soc`?
  - **Physical (one-way storage) instance:** genuine new value as an independent, dedicated partial UPS — potentially outage resilience (grid/inverter failure) on top of price optimization, depending on hardware. Seamless (no-reboot) transfer switching is a per-device hardware capability to verify — not every powerstation switches sources without a brief interruption.
  - Spec write-up: `Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §3.4.2 in the `Earnie-Projekt` docs repo.

- [ ] **2.7.e — Monitor charts — pan-to-load spike** (feasibility + usability → go/no-go; independent of **2.7.a–d**)
  - **Today:** display range depends on device (`ui/s2_viewport.py`: phone = 24 h segments, desktop/tablet = SA₀→SA₂). Charts get only the data of that default range. Panning with the Plotly drag/pan tool beyond it shows an empty chart. Navigation is via buttons / date picker (`ui/history_navigation.py`, `ui/s2_navigation.py`).
  - **Option A — pan-driven lazy loading:** panning replaces the nav buttons. Data for newly visible ranges is fetched step by step and appended to the charts.
  - **Option B — coupling:** keep the buttons, but sync them with the pan position (pan past the edge → switch segment/cycle; button → move the Plotly x-range). Optionally preload neighbouring segments (±1) so short pans never show empty areas.
  - **Feasibility to check:** Streamlit `st.plotly_chart` does not return `relayout` (x-range) events — only selections. Needs a custom component, `streamlit-plotly-events`-style bridge or a debounced rerun trigger. Check rerun cost/latency per pan, keeping all S-2 charts (flow, SoC, cumulative, consumer stack) on the same x-axis, zone/SA marker decorations outside the default range, and memory/load time on the Pi/Synology.
  - **Usability to check:** touch pan vs page scroll on phones, discoverability vs explicit buttons, behaviour at log start / live edge ("Heute"), loading indicator while data is fetched.
  - **Outcome:** short spike on a branch (prototype for one chart, then all), test on desktop + phone, then decide: A, B, preload-only, or keep status quo. Record decision here before any productive implementation.


### Version 2.+1 — Introducing nested data models / Epics **Adaptation** & **Thermals** (architecture first)

- [ ] Optimize Pool temperature to a certain value on time. Set desired temperature and using time. Combine it with RC model
  - Add a chart that shows comparison between actual and modeled temperature (including ambient temperature and heating activity)
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
  - `heat_loss_kw_per_k` and further linear model parameters; horizon per consumer (24 h / 1 year)
- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)
- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2** / **2.7.b**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)


### Version 2.+1 - Improvements for HA (HouseSim)

**Naming:** simulator stages are **HouseSim S1–S4** (formerly "HA Lab P1–P4"). **HA Lab** now means only the `ha_lab/` Compose stack (Earnie + HAOS + evcc, [ha-lab-setup.md](../docs/spec/ha-lab-setup.md)).

- [ ] Add possibility to take PV prognosis directly from HA when available
- [ ] **HouseSim S3** — CI harness: short simulated windows, not N live `main.py` days. Load each archetype → golden map → `HaAdapter` → check criteria of concept doc §3.5 (setpoint effect on next read, degrade on write errors, SoC/PV/temperature in a plausible band) for **all** archetypes; the static 2.6.a fixture stays the fast job. Diagnose-JSON → fixture converter only when support needs it.
- [ ] **HouseSim wallbox write-back** — Wallbox setpoints act on the simulated physics instead of only the scenario override: `set_evcs_max_current` / mode writes (go-e / Wattpilot `amp` + `frc`, evcc `max_current` + enable) → charge power = current × voltage × phases while an EV is connected (`car_arrives` / `car_leaves`), capped by the EV's acceptance. Mock REST (S1–S3) and S4 integration; tests on `evcc_en`, `fronius_de`, `huawei_en` (`sma_keba` stays the read-only wallbox case). Prerequisite for **HouseSim scenario import**.
- [ ] **HouseSim scenario import** (idea, after wallbox write-back; prefers **2.7.c**/**2.7.d** multi-/one-way ESS model) — S4 config flow reads a finished Earnie scenario (`house_config` with consumers, PV, batteries) and builds the simulated house from it: one device per configured component with a matching archetype, physics parameters from the scenario instead of manual `house_params`. Consumers beyond battery + PV need their physics in the core first (wallbox: item above; heat pump: open). Concept doc §5 S4 „optional später“.


### Version 2.+1 - Enhance Loxone Auto Binding functionality

- [ ] When importing from existing Loxone config is working the other way round would also be possible:
    - User has a complete HK with live scenario in place in Earnie
    - Earnie generates pre-filled Loxone Template XML files (with correct ids, (multiple) evs, (multiple) consumers, **(multiple) batteries after 2.7.c**) for importing into Loxone config.


### Version 2.+1 - POC for EEG-ready Earnie

Main Goal of this version is to get a proof-of-concept for an evolved Earnie that is able to optimize EEGs (Energie-Erzeuger-Gemeinschaft)
- See Entwicklungsplan\eeg-earnie-recherche-zusammenfassung.md for current research
- [ ] Implement a POC for EEG simulation *(benefits from **2.7.a** export-limit model and **2.7.c** multi-ESS)*


### Version 2.+1

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


### Version 2.+1 — Add-on Version 1.0 (Earnie northbound state)

Deferred from the **2.6** HA-coupling cycle. Prefer after southbound mapping UX is usable (**2.6.h**). Not the separate item “EHAL adaptation for MQTT” below.

- [ ] **Add-on Version 1.0.** From the [add-on plan](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie_HomeAssistant_Addon_Dokumentation.md): MQTT Discovery, native Home Assistant entities for Earnie state, HA Energy-dashboard integration, Supervisor health check. Earnie publishing its own state. Checked on the existing Synology HAOS. Stable vs pre-release install is the [add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md), not this item.


### Version 2.+1

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
