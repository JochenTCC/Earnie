# Rule-based reference — Earnie vs. standard rules (Scenario Explorer)

**Status:** design 2026-11-03, method decisions O1–O5 taken 2026-11-05 (§ 7). L1 and L2 implemented 2026-11-05 (`simulation/reference_ladder.py`) and computed in every SE run; the cost table, invoices, log and CLI summary read them (P3). The end-SoC valuation of § 3.3 and the window charts on L2 are in (P3b), the study export and sensitivity too (P5), the headline and expander as well (P4, `ui/backtesting_ladder.py`). The SE forecast mode is in ([`se-forecast-mode.md`](se-forecast-mode.md)). Backlog: the **RuleRef follow-up** items in `backlog/Backlog.md`.

**Related:** [`savings-ledger.md`](savings-ledger.md) (live counterfactual, `savings_v`), [`../workflow/earnie-points.md`](../workflow/earnie-points.md), `optimizer/sim_baseline.py`, `simulation/reference_costs.py`.

## 1. Problem

The Scenario Explorer (SE) compares every optimized run with a reference "Referenz (…) — ohne Optimierung" (`simulation/reference_costs.py::compute_historical_reference_costs`). That reference is closed-form: `_hour_cost_parts_without_optimization` (`simulation/anchor_step.py`) books `load − PV` per slot. **No battery, no flex control.**

Any real plant with a battery runs at least the inverter's self-consumption mode. So the SE saving credits Earnie with the whole battery benefit, plus everything a free rule (evcc PV charging, SG-Ready lock, "cheapest hours") would get. That makes the reference a straw man:

- Marketing: the "simple rules get you 80 %" (Pareto) argument cannot be answered.
- Upcoming studies (Earnie Points strategy, subscription prices) need the value **Earnie adds on top of what the customer already gets for free**. With today's reference that value is overstated.

The live side is already better: the matched baseline (`optimizer/sim_baseline.py::simulate_matched_baseline_horizon`) and the savings ledger (`savings_v: 1`) run the battery in vendor mode (`optimizer/battery.py::vendor_mode_step`). The SE does not.

## 2. Goal

A reference ladder in the SE. Each step adds one thing; the delta between two steps is attributable to that thing.

| Step | Name (UI, German) | Battery | Flex consumers | Delta belongs to |
|---|---|---|---|---|
| L0 | Ohne Steuerung | none | historical timing | — |
| L1 | Wechselrichter-Eigenverbrauch | `vendor_mode_step` | historical timing | hardware |
| L2 | Standard-Regeln | `vendor_mode_step` | local rules (§ 4) | free rules |
| L3 | Earnie | MILP | MILP | **Earnie** |

- **L2 replaces the current reference as the headline** ("Ersparnis" in the SE = L2 − L3).
- L0 is today's reference and stays as a ladder step (cheap, keeps the old figure comparable).
- KPIs: Earnie value `L2 − L3`; rule share of the total saving `(L0 − L2) / (L0 − L3)`. The second one answers the Pareto argument directly.
- Smaller savings factors are accepted; the goal is a defensible figure, not a large one.

## 3. Fairness requirements (all steps)

1. **Same energy.** Per window and per flex consumer, L1 and L2 deliver exactly the energy that L3 delivers (the same `consumer_daily_targets_kwh` / horizon targets the optimized run uses). Checked by the same `simulation/plausibility.py::validate_window_consumption` as the optimized run; a step that cannot reach its target in the eligible window fails loud with the missing kWh (`no-implicit-fallbacks.mdc`), no silent clipping. **Exception, heating rod:** it has no target, only an upper bound, and the MILP decides how much heat it replaces (`optimizer/targets.py::resolve_heating_rod_horizon_kwh`). In L1 it runs 0 kWh and the parent heat source delivers the heat. In L2 a rod beside a fuel source runs on surplus (§ 4.3); a rod beside an electric heat source stays at 0 kWh, since that configuration is not going to be allowed (O4). So L2 − L3 is overstated only for such a rod. The study export flags scenarios with a rod.
2. **Same windows and constraints.** Same charging windows (`charging_contexts`, `consumer_charging_eligible_indices`), same nominal / min power, `min_on_quarterhours`.
3. **One continuous SoC chain** over the whole SE period, never reset per anchor (lesson D1 in `savings-ledger.md`). End-of-period SoC difference to L3 is valued like the ledger's SoC correction: `(soc_L3 − soc_step) / 100 · capacity · efficiency · p_ref`, with `p_ref` L3's import-weighted buy price of the period's last 24 h (time mean on a day without import, recorded as `p_ref_basis`). All steps start at the same SoC, so there is no start term, and the ledger's telescoping sum reduces to this one term. The SoC is the one at the period's end, not at the run's end: books spill past it. The log keeps it per scenario for L1 and L2 (`ladder_soc_correction`). The cost column `Ersparnis vs. Standard-Regeln` and the CLI's rule share include it, `Jahres Kosten` and invoices stay the booked cost. L0 has no storage and no term.
4. **Same prices and fees.** End-customer price per slot incl. time-variable grid fee, same feed-in settings (`_reference_feed_in_settings`).
5. **Information parity.** Rules see measured values in real time (surplus at the meter) and the day-ahead prices once published — that is what real products see. Earnie in the SE plans with perfect foresight of PV, load and prices (O1, § 7), so L2 − L3 from a plain SE run is an **upper bound**. Studies report it as a range together with the **SE forecast mode** ([`se-forecast-mode.md`](se-forecast-mode.md), required before final study prices); the ladder itself does not depend on that mode.
6. **Rule parameters fixed up front**, plus a sensitivity run (§ 4.5) that reports the best parameter set in hindsight. Being generous to the rules is the point.

## 4. L2 rule set

Each rule is local: it knows its own consumer, the meter, and the price. It knows nothing about other consumers' plans or the battery SoC. Every rule is named after the product behaviour it imitates, so the reference is "evcc + SG-Ready + HA cheapest hours", not an invented strategy.

### 4.1 Mechanism: deferral queue on top of the matched profile

Starting point per consumer is the L1 profile (`optimizer/sim_baseline.py::build_shaped_flex_kw_per_slot`: real shape scaled to the target, zero outside the eligible window). It replaces `build_matched_flex_kw_per_hour` in the SE: SE matrices carry no `expected_flex_kw`, so that function spreads every target flat over the eligible slots, and it reads the live scenario's consumers (O4):

- **Shape source:** consumers of the scenario's house profile: `data/consumption_profiles.py::modeled_consumer_kw_for_slots`, the source of the L0 load. Others, and `logged_day` runs: the consumer's `cons_data` column. Scaled to the target and capped at `nominal_power_kw`; energy cut by the cap moves to the next eligible slots with headroom, then to earlier ones at the end of the window.
- **Target > 0 but no shape in the eligible window:** nominal power from the start of the eligible window until the target is reached ("switch on and run"), counted per consumer in the step's meta and in the run's result. Not spread flat.
- **Targets and windows:** the MILP's own preparation (`_prepare_horizon_state`: fixed load credited, charging limits) and its eligibility (`consumer_delivery_eligible_indices`, plus the thermal window).
- **Limit:** `min_power_kw` and `min_on_quarterhours` are not enforced on the scaled replay; a scaled shape can run below minimum power. § 3.2 holds for windows and nominal power.

Rules only **move** energy; a per-consumer budget keeps the total exact. Slots are processed in time order:

- `planned[t]` = matched profile value; `backlog` = energy deferred so far; `remaining` = target − delivered.
- Block → the slot's planned energy goes to `backlog`.
- Allowed → deliver `min(nominal, planned[t] + backlog)`; surplus pull may add more from `remaining` (§ 4.3).
- Deadline forcing (§ 4.4) overrides the block.

If no rule fires, L2 equals L1 slot for slot. Every L1 → L2 difference can therefore be traced to a rule. An EV is the exception: its wait rule (§ 4.3) always applies, so it departs from L1 by design.

Within a slot, all consumers first take their planned energy and the deadline's need; the surplus rule then runs in consumer order and each consumer sees what the ones before it took. Two consumers never claim the same surplus.

**Rule per consumer type (O4):**

| Consumer | Rules |
|---|---|
| `ev` | Waits for PV surplus (§ 4.3), deadline (§ 4.4). No price lock, no V2G discharge. |
| `thermal_annual`, `thermal_rc` | Price lock (§ 4.2), surplus boost (§ 4.3), deadline (§ 4.4). |
| `generic` with `generic_flex_window` | Cheapest block (§ 4.5). |
| Other flexible `generic` (also a consumer without a type) | Price lock (§ 4.2), deadline (§ 4.4). |
| Fixed load (`continuous_load`, native filter run) | No rule: already booked as fixed load. A filter's remaining target outside its native run counts as other flexible `generic`. |
| Heating rod (`daily_target_source: heating_rod`) | L1: 0 kWh. L2 beside a fuel source: surplus at the meter (§ 4.3), no price lock, no deadline. L2 beside an electric heat source: 0 kWh (§ 3.1). |

### 4.2 Price lock — "SG-Ready lock / EVU-Sperre"

Blocked when the slot's end-customer price (incl. grid fee and VAT, `k_act` on actual prices) is **strictly above** the P75 quantile of the prices available at that slot. "Available" means from the slot to the end of the last published day-ahead day (`data/backtesting_prices.py::last_day_ahead_calendar_date`), recomputed per slot. So the rule never uses an unpublished price, and a flat tariff never locks. Deferred energy is caught up in the next allowed slots. Thermal comfort is not modelled (same limitation as the matched baseline today).

The available horizon reaches past the book's end (SA₂), so the rule builder needs the price series up to that day, not just the window matrix. A gap in that range fails loud; `epex_prices_for_slots` would fill it with the previous price, so the runner checks the market data first. The SE loads market prices up to the day after the period.

**End of the market data (decided 2026-11-05, P3):** a run may end before the next day's prices exist: up to today before publication, or at the end of a price CSV. Only there the horizon ends at the last price, as an explicit rule, and the run reports the affected slots (`truncated_lock_slots`, column `Hinweis`). It affects at most the last afternoon. A gap inside the data, or data ending inside the book, still raises. This narrows O3's "missing price fails loud".

### 4.3 PV surplus charging (EV, heat pump and pool boost) — "evcc mode PV / SG-Ready state 3"

The consumer sees the local surplus `pv − baseload − Σ other flex in this slot` (before the battery: the consumer has priority, a common evcc setup). Battery first runs in the sensitivity (§ 4.7): there the consumer sees only what would be exported at the meter after `vendor_mode_step`. It charges when surplus ≥ `min_power_kw` with hysteresis via `min_on_quarterhours`, at most `nominal_power_kw`, from `remaining`. Without a configured minimum, an EV starts on any surplus and other consumers need their nominal power (they run on / off). The surplus rule works in locked slots too. While a started run is held, it draws at least its minimum power, from the grid if needed. Energy pulled forward this way comes from the backlog first, then from later planned slots (from the back of the profile), so the total stays exact.

An EV does not charge its L1 profile when it is plugged in: all its planned energy waits for the surplus, and only the deadline (§ 4.4) charges from the grid. This is what a surplus wallbox with a target time does. Charging at plug-in would leave the midday surplus unused and credit Earnie with a shift any such wallbox achieves. For a commuter car that plugs in during the evening, the wait moves charging into the night before departure, which can cost more than charging at plug-in on a flat tariff.

**Heating rod beside a fuel source — "surplus rod controller":** it sees what would go to the grid after all other consumers and the battery, also in the battery-first sensitivity, since such a controller measures export at the meter. So it changes neither the others nor the battery. It runs on / off at nominal power like in the MILP, when the export covers that power and the day's heat allows the whole slot. The cap is the MILP's own (`optimizer/thermal_flex_context.py::_rod_daily_heat_caps`, η = 1); the window too. It runs before L2's curtailment (§ 4.6), so it uses export that would cost money. No price lock and no deadline: it has no target. Its kWh appear in the rod's column, and `simulation/heat_fuel.py` takes the heat off the fuel (rod kWh / efficiency). The rule has no price check, like a simple controller, even when the export pays more than the fuel saved.

### 4.4 Deadline forcing — "evcc Min+PV / target charge"

If `remaining > (eligible slots after this one) × nominal × dt`, the consumer runs regardless of price lock or surplus, with exactly the power the later slots cannot deliver (at most nominal). A slot that planned more keeps its plan, which is why forcing alone never changes the L1 profile. This guarantees the target where the window allows it; if even that fails, the window is infeasible and the run fails loud (§ 3.1). The first forced slot can run below `min_power_kw` (limit in § 4.1).

### 4.5 Generic flex with a start window — "HA cheapest hours"

Consumers with `generic_flex_window` start their historical cycle (same duration and energy) in the cheapest contiguous block inside the window, by end-customer day-ahead price weighted with the cycle's power. Only prices published when the window opens count; slots without a published price are not candidates. No PV term.

- **Cycle:** the L1 profile from its first to its last running slot.
- **Window:** each contiguous run of eligible slots opens on its own.
- **Tie:** the real start stays, so a flat tariff changes nothing.
- **No start with all prices published:** the real timing stays and the consumer is reported in `no_published_block_ids`.

### 4.6 Battery

Unchanged `vendor_mode_step` on what remains after the flex consumers in that slot. No grid charging, no price logic: this is the inverter's own behaviour.

**Curtailment (O6):** while the slot's feed-in price is negative, L2 limits export at the meter to zero and the rest of the PV is curtailed, like the MILP's export cap and like a zero-export setting a home automation can switch on the published price. The battery still charges first. L1 does not curtail: it is the inverter alone, without any price logic.

### 4.7 Parameters and sensitivity

Defaults: quantile 0.75, consumer before battery, hysteresis from `min_on_quarterhours`. Sensitivity run: quantile ∈ {0.50, 0.66, 0.75, 0.90} × surplus priority ∈ {consumer first, battery first}, 8 runs per scenario; the report shows the default and the best set in hindsight ("Regeln, im Nachhinein bestens parametriert").

## 5. Implementation sketch

- **Rule builder** `optimizer/sim_baseline.py::build_rule_based_flex_kw_per_hour(matrix, targets_kwh, eligible_by_consumer, consumers, shapes_kw, price_series, rule_params, *, book_indices, battery_params, initial_soc)`: per-slot output like `build_shaped_flex_kw_per_slot`. It takes the eligible slots instead of charging contexts because the runner resolves them with the MILP's own eligibility. `shapes_kw` and `price_series` per § 4.1 and § 4.2; battery and start SoC serve the battery-first sensitivity. `rule_params` holds `lock_quantile` and `surplus_priority` (`DEFAULT_RULE_PARAMS`). Per-slot simulation reuses `_simulate_single_hour_baseline(flex_kw_override=…)`. The runner entry is `compute_l2_reference_costs`.
- **SE reference runner**: L1 and L2 are not closed-form any more. They use the same per-window matrices as the optimized run (`build_historical_window_matrix` / `build_sunrise_window_matrix`) and carry the SoC across anchors. Those matrices split baseload from flex but hold only per-consumer targets, no per-consumer series, so the runner adds the shapes (§ 4.1). L1 and L2 always book actual prices. L0 stays closed-form.
- **Reference sharing**: today references are shared across scenarios by `reference_fingerprint` (Historisch = assets stripped). L1/L2 depend on the house, the battery and the flex consumers, so they share by `simulation/reference_ladder.py::ladder_reference_fingerprint`, which adds those to the L0 key. `reference_fingerprint` stays as it is: L0 ignores them, and SE reference columns must not change before P3.
- **Output**: per-slot frame with the same columns as today (`_REFERENCE_COST_COLUMNS`) per ladder step, plus SoC for L1/L2, so existing charts and the SE invoice keep working. Result ids are `l1:<scenario>` and `l2:<scenario>`, with the scenario that first has the setup as owner. `reference_by_scenario` stays L0 (consumption comparison, slot coverage); `ladder_by_scenario` and `ladder_report` in the log hold the steps and what each run reports. The cost table's `Δ vs Referenz` stays as the comparison across scenarios against the Live L0; the saving is the new column `Ersparnis vs. Standard-Regeln`.
- **Window view** (P3b, `ui/backtesting_standard_rules.py`): with a ladder in the log, the SE window charts compare with L2 under the label "Standard-Regeln". Chart 2 reads the booked L2 and L3 per slot from the series file, also for SA₀→SA₁, which the previous window booked, so its saving is the L2 − L3 of its slots. Chart 1 shows the window's plan as before, with L2's SoC and flex per slot, which the ladder frame now carries in the same columns as an optimized run. Slots outside the period cost 0 € on both sides, have no L2 SoC and are named in the caption. A log without a ladder keeps the recomputed "BL Ziel"; a log with a ladder but without L2's series fails loud. A log from before P3b has no L2 flex columns, so Chart 1 shows no flex outlines for it.
- **Study export** (P5): `python -m scripts.run_reference_ladder --scenario … --workers N --output-dir …` runs a normal SE (`run_backtesting --scenario`, so the log and series file are there too) and writes three CSVs in the format of the series file. No fixed fees. Each step `l0`–`l3` has `l*_eur` (booked electricity), `l*_fuel_eur` (from the log's `heat_fuel` block), `l*_total_eur` (both, without the end-SoC term) and the quantities `l*_import_kwh`, `l*_export_kwh`, `l*_fuel_kwh`, `l*_rod_kwh`, `l*_battery_throughput_kwh` (charged + discharged on the AC side). A log without the block fails loud.
  - `reference_ladder_daily.csv`: the step columns per calendar day and scenario, and `l2_l3_with_fuel_eur` (booked, no end-SoC term). A day missing on one step fails loud, and a log without fuel per day (`heat_fuel.<result>.daily`, written since this column set) needs a new run. Daily fuel is not floored: a rod can store more heat than its day needs, as L3 does on some days, and then the day's fuel is negative, so the days sum to the period's total.
  - `reference_ladder_summary.csv`: totals per scenario, end-SoC terms and SoCs, plausibility of L1 and L2. `saving_l2_l3_eur` and `rule_share` stay electricity only, `saving_l2_l3_with_fuel_eur` and `rule_share_with_fuel` compare electricity plus fuel; both include the end-SoC term. `fuel_carriers` names the fuel. Use the `*_with_fuel_*` columns for a house with a fuel source: its rod shows only as extra electricity in the others.
  - `reference_ladder_sensitivity.csv`: the 8 parameter sets of § 4.7 per scenario, with `is_default` and `is_best_in_hindsight`, plus `l2_fuel_eur`, `saving_l2_l3_with_fuel_eur` and `rule_share_with_fuel`. Best is the lowest L2 cost including fuel and the end-SoC term; the default wins a tie. The default is the SE run's own L2, so a setup needs 7 extra runs; scenarios sharing a setup share them. `--skip-sensitivity` leaves them out.
  - The forecast run adds the range's lower end as `*_forecast` columns, with its own L3 fuel (`se-forecast-mode.md` § 4). L0–L2 must match between the runs in electricity and in fuel.
  - Every row of the daily, summary and sensitivity files states `l3_foresight=perfect`; daily and summary carry `heating_rod` (§ 3.1). `--scenario` only narrows what runs: the reference plan and the Live scenario still see all scenarios, so a chosen scenario's L0 does not change.

## 6. Effect on other features

- **Savings ledger:** `savings_v: 1` equals L1 on live actuals. Ledger P9/P10 (`savings_v: 2`, flex re-timing) could use the L2 rules on actuals, so live figures and study figures share one counterfactual. Separate decision, not part of this epic.
- **Earnie Points:** points are derived from the live scenario's components (`earnie-points.md`), not from savings; existing points do not change. The ladder is input for the Points strategy study.
- **SE figures change.** Savings drop for every scenario with a battery or flex consumers. User docs and release notes must say why (method change, not a regression). Golden-master regression cases that assert SE savings need `--update-golden` with that justification.

## 7. Method decisions (P0, maintainer, 2026-11-05)

Line numbers are as of this date.

### O1 Perfect foresight: yes. A forecast mode is required before final study prices.

The MILP sees the values that get booked:

| Input | What the MILP sees | Evidence |
|---|---|---|
| PV | Archive weather (Open-Meteo) or imported CSV, the series that is booked. `PV-Prognose (kW)` is this actual value. | `simulation/matrix_builder.py:315`, `simulation/historical_cache.py:149`, `simulation/engine.py:432` |
| Load | Baseload and flex targets of the window, i.e. the actual need; the book's values overlay the MILP matrix. `Verbrauch-Prognose (kW)` is this value. | `simulation/matrix_builder.py:478`, `:598-599`, `simulation/engine_scenario.py:177` |
| Prices | Default `perfect`: actual prices over SA₀→SA₂, no publication cutoff. The UI always runs this. | `data/backtesting_prices.py:341-357`, `scripts/run_backtesting.py:219` |

Limits on that foresight: one plan per day with no re-plan as in live, and no view past SA₂ (`simulation/backtesting_horizon.py:158`).

`--price-strategy mirror|forecast` does not fix this:

- It books at the planned price, not the actual one (`optimizer/sim_chart_rows.py:51`, `optimizer/sim_costs.py:82`), while references book actual prices (`simulation/reference_costs.py:153`).
- It plans at SA₀, so nearly the whole book lies past the day-ahead cutoff (`simulation/matrix_builder.py:574`).
- PV and load stay perfect.

The earlier result "forecast vs. mirror ±0.1–0.6 %" therefore says nothing about the foresight effect.

**Decision:** **SE forecast mode** ([`se-forecast-mode.md`](se-forecast-mode.md), implemented 2026-11-05): plan on forecasts, book on actuals. Perfect foresight is the upper bound for L3's value; one plan per day without re-plan is the lower bound. It does not block P1–P5, but final study prices wait for it.

### O2 Surplus priority: consumer before battery, battery first in the sensitivity.

See § 4.3 and § 4.7. The sensitivity grid doubles to 8 runs per scenario. A heating rod is always last, after the battery, in both priorities (maintainer, 2026-11-06).

### O3 Lock basis: available horizon, end-customer price, strictly above P75.

See § 4.2. Calendar day was the alternative. The strict comparison is not a matter of basis: `≥` would lock every slot of a flat tariff.

### O4 Consumer mapping and profiles.

- **Mapping:** table in § 4.1, generous to the rules (surplus boost for thermal consumers).
- **Starting profile:** real timing per consumer, "switch on and run" where there is no shape (§ 4.1). Flat spreading is out: it runs consumers below their minimum power and breaks comparability with L0.
- **Heating rod (2026-11-06):** 0 kWh in L1. In L2 beside a fuel source it runs on the export at the meter (§ 4.3), without price check, lock or deadline. A heat pump with a rod will not be an allowed configuration (checked elsewhere), so L2 has no rule for it and such a rod stays at 0 kWh. The study export keeps its flag (§ 5). Its `*_with_fuel_*` columns count the fuel the rod saves (§ 5).

### O6 Curtailment at a negative feed-in price: L2 yes, L1 no (maintainer, 2026-11-05).

Found in the study's sample runs: on a dynamic export tariff L3 curtailed 353 kWh in one June while L1 and L2 paid to export, which credited the whole effect to Earnie. See § 4.6.

### O5 UI: L2 vs. L3 as the headline, ladder in an expander.

The headline shows the saving L2 − L3 and the rule share; the expander shows L0–L3.

Implemented in `ui/backtesting_ladder.py` (P4): one metric per scenario above the cost table, Live first. It reads the cost table's totals, so fees and fuel are in and the headline equals the column `Ersparnis vs. Standard-Regeln`. The export has no fixed fees and keeps electricity and fuel apart (§ 5), so with different fees on L0 its `rule_share_with_fuel` can differ from the headline's, and with fuel its `rule_share` does.
