# Multiple EVs and wallboxes, HouseSim wallbox write-back: design and implementation plan

**Status:** design draft (2026-11-09), nothing implemented. All decisions below are **proposals** until the maintainer accepts them. Branch `docs/multi-ev-wallbox-design`, based on `main` at `fda24a4e`.
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

## Decisions (proposals)

| # | Question | Proposal | Why |
|---|---|---|---|
| D1 | Where does a wallbox live? | New list `components.wallboxes[]`, next to `batteries[]`, with its own Kennung and `ehal_bindings`. EVs stay consumers in the house profiles. | A wallbox is plant hardware like a battery; the EV's schedules differ per house profile. |
| D2 | What moves to the wallbox? | Voltage, phases, minimum and maximum current (A), the charger bindings (`sens_evcs_active_power`, `sens_evcs_connected`, `get_evcs_nominal_current`, `set_evcs_max_current`, `set_evcs_mode`) and a new optional `sens_evcs_vehicle_id`. The EV keeps capacity, schedules, SoC / limit / ready-by bindings, `min_on_quarterhours`, and gets `max_charge_power_kw` (what the car accepts) and optional `max_phases`. `min_power_kw` is no longer stored: it is the wallbox's minimum current × voltage × effective phases. | Each property is stored once, on the device that has it. A 1-phase car on a 3-phase box charges on one phase, so the effective phases are `min(wallbox, car)`. |
| D3 | How is an EV bound? | `ev.wallbox_assignment`: `{"mode": "fixed", "wallbox_id": "<id>"}` or `{"mode": "dynamic", "wallbox_ids": [...]}` (the wallboxes this car may use). Required field; migration writes `fixed`. | `fixed` keeps every existing pack exactly as it is; `dynamic` is opt-in. |
| D4 | Evidence for an assignment, in order | (a) the wallbox reports a vehicle ID (`sens_evcs_vehicle_id`, e.g. evcc vehicle detection, RFID) that matches the EV's `vehicle_ref`; (b) one wallbox and one dynamic EV report "plugged" inside the matching window, and no other candidate is open; (c) test charge (D5); (d) the user picks the car on the Monitor page. If none applies, the wallbox stays "unknown vehicle" (D6). | Backlog: "both devices report connection, confirm by test charging". (a) is cheaper and exact where the hardware has it. No step guesses (`no-implicit-fallbacks.mdc`). |
| D5 | Test charge | Earnie sets the wallbox to its minimum current for at most 120 s and watches the candidates' charge power or charging state. Positive when exactly one candidate reacts. Only for EVs with such a sensor (SoC steps of 1 % are too slow); one wallbox at a time; never while the user forces "Sofort laden" or a manual mode. Window and duration are documented settings, not hidden constants. | About 0.05 kWh per test. Running boxes one after another keeps the reaction unambiguous. |
| D6 | Wallbox with an unknown vehicle | Per wallbox `unknown_vehicle`: `off`, `pv_only` or `immediate`. Required once any EV is `dynamic`; no default. | A guest car or a car without sensors must charge in a way the user chose, not in one Earnie assumed. |
| D7 | Unplug and restart | Unplugging the wallbox ends the assignment at once. On daemon start all assignments are dropped and the D4 ladder runs again (test charge allowed). The last assignments are kept in `runtime/ev_assignments.json` for display and the cycle record only, never as truth. | Backlog: "cancel assignments and re-bind in case of shutdown". While Earnie was down a car may have changed boxes; only the vehicle ID sensor could tell. |
| D8 | Planning a dynamic EV that is not plugged in | Per slot, the dynamic EVs that may arrive share the wallboxes they may use: Σ power ≤ Σ maximum power of those wallboxes that are free, and the number of charging cars ≤ the number of those wallboxes. A plugged and assigned EV takes its wallbox out of the pool and is limited by `min(car, wallbox)`. | Picking a wallbox for a future arrival would be a guess, and a wrong one would block the other car's plan. |
| D9 | SE (Scenario Explorer) | `fixed` behaves as today. `dynamic` in the SE: first come, first served by arrival time in the schedule, ties by EV Kennung, so the SE stays deterministic. | The SE has no plug events; it needs a fixed rule, and the rule must be visible in the result. |
| D10 | HouseSim EV model | The write-back builds a small EV model (plug state, SoC as an energy counter, acceptance in kW, charging state). The HouseSim scenario series reuses it instead of building its own. | The assignment needs a car that reacts to a test charge. This changes the note under the series item that says the EV SoC model "builds on" the write-back. |
| D11 | Data model | `earnie_data_model` 6 with step `dm6.wallboxes` (`config-migration.mdc`). | Moving fields between files is a structural change. |

Open questions for the maintainer:

- **Q1:** Do several house profiles define the same EV (same Kennung)? Then `dm6.wallboxes` creates one wallbox per distinct set of charger bindings, not one per profile entry. The private pack must be checked before M1.
- **Q2:** Loxone: does the Wallbox block report a vehicle ID or only plug state? If only plug state, Loxone sites with two cars depend on (b)–(d).
- **Q3:** Release: both items are under Version 2.+1. Whether W1–W3 or M1–M2 move into a release is not decided here.

## Phases

Each phase is one chat session and ends with green tests and a commit. **W** = HouseSim wallbox write-back, **M** = multiple EVs and wallboxes. W1–W3 and M1–M2 do not depend on each other; M3 needs W3 as its test bench.

### W1: HouseSim core — wallbox and EV physics

- `house_params.wallboxes[]` (Kennung, voltage, phases, min / max current, `read_only`) and `house_params.evs[]` (Kennung, capacity, start SoC, acceptance kW, phases, optional vehicle ID).
- `WallboxSetpoints` per wallbox: `max_current_a`, `enabled` (from the vendor's enable or mode field). Read like `EssSetpoints` today.
- Charge power per wallbox: 0 when no car, not enabled, or current below the minimum; otherwise `min(I × U × min(phases), acceptance)`; never above the car's remaining energy to 100 %. A `read_only` wallbox charges at the car's acceptance while a car is connected (today's behaviour of `car_arrives`, now explicit).
- The EV's SoC counts the charged energy. `car_arrives(ev=…, wallbox=…, soc=…)` and `car_leaves(wallbox=…)` replace the fixed power override; `evcs_power_w` in the state becomes the sum over wallboxes.
- **Tests:** current × voltage × phases; 1-phase car on 3-phase box; current below minimum gives 0; acceptance caps; SoC stops at 100 %; disabled box gives 0; `read_only` keeps the old values of the existing core tests.

### W2: HouseSim vendor projections, S1–S4

- Writes in, sensors out per vendor: evcc (`number.*_max_current`, `switch.*_enable`, charge power, plug state, vehicle name), go-e / Wattpilot (`amp`, `frc` 0 neutral / 1 off / 2 on, `nrg_11`, `car` state), KEBA stays read-only (`sma_keba`).
- Mock REST (S1–S3) and the HA integration (S4); run `python -m scripts.sync_house_sim_integration` and keep `tests/test_house_sim_s4_packaging.py` green.
- HA services `car_arrives` / `car_leaves` take the wallbox and the EV.
- **Tests:** fixtures `evcc_en`, `fronius_de`, `huawei_en`: a written current changes `sens_evcs_active_power` and grid power in the next tick; `sma_keba` ignores writes; `reject_writes` fault still applies to wallbox writes.

### W3: Earnie against HouseSim — one EV end to end

- Contract test: Earnie plans one EV, writes `set_evcs_max_current`, HouseSim charges, the grid power and the EV SoC follow, the planner's next context sees the new SoC.
- `docs/dev/house-sim.md`: wallbox and EV parameters, services, what each fixture can do.
- **Done:** the existing single-EV path is tested against simulated physics. This closes **HouseSim wallbox write-back**.

### M1: Schema and migration (no behaviour change)

- `components.wallboxes[]` in schema, loaders and the Komponenten page; EV consumer fields as in D2; `ev.wallbox_assignment` (D3).
- Step `dm6.wallboxes`: one wallbox per EV consumer (Kennung = the consumer's Kennung, so `evcs.<Kennung>.*` IDs stay the same), charger fields and bindings moved, `max_charge_power_kw` = old `nominal_power_kw`, `fixed` assignment. Release notes helper picks it up.
- `power_limits_kw` and `ev_nominal_power_conversion` read the assigned wallbox. Earnie Points counts `wallboxes[]`. Loxone and HA greenfield import create a wallbox and an EV.
- **Tests:** migration of the example pack and of a pack with two EVs; golden-master regression unchanged (all packs migrate to `fixed`); points unchanged for migrated packs.

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

- Pool constraints for dynamic EVs (D8) in the MILP, using the EVs' existing on-variables where they have them; plugged, assigned EVs limited by `min(car, wallbox)`.
- SE rule D9, and the result says which car charged where.
- **Tests:** two dynamic cars, one wallbox: never both charging in one slot, the deadline that matters wins; three cars, two boxes; regression goldens unchanged for `fixed` packs.

### M5: Docs and wrap-up

- German user docs (`docs/konfiguration/`, Monitor page), EHAL reference (`docs/referenz/ehal.md`: `sens_evcs_vehicle_id`, Kennung of a wallbox), `EHAL-Binding-UX-Draft.md` note on the first EV removed.
- Release notes draft. **Done:** closes **Enable multiple EV / Wallboxes**.

## Risks

- **Vehicle sensors are the weak point.** Many cars expose SoC only through a cloud integration with minutes of delay. Without a charge power or charging-state sensor, (c) cannot run and the user has to pick. M3 must show this clearly in the UI, not hide it.
- **Test charge and the vendor's own logic.** evcc or a go-e in its own PV mode may override a short current setpoint. W2 must model the vendor's modes closely enough that M3's tests mean something.
- **Pool constraints add binaries.** Measure solve time on the sample pack in M4, as the max-power tariff did for its caps.
