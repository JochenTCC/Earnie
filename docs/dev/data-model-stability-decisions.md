# Data-model stability decisions D1–D3

Status: **decided (2026-10-25)** — D1 decided (option B), D2 decided (option C), D3 decided (recommendation accepted). Backlog notes written 2026-10-25.
Backlog entry: *Data-model stability decisions D1–D3* (Version 2.8).

Goal: a stable data model after 2.8, so fields added in the 2.8 migration steps (Edibert data migration, SUSI P1 / P2 / P6) are not migrated again in 2.+1. Each decision is a memo here plus a note on the owning 2.+1 item; implementation stays in 2.+1 unless stated.

## D1 — Consumer inner parts (nesting shape)

**Decision (2026-10-25): option B** — optional `parts[]` on the consumer, flat 3-segment wire IDs with a composite part Kennung, flat MILP with `parent_id`. Details under *Chosen: B* below; the two former open questions are settled there as defaults (see *Settled defaults*).

### Current state (code inventory)

- **Pool = two top-level consumers plus a synthetic sibling.** `pool_heating` is a `thermal_rc` consumer; the filter is a separate consumer with the reserved id `pool_filter` (`POOL_FILTER_ID` in `house_config/planning_flex_converters.py` and `ehal/qualified_ids.py`). Special-cased in ~50 places (`is_milp_pool_filter`, `planning_pool_filter_to_milp`, `_house_pool_filter_consumer`, `migrate_pool_filter.py`, `ehal_bindings_filter.py`, Loxone status/import).
- **Shared meter workaround.** `_ensure_shared_meter_filter_subtract` writes `loxone_inputs.subtract_consumer_ids = ["pool_filter"]` into the heating consumer, because the swim-spa meter includes the filter.
- **Qualified IDs are flat: `<ns>.<Kennung>.<kind>`** (exactly 3 segments, `parse_qualified_id`). The namespace is derived from consumer type, with `pool_filter` hard-wired to `pool` (`consumer_namespace`).
- **MILP is flat.** `collect_planning_flex_consumers` returns one list of flex dicts (generic, EV, thermal_annual, thermal_rc, filter); there is no parent/child concept in the model.
- **House thermal block.** `thermal_annual` holds `persons`, `house_heat_loss_kw_per_k` etc. (`house_config/profiles_thermal_annual.py`). SUSI P1 adds the heating rod there; SUSI P2 adds `internal_gain_factor` per consumer.

### Problem

SUSI P1 needs a heating rod that charges the heat storage — structurally the same relation as filter ↔ pool heating. Without a decision, 2.8 adds a second synthetic sibling (and special cases), and 2.+1 (*Enhance data model to nested structures*) migrates both again.

### Options

| | A. Status quo (siblings by convention) | B. `parts[]` on the consumer, flat wire IDs | C. `parts[]`, hierarchical wire IDs (4 segments) |
| --- | --- | --- | --- |
| Data model | reserved sibling ids per case | optional `parts[]` inside the consumer | same as B |
| Qualified ID | unchanged | stays 3 segments, part Kennung = `<parent>_<part>` | `<ns>.<parent>.<part>.<kind>` (parser, regexes, Loxone VO addresses, HA package change) |
| MILP | flat | flat (one flex entry per part, `parent_id` as metadata) | flat or nested |
| Wire / binding migration | none | none for existing bindings if the composite Kennung reproduces today's ids | all bindings and Loxone addresses |
| Fixes the sibling problem | no | yes | yes |

### Chosen: B

1. **Data model:** a consumer gets an optional `parts[]`; each part has `id` (unique within the consumer), `type` (e.g. `filter`, `heating_rod`), and its own planning fields. The consumer owns what is shared (label, shared meter, location in the UI).
2. **Addressing:** the part's Kennung on the wire is the composite slug `<consumer_id>_<part_id>` and the parser stays 3-segment. The parent/child relation is read from the profile, **never parsed from the string** (underscores are legal inside both ids). Today's `pool_filter` is reproduced by choosing the ids so the composite equals it, which avoids rewriting existing Loxone/HA bindings.
3. **MILP roles:** unchanged — one flat flex entry per part with `id` = composite Kennung and an added `parent_id`. No model change, so the R0 / P1 goldens and SE SNAP comparison stay valid. The shared-meter workaround becomes a parent-level meter with explicit `subtract_part_ids` instead of `subtract_consumer_ids` on a sibling.
4. **Mapping of today's consumers:**
   - pool heating + filter → one pool consumer, parts `heating` (RC thermal) and `filter` (flex hours / window) — implemented in 2.+1.
   - house `thermal_annual` + heating rod → parts `heat_source` (existing) and `heating_rod` — **new in 2.8** (P1).
   - EV + wallbox: not a part (separate entities with an assignment relation, see Multi-EV / Wallboxes).
5. **Consequences for 2.8:**
   - **SUSI P1:** the rod is `parts[]` entry `heating_rod` of the thermal consumer, no top-level `*_rod` consumer and no new synthetic sibling id. `parts[]` is introduced as an optional field in the 2.8 migration step; only the rod uses it in 2.8.
   - **SUSI P2:** `internal_gain_factor` sits on the electrical unit (consumer or part) that draws the power; the migration sets baseload / generic 0.8, ev / thermal / heating rod 0. Parts inherit nothing — the field is explicit per part.
   - **Pool merge** (drop `pool_filter`, its special cases and `migrate_pool_filter`) stays in 2.+1 as the owner item says; it migrates data into the already existing `parts[]` shape.
6. **Not a blocker:** Binding P6 (Kennung rename cascade) only makes the later rename of the composite Kennung cheaper; D1 does not depend on it.

### Settled defaults

- **Separator:** `_` in the composite Kennung (`<consumer_id>_<part_id>`). The relation is never parsed from the string, so the separator carries no meaning.
- **Location of `parts[]`:** on the consumer itself, next to (not inside) the `thermal` block. The MILP and addressing work at consumer level; `thermal` stays a pure physics block.
- Revisit only if the implementation in 2.+1 hits a case these defaults cannot express.

### Notes to add on completion

- *Enhance data model to nested structures* (2.+1): shape = B, link to this memo.
- SUSI P1 / P2: layout by D1 (already referenced; change wording from "per D1" to the concrete shape).

## D2 — `ac_connection` final name and ports vs. scalar

Status: **decided (option C, 2026-10-25).**

### Current state (code inventory)

- `inverters[].ac_connection` is a scalar enum `grid_tied | island` (`house_config/inverter.py`: `AC_ISLAND`, `allows_automatik`; schema enum in `share/config/components.schema.json`). It is read in `inverter_lifecycle.py`, `battery_kind.py`, `milp_inverter.py`, `optimizer/export_power_limit.py` (literal `"island"`), `pv_attribution.py`, `topology_live.py`, and the UI forms.
- `island` means "the inverter feeds attached loads only" — bus participation, not grid connectivity. A powerstation creates an *owned* island inverter (`owned_by`, `inverter_lifecycle.py`).
- The loads of such an output are listed in `attached_consumer_ids`, which lives on the **battery / powerstation** entry (`house_config/powerstation.py`, `entity_resolution.py`), not on the inverter.
- The legacy `batteries[].kind` / `ac_connection` values are still parsed in `battery_kind.py` (deprecated path).

### Options

| | A. Scalar, renamed | B. Ports replace the scalar | C. Scalar renamed, ports additive later |
| --- | --- | --- | --- |
| Shape | `grid_tied` / `attached_only` | `ports[]` (AC-in, AC-out with own `attached_consumer_ids`) | scalar stays; optional `ports[]` may refine it |
| Migrations | one (`island` → `attached_only`) | one, but a bigger model change now | one now, none later if ports stay additive |
| Needs a second use case | no | yes (several uncoupled AC outputs, series master) | no |
| Risk | ports later → second migration | speculative model, touches battery/inverter ownership | scalar and ports could disagree |

### Recommendation: C

1. **Name:** `attached_only`. It matches the existing `attached_consumer_ids` field; `load_side` does not say that the inverter feeds *only* the attached loads. `grid_tied` stays.
2. **No ports now.** The backlog item *Topology follow-up — Powerstation ports* itself says to build them only with a second use case; for one output `attached_consumer_ids` suffices. A powerstation is not a balance node (the root would count the attached load twice).
3. **Ports stay additive.** If they come, `ports[]` is an optional refinement and the scalar remains the shorthand for the single-port case. A validator rule keeps the two consistent (scalar must equal the derived value when `ports[]` exists). This avoids a second enum migration.
4. **2.8 impact: none.** The 2.8 migration step does not touch `ac_connection`; no port fields are reserved. The rename runs once in 2.+1 with *Topology P5* (`island` → `attached_only`, registered step with data-model bump, fail-fast loader, no dual-read). `balance_nodes[]` / `node_id` stay additive (default root).
5. **Touch list for the rename** is the file list above plus `docs/referenz/ehal.md`, German user docs and tests; the code-side literal in `export_power_limit.py` should use the constant when the rename is done.

### Open point

If you want zero risk of a second migration for ports, option B or reserving `ports[]` as an optional field in the 2.8 step is the alternative — at the cost of a speculative field that nothing reads.

### Notes to add on completion

- *Topology P5* and *Topology follow-up — Powerstation ports* (2.+1): name `attached_only`, ports additive, link to this memo.

## D3 — VAT flag and mandatory `vat_percent`

Status: **decided (2026-10-25).**

### Current state (code inventory)

- Tariffs carry `prices_include_vat` and `vat_percent` (`house_config/tariffs_store.py`, schema `share/config/tariffs.schema.json`). VAT is applied at the end of the price chain (`data/tariff_pricing.py`), and the net Netznutzung gets VAT on top (`se_invoice_netznutzung.py`).
- **Both fields are optional with silent defaults.** `data/tariff_pricing.py` reads `tariff.get("prices_include_vat", True)` and `float(tariff.get("vat_percent", 0.0) or 0.0)` at six places. A gross tariff without a rate only produces a once-per-tariff log warning (`_warn_gross_import_without_vat`) and then calculates with 0 % VAT — a result-obscuring default in the sense of `no-implicit-fallbacks.mdc`.
- **Catalog (`share/config/tariffs.json`) is already complete:** 50 tariff entries, all carry `vat_percent` (11 gross, 39 net). Making the field mandatory needs no catalog data change. The risk is user tariffs (`tariffs.json` in the config pack, later `user_tariffs.json`) that omit it.
- The house profile has no VAT field today.

### Recommendation

**(a) House-profile flag**

1. Name **`vat_deductible`** (bool, default `false`): "the operator can deduct input VAT". It states the fact; the effect (calculate net) follows from it, and it avoids "commercial". Alternative if you prefer naming by effect: `prices_net_of_vat`.
2. Placement: top level of the house profile (a property of the operator, not of a tariff or scenario).
3. It is **added in the SUSI P1 / P2 / P6 migration step** with value `false` and **ignored by the code** until the VAT item is implemented — no behaviour change in 2.8, no extra data-model bump later. A schema entry in `house_profiles.schema.json` with a description "not yet evaluated" keeps the loader honest.

**(b) `vat_percent` mandatory on every gross tariff**

1. Rule: `prices_include_vat: true` requires `vat_percent` (a number, `0` is allowed and explicit). Net tariffs may omit it only when no VAT step applies to them; for the VAT item (`vat_deductible: true`) the gross → net conversion needs the rate, so the Edibert format should simply require it on every tariff that has `prices_include_vat: true`.
2. Owner: the tariff format belongs to Edibert from 2.8 on, so this is agreed in the tariff-format alignment (*Versioning + Netznutzung split*) and ships as an Edibert format-version rule, not as an Earnie change. Earnie's loader then fails loud on a missing rate instead of the warn-and-continue path; the six silent defaults in `data/tariff_pricing.py` go away with the Edibert engine replacement.
3. Migration: the tariff-format step (same wizard run as the data-model step) must give user tariffs a rate or stop with a clear message. For existing gross user tariffs without a rate, the wizard asks (default 20 % AT / 19 % DE / 8.1 % CH from `STANDARD_VAT_PERCENT_BY_LAND`) instead of guessing.

### Text for the Edibert backlog

> Tariff format: `vat_percent` becomes mandatory whenever `prices_include_vat` is true (value `0` allowed). The loader rejects a gross tariff without a rate; no default. The shipped catalog already satisfies this (50 of 50 entries carry the field).

### Notes to add on completion

- *VAT model* (2.+1): flag name `vat_deductible`, already in the profile since 2.8, link to this memo.
- *Edibert integration* sub-item *Versioning + Netznutzung split*: the rule above (D3b), with the Edibert text.
- SUSI P6 / migration step: add `vat_deductible: false`.
