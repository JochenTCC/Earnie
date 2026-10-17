# Earnie-Points

**Status:** implemented client-side (`house_config/earnie_points.py`); wire format in [`usage-ping.md`](usage-ping.md) §4 (schema v2). Rule source: business plan §5.2 "Tarifmodell" (Earnie-Projekt repo). This file is the **single source** for the rule as implemented; the public German rule table in `docs/einrichtung/betrieb.md` must stay in sync with it.

## 1. Purpose

The Earnie-Points rate the size and complexity of one **plant** (one location). The cloud tariff S / M / L is a mapping *points → tariff* that may change over time; the **points calculation itself stays constant**. Therefore:

- The client computes points from the **live** configuration only (not Scenario-Explorer scenarios, not backtesting).
- Only the point **total** goes on the wire (usage ping, schema v2). The breakdown is local (UI, tests).
- No tariff name is sent or stored by the client. The mapping to S / M / L happens at analysis time from the histogram.
- Points are not a licence check; values are fakeable like the rest of the ping statistic.

## 2. Rule (`points_v: 1`)

| Part | Config source | Points |
|---|---|---|
| `pv` | sum of `components.json` → `pv_systems[].kwp` of the PV systems the **live scenario** selects (`pv_system_ids`) | 0 if the sum is 0; 1 up to 6 kWp; then +1 per started 4 kWp |
| `storage` | sum of `batteries[].battery_capacity_kwh` of the house batteries the live scenario selects (`battery_ids`) **and all powerstations** (always part of the plant) | 0 if the sum is 0; 1 up to 5 kWh; then +1 per started 5 kWh |
| `wallbox` | live house profile, consumer `type: ev` (one consumer = one wallbox) | 1-phase 1; 3-phase 2; `bidirectional: true` 3 |
| `heat` | live house profile | 1 per `thermal_annual` consumer (heat pump); 1 per consumer with `appliance_kind: air_conditioner` |
| `other` | live house profile | 1 per flexible large consumer: `thermal_rc`, or `generic` with `earnie_role: flex`, with `nominal_power_kw >= 2.5` and not already counted in `heat` |
| `total` | sum of the parts above | |

Formulas (`kwp`, `kwh` are sums, `ceil` = round up):

```text
pv      = 0                                  if kwp == 0
        = 1                                  if 0 < kwp <= 6
        = 1 + ceil((kwp - 6) / 4)            if kwp > 6
storage = 0                                  if kwh == 0
        = 1                                  if 0 < kwh <= 5
        = 1 + ceil((kwh - 5) / 5)            if kwh > 5
```

Boundaries: 6.0 kWp = 1, 6.1 kWp = 2, 10.0 kWp = 2, 10.1 kWp = 3; 5.0 kWh = 1, 5.1 kWh = 2, 10.0 kWh = 2, 10.1 kWh = 3.

### Details and decisions

- **Phases of a wallbox** come from `settings/ev_power.ev_nominal_power_conversion(consumer)` (`charging_schedule.nominal_power_phases`, then `charging_schedule.loxone.nominal_power_phases`, then the default 1). Only 1 and 3 are valid for points; any other value raises `ValueError` (no guessing). There is **no** kW-based heuristic.
- **Bidirectional** is the optional bool `bidirectional` on `ev` consumers (absent = false). A bidirectional wallbox scores 3 regardless of phases.
- **Number of EVs is not rated**; only wallboxes (EV consumers) are.
- **Manual consumers are never counted.** For `generic` consumers only the role `flex` is eligible (`manual` and `known` are not controlled by Earnie). `thermal_annual`, `thermal_rc` and `ev` consumers are always controlled by Earnie.
- **Air conditioner:** optional `appliance_kind: "air_conditioner"` on `generic` or `thermal_rc` consumers. It counts 1 point in `heat` regardless of power; for `generic` the role must be `flex`.
- **No double counting:** each consumer contributes to exactly one part (`wallbox`, `heat` or `other`). Powerstation-attached consumers are ordinary consumers of the profile and are counted once there.
- **One plant = one location = one ping.** No cross-location sums.
- Several wallboxes behind one `ev` consumer, or an EV without its own wallbox (car API only), count as one wallbox as long as there is no wallbox entity (see backlog "Enable multiple EV / Wallboxes").
- Invalid or missing numeric fields raise `ValueError` naming the component; there are no silent defaults.

## 3. Examples (test fixtures)

| Plant | pv | storage | wallbox | heat | other | total |
|---|---|---|---|---|---|---|
| 6 kWp + 1-phase wallbox | 1 | 0 | 1 | 0 | 0 | 2 |
| 10 kWp + 9 kWh + heat pump | 2 | 2 | 0 | 1 | 0 | 5 |
| 20 kWp + 15 kWh + 3-phase wallbox | 5 | 3 | 2 | 0 | 0 | 10 |

## 4. Client integration

- `house_config/earnie_points.py`: `compute_earnie_points(components, profile) -> {"total","pv","storage","wallbox","heat","other"}`. Pure, no I/O.
- `runtime_store/usage_points.py`: resolves the **live scenario** (`config.json` `live_scenario_id` → `backtesting_scenarios.json`), selects its PV systems and house batteries (plus all powerstations) from `components.json`, takes its `house_profile_id` profile, and calls the pure calculation. Components that exist in `components.json` but are not part of the live scenario (e.g. alternatives for the Scenario Explorer) are **not** counted. An id the live scenario references but `components.json` / `house_profiles.json` lacks raises (no fallback to "first profile").
- It recomputes only when the mtime stamp (`config.json`, `backtesting_scenarios.json`, `components.json`, `house_profiles.json`) changed and consent is `on`; the stamp is stored even after an error, so a broken config is evaluated once per change. Stores `points`, `points_v`, `points_stamp` in `runtime/usage_ping.json`.
- Hook: `note_live_cycle_success()` (live stage only, skipped in Shadow mode).
- A configuration or calculation error logs a WARNING and **removes** `points` / `points_v` from the state; the ping stays valid as schema v1 and never affects the cycle.
- A change of the points value (consent `on`) clears the daily send gate so the ping is sent again the same UTC day (like the scenario counter).

## 5. Privacy

The point total is a coarse derived number; it does not contain configuration content. It is part of the "Was wird gesendet?" preview. Schema v2 is covered by the existing opt-in; no re-consent prompt (transparency only: preview, German docs, privacy note).

## 6. Rule changes

A change of the rule bumps `points_v` (the constant in `house_config/earnie_points.py`) and this document. The receiver stores only the totals; histograms recorded under different `points_v` values are not comparable, so a rule change needs a note in the analysis (no client migration).
