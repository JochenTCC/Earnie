# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **HA-Loxone-Bridge-Builder:** standalone tool (no Earnie/EHAL runtime dependency) to auto-generate HA `rest_command:`/`automation:` YAML for numeric HA→Loxone writes. Design draft: [backlog/HA-Loxone-Bridge-Builder-Draft.md](HA-Loxone-Bridge-Builder-Draft.md). **Not part of Version 2.6.** A different audience (any HA+Loxone install). Do not share code with **2.6.b** / **2.6.e** (those map HA entities onto a fixed EHAL vocabulary inside Earnie). Deferred Loxone Virtual-In/Out XML in the draft is also not the Version 2.+1 “Earnie → Loxone template XML” item.
- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account
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


## Feature Backlog

### Version 2.6 - Enhancements for HA coupling

**Versioning note:** Official **2.5.3** ships the old Phase 1 (Options → `config.json` + Ingress; archived). Next community pre-releases: **`2.6.0-alpha.*`** (explicit `version.py` bump approval — do not continue `2.5.3-alpha.N`). Alpha compose may stay pinned at last pre-release (`2.5.3-alpha.6`) until the next alpha bump.

**Next:** **2.6.h** (then **2.6.f**). Bench stays **`house_sim`** (`evcc_en` + golden map). **HA Lab P2–P4** and **2.6.e** are postponed — do not start them in this cycle.

**Scope:** easier HA coupling for Earnie. Flat `ehal.ha.entities` (**2.6.b**) was an interim plant-wire map; Pattern B storage (**2.6.g**, done) puts HA entity IDs on `plant` / `consumers[].ehal_bindings`. Next: entity-first EHAL-Com UX (**2.6.h**). The generic HA↔Loxone bridge stays under Research Items. Add-on 1.0 (Earnie publishing its own state) comes after southbound mapping is usable.

**Documents:**

- [House simulator spec](../docs/spec/house-sim.md) — **2.6.a** / HA Lab P1 (done); fixture bench for **2.6.g** / **2.6.h**
- [HA compatibility tests (concept)](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument.md) — **2.6.a**; postponed HA Lab P2–P4 / **2.6.e**
- [Entwicklungsplan §3.2 HA entity mapping](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md) — **2.6.b** (done); postponed **2.6.e** (confirm-before-save; LLM stays out of 2.6)
- [EHAL spec — Pattern B / Loxone HITL](../docs/spec/ehal.md) — **2.6.g** done; target UX for **2.6.h** (same `plant` / `consumers[].ehal_bindings` as Loxone **2.4.k**)
- [Add-on plan](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie_HomeAssistant_Addon_Dokumentation.md) — **2.6.f**
- [Add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md) — stable vs pre-release channel (not part of 2.6)
- [Business backlog](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Business-Backlog.md) — Synology dogfood walkthrough (done); HA suggest-and-confirm (**2.6.b**) done; Pattern B storage (**2.6.g**) done; next **2.6.h**
- [HA-Loxone-Bridge-Builder draft](HA-Loxone-Bridge-Builder-Draft.md) — research item, not 2.6

#### Prerequisites for this epic
- [x] Install HA simulation instance on Synology for testing (same instance as the [Business backlog](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Business-Backlog.md) dogfood walkthrough: Hue, add-on setup, comfort-gap notes). An empty HAOS does not replace **2.6.a**.

#### Features

##### Pattern B parity with Loxone (active — next)

Same storage and EHAL-Com workflow as Loxone **2.4.k** — not a second binding model forever. Depends on usable plant southbound (**2.6.b**, done). Credentials / `ehal.backend=ha` / `base_url` / `token` stay in `config.json`; only the entity→field map moves. Regression bench: `house_sim` / `evcc_en` (not HA Lab).

- [ ] **2.6.h — HA EHAL-Com UX parity with Loxone.** Entity picker first (plant + live-profile consumers), then only that entity’s EHAL fields; save writes that entity’s `ehal_bindings` (not one giant form for all plant fields). Reuse Loxone HITL patterns where practical (`build_entity_rows` / role grouping / empty-only propose). Scan HA `/api/states` once per session; suggest-and-confirm still never overwrites saved bindings; no LLM. After save, Live-Lesen/Schreiben show the same entity-centric mapping column contract as Loxone. Regression: house_sim / golden plant map still fillable via the new UI.

- [ ] **2.6.f — Add-on Version 1.0.** From the [add-on plan](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie_HomeAssistant_Addon_Dokumentation.md): MQTT Discovery, native Home Assistant entities for Earnie state, HA Energy-dashboard integration, Supervisor health check. Earnie publishing its own state. Checked on the existing Synology HAOS. Not the Version 2.+1 item "EHAL adaptation for MQTT". Comes after southbound mapping is usable (**2.6.g** / ideally **2.6.h**). Stable vs pre-release install is the [add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md), not this item.

##### Postponed — HA Lab P2–P4 and stronger propose

Do **not** start in this cycle. Bench for Pattern B remains **`house_sim`** only. Resume after **2.6.g** / **2.6.h** (or later) if more archetypes are needed.

`house_config` supplies physics parameters only; entity IDs come from the archetype. No real customer HA install. Same concept doc as **2.6.a**.

- [ ] **HA Lab P2** — 2–3 more hand-authored archetypes (domain/naming/i18n) on the same physics; write-back per archetype. *(postponed)*
- [ ] **HA Lab P3** — CI harness: short simulated windows, not N live `main.py` days. The **2.6.a** static fixture stays the fast job. *(postponed)*
- [ ] **HA Lab P4** — Optional. Dogfood the stepper against the existing Synology HAOS or `ha_lab/haos-docker`, wall-clock, states via `template:` / `pyscript`. Diagnosis exports and a hosted multi-user tool stay out of this epic. *(postponed)*
- [ ] **2.6.e — Stronger propose, still confirm-before-save.** After HA Lab P2 (when resumed). Replay archetypes with empty map and vendor-style names. Obvious fields proposed; ambiguous or `switch.*` cases left empty. Optional LLM stays out (same status as Loxone MCP in [Entwicklungsplan §3.1](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md)). After **2.6.g**, the same empty-only propose rules apply to Pattern B bindings. *(postponed with HA Lab)*


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
