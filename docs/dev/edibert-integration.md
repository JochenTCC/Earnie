# Edibert integration

Decision record for the Earnie epic *Edibert* (backlog `backlog/Backlog.md`, Version 2.8). Architecture: development document §9.3, Edibert `docs/spec/architecture.md`.

## P0 — Packaging and license (decided 2026-10-26)

### Packaging

**Decision:** Earnie pins Edibert to a **git tag archive** of the public repo [`JochenTCC/Edibert`](https://github.com/JochenTCC/Edibert):

```toml
"edibert @ https://github.com/JochenTCC/Edibert/archive/refs/tags/v0.1.0.zip"
```

| Option | Verdict |
| --- | --- |
| Git tag archive (chosen) | Reproducible, no `git` needed in the slim image, no release upload. |
| PyPI release | Cleanest, but every Edibert state needs a public release (build, upload, token). Name `edibert` is still free on PyPI; switch later if Edibert gets external users. |
| Vendored copy | No network in the build, but duplicated code and a sync step on every Edibert change. Rejected. |

**Versioning:** Edibert's first tag is `v0.1.0`, cut after Edibert `0.1.f` (library API `edibert.api`). The letters `0.1.a` … `0.1.h` stay backlog phases; later tagged states are `0.1.1`, `0.1.2`, … Earnie raises the pin when a phase needs a newer Edibert.

**Where the pin acts:**

- `pyproject.toml` `dependencies` is the single source. `requirements.txt` is `.` and the Docker deps stage reads the list from `pyproject.toml`, so the release image installs Edibert with no Dockerfile change.
- Home Assistant add-on: wraps the release image (`packaging/homeassistant-addon/*/Dockerfile`), so it gets Edibert through the image. No add-on change.
- Wheel-only installs (`--only-binary=:all:` in `.devcontainer/post-create.sh`, `.github/workflows/sonarcloud.yml`, `ui-tests.yml`) add `--no-binary=edibert`, because the tag archive is a source distribution.
- Local side-by-side development: `python -m pip install -e ..\edibert` over the pin (`DEVELOPER.md`).
- Edibert brings `holidays` and `jsonschema` (already an Earnie dependency). The `mqtt` and `ui` extras are not installed; Earnie uses only the library.

### License

- Edibert: PolyForm Noncommercial 1.0.0. Earnie: own source-available, non-commercial license (`LICENSE.md`). Same copyright holder.
- Both allow only non-commercial use, so shipping Edibert inside the Earnie image matches Earnie's own terms. PolyForm requires that recipients get the license terms and the `Required Notice` line; both travel in Edibert's distribution metadata (`LICENSE`, `NOTICE` in `dist-info`), checked by `tests/test_edibert_dependency.py`.
- Commercial licenses for Earnie (`LICENSE.md` § 2.3) need a matching separate grant for Edibert. Same holder, so this is a contract matter, not a conflict.
- Open: name Edibert as a bundled third-party component in `LICENSE.md` / `README.md` (maintainer decision; legal wording).

### Done check

- [x] Pin in `pyproject.toml`; wheel-only install lines adapted; `DEVELOPER.md`.
- [x] Smoke test `tests/test_edibert_dependency.py` (import, installed version not behind the pin, LICENSE/NOTICE shipped).
- [x] Edibert `v0.1.0` tagged and pushed (Edibert `0.1.f`, 2026-10-26).
- [x] Docker build green with the tag archive (`docker build -f docker/Dockerfile .`, 2026-10-26): the image has `edibert` 0.1.0, `edibert.api` (API version 1), LICENSE/NOTICE in `dist-info`.

## P1 — Data files and read-only coexistence (2026-10-26)

Earnie **loads** the tariff files through `edibert.api` but **still prices with its own engine** (`data/tariff_pricing.py`, `data/grid_fees.py`) until P3b.

### What changed

- **One access module:** `house_config/edibert_tariffs.py` is the only caller of `edibert.api`. Every `EdibertError` becomes an `EdibertLoadError` (a `ValueError`) with a German message; `code` and `params` stay on the exception.
- **`user_tariffs.json`** lives next to `tariffs.json` (`runtime_store.persist_paths.user_tariffs_path_for`, no own ENV override). Every caller that passes a `tariffs_path` therefore sees the user file of the same directory: live, SE, recorder replay (`config/user_tariffs.json`), tests with fixture dirs. A missing file means no user tariffs.
- **Read path:** `house_config.tariffs_store.load_tariffs_document` merges the user file into the normalized catalog. Edibert checks the user file strictly first (prefix, unknown fields, duplicates); then each entry runs through Earnie's own normalizer and gets `origin: user`. Catalog entries keep their exact normalized shape (no `origin` key), so the goldens are unaffected.
- **E1, user tariffs Earnie cannot price:** `engine_pending_fields` is an allowlist. Every field that is neither priced by Earnie nor display-only (`requires`, `behavior_notes`, `source`, `last_verified`, `individual`, `applies_to`, `$comment`) marks the tariff as pending; `holidays` / `extra_holiday_dates` count only together with non-empty `rules`. Pending tariffs are listed in the Szenarienkonfigurator (label suffix *Benutzertarif, erst ab Engine-Umstellung*), `resolve_*_tariff_into_settings` raises, and the tariff plausibility reports scenarios that reference one.
- **E2, tariff track:** `user_tariffs.json` is untagged and exempt like `grid_fees.json` (`runtime_store.data_model.TARIFF_TRACK_FILES`): never stamped with `earnie_data_model`, in `PACK_JSON_FILES`, debug dumps, recorder snapshots and plan-input mtimes. P2 tags all three tariff files with `tariff_format` (Edibert must add the key to `ROOT_FIELDS` first).
- **E3, `region`:** optional field in the house profile (schema + profile editor, select per country, labels for AT states). Additive, so no migration step. Validated against the `holidays` calendar on load (unknown = error); absent stays absent (the normalized profile only carries the key when set). `holidays` is a direct dependency now (same package Edibert prices with).
- **Checks:** `collect_tariff_plausibility_errors(..., with_edibert=True)` loads catalog + user file, `grid_fees.json` and the pricing context of every house profile through Edibert. Used by the worker start check and `python -m scripts.validate_tariffs`; backtesting gates stay as before.

### Done check

- [x] All 50 catalog tariffs (37 import, 13 export) and all 14 grid areas load through Edibert without error (`tests/test_edibert_p1.py`, parametrized per ID); the site copy `earnie_env/config/tariffs.json` loads too.
- [x] User tariffs are visible in the Szenarienkonfigurator selection (AppTest `test_user_tariffs_appear_in_selection`).
- [x] Existing pricing tests unchanged and green.

### Format differences for P3a

| # | Topic | Earnie today | Edibert | P3a action |
| --- | --- | --- | --- | --- |
| 1 | Missing month in `monthly_table` | exact → same month prior year → prior month, logged once as a warning; error only if none exists | `PRICE_MISSING` (error) | needs Edibert `0.1.g` (`MONTH_RATE_FALLBACK` as coded warning); surface it, never swallow |
| 2 | Unknown tariff fields | ignored silently by the normalizer | `TARIFF_UNKNOWN_FIELD` (error) | none for the catalog (loads clean); user files are already checked strictly |
| 3 | `user_` prefix | no rule | user IDs must start with `user_`, catalog IDs must not (`ID_PREFIX_*`) | none; enforced since P1 |
| 4 | Edited site copy of the catalog | `earnie_env/config/tariffs.json` is seeded from `share/` and may be edited (`append_monthly_rate`) | treated as catalog; every entry gets origin `catalog` | P8 decides whether new entries may still land there |
| 5 | `__user_fixed__` (*Eigener Festpreis*) | pseudo tariff, cent values on the scenario | no equivalent | P3a: synthetic Edibert `fixed_cent` / `fixed` tariff at resolution time; not migrated (decided 2026-10-26, § P2 decision 4) |
| 6 | `tariff_format` root key | none | required (`FORMAT_MISSING` / `FORMAT_UNSUPPORTED`) | done in P2: all four tariff-track files carry `tariff_format: 1` (Edibert `v0.1.2`, `tf1.tariff_format`) |
| 9 | VAT on the net grid fee for gross tariffs | `grid_fee_on_tariff_basis`: `supplier + grid × (1 + vat/100)` | same since Edibert `v0.1.2` (`evaluate`) | P3a: accept with a gross tariff plus grid fee in the comparison run |
| 10 | Missing `vat_percent` | read as `0` | `VAT_PERCENT_MISSING` on every tariff (gross and net) | done in P2: catalog, templates and fixtures carry it; `tf1.tariff_format` asks for user tariffs |
| 7 | `land` | required per tariff (country filter) | optional | keep required (decided 2026-10-26, § P2 decision 7); P3b decides again |
| 8 | Root maintenance keys (`earnie_data_model`, `oemag_monthly_feed_in_rates`, …) | read by Earnie | tolerated and ignored (`ROOT_FIELDS`) | none |

Row 1, measured on the catalog (2026-10-26): there are no gaps inside any table; the differences are at the edges. Six export tables end at 2026-09 and `monthly_sunny_web_recherche` at 2026-10, so Earnie prices the following months with the prior-year month (`at_oemag_gesetzlicher_marktpreis` 2026-10: Earnie 9.008 ct from 2025-10, Edibert `PRICE_MISSING`); `at_vkw_strom_duo` ends at 2027-03. Before a table starts, both fail (`at_vkw_pv_flex` 2025-03: Earnie error, Edibert `PRICE_MISSING`). The SNAP comparison in P3a must therefore run over months that every table covers, or after `0.1.g`.

## P2 — Netznutzung split and migration (implemented 2026-10-26)

Status: **implemented** (see *Implementation notes* and *Done check* below). Backlog item *Edibert P2* (Version 2.8). Design sources: [Config-Migration-Draft.md](../../backlog/Config-Migration-Draft.md) §3.7 and §8, [data-model-stability-decisions.md](data-model-stability-decisions.md) § D3.

### Findings (2026-10-26)

- **Edibert was not ready (resolved by Edibert `0.1.i`, tag `v0.1.2`).** `tariff_format` is neither in `store.py` `ROOT_FIELDS` nor accepted by `gridfee.py` `parse_grid_fee_catalog`; `edibert.api` has no `plan_migration` / `migrate` (Edibert `docs/spec/api.md` "Not yet in the API"); there are no user grid areas; `vat_percent` silently becomes `0` (`tariff.py`). The Edibert backlog has no item for this. **Earnie P2 is blocked until an Edibert release ships Part A.**
- **Earnie's own grid fees are a flat base price only.** `data/grid_fees.py` `normalize_netznutzung_config` reads `area_id`, `base_cent_kwh` and `include_status`; `power_metering` and `quarter_hour_meter` are fixed constants, own `rules` / holidays are not read. The split therefore maps `area_id: null` + `base_cent_kwh: X` to one user grid area with `X` for both metering keys; no rule or holiday data has to move.
- **Real case:** the maintainer site (`earnie_env/config/house_profiles.json`) uses `area_id: null` with 5.353 ct.
- **First data-model bump since the Regression suite exists.** The frozen configs in recorder snapshots and `tests/regression/fixtures/*/configs/` carry `earnie_data_model: 4`; after the bump the loaders reject all 11 regression cases unless replay migrates them. SUSI P1 / P2 / P6 needs the same.

### Decisions (2026-10-26, recommendations accepted by the maintainer)

1. **Key and track:** `tariff_format` (int, starts at `1`), one shared version for all tariff-track files (`tariffs.json`, `user_tariffs.json`, `grid_fees.json`, `user_grid_fees.json`). Closes draft §8 points 1 and 2.
2. **User grid areas** live in their own file `user_grid_fees.json` next to `grid_fees.json`, same shape (`rule_sets`, `areas`), IDs start with `user_`, an ID in both files is a load error — the same split as `tariffs.json` / `user_tariffs.json`.
3. **No implicit "no grid fee":** after P2 `netznutzung.area_id` is required. A profile with `area_id: null` and `base_cent_kwh` missing or `0`, or without `netznutzung`, gets a required wizard question: pick a catalog area, or create a user area with an explicit `0` ct. Never a silent default.
4. **`__user_fixed__` (*Eigener Festpreis*) is not migrated.** It stays a scenario shortcut; P3a builds a synthetic Edibert fixed-price tariff at resolution time (format difference row 5).
5. **VAT question (D3b), widened during Edibert 0.1.i:** `vat_percent` is mandatory on **every** tariff (gross and net, `0` allowed, Edibert `VAT_PERCENT_MISSING`). Every user tariff without a rate gets the required question `vat_percent:<import|export>:<tariff_id>` (code `VAT_PERCENT`, `kind="number"`, country rate AT 20 / DE 19 / CH 8.1 as `default`, param `prices` gross/net); the user confirms the value, the step never writes it unasked. Earnie's `Question` gained `kind="number"` and `default`; the wizard shows the default as placeholder plus a *Vorschlag übernehmen* button.
6. **Bundling with SUSI:** data model 5 is opened by P2 and shared with the SUSI P1 / P2 / P6 steps **only if no release or pre-release (HA add-on pre-release channel included) ships between them**. If one does, SUSI gets data model 6.
7. **`land` on user tariffs** stays required in Earnie; P3b decides again (format difference row 7).

### Part A — Edibert (new Edibert phase, tag `v0.1.2`)

1. **Format version:** `tariff_format` in the root of all tariff-track files, current value `1`. Missing key → coded error; unknown value → `FORMAT_UNSUPPORTED`. `earnie_data_model` leaves `ROOT_FIELDS`; only the migration reads it (no dual-read).
2. **User grid areas:** load `user_grid_fees.json` (prefix rules, collision error, merged area view with origin `catalog` / `user`); write function in `edibert.api` for one user area (used by Earnie's house-profile UI until P7).
3. **Smaller `netznutzung`:** `CONFIG_FIELDS` = `area_id` (required), `power_metering`, `quarter_hour_meter`, `include_status`. `base_cent_kwh`, `rules`, `holidays`, `extra_holiday_dates` are removed (they live in a user area now).
4. **D3b:** `prices_include_vat: true` requires `vat_percent` (`0` allowed); new error code instead of the silent `0`.
5. **Migration API:** `edibert.api.plan_migration` / `migrate`, pure (docs in → docs out), with questions and blockers in the shape of Earnie's §3.1: tag untagged files with `tariff_format: 1`, replace `earnie_data_model` in `tariffs.json`, create user grid areas from values handed in by the caller, ask for missing VAT rates.
6. Spec (`tariff-format.md` §2 and §5a, version-track section; `api.md`), tests, Edibert backlog item, tag `v0.1.2`.

### Part B — Earnie

1. **Pin:** raise to `v0.1.2`; `house_config/edibert_tariffs.py` loads `user_grid_fees.json` and requires `tariff_format`.
2. **Track plumbing:** `TARIFF_TRACK_FILES` gains `tariffs.json` and `user_grid_fees.json`; `runtime_store.persist_paths.user_grid_fees_path_for`; config pack, debug dump, recorder snapshot, plan-input mtimes, `recorder_replay._ARCHIVE_TO_ENV`, `migration/io_util.py`. Stamping in `settings/json_io.py` / `config_pack.py` becomes track-aware (closes the bugfix entry *`grid_fees.json` gets `earnie_data_model` by side effect*). The planner blocks untagged tariff-track files from now on.
3. **Data model 5:** `CURRENT_DATA_MODEL = 5`, `MIGRATABLE_DATA_MODELS = {3, 4}`. Step `dm5.netznutzung_split` (`house_profiles.json`): per profile with `area_id: null`, move the base price out, set `area_id = user_<profile_id>`, hand the values to the tariff step; decision 3 as its question.
4. **Tariff step `tf1.tariff_format`:** thin wrapper around `edibert.api.migrate` (tag files, `tariffs.json` key swap, create `user_grid_fees.json`, VAT questions). Same wizard run and backup; planned after the Earnie-track steps (declared dependency, draft §3.7).
5. **Fail-fast loaders:** `normalize_netznutzung_config` requires `area_id` and rejects `base_cent_kwh` with the migrate hint (also in `migration/validate.py`); `resolve_grid_fee_spec` reads catalog plus user areas. Pricing stays on Earnie's own engine until P3b.
6. **UI:** *Eigener Arbeitspreis* in the house profile (`ui/house_config_profile_thermal.py`, `_session.py`, `_save.py`) writes a user grid area through `edibert.api` and selects it; tariff plausibility and `ui/setup_readiness.py` follow.
7. **Old snapshots:** recorder replay and regression intake run the migration chain in memory on archived configs; a snapshot that would need an answer stops the case with a clear message (no guess). Goldens: only input digests change, metrics must not. Pull this step early, SUSI needs it too.
8. **Seeds, schemas, fixtures:** `share/config/grid_fees.json` and `tariffs.json` get `tariff_format: 1`; example / minimal house profiles get an `area_id`; `house_profiles.schema.json` (`netznutzung`) and a new `user_grid_fees.schema.json`; new migration fixture `tests/fixtures/migration/v4_pre_tariff_track` (own base price, base `0`, gross user tariff without VAT rate) with golden; existing migration goldens move to data model 5.
9. **Docs:** German `docs/konfiguration/preise.md`, `docs/referenz/tarife-quellen.md`, `docs/konfiguration/speichern-laden.md`; English `docs/workflow/config-migration.md` (tariff track active), rule `.cursor/rules/config-migration.mdc`, this file (format differences rows 5 and 6); release-notes draft with a *Migration* section (draft only, `.github/release-notes/drafts/`).

### Order

Part A (Edibert repo) → B1 → B2 → B7 → B3 / B4 → B5 → B6 → B8 → B9.

### Implementation notes (2026-10-26)

- **Edibert `v0.1.2` adds VAT on the net grid fee for gross tariffs** (same rule as Earnie's `grid_fee_on_tariff_basis`); acceptance is part of P3a (format difference row 9).
- **Tracks:** `runtime_store.data_model`: `CURRENT_DATA_MODEL = 5`, `COMPATIBLE = {5}`, `MIGRATABLE = {3, 4}`; `TARIFF_TRACK_FILES` = the four tariff files (equal to `edibert.api.TARIFF_TRACK_FILES`, test), `TARIFF_TRACK_TEMPLATES` (`tariffs.example.json`, `tariffs.minimal.json`) never stamped; `ensure_tariff_format` in the Earnie loaders (`load_tariffs_document`, `data.grid_fees.load_grid_fee_catalog`) and in `validate_migrated_docs`. Untagged tariff files are no level blocker; `tf1.tariff_format` is pending, so the startup gate stays closed until it ran.
- **Doc-dependent questions:** `MigrationStep.questions_for(docs)` (per profile / tariff), collected along the dry-run chain (`types.step_questions`).
- **Hand-over dm5 → tf1:** in-memory key `types.HANDOFF_USER_GRID_AREAS` (never written, excluded from diffs); tf1 passes the areas as `user_grid_areas` to `edibert.api.migrate`. An existing user area with the same ID and another price is the Edibert blocker `GRID_ID_COLLISION`.
- **Registry order:** dm5 after every dm4 step, tf1 last. `migrate_v4` keeps stamping the current model (never downgrades a doc); `dm4.se_conf_defaults` now runs on model 4 and 5.
- **Unattended migration** (`runner.migrate_docs_unattended`): config-pack import and recorder replay. A required question of a data-model ≥ 5 step stops the run with the question IDs (dm4 questions keep their 2.7 unattended meaning, *keep as is*). Recorder replay runs only the steps of later data models than the snapshot (`model_bump_only`) and validates only what it changed: a snapshot was loadable when recorded.
- **UI:** `house_config/own_grid_fee.py` (`OWN_AREA`, `persist_own_grid_fee`) writes `user_<profile_id>` through `edibert.api.save_user_grid_area` before the profile; a new profile has no preselected area and is not saved until one is chosen; `ui/setup_readiness.py` reports a live profile without area. The Loxone greenfield import (`ensure_live_profile`, Smarthome-Backend) asks for the grid area as a required select when no house profile exists yet (decided 2026-10-26, no default).
- **Seeds and fixtures:** `share/config` grid catalog and tariff templates tagged, `vat_percent: 0` on the two template / fixture export and fixture import tariffs that had none (Earnie read a missing rate as 0, so prices are unchanged); `house_profiles.example.json` and the cloud POC pack select `AT-VBG` (before: no grid fee); the backtesting fixture keeps no grid fee via `user_test_home` (0 ct) plus `user_no_grid_fee` for test profiles; schemas `house_profiles` (`area_id` required, `base_cent_kwh` removed), `tariffs` (`tariff_format`), new `user_grid_fees.schema.json`.

### Done check

- [x] Edibert `v0.1.2` tagged with A1–A6; Earnie pin raised.
- [x] `dm5.netznutzung_split` and `tf1.tariff_format` registered, both run in one wizard run with one backup (`tests/test_edibert_p2.py`).
- [x] Migration fixture `v4_pre_tariff_track` and golden green; loaders fail fast on the old format with the migrate hint; the six existing migration goldens moved to data model 5.
- [x] All 11 regression cases green (metrics unchanged, no golden update) through in-memory replay migration.
- [x] Full suite green; the maintainer site `earnie_env` migrates cleanly in the dry run (2026-10-26; the real run is the maintainer's).
