# Predictive heat control: generic EHAL signal set (SG-Ready and beyond)

Status: **draft (2026-11-14)**. Concept only, nothing is implemented. Written before the
hydraulic sketch and the controller program of the reference plant were available; the
sections marked *preliminary* are refined once they are.

## 1. Goal

Use the heat store and the building mass ahead of time, the way Earnie uses a battery: charge
when electricity is cheap or the heat pump is efficient, and live off the stored heat later.

1. Give Earnie a heat-control interface that works with plain SG-Ready and can be extended.
2. Define it as a **generic EHAL signal set** for heating systems with a heat store and an
   optional heating rod. The smart-home backend translates it to the individual controller.
3. Adapt the reference plant: a freely programmable controller (Technische Alternative
   UVR 1611) without SG-Ready.
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
`building_mass` "schwer", 130 Wh/m²K) and an 887 l store. They are not measurements of the
reference plant.

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
  the warm hours of the day raises the COP, often by more than the price spread gains.
- **Solar gains:** preheating the building before a sunny day is wasted; the forecast gains
  (`thermal.solar_gains`) must enter the same plan.

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
- **Lock limits:** whether state 1 may be used and for how long is a setting of the heating
  system. Without it Earnie sends 2 instead and predicts the controller's own starts.

A standard SG-Ready heat pump is driven with exactly this level: two relay contacts in the
smart home, the boosts read from the heat pump's settings.

### Level 2: targets

| Signal | Dir | Unit | Meaning |
| --- | --- | --- | --- |
| `set_temperature_heat_storage_target` | write | °C | Charge the store up to this temperature |
| `set_temperature_dhw_target` | write | °C | Hot-water target (separate tank or hot-water zone) |
| `set_temperature_room_offset` | write | K | Shift of the heating curve or room setpoint, may be negative |

The targets apply in states 3 and 4; in state 2 the controller ignores them. They replace the
fixed boosts and let Earnie dose the energy.

The store target refers to the sensor at which the controller ends the charge. Earnie plans
with `T_eq`, so it assumes that the store is at the target at the end of a completed charge
and corrects itself with the next measured `T_eq`. Whether this holds depends on the sensor
position and is checked on the reference plant (open point O2).

### Level 3: feedback

| Signal | Dir | Unit | Meaning |
| --- | --- | --- | --- |
| `heatpump.<id>.sens_operating_mode` | read | enum | 0 off, 1 space heating, 2 hot water, 3 defrost, 4 locked, 5 cooling, 6 fault |
| `heatpump.<id>.sens_sg_ready_state` | read | 1–4 | State the controller applies (differs from the request while it overrides) |
| `sens_temperature_heat_storage_top` | read | °C | Top sensor: hot-water comfort and upper charge limit |
| `sens_temperature_dhw` | read | °C | Separate hot-water tank, if present |
| `sens_temperature_room` | read | °C | Reference room or mean of several rooms |
| `get_temperature_heat_storage_setpoint` | read | °C | Controller's normal store setpoint |
| `get_temperature_heat_storage_max` | read | °C | Highest store temperature the controller allows |
| `get_temperature_dhw_min` | read | °C | Hot-water comfort minimum |
| `get_temperature_room_setpoint` | read | °C | Effective room setpoint |
| `heatpump.<id>.sens_heat_power` | read | W | Thermal power (heat meter), optional |

The `get_*` values replace Earnie-side configuration where they are mapped, as the pool does
with `get_temperature_water_setpoint`. A missing optional signal switches the function that
needs it off; it is not replaced by a default (rule `no-implicit-fallbacks`).

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
the heat the emitters can transfer. Whether the generator feeds the heating circuit through
the store or beside it depends on the hydraulics (open point O1).

### 8.2 Efficiency by temperature

`COP = f(sink temperature, source temperature)` replaces the constant JAZ in the plan:

- **Source side:** the outside temperature forecast gives one factor per slot; it is known
  before the solve and costs no variables.
- **Sink side:** the store band is split into segments with falling COP, like tariff tiers.
  Cost minimisation fills the efficient segments first, so no binaries are needed.
- **Data:** the heating system stores a few COP points (manufacturer data or measured with
  the heat meter). Without them the planned efficiency stays the JAZ and the charge band
  above the setpoint stays off, because its cost would be unknown.

### 8.3 Hot water

Hot water needs a high temperature at the top of the store, not a high `T_eq`. A separate
tank becomes a third level with a comfort minimum. A combined store needs a rule for the
top zone; it is specified with the hydraulics (O1).

### 8.4 One model for Live and the Scenario Explorer

Live keeps the store physics outside the solver today, the Scenario Explorer has the level
inside. The two-store model belongs in one shared place, with Live starting from the
measured `T_eq` and room temperature. This is a decision to take before implementation (O5).

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

## 9. Translation in the smart home

### 9.1 Generic recipe

The backend needs, per plant: inputs for the state and the targets, a timeout to state 2,
and outputs for the feedback signals. `share/ehal/roles/heatpump.json` and the Loxone recipe
`share/loxone/recipes/heatpump.json` are extended per level.

### 9.2 Reference plant: UVR 1611 (preliminary)

The controller reproduces the states in its own program:

- **Inputs:** network inputs for the state and for each target.
- **State 1:** blocks the generator request, limited by a maximum duration and overridden by
  the minimum top temperature and frost protection.
- **State 3:** raises the setpoints of the store and hot-water requests to the targets,
  capped by the heat pump's maximum flow temperature, and shifts the heating curve.
- **State 4:** as 3 with the maximum temperatures.
- **No signal:** state 2.
- **Outputs:** operating mode, effective setpoints, sensors.

A mixed heating circuit is required: without a mixer an overcharged store reaches the house
as too high a flow temperature.

This section is rewritten against the scanned function-block diagram and the hydraulic
sketch. Missing controller inputs or outputs are added on the plant side.

### 9.3 Room control

In a house with low losses and ventilation with heat recovery, the rooms are coupled to each
other more strongly than to the outside. Room thermostats also work against charging the
building: they close when it is being charged. Recommended split:

- **Lead by flow temperature:** heating curve plus one reference room or a mean.
- **Room differences statically:** hydraulic balancing.
- **Thermostats as limiters only:** set to the top of the comfort band.

Earnie therefore controls one quantity for the building, `set_temperature_room_offset`, and
reads one, `sens_temperature_room`.

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

Whether the mapped signals of the reference plant are correct cannot be seen in the
repository; it needs the `ehal_bindings` of the house profile.

## 11. Phases

| Phase | Content |
| --- | --- |
| P0 | Measurement check on the reference plant; add top sensor, operating mode and room temperature; record two weeks; identify `τ_store`, `τ_house` and COP points. No optimizer change. |
| P1 | Signal set levels 1–3 in EHAL (role, functions, recipes, EHAL-Com, German user docs). Earnie writes state and targets from today's plan. |
| P2 | Translation on the reference plant (UVR 1611) including the timeout; plan against actual with the reported operating mode. |
| P3 | Two leaky stores and COP by temperature in the Scenario Explorer and Live; catalog fields and migration. |
| P4 | Hot-water level, heating rod in the same plan, adaptation of the parameters from measurements. |

HouseSim needs a controller that understands the states for the tests of P1 and P3.

## 12. Open points

- **O1 Hydraulics:** combined store or separate hot-water tank, fresh-water station, store in
  series or parallel to the heating circuit, mixers, solar thermal. Decides 8.1 and 8.3.
- **O2 Charge sensor:** which sensor ends a store charge, and how `T_eq` relates to it.
- **O3 Heat pump:** air or ground source, modulating or on/off, how the controller requests
  it, maximum flow temperature.
- **O4 Path:** how the smart home reaches the controller (C.M.I., CAN, Modbus) and which
  backend sits between.
- **O5 Model location:** store physics inside the Live MILP or outside as today (8.4).
- **O6 Lock:** whether Earnie uses state 1 at all, or only 2–4.
- **O7 Comfort band:** symmetric as today or asymmetric, constant or by time of day.
