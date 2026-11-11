# Savings ledger `savings_v: 2`: implementation plan (Version 2.8)

**Status:** plan, 2026-11-11. No code yet. Decisions D1–D6 (§ 3) taken 2026-11-11 (maintainer) and written into the spec (§ 7, § 9 items 7–12). The four checks of § 2 are done; they raised D7 (no per-consumer power on network backends), decided 2026-11-11: step Ledger P9e for HA is part of 2.8.
**Backlog items (Version 2.8):** **Ledger P9**, **Ledger P10**, **Heating rod in Live: count saved fuel in the savings ledger**.
**Spec:** [`savings-ledger.md`](savings-ledger.md) § 3, § 4, § 7. Related: [`rule-based-reference.md`](rule-based-reference.md) (reference ladder L0–L3 of the Scenario Explorer).

## 1. Goal

The Monitor tile "Mit Earnie gespart" also counts what Earnie saves by moving consumers, and the fuel a heating rod saves. Today (`savings_v: 1`) it counts the battery strategy only: the logged house load already holds the shifted flex energy, and the shadow plant runs on the same load.

`savings_v: 2` changes the load of the shadow plant:

```text
house_without = baseload_actual + Σ flex_retimed          (per slot)
baseload_actual = house_actual − Σ flex_delivered
```

- **Profile and window consumers (P9):** the energy delivered in the SA-day, in the shape the consumer has without control (its profile, or its native window).
- **EV (P10):** the energy delivered in the SA-day, charged at nominal power from plug-in.
- **Heating rod beside a fuel source:** 0 kWh in the shadow plant; the heat it delivered is bought as fuel there (`cost_without += rod_kwh · fuel price`).

All three change the definition "ohne Earnie", so they ship as **one** version bump. `SAVINGS_V` becomes 2 in the last step only (§ 5). A second bump later would restart the chain and the lifetime total once more.

**Why in 2.8:** the ledger ships for the first time with 2.8. If v2 is in that release, no released install ever holds a v1 chain, and no user sees the total restart.

## 2. What the code allows today

Read on `main`, 2026-11-11.

| Fact | Where | Consequence |
|---|---|---|
| The shadow chain steps once per closed slot, O(1), and never looks ahead. | `runtime_store/savings_ledger.py::advance_slot`, `savings_ledger_daemon.py::_on_cycle` | The re-timed shape needs the day's delivered energy, known only at the day close, and may put energy earlier than Earnie did. **v2 cannot be computed slot by slot.** The day is replayed when it closes (§ 4.1). |
| The open day's slot rows hold costs, import and export, `k_act_cent`, `shadow_soc_end`, `house_kwh`, `flex_delivered_kwh` per consumer. | `_slot_row` | A replay also needs `pv_kwh` and `k_push_cent` per slot. Both are known when the slot is booked. |
| A pure builder gives the reference timing of one window: real shape scaled to a target, capped at nominal power, zero outside the eligible slots, with the list of consumers without a shape. | `optimizer/sim_baseline.py::build_shaped_flex_kw_per_slot` (the SE's L1) | Reuse it. The spec names `build_matched_flex_kw_per_hour`; the SE replaced that with this builder (RuleRef). |
| The profile of a flex consumer can be loaded for any list of hours. | `data/profile_manager.py::_load_flexible_consumer_hourly_profiles` | The shape of a closed day comes from the configuration and the date, not from the cycle log. So the backfill CLI can compute it for past days too. |
| Slot 0 of the live matrix carries the meter reading, not the profile (`consumption_mode: live_snapshot`). | `optimizer/sim_baseline.py::_matched_baseline_profile_kw` | The shape must not be taken from the logged matrix row. |
| Without a house battery the ledger is inactive. | `_on_cycle` ("ledger inactive") | With v2 a house without a battery has a saving too (heat pump, EV, rod). The ledger must run without a battery. |
| The MILP already values rod heat with `fuel_credit_cent_per_kwh`; the SE books fuel per day. | `optimizer/milp_horizon_extras.py::_heating_rod_fuel_credit`, `simulation/heat_fuel.py` | One fuel price for plan, SE and ledger. |
| `lifetime_summary` counts rows of the current chain and the current `SAVINGS_V` only. | `savings_ledger.py::lifetime_summary` | After the bump the tile starts at 0 unless the chain is rebuilt from the log (`--rebuild`). |
| The plan's baselines and Chart 1 "SoC BL Ziel" start from the shadow SoC of the open day. | `savings_ledger_daemon.py::planning_shadow_soc` (Ledger P11) | The open day needs a running shadow SoC between two day closes (D2). |

Checked 2026-11-11 (Ledger P9a), by reading the code; no log of an install was read:

1. **Profile for a past day:** `_load_flexible_consumer_hourly_profiles(target_hours)` only reads `flexible_consumer_profiles.csv` and looks up (month, weekday, hour) per consumer of the current configuration; it has no side effects and works for any date. Three things the ledger must handle: the values are **hourly** (the replay repeats them over the four slots); a missing (month, weekday, hour) key takes the mean of that hour, a missing file or column gives zeros, which the builder then treats as "no shape" (nominal power from the first eligible slot); a read error prints a message and returns zeros. The last one is a silent fallback, so the ledger needs a strict read that raises and books the day's consumers as `logged` with the reason.
2. **Windows and plug state:** every log entry holds the cycle's `charging_contexts` (`main.py`, `optimizer/charging_resolve.py::serialize_charging_contexts`), with `plugged_in`, `deadline` and `available_from` per consumer. So the plug state of past days is in the log. The backfill CLI drops it today (`scripts/build_savings_ledger.py::_KEPT_FIELDS`); P10a adds the field there. Windows of the other consumers come from the configuration (`thermal_flex_window`, `generic_flex_window`, the filter's native start and duration); P9b fixes the source per consumer type.
3. **Consumer without its own meter:** `closed_interval.flex_kw` holds measured consumers only (`integrations/loxone_live_power.py::_build_chart_kw`, plus the native filter run that is inferred). A consumer without a meter has **no key**. Detection for D6 is therefore: a flex consumer of the configuration that has no key in any counted slot of the day.
4. **Fuel price:** `house_config/heat_source.py::heating_rod_fuel_credit_cent_per_kwh` = fuel price per kWh ÷ the source's efficiency, per rod kWh. The planning consumer carries it as `fuel_credit_cent_per_kwh` only beside a non-electric heat source (`house_config/planning_flex_converters.py`). The ledger reads that field, so plan and ledger use one value.

**Found in check 3:** on a network backend (HA / evcc, OpenEMS) the power sampler reads no per-consumer power at all (`runtime_store/power_interval_sampler.py`: `flex_kw` stays empty when `is_ehal_network_backend()` and no reader is passed; nothing passes one in production). There every consumer falls under D6, and v2 adds the battery-free houses (D3) but no flex part and no rod fuel. v2 as planned is complete on Loxone only. See D7.

## 3. Decisions (taken 2026-11-11, maintainer: the proposals as written)

| # | Question | Options | Decided |
|---|---|---|---|
| D1 | Which counterfactual for flex? | **(a)** unshifted timing, spec § 7 (the SE's L1). **(b)** standard rules on actuals (the SE's L2: surplus charging, price lock, cheapest hours), so the tile and the study share one reference. | (a) for 2.8. The day replay of § 4.1 takes the timing from one function, so (b) can replace it later. (b) needs per-slot inputs the ledger does not keep yet (published prices at decision time, rule parameters) and costs about two more sessions. Open point: the SE headline is L2 − L3, the tile would be L1-based and reads higher. The method note must say so. |
| D2 | What does the open day show ("Heute bisher", Chart 2 "Bisher", Chart 1 "SoC BL Ziel")? | **(a)** as today: shadow on the logged timing, battery only, replaced by the replay at the day close. **(b)** provisional re-timing with the plan's day targets. | (a). "Heute bisher" already reads as provisional. The text says that moved consumers are added when the day closes. At sunrise both chains usually sit at min SoC, so the line rarely jumps; the replay's end SoC is the chain value from then on. |
| D3 | Houses without a battery | ledger active with a shadow plant without battery (`grid = load − pv`, no SoC correction), or still inactive | active. |
| D4 | Show the flex part apart from the battery part? | **(a)** one figure. **(b)** the row also stores the day's saving with the logged timing from the same start SoC, and the tile help names "davon durch verschobene Verbraucher". | (b) in the row (one more replay per day, cheap), (a) on the tile at first. The split is approximate, because the two runs end at different SoC. |
| D5 | EV session across the SA-day boundary | re-time per SA-day (energy delivered on day N+1 starts at the day start if the car was already plugged in), or per session with a carry across days | per SA-day. Keeps the day's energy equal on both sides and understates slightly. |
| D6 | Consumer without its own meter | keeps its logged timing and is named in the row, or re-timed from the plan | logged timing, recorded per consumer (`flex_timing: "logged_no_meter"`). No estimate from setpoints. |
| D7 | Network backends log no per-consumer power (§ 2, check 3; found 2026-11-11). | **(a)** ship v2 as planned; on HA and OpenEMS the tile stays battery only. **(b)** step **Ledger P9e** before P9d: the slot log gets per-consumer power on HA (§ 3.1). | (b) for HA, decided 2026-11-11 (maintainer). OpenEMS wallboxes are not part of 2.8; there the tile stays battery only and the help says so. |

### 3.1 D7: scope and estimate of Ledger P9e (2026-11-11, from the code)

What exists on HA:

- The push contract already carries every bound `sens_*` field of a consumer: `integrations/ha_push_read.py::binding_entries` lists all consumer `ehal_bindings`, and `ehal/loxone_push_source.py::is_pushable_kind` accepts `sens_*`. So `flex.<id>.sens_power_act` and `flex.<id>.sens_consumer_active` arrive in the push inbox once the user has bound them.
- `read_push_ehal_value` reads such a value in EHAL units with the sign rule; `integrations/ha_units.py` knows `flex.sens_power_act` as a power.

What is missing is the read into the log: `main.py` sets the per-consumer power to 0 for every consumer on a network backend, and the sampler leaves `flex_kw` empty. Both date from the first OpenEMS adapter (2.4.b, `ef2c75c8`) and are a placeholder; no rule or doc was found that excludes consumer power on purpose.

**Ledger P9e — per-consumer power in the slot log on HA** (1 session):

- A reader for network backends that returns measured consumers only: `sens_power_act` when bound, else `sens_consumer_active` × nominal power for binary consumers, the wallbox's `sens_evcs_active_power` for an EV. A value that is missing or stale gives no key, never 0 (D6 then applies to that consumer and day).
- Wired into the sampler (`read_flex_chart`), so `closed_interval.flex_kw` holds slot means as on Loxone.
- Scope limit: the log and Chart 1 "Ist" per consumer only. `main.py` also feeds live consumer power into the planning matrix (baseload split of slot 0) and into the delivery check; switching those on for HA changes planning and is not part of this step. It needs its own item and a HouseSim run.
- Tests: reader with bound, unbound and stale values; a slot mean in `closed_interval.flex_kw`; HA contract testbed check case with one consumer power entity.

*Implemented 2026-11-11 (Ledger P9e):* `integrations/ha_flex_power.py::read_ha_flex_chart_kw` (pure, injected inbox read and sign) and `read_ha_flex_chart_kw_live`; `power_interval_sampler._read_live_sample` calls it when `is_ha_backend()` (OpenEMS still logs no consumer power). Decisions taken in the step:

- **What counts as measured:** inbox state `OK` or an explicitly pushed 0 (`0 (gehalten)`), for the digital run state also the held edge (`Digital (gehalten)`). The inbox's assumed zeros (`0 angenommen …`), `Zuletzt bekannt`, `0 (gehalten, Verbindung unbekannt)` and read errors give no key. When the HA link is down the plant read fails too and no sample is taken.
- **Run state × nominal power** only for consumers without power setpoint (`uses_power_setpoint` false); for a modulating consumer the run state says nothing about its power.
- **One push signal for two consumers** (one wallbox for two EVs): both get no key and a warning, since the power cannot be attributed.
- **No clamping:** the value is used with the sign rule as pushed (a negative consumer power would show a wrong binding instead of being hidden).
- **Slot mean:** a sample without the consumer's key counts as 0 in the slot mean (`_mean_flex`), as on Loxone; only the samples matter, a consumer that never reports in a day stays without key (D6). Changing the mean for both backends is a separate decision.
- **Testbed check:** `scripts/ha_testbed_check.py::check_consumer_power_sampled` takes the first consumer power read of the archetype (`sens_power_act` / `sens_evcs_active_power`) and waits until the newest power sample holds its pushed value; SKIP without such an entity or without samples (daemon not sampling).

**OpenEMS** (half a session, not in 2.8): the adapter reads the power per charger component already (`_evcs_power_w`) and sums it to `sens_evcs_active_power`; per-charger values can go into `flex_kw`. Other consumers have no channel binding on OpenEMS, so there is nothing to read for them.

Not estimated, because it depends on the installs and not on the code: how many HA houses have a power entity bound per consumer. Without the binding P9e changes nothing for that consumer.

The plan grows from 7 to 8 sessions. P9e is independent of P9b and P9c and can run at any point before P9d.

## 4. Design

### 4.1 Day replay

When the first slot after SA₂ closes the day (`advance` → `close_day`), v2 computes the day from the slot rows the state holds:

1. `flex_delivered_kwh[cid]` = Σ over the counted slots.
2. Reference timing per consumer over the **counted slots only**, scaled to that energy (`build_shaped_flex_kw_per_slot`; targets = delivered energy, shapes = profile, eligible = counted slots inside the consumer's window). A skipped slot stays zero on both sides, as in v1, so the day's energy is equal on both sides whatever the coverage.
3. `house_without` per slot, then `vendor_mode_step` over the day from the chain's SoC at the day start. Costs with the slot's own prices.
4. The row, the slot file record and the new chain SoC come from this replay. The SoC correction of § 3 of the spec is unchanged and uses the replay's end SoC.

**Open questions of P9b and how P9c handled them (2026-11-11).** All four are implemented (item 1 decided by the maintainer on 2026-11-11: the window from the log):

1. **Native filter window from the log.** Every cycle logs `filter_contexts` (`native_start_hour`, `native_duration_hours`, `source_label`; `main.py`), the schedule the device runs without Earnie. The daemon stores it in the slot row (as P10a does with `plugged_in`), the backfill CLI keeps `filter_contexts` in `_KEPT_FIELDS`; per day the window of the first counted slot applies. A day without a logged window takes the configured `config_fallback`, recorded in the row (`native_window_source: "log" | "config"`). If that is too much for P9c: the configured value for 2.8 and a sentence in the method note. *P9c: done. Slot rows carry `filter_native` per consumer (the entry's `filter_contexts`, only complete windows), the row records `flex_native_window_source` per filter consumer.*
2. **Open day without `pv_kwh` / `k_push_cent`: no special path.** With `SAVINGS_V = 2` (P9d) the store drops a v1 state and starts a new chain (`savings_v_changed`, `savings_ledger_store.py`), so no v1 day is ever replayed as v2, and the replay does not run in production before P9d. The replay reads the fields strictly (`KeyError`); a test pins that a v1 state starts a new chain after the bump. *P9c: done; the existing test `test_savings_ledger_day.py` pins the new chain.*
3. **Unreadable profile file.** `retime_flex_day` takes `profiles_kw=None` as "not readable": the no-meter, EV and no-energy rules stay, every other consumer keeps its logged timing with reason `profile_read_error`, and a warning names the file. Not the windows instead (silent fallback) and not a raise in the day close (it would close the day twice). The day counts the battery part only, as in v1, and the row says why. *P9c: done.*
4. **Time zone.** *P9c: done, with one change:* not `close_day` but the provider takes the time zone (`savings_ledger_store.flex_day_inputs(state, consumers, timezone_name, profile_path)`, required); daemon and CLI pass `config.get_planning_timezone()`, so `close_day` stays pure. DST fall-back: the repeated hour 02 gets the same hourly profile value on its eight slots (same lookup as the planning read), energy parity holds; spring-forward: 92 slots. One test each.

Side note: windows across midnight end at midnight in the ledger as in the MILP, so reference and plan share their windows. Whether that MILP behaviour is intended is a separate backlog question.

**Day replay (Ledger P9c, `runtime_store/savings_ledger.py`).**

- `close_open_day(state, battery_params, app_version, dt_h, day_flex)` closes the open day: v1 with `close_day` on the causal slots as before; v2 by `retime_flex_day`, then `replay_day` from `shadow_soc_day_start` with the re-timed flex, then `close_day` on the replayed slot rows, so the row uses the same formulas as v1. A second `replay_day` on the logged timing gives `saving_logged_timing_eur` (D4); it equals the causal day to the bit, because the causal step and the replay share `_shadow_step`.
- `advance_with_slots` returns the state and a `DayClose` (`row`, `closing`, `chain_soc`); `closing` is the replayed state in v2, so `day_slots_record(closing)` adds up to the row. `advance` keeps its return value for the chart and the plan's shadow SoC. Daemon and CLI use `advance_with_slots`.
- `day_flex` is a callable from the state to `FlexDayInputs` (consumers, profiles or `None`, windows). Daemon and CLI pass `savings_ledger_store.flex_day_provider(timezone_name)`: the consumers Earnie controls (`get_flexible_consumers(optimizer_only=True)`), the profile file, local wall-clock times. It is called once per closed v2 day and never in v1. A v2 close without it raises.
- State: `shadow_soc_day_start` (written and required for `savings_v >= 2` only, so v1 state files are unchanged); after a v2 close both `shadow_soc` and `shadow_soc_day_start` are the replay's end SoC.
- No battery (D3): `start_chain(..., savings_v=2, with_battery=False)`, `shadow_soc` `None`, `grid = load − pv`; the row has `p_ref_basis: "no_battery"`, both corrections 0 and `soc_shadow_end_pct` / `p_ref_cent` `None`. v1 refuses a chain or a day without battery.
- New row fields (v2): `flex_retimed_kwh`, `flex_timing`, `flex_logged_reasons`, `flex_native_window_source`, `saving_logged_timing_eur`, `fuel_saved_kwh`, `fuel_saved_eur` (heating rod step).
- Left for P9d (done there): the daemon stopped without a house battery (`ledger inactive`), the CLI refused without one, and Chart 1's shadow SoC series read `float(shadow_soc_end)`, which is `None` without battery.

The causal step per cycle stays for the open day (D2). Its SoC is kept apart from the chain SoC at the day start (`shadow_soc_day_start` in the state), so the replay does not depend on it.

A consumer whose energy cannot be placed (no shape and no window, or more energy than its eligible slots hold at nominal power) keeps its logged timing for that day and is named in the row. This is a recorded rule per consumer and day, not a silent fallback. The builder raises in the second case; the ledger checks the capacity before it calls the builder (same 1 Wh tolerance), so a raise from the builder stays a bug.

**Timing function (Ledger P9b, `runtime_store/savings_ledger_flex.py`).** `retime_flex_day(slot_rows, consumers, profiles_kw, windows, dt_h)` is pure and returns `flex_retimed` kW per slot row, `flex_timing` per consumer, the reason for each `logged` consumer and the delivered kWh. Rules per configured consumer, in this order:

| Case | `flex_timing` | Reference |
|---|---|---|
| no `flex_delivered_kwh` key in any counted slot of the day (D6) | `logged_no_meter` | logged (zero) |
| ≤ 1 Wh delivered | `no_energy` | logged |
| EV with plug state in every slot it charged in | `plug_in` | the day's energy at nominal power from the first plugged-in slot, over the slots it was plugged in or charged in (§ 4.3, P10a) |
| EV that charged in a slot without plug state | `logged_no_plug_state` | logged |
| heating rod beside a fuel source (`parent_heat_electric` false) with `fuel_credit_cent_per_kwh` | `fuel` | 0 kWh; its delivered kWh bought as fuel in the slot it ran in (§ 4.4) |
| same, without a fuel price (no `fuel_credit_cent_per_kwh`) | `logged`, reason `no_fuel_price` | logged |
| profile with energy in the counted slots of the enable window | `profile` | profile shape over the enable window (whole day without one) |
| filter with a counted slot in its native window | `native_window` | flat over the native window; the whole day is eligible, so energy beyond the native run continues right after it (capped at nominal power) |
| enable window with a counted slot | `enable_window` | flat over the enable window |
| none of the above | `logged`, reason `no_shape_no_window` | logged |
| more energy than the eligible counted slots hold at nominal power | `logged`, reason `exceeds_eligible_slots` | logged |
| key in `flex_delivered_kwh` but not configured | `logged`, reason `not_configured` | logged |

A heating rod beside an electric heat source is an ordinary consumer (rows below). The rod rule above came with the heating rod step (§ 4.4); a rod without its own meter is `logged_no_meter` like any consumer.

**Window source per consumer type** (`consumer_windows(consumer, slot_starts_local)`, decided in P9b). All windows come from the planning consumer of the current configuration, like the profile, so the backfill CLI can compute them for past days. They use the MILP's own slot rules (hour of the slot's local wall-clock time):

| Consumer type | Enable window (bounds the reference, flat shape without profile) | Native window (flat shape without profile, does not bound) |
|---|---|---|
| thermal (`daily_target_source: thermal_annual`) and heating rod (`heating_rod`) | `thermal_flex_window` (`consumer_thermal_eligible_indices`); none configured → whole day, no flat fallback | — |
| any consumer with `generic_flex_window` (planning generic consumers) | `generic_flex_window` (`consumer_generic_eligible_indices`) | — |
| filter (`filter_schedule.enabled`) | — | the window the cycles used (`filter_contexts` of the log, carried as `filter_native` in the slot rows; first counted slot of the day), else `filter_schedule.config_fallback.native_start_hour` / `native_duration_hours` (`slot_in_native_window`); the row names the source (`flex_native_window_source`: `log` / `config`); neither → no native window |
| thermal RC (`thermal`), EV, others | — | — |

Two consequences of using the MILP's rules: a `thermal_flex_window` or `generic_flex_window` that crosses midnight ends at midnight (`generic_allowed_slot_hours` keeps the run in the calendar day), as in the plan; and the filter's native window comes from the log where it was logged (decided 2026-11-11, implemented in P9c).

Profiles: `data/profile_manager.py::load_flexible_consumer_slot_profiles_strict(slot_datetimes, consumers, profile_path=...)` looks up (month, weekday, hour) of each slot's naive local time, so the hourly value is repeated over the four slots of the hour; a missing key takes the mean of that hour over the file, as the planning read does. A missing file or column means no profile. A file that cannot be read, lacks the key columns, repeats a key row, holds an empty or non-numeric value, or has no row for an hour raises `FlexProfileReadError`; P9c books the day's consumers as `logged` with that reason.

### 4.2 Data format

Slot row in the state, new: `pv_kwh`, `k_push_cent` (P9b: `pv_kwh` 0.0 and `k_push_cent` `None` in a skipped or error slot, like `house_kwh` and `k_act_cent`), later `plugged_in` per EV (P10). A state written before P9b loads unchanged; its open day has no `pv_kwh` / `k_push_cent`, so the replay of that one day must handle it (P9c).

Ledger row, new:

```json
{
  "savings_v": 2,
  "flex_retimed_kwh": {"waermepumpe": 3.86, "pool_swimspa": 0.7},
  "flex_timing": {"waermepumpe": "profile", "pool_swimspa": "native_window", "wallbox": "plug_in", "trockner": "logged_no_meter"},
  "saving_logged_timing_eur": 0.33,
  "fuel_saved_kwh": 2.1,
  "fuel_saved_eur": 0.25
}
```

`cost_without_eur` holds electricity and fuel of the shadow plant; `fuel_saved_eur` names the fuel part. Slot file: `cost_without_eur` per slot from the replay, fuel in the slot the rod ran in, so the slots still add up to the row (`check_day_slots`). A state file of v1 starts a new chain (`savings_v_changed`), as the store already does.

### 4.3 EV (P10)

The reference charges the energy delivered in the SA-day at nominal power from the first plugged-in slot of the day (D5). The daemon stores `plugged_in` per EV in the slot row, from the cycle's charging context. A day without that field for a slot the car charged in keeps the logged timing for the EV (`flex_timing: "logged_no_plug_state"`).

*Implemented 2026-11-11 (Ledger P10a):* `pending_slot_from_entry` keeps the boolean `plugged_in` of each consumer in the entry's `charging_contexts`; `LedgerInput.plugged_in` carries it, counted slot rows store it as `plugged_in`; the backfill CLI keeps `charging_contexts`. In `retime_flex_day` an EV (`type: ev` or an enabled `charging_schedule`) is eligible in the counted slots where it was plugged in **or** charged: the plug state is read when the cycle starts, so a car plugged in during a slot reads `False` there although it charged. The reference puts the energy at nominal power from the first eligible slot and carries it forward over eligible slots only, so a car that left and came back is not charged while away. Energy above what the eligible slots hold at nominal power keeps the logged timing (`exceeds_eligible_slots`). Logs from before the plug state was logged give `logged_no_plug_state` for every EV day (risk § 7: backfill).

### 4.4 Heating rod

Rule in the timing function: a consumer with `daily_target_source: heating_rod` beside a fuel source gets 0 kWh in the shadow plant; `fuel_saved_kwh` = delivered rod kWh ÷ the source's efficiency, priced like the MILP's fuel credit. Beside an electric heat source the rod is an ordinary consumer. A rod without its own meter: D6.

*Implemented 2026-11-11 (heating rod step):* `retime_flex_day` reads the planning consumer's `parent_heat_electric`, `parent_heat_efficiency` and `fuel_credit_cent_per_kwh` (the field the MILP's `_heating_rod_fuel_credit` uses, `heating_rod_fuel_credit_cent_per_kwh` = fuel €/kWh ÷ efficiency). Per slot the shadow plant buys rod kWh · credit as fuel (`FlexRetiming.fuel_eur_per_slot`); `replay_day` adds it to that slot's `cost_without_eur`, so the slot file still adds up to the row. Row: `fuel_saved_kwh` (Σ rod kWh ÷ efficiency), `fuel_saved_eur` (the fuel part of `cost_without_eur`). A rod beside a fuel source without a fuel price has no credit in the MILP either; the ledger keeps its logged timing (`no_fuel_price`) instead of buying fuel at 0 €. The logged-timing replay of D4 has no fuel rule, so the rod's saving counts in the flex part.

### 4.5 UI and docs

- Tile help and method note (German): "ohne Earnie" = gleiche PV, gleicher Tagesverbrauch je Gerät zur gewohnten Zeit, Auto lädt ab dem Einstecken, Heizstab aus und Wärme aus dem Brennstoff, Batterie im Herstellermodus, gleiche Preise.
- The chain switch is visible: the tile's start date, and a one-time note after the update.
- "Heute bisher": text per D2.
- Chart 2 account view and Chart 1 "SoC BL Ziel": check that closed days read the replay and the open day the running chain; no new drawing.
- `docs/ui/charts.md`, user manual, spec § 3 / § 4 / § 7, release note draft for 2.8.

*Implemented 2026-11-11 (Ledger P9d):*

- `SAVINGS_V = 2`. A v1 state file starts a new chain (`savings_v_changed`), as designed; `lifetime_summary` counts v2 rows only.
- No house battery (D3): the daemon books with `battery_params=None` and `start_chain(..., with_battery=False)`; the backfill CLI runs too; Chart 2 builds its figures without battery and Chart 1's shadow SoC series skips `None`. The tile's "ruht" notice is gone.
- Tile (`ui/ledger_kpi.py`): the method note of v2 (equal day energy per consumer at the usual time, EV from plug-in, rod off beside fuel, battery in vendor mode, "Heute bisher" provisional, the Scenario Explorer compares stricter with L2), the consumers of the newest closed day without their own meter (`logged_no_meter`, by configured name), a line for OpenEMS (battery only), "Heute bisher (vorläufig)", and a chain-switch note during the first 7 closed days of a chain that started with `savings_v_changed`.
- User docs: `docs/ui/charts.md` (Chart 2, tile), user manual (Monitor), `docs/einrichtung/betrieb.md` (ledger file), `docs/konfiguration/flexible-verbraucher.md` (heating rod beside fuel).
- Release note fragment: `.github/release-notes/drafts/v2.8.0-ledger-v2.draft.md` (draft; two sentences of `UNRELEASED.md` are now outdated, marked there for review).
- Tests that exercised v1 mechanics now run v2 with a `day_flex` without consumers (`tests/ledger_flex_helpers.py::no_flex`), which equals the causal day; state fixtures carry `shadow_soc_day_start`. Expected values are unchanged except the "Heute bisher" wording and the no-battery behaviour.
- Backfill dry-run and hand check done 2026-11-11 on a copy of the productive log; results in the backlog item **Ledger P9**. Findings: heat pump and swimspa have no profile energy and no window from 2026-11-01 (`no_shape_no_window` on 10 days each), so they keep their logged timing there; `kochen` and `tv` are metered but not configured as flex consumers (`not_configured`). Open: the live check on the maintainer's install (tracker row).

## 5. Steps

One chat session each; branch `feat/ledger-v2`, merged after the last step. `SAVINGS_V` stays 1 until P9d.

| Step | Content | Done when |
|---|---|---|
| **Ledger P9a** | Decisions D1–D6 (done 2026-11-11, spec § 7 and § 9 items 7–12). Checks of § 2 done 2026-11-11. Checks and D7 done 2026-11-11. Spec § 3 and § 4 got the v2 table and row fields with P9c (2026-11-11). | Done. |
| **Ledger P9b** (done 2026-11-11) | Timing function, pure: day slot rows + consumers → `flex_retimed` per slot and `flex_timing` per consumer (profile, native window, flat over the enable window). Slot rows carry `pv_kwh` and `k_push_cent`. | Tests: energy parity per day and consumer with full and partial coverage; cap at nominal power; consumer without shape; consumer that cannot be placed is recorded. |
| **Ledger P9c** (done 2026-11-11) | Day replay in `close_day`, state with `shadow_soc_day_start`, shadow plant without battery (D3), row and slot file from the replay, `saving_logged_timing_eur` (D4). Backfill CLI uses the same replay. Still behind `SAVINGS_V = 1` in production (the replay is called with an explicit version in tests). | Tests: synthetic 2-day log where a consumer is moved from an expensive to a cheap slot gives the hand-computed saving; a day without flex equals the v1 row to the cent; slots add up to the row; no battery → row without SoC correction. |
| **Heating rod** (backlog item, done 2026-11-11) | Rod rule and fuel in the replay (§ 4.4). | Tests: rod beside gas → `fuel_saved_eur` and rod electricity only on the "with" side; rod beside an electric source unchanged; price equals the MILP credit. |
| **Ledger P10a** (done 2026-11-11) | `plugged_in` in the slot row; EV rule (§ 4.3, D5). | Tests: car plugged in at 18:00, charged 02:00–05:00 → reference charges from 18:00; session across SA; day without plug state is recorded. |
| **Ledger P10b** (done 2026-11-11) | Consumers without their own meter (D6): detected, logged timing, named in the row and in the tile help. *Done: detection and logged timing came with P9b (`logged_no_meter` in `flex_timing`); P10b added the end-to-end tests (`tests/test_savings_ledger_no_meter.py`). The tile help moved to P9d: it describes v1 until `SAVINGS_V` is 2.* | Tests: such a consumer changes nothing against v1 and appears in `flex_timing`. |
| **Ledger P9e** (done 2026-11-11) | Per-consumer power in the slot log on HA (§ 3.1): reader for measured consumers, wired into the sampler; log and Chart 1 "Ist" only, planning unchanged. | Tests: bound, unbound and stale values; slot mean in `closed_interval.flex_kw`; HA testbed check case with one consumer power entity. |
| **Ledger P9d** (done 2026-11-11 except the live check) | `SAVINGS_V = 2`; tile, method note, chain-switch note, user docs, release note draft (§ 4.5). The tile help names consumers without their own meter (`flex_timing: logged_no_meter`, from P10b). Daemon and CLI run without a house battery (D3), and Chart 1's shadow SoC handles `None` (from P9c). Backfill `--rebuild --dry-run` on the maintainer's log; one day checked by hand against the log. | UI tests for tile and help; the hand check is written into the backlog item; live check on the maintainer's install is a tracker row. |

Order: P9a → P9b → P9c, then Heating rod, P10a and P10b in any order, P9e at any point, P9d last. Estimate: 8 sessions (the backlog said 1 each for P9 and P10; the day replay was not in that estimate).

## 6. Not in this plan

- Standard rules (L2) as the live reference (D1 option b).
- Per-charger power on OpenEMS (§ 3.1), and live consumer power in the planning matrix and the delivery check on network backends.
- **Ledger P12** (settlement points) and the usage-ping figure ("Simple Savings KPI"); both read the row and work with v2 unchanged.
- **Battery efficiency calibration from the log**: same shadow battery, own item.
- Thermal effects of moving a heat pump (another COP at another hour): the reference keeps the day's electrical energy, as the SE does.

## 7. Risks

- **The reference shape is a profile, not what the user would have done that day.** A consumer the user starts by hand at varying times gets a saving or a loss from the difference between profile and habit. Mitigation: only consumers Earnie controls are re-timed; the method note says "zur gewohnten Zeit".
- **Negative flex saving on single days** (Earnie moved a consumer into PV that then did not come). This is a real result and stays in the figure.
- **Backfill of old days** uses today's profiles and has no plug state. Rows built that way name it in `flex_timing`.
- **Size of P9c.** `close_day` and the state are used by the daemon, the CLI, Chart 1, Chart 2 and the tile. The replay must leave the v1 path byte-identical until P9d (test: v1 rows of the existing fixtures unchanged).
