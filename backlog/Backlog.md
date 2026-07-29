# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account
- [ ] Check possibilities to get quarterly-hour EPEX prices and change optimization to 15 min slots


## Feature Backlog


### Version 2.4 — EHAL foundation, DACH docking & Loxone on EHAL

**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 (Phases 1–4 / M1–M2)  
**Goal:** Freeze **EHAL**, prove Loxone-free southbounds (OpenEMS + HA/evcc), move production Loxone onto EHAL, add MCP one-click mapping, and prove config-only switch across all three. Earnie Core remains the sole 48h optimizer; hardware I/O only via EHAL (telemetry + setpoints + capability flags).  
**Southbound in this MINOR:** **C** OpenEMS = EHAL semantic prototype; **A+B** Home Assistant + evcc (A2) = DACH device volume; **Loxone** = production path via EHAL (`2.4.e`–`2.4.h`).  
**Packaging in this MINOR:** LoxBerry plugin **Scope A** MVP (`2.4.d`) done — thin Docker wrapper in `packaging/loxberry/` (not a native host install).  
**Naming:** **EHAL** is established (`docs/spec/ehal.md`, `2.4.a`/`2.4.b`/`2.4.e`/`2.4.f`/`2.4.g`/`2.4.h` done). Do not use “SAM” for this layer (Businessplan “SAM” = market size only). Thin marker prep (`2.3.f`) is done.  
**Moved out:** Donate (sidebar) — not part of docking.

- [ ] **2.4.j — EFM auto-sync (interpretation C)** *(follow-up from 2.4.f / §3.1)*
  - Auto-sync Energieflussmonitor meter tree → Hausprofil consumers + CSV paths after structure compare-all (`2.4.f`) yields a chosen source
  - Manual blueprint: `.cursor/plans/energieflussmonitor_hausprofil_blueprint_a.plan.md`
  - EFM has **no** multi-column Statistik export of all Leistungsflüsse — do not plan HK CSV column↔Verbraucher mapping on that assumption (abandoned 2026-07-23)
- [ ] **2.4.0 — Release**
  - Ship when: EHAL schema frozen, OpenEMS Compose path green, HA-EHAL path proven in lab (contract-tests + helpers smoke + marq24/HITL entity mapping); Loxone on EHAL without regression; Loxone one-click mapping usable (HITL; structure source compare-all until lab picks winner); Phase-4 automated config-switch proof (`2.4.h`) done — optional live lab matrix soft check
  - Official DACH messaging: Path A2; OpenEMS documented as prototype/industrial, not B2C default
  - “All three southbounds” release: OpenEMS ↔ HA+evcc ↔ Loxone via config switch
  - LoxBerry Scope A MVP (`2.4.d`) is implemented; ship plugin ZIP with this release when ready (hardware install acceptance optional)
  - **Note:** EFM auto-sync (`2.4.j`) is not a hard gate for `2.4.0`


### Version 2.5 — Investigate full migration to 15‑min slots (former B)

**Context:** Day-Ahead clearing is 15‑min MTU since ~2025-10-01. Earnie already fetches Energy-Charts (free, CC BY 4.0; native 15‑min after go-live) but `normalize_price_slot` floors to the hour — MILP still assumes `dt ≡ 1 h`. Official EPEX SFTP/MATS stays out of scope (paid; external use = license quote). aWATTar remains hourly fallback only. Prior deferral: **2.3.c.2** takeaway *variable sample time — hard*. Related open check: **2.3.2**.

**Scope of this chapter:** Investigate and decide whether/how to run the **full** optimizer on 15‑min slots (option B), not only “prices only” averaging (A) or hybrid grids (C).

- [ ] **2.5.a — Data & tariff fidelity**
  - Confirm Energy-Charts 15‑min coverage (AT/DE-LU/CH) vs pre-2025-10 hourly history; mixed-resolution handling
  - Map which catalog tariffs settle on ¼‑h EPEX vs hourly average; document billing vs plan mismatch if MILP stays hourly
  - Keep official EPEX unconnected unless a paid/internal use case appears
- [ ] **2.5.b — MILP / horizon impact study**
  - Explicit `dt_h` (0.25): battery SoC, wear, import/export cost, EV/thermal/generic (`min_on_quarterhours` as real slots)
  - Size estimate: ~4× variables on sunset→sunset; HiGHS/CBC solve time Live vs SE (`sunrise_window` / commit-K)
  - List breakages: `cons_data_hourly`, PV/price forecasts, charts (today mixed 15‑min log + 1‑h MILP), Loxone write cadence
- [ ] **2.5.c — Go / no-go + backlog split**
  - Decide: full B vs stay hourly + optional A (store QH prices for SE/billing only) vs hybrid C
  - If go: carve implementation phases into this MINOR (or successor); if no-go: archive rationale and close **2.3.2** accordingly


### Version 2.+1 — Introducing nested data models

- [ ] **Banner der Wahrheit — Layer C enforcement** *(follow-up from 2.4.i spike)*
  - Cosign/Sigstore in release CI + startup verifier + production signing keys
  - Watermark vs refuse-to-start decision; offline public-key path
  - Spec: [`docs/spec/hardware-registry-layer-c.md`](../docs/spec/hardware-registry-layer-c.md)
- [ ] For manual consumers take also PV into account - not just tariffs (check)
- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Move Loxone markers to data model - remove flat definition in config.json where possible
  - **Note:** Thin marker↔role prep and UI editability are in **2.3.f**; EHAL core / DACH adapters / Loxone-EHAL extraction in **2.4** (`2.4.e`). This chapter owns nesting / structure, not the EHAL interface rewrite.
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
