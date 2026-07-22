# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Adapt business plan
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog


### Version 2.3 — Enhance consumer visualization and cost analysis - sharpen tariffs handling

Year-1 product depth (trust / What-If / churn). **Good-enough €** for SE and demos — invoice-grade bill reconciliation is explicitly out of scope (nice-to-have later). Includes a thin marker/data-model prep for later SAM work (`2.4`), not the connector rewrite.

- [ ] **2.3.c.0a — SE: one MILP per window (or commit-K) instead of hourly re-solve**
  - **Goal:** Cut SE wall time; largest expected gain vs scenario-only parallelization
  - Today `simulate_horizon` re-solves CBC every hour on `matrix[i:]` (~24× per day window) even though SE has perfect foresight (prices/PV/load fixed for the window — unlike Live)
  - Implement open-loop apply of one full-window MILP, or commit first **K** hours then re-solve (tunable K); **Live stays** on periodic re-opt
  - A/B on a known year log: € / SoC / flex delivery vs current hourly rolling for `fixed_24h` and `sunrise_window`
  - Document SE policy (perfect-foresight open-loop / commit-K) vs Live MPC in spec; optional note under SE UI/docs that SE is not Live re-opt parity
  - [x] **TAKEAWAY** — SE defaults: `sunrise_window` (sunset2sunset) + `commit_hours=24`
  - [ ] There might be an issue again with different overall consumption over scenarios
- [x] **2.3.c.0b — Trial: HiGHS vs CBC for SE**
  - **Trial only** — measure before adopting
  - Bench wall time and €/plan delta vs CBC on the same SE window set (short month + a 12 months / defaults from above)
  - Decide: SE-only HiGHS, optional Live, or keep CBC; keep env/config switch so CBC remains fallback
  - [x] **TAKEAWAY** — Differences negligible → **HiGHS is the new default** (Live + SE). CBC remains fallback via `EARNIE_MILP_SOLVER=cbc` / SE `milp_solver`. Artifacts: `backtesting_logs/solver_ab_m03`, `solver_ab_last12m`.
- [x] **2.3.c.1 — Trial: fast paths for reference / trivial windows**
  - **Trial focused on reference calculations** (Historisch / scenario refs) and obvious no-MIP cases
  - Ensure reference/baseline paths do not pay full MILP cost; skip or cheap-path when no battery and no remaining flex (or equivalent trivial state)
  - Gate so optimized € path is unchanged unless a short A/B shows acceptable delta; report speedup on a multi-scenario SE run
  - [x] **TAKEAWAY** — Historisch/`ref:*` already closed-form (regression-tested). Optimized path skips solver when `battery_capacity_kwh<=0` and remaining flex=0 (`ENERGY_OPTIMIZER_MILP_TRIVIAL_FAST_PATH`, default on). Fixture A/B: dEUR=0 on battery+flex and no-battery/zero-flex; measurable wall speedup on trivial windows (`python -m scripts.ab_se_trivial_fast_path`)
- [x] **2.3.c.2 — Tuning MILP for SE and Live**
  - Check if removing constraint for SOC at end of horizon changes simulation results in backtesting for both fixed_24h and sunset2sunset
  - Trial SE `sunrise_window` without 24 h truncate: simulate full SA_0-->SA_2 (~40–48 h) per step; book costs only for the non-overlapping first day (t_now-->SA_1 or first 24 h); hand off simulated SoC at SA_1 as start SoC for the next day’s ~48 h run — **no hard SOC_min at SA_1** (same direction as removing end-of-horizon SOC constraint above; keep min/max only)
  - Check if non-constant sample time would be possible for online MILP (15 min for next 3hours, 1h in rest of neutral area, 2hours for green area)
  - [x] **TAKEAWAY (SOC anchors)** — last12m (`2025-07-01`–`2026-06-30`). Flag `disable_horizon_soc_anchor`. Small € win on `sunrise_window`; mixed on `fixed_24h`. **Keep product anchors on**. Artifacts: `backtesting_logs/soc_anchor_ab_last12m/`
  - [x] **TAKEAWAY (full SA_0-->SA_2)** — Flag `sunrise_full_horizon_trial`. Large € delta but plausibility collapsed (~127/365) from flex deferred past booked 24 h. **Keep SE truncate** as default. Artifacts: `backtesting_logs/sunrise_full_ab_last12m/`
  - [x] **TAKEAWAY (variable sample time)** — **hard — defer** (implicit `dt ≡ 1 h`; Live already re-opts ~15 min on hourly plan)
- [x] **2.3.c.3 — Full SA_0-->SA_2: force flex into booked slice**
  - Root cause of 2.3.c.2 plaus collapse: generic flex eligible on day-2 hours; open-loop satisfies 24 h targets after the book cut
  - Clamp consumer `flex_indices` to first `BACKTESTING_STEP_HOURS` via `flex_book_hours` when `sunrise_full_horizon_trial` is on (battery/PV still see full matrix)
  - A/B last12m truncated vs full+flexbook; gate: plaus ≈ truncated before reconsidering product path
  - [x] **TAKEAWAY** — last12m (`2025-07-01`–`2026-06-30`, 8 workers). Plaus **restored** to 344/365 (= truncated) on all four scenarios. € Δ vs truncated ≈ −7…−18 €/y (Live −10 €); wall ~398s vs ~423s. Broken run without flexbook had −136…−175 € with collapsed plaus — those “savings” were flex deferred past booking. **Product default (user 2026-07-22):** `sunrise_full_horizon_trial` **true** (full SA_0-->SA_2 + flexbook + free SOC anchors); set `false` for old truncate-before-MILP. Artifacts: `backtesting_logs/sunrise_full_flexbook_ab_last12m/`

- [ ] Streamlit Rollout (Pre-Release)

- [ ] **2.3.e — Verbraucheranalyse → Analyse Verbrauch & Kosten**
  - Visualize usage of consumers on a weekly basis compared to historical price and PV
  - Show if power came from PV, battery or grid
  - Visualize cost for each usage
  - Visualize total cost per week / month / year (**rough totals for trust** — not validation against invoices)
  - Visualize battery usage as sum of energy flow (maybe established charts exist?)
- [ ] **2.3.f — Thin marker / data-model prep (SAM optionality)**
  - **Goal:** Cheap prep for `2.4` without connector framework, MQTT/Matter, or Loxone HTTP rewrite
  - Clarify marker ↔ role assignments (consumers, inverter, heating, battery, EV, …) in data model / schema naming toward generic “smarthome markers” (docs + structure; keep Loxone as sole live backend)
  - Make existing marker→entity assignments editable in UI where already used
  - **Out of scope here:** connector architecture, Loxone HTTP extraction, third-party connector spec, device-template library (→ `2.4`); full nested structures (→ nested-models `2.+1`)
- [ ] **2.3.0 — Release**
  - Finalize after test usage; update German docs as needed (carry-over from 2.2.0 finalize)


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
- [ ] Integrate a MCP-based automatic communication-definition (see also Entwicklungsplan\MCP-Interfacing-für-Earnie.md) in Loxone-Kommunikation page

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
