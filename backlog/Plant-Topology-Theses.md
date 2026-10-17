# Plant topology and metering — theses for external review

**Status:** Draft for review. Nothing here is decided or implemented.
**Date:** 2026-10-12
**Scope:** How Earnie models the electrical topology of a plant (meters, inverters, PV, batteries, loads) and which topologies it accepts.
**Audience:** An independent reviewer (LLM or human). Please challenge the theses; do not just confirm them.

Related: [`docs/referenz/ehal.md`](../docs/referenz/ehal.md), [`docs/dev/done/conversion-losses.md`](../docs/dev/done/conversion-losses.md), [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md).
**Follow-up (2026-10-12):** reviews [`Plant-Topology-Theses-Review-Claude.md`](Plant-Topology-Theses-Review-Claude.md), [`Plant-Topology-Theses-Review-Grok.md`](Plant-Topology-Theses-Review-Grok.md); decisions in [`Plant-Topology-Conclusion.md`](Plant-Topology-Conclusion.md) (T5 replaced by the regulator rule, balance nodes instead of `meters[]`, epic **Topology** P1–P5 in [`Backlog.md`](Backlog.md)).

---

## 0. How to review this paper

Evidence is tagged: **[code]** read in this repository, **[vendor]** vendor documentation, **[forum]** user report, **[inference]** reasoning by the authors. Anything tagged **[inference]** or **[forum]** is a hypothesis, not a fact. Section 6 lists what could not be verified.

Please answer, per thesis (T1–T10): *agree / agree with changes / disagree*, with a reason and, if possible, a counter-example from a real installation. Section 7 lists the questions we are least sure about.

---

## 1. Current model (facts from the repository)

- **[code]** `components.json` holds `inverters[]`, `batteries[]`, `pv_systems[]`. Batteries and PV systems point to exactly one inverter via `inverter_id` (n:1). Inverter `type` is `hybrid`, `pv_string` or `battery`; `ac_connection` is `grid_tied` or `island`; `control` is `full`, `limits_only` or `read_only`; `efficiency` (η_inv) is mandatory. (`house_config/inverter.py`)
- **[code]** Validation checks unknown ids and rejects PV on a `battery` inverter. It does **not** reject a battery on a `pv_string` inverter, although the spec table says "no battery" there.
- **[code]** The MILP clips per inverter (`pv + discharge <= max_ac`, optional DC cap, optional grid-charge cap); `island` inverters contribute nothing to the house balance. (`optimizer/milp_inverter.py`)
- **[code]** The grid meter is **not** an entity in `components.json`. It exists as plant-level bindings in `house_profiles.json` under `plant.ehal_bindings` (bare keys such as `sens_grid_power_active`, `sens_grid_energy_import/export`, `get/set_grid_export_power_limit`). On the exchange wire they appear as `grid.meter.<kind>`. `GRID_METER_ID = "meter"` is hard-coded with the comment "first (and currently only) grid meter Kennung; more meters may follow"; `qualified_grid_id(key, meter_id=...)` already accepts a meter id. (`ehal/qualified_ids.py`, `share/config/house_profiles.schema.json`)
- **[code]** House load is derived: `P_cons = max(0, P_PV + P_grid + P_ess)` with grid `+` = import and ESS `+` = discharge, unless a house-load binding is mapped. (`integrations/ehal_live.py`, `docs/referenz/ehal.md`)
- **[code]** Plant PV (AC) can be derived as the sum of grid-tied inverter PV times η_inv; island inverters are excluded; incomplete maps fail loudly. (`integrations/pv_attribution.py`)
- **[code]** `grid.meter` appears in ~99 places in 31 files, including Loxone Virtual-Out/In templates and tests. Data model version is `earnie_data_model = 4`; one-shot migration scripts and fail-fast loaders already exist for earlier shape changes (e.g. `migrate_inverters_once`).
- **[code]** The configuration is unpublished, so the data model can still change.

**Implicit assumption today:** exactly one meter exists and all configured inverters are electrically behind it.

---

## 2. Problem statement

1. Earnie has **no access to the utility meter**. The meter it reads is a vendor smart meter (inside the inverter, or a separate sensor that some vendors require once a battery is present). **[inference/user report]**
2. Real installations often contain **several inverters of different vendors, installed at different times**. They do not know each other. **[inference]**
3. If two such systems each regulate towards "zero grid power" against the same grid value, the corrections add up and the system oscillates. **[forum]** (see §5). This is a control problem, not a measurement problem.
4. If meters sit in nested sub-networks, summing "house loads" from different meters double-counts. Worked example (load 4 kW, WR1 3 kW, WR2 2 kW):

   | View (meters at the same node) | Calculation | "House load" |
   |---|---|---|
   | Utility/root meter alone | export 1 kW → −1 | −1 kW |
   | WR1 with own meter | −1 + 3 | 2 kW |
   | WR2 with own meter | −1 + 2 | 1 kW |
   | True | −1 + 3 + 2 | 4 kW |

   Nested sub-networks (each with its own meter and inverter): `L1 = M1 + P1`, `L2 = M2 + P2`, `L_total = Z0 + P1 + P2`, `Rest = Z0 − M1 − M2`, and `L_total = L1 + L2 + Rest`. Adding `L_total` to `L1` and `L2` double-counts.

---

## 3. Theses

**T1 — Node model.** A *meter* is a balance node with three ports: **Netz** (upstream), **Last** (consumers connected in parallel at this node) and **Generator** (a generation/storage cluster). Balance: `P_netz + P_gen = P_last` (signs per EHAL convention). The Generator port is bidirectional (battery charging is negative generation); "Generator" is a working name.

**T2 — One balancing node.** Earnie balances (and later optimises) at exactly **one** node, the *root* meter, whose Netz port **is** the house connection. This is an assertion by the user; Earnie cannot verify it because the utility meter is not readable.

**T3 — Meaning of `grid.meter`.** `grid.meter` always denotes the root meter: the meter that measures directly downstream of the utility meter. In simple plants this is the one meter that was installed for balancing, and it is implicitly or explicitly assigned to the one inverter/cluster. The name stays reserved for the root meter and its wire IDs do not change.

**T4 — Tree, not mesh.** Other meters may exist as **sub-meters** ("Bilanzierungspunkte"), cascaded below the root (their Netz port attaches to a parent port), never in parallel to it. From the parent's view a sub-network is an **Abgang**: bidirectional (a garage with PV can export), not controllable by the parent, and its internal structure is invisible. Residual = parent − Σ children. Double counting only happens when nested scopes are summed. Sub-meters are used for attribution only; the optimiser uses the root.

**T5 — One controllable cluster per node.** A *cluster* is a set of inverters/batteries that can coordinate (e.g. one vendor dongle or gateway). At most one controllable cluster per meter. Further independent generators at the same node are allowed only as **not controllable** (`control: read_only`) and trigger a warning. Rationale: uncoordinated regulators against the same grid signal interfere (T-evidence in §5). Redundant meters in series at the same node are harmless (they measure the same quantity).

**T6 — Read per device, control per system.** Earnie must *read* per inverter where the vendor integration exposes it, but *controls* through battery devices and system-wide services. A communicating cluster is therefore either one logical inverter (if the integration exposes aggregated values and setpoints at one endpoint) or several inverters sharing one meter and one control path. The explicit `cluster` attribute is needed mainly to validate T5, not to route control.

**T7 — No critical/non-critical load split.** The balance needs only the total load (derived). A series master that passes all load current is a **capacity** concern (pass-through limit of the master), handled as a plausibility check, not as topology.

**T8 — Wiring is not modelled, scope and control are.** Series wiring (e.g. Victron-style master with loads and AC-coupled PV behind it) and parallel wiring (typical hybrid inverter at the house node) are equivalent for the energy balance as long as there is one root meter and everything controllable lies in its scope. The model records *scope* (which devices lie behind which meter) and *who controls*, not copper topology.

**T9 — Schema changes (proposal).**
- New `meters[]` (suggested location: `components.json`, because meters are physical devices like inverters, which already carry `ehal_bindings` there; alternative: keep under `plant` since bindings there are live-only): `id`, `label`, `role` (`root` | `sub`), `parent` (for `sub`), `ehal_bindings`.
- New `inverters[].meter_id` (n:1, same pattern as `pv_systems[].inverter_id`); defaults to the root meter when exactly one meter exists.
- Optional `inverters[].cluster`.
- Validation: exactly one root; no cycles; all references resolve; at most one non-`read_only` cluster per meter.
- Bare `plant` grid bindings move to the root meter's `ehal_bindings`; wire IDs `grid.meter.*` stay; sub-meters get a different namespace (e.g. `meter.<id>.*`) because `grid` means house connection.
- Consumer sensors (`consumer.*.sens_power_act`) remain *measuring points*, not meters, to avoid a naming clash.

**T10 — Migration and rollout.** Because the model is unpublished it can change within data model 4 (or bump to 5; open decision). Use a one-shot migration for existing development environments and a fail-fast loader for the old shape (no dual-read, no silent fallback — project rule). Schema may already contain sub-meters; code initially only evaluates the root meter.

---

## 4. Topology examples and expected validation result

ASCII notation: `[M]` meter, `G` generator cluster.

```
(a) Simple               Netz ─[M root]─┬─ Last
                                         └─ G: hybrid WR + PV + battery           → accepted

(b) Retrofit, 2 vendors  Netz ─[M root]─┬─ Last
    same node                            ├─ G1: vendor-A cluster (controlled)
                                         └─ G2: vendor-B WR (read_only)            → accepted with warning

(c) Two controllable     Netz ─[M root]─┬─ G1 (controlled)
    clusters, same node                  └─ G2 (controlled)                        → rejected (T5)

(d) Sub-network          Netz ─[M root]─┬─ Last
                                         └─ Abgang ─[M sub]─┬─ Last
                                                             └─ G2: PV + battery  → accepted; sub only for attribution

(e) No root meter        only [M sub] readable, utility side unknown               → rejected by default
                         (exact balance impossible; optional explicit approximation, see Q3)
```

Previously discussed concrete cases:

- Two hybrid inverters of different vendors, each with its own meter at the house connection → (b)/(c) depending on whether one can be `read_only`.
- AC-coupled retrofit (PV string inverter + battery inverter): accepted if one of them is the controlled cluster and the other coordinated or `read_only`.
- Island/standby powerstation (e.g. one-way battery with attached loads): today modelled as `ac_connection: island`; its place in the new tree is open (Q5).

---

## 5. Evidence and sources

| Claim | Type | Source |
|---|---|---|
| Two uncoordinated regulators on the same grid value overshoot and oscillate; a meter per system does not fix it | forum (several threads, consistent) | [Akkudoktor: Smartmeter an mehreren Stellen](https://akkudoktor.net/t/ein-smartmeter-an-mehreren-stellen-mit-mehreren-wr-abrufen/24687), [Akkudoktor: Zweites Smart Meter](https://akkudoktor.net/t/zweites-smart-meter-oder-reicht-eins/38622) |
| Victron: non-Fronius AC-coupled inverters cannot be zero-export-controlled; staggered setpoints used as workaround by users | vendor + forum | [Victron ESS system design](https://www.victronenergy.com/media/pg/Energy_Storage_System/en/ess-system-design.html), [forum](https://communityarchive.victronenergy.com/questions/46469/ac-coupling-with-non-fronius-inverters-and-export.html) |
| Victron: PV inverter "Position" = AC Input 1/2 or AC Output; without a Victron grid meter all loads and grid-tied inverters must hang on AC-out; "External meter" enables parallel layouts | vendor | [AC coupling with Fronius](https://www.victronenergy.com/live/ac_coupling:fronius), [ESS configuration](https://www.victronenergy.com/media/pg/Energy_Storage_System/en/configuration.html) |
| Victron: a parallel/three-phase Multi cluster is one VE.Bus system on one GX device | vendor | [GX manual](https://www.victronenergy.com/media/pg/Ekrano_GX/de/connecting-victron-products.html) |
| Huawei: master inverter with Smart Dongle, slaves via RS485 cascade, up to 10 devices; with battery or single-phase inverters max 3 inverters; a single ESS must sit on the master | vendor (search summary, quick guide itself unreadable) | [Huawei quick guide](https://support.huawei.com/enterprise/en/doc/EDOC1100265358) |
| Huawei via Home Assistant (`wlcrs/huawei_solar`): slaves readable only through the master dongle; one entity set per inverter (`_2`, `_3`); one power-meter sensor; force-charge/discharge and max-feed-in as services targeting battery devices; single Modbus client | vendor/community docs | [huawei_solar](https://github.com/wlcrs/huawei_solar/) and its wiki |
| UK G100: export limitation is assessed for the system (inverters + meter + controller), multi-inverter schemes exist | vendor declarations | [SMA EDMM-20 G100](https://www.windandsun.co.uk/cdn/shop/files/SMA_Commercial_Inverters_EDMM-20_Export_Limitation_G100-2.pdf) |
| German grid operators publish metering concepts (VDE-AR-N 4105 based); they describe billing metering, not control | vendor/operator (search summaries) | [VBEW concepts via Rheinnetz](https://rheinnetz.de/771.20-240514-vbew-messkonzepte-und-abrechnungshinweise.pdfx) |
| That billing metering concepts and control meters are separate concerns | inference | — |

---

## 6. Not verified

- Original Victron topology diagrams (images, not readable): the AC-in/AC-out drawings in this paper are reconstructions from text. Whether the grid meter sees an AC-in-side PV inverter is **not documented** in the pages read.
- Huawei quick guide (page content did not load); who holds the meter and how limits propagate to slaves is not confirmed. Which entities exist for charge/discharge limits, working mode and active-power limit in `huawei_solar` was not found.
- Fronius/Kostal multi-inverter behaviour: no official documentation found, forum reports only.
- Dortmund metering-concept PDF (diagram-only), VDE-AR-N 4105 full text, Austrian TOR Erzeuger: not read/found. No regulation was found that prescribes how mixed-vendor inverters must be metered or coordinated.
- No vendor-neutral installer training material was found; Victron offers an AC-PV online training (not opened).

---

## 7. Open questions for the reviewer

- **Q1.** Is a three-port node with a bidirectional generator port sufficient, or is a fourth port type (e.g. explicit storage) needed?
- **Q2.** Is "one controllable cluster per node, others `read_only`" the right rule, or too strict/too lax? Which real installations break it?
- **Q3.** Should an explicit user-acknowledged approximation exist when no meter at the house connection is readable (price the Netz port of the topmost readable meter as grid)? Or must Earnie refuse? (Project rule: no silent fallbacks.)
- **Q4.** Is the sign convention for an Abgang (bidirectional, uncontrollable) the right way to treat sub-networks with their own generation?
- **Q5.** Where do island/standby powerstations (one-way battery, attached loads, charged from the house net) fit in the tree: as sub-network, as special inverter, or unchanged?
- **Q6.** Energy counters (kWh) for cost accounting: do they always belong to the root meter, and what about sub-meter counters?
- **Q7.** PV attribution with η_inv: does summing over all inverters below the root remain correct when sub-meters exist?
- **Q8.** Meter accuracy and latency (e.g. 5-minute counter refresh reported for one vendor) versus control quality: should meter capability be part of the model?
- **Q9.** Three-phase asymmetry and per-phase metering are not modelled. Acceptable for a planning tool?
- **Q10.** Is `components.json` the right home for `meters[]`, given that backtesting scenarios share it but meters only matter live?

---

## 8. Non-goals

- Modelling copper wiring, phases, cable limits, protection devices.
- Reproducing vendor control loops or coordinating foreign regulators beyond setpoint/limit writes.
- Billing-grade metering concepts of grid operators.
- Any change to the optimiser: with only the root meter evaluated, the MILP is unaffected.
