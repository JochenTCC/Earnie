# Config migration inventory (P0)

Companion to [`Config-Migration-Draft.md`](Config-Migration-Draft.md). Documents today's v3→v4 gate and the seven in-model one-shots for the **ConfigMigration** epic. Fixtures: [`tests/fixtures/migration/`](../tests/fixtures/migration/).

**Chain start:** `earnie_data_model` **3**. Models **1** and **2** = blocker ("zu alt") — not migratable; July 2026 v1 in Earnie-env-home is only a nest source for `v3_pre_ehal`.

**Pack files (7):** `config.json`, `backtesting_scenarios.json`, `components.json`, `deviation_rules.json`, `grid_fees.json`, `house_profiles.json`, `tariffs.json` (`runtime_store/config_pack.py` `PACK_JSON_FILES`).

## Suggested registry order

Site history (Earnie-env-home) + code dependencies:

1. `dm4.ehal_bindings` (legacy nests; already done on this site before first v3 commit)
2. `dm4.v3_to_v4` (model stamp + scenarios `battery_id` + plant ESS phase-1 + embedded inverter migrate)
3. `dm4.ess_bindings` (residual plant-flat ESS + Quellenwahl phase-2; often partly done inside v3→v4)
4. `dm4.inverters` (detect-based if still needed after v3→v4)
5. `dm4.conversion_efficiency` (needs `inverters[]`)
6. `dm4.topology` (`regulates_on` + `plant.grid_meter`)
7. `dm4.pool_filter` (independent; still pending on this site)
8. `dm4.grid_fee_profile` (independent; needs user answers)

`pool_filter` / `grid_fee_profile` have no hard dependency on the inverter chain; planner may run them whenever `detect` is true. Prefer running them after the model is 4 so loaders that assume dm4 are usable.

## Step table

| Step id (proposed) | CLI | Core module(s) | Files | Detect | Idempotent | Dry-run | Loader rejection | Questions / blockers | Earnie-env-home “before” |
|---|---|---|---|---|---|---|---|---|---|
| `dm4.v3_to_v4` | `scripts.migrate_data_model_v4` | `runtime_store/migrate_v4.py` (`migrate_pack_docs`); gate `runtime_store/data_model.py` | All present pack JSONs | `needs_v4_migration`: `earnie_data_model == 3` | Re-run stamps/normalizes; scenarios still fix stray `battery_id` | `--config-dir` `--dry-run` | `ensure_compatible` → `DataModelError` (used on config-pack import; **not** on normal startup today — bootstrap stamps instead) | `MigrateV4Error`: 0 / >1 batteries for plant-flat ESS; 0 / >1 physical `standby_backup` for Quellenwahl | `7269b26` → fixtures `v3_last` (blocker), `v3_single_battery` (happy path) |
| `dm4.ehal_bindings` | `scripts.migrate_ehal_bindings` | `house_config/ehal_bindings.py` (`ensure_migrated`, `migrate_loxone_blocks_to_plant`, …) | `house_profiles.json`; optional `config.json` | Non-empty `config.loxone_blocks`; consumer legacy nests (`loxone_inputs`/`outputs`, `thermal_control.loxone`, schedule `loxone`, non-ehal `swimspa_filter_bindings`); flat `ehal.ha.entities`; residual plant-flat ESS | Yes when nests stripped / entity-scoped | `--path` [`--config`] `--dry-run` | `ensure_migrated` raises on blocks / residual flat ESS (UI / CLI path; cold start does not always call it) | Manual if blocks present without CLI; points at `migrate_ess_bindings_once` for plant-flat ESS | **Reconstructed** `v3_pre_ehal` (nests from `26c9daf`, stamped dm3) — no dm≥3 pre-state in history |
| `dm4.ess_bindings` | `scripts.migrate_ess_bindings_once` | `runtime_store/migrate_v4.py` (`migrate_plant_ess_to_components`, `migrate_plant_source_select_to_standby`) | `house_profiles.json`, `components.json` | Plant-flat ESS keys (phase-1); plant `set_ess_source_select` (phase-2) | Yes when no flat ESS / Quellenwahl left | `--config-dir` `--dry-run` | Via `ensure_migrated` residual flat ESS; CLI `MigrateV4Error` / exit | Multi-battery / multi-standby → blocker / question | Phase-1: `7269b26`; phase-2: `760ab99` → `v4_pre_quellenwahl` |
| `dm4.inverters` | `scripts.migrate_inverters_once` | `house_config/migrate_inverters.py`; detect `house_config/inverter.py` `needs_inverter_migration` | `components.json` | Any `batteries[].kind`; or assets without `inverters` / `inverter_id` (virtual PS exempt) | Yes when `inverters[]` present and no `kind` | `--config-dir` `--dry-run` | `reject_if_needs_inverter_migration`; `battery_kind.normalize_battery_kind` | Deterministic (`wr_main` / `wr_{bat_id}`) | `515ea9a` → `v4_pre_inverter_gridfee` |
| `dm4.conversion_efficiency` | `scripts.migrate_conversion_efficiency_once` | `house_config/migrate_conversion_efficiency.py` | `components.json` | Any inverter missing `efficiency` | Yes when every inverter has `efficiency` | `--config-dir` `--dry-run` | `reject_if_needs_conversion_efficiency_migration`; `normalize_inverter` | Default η_inv `0.97`; η_batt = η_old / η_inv | `49fc6a2` → `v4_pre_conversion` |
| `dm4.topology` | `scripts.migrate_topology_once` | `house_config/migrate_topology.py` | `components.json`; `house_profiles.json` if present | House battery missing `regulates_on`; and/or incomplete `plant.grid_meter` | Per half (components / profiles) | `--config-dir` `--dry-run` | `reject_if_needs_topology_migration`; live `_assert_grid_meter` | CLI prints operator CONFIRM text after seeding `true`/`true` | `c0cd597` → `v4_pre_topology` |
| `dm4.pool_filter` | `scripts.migrate_pool_filter_milp` | `house_config/migrate_pool_filter.py` | `house_profiles.json`; optional `deviation_rules.json` | Incomplete `pool_filter` MILP fields; `swimspa_filter_bindings` nests; deviation scope `swimspa_filter` | Yes when promoted + nests stripped | `--path` [`--deviation`] `--dry-run` | **No dedicated fail-fast loader**; warnings + exit `1` if warnings | Soft dual-path still exists in places | Any v3+ (never applied on this site); covered by `v3_last` / `v3_single_battery` |
| `dm4.grid_fee_profile` | `scripts.migrate_grid_fee_profile` | same script (`migrate_document`) | `house_profiles.json` | Profile has `netznutzung_arbeitspreis_cent_kwh` | Yes when legacy key gone | `--path` `--dry-run` [`--area-id`] [`--quarter-hour-meter`] | `profiles_store` raises with migrate hint | **Questions:** `--area-id`, `--quarter-hour-meter` (else `area_id: null` + old price as `base_cent_kwh`); dual key → raise | `515ea9a` → `v4_pre_inverter_gridfee` |

## Overlap / pitfalls

- **v3→v4 embeds** inverter migrate + plant ESS phase-1. Legacy steps stay detect-based under model 4; detect must stay precise so already-migrated packs are no-ops.
- **Bootstrap conflict (P2):** `_stamp_pack_jsons_to_current_data_model` stamps `< 4` / untagged to 4 without content migrate; `_migrate_pack_legacy_keys` runs parts of v3→v4 on every start. Bypasses `ensure_compatible` and “ask first”.
- **`grid_fees.json`:** untagged in 2.7; exempt from untagged blocker until tariff track (`tariff_format`) in 2.8. Stamping bug tracked in `Backlog-Bugfixes.md` (not this P0).
- **Uneven fail-fast:** inverters / η / topology / grid_fee / ESS (via `ensure_migrated`) are loud; **pool_filter** and **loxone_blocks** are weaker on cold-start load.

## Fixture map (P0)

| Folder | Source SHA / method | Primary coverage |
|---|---|---|
| `v3_last/` | `7269b26` scrubbed, 3 batteries kept | v3→v4 + ESS multi-battery **blocker**; pool_filter still pending |
| `v3_single_battery/` | same + slice to one battery | happy-path chain start |
| `v3_pre_ehal/` | nests from `26c9daf` on dm3 skeleton; ESS-mapped `loxone_blocks` + plant-flat ESS stripped | `migrate_ehal_bindings` |
| `v4_pre_quellenwahl/` | `760ab99` | ESS Quellenwahl phase-2 |
| `v4_pre_inverter_gridfee/` | `515ea9a` | inverters + grid_fee |
| `v4_pre_conversion/` | `49fc6a2` | conversion_efficiency |
| `v4_pre_topology/` | `c0cd597` | topology |

Goldens of migrated results → **P1**. Re-extract: `python -m scripts.extract_migration_fixtures --env-home <Earnie-env-home>`.

## Earnie-env-home chronology (reference)

| SHA | Date | dm | Note |
|---|---|---|---|
| `26c9daf` | 2026-07-19 | 1 | Initial pack; nest source only |
| `7269b26` | 2026-10-03 | 3 | Last v3 |
| `760ab99` | 2026-10-07 | 4 | First v4; plant Quellenwahl still present |
| `66b31de` | 2026-10-10 | 4 | Drop plant Quellenwahl |
| `515ea9a` | 2026-10-11 | 4 | Pre inverter + `netznutzung` object |
| `49fc6a2` | 2026-10-12 | 4 | Inverters + `netznutzung`; adds `grid_fees.json` |
| `c0cd597` | 2026-10-12 | 4 | Inverter `efficiency` split |
| `cf1454b` | 2026-10-13 | 4 | `regulates_on` + `grid_meter` |
