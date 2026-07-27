# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog

### Version 2.3.2 -- Feature Addition

- [ ] Check possibilties to get quarterly hour EPEX prices and change optimization to 15 min slots

### Version 2.4 — EHAL foundation & DACH docking (OpenEMS + HA/evcc)

**Strategic source:** `Earnie-Projekt/Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` v2.4 (Phases 1–2b / M1–M1.5)  
**Goal:** Freeze **EHAL** and prove a Loxone-free southbound path. Earnie Core remains the sole 48h optimizer; hardware I/O only via EHAL (telemetry + setpoints + capability flags).  
**Southbound in this MINOR:** **C** OpenEMS = EHAL semantic prototype; **A+B** Home Assistant + evcc (A2) = DACH device volume.  
**Deferred to 2.5:** Loxone-EHAL extraction, MCP onboarding, multi-system field test with Loxone, device-profile library slice.  
**Packaging in this MINOR:** LoxBerry plugin **Scope A** MVP (`2.4.d`) — thin Docker wrapper over existing `loxberry_productive` compose; not a native host install.  
**Naming:** **EHAL** is established (`docs/spec/ehal.md`, `2.4.a`/`2.4.b` done). Do not use “SAM” for this layer (Businessplan “SAM” = market size only). Thin marker prep (`2.3.f`) is done.  
**Moved out:** Donate (sidebar) — not part of docking.

- [ ] Follow .\docs\spec\openems-lab-setup.md to setup openems-lab on Raspberry

- [ ] **2.4.c — HA-EHAL + evcc under HA (Phase 2b / M1.5, DACH default)**
  - One production **HA-EHAL-Adapter** (WS/REST); prefer stable HA entities from evcc (lab-only direct evcc optional)
  - Reference Compose: `earnie-core` + Home Assistant + evcc
  - **Optimizer exclusivity:** disable/subordinate hub-local surplus/spot strategies; document checklist
  - **Modbus rule:** exactly one writing southbound owner per physical bus/device
  - Entity → EHAL mapping UI (Human-in-the-Loop); optional LLM assist can wait for 2.5 parity with MCP
  - Contract-tests: identical schedules vs OpenEMS when only adapter config is switched
  - German user docs: DACH install path A2 (default) vs B (existing HA)
- [ ] **2.4.d — LoxBerry plugin Scope A MVP (thin Docker wrapper)**
  - **Goal:** Install/manage existing Earnie container from LoxBerry Plugin Admin — no native Python/Streamlit/MILP on the host
  - **Prerequisite:** LoxBerry **4.x** (arm64) + **Docker plugin**; reuse `docker/compose/loxberry_productive.yml` / GHCR multi-arch image
  - Plugin skeleton: `plugin.cfg`, icons, German strings, standard LB dirs (`config` / `data` / `log` / `bin` / `webfrontend`)
  - `postinstall` / upgrade / uninstall: require Docker plugin; create persistent dirs for `earnie_env/config` + `earnie_env/runtime`; `docker compose pull` + `up -d`; preserve volumes across plugin upgrades
  - Daemon or cron: keep container healthy / restart if stopped
  - Minimal LB WebUI: container status, start/stop, link to Streamlit (`:8501`), show installed image/plugin version
  - `release.cfg` (and optional prerelease) so LB can auto-update the **plugin ZIP**; document image-tag story (plugin version ↔ `ghcr.io/…/earnie-energy:<tag>`)
  - German user docs: plugin path vs manual compose; point to Go/No-Go (RAM ≥4 GB, SSD preferred)
  - Acceptance: fresh LB 4.x install from ZIP → container running → UI reachable; upgrade preserves config/runtime; uninstall leaves data policy documented
  - **Out of scope (later polish / other versions):** native host install; HA/evcc/OpenEMS sidecars on the Pi; Miniserver prefill into `.env`; alpha/prod channel switcher; Streamlit iframe embed; full LoxWiki store listing polish beyond MVP
- [ ] **2.4.0 — Release**
  - Ship when: EHAL schema frozen, OpenEMS Compose path green, HA+evcc path proven in lab (contract-tests)
  - Official DACH messaging: Path A2; OpenEMS documented as prototype/industrial, not B2C default
  - Loxone production path still on pre-EHAL code until **2.5** (no forced Loxone cutover in 2.4.0)
  - LoxBerry Scope A MVP (`2.4.d`) shippable with this release or as late add-on in the same MINOR cycle (does not block EHAL freeze)


### Version 2.5 — Loxone on EHAL, MCP & multi-system field test

**Strategic source:** same Entwicklungsplan (Phase 3–4 / M2)  
**Prerequisite:** 2.4 EHAL freeze + OpenEMS + HA/evcc adapters exist.  
**Goal:** Move production Loxone onto EHAL; add MCP one-click mapping; prove config-only switch across OpenEMS ↔ HA+evcc ↔ Loxone.

- [ ] **2.5.a — Loxone-EHAL adapter extraction (Phase 3)**
  - Refactor existing Loxone HTTP/marker path into **Loxone-EHAL-Adapter** (markers/blocks → same EHAL structures as OpenEMS/HA)
  - Keep practical compatibility with `loxone_*` keys where possible (full nesting remains `2.+1`)
  - Acceptance: Live/optimizer unchanged for current Loxone installs after cutover
- [ ] **2.5.b — Loxone MCP one-click mapping + structure research (§3.1)**
  - MCP client: structure scan → LLM propose → Streamlit preview with confidence → write config after confirm
  - Map onto **EHAL fields** (not only legacy flat markers)
  - **Research / follow-up:** Auto-sync Energieflussmonitor meter tree → Hausprofil consumers + CSV paths (interpretation C). Blocked today by no official Loxone structure export; revisit with MCP structure-scan. Manual blueprint: `.cursor/plans/energieflussmonitor_hausprofil_blueprint_a.plan.md`
    - EFM has **no** multi-column Statistik export of all Leistungsflüsse — do not plan HK CSV column↔Verbraucher mapping on that assumption (abandoned 2026-07-23)
- [ ] **2.5.c — Device / hardware profile schemas (M2 slice; bounty later)**
  - EHAL-facing device role templates (battery, EVCS, PV, consumers, …) as adapter mapping aids
  - Optional: first JSON outline for SunSpec / proprietary Modbus profiles (feeds future Path D / M4 bounty)
  - Loxone library as counterpart templates (Baustein/marker recipes → EHAL)
  - **Defer:** full Community Bounty engine = Entwicklungsplan **M4** (later version)
- [ ] **2.5.d — Multi-system field test (Phase 4)**
  - Prove system-agnostic core: OpenEMS ↔ HA+evcc ↔ Loxone by **config switch only**
  - Docs for connector authors; update German user docs for adapter choice including Loxone-on-EHAL
- [ ] **2.5.0 — Release**
  - Ship when: Loxone on EHAL without regression, MCP mapping usable (human-in-the-loop), Phase-4 field test passed
  - First community non-Loxone pilot may already exist from 2.4; 2.5.0 is the “all three southbounds” release


### Version 2.6 — Investigate full migration to 15‑min slots (former B)

**Context:** Day-Ahead clearing is 15‑min MTU since ~2025-10-01. Earnie already fetches Energy-Charts (free, CC BY 4.0; native 15‑min after go-live) but `normalize_price_slot` floors to the hour — MILP still assumes `dt ≡ 1 h`. Official EPEX SFTP/MATS stays out of scope (paid; external use = license quote). aWATTar remains hourly fallback only. Prior deferral: **2.3.c.2** takeaway *variable sample time — hard*. Related open check: **2.3.2**.

**Scope of this chapter:** Investigate and decide whether/how to run the **full** optimizer on 15‑min slots (option B), not only “prices only” averaging (A) or hybrid grids (C).

- [ ] **2.6.a — Data & tariff fidelity**
  - Confirm Energy-Charts 15‑min coverage (AT/DE-LU/CH) vs pre-2025-10 hourly history; mixed-resolution handling
  - Map which catalog tariffs settle on ¼‑h EPEX vs hourly average; document billing vs plan mismatch if MILP stays hourly
  - Keep official EPEX unconnected unless a paid/internal use case appears
- [ ] **2.6.b — MILP / horizon impact study**
  - Explicit `dt_h` (0.25): battery SoC, wear, import/export cost, EV/thermal/generic (`min_on_quarterhours` as real slots)
  - Size estimate: ~4× variables on sunset→sunset; HiGHS/CBC solve time Live vs SE (`sunrise_window` / commit-K)
  - List breakages: `cons_data_hourly`, PV/price forecasts, charts (today mixed 15‑min log + 1‑h MILP), Loxone write cadence
- [ ] **2.6.c — Go / no-go + backlog split**
  - Decide: full B vs stay hourly + optional A (store QH prices for SE/billing only) vs hybrid C
  - If go: carve implementation phases into this MINOR (or successor); if no-go: archive rationale and close **2.3.2** accordingly


### Version 2.+1 — Improve "security" against violating License agreements

- [ ] Clarify how user could get a one-time registry that is bound to their hardware
  - What are the technical prerequisites to make that running?
- [ ] **Banner der Wahrheit — Layer C (deferred):** signed official builds / GHCR attestation + startup verifier; tie to hardware registry. Enforces attribution on *official* distribution only — not source forks. See plan outline (A + light B shipped in 2.2.0).


### Version 2.+1 — Introducing nested data models

- [ ] For manual consumers take also PV into account - not just tariffs (check)
- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Move Loxone markers to data model - remove flat definition in config.json where possible
  - **Note:** Thin marker↔role prep and UI editability are in **2.3.f**; EHAL core / DACH adapters in **2.4**; Loxone-EHAL extraction in **2.5**. This chapter owns nesting / structure, not the EHAL interface rewrite.
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
