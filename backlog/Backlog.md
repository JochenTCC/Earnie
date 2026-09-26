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

**Versioning note:** Official **2.5.3** ships the old Phase 1 (Options → `config.json` + Ingress; archived). Community channel: **`2.6.0-alpha.*`** on `main` (do not continue `2.5.3-alpha.N`). Alpha compose currently pins **`2.6.0-alpha.2`**.

**Next:** Live **H11** Gen2 check under **2.6.j** (verify → close without change, or **H11 (fix)** in the same chapter). In parallel **2.6.e**. Then **2.6.m**. **H0** ships with the publish after **2.6.m** (or path **B**/**C** then). Then **2.6.n** (battery controllability).

**Scope:** easier HA coupling for Earnie. HA entity IDs live on `plant` / `consumers[].ehal_bindings` (Pattern B, Loxone-parity HITL). The generic HA↔Loxone bridge stays under Research Items. Add-on 1.0 (Earnie publishing its own state) is deferred to **Version 2.+1**.

**Documents:**

- [House simulator spec](../docs/spec/house-sim.md) — HouseSim S1–S4 (archetypes, core, S4 integration)
- [HA compatibility tests (concept)](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument.md) — HouseSim S3 / **2.6.e** / **2.6.n**
- [Entwicklungsplan §3.2 HA entity mapping](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md) — **2.6.e** (confirm-before-save; LLM stays out of 2.6)
- [EHAL spec — Pattern B / Loxone HITL](../docs/spec/ehal.md) — same `plant` / `consumers[].ehal_bindings` as Loxone **2.4.k**
- [Installation hardening (concept)](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-Installation-Haertung-Entwicklungsdokument.md) — findings H0–H13, sprint plan, version channels — Sprint 1–4 = **2.6.j** / **2.6.k** / **2.6.l** / **2.6.m**
- [Add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md) — add-on packaging items; channel work is now **2.6.k**
- [Business backlog](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Business-Backlog.md) — Synology dogfood / HA coupling context
- [HA-Loxone-Bridge-Builder draft](HA-Loxone-Bridge-Builder-Draft.md) — research item, not 2.6

#### Installation hardening (Sprint 1–4 of the concept doc)

Trigger: support case 2026-09-25 (HA add-on crash loop on a `kvm64` VM, see [Backlog-Erledigt.md](Backlog-Erledigt.md)). IDs **H0–H13** refer to the [concept doc](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-Installation-Haertung-Entwicklungsdokument.md).

- [ ] **2.6.j — Sprint 1: quick safeguards + verification** (code done 2026-09-26; see [Backlog-Erledigt.md](Backlog-Erledigt.md))
  - [ ] **H0** Ship x86-64-v2 preflight with the **next** image publish after **2.6.m** (deferred; not required for community `2.6.0-alpha.2`)
  - [ ] **H11 (verify)** Gen2 Miniserver set to HTTPS-only vs. hard-coded `http://` in `integrations/loxone_client.py`
    - **Live checklist (leave open until run):** on Gen2 with Config → Network → „Nur verschlüsselt“ / HTTPS only: (1) `http://<ms-ip>/jdev/sps/status` (or any jdev Earnie uses); (2) `http://<ms-ip>/data/LoxAPP3.json`; (3) optional write path `http://<ms-ip>/dev/sps/io/...`. If all fail (timeout / connection refused / TLS redirect only) → confirm H11 and do **H11 (fix)** below. If HTTP still works → close H11 without code change.
  - [ ] **H11 (fix, only if verify confirms)** Configurable `http`/`https` for the Miniserver; pin the self-signed certificate by fingerprint instead of `verify=False`

- [ ] **2.6.m — Sprint 4: startup checks + runtime monitoring**
  - [ ] **H1** Extend `docker/cpu_check.sh` to `preflight.sh`: abort on non-writable data dir and on a clock before the image build date (wait briefly for NTP first); warn on RAM < 2 GB and < 500 MB free disk
  - [ ] **H4** `HEALTHCHECK` in `docker/Dockerfile` (`/_stcore/health`, add-on internal `:8502`) + daemon heartbeat in `runtime/`; add-on `watchdog:` URL; LoxBerry `healthcheck` evaluates `.State.Health.Status` (WARN on `unhealthy`)

#### Battery controllability

Trigger: HouseSim S2 archetype `huawei_en` (only charge/discharge limits, no active-power entity) and `fronius_de` (read-only). Today Earnie plans Zwangsladen / Zwangsentladen it cannot execute on such installs; since the function-completeness check (see [Backlog-Erledigt.md](Backlog-Erledigt.md) 2026-09-26) the active-power setpoint is skipped instead of degrading ESS writes, but the plan still assumes it.

- [ ] **2.6.n — Battery controllability in `house_config` + MILP**
  - [ ] **House config:** per battery `control: "full" | "limits_only" | "read_only"` (default `full`, backward compatible). Property of the installation, so simulation / backtesting / scenario comparison (business case) use it without a live adapter.
  - [ ] **MILP constraints:** `limits_only` → charge only from PV surplus, discharge only up to house load (no grid charging, no battery export); modes derived from the plan are only Automatik / Entladesperre. `read_only` → battery modelled as pure self-consumption, no setpoints.
  - [ ] **Cross-check with the mapping:** warn in EHAL-Com / Live when `control` says more than the bound functions allow (`ehal.functions`: `ess_limits`, `ess_active`), e.g. `full` without `set_ess_active_power`.
  - [ ] **Deviation evaluation:** `deviation_eval` must not expect forced modes on `limits_only` / `read_only`.
  - [ ] **Decision: Huawei forcible charge via HA service.** `huawei_solar` offers force charge/discharge only as a service (plus `storage_power_of_charge_from_grid` / working mode `select`). Evaluate whether the HA adapter should call such vendor services, which would make Huawei `full` again — decides how many users the `limits_only` restriction really hits.
  - [ ] Tests on HouseSim archetypes `huawei_en` (limits only) and `fronius_de` (read-only); docs `ehal.md`, `ehal-com.md`, house-config docs.

#### HA mapping proposals

- [ ] **2.6.e — Stronger propose, still confirm-before-save.** Replay the HouseSim archetypes with an empty Pattern B map and vendor-style names. Obvious fields proposed; ambiguous or `switch.*` cases left empty. Optional LLM stays out (same status as Loxone MCP in [Entwicklungsplan §3.1](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md)). Empty-only propose rules apply to Pattern B bindings.
  - Prerequisites done 2026-09-26: HouseSim S2 archetypes; physical-quantity filter in `heuristic_propose` (see [Backlog-Erledigt.md](Backlog-Erledigt.md)). HouseSim S3 is not a prerequisite — archetypes replay directly in pytest.
  - Baseline (correct / golden fields): `evcc_en` 13/13, `fronius_de` 3/9, `huawei_en` 0/11, `sma_keba` 3/9; no wrong-quantity proposals.
  - [ ] Name recognition for vendor vocabularies, e.g. "state of capacity" → SoC, `power_meter` → grid, `nrg_11` / `charging_power` → wallbox, German Fronius names (`leistung_netz`, `ladezustand`), `metering_total_absorbed` / `…_yield` → grid energy.
  - [ ] Target (pytest over all archetypes): **no wrong proposal** on any field; unambiguous fields hit; leaving a field empty is fine, a wrong binding is not. Known distractors (`inverter_active_power`, SMA `…_grid_power`, Fronius `leistung_verbrauch`) must not be proposed.

### Version 2.7 — Multiple storages and export power limitation

#### Features

- [ ] Limiting exporting power as new setting value. In addition to manipulate battery working mode it should also be possible to limit the power exported to the grid.    
  - See how this is done in HA / evcc and openEMS as "best practice
  - Define new EHAL standard value (set_*) for limiting power
  - Add new VI to Loxone VI Template
  - Add new templates to HA binding if appropriate
  - Implement mapping in Loxone productive config (Jochen)
  - Use control value for these purposes:
    1. User can set new parameter on house configuration as max power that is allowed to be exported (constant value)
    2. MILP can use it to prevent exporting when dynamic exporting tariffs are positive (user must pay to export power)
    3. Limitation comes from grid (externally - new EHAL value as input to Earnie) and is used solely as additional variable constraint that overrides the static parameter setting
    4. MILP has to take limitation coming from setting or external as constraint for optimization
    limitation from different sources must be treated in a useful prioritization (MILP-limit - than internal limit - than external limit)
- [ ] Enable multiple isolated battery or battery+Inverter entities
  - Isolated battery modes: charging / discharging / standby
  - batt+inverter modes: optimizing / charging / discharging
  - All batteries are parts of optimization
  - **One-Way storage type** (e.g. EcoFlow Delta 3 bridged HA `hassio-ecoflow-cloud` → Loxone, see `docs/referenz/loxone-signals.md`): chargeable on command, **not** dischargeable on command, **cannot** feed the house grid
    - New component classification `batteries[].direction: "bidirectional" | "one_way"` in `components.json` schema (default `bidirectional`, backward compatible); MILP must never plan a forced/automatic discharge for `one_way` batteries and must not count their SoC as grid-offset capacity
    - New EHAL Setpoint field `set_ess_source_select` (Write, enum `0` = grid / `1` = battery): routes locally-attached consumers on a one-way storage between grid passthrough (storage may charge in parallel) and battery-only island supply (no grid draw, no charging); irrelevant/omit for bidirectional ESS — needs `ehal.md` §Setpoint-API + `share/ehal/setpoint.schema.json` update (schema_version bump)
    - New Capability-Flag `supports_ess_source_select` in `share/ehal/capabilities.schema.json`
    - Feasibility confirmed for EcoFlow Delta 3: HA switch `switch.<device>_grid_bypass` (internal key `ban_bypass_en`) maps 1:1 by boolean identity — switch ON = "grid bypass disabled" = battery-only = EHAL `1`; switch OFF = "grid bypass enabled" (charges from AC, loads pass through) = EHAL `0`. Verified against `hassio-ecoflow-cloud` source (`switch.py::BypassBanScalarSwitch`); note the field name itself is confusingly inverted
    - Schema note: existing HA-adapter `sign: ehal|negate` convention (`share/config/ehal.ha.snippet.json`) only covers **signed power fields**; a boolean/enum field needs a separate invert convention for devices whose polarity doesn't happen to line up
    - Bridging path when Earnie stays on `ehal.backend=loxone` (no native HA southbound): Merker `Earnie_Speicher_Quellenwahl`, written by Earnie via `VI_Earnie_Plant.xml`-style poll, mirrored to HA via a Virtual-Output webhook — same pattern as `set_ess_charge_power_limit` in `docs/referenz/loxone-signals.md`


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
- [ ] **Thermals P2** — Coupled single-node models
  - House ↔ heat storage ↔ solar system
  - House parameters from energy certificate (`EXAMPLE:/local/reference/energy-certificate.pdf` — not in repo)
  - Prepare air conditioning as thermal consumer
  - Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)
- [ ] **Thermals P3** — Thermal parameter adaptation (on Adaptation P1)
  - `heat_loss_kw_per_k` and further linear model parameters; horizon per consumer (24 h / 1 year)
- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)
- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)


### Version 2.+1 - Improvements for HA HouseSim

**Naming:** simulator stages are **HouseSim S1–S4** (formerly "HA Lab P1–P4"). **HA Lab** now means only the `ha_lab/` Compose stack (Earnie + HAOS + evcc, [ha-lab-setup.md](../docs/spec/ha-lab-setup.md)).

- [ ] **HouseSim S3** — CI harness: short simulated windows, not N live `main.py` days. Load each archetype → golden map → `HaAdapter` → check criteria of concept doc §3.5 (setpoint effect on next read, degrade on write errors, SoC/PV/temperature in a plausible band) for **all** archetypes; the static 2.6.a fixture stays the fast job. Diagnose-JSON → fixture converter only when support needs it.
- [ ] **HouseSim wallbox write-back** — Wallbox setpoints act on the simulated physics instead of only the scenario override: `set_evcs_max_current` / mode writes (go-e / Wattpilot `amp` + `frc`, evcc `max_current` + enable) → charge power = current × voltage × phases while an EV is connected (`car_arrives` / `car_leaves`), capped by the EV's acceptance. Mock REST (S1–S3) and S4 integration; tests on `evcc_en`, `fronius_de`, `huawei_en` (`sma_keba` stays the read-only wallbox case). Prerequisite for **HouseSim scenario import**.
- [ ] **HouseSim scenario import** (idea, after wallbox write-back) — S4 config flow reads a finished Earnie scenario (`house_config` with consumers, PV, batteries) and builds the simulated house from it: one device per configured component with a matching archetype, physics parameters from the scenario instead of manual `house_params`. Consumers beyond battery + PV need their physics in the core first (wallbox: item above; heat pump: open). Concept doc §5 S4 „optional später“.


### Version 2.+1 - Enhance Loxone Auto Binding functionality

- [ ] When importing from existing Loxone config is working the other way round would also be possible:
    - User has a complete HK with live scenario in place in Earnie
    - Earnie generates pre-filled Loxone Template XML files (with correct ids, (multiple) evs, (multiple) consumers) for importing into Loxone config.


### Version 2.+1 - POC for EEG-ready Earnie

Main Goal of this version is to get a proof-of-concept for an evolved Earnie that is able to optimize EEGs (Energie-Erzeuger-Gemeinschaft)
- See Entwicklungsplan\eeg-earnie-recherche-zusammenfassung.md for current research
- [ ] Implement a POC for EEG simulation


### Version 2.+1

- [ ] Enable multiple EV / Wallboxes
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
- [ ] Add possibility to simulate restrictions for energy export dependent on current grid situation in SE (and maybe in Live optimization)


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)
