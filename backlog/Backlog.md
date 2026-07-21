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
    - Loxone Deutschland --> done
    - Loxone Bauherren
  - Photovoltaik-Forum --> done (more to follow)  
    - Last post (Communication\Post-Photovoltaik-Forum_Optimale-Erweiterung.md) was moved to "Bezugsstrom, Stromanbieter, Stromvergleich" --> create a different post with similar content but better title
    - Creat a post with comparison of different tariffs (SPOT; fixed; monthly)
  - Contact IoBroker-Community and HomeAssistant (when Best Interface is found — after **2.4.a** / connector spec)
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
- [x] Merge streamlitcloud branch with main, when app is working on SCC
- [x] Add a CONTRIBUTING.md document in German
- [x] Add [![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://earnie.streamlit.app) into README.md
- [ ] Add link to Streamlit in Posts
  - Photovoltaik-Forum - Done
  - LoxForum
- [x] Perform a SE for posts
- [x] Add a link to Manual in Info
- [x] Test if sunset2set-Mode is working in SE brings better results than fixed_24h
  - Results are better, but computing effort is much higher
- [x] In Scenario Editor show parameters of selected tariffs and give a hint that user must check if data is correct (there is no guarantee for correctness) and monthly fixed fees are not part of the calculation yet
- [ ] Finalize Version 2.2.0 after test usage and make a release
  - Update German Docs


### Version 2.3 — Enhance consumer visualization and cost analysis - sharpen tariffs handling

Year-1 product depth (trust / What-If / churn). **Good-enough €** for SE and demos — invoice-grade bill reconciliation is explicitly out of scope (nice-to-have later). Includes a thin marker/data-model prep for later SAM work (`2.4`), not the connector rewrite.

- [ ] **2.3.a — Tariff hygiene (good-enough €)**
  - Find EPEX API to have provider independent tariff calculation
  - Review current tariffs - use https://www.e-control.at/referenzmarktwert and `docs/referenz/` OeMAG/RefMrkt anchors
    - Add vkw variable tariffs
  - Shared OeMAG reference already lives in `tariffs.json` (data-model v2). Remaining: unify export `monthly_float` and `monthly_table` in the data model (one month-constant type with owned `monthly_rates`; migrate/trim catalog entries that only differ by scale-vs-table). UI already treats both as one Typ (“Monatspreis”); calculation paths stay distinct until this unify.
- [ ] **2.3.b — Approximate cost model (monthly fees)**
  - Improve cost calculation by adding monthly fees etc.
  - Label fees as approximate where needed; no requirement to match real invoices
- [ ] **2.3.c — Plan / SOC plausibility**
  - Make appropriate information accessible to user about where differences between optimized SOC and BL SOC Ziel come from (prove plausibility)
    - One reason is moved consumption from "standard" EV charging
    - Are there other reasons?
    - Idea for visualization: Draw "ghost bars" for scheduled EV charging as not color-filled bars (just thick edges)
  - Check if removing constraint for SOC at end of horizon changes simulation results in backtesting
  - Check if there is a special issue on weekends, when time-to-be-ready is set to 12:00 (Start/End-SOC constraints) in SE optimization
- [ ] **2.3.d — Verbraucheranalyse → Analyse Verbrauch & Kosten**
  - Visualize usage of consumers on a weekly basis compared to historical price and PV
  - Show if power came from PV, battery or grid
  - Visualize cost for each usage
  - Visualize total cost per week / month / year (**rough totals for trust** — not validation against invoices)
  - Visualize battery usage as sum of energy flow (maybe established charts exist?)
- [ ] **2.3.e — Scenario Explorer polish**
  - SE progress bars: show ETA (“time left until finished”) during scenario simulation
    - Reopened from Erledigt 2026-07-16 — requested with baseline progress; only `current/total h` shipped, not ETA
  - Order of progress bars in SE shall not change during execution of scenario simulation — previous fix (pre-seed worker progress files + sort by canonical preferred order) does not hold; reopen from Erledigt 2026-07-16
  - Improve performance of Scenario Explorer (ideas?)
- [ ] **2.3.f — Thin marker / data-model prep (SAM optionality)**
  - **Goal:** Cheap prep for `2.4` without connector framework, MQTT/Matter, or Loxone HTTP rewrite
  - Clarify marker ↔ role assignments (consumers, inverter, heating, battery, EV, …) in data model / schema naming toward generic “smarthome markers” (docs + structure; keep Loxone as sole live backend)
  - Make existing marker→entity assignments editable in UI where already used
  - **Out of scope here:** connector architecture, Loxone HTTP extraction, third-party connector spec, device-template library (→ `2.4`); full nested structures (→ nested-models `2.+1`)
- [ ] **2.3.0 — Release**
  - Finalize after test usage; update German docs as needed


### Version 2.4 — Become Loxone agnostic and standardize communication (SAM expansion)

Year-2+ SAM expansion (KNX / Home Assistant / IoBroker when a second connector is real). Depends on thin prep in **2.3.f**. Do not start the full rewrite until Loxone path is stable and a non-Loxone pilot volunteer exists.

- [ ] **2.4.a — Earnie ↔ smarthome internal interface**
  - **Goal:** Reach more smarthome “nerds” willing to build connections to their specific hardware
  - Redefine Loxone Markers → Smarthome Markers suitable for multiple standards (e.g. MQTT or Matter)
  - Create architecture for a connector approach that bridges a common generic internal Earnie interface to specific smarthome interfaces
  - Create specification for other smarthome connectors to the internal Earnie interface
- [ ] **2.4.b — Loxone connector extraction**
  - Refactor existing Loxone HTTP communication to a Loxone↔Earnie connector behind the internal interface
- [ ] **2.4.c — Device interface schemas & libraries**
  - Enhance JSON schemas to standardized interfaces between devices (heat pump, battery, EV, consumers, …) as templates for a library of communication interfaces between smarthome system and Earnie
  - Build a Loxone library as counterpart to those templates for quick interface configuration
  - Prepare similar templates for other standards (see above)
- [ ] **2.4.d — Donate**
  - Add a Donate feature into sidebar
- [ ] **2.4.0 — Release**
  - First non-Loxone pilot only when a volunteer connector exists; update docs / CONTRIBUTING for connector authors


### Version 2.+1 — Improve "security" against violating License agreements

- [ ] Clarify how user could get a one-time registry that is bound to their hardware
  - What are the technical prerequisites to make that running?
- [ ] **Banner der Wahrheit — Layer C (deferred):** signed official builds / GHCR attestation + startup verifier; tie to hardware registry. Enforces attribution on *official* distribution only — not source forks. See plan outline (A + light B shipped in 2.2.0).


### Version 2.+1 — Introducing nested data models

- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Move Loxone markers to data model - remove flat definition in config.json where possible
  - **Note:** Thin marker↔role prep and UI editability are in **2.3.f**; full connector extraction in **2.4**. This chapter owns nesting / structure, not the SAM interface rewrite.
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
- [ ] **Adaptation P2** — PV adaptation (new approach) — first pilot on Adaptation P1
  - Sidebar PV tuning removed (UI S-2 P1 + 2026-07-15 code path) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § PV tuning removal; see `runtime/pv_accuracy_log.csv`
  - Replace or integrate old `pv_tuner` path into Adaptation P1 (`pv_tuner.py` counter delta only)
- [ ] **Adaptation P3** — Adaptation algorithm (PV pilot)
  - Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)
- [ ] **Thermals P2** — Coupled single-node models
  - House ↔ heat storage ↔ solar system
  - House parameters from energy certificate (`EXAMPLE:/local/reference/energy-certificate.pdf` — not in repo)
  - Prepare air conditioning as thermal consumer
- [ ] **Thermals P3** — Thermal parameter adaptation (on Adaptation P1)
  - `heat_loss_kw_per_k` and further linear model parameters; horizon per consumer (24 h / 1 year)
- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)


### Version 2.+1

- [ ] Generic EV model — for better reusability


### Version 2.+1

- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)

### Version 3.0
- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)
