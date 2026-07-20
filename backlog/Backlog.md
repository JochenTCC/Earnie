# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Adapt business plan
- [ ] **Outreach (not software):** Ask for interested parties in loxforum / reddit — post under “my project”; take interesting chart snapshots (loxforum admins contacted re. best place)
  - loxforum -> done
  - Facebook groups
    - Loxone Konfigurationsbereich
    - Loxone D-A-CH --> done
    - Loxone Deutschland
    - Loxone Bauherren
  - Contact IoBroker-Community and HomeAssistant (when Best Interface is found)
- [x] Check if Loxone's Energiemonitor provides statistics to import in Earnie  
  - Energiemonitor logs statistics
  - [x] Check how data looks like -- Data is useable
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog


### Version 2.2.0

- [x] Build Szenario-Explorer as "web app" in Streamlit Community Cloud (SCC)
  - Precursor (done): `EARNIE_OFFLINE` live-scenario demo seed — [Backlog-Erledigt.md](Backlog-Erledigt.md)
  - Site config split (done): private `Earnie-env-home` + junction; public templates/catalog in `share/config/` (incl. `tariffs.json`); see [private-env.md](../docs/einrichtung/private-env.md)
  - New EARNIE_UI_MODES "live_environment" to enable / disable "Echtzeitumgebung"
- [x] Remove any references to DS-KO-DOLS (`DS-KO-DO-2`) in all files and replace it by dummies
- [x] Implement a first version of "Banner der Wahrheit", that can't be removed in a fork
- [x] Add a hint "Nicht optional, da ansonsten identisch mit Nicht optimierter Referenz" on subpage Batterien
- [x] Add a warning at SE at Gesamtkosten und -Verbrauch, when overall consumptions differ more than 5% from Live-Referenz (Hinweis column) with hint to send a config dump to TechCreaCon via Info / About contact.
- [x] Reorder sidebar
    - Deactivate "Verbraucheranalyse" when there is no live connection to smarthome (stub page notice)
    - Hide "Verbraucheranalyse" when EARNIE_UI_MODES does not include "live_environment"
    - Move "Verbraucheranalyse" into "Live-Cockpit" (at the bottom)
    - Rename section "Planung" into "Konfiguration"
    - Move Szenario-Explorer into section "Konfiguration" (above Live-Konfiguration)
    - Remove section "Analyse"
    - Move "Live-Konfiguration" into section "Konfiguration"; hide when `live_environment` not in modes (always usable when shown)
    - Rename section "Betrieb" into "Live-Cockpit"
- [x] Make a complete info section in sidebar (including version and Banner der Wahrheit + contacting formular with Topic, Description and attachments to mail@techcreacon.com)
- [ ] Merge streamlitcloud branch with main, when app is working on SCC
- [ ] Finalize Version 2.2.0 after test usage and make a release
  - Update German Docs

### Version 2.+1

- [ ] Clarify how user could get a one-time registry that is bound to their hardware
  - What are the technical prerequisites to make that running?
- [ ] **Banner der Wahrheit — Layer C (deferred):** signed official builds / GHCR attestation + startup verifier; tie to hardware registry. Enforces attribution on *official* distribution only — not source forks. See plan outline (A + light B shipped in 2.2.0).
- [ ] Insert a secured 

### Version 2.+1 - Become Loxone agnostic and standardize communication

- [ ] Make interface to smarthome loxone agnostic
  - **Goal:** Get into contact with more Smarthome "nerds" that are willing to build connections to their specific hardware
  - Redefine Loxone Markers --> Smarthome Markers that are suitable to multiple standards like MQTT or Matter
  - Make proper assignments to already used Marker to consumers, inverter, heating etc. in data model and make it editable in UI
  - Create architecture for a connector approach that bridges a common generic internal Earnie interface to specific Smarthome interfaces
  - Refactor existing Loxone HTTP communication to new Loxone<>Earnie-connector
  - Create specification for other Smarthome connectors to internal Earnie interface
- [ ] Enhance json Schemas to standardized interfaces between Devices like heat-pump, battery, EV, consumers, ... in order to use them as template to build up a library of communication interfaces between smarthome system and Earnie.
  - Build a Loxone library as suitable counterpart to that templates to be used for quick interface configuration
  - Prepare similar thing for other standards (see above)
- [ ] Add a Donate feature into sidebar 


### Version 2.+1

- [ ] Make appropriate information accessible to user about where differences between optimized SOC and BL SOC Ziel come from to give him explanation (prove plausability)
  - One reason is moved consumption from "standard" EV charging
  - are there other reasons?
  - Idea for visualization: Draw "ghost bars" for scheduled EV charging as not color filled bars (just thick edges)
- [ ] Check if removing constraint for SOC at end of horizon changes simulation results in backtesting
- [ ] Check if there is a special issue on weekends, when time-to-be ready is set to 12:00 (Start/ End-SOC constraints)
- [ ] Find EPEX API to have provider independent tariff calculation
- [ ] Review current tariffs - use https://www.e-control.at/referenzmarktwert and docs\referenz\.~lock.Oeko_RefMrktPr.csv# as anchor point
- [ ] Remove usage of "oemag_monthly_feed_in_rates" in backtesting_scenarios.json for monthly export tariffs. They must own their own complete data. Consider thac as design change if needed. Add data of "oemag_monthly_feed_in_rates" as sample in tariffs.json. Remove entry "oemag_monthly_feed_in_rates" in backtesting_scenarios.json.
- [ ] Improve cost calculation by adding monthly fees etc.
- [ ] Enhance page "Verbraucheranalyse" to "Analyse Verbrauch & Kosten"
  - Visualize usage of consumers on a weekly basis compared to historical price and PV 
  - Show if power came from PV, battery or grid
  - Visualize cost for each usage
  - Visualize total cost per week / month / year (validation against invoices) 
  - Visualize battery usage as sum of energy flow (maybe established charts exist?)
- [ ] SE progress bars: show ETA (“time left until finished”) during scenario simulation
  - Reopened from Erledigt 2026-07-16 — requested with baseline progress; only `current/total h` shipped, not ETA
- [ ] Order of progress bars in SE shall not change during execution of scenario simulation — previous fix (pre-seed worker progress files + sort by canonical preferred order) does not hold; reopen from Erledigt 2026-07-16
- [ ] Improve performance of Scenario Explorer (ideas?)


### Version 2.+1

- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Move Loxone markers to data model - remove flat definition in config.json where possible


### Version 2.+1

- [ ] **Recommendation mode smart/adaptive devices** (follow-up to recommendation mode manual devices)
  - Adaptive re runtime/energy per run; smart devices instead of manual input
  - Adaptation algo maintains `appliance_recommendation.default_power_kw` from Loxone power markers (`loxone_inputs.power_name`) on house-profile generics — reserved so far, no live use
  - Use Loxone power markers also for Sankey-Diagram for further differentation of defined consumers


### Version 2.+1 — Epics **Adaptation** & **Thermals** (architecture first)

- [ ] **Adaptation P1** — Generic adaptation model (skeleton)
  - Common structure for parameter adaptation of various forecast models:
    - Reference value (target for adaptation)
    - Variable parameters (with bounds)
    - Time horizon (e.g. 24 h for PV/freezer, 1 year for swim spa/house)
    - Start parameters from `config.json`; adaptation history **separate**; correct live parameters only when needed (rhythm oriented to horizon)
  - Target models (connect later): PV yield, thermal models, solar collector
  - **Precursor (done):** *Unified Open-Meteo solar* — shared archive bundle ([Backlog-Erledigt.md](Backlog-Erledigt.md))


### Version 2.+1

- [ ] **Adaptation P2** — PV adaptation (new approach) — first pilot on Adaptation P1
  - Sidebar PV tuning removed (UI S-2 P1 + 2026-07-15 code path) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § PV tuning removal; see `runtime/pv_accuracy_log.csv`
  - Replace or integrate old `pv_tuner` path into Adaptation P1 (`pv_tuner.py` counter delta only)
- [ ] **Adaptation P3** — Adaptation algorithm (PV pilot)
  - Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)


### Version 2.+1

- [ ] **Thermals P2** — Coupled single-node models
  - House ↔ heat storage ↔ solar system
  - House parameters from energy certificate (`EXAMPLE:/local/reference/energy-certificate.pdf` — not in repo)
  - Prepare air conditioning as thermal consumer
- [ ] **Thermals P3** — Thermal parameter adaptation (on Adaptation P1)
  - `heat_loss_kw_per_k` and further linear model parameters; horizon per consumer (24 h / 1 year)


### Version 2.+1

- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)


### Version 2.+1

- [ ] Generic EV model — for better reusability


### Version 2.+1

- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)

### Version 2.+1
- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)
