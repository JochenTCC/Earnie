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

**The print is not the running program.** The maintainer read the affected blocks and the
network variables at the controller on 2026-11-15; the result is in section 3.4 and worked
into sections 4 to 9. Sections 3.1 to 3.3 still describe the print. Where the two differ,
section 3.4 is valid.

## 1. Plant

| Part | Data |
| --- | --- |
| Heat pump | Weider SW 70, brine-water, ground source with brine distributors |
| Store | one combined store, 887 l, three sensors at their own position marks, not in the four sensor pockets (section 3.4), solar coil in the lower part |
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

### 3.4 Check of the running program (2026-11-15)

Read at the controller display at 8:00 with 1 °C outside, wall heating window active. Ambiguous
entries of the filled-in sheet were confirmed by the maintainer the same day.

**`MAX(An)2`**

| Input | Source | Value |
| --- | --- | --- |
| 1 | flow setpoint of the floor heating | 31.5 °C |
| 2 | flow setpoint of the wall heating | 41.1 °C |
| 3 | **network analog input 5** (store setpoint from Loxone) | 35.0 °C (the low value) |
| Result | | 41.1 °C |

There is no function between Loxone and the third input: the jump between the high and the
low store setpoint is made **in Loxone**, the controller only receives one analog value.

**`HZ_ANF`:** request sensor **S5** (store bottom), not S4 as in the print. No switch-off
sensor. Setpoint from `MAX(An)2`. Switch-on difference 2.0 K, switch-off difference 2.5 K,
minimum run time 10 min, base temperature 10 °C. **The enable input is in use:** NOT
(changeover valve hot water, A10), so there is no heating request during a hot-water charge.

**`WW_ANF`:** request sensor S3 (store top), setpoint 50 °C, differences −2.0 / 2.0 K.
Setpoint from network analog input 4, enable from network digital input 4, external switch
from network digital input 5.

**Network inputs (Loxone → controller)**

| No. | Analog | Value | | No. | Digital | Value |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | outside temperature | 2.4 °C | | 1 | cooling enable | off |
| 2 | maximum store temperature (collector re-cooling) | 94.9 °C | | 2 | enable floor heating | 1 |
| 3 | flow setpoint cooling | 20.0 °C | | 3 | enable wall heating | 1 |
| 4 | **hot-water setpoint** | 50.0 °C | | 4 | enable of `WW_ANF` | 1 |
| 5 | **store setpoint** | 35.0 °C | | 5 | external switch of `WW_ANF` | 0 |
| | | | | 6 | enable solar re-cooling | 0 |

New against the print: analog 4 and 5, digital 4 to 6. Analog inputs 6 to 16 and digital
inputs 7 to 16 are free.

**Network outputs (controller → Loxone)**

| No. | Analog | Value | | No. | Digital | Value |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | collector temperature | 4.3 °C | | 1 | solar pump | 0 |
| 2–7 | flow and return temperatures of the heat pump (per maintainer, not assigned one by one) | 0 / 32.8 / 10.3 / 14.4 / 38.4 / 41.9 | | 2 | pump wall heating | 1 |
| 8 | floor heating flow | 31.1 °C | | 3 | heating request to the heat pump | 0 |
| 9 | floor heating return | 29.0 °C | | 4 | pump floor heating | 1 |
| 10 | store bottom | 43.4 °C | | 5 | store charge pump | – |
| 11 | store middle | 43.4 °C | | 6 | changeover valve hot water | – |
| 12 | store top | 51.4 °C | | 7 | hot-water request | – |
| 13 | solar power | 0 | | | | |
| 14, 15 | energy counters of the collector | 9713 / 62 | | | | |
| 16 | wall heating flow | 41.0 °C | | | | |

**All 16 analog outputs are in use**; 9 of the 16 digital outputs are free. The print showed
one analog output.

**Timeout:** the network inputs have a timeout, set to 60 min. What a function receives
after it is not read yet.

**Functions:** 19 in the running program. New against the print: a third heating-circuit
controller named "Kühlung" and `LOGIK5`. `Timer 1` and `Zeit 4` are taken as the print's
`NACHLAUF` and `ZEIT`.

**Store sensors:** they do not sit in the four sensor pockets but at their own position
marks. Measured from the floor (2026-11-15): S5 at 57 cm, S4 at 99 cm, S3 at 145 cm; the
four pockets at 31 / 75 / 126 / 172 cm. The pockets agree with the data sheet (310 / 745 /
1250 / 1710 mm) within 1 cm, so the data sheet counts from the floor and the sensors are
at about 565 / 985 / 1445 mm of 2040 mm, that is 28 % / 48 % / 71 % of the height.

**Access:** no C.M.I. and no BL-NET, so the program cannot be downloaded.

## 4. What this means for the design

1. **Two zones, one store.** Hot water is the top zone (sensor S3), heating the lower zone
   (sensor S5, see 3.4). This is the "combined store with a hot-water zone" of the generic
   model.
2. **Sink priority is hard-wired:** during a hot-water charge both heating circuits are
   disabled. Earnie predicts this, it does not command it.
3. **The charge sensors are known:** S3 ends a hot-water charge, S5 a heating charge (the
   request sensor of `HZ_ANF`; no switch-off sensor is set). A heating charge therefore
   ends when the lowest sensor is 2.5 K above the setpoint, so the measured part of the
   store is at or above the target at the end of a charge.
4. **The heating request already is a maximum function, and its third input already comes
   from Loxone** (network analog input 5). A store target from outside enters there and
   wins over the heating curves when it is higher. The controller needs no new path for it.
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
11. **The sensors cover the store evenly.** S5 is at 28 % of the height, S4 at 48 %, S3 at
    71 % (section 3.4). The earlier assumption of sensors in the upper three pockets, with
    S5 at 37 % and a large unmeasured cold layer, does not hold. About 28 % of the height
    lies below S5 and 29 % above S3; `T_eq` extrapolates both ends from the nearest sensor.
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

The third input of `MAX(An)2` is network analog input 5, the store setpoint from Loxone
(section 3.4). Loxone switches it between a high and a low value with Earnie's
`heatpump.<id>.set_enable`; the two values are Loxone settings.

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

- **Lock:** a new digital network input. The enable input of `HZ_ANF` is in use (NOT
  hot-water valve, section 3.4), so a logic function combines the two: enable = NOT valve
  AND NOT lock. A
  comparison "S5 below a minimum" overrides it so that the heating never starves, and so
  does the wall-heating enable, so that the morning window is always served. The hot-water
  request stays unlocked: comfort first, and its energy is small.

### Level 2: targets

| Generic signal | Controller addition |
| --- | --- |
| `set_temperature_heat_storage_target` | **No controller change for the path:** Loxone sends Earnie's target on network analog input 5 instead of its two fixed values. The limit against a fixed maximum (heat pump flow limit minus a margin) is set in Loxone first; a minimum function in the controller protects against a wrong value from Loxone and is the optional second step. |
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

Most values already reach Loxone (section 3.4); the smart home builds the generic signals
from them. Only the store setpoint needs a change in the controller.

| Generic signal | From |
| --- | --- |
| `sens_temperature_heat_storage_top` | S3, analog output 12 |
| `sens_temperature_heat_storage_low` | S5, analog output 10 (lowest sensor, not the bottom of the store) |
| `sens_temperature_heat_storage` (`T_eq`) | weighted mean of S3, S4, S5 in the smart home |
| `heatpump.<id>.sens_operating_mode` | cooling if Loxone's own cooling enable is set, else hot water if digital output 7, else heating if digital output 3, else off; "locked" while the lock bit is set. No new output. |
| `heatpump.<id>.sens_temperature_source` | S13 (brine flow), one of the analog outputs 2–7. Valid only while the heat pump runs (at standstill the brine in the pipes is influenced by other temperatures), so Loxone holds it as in section 8.2 of the generic design: running = electric power above a threshold, settling time after the start, mean over the run frozen at the stop. |
| `get_temperature_heat_storage_setpoint` | result of `MAX(An)2`. Exported from the controller, not rebuilt in Loxone: a copy of the heating curves would drift from the original. **All 16 analog outputs are in use, so one has to be freed for it** (Q8). |
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
| Store temperatures | Three sensors, all available in Loxone. Per the check of 2026-11-15 they are at their own position marks, not in the sensor pockets, so the heights assumed so far (745 / 1250 / 1710 mm of 2040 mm) and the weights derived from them (bottom 0.49, middle 0.24, top 0.27) do not apply. With the measured heights (section 3.4) and the method of `waermespeicher-schichtung-teq.md` (layer boundaries halfway between the sensors, at 775 and 1215 mm) the weights of `T_eq` are **bottom 0.38, middle 0.22, top 0.40**. For the values of the check (43.4 / 43.4 / 51.4 °C) this gives 46.6 °C instead of 45.6 °C with the old weights, about 1 kWh more heat content. |
| Top sensor | Exists (S3). |
| Bottom sensor | Exists (S5) at 28 % of the height. The lowest pocket (310 mm) is free; a fourth sensor there would measure the coldest layer directly, but with both ends covered about equally it is an improvement, not a prerequisite. |
| Operating mode | Derivable in Loxone from the two requests it already receives (digital outputs 3 and 7) and its own cooling enable. |
| Room temperature | Not in the controller; expected in the smart home. |
| Source temperature | Exists (S13, S14). |
| Thermal power of the heat pump | **Missing.** Flow and return temperature exist (S11, S12) but no flow meter, and the charge pump is speed-controlled. A flow sensor in the heat pump circuit would give the measured COP. |
| Solar heat | Exists (heat meter). |
| Electric power of the heat pump | Exists in the smart home (confirmed 2026-11-16); not part of the controller. Also the "running" condition for the held source temperature. |
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

- **Q1 Running program:** answered by the check of 2026-11-15 (section 3.4).
- **Q2 Setpoints of the enable:** the high and the low value are Loxone settings. The low
  value is 35.0 °C, the high value at present 55 °C (hot-water setpoint plus 5 K). The
  fixed boost of level 0 is therefore 20 K, and with the request sensor S5 a charge ends
  when the lowest sensor reaches 57.5 °C: the whole measured store is then at hot-water
  temperature. The configured `heat_storage.setpoint_c` has to match the high value until
  Loxone reports the band (section 5, level 0). **Decided 2026-11-15:** the high value in
  Loxone is lowered to the configured band instead of raising the configuration, because
  the plan still counts with a constant efficiency and would charge hot too often. With
  the switch-off difference of 2.5 K at S5 the high value is `setpoint_c` minus 2.5 K, so
  that a charge ends at the configured setpoint. Hot water is not affected (own request,
  sensor S3). Set in Loxone on 2026-11-15; the values of section 3.4 show the state before. With a floor heating
  setpoint of 31.5 °C at 1 °C outside, the low value lies above the floor heating curve on
  most days: it acts as the permanent boost that section 5 advises against, and is to be
  reviewed with HeatControl P3. Needed for
  the Scenario Explorer's configured values and until Loxone reports the band.
- **Q3 Heat pump interface:** to which terminals of the Weider SW 70 A5 and A11 go and what
  they do there; maximum flow temperature; fixed speed or modulating; whether it has a lock
  input. Sources: the heat pump's wiring diagram or the installer. Not blocking: levels 1–3
  need only the requests the controller already sends, and the recording of section 7 gives
  the behaviour.
- **Q4 Controller parameters:** the differences and the minimum run time of `HZ_ANF` are
  read (section 3.4). Open: both heating curves.
- **Q5 Network timeout:** the network inputs have a timeout of 60 min. Open: which value a
  function receives after it, and whether 60 min is short enough for the store setpoint
  (a high target would stay active for up to an hour when Loxone is silent).
- **Q6 Sensor labels:** S12 (heat pump return?), S2 (solar flow, unused in the program), S10.
- **Q7 Sensor heights:** answered 2026-11-15 (section 3.4, weights in section 6). The
  weights 0.38 / 0.22 / 0.40 are set in the `T_eq` formula of the smart home since that day.
- **Q8 Analog network outputs:** answered 2026-11-15. The outputs 2–7 carry flow and return
  temperatures of the heat pump, 14 and 15 energy counters of the collector; per the
  maintainer any of them may be replaced. Proposal: give up a collector energy counter (or
  output 2, which read 0) for the result of `MAX(An)2`, and keep the heat pump
  temperatures: the brine flow is the source temperature of level 3, and flow and return
  are needed to learn the heat pump's behaviour (section 7). Which output carries which
  sensor is still to be assigned.

## 9. Implementation order on this plant

Order decided 2026-11-15: the generic phases of
[heat-control-sg-ready.md](heat-control-sg-ready.md) § 11 come first, each with the smallest
translation that makes it usable here. The steps that exist only because of the wall heating
follow after them.

### 9.1 Translation per generic phase

Nothing in this table is specific to the wall heating.

| Phase | In Loxone | In the controller | Before the phase |
| --- | --- | --- | --- |
| HeatControl P1 Feedback | Builds the level 3 signals of section 5 from values it already receives: S3 as top sensor, the operating mode from the two requests, the room mean. New: the store setpoint and the source temperature. | One analog network output re-assigned to the result of `MAX(An)2` (proposal: a collector energy counter, Q8). No new digital output. | Assignment of the analog outputs 2–7 to the sensors. |
| HeatControl P2 Operating state | State 3 sends today's high value, state 2 the low one. No lock bit. | None. | Q2 (the two values), Q5 (network timeout). |
| HeatControl P3 Store target | Sends Earnie's target on network analog input 5, limited to a fixed maximum; the low value while the state is 2. | None in the first step; optional minimum function against a fixed maximum. | Maximum flow temperature of the heat pump (Q3). |
| HeatControl P4 Two leaky stores | None. | None. | `τ_store` and `τ_house` from the recording of P1. The new `T_eq` weights (section 6) entered in the smart home before the recording starts. |
| HeatControl P5 COP by temperature | Holds the brine temperature for `sens_temperature_source` (section 5, level 3). | None. | COP points from the data sheet of the heat pump; the brine temperature comes from P1. Collector forecast against the solar heat meter. |
| HeatControl P6 Building as a store | Adds the offset to the setpoints of the participating rooms. | None in the first step (section 5, level 2). | Which rooms take part. |
| HeatControl — hot-water level (follow-up item) | Sends the larger of its own hot-water setpoint and Earnie's target on network analog input 4 (section 5, level 2). Delaying a charge would use the enable of `WW_ANF` (network digital 4), which Loxone already sets. | None. | Comfort minimum at S3; share of the volume above the changeover port (zone split); whether Earnie may hold back a hot-water request at all. |

### 9.2 Wall heating

The morning window is the generic "scheduled minimum temperature", so the plant-specific
part is small.

| Step | Content | Kind |
| --- | --- | --- |
| HeatControl P7 Study | From the recording of P1: how often the window starts the heat pump in expensive slots, at which flow temperature, with how much energy. Gain estimated in the Scenario Explorer with a configured window. | Decision, nothing changes on the plant. |
| HeatControl P8 Ready-by | Generic code; built only after a positive study. | Generic. |
| Report the window | Loxone sends the start of the next window from its schedule and the temperature after option A (last flow setpoint held). No controller change. | Plant-specific, with P8. |
| Later, if needed | Option B (shadow controller) when the held value is too inaccurate. The wall-heating enable overrides the lock, if state 1 is ever used (O2 of the generic document). The wall heating stays out of the room offset of P6. | Plant-specific, optional. |
