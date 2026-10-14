# Plant topology and metering — conclusion

**Status:** Decided on the §8 questions (2026-10-12); backlog items filed as epic **Topology** P1–P5 ([`Backlog.md`](Backlog.md)); P1 implemented; since 2026-10-14 P2 stays in Version 2.7 and P3–P5 are in Version 2.+1 (§8.7).
**Date:** 2026-10-12
**Inputs:** [`Plant-Topology-Theses.md`](Plant-Topology-Theses.md), [`Plant-Topology-Theses-Review-Claude.md`](Plant-Topology-Theses-Review-Claude.md), [`Plant-Topology-Theses-Review-Grok.md`](Plant-Topology-Theses-Review-Grok.md), [`docs/spec/ehal.md`](../docs/spec/ehal.md), [`docs/spec/conversion-losses.md`](../docs/spec/conversion-losses.md), [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md). Every **[code]** claim below was re-read in this repository (file:line); vendor/forum sources were not re-checked.
**Author:** Claude Fable 5.1 (`claude-fable-5-1`), run in Claude Code against this repository.

---

## 0. Summary

**Question:** Is the current code enough, or what has to change?

1. The theses hold as a **tree with one root = one tariff boundary**, **balance nodes (Bilanzierungspunkte)** below it for attribution only, and devices (not copper) as the things Earnie schedules. Both reviews agree on that core and both reject **T5** as written: the rule has to be about *who closes a control loop on which measurement*, not about Earnie's `control` flag (§1 M6).
2. **The current code is sufficient for topology (a)** — one readable meter at the house connection, one Earnie-controlled battery cluster, plus any number of read-only PV string inverters whose PV is mapped — and for island / standby powerstations (§2).
3. **It is not sufficient** for: a second battery that regulates itself at the same node (b′), several Earnie-commanded battery clusters (c), self-regulating devices behind a sub-node (d′), no readable root meter (e), a second billing meter (f). Today none of these is rejected; (b′)/(c)/(d′) are silently **mis-planned** and (b′)/(c) corrupt the derived house load (§3 G2–G5).
4. One fact neither review states: **Earnie writes ESS setpoints to the primary house battery only.** The mode/target pair is derived from the aggregate plan and written through the primary battery's bindings; secondary house batteries are planned but never commanded (§3 G3). Case (c) is therefore not an acceptance question but a missing write path (pre-existing 2.7.c gap).
5. Five phases in two tiers (§4), all under Version 2.7. Tier 1 (**Topology P1–P2**: small, fail-loud, no MILP change) makes the implicit model explicit and refuses — on the live path — what cannot be planned or executed correctly. Tier 2 (**P3–P5**) extends what Earnie accepts: per-ESS writes, reactive-regulator coupling in the MILP, and explicit **balance nodes** instead of a `meters[]` entity (§1.1). P5 is last: it buys attribution and detection, not control.

---

## 1. Model adopted

The paper's theses, revised by the reviews and the decisions in §8. "Adopted" means: this is the model the code implements and validates against.

**M1 — One balancing node = one tariff boundary** (T2 + T3, revised). Earnie balances and optimises at exactly one node: the **root balance node**, whose upstream connection is measured by the root meter. The user asserts (a) that this meter measures directly downstream of the utility meter and (b) that there is exactly one import price and one export price behind it. Earnie cannot verify either; both are recorded as explicit configuration, not inferred. `grid.meter.*` denotes the root's upstream measurement; wire IDs stay. *(Grok §3.5: "one tariff boundary", Claude §3.5: billing meters.)*

**M2 — A balance node (Bilanzierungspunkt) is one upstream connection plus n branches** (T1, revised). The entity of the model is the **balance node**, not the meter. A node has one upstream connection (Netz) and n further connections — loads (incl. controllable consumers), generator devices (inverters carrying PV and/or ESS) and child nodes (Abgänge). In practice a node has 2–4 connections (§1.1). A meter is a *measurement on a connection*, never an entity of its own. KCL at the node: `P_netz + Σ P_inv_ac = P_last + Σ P_abgang`, all signs "into the house / into the child" positive. No separate storage port: batteries are devices with SoC on the generator side. The three-port picture is the simple case, not the model. *(Claude §3.3, Grok §3.1.)*

**M3 — Scope and control are modelled, copper is not** (T8, revised). The model records which devices lie behind which node and who regulates. Series and parallel wiring are equivalent for the root energy identity. Three known exceptions are **explicit v1 limits** (documented; rejected or warned where detectable, otherwise a stated approximation): double-conversion / off-grid all-in-one hybrids where the load path pays η_inv; pass-through limits of a series master (grid charge and AC-out loads through one transfer relay); AC-coupled PV behind a series master that cannot be curtailed by setpoint. *(Claude §3.4, Grok §3.3–3.4.)*

**M4 — Tree of attribution-only sub-nodes** (T4, revised). Balance nodes below the root cascade (each child's upstream connection attaches to one parent), never in parallel. Sub-nodes serve attribution (per-node residual = upstream − Σ measured device and child connections). **Devices behind a sub-node remain terms in the single root MILP** — a controllable garage battery still changes root import and must stay scheduled. Only a device that *regulates on the sub-node's upstream measurement* needs per-node treatment (M6). Consumers get a node scope (`consumers[].node_id`) for attribution in P5. *(Grok §4.2, Claude T4.)*

**M5 — Read per device, control per actuator** (T6, revised). Earnie reads per inverter / battery where exposed. The generator side of the root node must be **covered completely**: every grid-tied inverter's AC contribution (per-inverter AC power, or PV plus ESS power of every device) enters the balance, or the balance fails loud. Control goes per battery (`set_ess_*`), per inverter (`set_inv_ac_power_limit`) and once per plant (`set_grid_export_power_limit`). No `cluster` routing key; `cluster` is at most an optional validation label. *(Claude §4.3, Grok T6.)*

**M6 — At most one active closed-loop grid regulator per balance node** (replaces T5). A *regulator* is anything that closes a loop on a grid-power measurement: a vendor ESS in self-consumption / zero-export mode, a dynamic feed-in limiter, a PV-surplus wallbox controller, a heating-rod zero-export controller — and Earnie's own battery whenever Earnie releases it into Automatik. Rules:
- Earnie may be the regulator and command **several** actuators with open-loop setpoints (forced power, limits). Several Earnie-commanded batteries are one regulator. *(Grok §4.1; [code] [`milp_horizon.py:410-411`](../optimizer/milp_horizon.py) already refuses to pin two batteries to the same residual.)*
- Each device declares which measurement its **own** controller uses when Earnie does not force it: `regulates_on: grid` (the root meter — the normal case for hybrid and home ESS) | `none` (never regulates on its own, e.g. a pure setpoint follower) | `<node_id>` (a sub-node's meter, P5). `control: read_only` says only that Earnie does not write, **not** that the device does not regulate. *(Claude §4.1.)*
- Per node: at most one loop may be active. Earnie keeps its own `full` batteries out of Automatik when a foreign loop exists (never-Automatik policy, P4) and plans the one foreign loop as **reactive** (greedy residual after Earnie's actuators, P4). Until the MILP can do that, such configurations are **rejected on the live path**, not approximated (§8.2).

**M7 — A second billing meter is a second economic node** (new). A heat-pump tariff meter, tenant meter or §14a-style module with its own price is outside the one-tariff assumption of M1. v1: documented non-goal with reason; rejected where it becomes detectable (a second tariff in config). Later: scoped tariff per child node. *(Claude §3.5, Grok §3.5.)*

**M8 — Island / standby stays as two mechanisms** (Q5). `ac_connection: island` keeps PV and ESS out of the house balance; standby load relief stays the house-side correction; from the root a grid-charged island pack is a one-way load. The island bus is not a balance node unless it has its own upstream measurement and own devices. *(Grok §4.3.)*

**M9 — No readable root meter → refuse** (Q3). An explicitly configured and visibly labelled approximation ("price the upstream connection of the topmost readable node as grid; costs are not the utility bill") is compatible with the no-silent-fallback rule because it is not silent — but it is a later opt-in, not v1.

### 1.1 The balance node (Bilanzierungspunkt) in detail

Decision 2026-10-12 (§8.4): the schema entity is the **balance node** — German *Bilanzierungspunkt*; "balancing point" is the literal alternative, "balance node" was chosen because the reviews already use it and "root node / sub-node" reads naturally. Schema `components.json` → `balance_nodes[]`, references `node_id`, wire namespace `node`. No `meters[]` list. This is M2 made explicit.

**Connections (Anschlüsse).** Every node has exactly one `upstream` connection and n further ones. Connections are **derived from references**, not stored as a list — the same n:1 pattern as `pv_systems[].inverter_id`:

| Connection kind | Declared by | Its measurement |
|---|---|---|
| `upstream` (Netz) | the node itself: `parent` = the node it hangs below, `null` for the root | the node's own `ehal_bindings`: root = the existing `grid.meter.sens_grid_*` keys; sub-node = `node.<id>.sens_node_power_active`, `sens_node_energy_import`, `sens_node_energy_export` |
| `device` (Generator) | `inverters[].node_id` (default: root) | the inverter's existing `inv.{id}.sens_inv_power_ac`, or its PV + ESS readings (M5) |
| `child` (Abgang) | a node whose `parent` is this node | the child's upstream measurement — one wire, read with the opposite orientation (`+` = into the child) |
| `load` (Last) | implicit: the node's residual; measured load branches are consumer measuring points (`consumers[].node_id`, `consumer.*.sens_power_act`) | derived: `P_last = P_upstream + Σ P_device − Σ P_child`; ≈ 0 for a node that only feeds a device |

**Counts.** Typical nodes have 2–4 connections: (a) root = upstream + hybrid + load (3); (b) root = upstream + two devices + load (4); (d) root = upstream + hybrid + child "garage" + load (4) and garage = upstream + hybrid + load (3); a dedicated meter in front of a PV cluster = upstream + device (2, load residual ≈ 0 — a non-zero residual there is a plausibility error). More are allowed; nothing in the model depends on the count.

**Closure rule.** A node's balance closes when its upstream connection and every device and child connection are measured (or derived from complete maps); the load connection is always the residual. A node whose upstream connection is unmeasured cannot be attributed — its devices still count at the parent (they are read per device); the node is then only a label. Exactly one root (`parent: null`); no cycles; every `node_id` and `parent` resolves. Absent `balance_nodes[]` means the implicit single root of today — backtesting scenarios and simple plants never need the list.

**Wire and storage.** Root upstream stays `grid.meter.*` (T3; `grid` = the one connection to the utility). Sub-node upstream uses namespace `node` with its own field kinds `sens_node_*`, so the rule "namespace = field stem" ([`qualified_ids.py`](../ehal/qualified_ids.py) docstring) holds and a garage node never shows a `sens_grid_*` kind (§5 D2). Storage of the root's bindings: today's `plant.ehal_bindings` grid keys; P5 decides whether they move onto the root node entry (one-shot migration, data model stays 4) or the root keeps reading them from `plant` — the wire does not change either way.

**What the MILP sees.** Nothing new: the root balance as today (M4). Sub-nodes are evaluated for attribution rows only; P4's reactive pin can later use a sub-node residual for case (d′).

---

## 2. Which topologies Earnie accepts

`v1` = after Tier 1 of §4 (validations only). `target` = after Tier 2. "today" notes what the unchanged code does. Rejections in `v1` apply to the **live path** (daemon planning cycle, EHAL-Com); Szenarien-Explorer and backtesting execute the plan by construction and are unaffected — except schema-level rejections (j).

| # | Topology | today | v1 | target | Rule |
|---|---|---|---|---|---|
| a | One root; one hybrid cluster (PV + ESS) commanded by Earnie | works | accepted | accepted | — |
| a′ | (a) + further PV string inverters, read-only, no own grid limiter | works if their PV is mapped (plant PV or complete `inv.*`/`pv.*` maps) | accepted; coverage validated | accepted | M5 |
| b | (a) + foreign battery in its **own** self-consumption mode, `read_only` | **mis-planned**: planned free within the `limits_only` envelope (no residual pin in multi-ESS); its power is invisible in the live balance | **rejected** with message (P1) | accepted as **reactive** device (one foreign loop, P4) | M6 |
| c | Two battery clusters, both commanded by Earnie (open-loop) | **half-executed**: MILP plans both, setpoints reach the primary only | rejected (live) until P3 + P4; SE unaffected | accepted | M6 |
| c′ | Two clusters each in their own vendor loop | not detected | rejected | rejected | M6 |
| d | Sub-node (own upstream meter) with PV + battery behind it, battery commanded by Earnie | works (sub-node unknown to code; devices in the root MILP) | accepted; sub-node not evaluated | accepted + attribution (P5) | M4 |
| d′ | Sub-node whose battery regulates on the **sub-node's meter** | mis-planned (house-wide envelope) | rejected | accepted as reactive on the sub-node residual (P4 + P5) | M4 + M6 |
| e | No readable meter at the house connection | not detected (user maps any meter as `grid.meter`) | rejected via the root assertion (P1) | opt-in approximation (M9) | M9 |
| f | Second billing meter / tariff (heat-pump tariff, §14a) | not representable | documented non-goal; rejected when detectable | scoped tariff per child node | M7 |
| g | Island / standby powerstation | works | unchanged | unchanged | M8 |
| h | Series master (Victron-style), loads + AC-coupled PV on AC-out, one root meter, all in scope | works for the energy identity; no pass-through limit | accepted with documented limits; the AC-out PV inverter must be `control: limits_only`/`read_only` when it cannot be curtailed | pass-through limit as MILP constraint | M3 |
| i | Controllable loads with their own surplus loop at the node (PV-surplus wallbox mode, heating-rod zero-export) | not detected | accepted only when Earnie commands them (e.g. `set_evcs_max_current`) or they are the single declared foreign loop | — | M6 |
| j | Battery attached to a `pv_string` inverter | accepted, treated like a hybrid by the clip | rejected (schema; spec says "PV only") | rejected | spec |

Worked example (paper §2.4), corrected per Grok §3.1: the same-node table shows **under-counting** (each vendor adds only its own PV to the common grid reading), not double counting; the nested algebra `L_total = L1 + L2 + Rest` is right when `P1`, `P2` are signed AC injections (incl. battery charge) and child connections are oriented "into the child". Both errors are consequences of M5 (coverage) and M4 (do not sum nested scopes).

---

## 3. Gap analysis — current code vs. the adopted model

| ID | Gap | Evidence | Consequence | Size |
|---|---|---|---|---|
| **G1** | The model is implicit: no root assertion, no tariff-boundary statement, no declaration of foreign regulators, no node scope. `GRID_METER_ID = "meter"` is a constant; `qualified_grid_id(meter_id=…)` exists but is unused for anything else. | [code] [`qualified_ids.py:30-31, 119-122`](../ehal/qualified_ids.py); [`components.schema.json:238-293`](../share/config/components.schema.json) has no `node_id` / `regulates_on` | Cases (b′), (c′), (e), (f) cannot be detected. | schema + validation, small |
| **G2** | Live balance covers one battery and one plant PV. Loxone reads the **primary** ESS power; HA reads one `sens_ess_power` (optional → `0`); derived load is `max(0, PV + grid + ESS)`. A mapped plant PV is taken as authoritative without checking that it covers every grid-tied inverter. | [code] [`loxone_live_power.py:514`](../integrations/loxone_live_power.py), [`ehal_live.py:137-148, 598-606`](../integrations/ehal_live.py), [`ha_adapter.py:361-368`](../integrations/ha_adapter.py), [`pv_attribution.py:300-327`](../integrations/pv_attribution.py) | A second battery's charge/discharge lands in "house load" (history and forecast corrupted); the clamp hides unread generation. | medium |
| **G3** | ESS setpoints go to the **primary** house battery only; mode/target are derived from the aggregate plan (`aggregate_battery_params_for_load` = first ESS + summed powers). Secondary house batteries are planned but never written. Physical powerstations have their own per-ESS write path. | [code] [`main.py:436-449, 493-498, 515-517`](../main.py), [`ehal_live.py:618-712`](../integrations/ehal_live.py) (`control_from_battery_params(config.get_battery_params())`), [`loxone_writes.py:471-473, 515-542`](../integrations/loxone_writes.py), [`ess_bindings.py:37-68`](../house_config/ess_bindings.py); contrast [`powerstation_live.py:617-645`](../optimizer/powerstation_live.py) | Case (c) is impossible today; a secondary `full` battery runs in its vendor default (usually its own loop → a hidden case (b)). | medium (pre-existing 2.7.c follow-up) |
| **G4** | MILP: the self-consumption pin is single-ESS only; in multi-ESS a `read_only` (or Automatik `limits_only`) battery is planned free inside the house-wide envelope `charge ≤ PV`, `discharge ≤ load + flex`. No reactive coupling that includes Earnie's own actuators in the residual; no per-node residual. | [code] [`milp_horizon.py:410-411, 526-531, 548-572`](../optimizer/milp_horizon.py) | (b′)/(d′) produce plans the plant cannot execute (e.g. grid-charging A while B discharges into it). | medium |
| **G5** | `inverters[].control` has **no** MILP effect; it only gates `set_inv_ac_power_limit`. T5's "`read_only` generator" therefore has no code hook; only `batteries[].control` shapes the plan. | [code] [`inv_ac_power_limit.py:22-43`](../optimizer/inv_ac_power_limit.py), [`control_capability.py:58-80`](../house_config/control_capability.py); no `control` read in [`milp_inverter.py`](../optimizer/milp_inverter.py) | Correct for PV-only inverters (they do not regulate); confirms that the regulator attribute must be separate from `control`. | none (fact) |
| **G6** | Silent fallbacks on the touched paths: `_eta_inv` falls back to `0.97` while `inverter_efficiency` raises; `sens_ess_power` missing → `0`; `max(0, …)` clamp on the derived load. | [code] [`pv_attribution.py:16-26`](../integrations/pv_attribution.py) vs [`milp_inverter.py:99-111`](../optimizer/milp_inverter.py); [`ehal_live.py:147`](../integrations/ehal_live.py) | Violates the no-silent-fallback rule exactly where topology errors would surface. | small |
| **G7** | Validation accepts a battery on a `pv_string` inverter; the clip then treats it as a hybrid. | [code] [`inverter.py:280-285`](../house_config/inverter.py), [`milp_inverter.py:287-290`](../optimizer/milp_inverter.py) | Spec/code mismatch. | trivial |
| **G8** | Known approximations, already documented, unchanged by topology: DC/AC mixing in the balance (η on DC PV, DC battery power on a hybrid), PV above `max_ac` lost instead of stored, no pass-through limit, no per-phase metering. | [code] [`conversion-losses.md`](../docs/spec/conversion-losses.md) out-of-scope list; [`milp_inverter.py:119-137`](../optimizer/milp_inverter.py) | Stated limits (M3), not gaps to fix now. | none |

**Verdict on the question:** the code is sufficient for (a), (a′), (d) and (g). For everything else it is not *wrong by design* but **undefended**: it accepts configurations it cannot plan or execute and hides the symptoms (G2, G6). Tier 1 closes that; Tier 2 widens acceptance. One consequence to state plainly: with G3 and G4 open, **no live plant with two grid-tied house batteries is executed as planned today**, so Tier 1 refuses such plants on the live path until P3 + P4 — the Szenarien-Explorer keeps multi-ESS.

---

## 4. Change proposal — epic **Topology**, Version 2.7 (decided)

All Tier 1 fields are additive → `earnie_data_model` stays **4**; where an existing config changes shape (P1 `regulates_on`, possibly P5 bindings), a one-shot migration script plus a fail-fast loader, no dual-read (§8.6). Order: P1 → P2 → P3 → P4 → P5 (§8.1).

### Tier 1 — make the model explicit, fail loud (no MILP change)

**Topology P1 — explicit root, regulator declaration, validation**
- `plant.grid_meter` in `house_profiles.json`: `{ "at_house_connection": true, "single_tariff": true }`. Both must be `true` for the live path; absent or `false` → the daemon refuses to plan, with the M1 wording. This records the user assertion of M1 — no node entity yet.
- `batteries[].regulates_on`: `"grid"` | `"none"`, **required** on house batteries (no silent default). Meaning: which measurement the device's **own** controller uses when Earnie does not force it — `grid` for every hybrid / home ESS with a self-consumption or zero-export mode (the normal case, also for `control: full`), `none` for a pure setpoint follower. Migration `scripts.migrate_topology_once` (data model stays 4) sets `grid` for every house battery and prints the list; the loader rejects the old shape with the migrate hint. Optional `inverters[].regulates_on` (`none` unless set; documented) for PV inverters with their own dynamic feed-in limiter.
- Live-path validation (daemon planning cycle + EHAL-Com; **not** Szenarien-Explorer / backtesting):
  - (i) loops at the root = house batteries with `regulates_on: grid` + inverters with `regulates_on: grid` ≤ 1; otherwise refuse, message names P3/P4;
  - (ii) at most one grid-tied house battery in the live plan until P3 + P4 exist — a second one can neither be commanded (G3) nor modelled as reactive (G4); refuse (§8.2: reject, no warn-and-exclude);
  - (iii) hence a single `read_only` / `limits_only` house battery with `regulates_on: grid` stays accepted as today (single-ESS self-consumption pin).
- Schema validation (everywhere): battery on a `pv_string` inverter → reject (G7).
- Docs: `docs/spec/ehal.md` § Plant topology (M1–M9 condensed + the §2 table); German user docs with the three questions a user must answer: *Sitzt der Zähler direkt am Hausanschluss? Gibt es nur einen Tarif? Regelt ein anderes Gerät selbst auf diesen Zähler?*

**Topology P2 — generator-side coverage in the live balance (G2, G6)**
- Multi-ESS: plant `sens_ess_power` := Σ over grid-tied house batteries of `ess.{id}.sens_ess_power`; a grid-tied house battery without a power binding → fail loud (same pattern as `derive_plant_pv_ac_w`). Single-ESS behaviour unchanged. (Exercised live only once P3 lifts rule (ii); needed before that.)
- Plant PV coverage: when plant PV is mapped **and** more than one grid-tied inverter owns PV, require `inv.*`/`pv.*` coverage or an explicit `plant.pv_covers_all_inverters: true` acknowledgement (user assertion, logged).
- Derived load tolerance, parameterised (§8.3): `plant.balance_tolerance_pct` (default **5**) and `plant.balance_tolerance_w` (default **100**). Raw balance `PV + grid + ESS` below `−max(tolerance_w, tolerance_pct/100 · P_PV)` → telemetry error, not `0`; within tolerance → clamp to 0 (measurement jitter; the absolute floor covers night-time with `P_PV = 0`).
- Remove `sens_ess_power → 0` on plants with ≥ 1 grid-tied house battery (keep it for battery-less plants); `pv_attribution._eta_inv` raises like `inverter_efficiency` (η is mandatory since the conversion-efficiency migration).

### Tier 2 — widen acceptance

**Topology P3 — per-ESS setpoint writes (G3; closes the 2.7.c gap).** Derive mode/target **per house battery** from `milp_plan["ess"]` and write entity-scoped `ess.{id}.set_*` for every mappable grid-tied house battery (template: `write_cycle_powerstation_setpoints`; `write_mapped_fields` exists for HA/OpenEMS, Loxone exchange IDs already exist). Plant-level `set_grid_export_power_limit` unchanged. Lifts rule (ii) for `control: full` secondaries with their own `set_ess_*` bindings — together with P4 (two `full` batteries both released into Automatik would still be two loops).

**Topology P4 — reactive regulator in the MILP (G4).** Generalise `_add_self_consumption_coupling`: residual := `p_pv − p_con − p_flex − Σ_{Earnie-commanded ESS} (p_charge − p_discharge)`; the one battery with `regulates_on: grid` that Earnie does not command is pinned to that residual's split. Never-Automatik policy: when another loop exists at the node, Earnie-commanded batteries get forced power / limits with discharge lock instead of `set_ess_mode = 0`. Rule (i) then counts foreign loops only. Unlocks (b′) and (c); per-node residual for (d′) only together with P5.

**Topology P5 — balance nodes (Bilanzierungspunkte) + attribution (T9/T10, §1.1).** Optional `components.json` → `balance_nodes[]` (`id`, `label`, `parent`, `ehal_bindings`, optional `update_interval_s`), `inverters[].node_id` and `consumers[].node_id` (default root); connections derived (upstream, devices, children, load residual); validation (exactly one root when present, no cycles, references resolve); wire `node.<id>.sens_node_*` for sub-nodes, root stays `grid.meter.*`; `regulates_on` accepts a `node_id`. Code evaluates the root only; per-node residuals as attribution rows on the Live page. One-shot migration if the root's grid bindings move from `plant` onto the root node entry.

**Later / separate items (not phases):** Q3 opt-in approximation (M9); scoped tariffs per child node (M7); pass-through constraint for a declared series master (M3); AC-side coverage via `sens_inv_power_ac` instead of DC·η (G8); curtailment live weights (already in Inverter follow-ups).

---

## 5. Where the reviews disagree — resolution

**D1 — Where do `set/get_grid_export_power_limit` live?** Claude: on the plant / regulating cluster, "a meter cannot limit". Grok: move all `GRID_KINDS` onto the root meter. **Resolution:** both are right at different layers. The export limit is a constraint on the flow through the PCC *node*; the root balance node *is* that node (M1). So the binding may be stored on the root node entry when `balance_nodes[]` exists (Grok), while the semantics stay plant-level: only the root may carry the limit kinds, never a sub-node (Claude). Wire ID `grid.meter.set_grid_export_power_limit` unchanged. Which cluster enforces it is a write-routing fact with exactly one target today. Storage location decided in P5.

**D2 — Sub-meter namespace.** Both ask for a conscious decision against the existing `grid.<Kennung>.*` plan ([`ehal.md:44`](../docs/spec/ehal.md), [`qualified_ids.py:30`](../ehal/qualified_ids.py)). **Decided (§8.4):** the entity is the balance node; `grid` stays PCC-only; sub-nodes get namespace `node` with their **own field kinds** `sens_node_power_active`, `sens_node_energy_import/export` (the rule "namespace = field stem" holds, and a garage node never shows a `sens_grid_*` kind). Supersede the sentence "more `grid.<Kennung>` meters may follow" in `ehal.md` and the comment at `qualified_ids.py:30` when P5 lands.

**D3 — T7 pass-through.** Grok: a series master carries the residual, not the full load (generation on the load side supplies the load locally) — correct physics. Claude: the pass-through limit matters for the MILP (grid charge + AC-out load through one relay) — correct for the feasible set. **Resolution:** v1 does not store the series link (M3), so no check; later an optional `pass_through_max_kw` on an inverter declared as series master becomes an MILP constraint on the grid-side flow through that device.

**D4 — Island.** Grok's correction stands: `island` removes PV and ESS from the house balance, and standby load relief subtracts the islanded attached load from `expected_p_act` ([`powerstation_standby.py:247-265`](../optimizer/powerstation_standby.py)). "Contribute nothing" in paper §1 is overstated.

**D5 — η_inv and the balance.** Claude (DC battery power on a hybrid skews the derived load by ≈ 3 % of battery power; PV→battery on the DC bus should not pay η_inv) and Grok (`sens_inv_power_pv` is DC by role definition; mapping an AC reading applies η twice) are complementary. **Resolution:** keep the v1 approximation as documented in `conversion-losses.md`; state the DC unit condition for `sens_inv_power_pv` under Q7; AC-side coverage via `sens_inv_power_ac` is the clean later option (§4 later items).

---

## 6. Final verdict per thesis

| Thesis | Verdict | Adopted as |
|---|---|---|
| T1 Node model | agree with changes | M2 + §1.1 (balance node with n connections, no storage port) |
| T2 One balancing node | agree with changes | M1 (one tariff boundary; explicit user assertion) + M7 |
| T3 Meaning of `grid.meter` | agree | M1 (root upstream measurement) |
| T4 Tree, not mesh | agree with changes | M4 (devices stay in the root MILP; consumers scoped in P5) |
| T5 One controllable cluster per node | **rejected as written** | M6 (one active closed loop per node; `regulates_on`) |
| T6 Read per device, control per system | agree with changes | M5 (control per actuator; coverage validation; no `cluster` routing) |
| T7 No critical/non-critical split | agree | M3 limit; pass-through later (D3) |
| T8 Wiring not modelled | agree with changes | M3 with three named exceptions |
| T9 Schema changes | agree with changes | P1 (assertions, `regulates_on`) now; `balance_nodes[]` instead of `meters[]` in P5; D1/D2 |
| T10 Migration and rollout | agree | data model 4, one-shot + fail-fast, root-only evaluation |
| §8 "No change to the optimiser" | **dropped** | MILP change needed for (b′)/(c)/(d′) (P4); until then those are rejected on the live path, not approximated |

---

## 7. Answers to the open questions (Q1–Q10)

- **Q1** No fourth port. A balance node has one upstream connection plus n branches (M2, §1.1); the MILP needs PV/ESS per device, not per connection.
- **Q2** T5 is too strict (several Earnie-commanded actuators are one regulator) and too lax (`read_only` does not switch a vendor loop off). Replace by M6.
- **Q3** Refuse by default (M9). A labelled opt-in approximation later.
- **Q4** Child positive = flow from parent into the child; the parent uses the same number as a child connection. One sign, one orientation (M2).
- **Q5** Unchanged = keep both mechanisms (M8). Not a balance node.
- **Q6** Money uses root import/export counters, valid only while M1 holds (one tariff). Sub-node counters are attribution; adding them to the bill double-counts internal transfer.
- **Q7** Σ over grid-tied inverters stays correct with sub-nodes. The error sources are DC/AC mixing and the unit condition on `sens_inv_power_pv` (D5), not the tree.
- **Q8** Optional `update_interval_s` per balance node (P5) as a capability warning for slot actuals and foreign loops; not needed for 15-minute planning.
- **Q9** Acceptable for quarter-hour energy cost (utility meters net phases in DE/AT). Not for per-phase export caps or phase overload — stays a non-goal.
- **Q10** `components.json` → `balance_nodes[]`, optional (backtesting scenarios have no nodes). The MILP and backtesting ignore it.

---

## 8. Decisions (taken 2026-10-12)

1. **Scope and order:** Tier 1 first (P1, P2); then P3 (per-ESS writes) before P4 (reactive regulator); P5 (balance nodes) last.
2. **Rejection, not warn-and-exclude:** P1 refuses, on the live path, a multi-ESS plant with a `regulates_on: grid` battery beside another house battery — a plan that cannot be executed is not planned. Szenarien-Explorer and backtesting are unaffected.
3. **Negative-balance tolerance:** 5 % of `P_PV`, parameterisable (`plant.balance_tolerance_pct`, default 5), with an absolute floor (`plant.balance_tolerance_w`, default 100 W) so that night-time jitter does not raise errors.
4. **Naming:** the entity is the **balance node** (German *Bilanzierungspunkt*, with n *connections* / Anschlüsse, typically 2–4); `balance_nodes[]`, `node_id`, wire `node.<id>.sens_node_*`; root stays `grid.meter.*`. No `meters[]` and no `meter.<id>` namespace.
5. **Backlog:** epic **Topology** P1–P5 under Version 2.7, next to the Inverter follow-ups.
6. **Data model:** stays 4; one-shot migration scripts with fail-fast loaders wherever an existing config changes shape.
7. **Release scope (2026-10-14, supersedes the "all under 2.7" part of 5):** P1 is done and running on the productive plant. Version 2.7 keeps **P2** (fail-loud live balance) and the powerstation wording follow-up; **P3–P5** move to Version 2.+1. Reason: P3/P4 only widen what Earnie accepts (several house ESS, foreign regulator), which the productive plant does not need and P1 rejects on the live path; P4 changes the MILP and should be guarded by the Regression epic; P5 buys attribution only. The `ac_connection: island` rename travels with P5.

---

## 9. Non-goals (v1), with reasons

- Copper wiring, phases, cable limits, protection devices — not needed for the root energy identity (M3); per-phase caps would need per-phase metering (Q9).
- Reproducing vendor control loops — Earnie writes setpoints/limits; a foreign loop is modelled as reactive (P4) or rejected (M6), never simulated dynamically.
- Billing-grade metering concepts of grid operators — separate concern **except** where they create a second tariff boundary (M7), which is why a second billing meter is rejected rather than ignored.
- Sub-node evaluation beyond attribution — the optimiser uses the root (M4); per-node treatment only when a self-regulating device sits behind a sub-node (d′), and then as a reactive pin, not a second objective.
- A `cluster` attribute — control already routes per battery / inverter / plant; a label would only duplicate `regulates_on` (M5, M6).
- A stored `connections[]` list per balance node — connections are derived from references (§1.1); an explicit list would duplicate `node_id` / `parent` and the device bindings.
