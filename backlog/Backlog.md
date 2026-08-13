# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account



## Feature Backlog



### Version 2.5.0 — Official release (pending)

**Context:** Community pre-release `2.5.0-alpha.1` ships full 15‑min MILP (`dt_h = 0.25`) plus remaining 2.5 feature items (archived). Brief: [`docs/spec/quarter-hour-slots.md`](../docs/spec/quarter-hour-slots.md). Official EPEX SFTP/MATS stays out of scope.

- [ ] Check possibilities to show decimal numbers according to regional settings (e.g. use "," as decimal sign for Germany)
- [ ] Official `2.5.0` after community soak (tag without `-alpha`; GHCR `:latest`)


### Version 2.6 - POC for EEG-ready Earnie

Main Goal of this version is to get a proof-of-concept for an evolved Earnie that is able to optimize EEGs (Energie-Erzeuger-Gemeinschaft)
- See Entwicklungsplan\eeg-earnie-recherche-zusammenfassung.md for current research
- [ ] Implement a POC for EEG simulation


### Version 2.+1 — Improvements for EVs / Export

- [ ] Clarify how to handle wallbox <> EVs
- [ ] When importing from existing Loxone config is working the other way round would also be possible:
    - User has a complete HK with live scenario in place in Earnie
    - Earnie generates pre-filled Loxone Template XML files (with correct ids, (multiple) evs, (multiple) consumers) for importing into Loxone config.
- [ ] Optimize Pool temperature to a certain value on time. Set desired temperature and using time. Combine it with RC model
  - Add a chart that shows comparison between actual and modeled temperature (including ambient temperature and heating activity)
- [ ] Add possibility to simulate restrictions for energy export dependent on current grid situation in SE (and maybe in Live optimization)


### Version 2.+1 — Introducing nested data models / Epics **Adaptation** & **Thermals** (architecture first)

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



### Version 2.+1

- [ ] Check possibility for automatically learn consumer schedules (for known consumers) and nominal power (for all consumers) from sens_power_act to substitute or improve manual settings
  - for multiple wallboxes / EVs there is not a "natural" 1 to 1 binding - hence it must be clarified how to handle that (have a look at evcc)
- [ ] **Banner der Wahrheit — Layer C enforcement** *(after soft first approach `2.4.q`; follow-up from `2.4.i` spike)*
  - Cosign/Sigstore in release CI + startup verifier + production signing keys
  - Watermark vs refuse-to-start decision; offline public-key path
  - Spec: `[docs/spec/hardware-registry-layer-c.md](../docs/spec/hardware-registry-layer-c.md)`
- [ ] Make also an EHAL adaption for MQTT
- [ ] **Data & tariff fidelity - Part 2**
  - Keep official EPEX unconnected unless a paid/internal use case appears
  - Check possibilities to automatic tariffs.json update to existing installations


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)
