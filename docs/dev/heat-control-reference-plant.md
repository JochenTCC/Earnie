# Predictive heat control: reference plant (UVR 1611)

Status: **draft (2026-11-14)**. Analysis and proposal, nothing is implemented or changed on
the plant.

This is the **plant-specific** part of the heat-control design. The generic signal set, its
levels and the model are in [heat-control-sg-ready.md](heat-control-sg-ready.md). This
document applies them to the first plant: the maintainer's house.

Source: the installer's hydraulic schema ("Schema mit Kühlung", 2015) and the printed
function overview of the controller program (three pages). The print shows the function
blocks and their wiring, **not the parameters** (setpoints, hystereses, times, heating
curves). Readings that are inferred and not explicit in the print are marked *(inferred)*.

## 1. Plant

| Part | Data |
| --- | --- |
| Heat pump | Weider SW 70, brine-water, ground source with brine distributors |
| Store | one combined store, 887 l, three sensors (top, middle, bottom), solar coil in the lower part |
| Hot water | fresh-water station (plate heat exchanger) fed from the top of the store; no separate tank |
| Heating circuits | floor heating and wall / bench heating, each with pump and mixer |
| Solar thermal | 10.6 m² collector, heat meter in the solar circuit |
| Cooling | passive, brine through a heat exchanger into the floor heating |
| Controller | Technische Alternative UVR 1611, CAN bus; the heat pump keeps its own internal controller |

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

So a CAN node 48 already sends setpoints and enables to the controller, and the controller
sends **one** value back. All other free network variables are available.

### 3.3 Functions

| Function | What it does |
| --- | --- |
| `SOLAR`, `ANALOG3`, `WMZ SOLAR` | Solar control on S1 against S5, pump speed, solar heat meter |
| `KUEHLFKT` | Re-cools the store through the collector when S4 exceeds the network maximum |
| `Wandheizung`, `Fusbodenheiz` (heating-circuit controllers) | Flow setpoint from the outside temperature. **No room sensor is connected.** Enabled by `LOGIK2` / `LOGIK4`. |
| `WW_ANF` (hot-water request) | S3 below the hot-water setpoint → A11, A10, A7. The setpoint input is not wired (parameter in the controller). |
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
6. **The room control is outside the controller.** The heating circuits have no room sensor
   and are enabled from the network *(inferred: the smart home switches them by room
   temperature)*. The building is therefore charged in the smart home, not in the controller.
7. **Request is not run.** A5 and A11 are requests to the heat pump's own controller. The
   compressor state comes from the electric power.
8. **Solar thermal shares the lower zone.** A boosted lower zone lowers the collector yield;
   the plan must respect the collector forecast. The solar heat meter can check it.
9. **Cooling excludes heating** in the controller already; out of scope here.

## 5. Mapping of the levels

The smart home translates the generic signals. Proposal with the smallest change to the
controller program; all additions are new blocks or free inputs, nothing existing changes
its behaviour while the new network inputs are 0.

### Level 0 (today)

Earnie's `heatpump.<id>.set_enable` has no input in the program as printed: the heating
request has no external enable. How the enable acts today is an open question (Q2).

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
  comparison "S4 below a minimum" overrides it so that the heating never starves. The
  hot-water request stays unlocked: comfort first, and its energy is small.

### Level 2: targets

| Generic signal | Controller addition |
| --- | --- |
| `set_temperature_heat_storage_target` | New analog network input on a free input of `MAX(An)2`. Limited by a new minimum function against a fixed maximum (heat pump flow limit minus a margin). |
| `set_temperature_dhw_target` | New analog network input and a new maximum function with the present hot-water setpoint, on the free setpoint input of `WW_ANF`. Same limit. |
| `set_temperature_room_offset` | **No controller change in the first step:** the smart home shifts its own room setpoints and thereby the circuit enables it already sends. Second step, if the floor heating takes the heat too slowly: a raised flow setpoint on a free input of `MAX(An)4` and `MAX(An)2`. |

### Level 3: feedback

New network outputs; the smart home builds the generic signals from them.

| Generic signal | From |
| --- | --- |
| `sens_temperature_heat_storage_top` | S3 |
| `sens_temperature_heat_storage_low` | S5 |
| `sens_temperature_heat_storage` (`T_eq`) | weighted mean of S3, S4, S5 in the smart home |
| `heatpump.<id>.sens_operating_mode` | cooling if A12, else hot water if A11, else heating if A5, else off; "locked" while the lock bit is set |
| `heatpump.<id>.sens_temperature_source` | S13 (brine flow) |
| `get_temperature_heat_storage_setpoint` | result of `MAX(An)2` |
| `sens_temperature_room`, `get_temperature_room_setpoint` | already in the smart home |
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
| Store temperatures | Three sensors exist. Which of the four pockets they occupy decides the weights of `T_eq` (`waermespeicher-schichtung-teq.md`, table for this store size). |
| Top sensor, bottom sensor | Exist (S3, S5); only the path to Earnie is missing or to be confirmed. |
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
| Capacity | whole store about 1.03 kWh/K | – |
| Hot-water band | present setpoint up to the heat pump limit | controller parameters, heat pump data sheet |
| Heating-zone band | flow setpoint (about 30 °C) up to the limit | same |
| `τ_store` | – | standstill period without charge or draw |
| `τ_house` | – | cool-down nights with the smart home's room temperatures |
| COP points | – | data sheet of the heat pump; measured once a flow sensor exists |

## 8. Open questions

- **Q1 Node 48:** which device sends the network variables (C.M.I., smart home gateway), and
  how do sensor values reach the smart home and Earnie today?
- **Q2 Enable today:** how does Earnie's heat pump enable act on the plant at present?
- **Q3 Controller parameters:** hot-water setpoint and times, request and switch-off
  differences of `HZ_ANF` and its switch-off sensor, heating curves, minimum run times.
- **Q4 Heat pump:** maximum flow temperature, fixed speed or modulating, what A5 and A11 do
  inside its controller (two setpoints?), minimum run and pause times, lock input.
- **Q5 Sensor pockets:** which three of the four store pockets hold S3, S4, S5.
- **Q6 Circuit enables:** are digital inputs 2 and 3 switched by room temperature, by
  schedule, or constantly on?
- **Q7 Heating rod:** none is in the schema. Is one installed or planned?
- **Q8 Sensor labels:** S12 (heat pump return?), S2 (solar flow, unused in the program), S10.
