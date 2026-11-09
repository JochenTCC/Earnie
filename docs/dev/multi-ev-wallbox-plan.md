# Multiple EVs and wallboxes, HouseSim wallbox write-back: design and implementation plan

**Status:** W1–W3 built and merged (2026-11-09); M1a built, M1b open. Decisions D1–D10 accepted by the maintainer on 2026-11-09 (D2 in its revised form: limits as current on both devices). D11 follows from D1–D3. Branch `feat/multi-ev-wallbox` (first named `docs/multi-ev-wallbox-design`), based on `main` at `fda24a4e`.
**Backlog items:** **Enable multiple EV / Wallboxes** and **HouseSim wallbox write-back** (both Version 2.+1). The write-back is the test bench for the assignment, so this plan covers both. Target release: not decided.

## Goal

1. A site has any number of wallboxes and any number of EVs. An EV may charge at a fixed wallbox (today's case) or at any wallbox it is plugged into.
2. Earnie finds out which EV is at which wallbox: from the wallbox's vehicle detection, from matching plug events, by a short test charge, or by asking the user. It never guesses.
3. The plan and the setpoints follow the assignment. An EV that is not plugged in yet is planned against the free wallboxes, not against one wallbox picked at random.
4. HouseSim simulates wallbox setpoints as physics, so items 1–3 can be tested end to end without a real car.

Not in this plan: load management across wallboxes (a shared current limit for several boxes), bidirectional charging (V2H), phase switching 1p/3p during a session, and the HouseSim scenario series (it reuses the EV model built here).

## What the code has today

| Area | Finding | Where |
|---|---|---|
| Config | An EV is one consumer `type: "ev"` in a house profile. It carries both car properties (`battery_capacity_kwh`, schedules) and wallbox properties (`nominal_power_kw`, `min_power_kw`, `nominal_power_voltage_v`, `nominal_power_phases`) and both kinds of bindings. There is no wallbox entity. | `share/config/house_profiles.example.json`, `house_config/profiles_consumers.py:522` |
| Plant hardware | Inverters, batteries and PV systems are lists in `components.json`, each with its own `ehal_bindings`. That is the model for wallboxes. | `share/config/components.example.json` |
| EHAL namespaces | Exchange IDs already split one EV consumer into `evcs.<Kennung>.*` (charger fields) and `ev.<Kennung>.*` (vehicle fields), both with the consumer's Kennung. Storage stays flat on the consumer. | `ehal/qualified_ids.py` (`EVCS_KINDS`, `EV_KINDS`, `consumer_namespace`) |
| Plug state | `sens_evcs_connected` is a charger field, read through the EV consumer. The planner's context (`plugged_in`, `anticipated`) hangs on it. | `optimizer/charging_resolve.py:165,254` |
| Live write | One EV only: `_first_ev_consumer()` picks the first EV, its planned kW becomes `set_evcs_max_current` (and `set_evcs_mode` on HA). | `integrations/ehal_live.py:641,718`, `integrations/ehal_live_adapters.py:177,207` |
| HA bindings | `find_first_ev_consumer` in three places. | `house_config/ha_ehal_bindings.py:45,125,221,328` |
| Planner | Each EV consumer is planned on its own; the limits come from `power_limits_kw(consumer)`. Several EV consumers would plan, but nothing couples them through a shared wallbox. | `optimizer/eauto_milp.py`, `optimizer/charging_context.py` |
| kW ↔ A | Voltage and phases come from the consumer's `charging_schedule` (default 230 V, 1 phase). | `settings/ev_power.py` |
| Earnie Points | Counts wallboxes from EV consumers. | `house_config/earnie_points.py:161` |
| HouseSim | One `evcs_power_w` per house. `car_arrives(power_w)` / `car_leaves()` set a fixed override; `set_evcs_max_current` is mapped in the fixtures but has no effect on the physics. Only ESS setpoints act. No EV model, no plug sensor, one wallbox per fixture. | `house_sim/core/physics.py:68-86,258-262`, `house_sim/fixtures/*/ehal.ha.entities.json` |
| HouseSim fixtures | `evcc_en`: evcc loadpoint (`max_current`, `enable`). `fronius_de`, `huawei_en`: go-e / Wattpilot (`amp`, power `nrg_11`). `sma_keba`: KEBA P30, read-only. | `house_sim/fixtures/` |
| Docs | The binding UX draft already states that the adapter uses only the first EV and that multi-EV runtime is this item. | `docs/dev/EHAL-Binding-UX-Draft.md:263-268` |

## Decisions

All accepted on 2026-11-09 (maintainer). D2 was revised in the review: the first proposal kept a kW acceptance on the car; the maintainer wants the limits as current on both devices.

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | Where does a wallbox live? | New list `components.wallboxes[]`, next to `batteries[]`, with its own Kennung and `ehal_bindings`. EVs stay consumers in the house profiles. | A wallbox is plant hardware like a battery; the EV's schedules differ per house profile. |
| D2 | Which limits live where, and in which unit? | **Limits are currents, on both devices.** Wallbox: `voltage_v`, `phases`, `min_current_a`, `max_current_a`, the charger bindings (`sens_evcs_active_power`, `sens_evcs_connected`, `get_evcs_nominal_current`, `set_evcs_max_current`, `set_evcs_mode`) and a new optional `sens_evcs_vehicle_id`. EV: `phases`, `min_current_a`, `max_current_a`, capacity, schedules, SoC / limit / ready-by bindings, `min_on_quarterhours`. For a pair: minimum current = the larger minimum, maximum current = the smaller maximum, phases = the smaller count, power = current × voltage × phases. A pair whose minimum exceeds its maximum is a configuration error for that pair, never clamped. `nominal_power_kw` and `min_power_kw` are no longer stored; the UI shows the kW of a pair and converts a datasheet kW value (230 V, the car's phases) into current on input. | A kW value depends on the pair (voltage, phases); a current is a property of one device. A 1-phase car on a 3-phase box charges on one phase. |
| D3 | How is an EV bound? | `ev.wallbox_assignment`: `{"mode": "fixed", "wallbox_id": "<id>"}` or `{"mode": "dynamic", "wallbox_ids": [...]}` (the wallboxes this car may use). Required field; migration writes `fixed`. | `fixed` keeps every existing pack exactly as it is; `dynamic` is opt-in. |
| D4 | Evidence for an assignment, in order | (a) the wallbox reports a vehicle ID (`sens_evcs_vehicle_id`, e.g. evcc vehicle detection; RFID / OCPP `idTag` identify a user, not a car, and are not accepted, see Q2) that matches the EV's `vehicle_ref`; (b) one wallbox and one dynamic EV report "plugged" inside the matching window, and no other candidate is open; (c) test charge (D5); (d) the user picks the car on the Monitor page. If none applies, the wallbox stays "unknown vehicle" (D6). | Backlog: "both devices report connection, confirm by test charging". (a) is cheaper and exact where the hardware has it. No step guesses (`no-implicit-fallbacks.mdc`). |
| D5 | Test charge | Earnie sets the wallbox to its minimum current for at most 120 s and watches the candidates' charge power or charging state. Positive when exactly one candidate reacts. Only for EVs with such a sensor (SoC steps of 1 % are too slow); one wallbox at a time; never while the user forces "Sofort laden" or a manual mode. Window and duration are documented settings, not hidden constants. | About 0.05 kWh per test. Running boxes one after another keeps the reaction unambiguous. |
| D6 | Wallbox with an unknown vehicle | Per wallbox `unknown_vehicle`: `off`, `pv_only` or `immediate`. Required once any EV is `dynamic`; no default. | A guest car or a car without sensors must charge in a way the user chose, not in one Earnie assumed. |
| D7 | Unplug and restart | Unplugging the wallbox ends the assignment at once. On daemon start all assignments are dropped and the D4 ladder runs again (test charge allowed). The last assignments are kept in `runtime/ev_assignments.json` for display and the cycle record only, never as truth. | Backlog: "cancel assignments and re-bind in case of shutdown". While Earnie was down a car may have changed boxes; only the vehicle ID sensor could tell. |
| D8 | Planning a dynamic EV that is not plugged in | Per slot, the dynamic EVs that may arrive share the wallboxes they may use: Σ power ≤ Σ maximum power of those wallboxes that are free, and the number of charging cars ≤ the number of those wallboxes. A plugged and assigned EV takes its wallbox out of the pool and is planned with the limits of that pair (D2). A car that is not plugged in is planned with the smallest maximum power among the free wallboxes it may use, and re-planned with the real pair once plugged in. | Picking a wallbox for a future arrival would be a guess, and a wrong one would block the other car's plan. |
| D9 | SE (Scenario Explorer) | `fixed` behaves as today. `dynamic` in the SE: first come, first served by arrival time in the schedule, ties by EV Kennung, so the SE stays deterministic. | The SE has no plug events; it needs a fixed rule, and the rule must be visible in the result. |
| D10 | HouseSim EV model | The write-back builds a small EV model (plug state, SoC as an energy counter, current limits and phases as in D2). The HouseSim scenario series reuses it instead of building its own. | The assignment needs a car that reacts to a test charge. This changes the note under the series item that says the EV SoC model "builds on" the write-back. |
| D11 | Data model | `earnie_data_model` 6 with step `dm6.wallboxes` (`config-migration.mdc`). | Moving fields between files is a structural change. |

Questions for the maintainer:

- **Q1 (answered 2026-11-09):** An EV belongs to exactly one house profile. Profiles made by copying carry the same EV Kennung with identical data (seen in the migration fixtures): `dm6.wallboxes` gives those one shared wallbox when the charger data (current range, voltage, phases, charger bindings) are equal, and blocks with a German message when they differ. It never merges different data.
- **Q2 (answered 2026-11-09):** Wallboxes deliver no vehicle ID for now; the design does not rely on one. AC home charging runs on IEC 61851, which has no vehicle ID; ISO 15118 (EVCCID) is rare on AC and hardly exposed by home wallboxes. RFID is not accepted as evidence. Sites without a vehicle ID source (Loxone included) assign by D4 (b)–(d).
- **Q3:** Release: both items are under Version 2.+1. Whether W1–W3 or M1–M2 move into a release is not decided here.

## Phases

Each phase is one chat session and ends with green tests and a commit. **W** = HouseSim wallbox write-back, **M** = multiple EVs and wallboxes. W1–W3 and M1–M2 do not depend on each other; M3 needs W3 as its test bench.

### W1: HouseSim core — wallbox and EV physics

**Built 2026-11-09**, EV limits switched to current after D2 was revised: `house_sim/core/evcs.py`, wired into `step_physics` / `run_ticks`, S4 copy synced, tests `tests/test_house_sim_core_evcs.py`. Archetypes without `house_params.wallboxes` keep the fixed power override, so no shipped fixture changes until W2. Not built: the vendor entities that feed `WallboxSetpoints` (W2), persistence of the EV state in the S4 coordinator (W2).

- `house_params.wallboxes[]` (Kennung, voltage, phases, min / max current, `read_only`) and `house_params.evs[]` (Kennung, capacity, start SoC, min / max current, phases, optional vehicle ID).
- `WallboxSetpoints` per wallbox: `max_current_a`, `enabled` (from the vendor's enable or mode field). Read like `EssSetpoints` today.
- Charge power per wallbox: 0 when no car, not enabled, or the setpoint below the pair's minimum current; otherwise `I × U × min(phases)` with `I` capped at the pair's maximum current (D2); never above the car's remaining energy to 100 %. A `read_only` wallbox charges at the pair's maximum current while a car is connected (today's behaviour of `car_arrives`, now explicit). A pair whose minimum exceeds its maximum raises.
- The EV's SoC counts the charged energy. `car_arrives(ev=…, wallbox=…, soc=…)` and `car_leaves(wallbox=…)` replace the fixed power override; `evcs_power_w` in the state becomes the sum over wallboxes.
- **Tests:** current × voltage × phases; 1-phase car on 3-phase box; current below the pair's minimum gives 0; the car's maximum current caps; impossible pair raises; SoC stops at 100 %; disabled box gives 0; `read_only` keeps the old values of the existing core tests.

### W2: HouseSim vendor projections, S1–S4

**Built 2026-11-09:** per-wallbox and per-EV `entities` in `house_params` (setpoint, enable with off states, power, energy, plug, status mapping, vehicle name; EV SoC, plug, power), setpoints read from the mock store and the S4 coordinator, telemetry projected per entity unit; all four fixtures switched to the wallbox model; S4: `binary_sensor` platform, text sensor states, services `car_arrives` / `car_leaves` with wallbox and EV, EV state, switch and select states persisted across restarts. Tests `tests/test_house_sim_wallbox_writeback.py`. Kept: the mock store still rejects `switch` services (existing negative case). **Not verified:** the S4 integration in a running HA (no HA in the venv; files only compile-checked) — part of W3's bench run. Archetypes generated by `house_sim/archetype_gen.py` keep the fixed power path; a wallbox model there belongs to M1, when the pack has `components.wallboxes[]`.

- Writes in, sensors out per vendor: evcc (`number.*_max_current`, `switch.*_enable`, charge power, plug state, vehicle name), go-e / Wattpilot (`amp`, `frc` 0 neutral / 1 off / 2 on, `nrg_11`, `car` state), KEBA stays read-only (`sma_keba`).
- Mock REST (S1–S3) and the HA integration (S4); run `python -m scripts.sync_house_sim_integration` and keep `tests/test_house_sim_s4_packaging.py` green.
- HA services `car_arrives` / `car_leaves` take the wallbox and the EV.
- **Tests:** fixtures `evcc_en`, `fronius_de`, `huawei_en`: a written current changes `sens_evcs_active_power` and grid power in the next tick; `sma_keba` ignores writes; `reject_writes` fault still applies to wallbox writes.

### W3: Earnie against HouseSim — one EV end to end

**S4 bench run (2026-11-09, HA `2025.7.0` testbed):** the new integration loaded the existing `earnie_pack` entry unchanged (`scripts.ha_testbed_check --require-all` 10/10 before and after); a second entry `evcc_en` created through the config flow REST API. Checked there: `car_arrives` without `archetype` rejected (400) while two simulators run; plug `binary_sensor` `on`, vehicle `Car A`, 10 A → 6900 W, car SoC rising, grid power following; enable switch off → 0 W, on → 6900 W; after `docker restart` the car stays plugged, SoC continues from the saved value, 10 A and switch state kept; `car_leaves` → plug `off`, vehicle `""`, 0 W. No integration errors in the HA log. Afterwards the test entry was deleted and the previous integration copy restored; check 10/10 again. New for this run: every service takes an optional `archetype`, required when several simulators run.

**Built 2026-11-09:** `house_sim/vendor_bridge.py` plays the HA carrier automations between the contract entities and a vendor archetype (setpoints contract → vendor, telemetry vendor → contract, plug `on`/`off` → `1`/`0`). `tests/test_house_sim_ev_end_to_end.py`: Earnie publishes `evcs.car_a.set_evcs_max_current` (kW → A with the consumer's voltage and phases), the push harness applies it, `evcc_en` charges the car, charge power, grid power, plug and car SoC come back through Earnie's push inbox, and Earnie's own read path (`fetch_loxone_actual_soc_percent`, `read_generic_value` on the plug marker) sees them; 0 A stops the car, unplugging is seen. **Not covered:** the setpoint is published with `ehal_write.write_field`, not by the planner through `write_evcs_max_current_from_consumers` (that needs the full live config). M2 replaces that function anyway (one write per wallbox) and tests it there.

- Contract test: Earnie plans one EV, writes `set_evcs_max_current`, HouseSim charges, the grid power and the EV SoC follow, the planner's next context sees the new SoC.
- `docs/dev/house-sim.md`: wallbox and EV parameters, services, what each fixture can do.
- **Done:** the existing single-EV path is tested against simulated physics. This closes **HouseSim wallbox write-back**.

### M1: Schema and migration (no behaviour change)

**M1a built 2026-11-09** (approach agreed with the maintainer: a pair resolver in the loader instead of rewriting the runtime readers now):

- Data model 6; `house_config/wallboxes.py` (wallbox normalize / serialize, EV current fields, `pair_limits`, `resolve_ev_pair`, `route_evs_to_wallboxes`); `components.json` keeps `wallboxes[]` through load / save; the house loader reads the wallboxes next to the house file like the heating catalog.
- **Pair view:** the loader fills `nominal_power_kw` / `min_power_kw` (rounded to 9 digits against float noise), `charging_schedule.nominal_power_voltage_v` / `_phases` and the wallbox's charger bindings (`evcs.<Wallbox>.*` rewritten to `evcs.<EV>.*`) into the normalized EV. All runtime readers stay unchanged until M2. Only the new shape is stored; a pre-dm6 EV fails loud with the migration hint.
- **Saves:** `route_evs_to_wallboxes` (Hauskonfigurator and every `save_house_profiles` editor: EHAL-Com, signal list, greenfield import) writes the wallbox side of an EV to `components.json` (form pair limits, charger bindings edited on the view) and drops the view keys. The serializer refuses a charger binding on the EV that differs from its wallbox.
- **Step `dm6.wallboxes`:** as below; also activates `evcs.<Kennung>.set_evcs_max_current` on the wallbox (the required key moved from the EV, `required_signal_activation`) and stamps every Earnie-track file to 6. `dm5.netznutzung_split` now detects models 3 / 4 only (it stamped every older pack before).
- Form: one set of limits (phases, min / max current, wallbox voltage) written to car **and** wallbox, kW shown. Earnie Points count distinct wallboxes. Greenfield EV stub in currents. Viability study generator writes wallboxes.
- Repo packs migrated: `share/config` templates, `studies/poc_cloud`, `tests/fixtures/backtesting`, migration goldens. Untracked local packs (`studies/viability/packs_*`, `greenfield/config`, `ha_lab/testbed/config`, the site config) migrate through the wizard / `scripts.migrate_config`.
- Tests: full suite green, golden-master regression 12/12 unchanged (incl. the private replay cases, migrated in memory).

**M1b (open):** wallbox list on the Komponenten page (label, voltage, phases, currents, bindings) and separate car limits in the EV form (D2 in full: car and wallbox may differ); readable example values in `share/config` (the migrated example keeps 15.217… A for 3.5 kW); HA greenfield / binding pages that create EVs, if any remain.

- `components.wallboxes[]` in schema, loaders and the Komponenten page; EV consumer fields as in D2; `ev.wallbox_assignment` (D3).
- Step `dm6.wallboxes`: one wallbox per EV consumer (Kennung = the consumer's Kennung, so `evcs.<Kennung>.*` IDs stay the same), charger bindings moved, the old `min_power_kw` / `nominal_power_kw` converted into current with the consumer's voltage and phases and written to **both** wallbox and EV (they described the pair, so the pair keeps exactly its old limits), `fixed` assignment. The same EV Kennung in several house profiles raises (Q1). Release notes helper picks it up.
- `power_limits_kw` and `ev_nominal_power_conversion` read the assigned wallbox. Earnie Points counts `wallboxes[]`. Loxone and HA greenfield import create a wallbox and an EV.
- **Tests:** migration of the example pack and of a pack with two EVs; the same EV Kennung in two profiles raises; golden-master regression unchanged (all packs migrate to `fixed`); points unchanged for migrated packs.

### M2: Several fixed pairs at runtime

- Replace `_first_ev_consumer`, `_first_ev_loxone_bindings` and `find_first_ev_consumer` with a loop over (EV, wallbox) pairs. Read plug state and power per wallbox, write current and mode per wallbox with that wallbox's voltage and phases.
- Cycle record and replay carry one entry per pair.
- **Done:** a site with two cars, each with its own wallbox, works. This is already useful without M3.
- **Tests:** two pairs, different phases; one pair's write failing does not stop the other; replay reproduces both.

### M3: Assignment engine (Live)

- State per wallbox: `free` → `plugged_unknown` → `testing` → `assigned` → `free` on unplug. Evidence ladder D4, test charge D5, unknown-vehicle policy D6, restart D7.
- `runtime/ev_assignments.json` (display and record only). Monitor page: assignment per wallbox, source of the evidence, and a pick list for (d).
- **Tests:** in HouseSim with a new fixture of two evcc loadpoints and three cars: vehicle ID match; plug match; ambiguous plug → test charge → assigned; car without sensor → user pick; unplug clears; restart re-binds; test charge skipped during "Sofort laden"; unknown car follows its policy.

### M4: Planner and SE

- Pool constraints for dynamic EVs (D8) in the MILP, using the EVs' existing on-variables where they have them; plugged, assigned EVs planned with the limits of their pair (D2).
- SE rule D9, and the result says which car charged where.
- **Tests:** two dynamic cars, one wallbox: never both charging in one slot, the deadline that matters wins; three cars, two boxes; regression goldens unchanged for `fixed` packs.

### M5: Docs and wrap-up

- German user docs (`docs/konfiguration/`, Monitor page), EHAL reference (`docs/referenz/ehal.md`: `sens_evcs_vehicle_id`, Kennung of a wallbox), `EHAL-Binding-UX-Draft.md` note on the first EV removed.
- Release notes draft. **Done:** closes **Enable multiple EV / Wallboxes**.

## Risks

- **Vehicle sensors are the weak point.** Many cars expose SoC only through a cloud integration with minutes of delay. Without a charge power or charging-state sensor, (c) cannot run and the user has to pick. M3 must show this clearly in the UI, not hide it.
- **Test charge and the vendor's own logic.** evcc or a go-e in its own PV mode may override a short current setpoint. W2 must model the vendor's modes closely enough that M3's tests mean something.
- **Pool constraints add binaries.** Measure solve time on the sample pack in M4, as the max-power tariff did for its caps.
