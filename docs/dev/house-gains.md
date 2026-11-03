# House gains and H re-calibration (SUSI P2)

Status: implemented 2026-11-03 (data model 5, step `dm5.house_gains`). Design source:
`Earnie-Projekt/Entwicklungsplan/Offen/Earnie-SUSI-Epic-Entwurf.md` § P2. User docs:
`docs/konfiguration/flexible-verbraucher.md` § *Heizwärme und Gewinne*.

## Data model

| Field | Where | Missing = |
| --- | --- | --- |
| `baseload_internal_gain_factor` | profile | 0.8 (schema default) |
| `internal_gain_factor` | consumer (D1: on the electrical unit) | type default (`x-earnie-type-defaults`: generic 0.8, ev / thermal_rc / thermal_annual 0); `pool_filter` 0 |
| `internal_gain_factor` | heating-rod part (`components.json` catalog) | 0; any other value fails loud |
| `thermal.gross_floor_area_m2` | house block | living area × 1.25 |
| `thermal.solar_gains` | house block | `enabled: false`, windows 0, g 0.6, frame 0.5 |

A `thermal_annual` consumer's factor must be 0 (its heat is the model). The migration writes
every field explicitly (solar gains off, windows from the SUSI cuboid); the Hauskonfigurator
starts a new building block with solar gains on.

The loader places an `internal_gains` descriptor into the normalized heating consumer's
`thermal`: Jahresverbrauch, Grundlast factor and the other planned consumers (stripped of
bindings). Every reader of the thermal block passes it on via `heating_params_from_thermal`;
the serializer never writes it.

## Year model (`optimizer/thermal_house.py`)

- Gains per hour: window gain (`optimizer.house_gains.solar_gain_kw_series`, four vertical
  Open-Meteo surfaces) + Σ other consumers' modeled kW × factor + Grundlast kW × factor.
  The RC step adds them to the heat balance; `house_requests_heat` projects with them.
- **Venting** [assumption]: the indoor temperature is capped at target + 3 K (`VENT_MARGIN_K`),
  never below the outdoor air. Without it a sunny house overheats without bound and carries
  heat into autumn.
- **Calibration on an ideal heater.** H is solved so that an ideal heater without power limit,
  holding `target_temp_c`, delivers HWB × BGF after gains (`calibrate_house_heat_loss_with_gains`,
  bracket + secant, monotone in H). Calibrating on the real bang-bang run diverged when the
  heat pump is undersized (delivered heat saturates, H grows without bound); the ideal heater
  keeps H a building property. The real run then uses that H, so an undersized heat pump
  delivers less than the HWB, as before. The old HDD estimate (with `heating_limit_c`) is only
  the bracket start.
- **Grundlast fixed point.** Grundlast = max(2 % floor, annual − other consumers − own heating
  electric). The own draw depends on the gains, so the loop recalibrates H with the Grundlast of
  the last run until the heating electric changes less than 1 kWh (2–3 runs). Fuel heat sources
  draw no electricity.
- **Scenario variants** (`apply_scenario_heating_systems`): the variant's descriptor carries
  `reference_heating` (efficiency, electric flag, store, input power of the installed system).
  The variant simulates the reference once for its electric draw and keeps that Grundlast; no
  fixed point. Without this a gas variant would count the old heat pump's draw as household heat.
- An H override skips the calibration; the gains then lower the annual demand.
- `HouseYearResult` carries the H it used and the delivered space heat; `ThermalParameters`
  (Live) reads H from there instead of a separate HDD calibration, so Live and year model share
  one H.
- Solar gains on but no hourly window series (offline daily fixture, or a caller that forgot
  `thermal_climate_kwargs`) fail loud. Internal gains work on both climate sources.

## Live (`optimizer/thermal_live_gains.py`)

- Windows: `get_hourly_tilted_irradiance_forecast_wm2` per direction (cached like the collector),
  archive year fallback with a warning (same rule as ThermalHorizon P3).
- Grundlast: hourly mean of the matrix column `expected_p_act` × factor. The observability
  snapshot has no matrix and uses the flat Grundlast of the year model.
- Other consumers: `modeled_consumer_kw_at_datetime` × factor.
- Known overlap: a manual appliance run the user scheduled is added to `expected_p_act`
  (`apply_appliance_schedules_to_matrix`) and also appears in its consumer's modeled schedule,
  so on such days it counts twice (once with the Grundlast factor). Small; revisit if the Live
  house temperature runs warm on appliance days.
- House plan without store: gains in `_step_hour_direct_wp`; store plan: `_space_heat_demand_kw`
  subtracts the gain from the envelope hold.

## Result change

All houses with heating change once: HWB on BGF (+25 % annual heat without explicit BGF),
internal gains always on, ideal-heater calibration (no heating-limit cut in the year
calibration). Golden masters and the SE SNAP comparison need triage (`regression-triage`).
