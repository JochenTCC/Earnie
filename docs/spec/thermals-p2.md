# Thermals P2 — Coupled single-node models (slice)

Backlog: **2.7.b**. This document covers the vertical slice shipped under that chapter (heat storage + house indoor RC).

## Topology

```text
Solar collector (kWh_th) ──► Heat storage (RC) ◄── Heat pump (electric → th)
                                  │
                                  ▼ heat_to_house
                         House indoor RC (T_house) ◄── Ambient (H)
```

Without `heat_storage`, the WP charges the **house node** directly (same band control).

When `heat_storage.volume_liters > 0`, topology is enforced: solar and WP feed **only** the store; space heating and DHW draw **only** from the store (house node receives heat from that draw).

- **Store:** single-node Euler RC (`volume_liters` → C, `heat_loss_kw_per_k`). Asymmetric temperature rules (year-sim):
  - Lower bound: `setpoint_c − tolerance_c` — if projected store T (solar only) would fall below this, WP **must** heat.
  - WP ceiling: `setpoint_c` — WP heat is capped so it does not raise store T above setpoint; above setpoint WP stays off.
  - Absolute / solar ceiling: **95 °C** (`HEAT_STORAGE_ABS_MAX_C`) — solar may raise the store above setpoint up to 95 °C; only above 95 °C is solar input reduced.
- **Solar:** collector yield injected into the store each hour (not an open-loop credit on house need).
- **House:** single-node RC with capacity from DIN V 18599 Bauweise × Wohnfläche; envelope loss `H` calibrated from HWB (or explicit override). Indoor **Ist** temperature is simulated; chart also shows Soll.
- **WP:** with store — bang-bang at the store lower bound (no opportunistic pre-heat inside the band in year-sim); house requests heat from store when house band would break. Without store — WP on/off from house band. Electric kWh = `nominal_power_kw` when on (thermal = `nominal_power_kw × JAZ`), prorated if WP heat is capped at setpoint within the hour.
- **Warm water:** daily thermal load on the store when coupled; without store, WW÷JAZ added as open-loop electric each hour.

## House capacity (Bauweise)

| `building_mass` | C [Wh/(m²K)] (DIN V 18599-2) |
|-----------------|------------------------------|
| `leicht` | 50 |
| `mittel` (default) | 90 |
| `schwer` | 130 |

`C_house [kWh/K] = c × living_area_m2 / 1000`.

Envelope `H [kW/K]`: if `house_heat_loss_kw_per_k` > 0 use it; else  
`H = annual_HWB_heat / Σ_h max(0, target − T_out)` for hours with `T_out < heating_limit`.

Band: heat when projected next temp (no heat) `< target_temp_c − house_tolerance_c` (default tolerance 0.5 K).

## Config

```json
"thermal": {
  "living_area_m2": 140,
  "building_mass": "mittel",
  "house_tolerance_c": 0.5,
  "house_heat_loss_kw_per_k": null,
  "heat_storage": {
    "volume_liters": 800,
    "heat_loss_kw_per_k": 0.02,
    "setpoint_c": 45.0,
    "tolerance_c": 5.0
  }
}
```

## Compatibility

- `living_area_m2 <= 0`: legacy open-loop HDD electric path (no house RC).
- `heat_storage` absent or `volume_liters <= 0`: house RC + direct WP (no store node).

## HK visualization

Hauskonfigurator **Stündlicher Verlauf** secondary **°C** axis:

- Außentemperatur, Haus-Solltemperatur, **Haus-Isttemperatur**, Wärmespeicher (if configured), Pool/SwimSpa (`thermal_rc`)

Builder: [`data/modeled_temperatures.py`](../../data/modeled_temperatures.py). When `solar_thermal_area_m2 > 0`, the chart path loads Open-Meteo tilted collector irradiance and passes it into `house_year_result` (same as the modeled WP load profile) so store temps can rise above setpoint from solar.

## Stratified store → energy-equivalent `T_eq`

Real DHW / buffer tanks are often **stratified** with several temperature sensors (typically three or four heights). The RC store is **single-node**. For Live Ist/Modell comparison and later Thermals P3 adaptation, the smart-home backend must supply **one** temperature that preserves heat content.

### Definition

With configured capacity `C = capacity_kwh_per_k_from_volume(V)` and reference 0 °C:

```text
Q = C × T_eq
T_eq = Σ (V_i · T_i) / V_total
```

Sensors at the centres of equal-height layers → arithmetic mean:

```text
T_eq = (T1 + … + Tn) / n
```

Or weights `w_i` with `Σ w_i = 1`: `T_eq = Σ w_i · T_i`. End layers extend to tank bottom / top, so the outermost sensor carries the full end-layer volume share; with three sensors the weights are usually **unequal** (e.g. sensors at 25 / 50 / 75 % of height → 0.375 / 0.25 / 0.375).

Do **not** use top-only, bottom-only, min/max, or setpoint as the RC state. Top sensor may remain for DHW comfort logic separately.

### Virtual heat content (2.7.b)

| Path | Temperature | Heat content |
|------|-------------|--------------|
| Model | `T_sim` from RC | `Q_sim = C(V_config) × T_sim` via `heat_content_kwh` |
| Measured | `T_eq` from SM (`sens_temperature_heat_storage`) | `Q_meas = C(V_config) × T_eq` |

Same `C` for both until adaptation changes effective capacity.

**Shipped:**

- Helper: [`optimizer/thermal_model.py`](../../optimizer/thermal_model.py) `heat_content_kwh`
- Year-sim / HK: `Q_sim` hour series on `ConsumptionSeriesBundle.heat_content_*` ([`data/modeled_temperatures.py`](../../data/modeled_temperatures.py)); weekly kWh chart under Gesamt-Lastverhalten
- Live: each cycle appends heat-storage (+ pool) `heat_content_kwh` into `thermal_observability` on `runtime/optimization_history.jsonl` ([`optimizer/thermal_live_store.py`](../../optimizer/thermal_live_store.py) `collect_heat_storage_observability`); HK chart overlays `Q_meas` when history exists
- Stratified-tank **weights `w_i`** remain operator/field work (not coded in Earnie)

### Loxone guideline (operator-facing)

German step-by-step (formula Merker, default equal weights, identifying `w_i` from geometry / quiet vs stratified periods):

[`docs/konfiguration/waermespeicher-schichtung-teq.md`](../konfiguration/waermespeicher-schichtung-teq.md)

Concept anchor (Earnie-Projekt): Entwicklungsplan §3.5.

## Out of scope (still on 2.7.b / later)

- Explicit hourly passive window / internal gains
- 2R2C (air + deep mass)
- Energy-certificate import
- Adaptation P2 update loop / Thermals P3 parameter adaptation
- Reference-install `T_eq` weight verification (field)
- Air conditioning consumer
- MILP thermal SoC decision variables (Live remains daily electric kWh flex + open-loop forced ON; no store-T variables in the solver)
- Heat-pump setpoint-only control (2.+1)

## Live / MILP store floor (2.7.b)

When `heat_storage.volume_liters > 0` on a Live snapshot:

1. Read `sens_temperature_heat_storage` (`T_eq`) and optional `sens_temperature_heat_storage_low` (`T_low`).
2. Missing `T_eq` → start at `setpoint_c`. Missing `T_low` → skip bottom hint.
3. Open-loop horizon plan ([`optimizer/thermal_live_store.py`](../../optimizer/thermal_live_store.py)) uses the same store step as year-sim (`step_coupled_hour`).
4. Forced ON QH when the plan would turn WP on; additionally if `T_low < setpoint − tolerance`, force the near-term hour even when `T_eq` is still above the floor.
5. Day energy ≥ `max(climate day, floor + opportunistic headroom to setpoint)`. Timing of non-forced energy stays MILP flex. Year-sim stays floor bang-bang only.
6. SE / non-Live matrices keep climate day targets only (no forced ON overlay).

## Code

- House RC: [`optimizer/thermal_house.py`](../../optimizer/thermal_house.py)
- Store step + wrappers: [`optimizer/thermal_coupled.py`](../../optimizer/thermal_coupled.py)
- Live store floor planner: [`optimizer/thermal_live_store.py`](../../optimizer/thermal_live_store.py)
- Heat content helper: [`optimizer/thermal_model.py`](../../optimizer/thermal_model.py) `heat_content_kwh`
- HK heat-content overlays: [`data/modeled_temperatures.py`](../../data/modeled_temperatures.py); chart [`ui/consumption_display/charts.py`](../../ui/consumption_display/charts.py) `heat_content_week_chart`
- Day targets: [`data/heating_need.py`](../../data/heating_need.py) `daily_electric_kwh` → `house_year_result` when Wohnfläche > 0
- Live flex: [`optimizer/thermal_flex_context.py`](../../optimizer/thermal_flex_context.py)
