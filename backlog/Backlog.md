🗺️ Project Roadmap & Backlog

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
  - Evaluate running Szenario-Explorer as "web app" in Streamlit Community Cloud — secrets, no Loxone, demo feasibility  
- [x] Check if Loxone's Energiemonitor provides statistics to import in Earnie  
  - Energiemonitor logs statistics
  - [x] Check how data looks like -- Data is useable
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog


### Version 2.+1

- [ ] Reactivate possibility to link historical data to consumers as .csv-file
  - Define column structure of csv-file for overall consumption 
  - Add input possibility to UI für csv-file and a check if it should be substracted from overall consumption log (if not checked, the synthetic usage profil is used instead)
  - Add a normalization function to import csv-files with fitting column structure
    - Define Unit normalization and right sign of signal
    - Normalize sampling rate to one/hour (by interpolation / mean calculation)
    - Check length (at least 12 months)
  - Define column structure of csv-file - depending on consumer-type
    - use same normalization function as for overall consumption
  - Change plotting respectively
    - In the plotting area (Verbrauchsprofil) the user can decide to see all consumers at once (present mode) or each consumer solely that are instrumented with a csv-file to adopt usage profile (for scheduling in live mode)
  - Settings must be used correctly in Scenario Explorer (using synthetic or real profiles)
- [] When csv-File is a digital signal the normalization function automatically multiplies it with nominal power (after confirmation by user)
  - During inspection of csv-file, the user is asked for multiplying


### Version 2.+1 - Become Loxone agnostic

- [ ] Make interface to smarthome loxone agnostic
  - **Goal:** Get into contact with more Smarthome "nerds" that are willing to build connections to their specific hardware
  - Redefine Loxone Markers --> Smarthome Markers that are suitable to multiple standards like MQTT or Matter
  - Make proper assignments to already used Marker to consumers, inverter, heating etc. in data model and make it editable in UI
  - Create architecture for a connector approach that bridges a common generic internal Earnie interface to specific Smarthome interfaces
  - Refactor existing Loxone HTTP communication to new Loxone<>Earnie-connector
  - Create specification for other Smarthome connectors to internal Earnie interface
  - 


### Version 2.+1

- [ ] Make appropriate information accessible to user about where differences between optimized SOC and BL SOC Ziel come from to give him explanation (prove plausability)
  - One reason is moved consumption from "standard" EV charging
  - are there other reasons?
  - Idea for visualization: Draw "ghost bars" for scheduled EV charging as not color filled bars (just thick edges)
- [ ] Check if removing constraint for SOC at end of horizon changes simulation results in backtesting
- [ ] Check if there is a special issue on weekends, when time-to-be ready is set to 12:00 (Start/ End-SOC constraints)
- [ ] Find EPEX API to have provider independent tariff calculation
- [ ] Review current tariffs - use https://www.e-control.at/referenzmarktwert and docs\referenz\.~lock.Oeko_RefMrktPr.csv# as anchor point
- [ ] Improve cost calculation by adding monthly fees etc.
- [ ] Enhance page "Verbraucheranalyse" to "Analyse Verbrauch & Kosten"
  - Visualize usage of consumers on a weekly basis compared to historical price and PV 
  - Show if power came from PV, battery or grid
  - Visualize cost for each usage
  - Visualize total cost per week / month / year (validation against invoices) 
  - Visualize battery usage as sum of energy flow (maybe established charts exist?)
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

