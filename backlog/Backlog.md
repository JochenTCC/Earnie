🗺️ Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Adapt business plan
- [ ] **Outreach (not software):** Ask for interested parties in loxforum / reddit — post under “my project”; take interesting chart snapshots (loxforum admins contacted re. best place)
  - loxforum -> done
  - Facebook groups (e.g. Loxone Smart Home Community)
  - Evaluate running Szenario-Explorer as "web app" in Streamlit Community Cloud — secrets, no Loxone, demo feasibility  
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog

### Minor changes in Version 1.99

- [ ] Rearrange Verbrauchsvergleich (Debug) table
  - Add a column (Verbrauch ohne PV und Speicher)
  - Change name of column "Baseline Spec kWh" to "Reference (Live) - ohne Optimierung [kWh]"
  - Change name of column "delta kWh (Opt-Baseline)" to "delta kWh (Ref. ohne Optimierung)"
  - Remove rows for "Historisch (ohne Optimierung, ohne PV/Batterie)" and "Referenz (Live) — ohne Optimierung"
  - Write consumption of scenario "Historisch ..." in all cells of colum "Verbrauch ohne PV und Speicher"
  - Write consumption of scenario "Reference (Live) - ohne Optimierung [kWh]" in all cells of column with this name


## Real Version 2.0 — legacy data model removed

### Version 2.0

After **real** 2.0 release: dead code, obsolete tests, and leftover patches from pre-1.26.0 data model (1.26.0 P6 removed runtime fallbacks; this epic mops up the rest)


### Version 2.+1 — Quality epic / post-migration cleanup

- [ ] Pimp README.md with snapshots
- [ ] Evaluate option for code coverage testing and identification of deprecated code / tests (especially due to substantial data model change) / obsolete patches because of legacy data model
  - **Planning (three deliverables):**
    - **Coverage baseline** — run coverage on migrated core packages; identify weakly covered modules that changed most in the 2.0 data model
    - **Legacy test audit** — review tests flagged by legacy symbols and `scripts/test_health_report.py`; decide keep, rewrite, or delete
    - **Obsolete patch audit** — search for compatibility code, fallback paths, and migration-only branches from pre-1.26.0 model
  - **Tooling already in repo:** `pytest-cov` / `coverage.py` (`pyproject.toml`), `scripts/test_health_report.py` (JUnit history, coverage triage, legacy hints), optional `mutmut` (`mutmut.ini`)
  - **Recommended additions (minimal, high value):** `vulture` (unused code / dead migration helpers), `pytest-deadfixtures` (orphaned fixtures after model change)
  - **Workflow:** weekly or pre-release: `test_health_report run --coverage` → `test_health_report report`; supplement with `vulture` and targeted `rg` on known legacy symbols; manual review only — never auto-delete flagged tests
- [ ] Thorough code review and refactoring (with proper KPIs)
- [ ] Search for deprecated and unnecessary files and remove them
  - Code for migration from V 1.x to 2.0 is not needed anymore


### Version 2.+1

- [ ] Make editors more compact: Parameter name and entry field side by side
- [ ] Add a hint text to SE that there is no guarantee for the results
- [ ] Make main.py controllable from streamlit.app (Checks must be included if main.py is runnin already, if necessary change spec / doc and put it in one container as deamon or so)


### Version 2.+1

- [ ] Add a German documentation about how to use Earnie from a user perspective (after installation is done)
- [ ] Make appropriate information accessible to user about where differences between optimized SOC and BL SOC Ziel come from to give him explanation (prove plausability)
- [ ] Check if removing constraint for SOC at end of horizon changes simulation resulst in backtesting
- [ ] Find EPEX API to have provider independent tariff calculation
- [ ] Improve cost calculation by adding monthly fees etc.
- [ ] Improve performance of Scenario Explorer (reduce aborting time for CBC issues? - other ideas?)


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

