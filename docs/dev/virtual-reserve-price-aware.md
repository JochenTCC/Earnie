# Virtual reserve: hold it only when it pays, release it promptly

Status: draft, 2026-11-22. P1 (prompt release) implemented 2026-11-22, live check
open; P4 (idle drain) implemented 2026-11-22, not yet configured live; P2 (price-aware
floor) implemented 2026-11-22, live check open; P3 (tolerance at the floor) implemented
2026-11-22, live check open. Backlog: epic **Reserve**
(`backlog/Backlog.md`).

## Problem

A virtual powerstation carves a reserve out of the house battery for an appliance
(2.7.g, 2.7.p). The reserve raises the battery's `min_soc` to a floor for the whole
horizon, and a SoC below that floor has to be refilled at once
(`optimizer/milp_soc_recovery.py`).

Live pattern on the maintainer's plant (15 kWh battery, `min_soc` 5 %, 1.1 kWh of
virtual reserves, floor 12.33 %), 2026-11-21:

- The idle battery loses about 1 % SoC per hour, also with a discharge limit of 0.
- The SoC is read in whole percent. At a reading of 12 % the floor is relaxed to the
  reading (ping-pong fix of 2026-11-03). At 11 % it is not, and the plan forces a grid
  charge of 0.9 kW for one slot, at whatever the price is.
- At a reading of 13 % Automatik releases 0.34 kW of discharge for one slot, which
  brings the next refill forward.
- Result for the day: 22 forced charge slots, 4.05 kWh charged and 1.52 kWh discharged
  with the SoC unchanged at about 12 %. Prices were between 25 and 37 ct/kWh.

Two more findings from the same data:

- **Late release.** The appliance trigger is only checked inside an optimization run
  (`sync_triggers_from_telemetry`). An appliance that starts right after a run draws
  from the grid for up to 15 minutes before the floor opens.
- **Idle drain is not in the model.** The battery has `standby_power_kw` = 0.026 as an
  AC load. In hold mode the SoC fell from 12 % to 8 % in 4.75 h, which is about 125 W
  from the battery. The battery power sensor showed 0.05 kW at most. At the device's
  own minimum SoC the battery stayed at 5 % with about 20 W from the AC side (one hour
  of data only).

The hold interface itself works: in Entladesperre (Huawei command 1, target SoC =
current SoC) there was no charge pulse in 4.75 h.

## Decisions taken (maintainer, 2026-11-22)

- After a trigger the plan decides when the released energy is used. The battery does
  not have to feed the appliance itself.
- The release must follow the appliance start promptly, not at the next quarter hour.
- The reserve is only held when feeding from the battery would be cheaper than the grid
  at that time. In a cheap phase no reserve is needed. It is built up before the price
  rises, from energy that was cheap.

## Design

### 1. Prompt release (Reserve P1)

The daemon's wait loop already samples live power every 30 s for the quarter-hour means
(`on_poll` in `optimizer/run_trigger.py`). The same tick checks the appliances of
reserves that hold energy. On a trigger it latches the reserve (`set_trigger`) and ends
the wait with a new out-of-band label, next to `request_optimize`.

- One extra run per appliance start: the latch stays until the reserve is empty.
- No wake when the next regular run is about to start anyway (early-start lead).
- Delay: up to 30 s for the sample plus the run itself (60 to 90 s on the maintainer's
  NAS). Faster would mean opening the discharge limit without a new plan, which
  contradicts "the plan decides".
- A hub can already do the same from outside by sending `Earnie_Request_Optimize` when
  the appliance starts. That needs no code and stays possible.
- Review fixes 2026-11-22: a run that plans an earlier slot than the one it ends in (a
  release run started shortly before the tick) is followed at once by a regular run for the
  current slot (`start_scheduler.missed_slot_start`), instead of the old setpoints staying
  until the tick after. Failed live reads in the wait-loop check are logged once per source
  and wait (`powerstation_live.WaitReadErrors`), not swallowed; the loop goes on. Signals
  only present in the cycle telemetry are not seen by the wait loop.

### 2. Price-aware floor per slot (Reserve P2)

Today the floor is one value for all slots. The battery's energy variables are already
created per slot with their own lower bound (`e_batt_{id}_{t}` in
`optimizer/milp_horizon.py`), so a floor per slot is a vector that is computed before
the model is built:

    floor[t] = base min_soc energy + reserve kWh   if the reserve pays in slot t
    floor[t] = base min_soc energy                 otherwise

The reserve pays in slot `t` when

    price[t] > fill_price(t) / eta_roundtrip + hold_cost

- `fill_price(t)`: the cheapest import price in the slots before `t`. PV surplus needs
  no special case in the rule: the model picks the source, the rule only decides
  whether the floor applies.
- `eta_roundtrip`: charge and discharge path of the battery.
- `hold_cost`: idle drain over the expected holding time (see P4), so a reserve that
  barely pays is not held.

The model then builds the reserve up by itself: the floor at `t` forces the energy to be
there, and the cost objective picks the cheapest slots before `t`. This is the same
principle as the EV deadline (energy due at a time, cheapest slots before it) and as the
reserve's own refill deadline from 2.7.p (`_add_virtual_reserve_deadline_charge`). The
difference to the EV: the car takes the energy away at the deadline, the reserve has to
stay in the battery for the whole expensive window. That is a bound on the stored
energy, not a sum of charge power, and it is the simpler of the two.

Consequences:

- The fixed refill deadline (24 h after the reserve was emptied) is replaced by "the
  start of the next slot in which the reserve pays". With flat prices no slot pays and
  nothing is refilled.
- A reserve that is full when a cheap phase starts is not forced out. The floor drops,
  and the plan uses the energy only if that pays, as with any other stored energy.
- The Automatik discharge cap (`reserve_floor_discharge_cap_kw`) uses the floor of the
  current slot. Without a floor there is no cap.
- With example prices of 2026-11-21 (minimum 25.4 ct): at a round trip of 0.88 the
  reserve pays above about 29 ct, at 0.77 above about 33 ct. Either way the midday and
  the cheap night hours need no reserve.

Alternative considered: model the appliance run as an expected load with a probability
per slot and let the objective value the reserve. More general, but it needs a start
time distribution per appliance. Not for the first version.

Implemented (2026-11-22), decisions by the maintainer the same day:

- **Rule** (`optimizer/reserve_price_floor.py::reserve_price_floor`): slot `t` pays when
  `price[t] > min over fill sources of (fill / eta_rt + hold)`. Prices are the matrix's
  `k_act`. Fill sources are the slots `s < t` of the horizon and the persisted fill basis.
- **`eta_roundtrip` = `efficiency²`**: the MILP applies `efficiency` once per direction
  (`p_charge · eff`, `p_discharge / eff`).
- **Hold cost** per kWh of reserve: `fill / efficiency · idle_drain_hold_kwh(hold_h) / R`,
  i.e. the drain over the hold time, bought again through the charge path and spread over
  the reserve `R`. Hold time from a horizon slot `s`: `(t − s) · dt`; from the basis:
  `t · dt`, from the start of slot 0 (review fix 2026-11-22). For energy already stored the
  fill price and the hold time up to now are sunk; only keeping it from now on costs. The
  first version counted the hold from the basis timestamp, so the hold cost grew every cycle
  and the floor dropped about 2 h into a long expensive phase. The basis timestamp stays the
  record of when the energy was bought. Without a drain the hold cost is 0.
- **Energy already stored (option A).** The matrix has no past prices, so with horizon
  slots alone every re-plan inside an expensive phase would see only expensive slots
  before `t` and drop the floor. The reserve state keeps a fill basis per virtual reserve
  (`fill_basis_price`, `fill_basis_at` in `runtime_store/powerstation_reserves.json`; no
  pack JSON change). After each live plan (`powerstation_live.update_reserve_fill_basis`,
  called from `main.py` after the setpoint writes, so a failure there never leaves the slot
  without control): if the floor is held at the end of slot 0, the fill price and
  time behind the first paying slot become the basis; otherwise the basis is cleared
  (cheap phase). A trigger (`set_trigger`) and an emptied reserve clear it too. The
  cheapest basis among the virtual reserves reaches the MILP as
  `_virtual_reserve_basis_price` / `_virtual_reserve_basis_at`.
- **Slot 0** has no slot before it and pays only through the basis.
- **Fill times** of the horizon slots that justify a paying slot are validated
  (`slot_datetime`, tz-aware) inside `reserve_price_floor`, i.e. before the MILP is built;
  a missing one fails loud there and not later when the basis is persisted.
- **Start below `min_soc`** (`milp_soc_recovery`): the recovery is forced (`recovered = 1`)
  in the first slot whose bound is above the base, so the solver cannot charge without it
  and skip the floor. That bound is reachable by construction (`reachable_floor_kwh`).
- **Where the floor binds.** `e_batt[k]` is the energy at the end of slot `k`. It carries
  the reserve when slot `k` or slot `k + 1` pays, so the reserve is there during the whole
  paying slot (start and end). Elsewhere the bound is the base `min_soc`.
- **Reserve size** `R` = protected + still missing kWh of all virtual reserves that are not
  released (the target). `min_soc` stays the configured value; the floor SoC sits in
  `_virtual_reserve_floor_soc`, the reserve in `_virtual_reserve_kwh`.
- **Reachability.** A floor above `e_init + (k + 1) · (max_charge · eff − idle_drain) · dt`
  is lowered to that value (never below the base), with a warning: the reserve is built as
  fast as possible and the plan stays feasible (as the refill shortfall rule of
  2026-11-18). PV and grid limits are not in this estimate.
- **Refill.** `_add_virtual_reserve_deadline_charge`, `REFILL_DEADLINE_H` and
  `refill_deadline_utc` are gone. The energy bound replaces the charge-sum constraint: the
  reserve counts as built when the energy is there, whatever its source.
- **SoC recovery** (`milp_soc_recovery`) uses the configured base `min_soc` to decide
  whether a battery starts below its limits and leads it back to each slot's own bound. A
  start between base and floor needs no recovery.
- **Reading resolution.** `relax_reserve_floor_for_soc_reading` lowers the floor SoC of
  the paying slots to a reading at most one step below it. *(Replaced by the band of P3.)*
- **Automatik cap** (`reserve_floor_discharge_cap_kw`, now with the matrix): the energy
  above the end-of-slot-0 floor; `None` when the reserve is not held in slot 0.
- **Sunrise anchor.** PV-only charging through sunrise is skipped when a paying slot up to
  the sunrise slot needs more energy than the start energy minus the drain.
- **UI** (Manuelle Geräte): the caption no longer shows a deadline; it says that the reserve
  is refilled before the next slot where it pays.

Open after P2: the regression replay of 2026-11-21 (forced charge slots per day, 22 then);
the reserve state's `stored_kwh` is still advanced by charge attribution
(`advance_virtual_reserves_from_plan`), independent of whether the plan held the floor —
it only drives the state shown in the UI and the release bookkeeping.

### 3. Tolerance at the floor (Reserve P3)

In the slots where the floor applies, the whole-percent reading still causes pulses.

- Symmetric tolerance: a reading one step above the floor releases no discharge (today
  0.34 kW for one slot at 13 %).
- Refill band: energy missing below the floor is refilled only when the gap exceeds a
  band, and then in one block to the floor plus the band. The band has to cover at least
  two reading steps.
- A gap inside the band is not "refill at once". It is due at the next slot where the
  reserve pays, like the build-up in P2.

Open: size of the band (fixed in percent, or from the idle drain and the slot length).

Implemented (2026-11-22):

- **One rule** (`optimizer/reserve_price_floor.py::banded_floor_kwh`), applied after the P2
  floor and before the reachability cap (`effective_floor_kwh`). Both the MILP bound
  (`milp_horizon._apply_reserve_price_floor`) and the Automatik cap
  (`reserve_floor_discharge_cap_kw`) take the floor from `effective_floor_kwh`, with the start
  energy from the SoC reading. Only the paying run that starts at slot 0 changes; later paying
  runs keep the full floor, so a gap inside the band is due at the next paying run and built in
  the cheapest slots before it (as in P2).
- **Zones** (`F` floor, `s` one reading step `SOC_READING_RESOLUTION_PCT`, `B` band, `d` drain
  per slot):
  - `e_init > F + s`: unchanged; the energy above the floor is free energy.
  - `F − B ≤ e_init ≤ F + s`: hold. Bound at the end of slot `k`: `e_init − d · (k + 1)`, the
    energy the drain alone leaves. No discharge (the Automatik cap is 0 at 13 % over 12.33 %),
    no charge.
  - `e_init < F − B`: one block up to the floor. Bound `F` at the end of slot 0, `F − d · k`
    after it, so the block is the gap plus the drain of slot 0 and nothing is topped up later.
    A block the battery cannot charge in one slot is spread by `reachable_floor_kwh`.
  - All bounds stay at or above the base `min_soc`.
- **Bound follows the drain, not held at `F − B`.** A bound held at the band bottom makes the
  plan top up the drain in small charges; with equal prices the solver puts them in slot 0
  (seen in the tests: 0.21 kW at a reading of 11 %). The band bottom is therefore enforced by
  the next cycles: once the reading leaves the band, slot 0 gets the refill block. The plan
  inside the band is optimistic by the refill it does not show.
- **Up to the floor, not floor + band.** Energy above `F + s` is free energy (P2): a block to
  `F + B` would read two steps above the floor at the next cycle, and the plan or Automatik
  would release it again, which is the next pulse. A block up to `F` lands in the tolerance
  zone and is held until the drain takes it below the band.
- **Band size** (`reserve_floor_band_soc_pct`): `max(BAND_MIN_READING_STEPS · s, drain over
  BAND_HOLD_SLOTS slots)` with `BAND_MIN_READING_STEPS = 2`, `BAND_HOLD_SLOTS = 8`; the drain via
  `idle_drain_hold_kwh`. Without a drain the band is 2 %. With 1 %/h on 15 kWh and 15-minute
  slots it is 2 % (the minimum), a block lasts about 2.5 h.
- **Automatik cap** subtracts the drain of slot 0 from the start energy before it compares with
  the floor of slot 0 (the floor follows the drain, so otherwise the drain would be released).
- **Removed:** `relax_reserve_floor_for_soc_reading` and the `current_soc` argument of
  `prepare_battery_params_for_reserves` / `apply_reserves_to_battery_params` (live and the
  recorder replay); the floor key keeps the reserve floor, the reading enters through the MILP
  start energy.
- **Replay** (`tests/test_reserve_floor_band.py`): a day of 96 live cycles, floor held all day,
  drain 1 %/h, readings truncated or rounded to whole percent: 9 forced charge slots and no
  Automatik release; the one-step relaxation of P2 with the drain in the model gives 42 in the
  same replay (22 live on 2026-11-21, before the drain was modelled).

Open after P3: live check (count forced charge slots per day). **Hold cost finding:** with the
drain configured, the hold cost of P2 is large for a small reserve (1 %/h of 15 kWh on 1.1 kWh,
fill at 25 ct: about 3.6 ct per kWh and hour held). A basis kept from the start of an expensive
phase stops paying after a few hours (at 35 ct after about 1.8 h), and the floor then drops in
the middle of the phase. Fixed 2026-11-22 (review finding 1): the basis counts the hold from
slot 0, not from the fill time. Still open: whether the drain should count fully as hold cost
(it runs whenever the SoC is above the base, also without the reserve held at the floor).

### 4. Idle drain in the model (Reserve P4)

- Model the drain as energy leaving the battery per slot while the SoC is above the
  device minimum, instead of an AC load only.
- Learn it from the reading: at the moment the whole-percent SoC changes, the true SoC
  is known to about 0.1 %. The time between two changes without charge or discharge
  gives the drain directly. No extra sensor is needed, and the battery power sensor
  cannot be used for this (it shows less than half of the drain).
- The value feeds `hold_cost` in P2 and the band in P3.

Open: whether the device covers its idle consumption from the AC side at its own
minimum SoC (seen for one hour at 5 %). If it does, a device-side hold is cheaper than
any hold above the minimum.

Implemented (2026-11-22):

- **Parameter.** `idle_drain_kw` on the battery (`components.json` → `batteries[]`,
  optional, missing = 0, no migration step: an absent key has one meaning). It is kept
  apart from `standby_power_kw`: standby is an AC load in the house balance
  (`effective_p_act`), the drain is DC energy leaving the store. Both can be set; on the
  maintainer's plant the 26 W AC standby stays and the drain comes on top.
- **Floor of the drain.** The configured `min_soc` (`idle_drain_floor_soc`): with a
  virtual reserve the drain runs through the reserve floor down to the base minimum stored
  under `VIRTUAL_RESERVE_BASE_MIN_SOC_KEY`. Earnie does not know the device's own minimum
  (only `get_ess_soc_min` is read); using `min_soc` keeps the plan feasible at the
  configured minimum, as before.
- **MILP: no drain (since 2026-11-24).** First the energy balance lost `idle_drain_kw · dt_h`
  per slot, with a binary `idle_drain_off` per slot near the floor (`_idle_drain_kwh_term`).
  With a learned 0.012 kW that was 169 extra binaries on a weak big-M; on the slow NAS the
  strict stage found no good incumbent within 5 s and the plan fell into the 10 % gap stage.
  An exact LP form does not exist (the drain must be at least `min(drain, room above the
  floor)`, a disjunction); a penalty form makes the plan buy the drain of the whole horizon at
  the floor. The drain is a few Wh per slot and the plan is renewed every cycle from the
  measured SoC, so the MILP leaves it out. `_reserve_build_before` (PV-only anchor) no longer
  subtracts it. The reserve floors (`effective_floor_kwh`: band, reachability) keep their
  drain terms; they are lower bounds, so the drain-free plan stays feasible and holds the
  start energy instead of following the drain.
- **Simulation** (`apply_soc_change(..., **idle_drain_kwargs(params))`): the drain is taken
  after the action and does not change the returned power. Wired into the plan simulation
  (`sim_chart_rows`), the multi-battery step (`sim_house_batteries`), the vendor-mode step
  (baseline, savings ledger), `sim_costs` and the horizon-end charge. Not wired: the
  plausibility checks of measured SoC (`consistency.py`, `soc_plausibility.py`) and the UI
  chart ramps (`ui/chart_soc_ramps.py`).
- **Setpoint.** `derive_control_from_milp_plan` adds the slot's drain to the plan's SoC
  before it turns the SoC step into a charge or discharge power, so the battery lands on the
  plan's SoC after the drain. A hold slot stays Entladesperre (no power).
- **Multi-battery.** The plant battery sums the drains (`primary_battery_with_plant_power`).
  Its floor is that of the first battery, which is approximate when the batteries'
  minimums differ.
- **Learner** (`runtime_store/idle_drain_learner.py`, state `idle_drain_learner.json`):
  the daemon feeds each 30 s sampler sample. An episode runs from one drop of the
  reading to the next drop by one step, with every sample's battery power within
  `threshold_power · max power` (idle) and no sample gap over 10 minutes; a rise starts
  over (the crossing level of a rise differs from that of a drop). Episodes between
  15 min and 48 h count; the value is the median of the last 20 once there are three.
  With several house batteries the learner records the reason and does not run.
  **Suggestion only** (maintainer, 2026-11-22): the plan uses the configured value; the
  learned one is logged (`idle_drain_learner: ...`) and read with
  `learned_idle_drain()`.
- **Hold cost for P2/P3.** `optimizer.battery.idle_drain_hold_kwh(params, hold_hours)`:
  the energy the configured drain takes over a holding time. P2 multiplies it with the
  fill price; P3 can size the band from `idle_drain_soc_pct`.

Open after P4: show the learned value in the UI (battery page or diagnosis) with a
button to take it over, and an editor field for `idle_drain_kw` in the house configurator
(today only `components.json`). **Gap:** saving the battery in the house configurator
drops `idle_drain_kw` today (`ui/house_config_battery_io._battery_save_spec` builds the
saved entry field by field); it must pass the key through before the value is set live.

## Field tests before the build (Reserve P0)

On the maintainer's plant, Earnie in silent mode during each test, evaluation from the
optimization history:

1. Fixed target: command 1, target SoC fixed (current SoC + 2 %), active power 0,
   discharge limit 0, for 4 to 6 h. Question: does the inverter hold a fixed target by
   itself, and with which charge power? Background: in July 2026 command 1 with target
   100 % and active power 0 charged about 0.2 kW from the grid.
2. Device cut-off: end-of-discharge SoC set to the floor in the vendor app, command 0,
   for 6 to 8 h. Question: does the device hold there from the AC side?
3. Charge efficiency by power: the same 20 % of SoC at 0.9 kW, 3 kW and 5 kW, AC energy
   against SoC gain.

If test 1 or 2 shows a device-side hold, P3 can use it instead of refill blocks, and a
write field for the device's minimum SoC becomes a candidate (today only
`get_ess_soc_min` is read).

Result of a first check, 2026-11-22: the Huawei registers 37004 and 37760 both deliver
the SoC in whole percent on this plant, although the interface defines one decimal.

## Order

P0 (tests) → P1 (prompt release, independent of the rest) → P4 (drain, input for P2 and
P3) → P2 → P3. P1 can ship alone.

## Tests to write

- P1: a trigger between two ticks ends the wait once; no second wake while the latch is
  set; no wake inside the early-start lead.
- P2: flat prices → no floor, no refill; a price step → the reserve is full at the first
  expensive slot and charged in the cheapest slots before it; a full reserve at the
  start of a cheap phase is not exported or forced out.
- P3: readings one step above and below the floor cause neither discharge release nor
  refill; a gap beyond the band is refilled in one block.
- P4: drain learned from a series of whole-percent readings; no learning across slots
  with charge or discharge.
- Regression: the live pattern of 2026-11-21 as a replay, with the number of forced
  charge slots as the measure (22 today).
