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

**Pack files (Earnie track, 2.7):** `config.json`, `components.json`, `house_profiles.json`, `backtesting_scenarios.json`, `deviation_rules.json`, and currently `tariffs.json` (until the Edbert integration moves it).

| Track | Key | Owner | 2.7 status |
|-------|-----|-------|------------|
| Earnie data model | `earnie_data_model` (int, today 4) | Earnie registry | Active |
| Tariff format | `tariff_format` (int) | Edbert | **Deferred to Version 2.8** |

Until 2.8, `grid_fees.json` stays untagged and is **exempt** from the untagged blocker; do not stamp it with `earnie_data_model`.

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

## 7. Out of scope (Version 2.8)

- Tariff track key `tariff_format`, `grid_fees.json` versioning, Netznutzung split — with Edbert integration (draft §3.7 / §8).
