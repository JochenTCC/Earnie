# Horizon shading (SUSI P3a)

Status: implemented 2026-11-19, manual input only (decision 21 of the SUSI epic). PVGIS import,
obstacle input and `horizon` for forecast.solar follow as **SUSI P3a-2**. User docs:
`docs/konfiguration/batterie-pv.md` § *Horizont*.

## Data model

| Field | Where | Missing = |
| --- | --- | --- |
| `horizon_source` | profile | `none` |
| `horizon` | profile, list of `{azimuth_deg, elevation_deg}` | no horizon |

- Azimuth as for the PV fields and Open-Meteo: 0° = south, -90° = east, 90° = west, ±180° = north.
  Elevation 0–90°. Linear interpolation between the points, also across ±180°.
- `manual` needs the list. `none` with a list is the configurator's switch turned off: the list
  stays stored and is not applied. A list without `horizon_source` fails loud.
- No migration step: a profile without the fields behaves as before, and the normalized profile
  and the saved file get no horizon key (precedent `heat_source.cop_points`).
- The loader copies an applied horizon into the normalized heating consumer's `thermal`, as it
  does with latitude and longitude. The serializer never writes it there.

## Mask (`data/solar_horizon.py`)

Open-Meteo's hourly irradiance is the mean of the hour before its stamp. For the hour ending at
a UTC stamp the sun position (`astral`, no `pvlib`) is sampled four times:

    GTI_shaded = GTI − DNI × Σ(blocked_i × max(0, cos AOI_i)) / n_up

- `blocked_i`: the sun is above 0° and below the horizon elevation at its azimuth.
- `n_up`: samples with the sun above 0°. The hourly DNI is a mean over the whole hour, the beam
  exists only while the sun is up, so the hour of sunrise and sunset is not counted too low.
- The result is clipped at 0. Diffuse and ground-reflected irradiance stay; Open-Meteo's
  transposition is kept, there is no sky model of our own.
- The mask runs on the UTC stamps of the response, before the series is converted to the local
  wall clock. The clock change cannot move it.
- A missing tilted value stays missing. A missing DNI makes the hour missing when a sample is
  blocked; it is not guessed.
- The tilt and azimuth of the mask are the whole degrees Open-Meteo is asked for.

## Requests

`direct_normal_irradiance` is asked for only with a horizon, in the same request as the tilted
irradiance of the surface. Without a horizon the request parameters, the shadow feed keys
(`ext:outdoor:<hash>`), the opendata parity fixtures and the archive cache file name are the
ones from before.

| Path | Function | With a horizon |
| --- | --- | --- |
| Archive bundle | `build_open_meteo_climate_bundle` | every surface series shaded; cache file `…_<surfaces>_hz<token>.json` |
| Forecast | `get_hourly_tilted_irradiance_forecast_wm2(shading=…)` | own cache entry per horizon token |
| Previous Runs (SE forecast mode) | `fetch_hourly_tilted_irradiance_day1_forecast_wm2_series` | `direct_normal_irradiance_previous_day1` of the same run |

## Where it applies

- `ModeledClimateContext` (SE, annual model, PV, collector, windows): horizon of its house profile.
- `reference_climate_for_thermal`, `_thermal_annual_daily_from_archive`: horizon carried by the
  `thermal` block. `house_thermal_parameters` keys its cache on the horizon token, so the P2
  calibration of H runs on the shaded gains and the annual heat still matches the HWB.
- Live: window gains (`optimizer/thermal_live_gains.py`), collector
  (`optimizer/thermal_live_solar.py`) and the Open-Meteo PV substitute (`data/pv_forecast.py`).
  forecast.solar gets no `horizon` parameter yet (its default is the PVGIS terrain horizon).
- SE forecast mode (`simulation/forecast_mode.py`): the archived forecast is shaded like the
  booked PV before the monthly scaling.

## Cost

One year, three surfaces: about 13 s for the first build (twelve requests per surface carry one
more variable; about 35,000 sun positions, cached per site and hour in the process). Later
builds read the cache file.

## Tests

`tests/test_solar_horizon.py` (interpolation, validation, sun position, mask incl. sunrise hour,
night and DST days, requests with and without horizon, profile round trip, wiring) and
`tests/apptest/test_house_horizon_apptest.py` (editor).
