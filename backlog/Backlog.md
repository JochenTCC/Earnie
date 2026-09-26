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

**Versioning note:** Official **2.5.3** ships the old Phase 1 (Options → `config.json` + Ingress; archived). Community channel: **`2.6.0-alpha.*`** on `main` (do not continue `2.5.3-alpha.N`). Alpha compose currently pins **`2.6.0-alpha.5`**.

**Next:** Version **2.6** feature letters done (through **2.6.n**). Next: **2.6.r re-check** (open below) → community/official publish as needed, then **2.7** (**2.7.a** … **2.7.e** on `feature/2.7`).

#### 2.6.r re-check — final pre-official quality gate (2026-09-26)

Completed steps (coverage, dead-code, KPI, docs, simplify) → [Backlog-Erledigt.md](Backlog-Erledigt.md) (`2.6.r re-check`).

- [ ] **2.6.r re-check** on `main` @ `64b151c` (+ local remediations; no `version.py` bump)
  - [ ] SonarCloud snapshot — pre-fix QG **ERROR** (`new_reliability_rating` C, `new_security_rating` C, `new_coverage` 66%); remediations applied locally (await push + analysis):
    - Fixed: `python:S1244` float eq in `integrations/ha_units.py` (new bug)
    - Fixed: SHA-pin Actions in `release-publish.yml` + `qemu-image-smoke.yml`; job-level permissions (S8233)
    - Fixed: path/URL hardening in `scripts/report_repo_stats.py` (S8707 / S8703)
    - Ignore (agentic LLM CLI noise): `pythonsecurity:S8707` + `S8705` via `sonar.issue.ignore.multicriteria` in `sonar-project.properties` (+ optional `python -m scripts.sonar_ignore_llm_cli_rules` with `SONAR_TOKEN` to mirror in SonarCloud UI/API)
    - Fixed: `docker/Dockerfile` explicit COPY (S6470) + tighter `.dockerignore`; `remote_backtesting_support` share-root validation (S2083)
    - Marked intentional: mock REST HTTP (`house_sim/mock_rest.py`), HA add-on root (`docker:S6471` NOSONAR)
    - Still open / accept: `pip install -r requirements.txt` S8541/S8544 (local `.` package cannot use `--only-binary=:all:`); library sinks if ignore does not apply until next scan; Sonar `new_coverage` 66% (informational — do not chase as in-gate)

**Scope:** easier HA coupling for Earnie. HA entity IDs live on `plant` / `consumers[].ehal_bindings` (Pattern B, Loxone-parity HITL). The generic HA↔Loxone bridge stays under Research Items. Add-on 1.0 (Earnie publishing its own state) is deferred to **Version 2.+1**.

**Documents:**

- [House simulator spec](../docs/spec/house-sim.md) — HouseSim S1–S4 (archetypes, core, S4 integration)
- [EHAL spec — Pattern B / Loxone HITL](../docs/spec/ehal.md) — same `plant` / `consumers[].ehal_bindings` as Loxone **2.4.k**
- [Add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md) — add-on packaging items; channel work is now **2.6.k**

- [ ] Manual Todo: Review updated docs (at least German ones)
- [ ] Update documents in Earnie-Projekt repo with current achievements / already implemented features

### Version 2.7 — Multiple storages and export power limitation

**Order:** **2.7.a** → **2.7.b** → **2.7.c** → **2.7.d** → **2.7.e**. Work on branch `feature/2.7` until official **2.6** is cut; merge after. Do not bump `version.py` to 2.7 until approved post-2.6.

- [ ] **2.7.a — Export power limitation** (Live / MILP / EHAL; HK static cap)
  - In addition to battery working mode, limit power exported to the grid.
  - See how this is done in HA / evcc and OpenEMS as “best practice”.
  - **Hard ceilings (kW):** effective export cap = `min` of all active sources (missing source = no cap from that source):
    1. **Internal (HK):** user parameter — max export power allowed (constant)
    2. **External (grid → Earnie):** new EHAL **inbound** field (`sens_*` / `get_*`, not `set_*`) — variable grid-side limit
    3. MILP must respect the effective cap as a constraint
  - **Soft / economic (not a kW cap):** when dynamic export tariffs are positive (user pays to export), MILP objective should prefer avoiding export — separate from the hard ceiling above.
  - Optional outbound EHAL `set_*` only if Earnie must command an inverter/feed-in limit southbound; otherwise Live enforces via ESS/mode + MILP only.
  - Add VI to Loxone VI template; HA binding templates if appropriate; mapping in Loxone productive config (Jochen).
  - **Follow-up (not this letter):** SE / grid-situation export restriction sim → **2.+1** item (consumes **2.7.a** model).

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


### Version 2.+1 - Improvements for HA HouseSim

**Naming:** simulator stages are **HouseSim S1–S4** (formerly "HA Lab P1–P4"). **HA Lab** now means only the `ha_lab/` Compose stack (Earnie + HAOS + evcc, [ha-lab-setup.md](../docs/spec/ha-lab-setup.md)).

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
- [ ] **Data & tariff fidelity - Part 2**
  - Keep official EPEX unconnected unless a paid/internal use case appears
  - Check possibilities to automatic tariffs.json update to existing installations
- [ ] Check possibilities to show decimal numbers according to regional settings (e.g. use "," as decimal sign for Germany)
- [ ] Simulate restrictions for energy export dependent on current grid situation in SE (and maybe Live) — **after 2.7.a** (consumes Live/MILP/EHAL export-cap model; do not redefine caps here)



### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)
