# Config migration orchestration — design draft

Backlog item: epic **ConfigMigration** (Version 2.7, [Backlog.md](Backlog.md)); formerly *Full orchestration of model version migration*.
Status: draft 2026-10-16, owner decisions from chat the same day (see §1 and §7). Backlog: epic **ConfigMigration** (Version 2.7); §8 is open for Version 2.8 only.

## 1. Owner decisions (2026-10-16)

| # | Topic | Decision |
|---|-------|----------|
| 1 | Scope | **Config JSON files only** (the 7 pack files: `config`, `backtesting_scenarios`, `components`, `deviation_rules`, `grid_fees`, `house_profiles`, `tariffs`). Runtime state / history / recorder are out of scope. |
| 2 | "Inform before" | **Release notes are enough.** No in-app update check. |
| 3 | Daemon | **`main.py` starts only after the migration is done.** |
| 4 | Safety net | **Backup of the old JSON files** — nothing else (no rollback tool, no downgrade support). |
| 5 | Version jumps | **Chain:** several steps run one after another. |
| 6 | Channels | Docker (Synology / Proxmox / greenfield), LoxBerry plugin, HA add-on (stable + pre-release). |
| 7 | v3 data set | From the private repo **Earnie-env-home** (§4). |
| 8 | Manual to-dos outside Earnie | **Text only**, unless an export mechanism already exists (e.g. Loxone VI/VO ZIP from the Signal list). |
| 9 | Rule | New `.cursor/rules/` rule + pointer in `CLAUDE.md`. |
| 10 | `grid_fees.json` | **Own format version**, independent of `earnie_data_model` (§3.7). |
| 11 | Chain start | **Data model 3.** Model 1 (and 2) = blocker "zu alt". |
| 12 | Edbert | Versioning of the tariff files is aligned with Edbert **now**, before the integration (next version); `user_tariffs.json` is coming as an additional tariff file (§3.7). |

## 2. Today (inventory)

- **Data-model gate:** `runtime_store/data_model.py` — `CURRENT_DATA_MODEL = 4`, `MIGRATABLE_DATA_MODELS = {3}`; `ensure_compatible()` rejects v3 with a CLI hint.
- **v3 → v4:** `runtime_store/migrate_v4.py` (`migrate_pack_docs`), CLI `scripts/migrate_data_model_v4.py`, also called from config-pack import (`runtime_store/config_pack.py`).
- **In-model one-shot migrations** (data model stays 4, each its own CLI, loaders fail loud with a script hint):
  `migrate_ehal_bindings`, `migrate_ess_bindings_once`, `migrate_inverters_once`, `migrate_conversion_efficiency_once`, `migrate_topology_once`, `migrate_pool_filter_milp`, `migrate_grid_fee_profile` (needs user input: `--area-id`, `--quarter-hour-meter`).
- **Silent migration in bootstrap (conflicts with the target):** `bootstrap._stamp_pack_jsons_to_current_data_model()` stamps every pack JSON `< 4` (and untagged ones, read as `1`) to 4 **without** migrating content; `_migrate_pack_legacy_keys()` runs parts of v3→v4 on every start. This bypasses `ensure_compatible` and the "ask first" target.
- **Startup path (all channels):** `docker/entrypoint.sh` → `scripts.bootstrap_runtime` → `scripts.run_streamlit` (`bootstrap.run()` → `load_config_or_exit()` → auto-start `main.py` when `EARNIE_AUTO_START_MAIN=1` → Streamlit). HA add-on `run.sh` and LoxBerry compose end in the same entrypoint. **Consequence:** an incompatible config aborts *before* Streamlit is up — there is no UI to guide the user.
- **Finding — `grid_fees.json` gets `earnie_data_model` by side effect** (bug entry in [Backlog-Bugfixes.md](Backlog-Bugfixes.md)): the seed `share/config/grid_fees.json` and the bootstrap copy carry no version key, but `build_config_pack_bytes()` stamps `earnie_data_model` on every pack file (`runtime_store/config_pack.py:60`), and the import stamps again via `stamp_data_model` + `write_json_dict` (`settings/json_io.py:56`, stamps every file it writes). After an export / import round trip the site copy carries `earnie_data_model: 4`; without one it carries nothing. Earnie's own loader (`data/grid_fees.py` `normalize_grid_fee_catalog`) ignores unknown root keys, so nothing breaks in Earnie — but Edbert's strict loader rejects the stamped file, and the file has two possible states. Target (§3.7): stamping is track-aware, tariff files never get `earnie_data_model`.
- **Version tracking:** `runtime_store/version_track.py` (`last_run_version`, downgrade warning).
- **Release notes:** `.github/release-notes/v<version>.md` per `docs/spec/release-checklist.md`.

- **Edbert** (`C:\Users\Test\Documents\Smarthome\edbert`, spec `docs/spec/tariff-format.md`, `docs/spec/architecture.md`), checked 2026-10-16:
  - reads `tariffs.json` (catalog) and `user_tariffs.json` (user file, editor-written, IDs `user_…`) — `src/edbert/store.py`; root keys are checked strictly (`ROOT_FIELDS`), `earnie_data_model`, `catalog_as_of`, `user_tariffs_as_of` are tolerated and ignored. Edbert has **no format version of its own**.
  - reads `grid_fees.json` (Earnie shape) — `src/edbert/gridfee.py` `parse_grid_fee_catalog`: `check_known(data, ("description", "rule_sets", "areas"))`. **A new version key in `grid_fees.json` is rejected by Edbert today.**
  - reads the `netznutzung` field of `house_profiles.json` strictly (`parse_grid_fee_config`, `CONFIG_FIELDS`) — an Earnie-model file, parsed by Edbert.
  - `catalog_as_of` / `user_tariffs_as_of` are **content dates** (data freshness), not format versions.

The backlog problem in one line: the integer data model does not capture the real structural changes (seven in-model steps), and add-on / LoxBerry users cannot run a CLI.

## 3. Target design

### 3.1 Step registry (`runtime_store/migration/`)

One ordered list of `MigrationStep` objects is the single source of truth:

```python
@dataclass(frozen=True)
class MigrationStep:
    id: str                    # stable, e.g. "dm4.inverters" / "dm5.<topic>"
    data_model: int            # model the step belongs to (result model)
    title_de: str              # UI text (German)
    files: tuple[str, ...]     # pack files read/written
    detect: Callable[[Docs], bool]          # pure: does this pack need the step?
    apply: Callable[[Docs, Answers], StepResult]  # pure: docs in → docs out
    questions: tuple[Question, ...] = ()    # user input the step needs
    manual_todos: Callable[[Docs, Docs], list[ManualTodo]] = ...  # text + optional export hook
```

- **Pure functions on in-memory docs** (no file I/O inside steps); existing migration functions move behind this interface, the one-shot CLIs become thin wrappers or are removed.
- **Chain:** the planner walks the registry in order; a step runs when `detect()` is true. Model-bump steps (v3→v4, future v4→v5 …) change `earnie_data_model`; the **legacy in-model steps** under model 4 stay detect-based (there is no record of which ran) and model 4 is **not** bumped for them (§7.2).
- **Future rule:** every new structural change bumps the data model and adds one step; no new in-model one-shots (see §6).
- **Answers / blockers:** steps that today raise on ambiguity (e.g. `migrate_v4` with several batteries, `grid_fee_profile` area) declare a `Question` instead; an unanswerable case is a **blocker** with German text, never a guess.

### 3.2 Planner + runner

- `plan_migration(config_dir) -> MigrationPlan` — read-only: from/to model, pending steps, questions, blockers, manual to-dos, per-file JSON diff preview (dry run on copies).
- `run_migration(config_dir, answers) -> MigrationReport`:
  1. load all pack JSONs, run the chain in memory;
  2. validate the result (`ensure_compatible`, JSON schema, the real loaders used by `load_config_or_exit`);
  3. **backup** the original files to `config/backups/pre-migration-dm<from>-dm<to>-<timestamp>/` (+ a small `manifest.json`: Earnie version, from/to, step ids);
  4. replace the files atomically (temp file + rename, same pattern as `config_pack.import_config_pack_bytes`);
  5. write `report.json` next to the backup (steps, manual to-dos) so the UI can show it again after restart.
  Any failure before step 4 leaves the config untouched.
- **Config-pack import** uses the same chain (today only v3→v4).
- **CLI:** `python -m scripts.migrate_config --config-dir PATH [--dry-run] [--answers answers.json]` — one entry point for devs / support; loader error messages point to the UI page and this CLI instead of individual scripts.

### 3.3 Startup gate

- **Bootstrap:** remove the silent stamping/partial migration of the live pack files (`_stamp_pack_jsons_to_current_data_model` for live files, `_migrate_pack_legacy_keys`). Stamping shipped `*.example.json` / `*.minimal.json` templates stays. A live pack file without `earnie_data_model` is a planner **blocker** (§7.1).
- **`scripts/run_streamlit`:** call `plan_migration()` before `load_config_or_exit()`. Pending plan → **migration mode**: skip `load_config_or_exit()`, skip `main.py` auto-start, start Streamlit with only the migration page (plus log / debug dump). No pending plan → as today.
- **`main.py` + `main_daemon.start()`:** hard guard — pending plan → refuse to start with a German message (fail loud, no fallback). Covers VS Code / manual starts.
- **Shadow mode (read-only shared config):** never migrates; refuses to start while Prod's config is pending.
- After a successful migration the wizard restarts the app state (fresh process or full reload) and starts `main.py` if `EARNIE_AUTO_START_MAIN=1` / add-on `auto_start_main` — otherwise offers the start button on *Optimierer-Dienst*.

### 3.4 Migration wizard (Streamlit, German)

1. **Hinweis:** "Earnie <new> braucht eine Anpassung deiner Konfiguration (Datenmodell 3 → 5)." Last run version from `last_run_version`, link to the release notes.
2. **Schritte:** list of pending steps (title, affected files), expandable JSON diff per file.
3. **Fragen:** inputs for steps with questions; blockers shown with what to fix by hand.
4. **Manuelle Schritte außerhalb von Earnie:** text (e.g. "Loxone Config: VO-Adresse X → Y ändern"); a download button only where an export exists today (Loxone VI/VO ZIP, HA YAML once Binding P5 ships).
5. **Button "Backup anlegen und migrieren"** → report: backup path, done steps, manual to-dos again as a checklist (checklist state is not persisted).
6. **Weiter:** reload → normal UI, daemon start as in §3.3.

### 3.5 Channels

All three channels share the entrypoint, so one implementation covers them. Per channel only check where the backup folder ends up and document it:
- **Docker:** `config` volume → `config/backups/…`.
- **HA add-on:** `/config` (addon_config) — visible in the HA file editor and included in HA backups.
- **LoxBerry:** plugin config dir; `postupgrade.sh` needs no change (only `plugin.env`).

### 3.6 Release notes ("inform before")

- Release checklist: new item — if the registry gained steps since the last tag, the release notes get a **"Migration"** section (what changes, questions the wizard will ask, manual to-dos, backup location, "kein Downgrade ohne Backup-Wiederherstellung").
- Helper: `python -m scripts.migration_release_notes --since <tag>` prints the section draft from the registry (titles, questions, manual to-do texts).
- Downgrade: `version_track` warning stays; an older Earnie rejects the newer data model with its existing error. Restoring the backup by hand is documented, not automated.

### 3.7 Version tracks and Edbert alignment

Two independent **version tracks**; each file belongs to exactly one:

| Track | Key | Files | Owner of the format | Migration steps live in |
|-------|-----|-------|---------------------|-------------------------|
| Earnie data model | `earnie_data_model` (int, today 4) | `config`, `components`, `house_profiles`, `backtesting_scenarios`, `deviation_rules` | Earnie | Earnie registry |
| Tariff format | `tariff_format` (int, starts at 1) | `grid_fees.json` now; `tariffs.json` + `user_tariffs.json` with the Edbert integration | Edbert (`docs/spec/tariff-format.md`) | Edbert library (`edbert.api`), called by the Earnie registry |

- **Why one tariff track instead of one version per file:** all three files follow the same Edbert spec and are read by the same library; a format change usually touches catalog and user file together. `grid_fees.json` is the first file on the track, the others join at integration time. (Key name `tariff_format` is a proposal — neutral, no product name in the data, so the Edbert product without Earnie uses the same files.)
- **Asynchronous:** a tariff-format bump never bumps `earnie_data_model` and vice versa. The registry holds steps per track; the planner runs Earnie-track steps first, then tariff-track steps (tariff files do not depend on Earnie files; if that ever changes, the step declares it).
- **Steps owned by Edbert:** tariff-track steps are pure functions in the Edbert library (`edbert.api.plan_migration` / `migrate`), so the Edbert product can migrate its files without Earnie. Earnie's registry wraps them as `MigrationStep`s (same wizard, same backup). Until the integration, the only tariff-track step (`grid_fees.json` untagged → `tariff_format: 1`) lives in Earnie and moves to Edbert with the integration.
- **Content dates stay separate:** `catalog_as_of` / `user_tariffs_as_of` keep meaning "data as of"; they are never used for format decisions.
- **`tariffs.json` today** carries `earnie_data_model: 4`. It stays on the Earnie track until the integration; the integration release then has one step that removes `earnie_data_model` from `tariffs.json` and sets `tariff_format`. After that, Edbert accepts only `tariff_format` on normal load; the old `earnie_data_model` key is read only by that migration step (no dual-read).
- **`user_tariffs.json`** is born with `tariff_format` from its first write (editor), joins `PACK_JSON_FILES`, backup and the planner at the same time — no untagged phase.
- **`netznutzung` in `house_profiles.json`** stays on the Earnie track (it is a house-profile field). Today it holds more than the grid selection: with `area_id: null` it carries own grid-fee definitions (`base_cent_kwh`, `rules`, `holidays`, `extra_holiday_dates`, later `capacity_charges`) — tariff format inside an Earnie file, parsed strictly by Edbert. Until the split below, a shape change needs an Earnie data-model bump **and** a matching Edbert release; the rule (§6) says so.
- **Target: grid selection in Earnie, grid definitions in the tariff files** (owner decision 2026-10-16, variant 2). The tariff files may hold grid areas for many grids; Earnie's config only says which grid the house uses.
  - `netznutzung` keeps only the selection (`area_id`) and the house-side metering facts (`power_metering`, `quarter_hour_meter`, `include_status` — exact split decided with Edbert).
  - Own grid fees (today `area_id: null` + own values) become a **user grid area** in a tariff-track file (analogous to `user_tariffs.json`: IDs `user_…`, written by the editor; file name / whether it is a section of an existing file decided with Edbert); `netznutzung.area_id` then points to it.
  - **Timing:** with the Edbert integration in **Version 2.8**. Requires a **migration** in that release, two coordinated steps in one run: Earnie track (`house_profiles.json`: move own values out, set `area_id` to the new user area; data-model bump) and tariff track (create the user area in the tariff file). Both run in the same wizard and backup; the Earnie step is planned before the tariff step and passes the extracted values on (declared dependency, §3.7 "Asynchronous").
  - Until 2.8 nothing changes in the data; the framework from this item must already support a step that writes to both tracks (P1 test with a synthetic `area_id: null` profile).
- **Required Edbert changes (Edbert backlog, before this item's P1 lands in a release):**
  1. `parse_grid_fee_catalog`: accept `tariff_format` in the root; reject unknown versions with a coded error (`FORMAT_UNSUPPORTED`).
  2. `store.py` `ROOT_FIELDS`: add `tariff_format` (for the integration); spec section "2. Files" documents the key and the track.
  3. `edbert.api`: `plan_migration` / `migrate` for tariff-track files (pure, docs in → docs out, questions / blockers like §3.1).
  4. Edbert `docs/spec/tariff-format.md`: version track section (key, current value, compatibility rule).

## 4. Regression data set (v3 → current)

- Source: private repo **Earnie-env-home** (`github.com/JochenTCC/Earnie-env-home`, local clone `C:\Users\Test\Documents\Smarthome\Earnie-env-home`), folder `config/`. Never commit raw content from it to the public repo.
- History found 2026-10-16 (14 commits, `earnie_data_model` per live pack file):

  | Commits | Date | Data model | Note |
  |---------|------|-----------|------|
  | `26c9daf` … `d6388e2` | 2026-07-19 … 07-21 | **1** | initial site pack; not migratable today (`MIGRATABLE_DATA_MODELS = {3}`) |
  | `1cbee2f`, `7269b26` | 2026-10-02 … 10-03 | **3** | v3 snapshots for the chain test |
  | `760ab99` … `6f8dfaf` | 2026-10-07 … 10-14 | **4** | in-model steps visible in the messages: plant Quellenwahl drop (`66b31de`), Loxone Merker names cleared (`968e4b6`), inverter model + `netznutzung` (`49fc6a2`), conversion efficiency (`c0cd597`), `regulates_on` / grid meter flags (`cf1454b`), inverter limits + topology (`a9f0dc4`) |

  `tariffs.json` is not in the repo (deliberately excluded); `grid_fees.json` exists from `49fc6a2` on and carries **no** `earnie_data_model` (see §8). `config/uploads/` holds CSVs with real names / addresses — not part of the fixtures.
- Extract snapshots of the 7 pack files at the commits **just before** each structural change (one per registered step + the oldest v3 state); helper script walks `git log -- config/*.json` of that repo.
- Scrub before commit (names, IDs, location, IPs, tokens, HA URLs, Loxone addresses → stable aliases; same bar as the R0 golden scrub).
- Fixtures: `tests/fixtures/migration/<snapshot>/` + golden of the migrated result.
- Tests:
  - full chain from every snapshot → result passes `ensure_compatible`, schema and real loaders;
  - golden diff of the migrated output;
  - idempotency (second run = no pending steps, no file change);
  - per-step unit tests (detect / apply / questions / blockers);
  - meta test: every registered step is covered by at least one fixture;
  - backup + atomic write (failure injection → original files unchanged);
  - startup gate (pending → no `load_config_or_exit`, no daemon auto-start; `main.py` guard).
- Optional: short SE/backtest run on a migrated snapshot vs. the hand-migrated Prod config (same results) — link to epic **Regression** if cheap.

## 5. Phases (epic **ConfigMigration**, Version 2.7)

Registered in `roadmap-nomenclature.mdc` (2026-10-16; the name `Migration` is taken by the file-structure plan `MIGRATION.md`). **2.7 scope:** v3 → v4 + legacy in-model steps on the Earnie track only. The tariff track (§3.7: `tariff_format`, `grid_fees.json` step, Netznutzung split) moves to the Edbert integration in **Version 2.8**; until then `grid_fees.json` stays untagged and is exempt from the untagged blocker (§7.1), and the stamping bug ([Backlog-Bugfixes.md](Backlog-Bugfixes.md)) is fixed first.

| Phase | Content | Depends on |
|-------|---------|------------|
| **P0** | Inventory of the existing steps (order from git history, inputs, idempotency, loader rejections); fixture extraction + scrub from Earnie-env-home (§4) | §8 decisions |
| **P1** | Registry, planner, runner (backup + atomic write), CLI; port v3→v4 and the 7 legacy steps; config-pack import on the chain; tests from §4 | P0 fixtures (tests can start with synthetic docs) |
| **P2** | Startup gate: bootstrap without silent migration, migration mode in `run_streamlit`, `main.py` / daemon guard, Shadow handling, loader messages | P1 |
| **P3** | Wizard UI (§3.4), AppTest coverage | P2 |
| **P4** | Process: rule (`.cursor/rules/config-migration.mdc`), `CLAUDE.md` pointer, release checklist item + notes helper, German user docs (`docs/einrichtung/betrieb.md` → "Update und Migration"), spec `docs/spec/config-migration.md` | P1–P3 |

## 6. Rule content (for P4)

- Any structural change of a persisted config JSON → bump the version of **its track** (`earnie_data_model` or `tariff_format`, §3.7) + register a `MigrationStep` + fixture + release-notes "Migration" section + user docs.
- Tariff-track formats are owned by Edbert: change the Edbert spec and library first; Earnie only wraps the step.
- A change of a file that the other side parses strictly (`netznutzung` in `house_profiles.json`, `grid_fees.json`) needs a matching release on both sides.
- No silent migration on load or in bootstrap; loaders fail loud and point to the wizard.
- No new standalone `migrate_*_once` scripts.
- Ambiguity → `Question` or blocker, never a default (`no-implicit-fallbacks.mdc`).

## 7. Follow-up decisions (2026-10-16)

1. **Untagged files** (no `earnie_data_model`): **blocker** ("Version unbekannt") — no guessing, no stamping. Bootstrap stops reading them as `1`. Re-check after P0 only if the v3 history shows a large share of untagged files.
2. **Legacy in-model steps:** **stay detect-based under data model 4** — no bump to 5 when the framework lands. Data-model bumps start with the next structural change (rule §6).
3. **Backup retention:** keep all, no automatic deletion; docs explain how to remove old backups.
4. **Migration mode UI:** only the wizard (plus log / debug dump), no other pages.
5. **`grid_fees.json`:** own format version on the tariff track (§3.7), independent of `earnie_data_model`. The untagged file is migrated by a tariff-track step to version 1 (Version 2.8, with Edbert); so §7.1 (untagged = blocker) applies to `grid_fees.json` only after that step exists — in 2.7 it is exempt.
6. **Chain start:** data model 3. Models 1 and 2 are a blocker ("Konfiguration zu alt — bitte Support kontaktieren / neu einrichten"); the July 2026 v1 snapshots in Earnie-env-home are not used as fixtures.
7. **Netznutzung split (variant 2):** grid selection stays in Earnie's `house_profiles.json`, grid definitions (incl. own grid fees) move to the tariff files; done with the Edbert integration in Version 2.8 with a migration step pair (§3.7).

8. **Epic + 2.7 scope:** epic `ConfigMigration` P0–P4 in Version 2.7 (Earnie track only); tariff track with the Edbert integration in Version 2.8 (§5).

## 8. Open points (for Version 2.8 — not blocking 2.7)

1. **Key name** `tariff_format` (proposal, §3.7) — confirm or rename; it must be fixed in Edbert's spec before the first file carries it.
2. **One tariff track for all three tariff files** (proposal) vs. one version per file.
3. **Order with Edbert:** `tariff_format` is written in two places — by the maintainer into the seed `share/config/grid_fees.json` (repo), and by the migration step into the site copy of existing installs (`earnie_env/config/grid_fees.json`, add-on `/config/grid_fees.json`; bootstrap never overwrites it). There is no runtime coupling to Edbert yet (only the Edbert CLI `--grid-catalog` and the coming integration), so the risk is small: Edbert's loader must accept `tariff_format` no later than the Earnie release that ships the seed with the key and the migration step — simplest in the same period. Add the Edbert items (§3.7) to the Edbert backlog now?
