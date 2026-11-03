# House cooling (air conditioning as inverse heat source)

Status: implemented 2026-11-03 (data model 5, step `dm5.house_cooling`). Backlog item: "Air
conditioning must be another optional inverse heat source as part of annual_rc". User docs:
`docs/konfiguration/flexible-verbraucher.md` § *Kühlung (Klimaanlage)*. Builds on the house
gains of [house-gains.md](house-gains.md).

## Decisions (maintainer, 2026-11-03)

- **Data shape:** a `cooling` block on the house's `thermal_annual` consumer, next to the heating
  system reference: `type` (`split` = own device, `heat_pump` = the reversible heat pump of the
  heating system), `seer`, `cooling_power_kw` (thermal), `setpoint_c`. No separate consumer.
- **Switch:** a second profile switch `cooling_enabled` („Kühlung betrachten“), independent of
  `heating_enabled`. Cooling without heating is allowed.
- **Scope:** year model and Scenario Explorer (consumption, Grundlast, Earnie-Points). Live
  control of the air conditioning is a backlog follow-up.
- **Migration:** `appliance_kind` is removed from every consumer; each removed
  `air_conditioner` flag is a manual to-do (the device data cannot be derived from the flag).

## Data model

| Field | Where | Missing = |
| --- | --- | --- |
| `cooling_enabled` | profile | false |
| `cooling` | `thermal_annual` consumer (only there; elsewhere fails loud) | no device |
| `cooling.type` | | required: `split` / `heat_pump` (`heat_pump` needs heat source `heat_pump`) |
| `cooling.seer` | | type default (`x-earnie-type-defaults`): split 5.0, heat_pump 4.0 [assumption] |
| `cooling.cooling_power_kw` | | 3.5 |
| `cooling.setpoint_c` | | 26.0 |

`cooling_enabled: true` without a device fails loud. The device is kept when the switch is off.
`house_config.house_cooling.cooling_consumer(profile)` finds the carrier in `consumers` or, with
the heating switch off, in `inactive_consumers` (the parked heating consumer also gets the
`internal_gains` descriptor now, for the cooling run).

## Year model (`optimizer/thermal_house.py`)

- `_simulate_house_year(..., cooling=None, heating_booked=True)`. After each hour step (and
  venting), `cool_house_temp` takes the house back to `setpoint_c`, at most `cooling_power_kw`
  of cold per hour; electricity = cold / SEER. `HouseYearResult.hourly_cooling_electric_kw`
  (8760 values) and `annual_cooling_kwh` (cold).
- The cooling electricity is **never** in `daily_electric_kwh`: that series is the heat source's
  input and feeds heat (input × efficiency), fuel, the MILP heating target and the heating rod
  cap.
- `heating_booked=False` (cooling run of a house with the heating switch off): the heating is
  still simulated so the indoor temperature is right, but its input energy is 0 (it stays in the
  Grundlast).
- The Grundlast fixed point counts heating (when booked and electric) plus cooling as the
  house's own draw.
- The H calibration ignores the cooling (ideal heater, building property).
- Venting (target + 3 K, never below the outdoor air) acts before the cooling, so the device
  runs mainly when the outdoor air itself is above the setpoint. Without solar gains a Central
  European house hardly needs cooling in this model.

## Where the cooling load enters (`optimizer/house_cooling.py`)

The cooling is a **fixed** load computed from its own house-year call
(`cooling_params`: heating params + `cooling` + `heating_booked`); the heating paths call the
year model without `cooling`, so heating results are unchanged.

| Path | Function |
| --- | --- |
| Grundlast | `resolve_profile_baseload` → `compute_baseload_kwh(cooling_kwh=…)` (reference system) |
| Live forecast overlay, SE baseload overlay | `thermal_hourly_overlay` adds `cooling_kw_for_slots` (also for a MILP heating or a parked heating consumer) |
| SE meter residual (path B) | `meter_residual_baseload_kw` peels the cooling |
| Consumption breakdown | `build_modeled_hourly_kw_by_consumer` series `<heating id>_cooling` |
| SE per-year weather | `ModeledClimateContext.cooling_kw_at` (H from the reference year) |
| Hauskonfigurator | `ui/house_config_profile_cooling.py`: section „Kühlung“, preview kWh/a into Grundlast and household reference |
| Earnie-Points | `split` 1 heat point; `heat_pump` 1 only when the heating consumer is not counted |

## Known limits

- The heating run's internal gains still count the cooling electricity as Grundlast (the
  descriptor cannot know the cooling before the run). Summer only, small; revisit if needed.
- A scenario heating variant keeps the stored `cooling` block; `type: heat_pump` with a
  non-heat-pump variant is not re-validated.
- No Live control, no flexibility (pre-cooling via the house mass) yet.
