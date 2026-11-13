# Earnie-Points

**Status:** implemented client-side (`house_config/earnie_points.py`); wire format in [`usage-ping.md`](usage-ping.md) §4 (schema v2). Rule source: business plan §5.2 "Tarifmodell" (Earnie-Projekt repo). This file is the **single source** for the rule as implemented; the public German rule table in `docs/einrichtung/betrieb.md` must stay in sync with it.

## 1. Purpose

The Earnie-Points rate the size and complexity of one **plant** (one location). The cloud tariff S / M / L is a mapping *points → tariff* that may change over time; the **points calculation itself stays constant**. Therefore:

- The client computes points from the **live** configuration only (not Scenario-Explorer scenarios, not backtesting).
- Only the point **total** goes on the wire (usage ping, schema v2). The breakdown is local (UI, tests).
- No tariff name is sent or stored by the client. The mapping to S / M / L happens at analysis time from the histogram.
- Points are not a licence check; values are fakeable like the rest of the ping statistic.

## 2. Rule (`points_v: 3`)

Rule version 3 since 2026-11-13 (maintainer's decision, before market start). It replaces version 2 because there an upgrade of the plant could lower the total. Version 3 guarantees: **no upgrade lowers the points** (more PV, more storage, another wallbox). Every part is rounded **half up** to whole points (0.5 → 1); `kwp` and `kwh` are sums.

| Part | Config source | Points |
|---|---|---|
| `pv` | sum of `components.json` → `pv_systems[].kwp` of the PV systems the **live scenario** selects (`pv_system_ids`) | `kwp / 7` |
| `storage` | sum of `batteries[].battery_capacity_kwh` of the house batteries the live scenario selects (`battery_ids`) **and all powerstations** (always part of the plant) | `kwh / 4`; at least 3 when the plant has a wallbox, also without any storage |
| `wallbox` | live house profile, consumers `type: ev`: the distinct wallboxes they use | 2 per wallbox; **bidirectional** wallboxes add their car batteries (below) |
| `heat` | live house profile | 1 per `thermal_annual` consumer whose heat source is a heat pump (`heat_source.type: heat_pump`); 1 for the air conditioning (`cooling` with `cooling_enabled`, see below). A boiler scores 0 here. |
| `heating_rod` | live house profile, `thermal_annual` consumer with a `heating_rod` part (heating-system catalog) | by the heat source it backs up (table below) |
| `other` | live house profile | 1 per flexible large consumer: `thermal_rc`, or `generic` with `earnie_role: flex`, with `nominal_power_kw >= 2.5` |
| `total` | sum of the parts above | |

Heating-rod points per `heat_source.type`:

| `gas` | `oil` | `district_heat` | `pellets` | `wood` | `electric_direct` | `heat_pump` |
|---|---|---|---|---|---|---|
| 6 | 6 | 6 | 3 | 3 | 0 | 0 |

Formulas (`half_up(x) = floor(x + 0.5)`):

```text
pv          = half_up(kwp / 7)
storage     = half_up(kwh / 4)                        without a wallbox
            = max(3, half_up(kwh / 4))                with at least one wallbox
wallbox     = 2 * wallboxes
            + max(bidirectional, half_up(car_kwh / 4 / 4))   if bidirectional > 0
heating_rod = points(heat_source)
```

`car_kwh` is the sum of `battery_capacity_kwh` of the bidirectional `ev` consumers; `bidirectional` is their count.

Boundaries: 3.4 kWp = 0, 3.5 kWp = 1, 10.5 kWp = 2; 1.9 kWh = 0, 2 kWh = 1, 6 kWh = 2, 10 kWh = 3, 14 kWh = 4.

**Monotonicity:** every part is non-decreasing in `kwp`, `kwh` and the number of wallboxes, and no part is reduced by another one, so the total never drops when PV, storage or a wallbox is added. `tests/test_earnie_points.py` checks this over a grid of plants.

### Details and decisions

- **Phases of a wallbox do not count** (version 1 scored 1-phase 1, 3-phase 2).
- **Storage floor with a wallbox:** a plant with at least one wallbox counts at least 3 storage points, once per plant, also with no storage at all. The floor is part of `storage`, not of `wallbox`. It replaces the version 2 extra of 4 points for "wallbox without storage", which a small battery removed again.
- **Bidirectional** is the optional bool `bidirectional` on `ev` consumers (absent = false). The car batteries count a quarter of a stationary storage (maintainer's decision 2026-11-08): the wallbox part gets 1 point per 4 kWh of that quarter, at least 1 point per bidirectional wallbox. Since version 3 these points are rounded on their own; version 2 took the difference of two rounded storage values, which could drop by a point when the stationary storage grew. The car battery does not count towards the storage floor. A bidirectional `ev` consumer without `battery_capacity_kwh` raises.
- **Heating rod:** the rule names gas, oil and pellets. Wood scores like pellets, district heat like gas; beside an electric direct heating or a heat pump a rod scores 0 (maintainer's decision 2026-11-08, kept in version 3). PV does not reduce the rod points any more. The heat source comes from the heating system the live scenario uses (`heating_system_ids` variant, else the house's reference system). An unknown source type raises.
- **Number of EVs is not rated**; only wallboxes are: the distinct wallboxes the profile's EVs use (`components.wallboxes[]`, data model 6): the fixed wallbox of an EV, every allowed wallbox of a dynamic EV. An EV without a valid `wallbox_assignment` raises. A wallbox shared by several cars counts once.
- **Manual consumers are never counted.** For `generic` consumers only the role `flex` is eligible (`manual` and `known` are not controlled by Earnie). `thermal_annual`, `thermal_rc` and `ev` consumers are always controlled by Earnie.
- **Air conditioner:** the `cooling` block of the house's `thermal_annual` consumer, counted only with the profile switch `cooling_enabled` („Kühlung betrachten“). `type: split` (a device of its own) counts 1 point in `heat` regardless of power; `type: heat_pump` (the reversible heat pump) counts 1 point only when the heating consumer is not counted (switch „Heizung betrachten“ off), so one device never counts twice.
- **No double counting:** each consumer contributes to one part (`wallbox`, `heat` / `heating_rod`, or `other`). Powerstation-attached consumers are ordinary consumers of the profile and are counted once there.
- **One plant = one location = one ping.** No cross-location sums.
- Invalid or missing numeric fields raise `ValueError` naming the component; there are no silent defaults.

### Version 2 (2026-11-08 until 2026-11-13, `-dev` builds only)

`storage`: up to 1 kWh per kWp of PV 1 point per 5 kWh, above 1 point per 2.5 kWh. `wallbox`: 2 per wallbox, +4 once with less than 1 kWh of storage; bidirectional: the storage points the car battery (a quarter) adds on top of the stationary storage, at least 1 per bidirectional wallbox. `heating_rod`: gas / oil / district heat 7, pellets / wood 4, minus `kwp / 5`, at least 0. `pv`, `heat`, `other` as in version 3. Dropped because an upgrade could lower the total: a battery removed the +4, more PV lowered the rod points and moved storage kWh below the kink.

### Version 1 (until 2.8.0-dev.9)

`pv`: 1 up to 6 kWp, then +1 per started 4 kWp. `storage`: 1 up to 5 kWh, then +1 per started 5 kWh. `wallbox`: 1-phase 1, 3-phase 2, bidirectional 3. `heat`: 1 per `thermal_annual` consumer of any heat source, 1 for the air conditioning. `other` as above. No heating-rod part.

## 3. Examples (test fixtures)

| Plant | pv | storage | wallbox | heat | heating_rod | other | total |
|---|---|---|---|---|---|---|---|
| 7 kWp + wallbox, no storage | 1 | 3 | 2 | 0 | 0 | 0 | 6 |
| 10 kWp + 10 kWh + heat pump | 1 | 3 | 0 | 1 | 0 | 0 | 5 |
| 20 kWp + 15 kWh + wallbox + gas boiler with heating rod | 3 | 4 | 2 | 0 | 6 | 0 | 15 |

## 4. Client integration

- `house_config/earnie_points.py`: `compute_earnie_points(components, profile) -> {"total","pv","storage","wallbox","heat","heating_rod","other"}`. Pure, no I/O.
- `runtime_store/usage_points.py`: resolves the **live scenario** (`config.json` `live_scenario_id` → `backtesting_scenarios.json`), selects its PV systems and house batteries (plus all powerstations) from `components.json`, takes its `house_profile_id` profile with the heating systems the scenario picks (`heating_system_ids`), and calls the pure calculation. Components that exist in `components.json` but are not part of the live scenario (e.g. alternatives for the Scenario Explorer) are **not** counted. An id the live scenario references but `components.json` / `house_profiles.json` lacks raises (no fallback to "first profile").
- It recomputes only when the mtime stamp (`config.json`, `backtesting_scenarios.json`, `components.json`, `house_profiles.json`) changed and consent is `on`; the stamp is stored even after an error, so a broken config is evaluated once per change. Stores `points`, `points_v`, `points_stamp` in `runtime/usage_ping.json`.
- Hook: `note_live_cycle_success()` (live stage only, skipped in Shadow mode).
- A configuration or calculation error logs a WARNING and **removes** `points` / `points_v` from the state; the ping stays valid as schema v1 and never affects the cycle.
- A change of the points value (consent `on`) clears the daily send gate so the ping is sent again the same UTC day (like the scenario counter).

## 5. Privacy

The point total is a coarse derived number; it does not contain configuration content. It is part of the "Was wird gesendet?" preview. Schema v2 is covered by the existing opt-in; no re-consent prompt (transparency only: preview, German docs, privacy note).

## 6. Rule changes

A change of the rule bumps `points_v` (the constant in `house_config/earnie_points.py`) and this document. The receiver stores only the totals; histograms recorded under different `points_v` values are not comparable, so a rule change needs a note in the analysis (no client migration).
