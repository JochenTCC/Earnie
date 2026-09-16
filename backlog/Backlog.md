# Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account
- [ ] Enable multiple isolated battery or battery+Inverter entities
  - Isolated battery modes: charging / discharging / standby
  - batt+inverter modes: optimizing / charging / discharging
  - All batteries are parts of optimization


## Feature Backlog

### Version 2.6 - Enhancements for HA coupling

#### Prerequisites for this epic
- [x] Install HA simulation instance on Synology for testing

#### Features

**Priority order (2026-09-16):** phased by "must fix before we publicly promote the HA add-on" — see `Earnie-Projekt/Business-Backlog.md`, Awareness-Sprint item "Earnie ist jetzt auch als HA-Add-On zu haben!" (postponed pending Phase 1).

##### Phase 1 — Installation blockers (gate the HA-add-on awareness post)

- [ ] Remove Loxone-only Supervisor options (`loxone_user`/`loxone_pass`/`loxone_ip` in `ha-addon-earnie/earnie/config.yaml` `options`/`schema`) — shown unconditionally in the Supervisor "Configuration" tab regardless of chosen backend, confusing when the add-on already implies HA as backend; the in-app Smarthome-Backend page (`ui/pages/page_smarthome_backend.py`) already handles this conditionally and correctly, so these Supervisor-level options are redundant
- [ ] Fix HA self-discovery inside the add-on: `discover_home_assistant()` ([integrations/integration_scanner.py](../integrations/integration_scanner.py)) only tries mDNS, and `full_active` adds nothing for HA (only an OpenEMS port scan) — no active fallback. Found via dogfooding: both normal and extended Smarthome-Backend scans find nothing when Earnie runs as the HA add-on, because the container isn't on `host_network` (missing in `config.yaml`) so mDNS multicast can't cross Supervisor's isolated Docker network. The code already knows it's running as the add-on (`EARNIE_INSTALL_CONTEXT=homeassistant_addon` from `run.sh`, read by `install_context_target_kinds()` in [runtime_store/install_context.py](../runtime_store/install_context.py)) but only uses that to narrow the scan, not to skip network discovery. Preferred fix: use the Supervisor's proxied Core API directly (`SUPERVISOR_TOKEN` + `hassio_api`/`homeassistant_api: true`) instead of network discovery — reliable, no multicast dependency. Weaker fallback: `host_network: true` (still useful for genuine LAN-discovery scenarios, has its own security/compatibility tradeoffs)
- [ ] Add-on Version 0.2 (Entwicklungsplan roadmap): Options-UI → `config.json` generation, Ingress (embedded UI, no separate port), Supervisor-Proxy instead of a manual long-lived-access token for the EHAL-HA-adapter
  - Confirmed via dogfooding on the new HAOS-in-VM Synology instance (2026-09-16): without Ingress, "OPEN WEB UI" opens `http://homeassistant.local:8501`, which fails when mDNS doesn't resolve the extra port from a fresh tab — user has to manually look up the VM IP. Looks like a broken add-on to a non-technical user; Ingress removes the port/IP lookup entirely

##### Phase 2 — Rounds out onboarding (not blocking, high value)

- [ ] Allow changing HTTP port for Home Assistant and OpenEMS (follow-up to Miniserver #9)
  - HA form already stores a full `ehal.ha.base_url` (default `http://homeassistant:8123`) — port is in the URL, not a separate field
  - OpenEMS form already stores `ehal.openems.base_url` (default `http://openems-edge:8084`)
  - Follow-up: make non-default ports obvious in SB Anbindung (help/caption, or dedicated port field if users still cannot change it in practice)
- [ ] Add-on `ehal_loxone_http_port` env-override in `scripts/bootstrap_runtime.py` (currently `config.json`-only; open point #1 in Earnie_HomeAssistant_Addon_Dokumentation.md — not a 0.1 blocker)

##### Phase 3 — Test infrastructure (regression safety net before more feature scope)

- [ ] Build Smoke Test for Integration test / EHAL compatibility fixtures (see Earnie-Projekt\Entwicklungsplan\Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument.md) — fixture-based testing with simulated ("faked") device entity signatures instead of real hardware, to test EHAL discovery/mapping against different HA integration shapes. Separate from Add-on M3 (archived; Supervisor persistence walkthrough in [docs/einrichtung/homeassistant-addon-testumgebung.md](../docs/einrichtung/homeassistant-addon-testumgebung.md)). Do this before Phase 4 so later feature work doesn't silently regress discovery/mapping for configs beyond the one real dogfooding instance

##### Phase 4 — Larger scope (after the add-on feels reliable)

- [ ] Add-on Version 1.0 (Entwicklungsplan roadmap): MQTT Discovery, native Home-Assistant entities for Earnie state, Energy-Dashboard integration — distinct from the "Make also an EHAL adaption for MQTT" item elsewhere in this file (that's an EHAL southbound backend; this is the add-on itself publishing Earnie state via HA's native MQTT Discovery)
- [ ] **energy counters (ΔkWh) for slot Ist on HA backend**
  - Prefer cumulative / total-increasing energy entities for grid± / PV when mapped
  - Same chart contract as Loxone (avg power = ΔE / slot Δt); battery/flex may stay on sampled mean
  - Needs HA entity discovery/mapping (energy sensors are usually separate entities, not a second channel of the power entity) — depends on improved HA-binding / EHAL-Com HA mapping UX
  - Combines with existing `closed_interval` / sampler path — not a replacement for daemon metering
- [ ] Check possibility to install either latest productive or pre-release version of Earnie



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
