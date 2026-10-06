# EHAL — Inverter entity: doc change draft (2.7.l)

**Status:** draft, nothing applied. Backlog: [Backlog.md](Backlog.md) → **2.7.l — Inverter entity**.
**Target files:** [`docs/spec/ehal.md`](../docs/spec/ehal.md) and [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md) (both English). Apply in **Inverter P4**; German user docs (`docs/konfiguration/batterie-pv.md`) follow in **Inverter P2**.

Open: wire `schema_version` stays **4** (2.7 is unreleased, all new fields are optional) or bumps to **5**. This draft assumes 4; swap the number in the envelope row, both headings and the three "(schema_version 4)" section titles if it becomes 5.

---

## Design in one paragraph

An inverter is a first-class device (`components.json` → `inverters[]`). PV systems and batteries point to it via `inverter_id`. Built-in inverters (EcoFlow, Balkonkraftwerk storage) are normal inverters with `owned_by: <battery_id>` — no special case on the wire. EHAL gets a new optional role `inverter` in Pattern B (`inverter.{slug}.*`), bindings stored on `inverters[].ehal_bindings`, like `ess.{slug}.*` on `batteries[].ehal_bindings`. The global `sens_pv_production_active` stays the required plant sum; per-inverter values are additive and optional. `batteries[].kind` disappears; `ac_connection` on the inverter replaces it.

### New wire fields

| Field | Kind | Unit | Required | Meaning |
|---|---|---|---|---|
| `inverter.{slug}.sens_inv_power_ac` | telemetry | W | no | AC power of this inverter. `+` = feeds the AC bus (house), `−` = draws from it (e.g. grid charging). Same sign idea as `sens_ess_power`. |
| `inverter.{slug}.sens_inv_power_pv` | telemetry | W | no | PV input power of this inverter, ≥ 0 (DC side of a hybrid, string power of a PV inverter). |
| `inverter.{slug}.get_inv_max_ac_power` | telemetry | W | no | Device AC rating, magnitude ≥ 0. |
| `inverter.{slug}.get_inv_max_pv_power` | telemetry | W | no | Device DC/MPPT input limit, magnitude ≥ 0. |
| `inverter.{slug}.set_inv_ac_power_limit` | setpoint | W | no | Cap on AC output (curtailment), non-negative magnitude. Absent = leave unchanged; sticky backends: write the rating to release the cap, like `set_grid_export_power_limit`. |
| `supports_inv_power_limit` | capability | bool | no | `set_inv_ac_power_limit` can be written (omitted = false). |

`slug` = inverter id, same slug rules as `ess_ehal_slug`. The role is optional: a plant without mapped inverter fields behaves exactly as today. `sens_inv_*` names follow the existing `sens_ess_*` / `sens_evcs_*` prefixing.

---

## Changes to `docs/spec/ehal.md`

### 1. Header / history

- `**History (backlog):**` append `→ 2.7.l (inverter entity)`.
- `**Status:**` line: add "role `inverter` (Pattern B, optional)".

### 2. Core contract table

Add a row after "HA today":

| Rule | Detail |
|---|---|
| Inverter today | Optional role `inverter`: bindings `inverter.{slug}.*` on `inverters[].ehal_bindings` (Pattern B, same storage idea as `ess.{slug}.*`). Without mapped inverter fields the plant behaves as before; `sens_pv_production_active` stays the plant PV sum. |

### 3. Units and sign convention

- Table row 1 (active power telemetry): add `sens_inv_power_ac`, `sens_inv_power_pv`.
- Table row 3 (non-negative magnitudes): add `get_inv_max_ac_power`, `get_inv_max_pv_power`, `set_inv_ac_power_limit`.
- **Export limit "unconstrained"** paragraph — replace "sum of PV nameplate (kWp) + sum of max discharge power of every selected battery …" by:

  > Plant physical export maximum = Σ over **grid-tied** inverters of `min(max_ac_power_kw, PV kWp of its PV systems capped by max_pv_input_kw + max discharge of its force-dischargeable batteries)`; an inverter without `max_ac_power_kw` contributes the uncapped sum (previous behaviour). `island` inverters contribute nothing. Fallback when all unknown: `1 000 000` W.

- **PV** paragraph: add "`sens_pv_production_active` is the plant sum. When every inverter maps `sens_inv_power_pv`, adapters may derive it as Σ `sens_inv_power_pv` of grid-tied inverters (derived value only when the global field is unmapped; island inverters excluded)."
- **Reference power balance:** unchanged. Add one sentence: "Per-inverter values refine `P_PV` / `P_Bat`; they never replace the plant-level identity."

### 4. Telemetry-API

Add rows after `get_ess_max_discharge_power`:

| Field | Required | Unit | Notes |
|---|---|---|---|
| `inverter.{slug}.sens_inv_power_ac` | no | W | per inverter; `+` = feeds the AC bus |
| `inverter.{slug}.sens_inv_power_pv` | no | W | ≥ 0 |
| `inverter.{slug}.get_inv_max_ac_power` | no | W | device rating, magnitude |
| `inverter.{slug}.get_inv_max_pv_power` | no | W | DC/MPPT limit, magnitude |

### 5. Setpoint-API

Add a row after `set_grid_export_power_limit`:

| Field | Required in doc | Unit | Notes |
|---|---|---|---|
| `inverter.{slug}.set_inv_ac_power_limit` | no* | W | Max AC output of this inverter (magnitude ≥ 0). Curtailment tool for clipping / export caps per inverter. OpenEMS: see alignment table. |

### 6. New section after "Battery controllability": "Inverter topology (`inverters[]`, 2.7.l)"

Content (short, normative):

- Entity fields: `id`, `label`, `type` (`hybrid` | `pv_string` | `battery`), `max_ac_power_kw`, `max_pv_input_kw`, `max_ac_charge_kw`, `efficiency`, `control` (`full` | `limits_only` | `read_only`), `ac_connection` (`grid_tied` | `island`), `owned_by`, `ehal_bindings`.
- References: `pv_systems[].inverter_id`, `batteries[].inverter_id` (n:1). Scenario selects `pv_system_ids[]` / `battery_ids[]`; inverters in play follow from them.
- Table of `type` × MILP effect:

  | `type` | PV | Battery | Limits |
  |---|---|---|---|
  | `hybrid` | DC side | DC side | `pv + discharge ≤ max_ac`; PV ≤ `max_pv_input` |
  | `pv_string` | yes | — | PV ≤ `max_ac` |
  | `battery` | — | AC-coupled | charge/discharge ≤ `max_ac` |

- `ac_connection`: `grid_tied` = AC side on the house bus; `island` = AC side feeds only attached loads, its PV is not part of the house balance, battery never runs in Automatik (replaces `batteries[].kind = isolated`).
- Built-in inverters (`owned_by`): lifecycle/UI flag only; created and deleted with the battery.
- `control` per inverter gates `set_inv_ac_power_limit` the same way `batteries[].control` gates ESS writes; EHAL-Com warns when `control` asks for more than bound functions allow.
- Virtual powerstations have no inverter (carve-out of the house battery).

### 7. Capability-Flags table

Add row: `supports_inv_power_limit` | no | `set_inv_ac_power_limit` can be written. Update the sentence below the table: "…`supports_ess_source_select` and `supports_inv_power_limit` may be omitted (treated as false)."

### 8. OpenEMS light alignment table (semantic reference, verify before freezing)

| EHAL field | OpenEMS (prototype) |
|---|---|
| `sens_inv_power_ac` | ESS `ess0/ActivePower` (hybrid) / meter `…/ActivePower` |
| `sens_inv_power_pv` | `charger0/ActualPower` (DC string on hybrid) / PV-inverter `…/ActivePower` |
| `get_inv_max_ac_power` | `ess0/MaxApparentPower` |
| `get_inv_max_pv_power` | *(optional / absent)* |
| `set_inv_ac_power_limit` | PV-inverter `…/ActivePowerLimit` (where available); else unused |

### 9. Deferred device classes / Device roles

- "Device roles" table, `Device-role schema` row: roles list becomes `grid`, `pv`, `ess`, `inverter`, `evcs`; stubs unchanged. Add `share/ehal/roles/inverter.json` (all fields optional).
- Rules paragraph: add "`inverter.{slug}.*` is a Pattern B namespace like `ess.{slug}.*` and `flex.{slug}.*`."

### 10. Implementation notes

- **OpenEMS / HA / Loxone:** one bullet each: bindings live on `inverters[].ehal_bindings`; HA live aggregation subset (`HA_ALL_FIELDS`) gains the `inverter.*` keys only when wired; Loxone adds optional Merker (`Earnie_WR_…`, recipe `share/loxone/recipes/inverter.json`) — names to be fixed in P4.
- **Built-in inverter devices** (EcoFlow): one device may map `ess.{slug}.*` and `inverter.{slug}.*` to entities of the same HA device; no collision because the slugs differ (`owned_by` links them).

### 11. Out of scope

Add: "Efficiency modelling DC↔AC (follow-up of 2.7.l), multi-inverter attribution of the plant-level `sens_pv_production_active` on the wire."

---

## Changes to `docs/ui/ehal-com.md`

### 1. §B wire table

- Envelope row `schema_version` text: unchanged (assuming 4).
- Add rows (category "Telemetry (optional)"): `inverter.{slug}.sens_inv_power_ac`, `…sens_inv_power_pv`, `…get_inv_max_ac_power`, `…get_inv_max_pv_power`.
- Add row (category "Setpoints (limits)"): `inverter.{slug}.set_inv_ac_power_limit`.
- Add row (category "Capability flags"): `supports_inv_power_limit` (no; boolean).
- Sentence under the table ("Full device roles …"): mention "`ess.{slug}.*` / `inverter.{slug}.*`".

### 2. §C.1 — rename and scope

- Current title "C.1 Inverter (Grid / PV)" is misleading once a real inverter role exists. Rename to **"C.1 Plant (Grid / PV sum)"**; table content unchanged. The PV row gets the note "plant sum; per-inverter values in C.7".
- Keep the anchor stable or add `<a id="c1-inverter-grid-pv"></a>` so existing links survive.

### 3. §C.2 ESS

- Under the Multi-ESS paragraph add: "A battery belongs to an inverter via `batteries[].inverter_id`. `batteries[].kind` (topology) no longer exists; `inverters[].ac_connection` (`grid_tied` | `island`) replaces it."
- "Battery `control` vs mapping" paragraph unchanged.

### 4. New §C.7 "Inverter (per device)" (append after C.6 to avoid renumbering)

Intro (short): "Bindings live on `inverters[].ehal_bindings` as Pattern B `inverter.{slug}.*` (slug = inverter id). Optional; role template `share/ehal/roles/inverter.json`. Built-in inverters (`owned_by`) share a physical device with an ESS: map both slugs to that device's entities."

| Area / meaning | Type | EHAL value name | OpenEMS | evcc | Victron GX | Loxone / Loxone extra |
|---|---|---|---|---|---|---|
| Inverter AC power | Measurement | `inverter.{slug}.sens_inv_power_ac` | `ess0/ActivePower` / PV-inverter `…/ActivePower` | | TBD | `Earnie_WR_Leistung_AC` *(name TBD, P4)* |
| Inverter PV input power | Measurement | `inverter.{slug}.sens_inv_power_pv` | `charger0/ActualPower` | | TBD | `Earnie_WR_Leistung_PV` *(TBD)* |
| Inverter max AC power (device) | Input value | `inverter.{slug}.get_inv_max_ac_power` | `ess0/MaxApparentPower` | | | `Earnie_WR_Max_AC` *(TBD)* |
| Inverter max PV input (device) | Input value | `inverter.{slug}.get_inv_max_pv_power` | *(optional / absent)* | | | `Earnie_WR_Max_PV` *(TBD)* |
| Write inverter AC limit | Control value | `inverter.{slug}.set_inv_ac_power_limit` | PV-inverter `…/ActivePowerLimit` | | | `Earnie_WR_Limit_AC` *(TBD)* |
| Inverter limit write capability | Capability | `supports_inv_power_limit` | derived adapter capability | derived | | derivable from mapped limit Merker |

Note below the table: "Inverter `control` vs mapping: `full` needs `set_inv_ac_power_limit`; `limits_only` / `read_only` need no inverter write. EHAL-Com warns like for ESS."

### 5. Page sections

- **Live Read:** the Live tables group by role label; add role "Wechselrichter" (labels come from `ehal.profiles.role_field_labels`). Rows show `{inverter_id}:inverter.{slug}.…` like `{id}:flex.{slug}.…`.
- **HA Entity → EHAL Mapping / Loxone Structure → EHAL Mapping:** one sentence each — fields of role `inverter` appear per inverter after the ESS block; heuristic proposals only for empty fields; built-in inverters are listed under their battery.
- **Live Write / Schreibtest:** list `set_inv_ac_power_limit` as a writable field (needs `supports_inv_power_limit`; the test restores the previous value like the ESS write test).

### 6. See Also

Add link to the new section "Inverter topology" in `ehal.md`.

---

## Code touchpoints for P4 (not doc changes, for planning)

`ehal/ess_fields.py` (pattern as template for `ehal/inverter_fields.py`), `ehal/models.py`, `ehal/functions.py` (function "inverter_limit" available when `set_inv_ac_power_limit` is mapped), `ehal/profiles.py` (role + labels), `share/ehal/*.schema.json`, `share/ehal/roles/inverter.json`, `house_config/ha_ehal_bindings.py` (`HA_ALL_FIELDS`), `integrations/{ha,loxone,openems}_adapter.py`, `integrations/ehal_live.py`, `ui/ehal_ha_mapping.py` / `ui/ehal_loxone_mapping.py`, `share/loxone/recipes/inverter.json`, `share/loxone/templates/VirtualIn/VI_Earnie_Plant.xml`.
