# Horizon shading (SUSI P3a)

Status: implemented 2026-11-19, manual input only (decision 21 of the SUSI epic). `horizon` for
forecast.solar since 2026-11-20 (**SUSI P3a-2**, Version 2.8); PVGIS import and obstacle input as **SUSI P3a-3**. User docs:
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

## Editor (`ui/house_config_profile_horizon.py`, `ui/horizon_bars_component.py`)

- One bar per 22.5°, north to north clockwise, labelled with the azimuth of the PV fields
  (S 0°, E −90°, W 90°, N ±180°; compass bearings were tried first and dropped on 2026-11-20,
  the bar under the sun path already shows the direction); the stored azimuth stays
  south-based. Drag with the mouse or step by 1° with the buttons under the axis.
- The bars are a Streamlit component (`st.components.v2`, inline HTML/CSS/JS, no asset to
  package). Its state `elevations` is sent when the mouse is released or 0.6 s after the last
  button step. The component key must not contain `__`, so it is not a `_scoped_key`.
- Active are the directions within one step of a sun azimuth on 21 June, the equinox or
  21 December (`active_directions`). The others are stored as 0°; a stored value there is
  dropped with a notice.
- Every change saves the profile and rebuilds the annual heat preview on the same page. That
  needs no request, see *Archive cache*.

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
| Archive bundle | `build_open_meteo_climate_bundle` | every surface series shaded; cache file `…_<surfaces>_hzraw.json` (see below) |
| Forecast | `get_hourly_tilted_irradiance_forecast_wm2(shading=…)` | own cache entry per horizon token |
| Previous Runs (SE forecast mode) | `fetch_hourly_tilted_irradiance_day1_forecast_wm2_series` | `direct_normal_irradiance_previous_day1` of the same run |

## Archive cache

With a horizon the cache file holds what Open-Meteo sent: the unshaded UTC payloads of the
temperature and of every surface with its DNI (`{"version": 1, "payloads": {...}}`, one entry
per request). It is the same file for every horizon of the site; the mask is applied when the
bundle is read, and the shaded bundle is kept in memory only (eight per process, keyed on the
file and the horizon token). A file with a missing entry fails loud. The file without a horizon
is the one from before; turning the horizon on fetches the year once more with DNI.

The regression climate fixture tracks and records this file like the others and refuses the
raw fetch outside recording.

## Where it applies

- `ModeledClimateContext` (SE, annual model, PV, collector, windows): horizon of its house profile.
- `reference_climate_for_thermal`, `_thermal_annual_daily_from_archive`: horizon carried by the
  `thermal` block. `house_thermal_parameters` keys its cache on the horizon token, so the P2
  calibration of H runs on the shaded gains and the annual heat still matches the HWB.
- Live: window gains (`optimizer/thermal_live_gains.py`), collector
  (`optimizer/thermal_live_solar.py`) and the PV forecast (`data/pv_forecast.py`): the line is
  passed to forecast.solar as `?horizon=` (SUSI P3a-2, 2026-11-20) and the Open-Meteo substitute
  shades with the same line.
- forecast.solar format (`solar_horizon.forecast_solar_horizon_param`): 36 elevations at 10°
  steps, clockwise from north (compass bearing `b` = our azimuth `b - 180`), whole degrees.
  The line **replaces** forecast.solar's default PVGIS terrain horizon. Without a horizon the
  URL is unchanged, so the in-memory / disk cache and the Shadow feed key (`url_hash`) stay;
  a new or changed line is a new URL (first fetch without cache, counts against the public
  rate limit of 12 calls per hour and IP). Checked 2026-11-20 on the public plan without key:
  accepted, a test site with 40° to the west lost about 14 % of its daily yield.
- SE forecast mode (`simulation/forecast_mode.py`): the archived forecast is shaded like the
  booked PV before the monthly scaling.

## Cost

One year, five surfaces: about 18 s for the first build with a horizon (72 requests, twelve
per surface carry one more variable). Every other horizon of the site: 0.1 to 0.3 s for the
mask (about 35,000 sun positions, cached per site and hour in the process), no request.

## Tests

`tests/test_solar_horizon.py` (interpolation, validation, sun position, mask incl. sunrise hour,
night and DST days, requests with and without horizon, profile round trip, wiring) and
`tests/apptest/test_house_horizon_apptest.py` (editor; AppTest mounts the component and the
tests set its state), `tests/test_house_horizon_editor.py` (axis and labels, active directions, checks).
Dragging and the buttons are checked in the browser only.
