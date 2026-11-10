# Multiple EVs and wallboxes, HouseSim wallbox write-back: design and implementation plan

**Status:** W1–W3 built and merged (2026-11-09); M1a, M1b, M2, M3 and M4 built. Decisions D1–D10 accepted by the maintainer on 2026-11-09 (D2 in its revised form: limits as current on both devices). D11 follows from D1–D3. Branch `feat/multi-ev-wallbox` (first named `docs/multi-ev-wallbox-design`), based on `main` at `fda24a4e`.
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

**M1b built 2026-11-09:**

- Hauskonfigurator tab **Wallboxen** (`ui/planning_wallbox_form.py`, store helpers `ui/house_config_wallbox_io.py`): label, voltage, phases, current range; the Kennung is set from the label on create and fixed afterwards (EV assignments and `evcs.<Kennung>.*` IDs point to it). An update that leaves an assigned EV without a common current and the delete of an assigned wallbox fail loud. Charger bindings stay on EHAL-Com (pair view).
- EV form: car phases and current range of their own (D2 in full) plus the wallbox choice (`wallbox_assignment`); a button creates a wallbox with the car limits at 230 V. The form no longer sends `wallbox_voltage_v` (importers still do) and drops the view's charger bindings, so a changed wallbox choice does not carry them over.
- Save routing: a view's wallbox limits are never written back; a view's charger bindings are applied as a diff against what the view showed (copied profiles show the same wallbox twice; an unchanged copy no longer undoes an edit).
- Two EVs of one house profile at the same fixed wallbox fail loud on load (`reject_shared_fixed_wallboxes`): until M3 every pair is planned on its own, so they would charge at the same time. Sharing a wallbox is `mode: dynamic`.
- `share/config` example: wallbox 3 phases 6–16 A at 230 V, car 1 phase 6–16 A (pair 1.38–3.68 kW, was 3.5 kW).
- No other page creates EVs: the Loxone greenfield import keeps its own wallbox per EV through the import key; the HA side has no EV import.

- `components.wallboxes[]` in schema, loaders and the Komponenten page; EV consumer fields as in D2; `ev.wallbox_assignment` (D3).
- Step `dm6.wallboxes`: one wallbox per EV consumer (Kennung = the consumer's Kennung, so `evcs.<Kennung>.*` IDs stay the same), charger bindings moved, the old `min_power_kw` / `nominal_power_kw` converted into current with the consumer's voltage and phases and written to **both** wallbox and EV (they described the pair, so the pair keeps exactly its old limits), `fixed` assignment. The same EV Kennung in several house profiles raises (Q1). Release notes helper picks it up.
- `power_limits_kw` and `ev_nominal_power_conversion` read the assigned wallbox. Earnie Points counts `wallboxes[]`. Loxone and HA greenfield import create a wallbox and an EV.
- **Tests:** migration of the example pack and of a pack with two EVs; the same EV Kennung in two profiles raises; golden-master regression unchanged (all packs migrate to `fixed`); points unchanged for migrated packs.

### M2: Several fixed pairs at runtime

- Replace `_first_ev_consumer`, `_first_ev_loxone_bindings` and `find_first_ev_consumer` with a loop over (EV, wallbox) pairs. Read plug state and power per wallbox, write current and mode per wallbox with that wallbox's voltage and phases.
- Cycle record and replay carry one entry per pair.
- **Done:** a site with two cars, each with its own wallbox, works. This is already useful without M3.
- **Tests:** two pairs, different phases; one pair's write failing does not stop the other; replay reproduces both.

**M2 built 2026-11-09** (pair view kept as the runtime form, maintainer decision; the readers move to EV + wallbox in M4):

- Adapters (HA, Loxone, OpenEMS) have `write_evcs_setpoints(charger_id, setpoint, voltage_v=, phases=)`; `write_setpoints` takes plant / ESS fields only and rejects EVCS fields. A failed charger write disables that charger only (`_evcs_disabled`), the others keep writing.
- `ehal_live.write_evcs_max_current_from_consumers` loops over `live_ev_consumers()`, one call per pair with the pair's voltage / phases; trace rows are `evcs.<Kennung>.set_evcs_*`; the first error is returned, every error is persisted.
- Charger Kennung = the EV's (`charger_id_for_ev`), as the pair view keys the charger bindings (`evcs.<EV>.*`); push IDs stay as they were. They become the wallbox's with the dynamic assignment (M4).
- HA: `aggregate_ha_entities` activates `evcs.<Kennung>.<kind>` for every EV (no plant fallback for charger fields); `setpoint_qualified_ids` keys EV charger setpoints by their qualified ID. `find_first_ev_consumer` is left only in the legacy flat-map migration (`migrate_ha_entities_to_house`, `apply_ha_entities_to_house`).
- Loxone adapter: `LoxoneConfig.evcs_markers` per charger; publishes the qualified ID (was the bare field).
- OpenEMS (maintainer, 2026-11-09: in M2, no separate issue): one component per wallbox, address `<component>/<channel>` in the wallbox binding `set_evcs_max_current` like the inverter limits; telemetry `sens_evcs_active_power` = sum over the wallbox components. `ehal.openems.evcs_component` is gone (config loader rejects it with a migration hint); `dm6.wallboxes` moves it (or the old default `evcs0` for a model-5 OpenEMS pack) onto the one wallbox, more than one wallbox → blocker. Packs already on model 6 with the key left are detected again.
- Write test (EHAL-Com Schreibtest): EVCS probes go through `write_evcs_setpoints` of their charger.
- Tests: adapter tests per charger incl. failure isolation (HA, Loxone, OpenEMS), two EVs with different phases on the HA live path, HouseSim end to end with two loadpoints (`tests/test_house_sim_two_pairs_end_to_end.py`, second loadpoint built in memory from `evcc_en`), OpenEMS migration. Not covered: a replay test with two pairs (the recorder already keys the EV reads per consumer; write rows are outputs, not replayed).

### M3: Assignment engine (Live)

- State per wallbox: `free` → `plugged_unknown` → `testing` → `assigned` → `free` on unplug. Evidence ladder D4, test charge D5, unknown-vehicle policy D6, restart D7.
- `runtime/ev_assignments.json` (display and record only). Monitor page: assignment per wallbox, source of the evidence, and a pick list for (d).
- **Tests:** in HouseSim with a new fixture of two evcc loadpoints and three cars: vehicle ID match; plug match; ambiguous plug → test charge → assigned; car without sensor → user pick; unplug clears; restart re-binds; test charge skipped during "Sofort laden"; unknown car follows its policy.

**M3 built 2026-11-09** (design above):

- Schema: `wallbox_assignment` `{"mode": "dynamic", "wallbox_ids": [...]}`; wallbox `unknown_vehicle` (`pv_only` needs `set_evcs_mode`); loader view of a dynamic EV (`resolve_dynamic_ev_view`: limits of the smallest pair, no charger bindings, `dynamic_wallboxes`); load rejects a missing policy, a missing `sens_evcs_connected` on a dynamic wallbox, `forecast_when_absent: true`, charger bindings on a dynamic EV, and a wallbox both fixed and dynamic in one profile. EV kinds `sens_ev_connected`, `sens_ev_charge_power`.
- Engine `optimizer/ev_assignment.py` (settings `AssignmentSettings`: poll 10 s, window 300 s, test 120 s, 500 W; module defaults, not in `config.json` yet). Driver `integrations/ev_assignment_live.py`: `start()` before the safe setpoints, `tick()` before the cycle reads consumers, `poll()` from `_daemon_wait_poll` (wakes a plan on change), the test charge only while setpoints are written (`should_invoke_setpoint_writes`; silent → no test, the wallbox waits for plug match or pick), `write_unassigned_wallboxes()` after the EV writes on every backend (through `write_evcs_setpoints` of the HA / OpenEMS / Loxone adapter), snapshot in `optimizer_run_state.ev_assignments`.
- Overlay `runtime_store/ev_assignments.py` in `settings.flexible_consumers.load_flexible_consumers` (`raw_dynamic=True` skips it): assigned → `assigned_dynamic_ev_view` with `charger_id` = wallbox; unassigned → dropped. `charger_id_of_ev` replaces `charger_id_for_ev(id)` at the call sites; `live_charger_consumers()` = fixed pairs + every dynamic wallbox (`dynamic_charger_consumers`), used for the Loxone markers, OpenEMS channels and write probes; HA activation, push read / setpoint IDs and the signal export list the dynamic wallboxes as `evcs.<Wallbox>.*`.
- UI: Monitor section **Wallboxen** (`ui/ev_assignment_panel.py`, pick → `runtime/ev_assignment_picks.json` + Request-Optimize); EV form „Wallbox-Zuordnung“ fixed / dynamic with allowed wallboxes (forecast switched off); Wallboxen tab „Unbekanntes Auto“; EHAL-Com row per dynamic wallbox (`wallbox` kind → `components.json`), dynamic EV rows show car fields only.
- Scenario Explorer / backtesting reject dynamic EVs (`simulation.engine_scenario._reject_dynamic_evs`) until M4 (D9).
- HouseSim fixture `evcc_multi_ev` (two loadpoints, three cars); tests `tests/test_ev_assignment_engine.py`, `tests/test_house_sim_ev_assignment_end_to_end.py` (plug match + plan follows the wallbox + unplug; simultaneous plug → test charges → restart re-binds; car without sensors charges by policy → user pick), `tests/test_wallbox_dynamic_assignment.py`, AppTest of the Monitor panel. "Sofort laden" skip and timeouts are covered in the engine tests only.
- **Not covered / open:** a live run on the HA testbed or a real site; the S4 integration with the new fixture in a running HA; the settings in `config.json`; the startup safe setpoints do not touch dynamic wallboxes (their policy goes out with the first cycle); evcc's own PV mode overriding the test current (risk noted below) is not modelled.

**M3 design agreed 2026-11-09** (maintainer, before the code):

- **Vehicle sensors:** two new optional EV fields `ev.<Kennung>.sens_ev_connected` (bool) and `ev.<Kennung>.sens_ev_charge_power` (W). Plug match (b) needs the first, the test charge (c) the second; a car without them is assigned by the user (d).
- **Vehicle ID (a) is not built in M3** (Q2: no source). No `sens_evcs_vehicle_id`, no `vehicle_ref`; the M3 test "vehicle ID match" is dropped. Open for later.
- **State:** a pure state machine (`optimizer/ev_assignment.py`) and a live driver (`integrations/ev_assignment_live.py`). The state lives in the daemon's memory only and is dropped on start (D7). `runtime/ev_assignments.json` is written on every change for display and the cycle record. The Monitor writes a pick request (`runtime/ev_assignment_picks.json`) and wakes the daemon; the daemon applies it only for the same plug session.
- **Hook:** the driver ticks at the start of every cycle and in the daemon's wait loop every `poll_sec`. The test charge runs in the wait loop and never delays a plan; an assignment or an unplug wakes a new plan at once. Plug match waits `match_window_sec` after the wallbox's plug edge before it decides. `poll_sec`, `match_window_sec`, `test_duration_sec` and `test_power_threshold_w` are documented settings.
- **Charger Kennung:** wallboxes used by dynamic EVs are addressed as `evcs.<Wallbox>.*` already in M3; fixed pairs keep `evcs.<EV>.*` until M4.
- **Planning:** a dynamic EV is planned only while it is assigned, with the limits of its pair. Not assigned → not planned (the pool of D8 is M4). `forecast_when_absent: true` on a dynamic EV is rejected on load until M4. The Scenario Explorer and backtesting reject dynamic EVs until M4 (D9).
- **Unknown vehicle:** `unknown_vehicle` is required on the wallboxes a dynamic EV may use (narrower than D6: a fixed wallbox always has its car). `off` → 0 A; `immediate` → the wallbox's maximum current, mode `now`; `pv_only` → mode `pv` of the vendor and therefore requires a `set_evcs_mode` binding on that wallbox. A wallbox is either fixed to one EV or open to dynamic EVs within one house profile.
- No new data model step: the new keys are optional and additive; only `mode: dynamic` is unlocked.

### M4: Planner and SE

- Pool constraints for dynamic EVs (D8) in the MILP, using the EVs' existing on-variables where they have them; plugged, assigned EVs planned with the limits of their pair (D2).
- SE rule D9, and the result says which car charged where.
- **Tests:** two dynamic cars, one wallbox: never both charging in one slot, the deadline that matters wins; three cars, two boxes; regression goldens unchanged for `fixed` packs.

**M4 design agreed 2026-11-10** (maintainer, before the code):

- **Occupied wallbox:** a wallbox that is not `free` in the engine at the start of the horizon (assigned, `plugged_unknown`, `testing`) stays out of the pool for the whole horizon; unplugging wakes a new plan. No assumption about departure times.
- **SE (D9):** one assignment per run from the `weekday` block; a `weekend` block that gives another assignment stops the run with a German message.
- **Pair view:** stays the derived planner input (never stored); the ~160 readers of `nominal_power_kw` are not rewritten. Only the charger Kennung of fixed pairs moves to the wallbox (`evcs.<Wallbox>.*`). This replaces "readers move to EV + wallbox in M4" (M2 note above).

**M4 built 2026-11-10:**

- Live overlay (`runtime_store.ev_assignments`): the engine's free wallboxes (`AssignmentEngine.free_wallboxes`) go with the assignments; a dynamic EV that is not assigned gets `pool_dynamic_ev_view` (`pool_wallbox_ids` = free allowed wallboxes, limits of the smallest free pair) instead of being dropped. Its charging context is never `plugged_in` (no plug read); `forecast_when_absent: true` → anticipated (connect prognosis), false → inactive; no free wallbox → inactive "keine freie Wallbox". The load no longer rejects `forecast_when_absent` on dynamic EVs; the EV form no longer disables it.
- MILP (`optimizer/milp_ev_pool.py`): per slot and per group of EVs sharing free wallboxes, for every wallbox subset `U`: Σ on of the EVs that may use only `U` ≤ |U| (Hall's condition, so the charging cars always fit onto distinct wallboxes), and Σ power of the group ≤ Σ wallbox maximum power. Existing on-variables only, no new binaries; at most 8 wallboxes per group (fails loud above). Pool EVs never take the preset path (`split_eauto_preset`), so only the MILP places them.
- Writes: pool EVs have no charger; `live_ev_consumers` leaves them out, `charger_id_of_ev` raises for them.
- Charger Kennung: `resolve_ev_pair` sets `charger_id` = wallbox and merges the wallbox bindings as `evcs.<Wallbox>.<kind>` (bare wallbox keys qualified with the wallbox, also in `assigned_dynamic_ev_view`); `qualified_consumer_id` keeps an `evcs.<X>.*` key's Kennung; `charger_id_for_ev` is gone. Saving a view keeps a stored bare wallbox key unless its value changed. Migrated packs (wallbox Kennung = EV Kennung) keep every ID.
- SE / backtesting (`simulation/ev_wallbox_fcfs.py`): D9 in `_flexible_consumers_from_scenario` (assigned EVs as pairs, an EV without free wallbox left out); the run log and `df.attrs["ev_wallbox_assignment"]` carry "car → wallbox"; the SE run panel shows the rule and the assignment per scenario before the start.
- Tests: `tests/test_milp_ev_pool.py` (two cars / one wallbox incl. control without pool, three cars / two wallboxes, different wallbox lists, pool view, charging contexts), `tests/test_se_ev_wallbox_fcfs.py`, `tests/test_wallbox_dynamic_assignment.py` (fixed pair charger = wallbox, pool EV has no charger), HouseSim end to end with pool views. Full suite green, regression 12/12 unchanged.
- **Solve time** (synthetic 36 h quarter-hour horizon on the test fixture config, anticipated cars with 20 kWh each, median of 5): 2 cars / 1 wallbox 0.45 s → 0.33 s with pool; 3 cars / 2 wallboxes 0.53 → 0.57 s; 4 cars / 2 wallboxes 0.78 → 0.80 s.
- **Not covered / open:** no live run (HA testbed or site); no full SE run with a dynamic EV (D9 is tested on the consumer resolution, not through `run_simulation`); a car plugged but not yet identified is still planned against the other free wallboxes until it is assigned; the user docs got only the M4 behaviour (pool, D9, charger Kennung), the rest stays with M5.

### M5: Docs and wrap-up

- German user docs (`docs/konfiguration/`, Monitor page), EHAL reference (`docs/referenz/ehal.md`: `sens_evcs_vehicle_id`, Kennung of a wallbox), `EHAL-Binding-UX-Draft.md` note on the first EV removed.
- Release notes draft. **Done:** closes **Enable multiple EV / Wallboxes**.

## Risks

- **Vehicle sensors are the weak point.** Many cars expose SoC only through a cloud integration with minutes of delay. Without a charge power or charging-state sensor, (c) cannot run and the user has to pick. M3 must show this clearly in the UI, not hide it.
- **Test charge and the vendor's own logic.** evcc or a go-e in its own PV mode may override a short current setpoint. W2 must model the vendor's modes closely enough that M3's tests mean something.
- **Pool constraints add binaries.** Measure solve time on the sample pack in M4, as the max-power tariff did for its caps.
