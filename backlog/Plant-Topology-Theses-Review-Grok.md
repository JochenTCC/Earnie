# Review — Plant topology and metering theses

**Reviewed document:** [`Plant-Topology-Theses.md`](Plant-Topology-Theses.md) (draft, 2026-10-12)
**Reviewer:** Grok 4.7, run in Cursor against this repository
**Date:** 2026-10-12
**Status:** Review only. Nothing here is decided or implemented.

---

## 0. Scope and method

- Read the theses paper, the linked documents ([`docs/referenz/ehal.md`](../docs/referenz/ehal.md), [`docs/dev/done/conversion-losses.md`](../docs/dev/done/conversion-losses.md), [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md)) and the code the paper cites, plus the MILP balance, inverter clip, live PV attribution, and standby-powerstation paths.
- Same evidence tags as the paper: **[code]** = verified in this repository, **[inference]** = reasoning by the reviewer.
- **Not re-checked:** vendor and forum sources in §5 of the paper (Victron, Huawei, SMA, VBEW). Counter-examples below are installation types, not documented real cases.

## 1. Summary

The core idea holds: one AC balance at the root meter, a tree of sub-meters for attribution, and devices rather than copper as the things Earnie schedules. Three problems need fixing before the theses can be decided:

1. **T5 rejects a plant Earnie already optimizes.** Several grid-tied batteries in one MILP are one scheduler and several actuators. The oscillation in paper §2.3 is two closed-loop grid regulators on the same measurement. Those are different situations (§4.1).
2. **"The optimiser uses the root" / §8 "MILP unaffected" is safe only if every controllable device stays in today's single balance.** A battery behind a sub-meter still changes root import. Dropping it from the schedule leaves it unsteered and makes the root forecast wrong (§4.2).
3. **The worked example and the island claim do not match the formulas.** The same-node table under-counts load; it does not show the nested double-count. Island inverters are omitted from house PV and ESS, but a standby powerstation still changes house load (§2, §3.1, §4.3).

---

## 2. Facts about the current code (paper §1)

| Paper claim | Verdict | Evidence / correction |
|---|---|---|
| `inverters[]`, `batteries[]`, `pv_systems[]`; η_inv mandatory; `type` / `ac_connection` / `control` enums | correct | [code] `house_config/inverter.py` (`normalize_inverter`, missing `efficiency` rejected). Schema: `share/config/components.schema.json`. |
| Every battery and PV system has exactly one `inverter_id` | incomplete | [code] Physical batteries and PV systems require one `inverter_id`. A virtual powerstation must not have one (`house_config/entity_resolution.py`, `is_virtual_powerstation`). |
| Inverter `control` is the controllability flag | incomplete | [code] `batteries[].control` gates ESS setpoints and the MILP envelope (`house_config/battery_control.py`, `optimizer/milp_horizon.py` `_add_control_slot_constraints`). `inverters[].control` gates `set_inv_ac_power_limit` (`optimizer/inv_ac_power_limit.py`, `house_config/control_capability.py`). |
| Battery on a `pv_string` inverter is not rejected | correct | [code] `validate_inverter_topology` rejects PV on `type=battery` only (`house_config/inverter.py`). Schema text says `pv_string` = "PV only". If a battery is attached anyway, the MILP applies the hybrid/string clip to it (`optimizer/milp_inverter.py`, `_add_one_inverter_slot`). |
| MILP clips `pv + discharge <= max_ac`, plus optional DC cap and grid-charge cap | imprecise | [code] PV is not a decision variable in the clip. `pv_ac = min(P_pv_dc · η_inv, max_ac)`, then `discharge <= max_ac − pv_ac` (`ac_clip_pv_and_max_discharge`). Plant curtailment (`p_pv_curtail`) does not give that headroom back to discharge. Charge is a separate cap: `max_ac` on a `battery` inverter, optional `max_ac_charge_kw` otherwise. |
| Island inverters contribute nothing to the house balance | overstated | [code] Grid-tied PV only (`house_balance_pv_kw`); island batteries dropped (`filter_house_balance_batteries`). A physical powerstation still has an owned island inverter (`house_config/inverter_lifecycle.py`) and `apply_standby_load_relief` removes its attached load from `expected_p_act` in battery-fed slots (`optimizer/powerstation_standby.py`). |
| Grid meter is plant bindings, wire id `grid.meter.<kind>`, `GRID_METER_ID = "meter"` | correct | [code] `ehal/qualified_ids.py` (`GRID_METER_ID`, `GRID_KINDS`, `qualified_grid_id`). Bindings: `share/config/house_profiles.schema.json` `plant.ehal_bindings`. |
| `P_cons = max(0, P_PV + P_grid + P_ess)` | correct | [code] `integrations/ehal_live.py` `derive_sens_power_consumers_w`. Signs match `docs/referenz/ehal.md`. A missing `sens_ess_power` is treated as 0. The `max(0, …)` clamp means a negative balance cannot show up as house load. |
| Plant AC PV = Σ grid-tied inverter PV · η_inv; island excluded; partial map fails | correct, with a unit condition | [code] `integrations/pv_attribution.py` `derive_plant_pv_ac_w`. [code] `sens_inv_power_pv` and `pv.{id}.sens_pv_production_active` are DC input (`share/ehal/roles/inverter.json`, `share/ehal/roles/pv.json`). Multiplying an already-AC reading by η_inv would apply the loss twice. |
| `grid.meter` in ~99 places / 31 files | about right | [code] Workspace search is on that order, including Loxone Virtual-Out/In templates. The exact count depends on whether the theses and this review folder are included. |
| `earnie_data_model = 4`; one-shot migration and fail-fast loaders exist | correct | [code] `runtime_store/data_model.py` `CURRENT_DATA_MODEL = 4`. `scripts/migrate_inverters_once.py` stays on 4 and detects the old shape. |
| Configuration is unpublished, so the model can still change | not a code fact | The repository shows that shape changes already ship as a one-shot migration plus a fail-fast loader while the version stays 4. It does not show that the config is unpublished. |

**Implicit assumption today.** One exchanged grid meter, and every grid-tied inverter in one house balance. Island PV and island ESS are outside that balance. There is no `meter_id` on an inverter.

The live identity and the MILP identity are the same node, written differently. [code] `optimizer/milp_horizon.py`:

```text
p_pv + p_grid_buy + p_discharge
  = p_con + p_flex + p_grid_sell + p_charge + p_pv_curtail
```

`p_pv` here is already AC: DC forecast times η_inv, then clipped (`house_balance_pv_kw`). Battery SoC uses `batteries[].efficiency` on the AC charge/discharge powers. η_inv is not applied again on the battery path.

---

## 3. Physics

### 3.1 The single-node identity is right; the worked example is not

With EHAL signs, `P_last = P_netz + P_PV + P_bat` is the spec identity `P_cons = P_PV + P_Grid + P_Bat` (`docs/referenz/ehal.md`, losses ignored because the terms are AC-side). T1 matches that if `P_gen = P_PV + P_bat` and charge is negative generation.

A fourth storage port does not change Kirchhoff at the AC node. Storage is a state on the generator side (Q1).

The §2 table and the nested algebra are two different errors, and the table does not illustrate double-counting.

| Situation in the paper | What the numbers say |
|---|---|
| Same node: common grid reading −1 kW, each vendor adds only its own PV (3 kW and 2 kW) | Load is under-counted: 2 kW and 1 kW instead of 4 kW. Adding those two results gives 3 kW. That is neither the true load nor a double count. |
| "Utility meter alone → house load −1 kW" | That cell is the meter reading. The derive formula also needs PV. Current code would clamp a negative result to 0, so −1 kW cannot appear as `sens_power_consumers`. |
| Nested: `L1 = M1 + P1`, `Rest = Z0 − M1 − M2`, `L_total = L1 + L2 + Rest` | The algebra closes and equals `Z0 + P1 + P2`. Summing `L_total` with `L1` and `L2` double-counts. |

`P1` and `P2` have to be signed AC injection, including battery charge. As PV-only powers the nested balance is short one term. `M1` has to be power into the child. On that same wire the parent sees the opposite sign. "Signs per EHAL" is the right local rule (positive = flow in from upstream) when each meter is oriented at its own node. Adding the raw numbers as if both were utility-import mixes the two directions.

Residual = parent − Σ children is the right attribution identity with that orientation (T4, Q4).

### 3.2 η_inv belongs on DC PV, not on an arbitrary inverter power

[code] Plant derive does `Σ (sens_inv_power_pv · η_inv)` for grid-tied inverters with PV. The role text calls that field PV input power. The sum stays valid when sub-meters exist, as long as those inverters are grid-tied and the mapped value is DC (Q7). Island PV stays out.

[inference] Mapping a string inverter's AC output onto `sens_inv_power_pv` applies η_inv twice. The paper should state that unit condition under Q7. Sub-meters are not the error source.

[code] `docs/dev/done/conversion-losses.md` leaves the DC-bus shortcut (PV → battery without paying η_inv) out of scope. The MILP therefore prices all PV through the AC path. That is a known planning approximation, not a topology-tree defect.

### 3.3 A series master does not pass all load current

T7 calls a series master a capacity concern because it "passes all load current". [inference] Generation on the load side of the master supplies the load locally. The master carries the residual (grid exchange), not `P_last`. A pass-through check belongs on the master's measured current (input and output ratings separately).

T7 asks for that check. T8 says wiring is not recorded, so the model cannot know there is a series master. Those two theses conflict (§5).

### 3.4 Parallel and series are the same balance and not the same feasible set

T8 holds for the root energy identity: one root meter sees the same import either way. It does not hold for limits:

- The MILP clips each inverter as its own AC port (`pv_ac` then discharge headroom). A series master adds a limit on the residual through that device.
- AC-coupled PV behind a series master is often not setpoint-curtailable. The paper already cites that Victron case. The model cannot warn about it if series versus parallel is not stored.

Scope plus "who controls" is a sound v1 if the independent-port approximation is stated as a limit.

### 3.5 One tariff is part of "one node"

[inference] T2 matches a single connection with one import price and one export price. A second billing meter with its own price (tenant meter, separate heat-pump meter) is a second economic node. No such split exists in the MILP. That can stay a non-goal, but then T2 should say "one tariff boundary", not only "the house connection".

---

## 4. Controllability and optimisation

### 4.1 T5 is about the wrong kind of "control"

[code] Two or more grid-tied batteries share one balance and one objective. The solver refuses to pin each of them to self-consumption against the same grid, because those pins would fight:

```text
# Self-consumption pin is single-ESS only (multi would fight over grid).
apply_self_consumption = len(ess_ids) == 1
```

(`optimizer/milp_horizon.py`, `_add_slot_power_balance_and_soc`). With `control: full`, Earnie assigns charge and discharge. That is one closed loop, not two.

Paper §2.3 and the forum rows describe a different object: two vendor regulators each driving toward zero on the same grid reading. A second meter does not separate them if both loops still close on that reading.

**Proposed rule:** at most one closed-loop grid-power regulator per measurement. Earnie may be that regulator and may command several actuators (`set_ess_active_power`, `set_inv_ac_power_limit`, `set_grid_export_power_limit`), provided those devices are not also running their own grid loop. A device that still runs that loop is `read_only` or has the loop switched off.

Counter-examples to T5 as written [inference]:

- Two hybrids, both in remote/forced mode, both given setpoints by Earnie. Example (c) rejects this. The current MILP accepts it and should.
- Example (b) with the second device in its own zero-export mode, configured `read_only`. T5 accepts it. The device still fights the controlled one. The MILP does not simulate that foreign loop, and with more than one ESS it does not pin self-consumption at all, so the plan treats the foreign battery as free inside its envelope.
- Parent cluster and child cluster, both closing on the root grid reading. "One cluster per node" allows this. They still fight. The key is which measurement the regulator uses, not which `meter_id` was configured.

`inverters[].cluster` as a validation label is fine (T6). It does not route writes. Writes already go per battery, per inverter, and once for the plant export limit.

### 4.2 Sub-meters are attribution; the devices stay in the MILP

T4, example (d), and §8 say the optimiser uses the root and the MILP does not change. That is true when:

- cost and the export cap stay on the root buy/sell pair, and
- every grid-tied PV system and battery remains a term in the existing balance, including devices behind a sub-meter.

[inference] A controllable garage battery changes root import. Removing it from the schedule because "sub is attribution only" leaves it unsteered and the root forecast short. The charitable reading of T4 — sub-meter *series* are attribution, devices stay — is the one that matches §8. The paper should say that in T4 and in example (d).

[code] The `limits_only` / `read_only` envelope compares one battery with whole-house PV and load (`p_charge <= p_pv`, `p_discharge <= p_con + p_flex`). That coupling is house-wide. A battery that self-consumes only inside a sub-network is not what this envelope models. Until a per-node coupling exists, a self-regulating battery behind a sub-meter should be rejected or explicitly marked as outside the forecast, not silently planned as a house battery.

### 4.3 Island is already two mechanisms

[code] `ac_connection: island` removes that inverter's PV and ESS from the house balance. The standby MILP is separate: it may charge from the grid, and when the pack feeds its own loads those loads are subtracted from house `expected_p_act`.

Q5 "unchanged" should mean keeping both mechanisms. It should not mean the powerstation is absent from the house. From the root, a grid-charged island pack is a load. It becomes a sub-meter only if it has its own balance node. The island AC bus itself is outside the tree.

---

## 5. Verdict per thesis

| Thesis | Verdict | Reason |
|---|---|---|
| T1 Node model | agree with changes | Three accounting flows match the AC identity. They are buckets, not copper ports (same stance as T8). No fourth storage port (§3.1). |
| T2 One balancing node | agree with changes | Earnie already optimizes one economic node. "Later optimises" lags the code. Say one tariff boundary (§3.5). The readable meter is the utility connection only by user assertion. |
| T3 Meaning of `grid.meter` | agree | Reserving `grid.meter.*` for the root matches `GRID_METER_ID`. The id does not prove the meter sits at the utility connection. |
| T4 Tree, not mesh | agree with changes | Residual and "do not sum nested loads" are right (§3.1). Sub-meter series are attribution; devices behind them stay in the MILP (§4.2). An Abgang is invisible to the parent's balance and may still be steered by Earnie. |
| T5 One controllable cluster per node | **disagree** (as written) | Rule must be one closed-loop regulator per measurement, not one writable cluster (§4.1). |
| T6 Read per device, control per system | agree with changes | Reads are per device. Control today is per battery, per inverter (`set_inv_ac_power_limit` when `control=full`), and one plant export limit — not only batteries plus system services. `cluster` should not become a second routing key. |
| T7 No critical/non-critical split | agree for grid cost | Total load is what the cost balance needs. The pass-through sentence is physically wrong when generation sits on the load side of the master (§3.3). Backup already has a separate powerstation reserve. |
| T8 Wiring not modelled | agree with changes | True for the root identity. False for the feasible set and for the T7 pass-through check, which needs the series link T8 refuses to store (§3.3, §3.4). |
| T9 Schema changes | agree with changes | see below |
| T10 Migration and rollout | agree with changes | Root-only evaluation matches a first step if devices stay in the current MILP. A migration that stays on data model 4 must detect the old shape; sites already stamped 4 will not run the v3→v4 migrator again. |

**T9 details:**

- `meters[]` beside inverters fits. Inverters already carry `ehal_bindings` in `components.json`. Move the grid keys (`GRID_KINDS`) onto the root meter. Leave plant PV and `sens_power_consumers` on `plant`.
- `meters[]` stays optional. Backtesting scenarios share `components.json` and have no meters (Q10). Requiring a meter before the MILP runs would break those scenarios.
- Sub-meters need a namespace that is not `grid.<id>.*`. `qualified_grid_id(meter_id=...)` already emits `grid.<meter_id>.<kind>`. Using that parameter for a garage meter would contradict T3. The paper's §1 presents that parameter as the extension point; T9 then does not use it. Pick one and say so.
- Replace "at most one non-`read_only` cluster per meter" with the regulator rule in §4.1.
- Consumers stay measurement points. A `consumer.*.sens_power_act` reading is not a balance node.

---

## 6. Answers to the open questions

- **Q1.** No fourth port. Three flows are enough for the AC node. Batteries stay devices with SoC on the generator side.
- **Q2.** Too strict for several Earnie-commanded actuators. Too lax for a second device that still runs its own zero-export loop, including one that was labeled `read_only` (§4.1).
- **Q3.** Refuse when no meter at the house connection is readable. An explicit, labeled approximation (price the topmost readable meter, costs marked as not the utility bill) is compatible with the no-silent-fallback rule because it is not silent. A missing root should fail the load.
- **Q4.** Child positive = flow from parent into child. The parent's Abgang uses that same number as a load. Store one sign and one orientation.
- **Q5.** Keep `ac_connection: island` as "PV and ESS not in the house AC balance", and keep the standby load relief as the house-side correction (§4.3). Do not add the island bus as a sub-meter unless it has its own balance node.
- **Q6.** Money uses the root import/export counters, and only if that root is the billing meter (§3.5). Sub-meter counters are attribution. Adding them into the bill double-counts internal transfer.
- **Q7.** Summing grid-tied DC PV · η_inv under the root stays correct with sub-meters. It is wrong if an AC power is mapped onto `sens_inv_power_pv` (§3.2). Do not add sub-meter house loads on top of that sum.
- **Q8.** Quarter-hour planning can use a slow energy counter. A zero-export loop cannot. Cadence is a later capability warning, not part of the topology.
- **Q9.** Acceptable for quarter-hour energy cost in this planning model. Not acceptable for per-phase export limits or phase overload. That matches the stated non-goals.
- **Q10.** `components.json` is the right home for meter entities. The MILP and backtesting can ignore `meters[]`.

---

## 7. Suggested next steps

1. Rewrite T5 as "one closed-loop grid regulator per measurement", and allow several actuators under that one regulator (§4.1).
2. In T4, example (d), and §8, state that sub-meter series are attribution and that the devices remain in the single MILP (§4.2).
3. Replace the §2 same-node table, or relabel it as under-counting. Keep the nested algebra, with `P` as signed AC injection (§3.1).
4. Correct the island sentence in §1: omitted from house PV and ESS, still visible through standby load relief (§4.3).
5. Decide the sub-meter namespace against `qualified_grid_id(meter_id=...)`, and keep `meters[]` optional (§5, T9).
6. State the T7/T8 limit in one sentence: pass-through and series AC-coupled PV are outside v1 because wiring is not stored (§3.3, §3.4).
