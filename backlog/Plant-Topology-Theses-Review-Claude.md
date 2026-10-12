# Review — Plant topology and metering theses

**Reviewed document:** [`Plant-Topology-Theses.md`](Plant-Topology-Theses.md) (draft, 2026-10-12)
**Reviewer:** Claude Opus 5.5 (`claude-opus-5-5`, Anthropic), run in Claude Code against this repository
**Date:** 2026-10-12
**Status:** Review only. Nothing here is decided or implemented.

---

## 0. Scope and method

- Read the theses paper, the linked documents ([`docs/spec/ehal.md`](../docs/spec/ehal.md), [`docs/spec/conversion-losses.md`](../docs/spec/conversion-losses.md), [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md)) and the code the paper cites, plus the MILP battery-control and live-load paths it depends on.
- Same evidence tags as the paper: **[code]** = verified in this repository (file:line), **[inference]** = reasoning by the reviewer.
- **Not re-checked:** vendor and forum sources in §5 of the paper (Victron, Huawei, SMA, VBEW). Counter-examples below are installation *types*, not documented real cases.

## 1. Summary

The core idea holds: a tree instead of a mesh, one root as the balancing node, sub-meters for attribution only. Three problems need fixing before the theses can be decided:

1. **T5 conflates Earnie's `control` flag with device self-regulation.** `read_only` means "Earnie does not write", not "the device does not regulate". The rule neither prevents the oscillation it is meant to prevent nor allows a harmless case it rejects (§4.1).
2. **§8 "no change to the optimiser" is wrong** for cases (b) and (d): the MILP would plan an uncontrolled battery as if it were coordinated (§4.2).
3. **The live load balance cannot represent case (b) today:** it takes one plant PV value and one battery power. Unread foreign generation silently becomes "negative load", which the `max(0, …)` clamp hides (§4.3).

---

## 2. Facts about the current code (paper §1)

| Paper claim | Verdict | Evidence / correction |
|---|---|---|
| `inverters[]` fields; η_inv mandatory | correct | [code] `house_config/inverter.py:163` rejects a missing `efficiency`. Minor inconsistency: [`pv_attribution.py:17-19`](../integrations/pv_attribution.py) silently falls back to 0.97 when `efficiency` is missing (no-fallback rule). |
| Battery on `pv_string` not rejected | correct | [code] [`inverter.py:281`](../house_config/inverter.py) only rejects PV on `battery`. Addition: the MILP then treats that inverter like a hybrid without notice ([`milp_inverter.py:287`](../optimizer/milp_inverter.py)). |
| MILP clips `pv + discharge <= max_ac` | imprecise | [code] PV is not a decision variable in this clip. It is the forecast after η and clip, `pv_ac = min(pv·η, max_ac)`, then `discharge <= max_ac − pv_ac` ([`milp_inverter.py:136`](../optimizer/milp_inverter.py)). Consequence [inference]: for a hybrid with DC/AC ratio > 1, PV above `max_ac` is lost in the model, although a real hybrid would store it on the DC side. Storage gain is under-estimated for oversized arrays. |
| Island inverters contribute nothing | correct | [code] PV excluded (`house_balance_pv_kw`), batteries filtered (`filter_house_balance_batteries`). |
| Grid meter only as plant bindings; `GRID_METER_ID = "meter"` | correct | [code] [`ehal/qualified_ids.py:30`](../ehal/qualified_ids.py). |
| `P_cons = max(0, P_PV + P_grid + P_ess)` | correct | [code] [`ehal_live.py:147-148`](../integrations/ehal_live.py). Addition: a missing `sens_ess_power` silently becomes 0. |
| `grid.meter` in ~99 places / 31 files | correct | [code] `git grep`: 96 matches in 31 tracked files. |
| `earnie_data_model = 4` | correct | [code] [`runtime_store/data_model.py:7`](../runtime_store/data_model.py). |

**Missing implicit assumption.** Besides "exactly one meter", today's code also assumes **exactly one battery power in the load balance** and a **complete plant PV value**:

- [code] Loxone live power reads the primary battery only ([`loxone_live_power.py:514`](../integrations/loxone_live_power.py), `resolve_primary_ess_binding`).
- [code] Load derive reads a single `sens_ess_power` ([`ehal_live.py:147`](../integrations/ehal_live.py)).
- [code] A mapped plant `sens_pv_production_active` is taken as authoritative; per-inverter coverage is only checked when plant PV is *derived* ([`pv_attribution.py`](../integrations/pv_attribution.py), `with_attributed_plant_pv`).

---

## 3. Physics

### 3.1 Correct

- The worked example in paper §2.4 is correct, as is `L_total = L1 + L2 + Rest`.
- Residual = parent − Σ children is correct, given a consistent sign (child flow `+` = into the child).
- [inference] Nested regulators do not couple: an inner regulator on a sub-meter is unaffected by the outer one, because the outer one's actions do not change the flow through the sub-meter. This supports T4. Same-node regulators do couple (paper §2.3).

### 3.2 DC and AC quantities are mixed in the balance

[code] Derived plant PV is `Σ PV_DC · η_inv` ([`pv_attribution.py`](../integrations/pv_attribution.py), `derive_plant_pv_ac_w`). [inference] On a hybrid, `sens_ess_power` is often the DC battery power (e.g. the Huawei battery register cited in `ehal.md`). The true AC output of the hybrid is `η·(PV_DC + P_bat_DC)`. The derived load is then off by `P_bat_DC · (1 − η)`, about 3 % of battery power, systematically (lower while charging, higher while discharging). PV that flows on the DC side straight into the battery also pays η_inv, which it physically does not.

`conversion-losses.md` already lists the DC shortcut as out of scope, so this is acceptable for v1. The paper should state it under Q7, because the problem is DC/AC mixing, not sub-meters.

**Proposal:** measure the generator side of the balance on the AC side with the existing `inv.{id}.sens_inv_power_ac`: `P_load = P_grid + Σ P_inv_ac`. No η, no DC values in the balance. PV/battery split stays per device for the MILP.

### 3.3 Three ports are not enough (T1)

- Case (b) needs several generator ports at one node.
- T4 introduces bidirectional Abgänge, which are neither Last nor Generator.
- If an Abgang with PV is folded into Last, `P_last` can become negative. [code] The `max(0, …)` clamp hides that silently.

**Proposal:** a node = one Netz port + a list of branches (load, cluster, sub-node), with KCL Σ = 0. No separate storage port is needed for the balance (Q1).

### 3.4 Wiring is not irrelevant for everything (T8)

T8 holds for the node balance (KCL). It does not hold for:

- **Double-conversion / all-in-one off-grid hybrids**, where the load is supplied through the inverter. The load path then pays η_inv. [code] `conversion-losses.md` assumes grid↔load is lossless.
- **Pass-through limits** when grid charging and AC-out loads share the same transfer relay. This limits what the MILP may plan, so it is more than a plausibility check (also T7).
- **Where the regulator measures** (e.g. Victron internal AC-in measurement vs. external grid meter). This decides which flows a regulator reacts to and is needed for the T5 replacement (§4.1).

### 3.5 Billing metering is not a separate concern for a cost optimiser

Paper §5 infers that billing metering concepts and control meters are separate concerns. For Earnie, whose objective is cost, this does not hold:

- [inference] A heat-pump tariff with its own utility meter (parallel or cascaded) or §14a EnWG module 2 gives **different prices per energy flow**.
- A parallel-metered heat pump physically cannot be supplied by PV.
- T2 ("one root = house connection") breaks when two billing meters exist.

[code] No representation of separate tariff meters was found in the code. **Minimum:** detect and reject (or warn), and state this explicitly as a non-goal with a reason instead of leaving it out.

---

## 4. Controllability and optimisation

### 4.1 T5 conflates `control` with self-regulation (main issue)

- A foreign battery in self-consumption mode with `control: read_only` **still regulates** on the same grid value. Case (b) with a battery therefore keeps oscillating, although T5 accepts it.
- Conversely, case (c) is rejected unnecessarily. Two Earnie-controlled clusters at one node are harmless if Earnie leaves at most one of them in Automatik and drives the other with fixed `set_ess_active_power`. A fixed setpoint is open-loop and closes no control loop. Users already do this with staggered setpoints (paper §5, Victron row).
- T5 only looks at generators. Controllable loads that regulate on surplus at the same meter (e.g. a wallbox charger in PV-surplus mode, heating-rod controllers regulating to zero export) are the same kind of regulator.

**Proposed rule:** record per device whether it runs its own closed loop and on which meter (`regulates_on: <meter_id> | none`). Validation: at most one *active* closed loop per measurement node at any time. Earnie enforces this through mode choice (Automatik for at most one regulator per node), not through a static `control` flag.

Counter-examples to T5 as written [inference]:
- *Hybrid A + AC-coupled battery B (different vendors), B in its own self-consumption mode, configured `read_only`:* accepted by T5, oscillates in reality.
- *Same plant, B driven by Earnie with fixed setpoints, A in Automatik:* rejected by T5 (two controllable clusters), works in reality.

### 4.2 §8 "MILP unaffected" does not hold

- **Case (b) with a `read_only` battery:** [code] the self-consumption coupling is disabled as soon as more than one ESS exists ([`milp_horizon.py:411`](../optimizer/milp_horizon.py)). The MILP then plans the uncontrolled battery freely within its envelope, as if Earnie coordinated it. The plan cannot be executed.
- **Case (d) with an autonomous battery in a sub-network:** the battery regulates on the sub-meter. [code] The `limits_only` / `read_only` envelope uses whole-house PV and load (`p_charge <= p_pv`, `p_discharge <= p_con + p_flex`, [`milp_horizon.py:530-531`](../optimizer/milp_horizon.py)). That is wrong once the sub-network has its own generation or load split.

The sub-meter scope therefore matters to the MILP whenever a battery behind it regulates itself. Either the MILP gets per-node coupling for self-regulating batteries, or such configurations are rejected until it does.

### 4.3 Case (b) needs "read per device", which the code does not enforce

T6 is right that foreign generators must be read. [code] Today a mapped plant PV is used without checking that it covers all inverters, and only one battery power enters the balance (§2). Vendor B's PV or battery then shows up as negative load and the clamp hides it.

**Needed validation:** the generator side of a node must cover every device in its scope (via per-inverter AC power or complete PV/ESS maps), otherwise fail loud.

---

## 5. Verdict per thesis

| Thesis | Verdict | Reason |
|---|---|---|
| T1 Node model | agree with changes | n branches instead of three ports (§3.3); measure the generator side on AC (§3.2) |
| T2 One balancing node | agree with changes | breaks with a separate heat-pump / §14a billing meter: detect and reject (§3.5) |
| T3 Meaning of `grid.meter` | agree | — |
| T4 Tree, not mesh | agree with changes | an Abgang is not controllable by the parent's regulator but may be controllable by Earnie; consumers need a scope too (`consumers[].meter_id`), otherwise per-sub-network residuals cannot be attributed |
| T5 One controllable cluster per node | **disagree** (as written) | rule must be about who regulates on which meter, not about `control` (§4.1) |
| T6 Read per device, control per system | agree | needs the coverage validation in §4.3 |
| T7 No critical/non-critical split | agree | pass-through limit for grid charging is better as an MILP constraint than a plausibility check |
| T8 Wiring not modelled | agree with changes | balance yes; regulator measuring point and double-conversion topologies no (§3.4) |
| T9 Schema changes | agree with changes | see below |
| T10 Migration and rollout | agree | — |

**T9 details:**

- `set_grid_export_power_limit` / `get_grid_export_power_limit` do not belong to a meter (a meter cannot limit). They belong to the plant or to the regulating cluster that enforces them. Only the `sens_grid_*` kinds move to the root meter.
- The sub-meter namespace `meter.<id>.*` contradicts [`ehal.md:44`](../docs/spec/ehal.md) ("more `grid.<Kennung>.*` meters may follow") and the comment at [`qualified_ids.py:30`](../ehal/qualified_ids.py). This can be a deliberate change, but the paper should name it as one.
- Field kinds would then read `meter.<id>.sens_grid_*`, which is misleading for a sub-meter. The namespace `meter` also clashes visually with the Kennung `meter` in `grid.meter`.
- Replace the validation "at most one non-`read_only` cluster per meter" with the regulator rule from §4.1.
- `meters[]` must stay optional: backtesting scenarios share `components.json` and have no meters (Q10).

---

## 6. Answers to the open questions

- **Q1:** No fourth port type is needed for the balance. Branches must be n-ary (§3.3). The MILP needs the PV/battery split per device, not per port.
- **Q2:** Too strict and too lax at the same time (§4.1).
- **Q3:** Refuse by default. An explicitly confirmed and visibly labelled approximation is compatible with the no-silent-fallback rule because it is not silent.
- **Q4:** Sign `+` = into the sub-network is consistent with the house-load convention. Fine.
- **Q5:** From the root's view an island/standby powerstation is a one-way load (≥ 0) on the root node. Its island net lies outside the tree. The current model can stay.
- **Q6:** Root kWh counters are valid for cost accounting only if the root is effectively the billing meter. With a separate heat-pump / §14a meter they are not (§3.5). Sub-meter counters: attribution only.
- **Q7:** Summing over all inverters below the root stays correct with sub-meters. The actual error source is DC/AC mixing (§3.2).
- **Q8:** An optional `update_interval_s` (or staleness bound) per meter is enough. It affects slot actuals and foreign regulators more than 15-minute planning.
- **Q9:** Acceptable for Germany, where utility meters net all phases.
- **Q10:** `components.json` fits; inverters already carry `ehal_bindings` there. Keep `meters[]` optional for scenarios.

---

## 7. Suggested next steps

1. Rewrite T5 around `regulates_on` and "at most one active closed loop per node" (§4.1).
2. Drop the "no MILP change" non-goal, or restrict accepted topologies to those the MILP models correctly (no self-regulating battery besides the controlled one; none behind a sub-meter) until per-node coupling exists (§4.2).
3. Add the coverage validation for the generator side of the root node and remove the silent `sens_ess_power → 0` / `max(0, …)` masking on the changed path (§4.3).
4. Decide explicitly how separate billing meters (heat-pump tariff, §14a) are handled: reject, or a scoped tariff per Abgang (§3.5).
5. Decide the sub-meter namespace consciously against the existing `grid.<Kennung>` plan (§5, T9).
