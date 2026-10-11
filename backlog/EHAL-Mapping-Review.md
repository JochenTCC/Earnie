# EHAL field mapping — Loxone vs Home Assistant review

Comparison of EHAL field mapping / binding for Loxone and HA: shared surface, safe unification done, and deferred reuse candidates.

## Already shared

| Concern | Location |
|---------|----------|
| Binding store | `plant` / `batteries[]` / `consumers[].ehal_bindings` (Loxone: Merker or empty Q8 id; HA: `entity_id`) |
| Qualified IDs / entity-scoped | `ehal/qualified_ids.py`, `ehal/ess_fields.py`, `ehal/flex_fields.py` |
| Function completeness | `ehal/functions.py` |
| ESS Automatik omit | `integrations/loxone_writes.map_ess_setpoints` via `integrations/ehal_live.write_ess_setpoints_from_control` (HA adds Huawei force-stop when `set_ess_active_power` is absent) |
| HITL plant helpers | `ui/ehal_ha_mapping.py` imports `PLANT_TELEMETRY_REQUIRED` / entity helpers from `ui/ehal_loxone_mapping.py` |

## Safe unification (done)

Hub-agnostic field-membership catalogs live in [`ehal/field_catalog.py`](../ehal/field_catalog.py):

- `TELEMETRY_REQUIRED`, `TELEMETRY_OPTIONAL_CORE` / `_HA` / `_LOXONE`
- `TELEMETRY_BINARY_OPTIONAL`, `TELEMETRY_ENERGY_OPTIONAL`, `SETPOINT_FIELDS`
- `HA_MAP_FIELDS`, `STATIC_HUB_MAP_FIELDS` (aliases `LOXONE_MAP_FIELDS` / `TELEMETRY_OPTIONAL_LOXONE` kept temporarily)

Adapters and UIs import these tuples instead of maintaining parallel copies in `ha_adapter`, `loxone_ehal_mapping`, and `loxone_adapter`. HA optional stays core-only (no numeric outdoor-temp / absent loop). Loxone optional keeps historical mid-tuple order for `sens_temperature_outside` / `sens_absent_mode`.

## Intentionally separate

| Concern | Loxone | HA |
|---------|--------|-----|
| Transport | VO push inbox + `status.json` | REST state / services; vendor `ha_ess_force` |
| Units | Role JSON `loxone` blocks → `ehal/field_registry` (`hub * sign * factor`) | Runtime `unit_of_measurement` → `integrations/ha_units.py`; `ehal.ha.sign` |
| Read-loop membership | `PLANT_REQUIRED_READ_FIELDS` / `PLANT_OPTIONAL_READ_FIELDS` in `field_registry` (`sens_ess_power` required; different order) | Mapping catalog optional list |
| Live-Lesen catalogs | `integrations/ehal_debug_mapping.py` (`PLANT_*`, `EV_*`, `THERMAL_*` — qualified / per-battery) | Same Live catalogs; mapping overlay differs |
| HITL UI | `ui/ehal_loxone_mapping.py` (+ `_ui`) | `ui/ehal_ha_mapping.py` |
| Heuristic propose | `integrations/loxone_ehal_mapping.py` | `integrations/ha_ehal_mapping.py` |

Do **not** add `ha` conversion blocks to role JSON or store factors on bindings.

## Deferred reuse candidates (not in this change)

1. **HITL UI merge** — parallel scan / propose / save flows (~700–900 LOC each). Large UI task; keep hub-specific propose and entity pickers.
2. **Live-Lesen catalog alignment** — `ehal_debug_mapping` overlaps mapping catalogs but uses qualified IDs and per-battery kinds; unify only with a clear exchange-ID contract.
3. **Loxone read-loop vs mapping catalog** — collapsing `PLANT_*_READ_FIELDS` into `field_catalog` would change which Loxone reads are mandatory.
4. **Heuristic propose** — different name hints and domains; share only field lists (already via catalog).
5. **Loud ESS write units** — `loxone_writes` publishes hub kW into `status.json` while the adapter path uses `require_loxone_write` (EHAL W → hub); document/clarify, do not blindly share with HA W-native entities.

## Verification

See `tests/test_ehal_field_catalog.py` and the adapter / mapping pytest subset listed in the implementation plan.
