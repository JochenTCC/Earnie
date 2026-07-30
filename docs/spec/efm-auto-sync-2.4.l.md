# EFM auto-sync research (2.4.l / Interpretation C)

**Date:** 2026-07-30  
**Lab:** Live Miniserver with Energieflussmonitor + Zähler (LoxAPP3 + MCP 17.1).  
**Manual blueprint:** `.cursor/plans/energieflussmonitor_hausprofil_blueprint_a.plan.md`

## Verdict

| Capability | Result | Notes |
| --- | --- | --- |
| Meter list | **Go** | LoxAPP3 `type=Meter` (11+) plus EFM `details.nodes` (`nodeType` Grid/Production/Storage/Load/Group). Rest lives under EFM `subControls`. |
| Consumer import | **Go** | Enough `name` + uuid for generic HK consumers. Flatten Groups to leaf Loads. |
| `flex.power_name` | **Go** | `/jdev/sps/io/{Meter.name}` returns actual power (kW). Prefer **control name**, not state UUID (state UUID → 404). |
| CSV stem mapping | **Go** | Suggest stem from Bezeichnung; user still exports/uploads single-series CSVs. |
| MCP `control_bind` | **N/A** | `control_describe` returns Meter metadata (`states`, `details`) but **no** `control_bind` field. EFM↔Zähler link is LoxAPP3 `nodes[].ctrlUuid`. |
| `flex.enable_name` / `flex.power_setpoint_name` | **N/A** | Cannot be derived from Zähler (by design). |

**Product path:** thin HITL on EHAL-Com (`integrations/loxone_efm_meters.py`, `ui/ehal_efm_import.py`). No multi-column EFM Statistik import.

## Role mapping (EFM `nodeType` + Meter `details.type`)

| Source | Earnie role | Action |
| --- | --- | --- |
| `Grid` / name≈Netz / `bidirectional` plant | `grid` | Suggest `plant` `sens_grid_power_active` = Meter name |
| `Production` / name≈PV | `pv` | Suggest `sens_pv_production_active` |
| `Storage` / `details.type=storage` | `battery` | Suggest `sens_ess_power` |
| `Load` / other unidirectional Meter | `consumer` | Create generic + optional `flex.power_name` |
| `Group` | — | Flatten; no consumer for the group node itself |
| EFM `Rest` (subControl and/or Load named Rest) | `residual` | No consumer (Basislast residual) |

## Naming: required vs recommended

**Not required** for import when Zähler are hung on the Energieflussmonitor with the correct Loxone **node role** (`Grid` / `Production` / `Storage` / `Load`). Earnie prefers `nodeType` over the Bezeichnung. Live `flex.power_name` is the Meter control **name as configured** (must be unique and stable on the Miniserver so `/jdev/sps/io/{name}` keeps working).

**Hard rules (few):**

| Rule | Why |
| --- | --- |
| Unique Bezeichnung per Zähler | Earnie binds and matches by name; duplicates collapse in structure scans |
| Do not rename after binding | `flex.power_name` and HITL match-by-label break if the Loxone name changes |
| Residual meter stays named **`Rest`** (Loxone default) | Name `Rest` forces residual even if EFM lists it as `Load` |

**Recommended** (helps orphans, CSV stems, and human HITL):

| Layer | Convention | Example |
| --- | --- | --- |
| Consumer / branch Zähler | Clear device label; optional `cons_` prefix | `Zähler Wärmepumpe` or `cons_wp_waermepumpe` |
| Grid / PV / battery | Keep role words in the name **or** rely on EFM nodeType | `Zähler Netz`, `Zähler PV-Anlage`, `Zähler Batterie` |
| Optional role tokens (blueprint A) | `grid_` / `pv_` / `batt_` / `cons_` / `total_` | `grid_main`, `pv_main`, `cons_wb_wallbox` |
| Statistik export filename | Same stem as Bezeichnung | `zaehler_waermepumpe_2025.csv` → HK upload |
| Earnie consumer label | Same as Loxone Bezeichnung | HITL action **match** when re-importing |

Name heuristics used only when `nodeType` is missing (orphan Meter not in EFM tree): substrings `netz`/`grid`, `pv`/`solar`/`produktion`/`erzeug`, `batter`, and Meter `details.type` `storage` / `bidirectional`. Free-text consumer names (e.g. `Zähler TV`) are fine as Loads.

Attach plant meters (Netz/PV/Batterie) and each important Verbraucher as EFM nodes rather than relying on naming alone.

## Abandoned (unchanged)

Multi-column Energieflussmonitor Statistik CSV with all Leistungsflüsse → HK column↔Verbraucher (2026-07-23).
