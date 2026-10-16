# Migration fixtures (ConfigMigration P0)

Scrubbed **before**-state pack snapshots for the guided config migration epic. Inventory: [`backlog/Config-Migration-Inventory.md`](../../../backlog/Config-Migration-Inventory.md). Design: [`backlog/Config-Migration-Draft.md`](../../../backlog/Config-Migration-Draft.md).

**Source:** private repo Earnie-env-home (`config/`). Never commit raw content from that repo.

**Re-extract:**

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m scripts.extract_migration_fixtures --env-home <path-to-Earnie-env-home>
```

Goldens of migrated results: [`goldens/<snapshot>/`](goldens/) (ConfigMigration P1).

## Snapshots

| Folder | Source | Covers |
|--------|--------|--------|
| `v3_last/` | Earnie-env-home `7269b26` (3 batteries) | v3→v4 + plant-flat ESS **blocker** (cannot auto-pick target); `pool_filter` MILP fields still missing |
| `v3_single_battery/` | same SHA, sliced to one battery | happy-path chain start for P1 |
| `v3_pre_ehal/` | reconstructed: v1 (`26c9daf`) `loxone_blocks` + consumer nests on dm3 skeleton; ESS-mapped block keys and plant-flat ESS stripped so the ehal CLI can dry-run alone | `migrate_ehal_bindings` only |
| `v4_pre_quellenwahl/` | `760ab99` | `migrate_ess_bindings_once` phase 2 (Quellenwahl) |
| `v4_pre_inverter_gridfee/` | `515ea9a` | `migrate_inverters_once` + `migrate_grid_fee_profile` |
| `v4_pre_conversion/` | `49fc6a2` | `migrate_conversion_efficiency_once` |
| `v4_pre_topology/` | `c0cd597` | `migrate_topology_once` |

Pack files included when present: `config.json`, `house_profiles.json`, `components.json`, `deviation_rules.json`, `backtesting_scenarios.json`, `grid_fees.json`. No `uploads/`, schemas, examples, or private `tariffs.json`.

## Scrub rules

Applied by `scripts.extract_migration_fixtures`:

- Profile id → `profile_a`, label → `House A`
- Latitude / longitude → `47.0` / `10.0` (including thermal_rc)
- Non-empty values under `ehal_bindings`, `loxone_blocks`, `loxone_inputs` / `loxone_outputs`, `swimspa_filter_bindings` → `alias_N`
- CSV / path-like fields → `fixture/<basename>`
- Street / address substrings rewritten to `House A`

Structural ids (battery / consumer / inverter ids) are kept so detect/apply logic stays realistic; only personally identifying strings and hub addresses are scrubbed.
