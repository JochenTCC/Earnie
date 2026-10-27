# Config migration — guided pack JSON chain

**Status:** implemented (ConfigMigration P0–P4, 2026-10-16)
**Date:** 2026-10-16
**Backlog:** epic **ConfigMigration** (Version 2.7 → `backlog/Backlog-Erledigt.md`)
**Related:** design draft [`backlog/Config-Migration-Draft.md`](../../backlog/Config-Migration-Draft.md), inventory [`backlog/Config-Migration-Inventory.md`](../../backlog/Config-Migration-Inventory.md), package `runtime_store/migration/`, wizard `ui/pages/page_config_migration.py`, CLI `python -m scripts.migrate_config`, rule `.cursor/rules/config-migration.mdc`, release checklist [release-checklist.md](release-checklist.md)

This document is the living contract. Design history and open 2.8 points stay in the draft.

## 1. Problem and goal

Earnie’s config pack JSON can change shape across releases. Operators on Docker, LoxBerry, and the HA add-on must be guided after an update: **ask first**, show pending steps and questions, back up the old pack files, then write. `main.py` / the daemon must not start while a migration is pending. Runtime state, history, and recorder are out of scope.

“Inform before” = **release notes** only (no in-app update check).

## 2. Scope and tracks

**Pack files (Earnie track):** `config.json`, `components.json`, `house_profiles.json`, `backtesting_scenarios.json`, `deviation_rules.json`.

**Pack files (tariff track, Edibert P2, 2.8):** `tariffs.json`, `user_tariffs.json`, `grid_fees.json`, `user_grid_fees.json` (`runtime_store.data_model.TARIFF_TRACK_FILES`, equal to `edibert.api.TARIFF_TRACK_FILES`; shipped templates `tariffs.example.json` / `tariffs.minimal.json` belong to the same track).

| Track | Key | Owner | Status |
|-------|-----|-------|------------|
| Earnie data model | `earnie_data_model` (int, today 5) | Earnie registry | Active |
| Tariff format | `tariff_format` (int, today 1) | Edibert (`edibert.api.plan_migration` / `migrate`); Earnie wraps the step | Active since 2.8 |

Tariff-track files are never stamped with `earnie_data_model` (`settings/json_io.py`, `config_pack.py`, bootstrap template stamping skip them). An untagged tariff-track file is the pre-format-1 state: it is not a level blocker, `tf1.tariff_format` migrates it, and the startup gate stays closed until it ran. Loaders require the current `tariff_format` (`runtime_store.data_model.ensure_tariff_format`, Edibert `FORMAT_MISSING` / `FORMAT_UNSUPPORTED`).

Chain start: data model **3**. Models **1** and **2** are blockers (“Konfiguration zu alt”). Untagged Earnie-track files are blockers (“Version unbekannt”) — no guessing, no silent stamp.

## 3. Architecture (as shipped)

```text
plan_migration / gate  →  migration mode UI (wizard only)
run_migration          →  validate → backup → atomic replace → report.json
scripts.migrate_config →  same planner / runner for support
```

### 3.1 Registry

Ordered `MigrationStep` list in [`runtime_store/migration/registry.py`](../../runtime_store/migration/registry.py): pure `detect` / `apply` on in-memory docs, optional `Question`s, blockers, `manual_todos` (computed from before/after docs). Legacy in-model steps under model 4 stay **detect-based** (model is not bumped for them). Future structural changes bump the track version and add a step — no new standalone `migrate_*_once` scripts.

Optional `detect_on_start` gates a step on the docs the chain **started** from (`types.step_is_pending`): `dm4.loxone_binding_names` (2.7.q Q8 Merker names) only runs when the chain starts at model 3, so the required question (`loxone_binding_names.keep`: `Behalten` / `Leeren`) is asked once and never again on model 4 — also when the user keeps the names. It runs after `dm4.ess_bindings` (names first move onto the batteries), only for `ehal.backend` Loxone, and clears plant, consumer, battery, inverter and PV values (keys stay as activation flags). Rationale: names are functionally tolerated (writes publish qualified IDs, reads map Merker → ID via the binding index) and kept names show up as „Bisheriger Name“ in the Loxone signal-list export.

`dm4.ha_sign` (issue #56) works the same way for a leftover `ehal.ha.sign` on the HA backend (`ha_sign.remove`: `Behalten` / `Entfernen`): in 2.7 `sign` is applied on top of the HA push, so a 2.6 entry flips already EHAL-signed values twice. `Entfernen` empties `ehal.ha.sign` and leaves a manual to-do to check Live-Lesen against the live power line.

Required `choice` questions start empty in the wizard (no implicit default); the runner rejects missing answers before any write.

Questions that depend on the docs (one per house profile or tariff) come from `MigrationStep.questions_for(docs)` and are collected along the dry-run chain (`types.step_questions`). `kind="number"` questions carry an optional `default` (suggestion): the wizard shows it as placeholder plus a **Vorschlag übernehmen** button and never writes it unasked; the CLI prints it.

**Data model 5 (Edibert P2):** `dm5.netznutzung_split` (after every dm4 step) reduces the house-profile `netznutzung` to `area_id` (required) and the metering facts, turns an own base price into the user grid area `user_<profile_id>`, asks (`dm5.netznutzung_split.area_id:<profile_id>`, choice of catalog / user areas or `user_<profile_id>` with 0 ct) when a profile has neither, and stamps every Earnie-track file to 5. It hands the new areas to `tf1.tariff_format` through the in-memory key `types.HANDOFF_USER_GRID_AREAS` (never written; excluded from diffs). `tf1.tariff_format` runs last: a thin wrapper around `edibert.api.migrate` (tag the four files, drop `earnie_data_model` from `tariffs.json`, write the handed areas into `user_grid_fees.json`, VAT question `vat_percent:<import|export>:<tariff_id>` for every user tariff without a rate). Both steps run in the same wizard run with one backup. `dm5.scenario_feed_in` (Edibert P3b, decision D2) runs between them: scenarios with the flat feed-in keys `k_push_cent` / `feed_in_mode` / `monthly_fixed_feed_in_rates` lose them; without an export tariff it asks `dm5.scenario_feed_in.export_tariff_id:<scenario_id>` (`__user_fixed__` = Eigener Festpreis with the old `k_push_cent`, suggested for `fixed`, or a catalog / user tariff), without an import tariff `dm5.scenario_feed_in.import_tariff_id:<scenario_id>` (suggestion: the live scenario's import tariff, which priced it so far).

**Archived configs:** recorder replay (`runtime_store.recorder_replay`) and config-pack import run the full chain in memory without answers (`runner.migrate_docs_unattended`); a snapshot that needs an answer or hits a blocker fails with the reason. Regression goldens therefore keep their recorded snapshots unchanged.

### 3.2 Planner and runner

- `plan_migration(config_dir)` — read-only plan: from/to model, pending step ids, questions, blockers, manual to-dos, per-file diffs.
- `run_migration(config_dir, answers)` — apply chain in memory → validate with real loaders → backup under `config/backups/pre-migration-dm<from>-dm<to>-<UTC>/` (`manifest.json`) → atomic replace → `report.json` beside the backup. Failure before replace leaves the live pack untouched.
- Config-pack import uses the same chain.

### 3.3 Startup gate

[`runtime_store/migration/gate.py`](../../runtime_store/migration/gate.py): pending plan or level blockers → Streamlit **migration mode** (skip `load_config_or_exit`, no daemon auto-start); `main_daemon` / Shadow refuse with German messages. Bootstrap does **not** silently migrate or stamp live pack files (templates / greenfield create only).

### 3.4 Wizard

German UI in `ui/pages/page_config_migration.py`: hint → steps/diffs → questions → blockers → manual to-dos → **Backup anlegen und migrieren** → report → **Weiter zur App** (optional `maybe_auto_start`). AppTest under `tests/apptest/`.

### 3.5 CLI

```text
python -m scripts.migrate_config --config-dir PATH [--dry-run] [--answers answers.json]
```

## 4. Channels and backup locations

Same entrypoint on all channels. Documented for operators in [`docs/einrichtung/betrieb.md`](../einrichtung/betrieb.md) (Update und Migration):

| Channel | Config root | Backup folder |
|---------|-------------|-----------------|
| Docker | host `earnie_env/config/` | `…/config/backups/pre-migration-…/` |
| LoxBerry | plugin `…/earnie_env/config/` | same relative `backups/` |
| HA add-on | `/config/` (`addon_configs/…`) | `/config/backups/…` (also in HA backups) |

Retention: keep all; deletion is manual. No automated downgrade — restore a backup by hand.

## 5. Release notes process

When the registry gains steps since the previous tag, release notes must include a German **`## Migration`** section (checklist: [release-checklist.md](release-checklist.md) §1).

Draft helper:

```text
python -m scripts.migration_release_notes --since <previous-tag>
```

Diffs step ids at `--since` (git) against the current registry; prints boilerplate (backup path, no downgrade) plus new steps (`id`, `title_de`, questions, files). Manual to-dos are noted as computed at migrate time.

## 6. Maintainer rule

Any structural pack JSON change → bump the owning track + register a step + fixture + Migration release-notes section + user docs. See `.cursor/rules/config-migration.mdc` and `CLAUDE.md` Area notes.

## 7. Out of scope

- Later tariff-format versions (`tariff_format` 2+): Edibert adds the step to its migration API first, Earnie's `tf1.tariff_format` wrapper picks it up.
