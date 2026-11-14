# Predictive heat control: reference plant (UVR 1611)

Status: **draft (2026-11-14)**. Analysis and proposal, nothing is implemented or changed on
the plant.

This is the **plant-specific** part of the heat-control design. The generic signal set, its
levels and the model are in [heat-control-sg-ready.md](heat-control-sg-ready.md). This
document applies them to the first plant: the maintainer's house.

Sources: the installer's hydraulic schema ("Schema mit Kühlung", 2015), the printed
function overview of the controller program (three pages), and the maintainer's answers of
2026-11-14. The print shows the function blocks and their wiring, **not the parameters**
(setpoints, hystereses, times, heating curves). Readings that are inferred and not explicit
in the print are marked *(inferred)*.

**The print is not the running program.** At least two things differ: Loxone provides the
hot-water setpoint and receives the store temperatures S3–S5, and the print shows neither.
Every statement below about a "free input" or a missing output therefore has to be checked
against the running program before the controller is changed.

## 1. Plant

| Part | Data |
| --- | --- |
| Heat pump | Weider SW 70, brine-water, ground source with brine distributors |
| Store | one combined store, 887 l, three sensors in the **upper three** of four pockets (per maintainer, to be checked once at the store), solar coil in the lower part |
| Hot water | fresh-water station (plate heat exchanger) fed from the top of the store; no separate tank |
| Heating circuits | floor heating and wall / bench heating, each with pump and mixer |
| Solar thermal | 10.6 m² collector, heat meter in the solar circuit |
| Cooling | passive, brine through a heat exchanger into the floor heating |
| Heating rod | none |
| Controller | Technische Alternative UVR 1611, CAN bus; the heat pump keeps its own internal controller |
| Smart home | Loxone, connected through a CAN–KNX interface (CAN node 48) |

## 2. Hydraulics

- **Changeover:** two three-way valves (output A10, switched together) connect the heat pump
  either to the top zone of the store (hot-water charge) or to the lower zone (heating).
- **Heating:** the store is **parallel** to the heating circuits. The heat pump's flow passes
  the circuit connections first; what the circuits do not take goes into the lower zone. With
  the heat pump off the circuits draw from the store.
- **Hot water:** the fresh-water station draws from the top and returns to the bottom.
- **Mixers on both circuits:** a store charged above the flow setpoint does not reach the
  house as too high a flow temperature. The precondition of the generic design is met.
- **Solar coil in the lower zone:** the same zone the heat pump charges in heating mode.
- **Cooling:** changeover valves and pump (A12, A13) route brine through the cooling heat
  exchanger; the floor-heating mixer then controls a cooling flow setpoint.

## 3. Controller program as read

### 3.1 Inputs and outputs

| Sensor | Meaning | | Output | Meaning |
| --- | --- | --- | --- | --- |
| S1 | collector | | A1 | solar pump |
| S3 | store top | | A2 | pump wall heating |
| S4 | store middle | | A3/A4 | mixer wall heating |
| S5 | store bottom | | A5 | heating request to the heat pump |
| S6, S7 | wall heating flow, return | | A6 | pump floor heating |
| S8, S9 | floor heating flow, return | | A7 | store charge pump |
| S10 | outside sensor (schema; not used in the program) | | A8/A9 | mixer floor heating |
| S11, S12 | heat pump flow and return *(inferred: the schema labels both "VL")* | | A10 | changeover valves hot water |
| S13, S14 | brine flow, return | | A11 | hot-water request *(inferred: wired to the heat pump)* |
| S15, S16 | solar return, solar flow rate | | A12 | cooling valves |
| | | | A13 | cooling / brine pump |
| | | | A15, A16 | analog: speed of solar pump, of charge pump |

The schema labels the pump speed outputs "A 13 drehz."; the program uses A15 and A16. The
program is taken as valid.

### 3.2 CAN network variables in use

| Variable | From / to | Used for |
| --- | --- | --- |
| Analog in 1 (node 48) | in | outside temperature for both heating-circuit controllers |
| Analog in 2 (node 48) | in | maximum store temperature for the collector re-cooling |
| Analog in 3 (node 48) | in | flow setpoint for the floor-heating mixer (cooling) |
| Digital in 1 (node 48) | in | cooling request |
| Digital in 2 (node 48) | in | enable floor heating circuit |
| Digital in 3 (node 48) | in | enable wall heating circuit |
| Analog out 1 | out | collector temperature S1 |

Node 48 is the CAN–KNX interface to Loxone. Loxone already sends setpoints and enables to
the controller. The print shows one value sent back (the collector temperature); in the
running program Loxone also receives S3, S4 and S5 and sends the hot-water setpoint.

### 3.3 Functions

| Function | What it does |
| --- | --- |
| `SOLAR`, `ANALOG3`, `WMZ SOLAR` | Solar control on S1 against S5, pump speed, solar heat meter |
| `KUEHLFKT` | Re-cools the store through the collector when S4 exceeds the network maximum |
| `Wandheizung`, `Fusbodenheiz` (heating-circuit controllers) | Flow setpoint from the outside temperature, each with its own heating curve stored in the controller. **No room sensor is connected.** Enabled by `LOGIK2` / `LOGIK4`, that is by Loxone. |
| `WW_ANF` (hot-water request) | S3 below the hot-water setpoint → A11, A10, A7. The setpoint comes from Loxone (not wired in the print). |
| `MAX(An)2` → `HZ_ANF` (heating request) | Largest flow setpoint of the two circuits is the request setpoint; S4 below it → A5, A7. The enable input and the switch-off sensor are not wired. |
| `MAX(An)1` | Charge pump speed from the heat pump flow S11 → A16 |
| `LOGIK2`, `LOGIK4` | Circuit enable = network enable AND no hot-water request AND no cooling |
| `LOGIK1`, `MAX(An)4`, `M-REG.1`, `NACHLAUF`, `ZEIT` | Cooling: valves, pumps and the floor-heating mixer setpoint |

## 4. What this means for the design

1. **Two zones, one store.** Hot water is the top zone (sensor S3), heating the lower zone
   (sensor S4). This is the "combined store with a hot-water zone" of the generic model.
2. **Sink priority is hard-wired:** during a hot-water charge both heating circuits are
   disabled. Earnie predicts this, it does not command it.
3. **The charge sensors are known:** S3 ends a hot-water charge, S4 a heating charge
   *(inferred for S4: the switch-off sensor is not wired, the parameters decide)*.
4. **The heating request already is a maximum function.** `MAX(An)2` has free inputs. A
   store target from outside enters there and wins over the heating curve when it is
   higher. No existing logic has to be rewritten.
5. **Ground source:** the COP depends on the sink temperature and the slowly drifting brine
   temperature, not on the time of day. The "run in the warm hours" lever does not apply
   here. The brine temperature is measured (S13, S14).
6. **The room control is in Loxone.** It controls every room by its room temperature and
   enables the two circuits over the network. The building is therefore charged in Loxone,
   not in the controller.
7. **Request is not run.** A5 and A11 are requests to the heat pump's own controller. The
   compressor state comes from the electric power.
8. **Solar thermal shares the lower zone.** A boosted lower zone lowers the collector yield;
   the plan must respect the collector forecast. The solar heat meter can check it.
9. **Cooling excludes heating** in the controller already; out of scope here.
10. **The wall heating is a scheduled comfort demand.** Loxone switches it on separately in
    the morning to warm the walls of the open shower, with a higher flow temperature from
    its own heating curve. Through `MAX(An)2` this raises the request setpoint of the store
    for that window. It is the case of the generic "scheduled minimum temperatures": the
    demand is known in advance, needs a high temperature, and can be pre-charged in cheap
    hours instead of starting the heat pump when the window opens.
11. **The bottom of the store is not measured.** With the sensors in the upper three
    pockets the sensor called "bottom" (S5) sits at about 37 % of the height. The cold layer
    below it, where the solar coil and the heat pump's return are, has no sensor. S3 is a
    real top sensor.
12. **The heat pump is a black box so far.** The controller sends requests (A5 heating, A11
    hot water); how they are wired to the Weider SW 70 and what its own controller does with
    them is not known. Until then the plan treats a request as "may run" and learns the
    behaviour from measurements (section 7).
13. **No heating rod:** state 4 equals state 3 with the maximum targets.

## 5. Mapping of the levels

The smart home translates the generic signals. Proposal with the smallest change to the
controller program; all additions are new blocks or free inputs, nothing existing changes
its behaviour while the new network inputs are 0.

### Level 0 (today)

The running program has a third input on `MAX(An)2` (not in the print). It jumps between a
high and a low store setpoint with Earnie's `heatpump.<id>.set_enable`.

- **Enable = 1:** the heating zone is charged up to the high setpoint. This already is the
  generic state 3 with a fixed boost.
- **Enable = 0:** the low setpoint. Through the maximum function the heating curves still
  win when they are higher, so this is state 2, not a lock.

Loxone reports the band to Earnie (`get_temperature_heat_storage_setpoint`,
`get_temperature_heat_storage_tolerance`), so Live plans with the controller's values and
not with those of the house configurator. Until these signals exist, the configured
`heat_storage.setpoint_c` has to equal the high setpoint by hand.

### The band on this plant

| End | Value | Remark |
| --- | --- | --- |
| Lower end | flow setpoint of the floor heating curve, plus the wall heating's while its window is open | What `MAX(An)2` yields without Earnie's input. No permanent boost on it: a store that is always kept hotter pays the lower COP and the higher loss all the time. |
| Upper end, levels 0 and 1 | lower end plus a fixed boost | The present "high" value. |
| Upper end, level 2 | Earnie's target, capped by the maximum | The boost is planned per day. |
| Hot water | separate: top zone, sensor S3, own setpoint and target | Not part of the heating zone's setpoint. Charging the whole lower zone to the hot-water temperature costs COP on the full volume. |

How far a boost carries, with the whole store at about 1.03 kWh/K (the heating zone alone
has less) and illustrative heat loads:

| Heat load | Heat for 6 h | Boost needed |
| --- | --- | --- |
| 1 kW (mild day) | 6 kWh | about 6 K |
| 2 kW | 12 kWh | about 12 K |
| 3 kW (cold day) | 18 kWh | about 17 K |

On a cold day six hours from the store alone need a flow temperature near the heat pump's
limit. The building covers the same heat with about 1 K of its comfort band (about
20 kWh/K, illustrative). A fixed bridging time is therefore not a design value of this
plant: the store and the building bridge together, and the plan decides the split.

### Level 1: operating state

The controller needs no state input. The smart home resolves the state:

| State | Smart home sends |
| --- | --- |
| 1 Lock | lock bit = 1, targets = 0 |
| 2 Normal | lock bit = 0, targets = 0 |
| 3 Charge | lock bit = 0, targets = configured or planned values |
| 4 Forced charge | lock bit = 0, targets = maximum values |

Controller additions:

- **Lock:** a new digital network input, inverted, on the free enable input of `HZ_ANF`. A
  comparison "S4 below a minimum" overrides it so that the heating never starves, and so
  does the wall-heating enable, so that the morning window is always served. The hot-water
  request stays unlocked: comfort first, and its energy is small.

### Level 2: targets

| Generic signal | Controller addition |
| --- | --- |
| `set_temperature_heat_storage_target` | The existing third input of `MAX(An)2` takes Earnie's target instead of the two fixed values. Limited by a new minimum function against a fixed maximum (heat pump flow limit minus a margin). |
| `set_temperature_dhw_target` | Loxone already provides the hot-water setpoint, so Loxone sends the larger of its own setpoint and Earnie's target; no controller change. The limit against the heat pump's maximum is added in the controller or in Loxone. |
| `set_temperature_room_offset` | **No controller change in the first step:** Loxone adds the offset to the setpoints of the participating rooms and thereby changes the circuit enables it already sends. The wall heating's morning window does not take part. Second step, if the floor heating takes the heat too slowly: a raised flow setpoint on a free input of `MAX(An)4` and `MAX(An)2`. |

The morning window of the wall heating is reported by Loxone, which holds its times, as the
generic ready-by pair: `get_heat_storage_ready_by_time` = start of the next window,
`get_temperature_heat_storage_ready` = the wall heating's flow setpoint for it. Earnie then
sends a store target before the window. Nothing in the signals is specific to the wall
heating.

The wall heating's flow setpoint exists only while the circuit is enabled; disabled, the
controller outputs an artificially low value. Options for the ready temperature:

| Option | How | Assessment |
| --- | --- | --- |
| A Hold the last value | Loxone stores the flow setpoint of the last window and reports it for the next one. | Recommended first step: no controller change, no second curve. The error is the day-to-day change of the outside temperature times the curve slope, a few kelvin at most; a small margin covers it. |
| B Shadow controller | A second heating-circuit function in the UVR with the same curve, always enabled, without outputs; its flow setpoint is sent to Loxone. | Exact for the present outside temperature. Two parameter sets of the same curve in one device have to be kept equal. |
| C Curve in Loxone | Loxone computes the curve itself. | Not recommended: a copy outside the controller drifts from the original. |

### Level 3: feedback

New network outputs; the smart home builds the generic signals from them.

| Generic signal | From |
| --- | --- |
| `sens_temperature_heat_storage_top` | S3 |
| `sens_temperature_heat_storage_low` | S5 (lowest sensor, not the bottom of the store) |
| `sens_temperature_heat_storage` (`T_eq`) | weighted mean of S3, S4, S5 in the smart home |
| `heatpump.<id>.sens_operating_mode` | cooling if A12, else hot water if A11, else heating if A5, else off; "locked" while the lock bit is set |
| `heatpump.<id>.sens_temperature_source` | S13 (brine flow) |
| `get_temperature_heat_storage_setpoint` | result of `MAX(An)2`. Exported from the controller, not rebuilt in Loxone: a copy of the heating curves would drift from the original. |
| `sens_temperature_room`, `get_temperature_room_setpoint` | already in the smart home |
| `get_heat_storage_ready_by_time`, `get_temperature_heat_storage_ready` | Loxone schedule of the wall heating and its flow setpoint from the controller |
| heat pump flow and return, solar power | S11, S12, `WMZ SOLAR`; for identification, no generic signal yet |

### Fail-safe

- **Earnie silent:** the smart home sends lock = 0 and targets = 0. The plant then runs
  exactly as today.
- **Smart home silent:** whether the UVR 1611 can replace a network input by a default after
  a timeout has to be checked in its manual. The same question already applies to the
  outside temperature, which comes over the network today.

## 6. Measurement check

| Measurement | State on this plant |
| --- | --- |
| Store temperatures | Three sensors in the upper three pockets (745 / 1250 / 1710 mm of 2040 mm), all available in Loxone. Weights of `T_eq` from `waermespeicher-schichtung-teq.md`: bottom 0.49, middle 0.24, top 0.27. The layer below 745 mm is unmeasured, so `T_eq` tends to be too high, most of all with a discharged store. |
| Top sensor | Exists (S3). |
| Bottom sensor | **Missing.** S5 is not the bottom of the store. A fourth sensor in the free bottom pocket (310 mm) removes the error (about 4 kWh in the example of the `T_eq` guide) and brings the weights close to 0.25 each. It also shows how much room the solar coil has left. |
| Operating mode | Derivable from A5, A11, A12; needs network outputs. |
| Room temperature | Not in the controller; expected in the smart home. |
| Source temperature | Exists (S13, S14). |
| Thermal power of the heat pump | **Missing.** Flow and return temperature exist (S11, S12) but no flow meter, and the charge pump is speed-controlled. A flow sensor in the heat pump circuit would give the measured COP. |
| Solar heat | Exists (heat meter). |
| Electric power of the heat pump | Not part of the controller; to be confirmed. |
| Controller setpoints | Parameters, not on the print. |

## 7. Model parameters (to be measured)

| Parameter | First estimate | How to get the real value |
| --- | --- | --- |
| Zone split | top zone about a third of 887 l | height of the changeover port from the store's data sheet |
| Morning window of the wall heating | – | schedule from Loxone, flow temperature from the wall heating curve |
| Capacity | whole store about 1.03 kWh/K | – |
| Hot-water band | present setpoint up to the heat pump limit | controller parameters, heat pump data sheet |
| Heating-zone band | flow setpoint (about 30 °C) up to the limit | same |
| `τ_store` | – | standstill period without charge or draw |
| `τ_house` | – | cool-down nights with the smart home's room temperatures |
| COP points | – | data sheet of the heat pump; measured once a flow sensor exists |
| Heat pump behaviour | – | record A5, A11, the electric power and S11 / S12 for two weeks: start delay after a request, flow temperature at which it stops, minimum run and pause times |

## 8. Open questions

Answered and worked in above: CAN node 48, circuit enables, sensor pockets, heating rod,
store temperatures in Loxone, hot-water setpoint, how the enable acts today, source of the
morning window.

- **Q1 Running program:** a current function overview, or a check of the affected blocks at
  the controller (`HZ_ANF`, `WW_ANF`, `MAX(An)2`, network inputs and outputs in use).
- **Q2 Setpoints of the enable:** the high and the low value on `MAX(An)2`. Needed for the
  Scenario Explorer's configured values and until Loxone reports the band.
- **Q3 Heat pump interface:** to which terminals of the Weider SW 70 A5 and A11 go and what
  they do there; maximum flow temperature; fixed speed or modulating; whether it has a lock
  input. Sources: the heat pump's wiring diagram or the installer. Not blocking: levels 1–3
  need only the requests the controller already sends, and the recording of section 7 gives
  the behaviour.
- **Q4 Controller parameters:** request and switch-off differences of `HZ_ANF` and its
  switch-off sensor, both heating curves, minimum run times.
- **Q5 Network timeout:** whether the UVR 1611 or the CAN–KNX interface replaces a network
  input by a default when Loxone is silent.
- **Q6 Sensor labels:** S12 (heat pump return?), S2 (solar flow, unused in the program), S10.
