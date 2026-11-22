# Virtual reserve: hold it only when it pays, release it promptly

Status: draft, 2026-11-22. Nothing here is implemented. Backlog: epic **Reserve**
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
