# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account
- [ ] Check possibilities to get quarterly-hour EPEX prices and change optimization to 15 min slots



## Feature Backlog



### Version 2.5 — Investigate full migration to 15‑min slots

**Context:** Day-Ahead clearing is 15‑min MTU since ~2025-10-01. Earnie already fetches Energy-Charts (free, CC BY 4.0; native 15‑min after go-live) but `normalize_price_slot` floors to the hour — MILP still assumes `dt ≡ 1 h`. Official EPEX SFTP/MATS stays out of scope (paid; external use = license quote). aWATTar remains hourly fallback only. Prior deferral: **2.3.c.2** takeaway *variable sample time — hard*. Related open check: **2.3.2**.

**Scope of this chapter:** Investigate and decide whether/how to run the **full** optimizer on 15‑min slots (option B), not only “prices only” averaging (A) or hybrid grids (C).

### Version 2.5

- [x] Add standby power for battery
  - This power is needed all the time as consumed energy for keeping the battery up. For optimization treat it as 24/7 consumer. Parameter is part of battery
- [x] Add possibility to take Netznutzungsentgelte into account (as far as they are relevant to relative price changes)
  - As a first MVP the user has to provide the "Arbeitspreis" in ct/kWh
  - Add "Arbeitspreis" to normal import tariff and use sum for optimization
  - Add a new section into fake invoices for the Netzentgelt 
    - Jahr: split Energiebezug (Lieferant) vs Netznutzung Arbeitspreis (same Gesamt; AP already in k_act)
    - Dedicated ## Netznutzung section (AP, Bezug kWh, €, Grundpreis stub)
- [x] Reduce messages like:
  - 2026-08-05 13:42:43 [INFO] (optimizer.milp_consumers:620) - urgent-Regel [e_auto]: nur_urgent_fenster — Ziel 3.650 kWh, optional geplant 0.000 kWh, urgent geplant 3.652 kWh (must_start=2026-08-08T11:54:18+02:00, deadline=2026-08-08T13:00:00+02:00)
  - Add possibility on Optimierer-Dienst page to filter for [INFO] / [WARNING] / ...
- [x] Place a thicker slightly transparent line behind the SOC line in chart 1 of Monitor page depending on ess-mode
  - Nothing, when in Automode
  - Cyan when in Zwangsladen but charging power is near zero (Remove yellow / black bar)
  - Blue when in Zwangsladen with higher charging power
- [ ] **2.5.a — Data & tariff fidelity**
  - Confirm Energy-Charts 15‑min coverage (AT/DE-LU/CH) vs pre-2025-10 hourly history; mixed-resolution handling
  - Map which catalog tariffs settle on ¼‑h EPEX vs hourly average; document billing vs plan mismatch if MILP stays hourly
- [ ] **2.5.b — MILP / horizon impact study**
  - Explicit `dt_h` (0.25): battery SoC, wear, import/export cost, EV/thermal/generic (`min_on_quarterhours` as real slots)
  - Size estimate: ~4× variables on sunset→sunset; HiGHS/CBC solve time Live vs SE (`sunrise_window` / commit-K)
  - List breakages: `cons_data_hourly`, PV/price forecasts, charts (today mixed 15‑min log + 1‑h MILP), Loxone write cadence
- [ ] **2.5.c — Go / no-go + backlog split**
  - Decide: full B vs stay hourly + optional A (store QH prices for SE/billing only) vs hybrid C
  - If go: carve implementation phases into this MINOR (or successor); if no-go: archive rationale and close **2.3.2** accordingly


### Version 2.+1 — Introducing nested data models

- [ ] When importing from existing Loxone config is working the other way round would also be possible:
    - User has a complete HK with live scenario in place in Earnie
    - Earnie generates pre-filled Loxone Template XML files (with correct ids, (multiple) evs, (multiple) consumers) for importing into Loxone config.
- [ ] Check possibility for automatically learn consumer schedules (for known consumers) and nominal power (for all consumers) from sens_power_act to substitute or improve manual settings
- [ ] Clarify how to handle wallbox <> EVs
  - for multiple wallboxes / EVs there is not a "natural" 1 to 1 binding - hence it must be clarified how to handle that (have a look at evcc)
- [ ] Optimize Pool temperature to a certain value on time. Set desired temperature and using time. Combine it with RC model
  - Add a chart that shows comparison between actual and modeled temperature (including ambient temperature and heating activity)
- [ ] Add possibility to simulate restrictions for energy export dependent on current grid situation in SE (and maybe in Live optimization)
- [ ] **Banner der Wahrheit — Layer C enforcement** *(after soft first approach `2.4.q`; follow-up from `2.4.i` spike)*
  - Cosign/Sigstore in release CI + startup verifier + production signing keys
  - Watermark vs refuse-to-start decision; offline public-key path
  - Spec: `[docs/spec/hardware-registry-layer-c.md](../docs/spec/hardware-registry-layer-c.md)`
- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Move Loxone markers to data model - remove flat definition in config.json where possible
  - **Note:** Thin marker↔role prep and UI editability are in **2.3.f**; EHAL core / DACH adapters / Loxone-EHAL extraction in **2.4** (`2.4.e`). This chapter owns nesting / structure, not the EHAL interface rewrite.
  - **Pool nesting:** Merge today’s separate consumers **Pool-Filter** into **Pool-Heizung** (drop the bridge/synthetic `swimspa_filter` / `pool_filter` sibling). Introduce a combined **pool** model: outer entity = one house-profile consumer; inner parts = RC thermal (Heizung) + generic flex (Filter hours / Freigabe / native window). EHAL bindings and MILP stay role-scoped to the inners; UI/planning show one Pool.
- [ ] **Recommendation mode smart/adaptive devices** (follow-up to recommendation mode manual devices)
  - Adaptive re runtime/energy per run; smart devices instead of manual input
  - Adaptation algo maintains `appliance_recommendation.default_power_kw` from Loxone power markers (`loxone_inputs.power_name`) on house-profile generics — reserved so far, no live use
  - Use Loxone power markers also for Sankey-Diagram for further differentation of defined consumers
- [ ] Update Greenfield import workflow


### Version 2.+1 — Epics **Adaptation** & **Thermals** (architecture first)

- [ ] **Adaptation P3** — Adaptation algorithm (PV pilot)
  - Common structure for parameter adaptation of various forecast models:
    - Reference value (target for adaptation)
    - Variable parameters (with bounds)
    - Time horizon (e.g. 24 h for PV/freezer, 1 year for swim spa/house)
    - Start parameters from `config.json`; adaptation history **separate**; correct live parameters only when needed (rhythm oriented to horizon)

- Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)

- [ ] **Thermals P2** — Coupled single-node models
  - House ↔ heat storage ↔ solar system
  - House parameters from energy certificate (`EXAMPLE:/local/reference/energy-certificate.pdf` — not in repo)
  - Prepare air conditioning as thermal consumer
- [ ] **Thermals P3** — Thermal parameter adaptation (on Adaptation P1)
  - `heat_loss_kw_per_k` and further linear model parameters; horizon per consumer (24 h / 1 year)
- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)



### Version 2.+1

- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)


### Version 2.+1
- [ ] Make also an EHAL adaption for MQTT
- [ ] **Data & tariff fidelity - Part 2**
  - Keep official EPEX unconnected unless a paid/internal use case appears
  - Check possibilities to automatic tariffs.json update to existing installations


### Version 3.0

- [ ] Make complete Earnie available as cloud service (Online optimization and Internet communication with local smarthome / isolated devices) - similar to "Smart-Energy" (Steiermark)
