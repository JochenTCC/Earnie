# Predictive heat control: generic EHAL signal set (SG-Ready and beyond)

Status: **draft (2026-11-14)**. Concept; implemented so far: **P1 Feedback** (2026-11-15,
level 3 without the ready-by signals, see section 6 "Implementation of P1"), P2 to P4
(sections 6 and 8.6) and **P5 COP by temperature** (2026-11-16, section 8.2).

This document is the **generic** part: the signal set, its levels and the model. It names no
individual plant. The first plant it is applied to is described in
[heat-control-reference-plant.md](heat-control-reference-plant.md); what that plant taught the
generic design is marked "(from the reference plant)".

## 1. Goal

Use the heat store and the building mass ahead of time, the way Earnie uses a battery: charge
when electricity is cheap or the heat pump is efficient, and live off the stored heat later.

1. Give Earnie a heat-control interface that works with plain SG-Ready and can be extended.
2. Define it as a **generic EHAL signal set** for heating systems with a heat store and an
   optional heating rod. The smart-home backend translates it to the individual controller.
3. Adapt a first plant with a freely programmable controller without SG-Ready (separate
   document, see above).
4. Check that Earnie receives the right measurements for this.

## 2. Why SG-Ready alone is not enough

A battery can be planned because the state of charge, the charge power and the efficiency are
known, and a command has a defined effect. SG-Ready carries one of four operating states:

| State | Meaning (BWP) |
| --- | --- |
| 1 | Lock (utility lock, limited duration) |
| 2 | Normal operation |
| 3 | Start recommended, raised setpoints |
| 4 | Start command, optionally with the electric heater |

What the plant does in state 3 depends on the manufacturer: how far it raises which setpoint,
how much energy that takes, and whether the heat goes to domestic hot water or to heating.
None of it is reported back. So SG-Ready is a mode, not an energy interface.

Earnie does not have to decide between hot water and heating. The controller keeps its
priority rule. Earnie needs to **predict** the rule in its model and **read** the actual
operating state.

## 3. What Earnie does today

- **Signals** on the `thermal_annual` consumer: `heatpump.<id>.set_enable` (0/1),
  `heatpump.<id>.sens_power_act` or `.sens_consumer_active`, `sens_temperature_heat_storage`
  (equivalent store temperature `T_eq`), `sens_temperature_heat_storage_low` (bottom sensor),
  and the plant-wide `sens_temperature_outside`. The heating rod has its own
  `heatpump.<id>_heating_rod.set_enable` and power or run state.
- **Store band:** the heat pump charges up to `heat_storage.setpoint_c` at most. The usable
  band is `tolerance_c` below it, so the usable heat is volume × `tolerance_c`.
- **Live:** the store physics run outside the MILP (`optimizer/thermal_live_store.py`). The
  solver gets forced hours (forecast of `T_eq` or `T_low` below the band) and a scalar amount
  of opportunistic energy up to the setpoint. There is no room sensor; the house starts at
  the target temperature.
- **Scenario Explorer:** store band and house mass are added to one level without losses
  (`optimizer/hp_store.py`). The heat pump efficiency is one constant (JAZ).
- **Role template:** `share/ehal/roles/heatpump.json` is a stub.

Gaps that follow:

1. **Enable is not run.** With `set_enable = 1` the controller still decides by its own
   setpoints. If it considers the store full, nothing happens and plan and reality diverge.
2. **No charge band above the setpoint**, so the store holds little shiftable heat.
3. **Constant efficiency.** Charging hotter and charging in cold hours cost the same as
   charging at the normal setpoint in the warm hours of the day.
4. **One lumped, loss-free store** in the Scenario Explorer; no room temperature in Live.
5. **No feedback** of the operating state or the controller's effective setpoints.

## 4. Two stores, four numbers each

Every thermal store is described by the same four numbers:

| Number | Meaning |
| --- | --- |
| Capacity `C` [kWh/K] | Heat per kelvin |
| Band `ΔT` [K] | Usable temperature range |
| Time constant `τ = C / H` [h] | How fast stored heat leaks (`H` = loss in kW/K) |
| Charge cost | Extra electricity per kWh of heat, compared with normal operation |

Illustrative values for a well-insulated 150 m² house of heavy construction (Earnie's
`building_mass` "schwer", 130 Wh/m²K) and a 900 l store. They are not measurements.

| | Building | Heat store |
| --- | --- | --- |
| Capacity | about 20 kWh/K | about 1 kWh/K |
| Usable band | 1–2 K (comfort) | 15–25 K |
| Usable heat | 20–35 kWh | 15–25 kWh |
| Loss of the stored extra heat | about 10–15 % per day | about 5 % per day |
| Charge cost | almost none (flow temperature barely rises) | 2–2.5 % more electricity per kelvin |
| Charging | slow, limited by the floor heating | fast, full heat pump power |
| Discharging | not controllable, the house releases the heat by itself | controllable (mixer) |

Consequences:

- **Charge in the order of marginal cost:** building within the comfort band, then the lower
  part of the store band, then the hot part, the heating rod last.
- **Losses limit the look-ahead by themselves.** Shifting heat from slot `a` to slot `b` pays
  only if `p_a / COP_a × e^((b−a)/τ) < p_b / COP_b`. For the building that is hours up to
  about a day, for the store two to three days.
- **The outside temperature counts like the price** for an air-source heat pump: running in
  the warm hours of the day raises the COP, often by more than the price spread gains. A
  ground-source heat pump has a nearly constant source, so only the sink temperature counts.
- **Solar gains:** preheating the building before a sunny day is wasted; the forecast gains
  (`thermal.solar_gains`) must enter the same plan.
- **Solar thermal** (from the reference plant): a collector that feeds the lower part of the
  store yields less when that part was charged electrically before. The plan must not boost
  the store ahead of forecast collector heat.

## 5. Layers and responsibilities

```text
Earnie  ──EHAL signal set──►  smart-home backend  ──individual──►  heating controller
(plan: energy, targets)       (translation, watchdog)              (safety, comfort, sink priority)
```

- **Earnie** plans electricity per slot and derives an operating state and target
  temperatures. It never controls valves, pumps or the compressor.
- **The smart-home backend** (Loxone, Home Assistant) maps the generic signals to the
  controller's inputs and outputs and falls back to normal operation when Earnie is silent.
- **The controller** keeps everything that must work without Earnie: frost protection,
  minimum hot-water temperature, maximum temperatures, minimum run and pause times, the
  priority between hot water and heating, legionella program.

This matches the rule already decided for the heating rod: no Earnie-side fail-safe, safety
belongs to the plant.

## 6. Signal set (proposal)

Naming follows the existing EHAL prefixes (`sens_`, `get_`, `set_`). Generator signals live
in the `heatpump.<id>` namespace, store and room temperatures on the `thermal_annual`
consumer like today's `sens_temperature_heat_storage`. The names are proposals.

The set has four levels. A level is available once all its signals are mapped, in the sense
of `ehal/functions.py`. Each level works without the higher ones.

### Level 0: enable (today)

| Signal | Dir | Unit | Meaning |
| --- | --- | --- | --- |
| `heatpump.<id>.set_enable` | write | 0/1 | Generator may run |
| `heatpump.<id>.sens_power_act` | read | W | Electric power |
| `sens_temperature_heat_storage` | read | °C | `T_eq` of the store |
| `sens_temperature_heat_storage_low` | read | °C | Bottom sensor |

### Level 1: operating state (SG-Ready compatible)

| Signal | Dir | Unit | Meaning |
| --- | --- | --- | --- |
| `heatpump.<id>.set_sg_ready_state` | write | 1–4 | Operating state, see below |

| State | Earnie semantics |
| --- | --- |
| 1 Lock | The generator does not start for heating or store charging. The controller overrides it for frost protection and its comfort minimums and limits the duration. |
| 2 Normal | The controller runs its own logic with its normal setpoints. Also the fallback state. |
| 3 Charge | The controller raises the setpoints, to the targets of level 2 or by fixed boosts, and starts the generator when a sink is below them. |
| 4 Forced charge | As 3, up to the maximum temperatures and without waiting for a hysteresis. |

Differences from the BWP definition:

- **Heating rod:** state 4 does not release it. The rod keeps its own
  `heatpump.<id>_heating_rod.set_enable`, because Earnie plans it separately. A heat pump
  that couples the heater to state 4 internally is described by a flag in the heating system.
- **Fixed boosts:** on level 1 the controller raises by amounts Earnie cannot set. The
  heating system therefore stores the boost per sink in kelvin (store, hot water, room), so
  that state 3 has a known capacity: `C × boost`.
- **Sizing a fixed boost:** the boost that lets the generator stay off for a time `t` at a
  heat load `P` is `ΔT = P × t / C`. The load changes with the weather, so a fixed boost
  fits one load only. On level 2 the bridged time is a **result** of the plan, not a
  setting: Earnie sets the target from the forecast demand, the prices, the building's
  band and the cost of charging hotter.
- **Lock limits:** whether state 1 may be used and for how long is a setting of the heating
  system. Without it Earnie sends 2 instead and predicts the controller's own starts.

A standard SG-Ready heat pump is driven with exactly this level: two relay contacts in the
smart home, the boosts read from the heat pump's settings.

### Level 2: targets

| Signal | Dir | Unit | Meaning |
| --- | --- | --- | --- |
| `set_temperature_heat_storage_target` | write | °C | Charge the store, or the heating zone of a combined store, up to this temperature |
| `set_temperature_dhw_target` | write | °C | Hot-water target (separate tank, or the hot-water zone of a combined store) |
| `set_temperature_room_offset` | write | K | Shift of the room setpoint, may be negative |

The targets apply in states 3 and 4; in state 2 the controller ignores them. They replace the
fixed boosts and let Earnie dose the energy.

A value of 0 means "no target"; the backend may use this instead of a separate state input
(from the reference plant).

Each target refers to the sensor at which the controller ends the charge of that sink.
Earnie plans with the heat content, so it assumes that the zone is at the target at the end
of a completed charge and corrects itself with the next measurement. How well this holds
depends on the sensor position and is checked per plant.

The backend decides how it realises the room offset: a shifted room setpoint in its own room
control, a shifted heating curve, or a raised flow setpoint. A negative offset may also be
realised by switching a heating circuit off.

### Level 3: feedback

| Signal | Dir | Unit | Meaning |
| --- | --- | --- | --- |
| `heatpump.<id>.sens_operating_mode` | read | enum | 0 off, 1 space heating, 2 hot water, 3 defrost, 4 locked, 5 cooling, 6 fault |
| `heatpump.<id>.sens_sg_ready_state` | read | 1–4 | State the controller applies (differs from the request while it overrides) |
| `sens_temperature_heat_storage_top` | read | °C | Top sensor: hot-water comfort and upper charge limit |
| `sens_temperature_dhw` | read | °C | Separate hot-water tank, if present |
| `sens_temperature_room` | read | °C | Reference room or mean of several rooms |
| `get_temperature_heat_storage_setpoint` | read | °C | Controller's normal store setpoint |
| `get_temperature_heat_storage_tolerance` | read | K | Band below the setpoint in which the controller does not yet request heat |
| `get_temperature_heat_storage_max` | read | °C | Highest store temperature the controller allows |
| `get_temperature_dhw_min` | read | °C | Hot-water comfort minimum |
| `get_temperature_room_setpoint` | read | °C | Effective room setpoint |
| `get_heat_storage_ready_by_time` | read | time | Next time at which the store, or its heating zone, must be at the temperature below; optional, see 8.3a |
| `get_temperature_heat_storage_ready` | read | °C | Minimum temperature required at that time |
| `get_dhw_ready_by_time`, `get_temperature_dhw_ready` | read | time, °C | The same for hot water |
| `heatpump.<id>.sens_heat_power` | read | W | Thermal power (heat meter), optional |
| `heatpump.<id>.sens_temperature_source` | read | °C | Source temperature (brine, ground water) **while the generator runs**, optional; replaces the outside temperature in the COP. The backend holds the last valid value while it is off (section 8.2) |

The operating mode reports what the controller requests. Whether the compressor runs is
taken from the electric power, because a heat pump with its own controller may delay a
request (from the reference plant).

**The backend owns the band in Live.** Where the setpoint and tolerance signals are mapped,
Live plans with them and not with `heat_storage.setpoint_c` / `tolerance_c` of the house
configurator, as the pool does with `get_temperature_water_setpoint` and
`get_temperature_tolerance_c`. Controller and plan then cannot drift apart. Consequences:

- **Scenario Explorer:** it has no backend, so the configured values stay its input. The
  house configurator shows that Live overrides them and with which present values.
- **Changing setpoint:** a setpoint that follows a heating curve moves with the outside
  temperature. Live reads it every cycle and holds it over the horizon.
- **Band by level:** on levels 0 and 1 the band is setpoint − tolerance up to the setpoint.
  On level 2 the setpoint is the lower end and `get_temperature_heat_storage_max` the upper.

A missing optional signal switches the function that needs it off; it is not replaced by a
default (rule `no-implicit-fallbacks`).

**Implementation of P1 (2026-11-15).**

- **Names:** as proposed above. All twelve kinds are stored on the `thermal_annual`
  consumer's `ehal_bindings` and exchange as `heatpump.<id>.<kind>`, the store and room
  kinds too, like `sens_temperature_heat_storage` already does. One list:
  `ehal/heat_fields.py`. The ready-by signals are not part of it (P8).
- **Units:** temperatures °C, the tolerance K, `sens_heat_power` W (Loxone kW through the
  `loxone` block of `share/ehal/roles/heatpump.json`).
- **Band:** function `heat_storage_band` in `ehal/functions.py`, resolved in
  `optimizer/thermal_live_band.py`. Both signals mapped: the backend's band. One of the
  two: the configured band and a warning. Both mapped but a value missing in a cycle (e.g.
  activated before the backend sends it): the configured band, a warning per cycle and
  `band_source = "config_no_value"` (decided 2026-11-15 after the first activation on the
  reference plant stopped the store plan). A negative tolerance is an error.
- **`T_eq` without a value:** the store plan starts at the setpoint, with a warning per cycle
  and `eq_source = "setpoint_no_value"` in `thermal_observability[]` (`"measured"`
  otherwise); same reasoning as the band (decided 2026-11-18). Without an outdoor forecast
  and without `sens_temperature_outside` the Live plan fails loud; there is no assumed
  outdoor temperature.
- **One key per kind:** the mapping UI stores the heat and pool read kinds bare
  (`house_config.ehal_bindings.consumer_bare_stored_kinds`); the signal list now writes
  the same key and treats the qualified spelling as activated too. Migration
  `dm6.consumer_bare_bindings` merges packs that hold both.
- **Recording:** the mapped kinds are read in the planning path of every cycle, so the
  cycle recorder stores them with its push reads; `thermal_observability[]` carries
  `band_source` and `feedback` in `optimization_history.jsonl`.

**Implementation of P2 (2026-11-15).**

- **Signal:** `heatpump.<id>.set_sg_ready_state`, an optional write on the `thermal_annual`
  consumer (role `heatpump`, `ehal/heat_fields.py`). `set_enable` stays required and is
  sent as before; the state goes out next to it when its key is activated
  (`integrations/loxone_writes.py`, both backends through the `status.json` ledger).
- **Derivation:** `sg_ready_state_for_plan`: 3 where the planned power of the slot is
  above zero (enable 1), otherwise 2. State 1 waits for O2. State 4 moved to P5
  (decided 2026-11-15): before P5 the energy above setpoint + boost is neither planned nor
  priced, and on the reference plant 3 and 4 would reach the same temperature.
- **Boost:** `heat_storage.boost_k` (K, default 0, schema default, no migration: 0 keeps
  the old behaviour). Store only; hot-water and room boosts come with their levels. Live's
  opportunistic headroom reaches setpoint + boost (`LiveStorePlan.charge_max_c`), the
  floor (normal operation) still ends at the setpoint; the Scenario Explorer's store band
  is volume × (tolerance + boost). With the backend band the reported setpoint must be the
  normal one, without the boost; the boost is the configured value.
- **HouseSim:** `house_sim/core/heat_pump.py`, a store with its own controller that takes
  enable or state 1–4 (one source per step). Not wired into the HA integration or the mock
  REST yet.
- **Fail-safe:** the HA package's watchdog writes 2 to every mapped state
  (`MODE_FAIL_SAFE_VALUES` in `integrations/ha_carrier_yaml.py`); Loxone: fallback logic
  in `docs/referenz/loxone-signals.md`.

**Implementation of P3 (2026-11-15).**

- **Signal:** `heatpump.<id>.set_temperature_heat_storage_target`, an optional write on the
  `thermal_annual` consumer (°C, 0 = no target).
- **Computation** (`optimizer/heat_storage_target.py`): the Live store plan travels in the
  thermal MILP context (`LIVE_STORE_PLAN_KEY`) to `MilpHorizonModel.live_store_plans`.
  After the solve, the run is the planned power of the heat pump from slot 0 until the
  first slot without power. The target is `T_eq` plus the run's heat (power × JAZ) minus
  the net draw of the store plan (house + hot water − collector, per hour) and the store
  loss, clamped to [setpoint, `charge_max_c`]. `charge_max_c` = setpoint + boost, capped
  by `get_temperature_heat_storage_max` when it is read; the same cap now limits the
  opportunistic headroom. No run in slot 0, no optimal solve, or startup: 0.
- **Path:** `milp_plan["heat_storage_targets"]` → `main.py` → flex writes (both backends,
  `status.json` ledger). A call without targets (the Loxone watchdog's snapshot) writes none.
- **Deviation check:** `operating_mode_deviation`: a planned run while the controller
  reports locked (4) or fault (6) is logged as a warning. Other modes are not deviations
  (own runs, hot water during a planned charge). Recorded per cycle as
  `thermal_observability[].heat_control` (target, planned run, mode, deviation).
- **HouseSim:** `store_target_c` on `step_heat_pump_store`: with enable 1 / state 3 the
  controller charges to the target instead of setpoint + boost; the target alone also works
  (> 0 charge, 0 normal), as on the reference plant.
- **Fail-safe:** the HA watchdog writes 0; Loxone: fallback logic.
- **Known limit:** the controller starts only below target − its switch-on difference, so a
  target just above `T_eq` does not start a run. The plan does not model this yet.

### Fail-safe

- The backend falls back to state 2 when `status.json` is no longer refreshed. The watchdog
  package for Home Assistant covers numeric `set_*` values today, not modes; it needs an
  extension for the state. For Loxone and for the controller the timeout is part of the
  recipe.
- States are held for at least one planning slot (15 min); the controller adds its own
  minimum run and pause times.

## 7. From the plan to the signals

Per slot the plan holds the generator's electricity and the planned level of each store.

| Plan for the slot | State | Targets |
| --- | --- | --- |
| Generator runs to charge above normal operation | 3 | planned end-of-run temperatures |
| Generator runs at maximum (negative price, surplus that would be curtailed) | 4 | maximum temperatures |
| Generator off, all bands hold in the forecast | 1, if the lock is allowed | – |
| Otherwise, and whenever Earnie has no valid plan | 2 | – |

On level 0 this collapses to today's enable. On level 1 the targets are the configured
boosts and Earnie can only choose whether to start a boost, not how far it goes.

The deviation check compares the planned with the reported operating mode. A run for hot
water while Earnie planned space heating is not an error; it moves energy between the two
store states and is corrected in the next cycle.

## 8. Model changes

### 8.1 Two leaky stores instead of one level

The Scenario Explorer's level model (`hp_store.py`) is extended rather than replaced. Each
store is a level in kWh above its reference state:

```text
x_house[t+1] = (1 − Δt/τ_house) · x_house[t] + q_to_house[t] − q_house_ref[t]
x_store[t+1] = (1 − Δt/τ_store) · x_store[t] + q_gen[t] + q_rod[t] − q_to_house[t] − q_dhw[t]
0 ≤ x ≤ C · ΔT   for each store
```

The leak term is linear in the level, so the model stays linear. `q_to_house` is limited by
the heat the emitters can transfer. A store in parallel to the heating circuits (the
generator feeds the circuits directly and the rest goes into the store) has the same energy
balance, so it needs no separate model.

### 8.2 Efficiency by temperature

`COP = f(sink temperature, source temperature)` replaces the constant JAZ in the plan:

- **Source side:** the outside temperature forecast gives one factor per slot; it is known
  before the solve and costs no variables. With a measured source temperature
  (`sens_temperature_source`) the factor is that value held over the horizon.
- **Source temperature at standstill** (from the reference plant): a sensor in the brine or
  ground-water circuit shows the source only while the generator runs; at standstill the
  fluid in the pipes takes the temperature of its surroundings. The signal is therefore
  defined as the source temperature **during operation**, and the backend holds it:
  - "running" is taken from the compressor (electric power above a threshold), not from the
    request, which comes before the start delay;
  - values count only after a settling time from the start (a few minutes, read from the
    plant's curves), when the fluid from the pipes has passed the sensor;
  - the value sent is the mean over the run after the settling time, frozen at the stop and
    held until the next valid run. The source drops during a run and recovers at standstill,
    so the last value before the stop underestimates the next run; the run mean matches what
    the COP sees over a whole run. The last value after the settling time is an acceptable
    simpler variant, since the source drifts slowly.

  Earnie uses the value as reported and does not filter it itself; a backend that maps the
  raw sensor gives the planner a wrong source factor.
- **Sink side:** the store band is split into segments with falling COP, like tariff tiers.
  Cost minimisation fills the efficient segments first, so no binaries are needed.
- **Data:** the heating system stores a few COP points (manufacturer data or measured with
  the heat meter). Without them the planned efficiency stays the JAZ and the charge band
  above the setpoint stays off, because its cost would be unknown.

**Implementation of P5 (2026-11-16).**

- **COP points:** `heat_source.cop_points` in the heating system (`source_c`, `sink_c`,
  `cop`; heat pumps only, optional, no migration step: nothing is reshaped and absence keeps
  the old behaviour). The points form a grid, every source temperature with every sink
  temperature; one source temperature alone means no source dependence.
  `optimizer/heat_pump_cop.py` (`CopCurve.cop_at`) interpolates linearly in both directions
  and holds the edge value outside the grid. A gap in the grid, a point given twice, a COP
  that rises with the sink or falls with the source temperature, and points on another heat
  source fail loud. The values are absolute, not scaled to the JAZ.
- **Common form with SUSI P7:** the same points and the same function. SUSI's two-piece
  curve over the outside temperature is three points per sink temperature, "constant above
  12 °C" is the held edge value. P7 adds default points per heat pump type and its scale to
  the age table on top; whether default points release the band in Live is decided there.
  Until P7 the year model, the Scenario Explorer and the derived electric power keep the JAZ.
- **Source per slot** (`optimizer/thermal_live_cop.py`): `sens_temperature_source` held over
  the horizon where it is mapped, else the outside temperature forecast per slot. Mapped but
  without a value in a cycle: a warning, the JAZ for that cycle and no charge above the
  setpoint (`efficiency.source = "jaz_no_source_value"`).
- **Sink segments:** band minimum to setpoint, above it steps of 5 K, at most four segments
  (wider steps above the setpoint when the band is larger). The sink temperature of a
  segment is its upper edge; there is no parameter for the spread between flow and store.
- **No binaries, with a bound instead of exactness** (`optimizer/thermal_store_model.py`).
  "Cost minimisation fills the efficient segments first" holds for filling only. When the
  store is drained, cost minimisation would keep the hot segments full and cycle the cheap
  ones, so a hot store would be recharged at the COP of a cold one. Each segment therefore
  has its own balance in two steps per slot (drain, then charge), and a segment may never be
  fuller than the one below it, after the drain and at the end of the slot. The plan can
  then hold at most the same fill fraction in a hot segment as in the one below. Recharging
  a partly drained hot store is priced somewhat too low, never as if the store were cold.
  The exact order needs one binary per slot and segment boundary, which the solve times of
  the Live MILP do not allow at present.
- **Band:** without COP points nothing changes (setpoint + `boost_k`, JAZ). With points, the
  store target mapped and `get_temperature_heat_storage_max` read, the band reaches the
  reported maximum (`LiveStorePlan.band_released`); without the target or the maximum it
  stays at setpoint + `boost_k`, priced with the curve.
- **State 4** (`heat_storage_target.forced_charge_ids`): the plan runs the heat pump in the
  present slot and the buy price of the slot is negative or the plan curtails PV in it; only
  with the curve. The store target is then the upper end of the band.
  `milp_plan["heat_forced_charge"]` → `main.py` → flex writes.
- **Collector** (section 4): the generator may not run on a slot whose level ends above the
  capacity minus the room the collector surplus of the following 24 h needs, never below the
  setpoint (`StoreLevelModel.charge_limit_kwh`, on the generator's on-variable). The surplus
  is the collector heat the draw does not use up: from the slot on, the net heat into the
  store is summed slot by slot, and the largest sum is the room
  (`thermal_live_store._collector_charge_limits`). Collector heat that the house draws
  before or while it arrives needs no room, so a charge that is used up before it comes
  stays allowed. A slot without such a surplus ahead has no limit and no row. The terminal
  level asks for no more than the limit of the book's last slot. Collector heat itself and
  the content already there may lie above the line. Applies with and without COP points.
  (First version, 2.8.0-dev.23: the room was the whole collector heat of the following
  24 h. Beside a draw larger than the collector heat that closed the band a day ahead for
  heat the store never has to take; with the pulse limit the plan then left the band and
  the solve ran into its time limits.)
- **Recorded:** `thermal_observability[].efficiency` (source of the efficiency, source
  temperature, number of points).
- **Open:** the curve by the flow temperature the controller asks for instead of the mean
  store level (a charge pump controlled to a flow temperature runs the whole charge at the
  target's COP; check with recorded flow temperatures); an editor for the points in the
  house configurator; the Scenario Explorer with the curve (SUSI P7).

### 8.3 Hot water

Hot water needs a high temperature at the top of the store, not a high `T_eq`. Both
hydraulic variants become a second store level with a comfort minimum:

- **Separate tank:** its own volume and sensor.
- **Combined store with a hot-water zone** (from the reference plant): the generator charges
  either the top zone or the heating zone through a changeover valve. The top zone is the
  hot-water level, the rest the heating level. The heating system stores the zone split
  (share of the volume above the changeover port). When the heating zone is charged hotter
  than the top zone, the store acts as one volume.

The generator serves one sink at a time, and the controller gives hot water priority. The
plan predicts this rule; it does not command the sink.

### 8.3a Scheduled minimum temperatures

The lower limit of a store level is not constant (from the reference plant): hot-water
comfort times, or a heating circuit that needs a higher flow temperature at a fixed time of
day, raise it for a window. The setpoint signals report only the present value, so Earnie needs
the next demand ahead of time. This is the thermal counterpart of the electric car's
ready-by time (`get_evcs_ready_by_time`): **a temperature that must be reached by a time**.

- **From the backend:** `get_heat_storage_ready_by_time` with
  `get_temperature_heat_storage_ready` (and the hot-water pair). The backend reports the
  next demand it knows, whatever its reason: a comfort window, a hot-water time, a
  legionella program, guests. Earnie does not need to know the reason. The time format
  follows `get_evcs_ready_by_time`.
- **From configuration:** fixed windows with a minimum temperature per zone in the heating
  system, for plants whose backend has no such schedule.

A zone uses one of the two sources; with the signals mapped, a configured schedule for the
same zone fails loud. The ready temperature is the backend's best estimate; a setpoint that
exists only while a circuit is active may be reported as the value of its last active
period. If the real demand turns out higher, the controller requests the rest itself.

The plan then charges the zone in the cheapest slots before the time
instead of letting the controller start the generator when the window opens. With neither
source the controller still serves the demand; Earnie sees it only as a deviation.

### 8.4 One model for Live and the Scenario Explorer

Live keeps the store physics outside the solver today, the Scenario Explorer has the level
inside. The two-store model belongs in one shared place, with Live starting from the
measured `T_eq` and room temperature.

**O1 decided (2026-11-15): inside the Live MILP.** The Scenario Explorer already carries the
store level as one continuous variable per slot without binaries. The leak term, a second
level, the COP segments of P5 and the comfort band of P6 all stay linear. The charge target of
P3 becomes the planned level at the end of the run instead of a second simulation outside the
solver, and the opportunistic charge is decided by price instead of a heuristic. Plan: 8.6.

### 8.5 Parameters and their source

| Parameter | Source |
| --- | --- |
| `C_store` | `volume_liters` (today) |
| `τ_store` | `heat_loss_kw_per_k` (today); check with a standstill period |
| `C_house` | living area × building mass (today) |
| `τ_house` | `house_heat_loss_kw_per_k` (today, calibrated); check with cool-down nights once a room sensor exists |
| Store band | new: maximum charge temperature per heating system, or `get_*` |
| Comfort band | `house_tolerance_c` (today); an asymmetric band (less down than up) is worth considering |
| COP points | new, see 8.2 |

New fields go into the heating-system catalog (`components.json`) and need a step in
`runtime_store/migration/`.

### 8.6 Implementation plan of P4 (2026-11-15)

**Implemented (2026-11-15)** with D1–D3 as proposed. Code: `optimizer/thermal_store_model.py`
(`StoreLevelModel`, `add_store_level`), Live in `thermal_flex_context._add_live_store_consumer`
and `thermal_live_store.live_store_level_model` / `live_store_terminal_kwh`, SE in
`hp_store.py` and `thermal_flex_context._add_hp_store_balance`, target and report in
`heat_storage_target.py` (`milp_plan["heat_storage_levels"]`). Details beyond the plan:

- D2: the terminal level is the mean level of normal operation over the last 24 h of the book,
  so it does not depend on where in a charge cycle the simulation ends.
- Live with a store keeps the pulse limit per day but has no maximum run length; the band
  limits a charge.
- The Live horizon target (`remaining`) is the store's room over the horizon
  (`LiveStorePlan.charge_room_electric_kwh`); it only gates whether the heat pump is planned.
  The same room is the horizon target of a rod beside an electric source.
- SE without a store (house only) stays loss-free.
- Open: a golden-master regression case for the shorter look-ahead; the toy MILP test
  `test_losses_shorten_the_look_ahead` covers the mechanism.

Plan as written before the build:

**Scope.** One linear store model in one module (`optimizer/thermal_store_model.py`), used by
the MILP of Live and of the Scenario Explorer. Not in P4: the building as a controllable store
(P6), COP by temperature (P5), the hot-water level (8.3), the store of a heating rod beside a
fuel source (`rod_store.py` stays).

**Model.** Per heat pump with a store, slot `t` of length `Δt`:

```text
x[t+1] = (1 − Δt·H/C) · x[t] + JAZ · e_hp[t] + e_rod[t] − d[t]
0 − s_below[t] ≤ x[t+1] ≤ C · (T_charge_max − T_min) + s_above[t]
```

- `x`: heat [kWh] above the band minimum `T_min = setpoint − tolerance`; `C` from
  `volume_liters`, `H` = `heat_loss_kw_per_k`; `T_charge_max` = `LiveStorePlan.charge_max_c`
  (setpoint + boost, capped by `get_temperature_heat_storage_max`).
- `d[t]`: net draw, i.e. space heat + hot water − collector heat + the store's loss at `T_min`
  (`H · (T_min − T_amb)`). Live takes it from today's normal-operation simulation
  (`draw_kw_by_hour`), the Scenario Explorer from the year model scaled to the day's heat, as
  today.
- `s_below`, `s_above`: slack at `HP_STORE_SLACK_PENALTY_CENT_PER_KWH`. Slack in Live is
  logged as a warning and recorded in `thermal_observability`; it is never silent.
- Start: Live `x[0] = C · (T_eq − T_min)` from the measured `T_eq`; a start above the upper
  bound (collector heat) raises the bound to the start level and lets it decay with the leak,
  so the start itself costs no slack. The Scenario Explorer carries the level between
  windows as today.
- The bottom-sensor rule (`T_low` below the band forces slot 0) stays as it is.

**What it replaces in Live.** Forced hours, `floor_kwh`, `opp_cap_kwh`, `live_day_min_kwh`
(`_live_store_flex_overlay`, `_thermal_day_want_kwh`), the rod cap
`live_rod_heat_cap_kwh` beside an electric source, and the target simulation of
`heat_storage_target.store_charge_target_c`: the target becomes
`T_min + x[end of run] / C`. The normal-operation simulation stays as the source of `d[t]`
and as the reference for the observability.

**Decisions before the build.**

- **D1 House in P4.** The Scenario Explorer counts the house's comfort band as store capacity
  today (`hp_store_capacity().house_kwh`). Live cannot charge the house before P6 (no room
  offset). Proposal: the house is a passive level in both (its demand is part of `d[t]`); the
  Scenario Explorer loses the house share until P6 and its results change once.
- **D2 End of the horizon.** Without a terminal condition the plan empties the store at the
  end. Proposal: `x[end] ≥` the level of the normal-operation simulation at the same slot,
  the counterpart of the terminal SoC.
- **D3 Plants on level 0 or 1.** Without the target signal the controller charges to the
  setpoint (or setpoint + boost) once it runs, while the plan may want a partial run.
  Proposal: accept the gap, correct it in the next cycle and measure it with the P1
  recording; no binaries for full charges.

**Steps.**

1. Module with the balance, leak, bounds, slack, start above the bound and terminal level;
   unit tests.
2. Live: the overlay hands the model to the MILP instead of forced hours and scalars; rod
   heat beside an electric source enters the level; the P3 target is read from the solution.
3. Scenario Explorer: `_add_hp_store_balance` moves onto the same builder and gains the leak.
4. Observability: planned level and `T_eq` per slot, slack per slot, in
   `thermal_observability`.
5. HouseSim closed loop: the plan drives the controller of `house_sim/core/heat_pump.py`
   through the target; the store stays in its band and a charge ends at the target. A test in
   which a price spread smaller than the loss over two days plans no pre-charge.
6. Regression: golden changes of the heat-pump cases triaged (`regression-triage`); one case
   that shows the shorter look-ahead with losses.
7. Solve time of a recorded Live cycle before and after, on a NAS-like run.
8. German user docs (how Live plans the store) and this document.

**Parameters.** No new catalog field: `C`, `H`, setpoint, tolerance, boost and the reported
maximum exist. The check of `τ_store = C / H` against the P1 recording (standstill periods)
is a separate validation once a few weeks of data exist; it does not block the build.

## 9. Translation in the smart home

### 9.1 Generic recipe

The backend needs, per plant: inputs for the state and the targets, a timeout to state 2,
and outputs for the feedback signals. `share/ehal/roles/heatpump.json` and the Loxone recipe
`share/loxone/recipes/heatpump.json` are extended per level.

### 9.2 Plants

| Plant type | Translation |
| --- | --- |
| Heat pump with SG-Ready contacts | Level 1: two relay contacts; boosts from the heat pump's settings. Feedback as far as the heat pump's interface offers it. |
| Heat pump with a bus interface (Modbus, manufacturer API) | Levels 1–3 as far as the registers allow: setpoints as targets, status as operating mode. |
| Freely programmable controller | Levels 1–3 in the controller program; first case: [heat-control-reference-plant.md](heat-control-reference-plant.md). |

### 9.3 Room control

In a house with low losses and ventilation with heat recovery, the rooms are coupled to each
other more strongly than to the outside. Room thermostats also work against charging the
building: they close when it is being charged. Recommended split:

- **Lead by flow temperature:** heating curve plus one reference room or a mean.
- **Room differences statically:** hydraulic balancing.
- **Thermostats as limiters only:** set to the top of the comfort band.

Earnie therefore controls one quantity for the building, `set_temperature_room_offset`, and
reads one, `sens_temperature_room`.

A backend with its own room-by-room control keeps it (from the reference plant). It applies
the offset to the setpoints of the rooms that take part and leaves the others alone, for
example bedrooms. Which rooms take part is a setting of the backend; `sens_temperature_room`
is then the mean of the participating rooms, and the house capacity in Earnie is reduced to
their share of the living area.

## 10. Measurement check

| Measurement | Today | Needed for | Priority |
| --- | --- | --- | --- |
| Electric power of the heat pump | yes | plan against actual, savings | – |
| `T_eq`, bottom sensor | yes | store state; check the sensor weights (`waermespeicher-schichtung-teq.md`) | check |
| Outside temperature | yes | demand, COP | – |
| Top sensor | no | hot-water comfort, upper charge limit | high |
| Operating mode | no | plan against actual, sink attribution | high |
| Room temperature | no | building as a store | high |
| Controller setpoints and limits | no | same band in Earnie and controller | medium |
| Thermal power | no | measured COP, loss identification | medium |
| Hot-water tank temperature | no | only with a separate tank | by hydraulics |

The state of a concrete plant is checked per plant, see the reference plant document.

## 11. Phases

Order decided 2026-11-15: **generic first**. Every phase is usable on its own, on any plant
whose backend maps the signals of that phase. Backlog epic: `HeatControl`. What each phase
needs on the reference plant, and the steps that exist only there, are in
[heat-control-reference-plant.md](heat-control-reference-plant.md) § 9.

| Phase | Content | Gain |
| --- | --- | --- |
| P1 Feedback | Read signals of level 3 in EHAL (role, functions, recipes, EHAL-Com, German user docs). Live plans with the store band of the backend where it is mapped (section 6). The new signals are recorded. No change of the plan itself. | Plan and controller cannot drift apart. The recording yields `τ_store`, `τ_house` and the generator's behaviour. |
| P2 Operating state | `heatpump.<id>.set_sg_ready_state` (level 1), derived from today's plan: 3 where the plan charges, otherwise 2; the lock stays unused until O2 is decided, state 4 comes with P5. Fixed boost per sink in the heating system. HouseSim controller that understands the states; watchdog for modes in the Home Assistant package. | Standard SG-Ready heat pumps can be driven. On a plant that runs level 0 the behaviour stays the same, so the changeover carries no risk. |
| P3 Store target | `set_temperature_heat_storage_target` (level 2), computed from the planned energy. The band stays the one of levels 0 and 1 until P5. | The charge is dosed instead of switched between two values. |
| P4 Two leaky stores | Model of 8.1 in one place for the Scenario Explorer and Live, inside the MILP (8.4, O1 decided; plan 8.6). Time constants checked against the recording of P1. | Losses limit the look-ahead; store and building are planned separately. |
| P5 COP by temperature | Model of 8.2: source factor per slot, sink segments, COP points in the heating system. Releases the charge band above the setpoint, and with it SG-Ready state 4 (moved here from P2). One curve together with SUSI P7. The plan does not boost ahead of forecast collector heat (section 4). | Charging hotter has a price; the usable band grows. |
| P6 Building as a store | `set_temperature_room_offset` and `sens_temperature_room`; the comfort band is planned (O3); Live starts the house from the measured room temperature. | The largest store with the lowest charge cost. |
| P7 Scheduled demand: study | For a plant with a scheduled minimum temperature (8.3a): from the recording of P1, how often the demand starts the generator in expensive slots and with how much energy; gain estimated in the Scenario Explorer with a configured window. Decision whether P8 is built. | Decision basis, no change on any plant. |
| P8 Ready-by | Model of 8.3a: the ready-by signals and configured windows as the two sources; the plan charges the zone before the time. Only after a positive P7. | A known demand is pre-charged in cheap slots. |

Dependencies:

- P1 → P2 → P3 build on each other and need no model change.
- P4 needs O1 (decided 2026-11-15). P5 and P6 need P4; P6 may move before P5 when the gain counts more than the
  comfort risk (room sensor, room control and cool-down nights for the calibration).
- P7 needs only P1. P8 needs P3 and gets more accurate with P5, because a scheduled demand
  usually asks for a high temperature.

Not scheduled yet, separate items once P5 is done: the hot-water level (8.3, with
`set_temperature_dhw_target` and the hot-water ready-by pair), the heating rod in the same
plan, the adaptation of the parameters from measurements, and cooling (O4).

## 12. Open points

Plant-specific questions are in the reference plant document.

- **O1 Model location:** decided 2026-11-15, inside the Live MILP (8.4, plan 8.6).
- **O2 Lock:** whether Earnie uses state 1 at all, or only 2–4.
- **O3 Comfort band:** symmetric as today or asymmetric, constant or by time of day.
- **O4 Cooling:** passive or active cooling uses the same emitters and excludes heating. How
  the cooling follow-up (`house-cooling.md`) shares the signal set is not designed here.
- **O5 Measured collector heat:** whether a solar heat meter becomes an EHAL signal to
  correct the collector forecast.
