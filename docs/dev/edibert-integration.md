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
- Edibert brings `holidays` and `jsonschema` (already an Earnie dependency). The `mqtt` extra is not installed; the `ui` extra is pinned since P7 (D8, the embedded editor; it adds only `streamlit`, which Earnie pins anyway).

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
| 1 | Missing month in `monthly_table` | exact → same month prior year → prior month, logged once as a warning; error only if none exists | same order since Edibert `v0.1.4` (`0.1.g`), coded warning `MONTH_RATE_FALLBACK` (`rule`, `used_month`); `PRICE_MISSING` only when none of the three exists | done in P3a-2: the adapter logs the warning once per tariff and month and returns it to reports; harness and test check rule, month and price against Earnie |
| 2 | Unknown tariff fields | ignored silently by the normalizer | `TARIFF_UNKNOWN_FIELD` (error) | none for the catalog (loads clean); user files are already checked strictly |
| 3 | `user_` prefix | no rule | user IDs must start with `user_`, catalog IDs must not (`ID_PREFIX_*`) | none; enforced since P1 |
| 4 | Edited site copy of the catalog | `earnie_env/config/tariffs.json` is seeded from `share/` and may be edited (`append_monthly_rate`) | treated as catalog; every entry gets origin `catalog` | decided in P8 (D1, D3): no new entries; the site copy keeps its seeded entries and the inline next-month form until catalog packages bring the monthly rates |
| 5 | `__user_fixed__` (*Eigener Festpreis*) | pseudo tariff, cent values on the scenario | no equivalent | P3a T3: synthetic Edibert `fixed_cent` / `fixed` tariff built with `api.parse_tariff` (Edibert `0.1.j`) from the resolved cent and VAT values; not migrated (decided 2026-10-26, § P2 decision 4) |
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

## P3a — Engine parity harness (plan 2026-10-26)

Status: **done 2026-10-26** — P3a-1 incl. T3 and P3a-2 (see *Implementation notes*, *Results*, *Triage*, *T3*, *P3a-2*). Backlog item *Edibert P3a* (Version 2.8). Goal: prove that Edibert prices every slot exactly like Earnie's own engine before P3b deletes `data/tariff_pricing.py` / `data/grid_fees.py`. No MILP change, no user-visible change.

### Findings (2026-10-26)

- **Edibert `v0.1.2` already has what a parity run needs:** `edibert.api.tariff_price_series` (15/30/60 min, hourly settlement = mean of the four slots as in Earnie's `hourly_settlement_epex_values`), `evaluate` per slot, `PricePoint` with `supplier_cent` / `grid_cent` / `vat_cent`, grid fee on import only (same as Earnie), VAT on the net grid fee for gross tariffs (format difference row 9). Missing until `0.1.g`: the monthly-table fallback with `MONTH_RATE_FALLBACK` (row 1); Edibert raises `PRICE_MISSING` instead.
- **Three seams compute slot prices in Earnie** (everything else consumes `k_act` / `k_push_act`):
  - live import: `data/market_prices.py` `epex_to_brutto_cent` (per slot) → `import_cent_kwh`;
  - SE / backtesting import: `data/backtesting_prices.py` `import_brutto_cent_for_slots` / `enrich_slots_import_prices` (lists, hourly settlement applied before);
  - export (live and SE): `data/feed_in_prices.py` `resolve_k_push_act` → `export_cent_kwh` (monthly lookup from the resolved settings).
  - Plus the SE invoice line `simulation/se_invoice_netznutzung.py` (`grid_fee_work_cent`, `matching_rule`): compared through `PricePoint.grid_cent` so P3b can switch it too.
- **Rounding:** both engines round the final cent to 4 decimals per slot; Edibert additionally rounds the 15-min means of a coarser resolution. At 15 min the expected difference is `0` or one unit in the 4th decimal.
- **Earnie has no feature-flag mechanism** today (no `FEATURE_*` setting, no env switch for engines).
- **Matrix size:** 37 import × 14 grid areas × 2 metering variants (`quarter_hour_meter` on / off; SNAP rules need it) + 13 export tariffs, over 35,040 slots per year. Restricted to `land` of tariff = `land` of area this is a few hundred combinations, i.e. tens of millions of slot evaluations per engine → needs parallel workers (same rule as backtesting: `--workers N`, largest useful N).
- **`__user_fixed__`** (*Eigener Festpreis*) has no Edibert equivalent; P3a builds the synthetic tariff (decided in P2, decision 4).
- **Overlap with Edibert `0.1.g`:** its item "committed compatibility tests against Earnie results" needs exactly the reference data this harness produces. One fixture set serves both repos.

### Decisions (2026-10-26, recommendations accepted by the maintainer)

1. **Start before `0.1.g` in two steps.** **P3a-1** now: adapter, flag, harness, comparison over the months every monthly table covers (P1 row 1: through 2026-09 for the six export tables, 2026-10 for `monthly_sunny_web_recherche`). **P3a-2** after `0.1.g`: raise the pin, add the edge months, check `MONTH_RATE_FALLBACK` against Earnie's prior-year / prior-month result and its log warning. Rejected: waiting for `0.1.g` and doing it in one go (blocks the epic until then).
2. **Flag:** environment variable `EARNIE_PRICING_ENGINE` = `earnie` (default) | `edibert`; an unknown value is a startup error. Dev / CI only, no UI, no settings key, removed in P3b. No settings key, because it would need a migration step for a switch that lives one phase.
3. **Tolerance:** absolute `1e-4` ct per slot on `cent`, and separately on the grid part (`grid_cent` vs. `grid_fee_work_cent`). Anything above is a deviation that gets triaged; no relative tolerance.
4. **Comparison period:** calendar year 2025 in full (both SNAP seasons, both DST changes), plus 2026-01 through the last covered month (P3a-1) / through today + 2 days (P3a-2). Market prices: the archived day-ahead series the SE already loads (`data/data_loader.py`), same values for both engines, negative prices included (they matter for `feed_in_fee_factor × |EPEX|`).
5. **Report and fixtures:** the harness writes a full diff report (JSON + Markdown summary) to `runtime/` (not committed); a small committed fixture (a few days around the DST changes, a SNAP summer day, a month boundary, one hourly-settled tariff, `__user_fixed__`, one user grid area) with the expected Earnie prices becomes the CI parity test, and is offered to Edibert for `0.1.g`.

### Part A — Edibert

- **P3a-1:** none (`v0.1.2` is enough).
- **P3a-2:** `0.1.g` (fallback with `MONTH_RATE_FALLBACK`, `market_cent` + method per point; the range queries are needed only from P4b). Ask the Edibert side to take the committed fixture from decision 5 into its compatibility tests.

### Part B — Earnie

1. **Access module:** `house_config/edibert_tariffs.py` stays the only caller of `edibert.api`. New functions: Edibert `Tariff` by direction + ID (from the loaded `TariffSet`, cached by file mtime like the loaders), `GridFee` from the profile's `netznutzung` (`parse_grid_fee_config` + `resolve_grid_fee` on the catalog + user view), `PricingContext` from the profile (`timezone`, `land`, `region`), the synthetic `__user_fixed__` tariff (`fixed_cent` / `fixed` with the scenario's cent value, `prices_include_vat` and `vat_percent` as Earnie resolves them today), and series / slot evaluation. `EdibertError` → `EdibertLoadError` as in P1; every `EdibertWarning` is returned to the caller, never dropped.
2. **Adapter `data/edibert_slot_prices.py`:** `import_cents(slot_datetimes, epex_values, …)` / `export_cents(…)` returning lists aligned to Earnie's slot datetimes (local → Edibert UTC keys, one `tariff_price_series` call per contiguous range at 15 min; per-slot `evaluate` for the live single-slot path), plus `grid_net_cents` for the invoice line. Hourly settlement is left to Edibert (Earnie's pre-averaging is not applied on this path, to avoid averaging twice). Warnings are logged once per tariff and returned.
3. **Flag `EARNIE_PRICING_ENGINE`:** read once in one place (e.g. `settings/pricing_engine.py`); the three seams and the invoice line branch on it. With `edibert`, the Earnie functions are not called at all (no mixed result, no fallback to Earnie on an Edibert error).
4. **Harness `python -m scripts.edibert_parity`:** `--year`, `--from` / `--to`, `--tariffs`, `--areas`, `--workers N`; builds the matrix (tariff × area × metering variant, land-matched; export tariffs without area; `__user_fixed__` and one flat user area as extra cases), prices every slot with both engines and writes the report: per combination max / count of deviations, first deviating slots with the intermediate steps of both sides (Edibert `PriceResult` vs. Earnie's base, grid, VAT), warnings seen. Exit code ≠ 0 when a deviation exceeds the tolerance.
5. **Tests:** committed parity fixture (decision 5) in `tests/test_edibert_p3a.py`; DST days (23 and 25 hours), SNAP window edges, month boundary, hourly-settled tariff, gross tariff + grid fee (row 9), net tariff; flag parsing (default, unknown value fails); seams with `edibert` produce the same `k_act` / `k_push_act` lists as with `earnie` on a short SE window. End-to-end: the 11 regression cases with `EARNIE_PRICING_ENGINE=edibert` unchanged (metrics within the goldens' tolerance) — the gate P3b relies on.
6. **Triage:** every deviation goes into a table in this section (bug in Earnie / bug in Edibert / intended / test data), with the fix in the owning repo. Intended differences are documented here and in P3b's release-notes draft; nothing is "fixed" by loosening the tolerance.
7. **Docs:** this section (findings → implementation notes, format-differences table updated for rows 1, 5, 9); `DEVELOPER.md` (flag + harness call). No German user docs (no user-visible change until P3b).

### Order

P3a-1: B1 → B2 → B3 → B4 → first full run → B6 triage → B5 → B7. P3a-2 (after `0.1.g`): pin → fallback months in B4 / B5 → triage → done check.

### Implementation notes (P3a-1, 2026-10-26)

- **Correction to decision 4:** the catalog's SNAP rule is `valid_from: 2026-04-01`, so 2025 has no SNAP season. The comparison period is **2025-01-01 → 2026-10-01** (both DST changes of 2025, SNAP April–September 2026, all monthly tables covered). Prices come from the Energy-Charts API (`--fetch-prices`, cached per quarter under `runtime/edibert_parity/`, waits on HTTP 429), not from `data/data_loader.py`: that loader returns naive house time and averages the repeated autumn hour away.
- **Pricing reference instead of Edibert objects in the settings:** with the flag, `resolve_scenario_settings` stores `_edibert_pricing` (plain dict: tariff and grid file paths, tariff IDs, time zone, `land`, `region`, `netznutzung`). Edibert objects would not survive SE worker pickling, fingerprints and debug dumps. `pricing_kwargs_from_resolved` and `FeedInSettings` carry the reference to the seams; a seam that runs with the flag but without a reference fails (`Edibert-Preisreferenz`), it never prices with Earnie.
- **One path in the adapter:** every seam (live single slot included) goes through `tariff_price_series` per run of consecutive 15-min slots. Hourly settled spot tariffs therefore need the whole hour in the input; a partial hour is Edibert `PRICE_MISSING` (Earnie averages the slots present). Live horizons start at the current quarter-hour, so the live path with an hourly settled tariff will hit this — to be decided in P3b (see triage).
- **`__user_fixed__`:** `edibert.api` had no public way to build a tariff from a dict (`parse_tariff` was internal; `load_tariffs` needs files and the `user_` prefix). Solved by T3 (Edibert `0.1.j`, `v0.1.3`).
- **Metering variants dropped from the matrix:** Earnie always assumes an unmetered household with quarter-hour meter (`normalize_netznutzung_config` forces both), so only that variant is comparable. Both engines get the `netznutzung` object Earnie writes (`default_netznutzung_config()` + `area_id`); with only `area_id`, Edibert defaults to no quarter-hour meter and skips SNAP.
- **Invoice line not switched in P3a-1:** the harness compares the net grid fee per slot (`grid_fee_work_cent` vs. `PricePoint.grid_cent`), which is what the invoice line sums; switching `simulation/se_invoice_netznutzung.py` (it groups by rule ID) moves to P3b together with the deletion of `data/grid_fees.py`.
- **Harness without site config:** Earnie's price helpers read the planning time zone from `config`; the harness points `config` at the test fixture config unless `--site-config` (the maintainer site is not migrated to `tariff_format` yet).
- **CI fixture:** `tests/fixtures/edibert_parity/expected_prices.json`, 9 catalog tariffs × 4 windows (spring DST 2026, month boundary + SNAP start 2026-03-31/04-01, SNAP day 2026-07-01, autumn DST 2025), deterministic EPEX with negative values. `tests/test_edibert_p3a.py` checks Earnie still produces it (dropped in P3b) and Edibert matches it.
- **Scenarios without a tariff keep Earnie's existing rules** (not new fallbacks): no import tariff → the live scenario's tariff, as Earnie's `epex_to_brutto_cent` does (now with the live scenario's Edibert reference); no export tariff → the constant `k_push_cent`, which is no tariff pricing at all. P3b decides whether such scenarios stay valid.
- **Regression L2 inline pricing:** `REG-S-gross-tariff-netznutzung` defines its tariff and flat grid fee as Earnie-internal specs (`_import_tariff_spec`, `_grid_fee_spec`). With the flag, `tests/regression/l2_runner.py` writes them as tariff-track files (catalog tariff + user grid area in a temporary directory) and attaches a pricing reference, so both engines price the same inputs.

### Results (P3a-1, 2026-10-26)

- **Full matrix** (`python -m scripts.edibert_parity --fetch-prices --workers 8`, 2025-01-01 → 2026-10-01): 470 cases (30 AT import tariffs × 14 areas + no grid fee, 7 DE / CH import tariffs without area, 13 export tariffs), 28,767,308 slots, 307 s. **0 untriaged deviations**; outside T1 the final cent differs by exactly `0`, the net grid fee by at most `1.8e-15`. T1: 880 slots (110 cases = all 12 hourly settled spot tariffs × their areas, 8 slots each, max 0.003 ct). 6 months both engines refuse (`at_vkw_pv_flex` before its table starts 2025-07); no month only one engine can price.
- **Regression with `EARNIE_PRICING_ENGINE=edibert`:** all 11 cases green, metrics unchanged. Coverage is limited: the three L2 cases with a tariff (`REG-O-summer-june`, `REG-O-ev-deadline` via the live scenario's `fixed_25ct`, `REG-S-gross-tariff-netznutzung` via the case's gross tariff + user grid area) price through the adapter; the L1 cases replay recorded cycles and never price, so they do not test the engine. Spot tariffs are covered by the harness, not by the regression gate.

### Triage

| # | Case | Finding | Verdict | Action |
| --- | --- | --- | --- | --- |
| T1 | hourly settled spot tariffs (import and export), autumn DST night | Earnie groups the hourly mean by wall-clock hour (`normalize_price_slot` → `floor_to_hour_slot`), so both 02:00 hours (CEST, CET) share one mean of eight quarter-hours; Edibert prices each real hour | **Earnie bug**, Edibert correct; one night a year | none in Earnie (engine removed in P3b); pinned in the CI fixture test (`DST_REPEATED_HOUR`); P3b release-notes draft mentions the changed prices for that hour |
| T2 | hourly settled spot tariffs, horizon starting mid-hour | Earnie averages the quarter-hours present; Edibert needs the whole hour (`PRICE_MISSING`) | **intended** (no invented data) | decide in P3b: Earnie's live path passes the full hour of market prices (they are known day-ahead) |
| T3 | `__user_fixed__` | no public Edibert constructor for a synthetic tariff | **gap in Edibert API** | **done:** Edibert `0.1.j` `api.parse_tariff` (`v0.1.3`) + Earnie `synthetic_fixed_tariff` (§ T3) |
| T4 | `at_vkw_pv_flex`, 2025-01 … 2025-06 | both engines refuse (table starts 2025-07) | **test data** (expected) | none |

### P3a-2 — Monthly-table edge months (2026-10-26)

- **Edibert `0.1.g` released as `v0.1.4`** (approved by the maintainer); pin raised. New in the API (additive, `API_VERSION` 2): monthly-table fallback in Earnie's order with `MONTH_RATE_FALLBACK` (`tariff_id`, `direction`, `month`, `used_month`, `rule` = `prior_year` / `prior_month`) in `PriceSeries.warnings` and `PriceResult.warnings`; `PricePoint.market_cent` and `PricePoint.method`; `market_range` / `MarketArchive` for arbitrary ranges (UTC, monthly cache, needed from P4b). Edibert also took Earnie's CI fixture and Earnie's edge-month values into its own tests.
- **Adapter:** no change needed — `price_points` already logs every series warning once per tariff and text (so once per fallback month) and collects them for reports (`warnings_out`); a month without any of the three rates stays `PRICE_MISSING`, an error.
- **Harness:** for `monthly_table` tariffs every month compares the source of the rate (Earnie `lookup_monthly_cent` → `exact` / `prior_year YYYY-MM` / `prior_month YYYY-MM` vs. Edibert's `MONTH_RATE_FALLBACK`); a different source is a failure (exit code 1). Tariffs without market prices need no price data, so months after the last day-ahead price can be checked.
- **Edge-month run** (`--from 2026-10-01 --to 2027-05-01`, the 9 `monthly_table` tariffs, 37 cases): 78 fallback months (six AT/DE export tables from 2026-10, `monthly_sunny_web_recherche` from 2026-11, `at_vkw_strom_duo` / `at_vkw_strom_duo_normalpreis` 2027-04 with all grid areas), all `prior_year`, source and price equal on both sides, 0 deviations. No catalog tariff reaches `prior_month`; `tests/test_edibert_p3a.py` covers both rules with a gap table through the adapter.
- **Full run again with `v0.1.4`** (2025-01 → 2026-10): unchanged — 0 untriaged deviations, 880 T1 slots, 6 months both engines refuse (`at_vkw_pv_flex` before 2025-07). Regression with the flag green.

### T3 — *Eigener Festpreis* on Edibert (plan 2026-10-26)

**Problem:** `__user_fixed__` is a scenario shortcut (cent values on the scenario, not in a tariff file; not migrated, § P2 decision 4). Edibert can only build tariffs from files (`load_tariffs`, with the `user_` prefix rule), and `parse_tariff` is internal.

**Part A — Edibert `0.1.j` (additive, `API_VERSION` stays `2`):**

1. `api.parse_tariff(raw, direction) -> Tariff`: one tariff object, checked exactly like a file entry (unknown fields, type fields, mandatory `vat_percent`, …). No ID prefix rule and no `tariff_format` (both belong to files). Re-export of `edibert.tariff.parse_tariff`, like `evaluate`.
2. Spec `docs/spec/api.md` (functions table), test in `tests/test_api.py` (valid fixed import / export tariff, unknown field and missing VAT fail, prefix not checked), backlog item `0.1.j`.
3. Release `v0.1.3` (version bump and tag only with the maintainer's approval).

**Part B — Earnie (after the pin is raised to `v0.1.3`):**

1. `house_config/edibert_tariffs.py`: `synthetic_fixed_tariff(direction, cent, *, vat_percent, land)` builds the raw dict and calls `api.parse_tariff` — import: `type fixed_cent`, `fix_cent_kwh`, gross, `vat_percent` = the land rate Earnie already applies (`apply_land_vat_to_user_fixed_import`); export: `type fixed`, `k_push_cent`, gross, `vat_percent 0` (same as Earnie's `_synthetic_user_export_tariff`).
2. `pricing_reference` stops rejecting `__user_fixed__` and stores `user_fixed` = `{import: {cent, vat_percent}, export: {cent}}` from the resolved synthetic specs; the adapter builds the tariff from it instead of looking up the ID.
3. Tests: seam test with *Eigener Festpreis* equal under both engines (import with grid area AT-VBG on a SNAP day — row 9, VAT on the net grid fee — and export); the "not yet on Edibert" test is replaced. Not in the shared CI fixture: `__user_fixed__` is an Earnie scenario shortcut, not a catalog tariff Edibert's compatibility tests could use.
4. Docs: this section → done, format differences row 5, triage T3.

**Status (2026-10-26): done.** Edibert `0.1.j` released as `v0.1.3` (approved by the maintainer); Earnie pin raised to `v0.1.3` in the same change as Part B.

### Done check

- [x] Harness runs the full matrix over the comparison period with `--workers N`; report with zero deviations above `1e-4` ct, or every deviation triaged in this section (2026-10-26: 0 untriaged, T1 triaged).
- [x] `MONTH_RATE_FALLBACK` surfaced on the edge months and equal in value to Earnie's prior-year / prior-month result (P3a-2, 2026-10-26: 78 fallback months, 0 differences).
- [x] Parity fixture committed, `tests/test_edibert_p3a.py` green; full suite green with the default flag.
- [x] All 11 regression cases green with `EARNIE_PRICING_ENGINE=edibert` (L2 cases with a tariff price through Edibert; L1 cases do not price, see *Results*).
- [x] `__user_fixed__` on Edibert (T3, Edibert `v0.1.3`, pin raised).

## P3b — Engine switch (2026-10-27)

Status: **implemented** (see *Implementation notes*, *Results*, *Done check*). Backlog item *Edibert P3b* (Version 2.8). Goal: live **and** SE prices come only from Edibert; Earnie's own pricing code is deleted; the MILP keeps receiving `k_act` / `k_push_act` per slot.

### Findings (2026-10-27)

- **No Edibert release needed.** `v0.1.4` has everything: `tariff_price_series` for the slot lists, `GridFee.work_cent(local, ctx)` returns the net grid fee **and** the matching rule ID (SE invoice line), `GridFee.skipped` (rules not applied), `Tariff.fees` (monthly fees), `api.market_zone`, `api.STANDARD_VAT_PERCENT`.
- **The resolved tariff specs are more than prices.** `_import_tariff_spec` / `_export_tariff_spec` also feed the monthly fees (`simulation/monthly_fees.py`), land / market zone and the aWATTar URL (`house_config/awattar_api.py`), the SE fingerprint (`simulation/backtesting_fingerprint.py`), the reference fingerprint (`house_config/planning_flex_bridge.py`), the info sidebar hints and the VAT of the invoice line.
- **Live prices twice:** `resolve_market_slots` priced every slot on its own (`epex_to_brutto_cent`), then `enrich_slots_import_prices` priced the whole list again and overwrote `k_act`. On Edibert the single-slot call fails for hourly settled tariffs (T2).
- **Partial hours also in the SE:** sunrise windows start and end at quarter-hours, so an SE run with an hourly settled tariff hits T2 as well (P3a never ran the SE with such a tariff under the flag).
- **Single-slot callers besides live:** `runtime_store/history_chart_rows.py` (market price back-inference of legacy log entries) and `simulation/reference_costs.py` (`resolve_k_push_act` per slot).
- **Dead code:** `data/profile_manager.build_historical_optimization_matrix` / `_get_historical_*` (hourly slots) had no production caller.
- **Usage:** 12 catalog tariffs are hourly settled (`settlement_mtu: 60min`); the maintainer's live tariff is quarter-hourly.

### Decisions (2026-10-27, recommendations accepted by the maintainer)

1. **D1 — partial hour of hourly settled tariffs (T2):** the caller supplies the market prices of the quarter-hours an hourly settled tariff needs outside the input (`market_for`), obtained the same way as the horizon (day-ahead, else mirror / forecast); prices stay per input slot. No averaging of a partial hour, no `PRICE_MISSING` in live or SE.
2. **D2 — scenarios without a tariff:** import and export tariff are **required** for pricing. The rules "no import tariff → the live scenario's tariff" and "no export tariff → constant `k_push_cent`" and the legacy `feed_in_mode` / `dynamic_epex` / monthly path are deleted; a scenario without a tariff fails loud when priced (`import_tariff_id fehlt` / `export_tariff_id fehlt`), the flat keys fail loud on resolution. Data model 5 (not shipped yet) gets the step `dm5.scenario_feed_in` with required questions for scenarios with the flat keys. A scenario that is simply incomplete (no tariff, no flat keys; e.g. during onboarding) is no migration case.
3. **D3 — VKW Strom Duo summer window:** **dropped** (maintainer, 2026-10-27; not needed any more). The catalog stays as it is.
4. **D4 — tariff metadata:** the keys `_import_tariff_spec` / `_export_tariff_spec` stay, filled from the Edibert `Tariff` (`house_config.edibert_tariffs.tariff_info`: metadata and catalog parameters for display, fees and fingerprints; no Earnie code prices from them). The SE fingerprint hashes the content of the tariff entries, the grid area and its rule set (`pricing_digest`), so a catalog edit invalidates cached SE results.
5. **D5 — `house_config/tariffs_store.py`:** the whole resolution goes (`resolve_*_tariff_into_settings`, synthetic `__user_fixed__` specs, `engine_pending_fields` / E1, `monthly_rates_holder`). Document loading for the UI selects stays until P7, `append_monthly_rate` until P8.
6. **D6 — `land` on user tariffs** (format difference row 7): stays required (the market zone is derived from it).

### Implementation notes (2026-10-27)

- **Deleted:** `data/tariff_pricing.py`, `data/grid_fees.py`, `settings/pricing_engine.py` (flag), `scripts/edibert_parity.py` (needs the old engine), the resolution part of `tariffs_store`, the dead historical matrix code, `tests/test_tariff_pricing.py`, `tests/test_grid_fees.py`. Moved: `netznutzung` profile helpers → `house_config/netznutzung.py`; month hints for the UI → `house_config/tariff_month_hints.py`; market zone → `house_config.edibert_tariffs.market_zone`; UI area lists and the grid-fee preview → `grid_area_view` / `profile_grid_fee` (Edibert).
- **Resolution** (`house_config/scenario_resolution.py`): always attaches `_edibert_pricing`; the tariff IDs and the *Eigener Festpreis* cents leave the settings; `_import_tariff_spec` / `_export_tariff_spec` / `market_zone` come from the Edibert tariff; `k_push_cent` stays only as the constant of a fixed export tariff (0 otherwise) for the history / log fallbacks (`K_PUSH_CENT`, MILP `fallback_k_push`); `_grid_fee_spec` and `FEED_IN_MODE` are gone. *Eigener Festpreis* import carries the profile country's VAT (no profile → no grid fee → rate 0, as before).
- **Adapter** (`data/edibert_slot_prices.py`): `market_for` (D1) fills the market dict with the missing quarter-hours of every hour an hourly settled spot tariff touches; the price series still covers only the input slots. `single_slot_cent` (`api.evaluate`, no hourly mean) is used only for legacy history log entries that stored one EPEX value per slot. `pricing_digest` for the fingerprint (file paths left out).
- **Seams:** live `_build_optimization_matrix` passes one `market_for` (via `resolve_market_slots`) to import and export; SE `matrix_builder` / `engine_scenario` / `reference_costs` pass `market_for_prices(prices_df, ctx)`; `reference_costs` prices export per window as a list. A missing scenario (`scenario_params=None`) means the live scenario, as for the feed-in settings before.
- **SE invoice:** `InvoiceGridFee` (`simulation/se_invoice_netznutzung.py`) from the reference: base price, rule labels, skipped rules (`status=<status>`), and `work(slot)` = `GridFee.work_cent` (net cent + rule ID).
- **Tests and fixtures:** the parity fixture stays as the Edibert golden (`tests/test_edibert_slot_prices.py`, T1 pinned); new `tests/test_edibert_p3b.py` (D1, D2, invoice, digest, `netznutzung`, Duo 2024-12 coverage, migration); migration fixture `v5_pre_scenario_feed_in`; backtesting fixture: the scenario `fixture_5kwh_fixed` gets `fixed_25ct_de` (new, DE so the fixture's DE-LU price CSV stays the market zone) and `fixed_35ct` instead of `k_push_cent: 3.5` (same prices), `entity_test` gets `fixed_25ct`; tests that wrote tariff files without `supplier_id` / `vat_percent` were fixed; `tests/fixtures/backtesting_fixtures.fixture_tariff_params` for hand-built SE scenarios; `tests/regression/l2_runner.py` always writes inline case pricing as tariff files.
- **Removed warning:** the loader warning "gross tariff without `vat_percent`" is gone; `vat_percent` is mandatory since P2 (`0` is an explicit choice).
- **Examples:** `share/config/backtesting_scenarios.example.json` uses tariffs (`dynamic_epex`, `__user_fixed__` 3.7 ct) instead of `k_push_cent` / `feed_in_mode`; both keys left the scenario schema.

### Results (2026-10-27)

- **SNAP comparison** (fixture pack with grid area AT-VBG, 2026-06-23 … 25, quarter-hour EPEX with negative midday prices; baseline with the old engine before the switch): quarter-hour spot (`at_vkw_strom_dynamisch` / `at_oemag_gesetzlicher_marktpreis`) and gross fixed (`at_verbund_v_strom_sterreich` / `…_sonneneinspeisung_fix`): every slot price, cost, flow and the invoice grid line (base + SNAP group) **identical**. Hourly settled (`awattar_at` / `at_smartenergy_smartsun_spot`): invoice identical; `k_act` / `k_push_act` differ in the 4 slots where a sunrise window ends mid-hour (05:00, now the full-hour mean, D1), and the MILP books 9 slots differently as a consequence.
- **Regression:** all 11 cases green, metrics equal to the goldens (input digests of the backtesting fixture changed).
- **Full suite:** 4865 passed, 30 skipped.

### Order

SNAP baseline with the old engine → B1 → B2 → B3 → B4 → B5 → B7 (gate: suite, regression, SNAP comparison) → B8 → B9. (B6, the Duo window, dropped with D3.)

### Done check

- [x] SE run with a SNAP grid area gives identical results before and after the switch for quarter-hour and fixed tariffs; hourly settled tariffs differ only at partial hours (D1, intended).
- [x] All 11 regression cases green, metrics unchanged; full suite green.
- [x] `data/tariff_pricing.py`, `data/grid_fees.py`, `settings/pricing_engine.py` and the resolution in `tariffs_store` are gone.
- [x] A horizon with an hourly settled tariff starting mid-hour prices without `PRICE_MISSING` (live and SE; `tests/test_edibert_p3b.py`).
- [ ] A live cycle on the maintainer site (needs the site migrated to data model 5 first; quarter-hour tariff there).

## P4a — Market prices, live chain (2026-10-27)

Status: **implemented** (see *Implementation notes*, *Results*, *Done check*). Backlog item *Edibert P4a* (Version 2.8). Goal: `data/live_market_prices.py`, `integrations/entsoe_client.py` and `integrations/awattar_client.py` are replaced by Edibert's market module; `price_source` per slot comes from Edibert's forecast method. **Done:** a live cycle runs on Edibert prices, recorder-format regression goldens green.

### Findings (2026-10-27)

- **The live chain is not public.** `MarketService` (cache → ENTSO-E → Energy-Charts → aWATTar, `edibert.market.service`) is used only by the publish product; `api.__all__` exports only `MarketArchive` / `market_range` (ranges, Energy-Charts only). An Edibert release is needed.
- **Window:** Earnie fetches from today 00:00 minus `MAX_MIRROR_LOOKBACK_DAYS` (7) for the mirror sources (`awattar_fetch_window`). `MarketService.load` fetches today and, after 12:00, tomorrow; earlier days come only from its cache (`HISTORY_DAYS = 7`), so a fresh install has no mirror sources.
- **Shadow mode:** all three Earnie fetchers go through `ext_get` / `safe_record` / `replay_ext_payload` with the feed keys `ext:prices:entsoe`, `ext:prices:energy_charts`, `ext:prices:awattar`. Edibert takes an injectable `HttpGet` (`get(url, params, timeout) -> str`), so Earnie can pass its shadow-aware transport. aWATTar is recorded today as parsed JSON, Edibert expects text.
- **CH:** Earnie falls back to the aWATTar AT series for CH; Edibert has deliberately no third source for CH.
- **`price_source`:** `tariff_price_series` runs no forecaster; the caller passes `forecast_from` / `forecast_method`, every `PricePoint` carries `market_cent` and `method`. Earnie's `resolve_market_slots` produces `day_ahead` / `mirrored` / `predicted` (OLS); OLS moves to Edibert only in P5.
- **Cache:** Earnie keeps `runtime/live_day_ahead_<zone>.json` (freshness logic in `data/live_price_cache.py`), Edibert its own cache file. `live_price_cache.py` is removed in P4b (SE side); the live path stops using it here.
- **Callers:** `main.py`, `ui/live_mode.py`, `data/live_prefetch.py` (all `fetch_live_day_ahead_prices(planning_end)`); tests `tests/main_run_harness.py`, `tests/early_start_runner.py`, `tests/test_entsoe_client.py`, `tests/test_live_market_prices_regression.py`, `tests/test_live_price_cache.py`.

### Decisions (2026-10-27, recommendations accepted by the maintainer)

1. **D1 — Edibert API:** new Edibert phase **`0.1.k`** makes the live chain public: a function in `edibert.api` (e.g. `market_live(zone, data_dir, tz, *, entsoe_token, get, history_days, now=None) -> MarketData`) plus `MarketData` in `__all__`. Additive, `API_VERSION` unchanged. Earnie raises the pin afterwards (tag proposal `v0.1.5`, version bump only with maintainer approval).
2. **D2 — mirror lead time:** the live call takes `history_days`; Edibert fetches the window from today minus `history_days` (like Earnie today), not only from its cache. No second chain via `market_range` in Earnie.
3. **D3 — CH:** Edibert's behaviour: no aWATTar AT substitute for CH. Missing slots → `MARKET_DATA_INCOMPLETE` → mirror. Behaviour change for CH sites, noted in the release notes.
4. **D4 — `price_source`:** slot labels stay `day_ahead` / `mirrored` / `predicted`. Mirror comes from Edibert (`MirrorForecaster`, same wall-clock rule, 7 days); OLS stays in Earnie until P5 but is passed as `forecast_method` to `tariff_price_series`. Mapping `exact` → `day_ahead`, `mirror` → `mirrored`, OLS → `predicted` in one helper.
5. **D5 — replays:** an Earnie transport adapter maps each request URL to its feed key and records the raw text; old aWATTar recordings (dict payload) are turned into text with `json.dumps` on replay. No converter for old recordings.

**Amendments during implementation (2026-10-27, maintainer):**

- **D1b — `MarketSourceError`:** Edibert's chain only falls through to the next source on its internal `SourceError`; an injected `get` raising anything else ends the call. New Edibert phase `0.1.l` exports it as `api.MarketSourceError` and documents the `get` contract; released as `v0.1.6` (after `0.1.k` as `v0.1.5`), Earnie pins `v0.1.6`.
- **D4 moved to P4b:** `resolve_market_slots` (and its mirror) also serves the SE / backtesting, partly with hourly history (mirror via the parent hour). Switching the mirror to Edibert's `MirrorForecaster` therefore moves to P4b, where the SE chain switches too. P4a keeps Earnie's `find_mirror_slot` and the `price_source` labels unchanged; nothing maps Edibert `method` yet.

### Part A — Edibert (`0.1.k`)

- Public live function + `MarketData` in `api`; `history_days` in `expected_window` / `load` (fetch window starts `history_days` before today 00:00; completeness check stays today / tomorrow).
- Tests: window with lead time, fresh install without cache, injected `get` is used for every source, CH without aWATTar, partial result reported.
- `docs/spec/api.md`, backlog, tag after approval.

### Part B — Earnie

- **B1** New module `data/edibert_live_market.py` with the same signature as `fetch_live_day_ahead_prices(planning_end)`, so the three callers only swap the import: zone from `land` via `eb.market_zone` (no silent "AT" for an unknown land), ENTSO-E token (`read_entsoe_api_token` moves here), `data_dir` under `runtime/`, shadow-aware `get` adapter (D5), `record_cycle_event(EVENT_DAY_AHEAD_FETCH)` only on a real fetch, Edibert warnings logged. Returns the same `timestamp` / `hour` / `price_buy` list as today.
- **B2** Mirror in `resolve_market_slots` from Edibert, `method` → `price_source` mapping (D4).
- **B3** Delete the three old modules, `tests/test_entsoe_client.py`, `tests/test_live_market_prices_regression.py` and the live parts of `tests/test_live_price_cache.py`; repoint `tests/main_run_harness.py` and `tests/early_start_runner.py`; remove `AWATTAR_URL` from the config if nothing else reads it.
- **B4** Tests: zone mapping, shadow record / replay per source, mirror parity (Edibert vs. the old `find_mirror_slot` on the same data), CH path, empty answer fails loud.
- **B5** Docs: German user docs on price sources (`docs/referenz/tarife-quellen.md`, possibly `docs/konfiguration/preise.md`: source order, CH, cache location); this section (implementation notes, results); shadow-mode workflow doc if it lists feed keys.

### Implementation notes (2026-10-27)

- **Edibert:** `0.1.k` (`api.market_live`, `MarketData`, `history_days` 0–7 in `MarketService`) and `0.1.l` (`api.MarketSourceError`); tags `v0.1.5`, `v0.1.6`; Earnie pin `v0.1.6`.
- **New module** `data/edibert_live_market.py`: `fetch_live_day_ahead_prices(planning_end)` with the old signature (callers `main.py`, `ui/live_mode.py`, `data/live_prefetch.py` only swap the import). `market_live(zone, runtime/edibert_market, tz, history_days=MAX_MIRROR_LOOKBACK_DAYS, now=planning_now(tz))`; zone from the house-profile `land` via `market_zone` (missing land: `ValueError`, unknown land: `EdibertLoadError`; the silent AT default is gone); `MARKET_DATA_UNAVAILABLE` → error log + `None` (the callers' existing "no prices" path), every other `EdibertError` propagates; Edibert notes are logged as warnings; `record_cycle_event(EVENT_DAY_AHEAD_FETCH)` once per call that sends a request. `planning_end` only gives the time zone now (the window is Edibert's).
- **Shadow transport** `_shadow_get`: URL host → feed key (`ext:prices:entsoe|energy_charts|awattar`, an unknown host fails), `requests.get` with a 30 s timeout; Prod records the raw text (ok and HTTP ≥ 400; connection errors with the ENTSO-E token redacted); Shadow replays first (old dict records → `json.dumps`) and falls back to an unrecorded live request; failures raise `api.MarketSourceError`. `read_entsoe_api_token` moved here.
- **Deleted:** `data/live_market_prices.py`, `data/live_price_cache.py` (its only user was the old orchestrator, so it goes now, not in P4b), `integrations/entsoe_client.py`, `integrations/awattar_client.py`, `tests/test_entsoe_client.py`, `tests/test_live_market_prices_regression.py`, `tests/test_live_price_cache.py`, `tests/fixtures/entsoe/`. `AWATTAR_URL` stays (SE and analysis scripts read it).
- **Behaviour changes (release notes):** CH has no aWATTar AT substitute (D3); the cache `runtime/edibert_market/market_<zone>.json` replaces `runtime/live_day_ahead_<zone>.json` (the old file is ignored); the expected window ends with today / tomorrow instead of the planning end, and a partial answer is asked again at most every 10 minutes; a missing or unknown `land` fails instead of using AT.
- **Tests:** `tests/test_edibert_live_market.py` (feed keys, rows with 7 lead days, cache hit without request, ENTSO-E failure recorded redacted with fall-through, HTTP error → `MarketSourceError`, Shadow replay of old dict records without network, unrecorded Shadow live fallback, CH without aWATTar → `None`, missing / unknown land); `tests/main_run_harness.py` patches the new module; `tests/early_start_runner.py` fakes the Energy-Charts HTTP answer instead of patching the old orchestrator.
- **Docs:** `docs/konfiguration/preise.md`, `docs/einrichtung/betrieb.md` (German), Shadow spec (private repo Earnie-Projekt, `Betrieb/Shadow-Mode-Spec.md`).

### Results (2026-10-27)

- **Full suite:** 4798 passed, 19 skipped, run with `-p no:hypothesispytest` and without `tests/test_storage_roundtrip.py`: Windows application control currently blocks the `hypothesis` native extension on this machine (`ImportError: DLL load failed`, file unchanged since 2026-10-23), so the plugin cannot load. `tests/test_early_start_equivalence.py` (4 cases) green.
- **Regression:** all 11 cases green, metrics unchanged, no `--update-golden`. Run with `EARNIE_CONFIG_PATH=tests/fixtures/backtesting/config.json`: without it, the runner's import-time config load reads the maintainer site (`earnie_env/config`), which is not migrated to data model 5 yet, and fails before any case.

### Order

Part A (release, pin) → B1 → B2 → B3 → B4 → B5 → gate: full suite (`scripts.run_pytest`), `scripts.run_regression` without `--update-golden`, live cycle on the maintainer site (the site needs the data-model-5 migration first, see P3b). The pandas-free chain (`fetch_energy_charts_prices` in `data/data_loader.py`) is P4b.

### Done check

- [x] Edibert `0.1.k` (and `0.1.l`) released, Earnie pin raised to `v0.1.6`.
- [x] The three old modules are gone; live callers use Edibert.
- [x] Shadow record / replay works for all three sources (unit tests; no Shadow run against a real feed yet).
- [x] Full suite (see *Results* for the hypothesis exclusion) and all regression cases green, goldens unchanged.
- [ ] A live cycle on the maintainer site runs on Edibert prices (needs the data-model-5 migration of the site first).

## P4b — Market prices, SE and backtesting (2026-10-27)

Status: **implemented** (see *Implementation notes*, *Results*, *Done check*). Backlog item *Edibert P4b* (Version 2.8). Goal: the SE and backtesting load market prices through Edibert's long-range archive (`api.MarketArchive`), the mirror of `resolve_market_slots` comes from Edibert's `MirrorForecaster` (live and SE), `price_source` follows from Edibert's method names, and the Energy-Charts / aWATTar part of `data/data_loader.py` is gone. **Done:** SE and backtesting run on Edibert prices, SNAP unchanged, the removed modules are gone, chain pandas-free.

### Findings (2026-10-27)

- **Loader:** `load_market_prices` (about 17 callers: `scripts/run_backtesting.py`, `simulation/backtesting_single_window.py`, diagnosis scripts, `greenfield/`, tests) asks Energy-Charts first and aWATTar (hourly) on any failure; without a market zone it silently uses `DE-LU`. `price_source: csv` reads an Energy-Charts CSV; the backtesting fixture (`tests/fixtures/backtesting/config.json`, also used by the regression runner) uses it. The L2 regression cases use synthetic prices.
- **Edibert:** `MarketArchive` / `market_range` (Energy-Charts only, one cache file per UTC month, HTTP 429 waited out), `MirrorForecaster` and `builtin_forecaster` are public since `0.1.g`; no Edibert release is needed. An injected `get` cannot signal HTTP 429 (`RateLimited` is internal), so only Edibert's own `http_get` gets the 429 retry.
- **Shadow:** the SE path recorded its Energy-Charts answers under `ext:prices:energy_charts`, the live feed key; a backtest in Prod could thus put a month payload where a live replay expects the live answer.
- **Mirror:** Earnie's `find_mirror_slot` takes the exact quarter-hour or its parent clock hour (hourly history) and steps back with aware datetime arithmetic; `MirrorForecaster` takes exact quarter-hours only and steps back in local wall time (`fold=0`). DST days may differ.
- **`mirrored_from`:** Edibert does not report the source slot; Earnie writes it only into the profile rows (`data/profile_manager.py`) and two tests.
- **`price_source`:** `tariff_price_series` takes one `forecast_from` / `forecast_method` per call; Earnie mixes `predicted` and `mirrored` slots (OLS falls back to the mirror per slot), and the method does not change `k_act`.

### Decisions (2026-10-27, recommendations accepted by the maintainer)

1. **D1 — SE source:** `api.MarketArchive(zone, runtime/edibert_market)` with Edibert's own `http_get`, no shadow transport (429 retry works; SE runs no longer write the live feed key). Behaviour change: no aWATTar fallback in the SE; Energy-Charts failing without a cache fails loud (`MARKET_DATA_UNAVAILABLE`). New monthly cache `runtime/edibert_market/market_archive/<zone>/YYYY-MM.json`.
2. **D2 — boundary:** new module `data/edibert_market_range.py`, `load_market_prices(start, end, sim_cfg, *, market_zone)` builds today's DataFrame from the `MarketRange` (naive planning-time index, column `price_cent_kwh`, the repeated autumn hour averaged as before); missing slots are logged as warnings; a missing market zone is an error (no silent `DE-LU`). The `awattar_url` parameter goes from every caller; `AWATTAR_URL`, `house_config/awattar_api.py` and the dead `awattar_fetch_window` go too.
3. **D3 — CSV mode:** the Energy-Charts CSV reader stays as the offline source (fixtures, downloaded files) and moves into the new module; no config migration.
4. **D4 — mirror:** missing slots in `resolve_market_slots` are filled by `api.builtin_forecaster("mirror", tz)` on the known prices in UTC; hourly entries are expanded to their four quarter-hours first (for the Day-Ahead lookup and the mirror). `find_mirror_slot` and `mirrored_from` go; the error for a slot without a mirror source stays. Parity test against the old mirror, DST weeks included; differences are documented.
5. **D5 — `price_source`:** one helper maps the method: `exact` → `day_ahead`, `mirror` → `mirrored`, OLS → `predicted`, anything else is an error. The resolver keeps setting the labels; Earnie's pricing calls pass no `forecast_method` to Edibert until P5.

### Steps

- **B1** New module (D2, D3), all callers switched.
- **B2** Mirror and method mapping in `data/market_prices.py` (D4, D5).
- **B3** Delete the Energy-Charts / aWATTar functions of `data/data_loader.py`, `AWATTAR_URL`, `house_config/awattar_api.py`; `tests/test_data_loader_market_prices.py` replaced.
- **B4** Tests: `MarketRange` → DataFrame, autumn hour, missing zone, mirror parity (DST, hourly history), method mapping.
- **B5** Docs: `docs/konfiguration/preise.md` (German), this section (implementation notes, results), backlog.

### Implementation notes (2026-10-27)

- **New module** `data/edibert_market_range.py`: `load_market_prices(start, end, sim_cfg, timeout=30, *, market_zone=None)`. `price_source: api` → `api.MarketArchive(zone, runtime/edibert_market, timeout)` with Edibert's own `http_get` (D1); the `MarketRange` (UTC keys) becomes the old frame (naive `Europe/Vienna` index, `price_cent_kwh`, the repeated autumn hour averaged); Edibert notes (`MARKET_RANGE_INCOMPLETE`, `MARKET_SOURCE_FAILED`, …) are logged as warnings; `MARKET_DATA_UNAVAILABLE` propagates. Any other `price_source` reads the Energy-Charts CSV of `path_price` as before (the schema documents "other values = CSV", so no new error there). Zone: `market_zone`, else `energy_charts_bzn`, else `ValueError` (the loader's own `DE-LU` default is gone; `config_loaders` still defaults `energy_charts_bzn` to `DE-LU`, unchanged). The request window is `[start 00:00, end + 1 day 00:00)` local, fetched as whole UTC months.
- **Callers:** `scripts/run_backtesting.py`, `simulation/backtesting_single_window.py`, the diagnosis scripts and two tests import from the new module and no longer pass `awattar_url`; `load_market_prices_for_scenario` (only its own test used it) is gone.
- **Deleted:** in `data/data_loader.py` everything from `_ensure_csv_exists` to `load_market_prices_for_scenario` (Energy-Charts HTTP with its shadow recording, aWATTar, the CSV reader, zone constants) — the module keeps only the simulation-window helpers; `house_config/awattar_api.py`, `AWATTAR_URL` in `settings/config_loaders.py`, `awattar_fetch_window` in `data/market_prices.py`; `tests/test_data_loader_market_prices.py` → `tests/test_data_loader_window.py` (window tests only).
- **Mirror (D4):** `resolve_market_slots` builds `known` once per call (`_known_quarter_hours`: an `:00` sample fills its missing `:15/:30/:45`, keys UTC), takes the Day-Ahead price from it and fills a missing slot with `api.builtin_forecaster(METHOD_MIRROR, planning tz)`; no source within 7 days keeps the old `ValueError` ("Spiegelquelle"). `find_mirror_slot`, `_price_from_indexed_slot` and `mirrored_from` (also in the profile rows of `data/profile_manager.py`) are gone. `MAX_MIRROR_LOOKBACK_DAYS` stays an Earnie constant (7, as Edibert's): `edibert.api` does not export Edibert's.
- **`price_source` (D5):** `price_source_for_method` (`exact` / `mirror` / `ols`, `METHOD_OLS = "ols"`) sets the label of every resolved slot; an unknown method raises.
- **Speed-up (maintainer request during P4b):** `build_market_data_as_of` ran `iterrows` over the whole price series per call (0.66 s for a year of quarter-hours), once per anchor and scenario with `mirror` / `forecast` and per `market_for` call. It now cuts the series by index first (`not_before`, plus the Day-Ahead cutoff, one hour of margin each side, aware or naive index) and loops over the slice only; `resolve_backtesting_slot_prices` passes `not_before` = first target slot − 8 days (mirror 7 days, live bias 48 h never read further back).
- **Tests:** `tests/test_backtesting_prices.py` (slice equals the full scan from `not_before` on); `tests/test_edibert_market_range.py` (real `MarketArchive` with a fake `http_get`: Vienna index and autumn hour, month cache without a second request, zone from `energy_charts_bzn`, no zone, no answer without cache → `MARKET_DATA_UNAVAILABLE`, CSV column / missing column / missing path / missing file); `tests/test_market_prices.py` (mirror from an hourly sample, wall clock across the spring DST change, method mapping; `mirrored_from` asserts and the `awattar_fetch_window` test removed).
- **Docs:** `docs/konfiguration/preise.md`, `docs/konfiguration/overview.md`, `docs/referenz/tarife-quellen.md`, `docs/einrichtung/betrieb.md` (German); `share/config/config.schema.json` descriptions of `price_provider` / `energy_charts_bzn`.
- **Behaviour changes (release notes):** no aWATTar fallback in the SE / backtesting; new monthly price cache `runtime/edibert_market/market_archive/<zone>/`; a missing market zone fails; `mirrored_from` is no longer in the profile rows.

### Results (2026-10-27)

- **Full suite:** 4798 passed, 19 skipped (same hypothesis exclusion as P4a: `-p no:hypothesispytest`, without `tests/test_storage_roundtrip.py`).
- **Regression:** all 11 cases green, metrics unchanged, no `--update-golden` (run with `EARNIE_CONFIG_PATH=tests/fixtures/backtesting/config.json`, see P4a).
- **Price comparison 2025** (old `fetch_energy_charts_prices` in one request vs. `MarketArchive`, AT / DE-LU / CH): every slot both deliver is equal (max |diff| 0.000000 ct). The new loader has more rows: Edibert asks month by month and gets quarter-hours, the old one-year request came back hourly for AT / DE-LU up to 2025-09 and for CH all year (same values; the SE expanded them anyway). The autumn hour 2025-10-26 / 2026-10-25 is averaged as before. Edibert waited out several HTTP 429 answers on the CH months.
- **Mirror comparison 2025** (old `resolve_market_slots` vs. Edibert mirror, planning moments daily 10:00 and 13:00, 144 slots each, 102,528 slots per zone, a third mirrored): 12 slots per zone differ, all 2025-03-30 02:00–02:45, a wall time that does not exist (spring DST change). The old code treated the non-existent wall time as its own slot and mirrored 02:xx of the day before; Edibert works on the real instant (01:xx UTC = 03:xx CEST) and takes that slot's Day-Ahead price or mirrors 03:xx. Intended: the new value belongs to the instant that the slot really is.
- **Slice of `build_market_data_as_of`:** resolved slots with the slice equal those of a full scan in all 1,420 calls (AT, CH, 2025, daily 10:00 and 13:00); 11.3 s vs. 185.8 s (AT) and 7.3 s vs. 129.4 s (CH).
- **SE comparison (SNAP):** maintainer site, copied outside the repo and migrated to data model 5 there, September–October 2026, `--workers 20`, `HEAD` before P4b vs. P4b. `k_act` / `k_push_act` identical in all 16,417 rows (`perfect` and `mirror`); totals differ by 1–6 cent in the Live scenario, all other scenarios equal. Two baseline runs without any code change differ by 4 cent and 200 rows (CBC `strict_slow` windows), so the difference is solver noise, not prices. Run time with `mirror`: 98–113 s before, 61 s with the slice (`perfect`: 69–70 s).

### Order

B1 → B2 → B3 → B4 → B5 → gate: full suite (`scripts.run_pytest`), `scripts.run_regression` without `--update-golden`, a script comparing old and new prices for 2025 (AT, DE-LU, CH), an SE before / after comparison on the fixture config. An SE run on the maintainer site needs its data-model-5 migration first.

### Done check

- [x] SE and backtesting load prices through `MarketArchive`; the Energy-Charts / aWATTar code of `data/data_loader.py` is gone.
- [x] Mirror from Edibert for live and SE, `price_source` through the method mapping.
- [x] Full suite and all regression cases green, goldens unchanged; price comparison 2025 and SE comparison documented.
- [x] An SE run on the maintainer site: done on a migrated copy outside the repo (see *Results*); the site itself still needs its data-model-5 migration.

## P5 — Forecast handover (2026-10-27)

Status: **implemented** (see *Implementation notes*, *Results*, *Done check*). Backlog item *Edibert P5* (Version 2.8). Goal: Earnie's OLS price model becomes an object that implements Edibert's `api.Forecaster` interface (no key), the missing-slot chain of `resolve_market_slots` runs OLS and mirror through that one interface, the forecast horizon is capped at 72 h, `mirror` and `hold` stay Edibert's free methods. **Done:** parity test — forecast through the new path equals today's OLS output on recorded inputs.

### Findings (2026-10-27)

- **Edibert side is ready:** `api.Forecaster` (`forecast(known, start, end) -> {UTC slot: cent}`, slots it cannot price are left out), `MirrorForecaster`, `HoldLastForecaster` and `builtin_forecaster` are public since `0.1.f` (pin `v0.1.6`). The library has **no function that runs a forecaster**: only the product's `Publisher._forecast` calls one; `tariff_price_series` takes finished market prices plus `forecast_from` / `forecast_method`. The 72 h cap exists only as `MAX_FORECAST_HOURS` in `edibert.publish.config` (product layer, not in `api`).
- **Earnie's OLS path** (`data/market_prices.py`): per missing slot `_lookup_forecast_epex` (feature row of the quarter-hour, else of its parent hour; tz-naive index handled) → `predict_prices` (model incl. its own `bias_correction_cent_kwh`) → plus the rolling live bias (`_resolve_live_bias_cent`, computed once per call over the 48 h before the first target slot, capped ±12 ct) → label `predicted`. A slot without a feature row falls back to the mirror per slot; no mirror source → `ValueError`.
- **Inputs:** live builds the feature frame from Energy-Charts EU power (archive or forecast mode, `build_live_feature_frame_for_slots`, 1 h back-off after a failure); SE / backtesting read `data/cache/price_training_*.csv` (not committed) and the model from `share/data/price_model_coefficients.json` or `--forecast-model`.
- **Fallbacks today** (logged warnings, but not loud): no model file or no feature frame → `resolve_market_slots_kwargs` switches the whole call to `mirror`; per slot without features → mirror. The `price_source` label shows the result per slot.
- **SE live bias:** `resolve_backtesting_slot_prices` passes no `live_bias_*` arguments, so the default `live_bias_enabled=True` applies and the SE computes the bias from `build_live_feature_frame_for_slots` (Energy-Charts, not the training CSV). Probably unintended; parity keeps it, see D5.
- **Horizon:** no cap today. Live horizons are ≤ 48 h past the last Day-Ahead price; SE windows the same per anchor. Nothing in Earnie forecasts beyond 72 h, so the cap is a guard, not a behaviour change.
- **Dead code:** `build_predicted_slot` and `predict_epex_cent_for_features` in `data/price_forecast_live.py` have no callers.

### Decisions (2026-10-27, recommendations accepted by the maintainer)

1. **D1 — where the chain runs:** *(recommended)* Earnie runs the chain itself, as for the mirror in P4b: `resolve_market_slots` calls `ols.forecast(known, start, end)` over the missing range, then the mirror for the slots OLS left out. No Edibert release. *Alternative:* Edibert `0.1.m` adds a library function (e.g. `api.forecast_market(known, start, end, forecasters, max_hours=72)` returning price and method per slot), used by Earnie and the publisher; cleaner "handover", but an Edibert release, pin bump and a publisher refactor for no behaviour gain.
2. **D2 — the forecaster object:** new module `data/ols_forecaster.py`, class `OlsForecaster(model, feature_frame, *, bias_cent=None, tz)` implementing `api.Forecaster`: pure (no network, no file access), takes `_lookup_forecast_epex` logic, returns only slots with a feature row (as Edibert's mirror: never guessed). Constant `METHOD_OLS = "ols"` moves there; `price_source_for_method` keeps mapping it to `predicted`.
3. **D3 — live bias:** stays outside the forecaster: computed as today (`_resolve_live_bias_cent`) and handed in as `bias_cent`. Keeps `forecast()` pure and the network calls where they are; parity is trivial. Extra fields of predicted slots (`forecast_model_path`, `eu_power_live_source`, `live_bias_cent_kwh`) stay Earnie labels on the resolved row.
4. **D4 — 72 h cap:** Earnie constant `MAX_FORECAST_HOURS = 72` (as `MAX_MIRROR_LOOKBACK_DAYS`; `edibert.api` does not export Edibert's), checked once per `resolve_market_slots` call for the forecast span (first missing slot → end of the last target slot). Longer → `ValueError`, no truncation. Applies to OLS and mirror alike. Optional Edibert follow-up: export `MAX_FORECAST_HOURS` in `api` (then Earnie imports it).
5. **D5 — fallbacks:** P5 is a parity step, so the existing fallbacks (whole call to mirror without model / features; per-slot mirror without a feature row) stay as they are and are documented here; they are visible through `price_source`. The SE live-bias default (finding above) is **not** changed in P5; it becomes a separate bugfix item for the maintainer to decide (keep, or `live_bias_enabled=False` / bias from the training CSV in the SE).
6. **D6 — `forecast_method` to Edibert:** still not passed. `tariff_price_series` takes one method per call while Earnie mixes `predicted` and `mirrored`, and the method does not change `k_act` (P4b D5 stays).

### Steps

- **S0** Golden first (old code): script `scripts/record_ols_forecast_golden.py` records inputs and today's output into `tests/fixtures/edibert_forecast/`: model (frozen copy of `price_model_coefficients.json`), a feature frame (Energy-Charts EU power, public data, ~10 days incl. a DST change, hourly and quarter-hour index, one tz-naive variant), Day-Ahead prices with a gap, the resolved rows of `resolve_market_slots(..., missing_price_strategy="forecast")` for several planning moments, with bias off / on / capped and with feature gaps (mirror fallback). Committed before the refactor.
- **S1** `data/ols_forecaster.py` (D2), unit tests: interface conformance (`isinstance` check against the protocol is not available — call through an `api.Forecaster`-typed helper), quarter-hour / parent-hour lookup, tz-naive index, gaps left out, bias added.
- **S2** `resolve_market_slots` switched (D1, D3, D4): missing slots collected, `OlsForecaster.forecast` over their span (strategy `forecast`), mirror for the rest, labels via `price_source_for_method`; `_lookup_forecast_epex`, `_resolve_missing_slot` and the per-slot mirror call go. Signature unchanged (callers: `data/backtesting_prices.py`, `data/live_prefetch.py`, `data/profile_manager.py`, `scripts/compare_live_price_prognosis_research.py`).
- **S3** Parity test `tests/test_edibert_p5_forecast.py`: new path vs. S0 golden, every row equal (`price_buy` within 1e-9, `price_source`, extra fields); 72 h cap (72 h passes, 72 h + 15 min raises).
- **S4** Delete `build_predicted_slot`, `predict_epex_cent_for_features`; adapt `tests/test_market_prices.py` / `tests/test_backtesting_prices.py` patches of removed private functions.
- **S5** Docs: this section (implementation notes, results), backlog (P5 → [Erledigt](../../backlog/Backlog-Erledigt.md), new bugfix item for the SE live bias if D5 is accepted). German user docs: no behaviour change expected; check `docs/konfiguration/preise.md` (`missing_price_strategy`) and mention the 72 h limit there. Edibert backlog: close "Earnie's OLS model is handed in as a forecaster object".

### Implementation notes (2026-10-27)

- **Golden (S0):** `scripts/ols_forecast_golden.py` (`record`, `golden`) holds the recording and the case builder that the test reuses. Recorded once into `tests/fixtures/edibert_forecast/`: the model (copy of `share/data/price_model_coefficients.json`), the archive EU features (`_build_archive_feature_frame`, naive Vienna index, the repeated autumn hour as two rows) and the AT Day-Ahead prices in UTC (`MarketArchive`) for 2025-03-24 → 04-06 and 2025-10-20 → 11-02. 58 cases: four planning moments per window (10:00 before, 14:00 after the Day-Ahead publication), 72 h with every feature-frame variant (hourly naive, quarter-hourly naive, hourly aware, gaps on three evenings / one day), bias off / on / capped at 0.3 ct, a 48 h horizon, and hourly Day-Ahead history. The live bias reads its lookback features through `build_live_feature_frame_for_slots`, patched to serve the recorded frame. The golden (`expected.json`, compact rows `[slot, hour, price_buy, price_source, {extra fields}]`) was written with the pre-P5 code before any change.
- **`data/ols_forecaster.py`:** `OlsForecaster(model, feature_frame, *, tz, bias_cent=None)`, `forecast(known, start, end)` over UTC quarter-hours; the lookup is the old `_lookup_forecast_epex` (quarter-hour row, else its clock hour; naive or aware index); slots without a row are left out; the bias is added before the resolver rounds to 4 decimals (same order as before). `METHOD_OLS` moved here. No network, no file access.
- **`resolve_market_slots`:** normalises the targets once, collects the missing UTC slots, checks the span (first missing slot → end of the last one) against `MAX_FORECAST_HOURS = 72` (`ValueError`), runs `OlsForecaster.forecast` over the span (strategy `forecast` with model and frame), then Edibert's mirror over the remaining slots in one call; the error for a slot without a mirror source stays. Labels and extra fields of predicted rows unchanged; signature unchanged. `_lookup_forecast_epex` and `_resolve_missing_slot` are gone.
- **Removed:** `build_predicted_slot`, `predict_epex_cent_for_features` (`data/price_forecast_live.py`, no callers). Two tests in `tests/test_market_prices.py` patch `OlsForecaster._predict` instead of the removed lookup.
- **Edibert:** no change, no release; its backlog note on the OLS handover (`0.1.e2`) is updated.

### Results (2026-10-27)

- **Parity:** all 58 golden cases equal (same slots, labels and extra fields; `price_buy` within 1e-9, the bias within 1e-12; in fact identical): 10,272 predicted, 176 mirrored (feature gaps) and 5,488 Day-Ahead slots. The 72 h tests pass (72 h passes, 72 h 15 min raises).
- **Full suite:** 4855 passed, 26 skipped (same hypothesis exclusion as P4a). **Regression:** all 11 cases green, metrics unchanged, no `--update-golden`.
- **SE before / after:** fixture config copied outside the repo with `price_source: api` (the fixture CSV has DE-LU prices only, the house is AT), June 2026 (the only month with fixture consumption data, 2026-06-21 → 06-25), `price_strategy=forecast`, training CSV built for 2026-06-10 → 06-30, `--workers 20`, `--allow-stale-cons-data` (fixture consumption data has no meta). `HEAD` before P5 (worktree) vs. P5: `backtesting.csv` identical in every column and row (3,213 rows, all scenario totals equal). Limited value: the fixture scenarios use fixed tariffs (`k_act` 25 ct, `k_push_act` 3.5 / 3.7 / 5.0 ct), so the forecast prices do not reach the costs; the run shows the SE path end to end, the parity proof is the golden test.
- **Run time and Energy-Charts:** each SE run took about 28 min, almost all of it waiting for Energy-Charts: the SE live bias (finding above, bugfix item) fetches EU power per window from 20 processes at once, Energy-Charts answers HTTP 429, and after five retries (2–32 s) a country is skipped and the EU sum is taken over the remaining ones (43–45 skips per run). The skipped countries differ between runs, so the bias of two SE runs is not reproducible. Follow-up proposal: a monthly disk cache for the Energy-Charts archive calls and fail-loud instead of a shrunken country sum, in **Edibert P6** (shared, caching access).

### Order

S0 (commit golden on old code) → S1 → S2 → S3 → S4 → S5 → gate: full suite (`scripts.run_pytest`), `scripts.run_regression` without `--update-golden`, an SE before / after with `price_strategy=forecast` on the fixture config over a short window (needs `python -m scripts.build_price_training_dataset` locally; `--workers N`).

### Done check

- [x] `OlsForecaster` implements `api.Forecaster`; the missing-slot chain runs OLS and mirror through it.
- [x] Parity test on recorded inputs green (golden recorded with the pre-P5 code).
- [x] Forecast span capped at 72 h (error beyond).
- [x] Full suite and all regression cases green, goldens unchanged; SE before / after with `forecast` identical (fixed tariffs only, see *Results*).

## P6 — Shared weather and power-data access (plan 2026-10-27)

Status: **done 2026-10-27** (D1–D8 accepted 2026-10-27; S0–S7 and the gate done; see *Implementation notes*, *Done check*). Backlog item *Edibert P6* (Version 2.8), extended by the P5 findings on Energy-Charts. Goal: one standalone, caching package without Earnie imports for the public data feeds Earnie fetches itself (Open-Meteo archive and forecast, Energy-Charts EU power), so that SUSI P3a can add `direct_normal_irradiance` in one place and the SE stops hammering Energy-Charts. **Done:** one access path, cache test, import-isolation test, and (new) fail-loud on a missing country instead of a shrunken EU sum.

### Findings (2026-10-27)

- **Five HTTP paths, three retry loops:**
  - `data/eu_market_features.py` `_http_get_json`: Energy-Charts `public_power` per country and month, AT Day-Ahead `price` (training set only), Open-Meteo archive per EU grid point and month, Open-Meteo forecast per point. Retries only 429 (2–32 s, 5 attempts); after five 429s the error reads `… fehlgeschlagen (…): None` because `last_error` is not set on the status-code path.
  - `eu_market_features._fetch_open_meteo_forecast_grid`: one multi-location forecast call with plain `requests.get` and no retry; on any error it falls back to one call per grid point.
  - `data/open_meteo_solar_archive.py` `_archive_http_get`: Open-Meteo archive for the house site (temperature, tilted irradiance), retries 429 / 502 / 503 / 504 within an optional `climate_fetch_budget`.
  - `data/outdoor_forecast.py` `_open_meteo_payload`: Open-Meteo forecast for the house site through the shadow transport (replay in shadow mode, record in prod).
  - Out of scope: `data/pv_forecast.py` (forecast.solar) and `data/edibert_live_market.py` (Day-Ahead prices, Edibert P4a).
- **Caches today:**
  - The house-site archive has a disk cache (`data/cache/open_meteo_utc/`, one JSON per lat / lon / tz / start / end / surfaces, env `EARNIE_OPEN_METEO_CACHE_PATH`) plus an mtime-checked memory cache. Regression cases ship these files as frozen fixtures (`tests/regression/climate_fixture.py` patches `_load_bundle_from_cache` / `_save_bundle_to_cache` / `_fetch_hourly_archive_chunk`).
  - Energy-Charts power and the EU grid weather (archive) have **no disk cache**, only process-local memory caches in `data/price_forecast_live.py` (45 min TTL, 1 h back-off after a failure). The house-site forecast has a 30 min memory cache keyed on the planning clock.
- **Earnie imports in the access code:** `config.get_global_timeout`, `runtime_store.planning_clock` (`planning_now`, `cache_entry_fresh`), `runtime_store.env_vars.read_env`, `runtime_store.shadow.*`, `runtime_store.cycle_duration_stats`, and `archive_latest_complete_date` reaching back into `data.price_forecast_live`. These must become parameters or stay in Earnie-side adapters.
- **Silent shrink:** `fetch_eu_power_hourly` skips a country after an error and sums the rest; the OLS model was trained on all 12 countries, so a missing Germany lowers `eu_wind_mw` / `eu_load_mw` by a third without any label on the forecast. In the P5 SE runs 43–45 countries were skipped per run (HTTP 429 under 20 workers), so the bias was not reproducible. The EU weather grid already fails loud on a missing point.
- **Who pays for the 429s:** live fetches a few days per cycle and is rarely throttled. The SE fetches the same days from every worker, but only because of the live-bias bug (*Backlog-Bugfixes*, item from P5): SE features otherwise come from the training CSV. Training (`scripts.build_price_training_dataset`) fetches months × 12 countries once.
- **Edibert:** its `MarketArchive` already caches Day-Ahead prices per month on disk and waits out 429, so the Edibert repo is not touched. Its research item *Shared library (weather)* says "no shared cache building block in advance"; P6 is the moment that note was waiting for.

### Decisions (open, recommendations marked)

1. **D1 — package and scope:** *(recommended)* new top-level package `opendata/` in Earnie (working name; checked for a free PyPI name before the own repo), added to `[tool.setuptools.packages.find]`. Scope: an HTTP layer, a disk cache, an Open-Meteo client (archive and forecast, single and multi-location, any hourly variables) and an Energy-Charts client (`public_power`, `price`). Feature logic stays in Earnie: grid-point weights, the country list, the EU sum, PV / thermal conversion, planning-time conversion. *Alternative:* weather only (as the backlog text says), Energy-Charts stays in `eu_market_features`; then the cache and fail-loud work is done twice or not at all.
2. **D2 — no Earnie imports through injection:** the package exposes a `Session(cache_dir, timeout_s, transport=None)`. The default transport is `requests` with the shared retry policy. Earnie builds the session in one place (`data/opendata_session.py`): timeout from `config`, cache dir from `EARNIE_OPEN_METEO_CACHE_PATH` / a new `EARNIE_ENERGY_CHARTS_CACHE_PATH`, the shadow-aware transport for the house-site forecast. Planning clock, "last complete archive day", memory TTL caches and `climate_fetch_budget` stay Earnie-side; the package only gets explicit dates.
3. **D3 — one retry policy:** retry 429 / 502 / 503 / 504 with exponential backoff (2–32 s, 5 attempts), honour `Retry-After` when present, keep a per-host pause (Energy-Charts 0.75 s as today), raise the last HTTP error (not `None`), keep `ApiUnreachableError` for connection errors and timeouts. The multi-location forecast call gets the same retries; its per-point fallback stays (same data, not a silent change of meaning).
4. **D4 — Energy-Charts disk cache:** one file per country and calendar month (parsed hourly frame, JSON `orient="split"` like the Open-Meteo cache), under `data/cache/energy_charts/`. Only **settled** days are written: days older than 2 days at fetch time (Energy-Charts revises the most recent load and generation values); younger hours are always fetched and never stored. A month file records the last settled day it covers; a request beyond it fetches the month again and rewrites the file. Writes are atomic (temp file + `os.replace`) so parallel SE workers can share the directory. The same cache serves the EU grid weather archive (one file per grid point and month). Tests never write the repo cache (same conftest guard as Open-Meteo).
5. **D5 — house-site Open-Meteo cache unchanged:** file names, format and the regression patch points (`_load_bundle_from_cache`, `_save_bundle_to_cache`, `_fetch_hourly_archive_chunk`, `open_meteo_cache_path`) stay as they are; only the HTTP call underneath moves into the package. Otherwise every regression climate fixture would have to be re-recorded (needs network, changes the input fingerprints). A unified per-month cache for the house site is a later step.
6. **D6 — fail-loud on a missing country:** *(recommended)* `fetch_eu_power_hourly` raises when any country fails (error names the countries and the cause). Consequences, all visible:
   - Live: `build_live_feature_frame_for_slots` already catches the error, so the whole call falls back to the mirror (P5 D5, label `mirrored`, warning, 1 h back-off). OLS on a distorted feature is replaced by the mirror.
   - Training: the dataset build stops instead of training on a shrunken sum.
   - SE: no effect once the live-bias bugfix (D7) is in; before that, an SE run fails instead of producing a non-reproducible bias.

   German user doc `docs/konfiguration/preise.md`: one sentence that missing EU power data leads to the mirror. *Alternative:* keep the skip but label the slots and log an error; the forecast stays distorted.
7. **D7 — SE live bias first:** fix the bugfix item before P6 (own commit, small), so P6 is measured on an SE that does not fetch EU power. Variants:
   - *(recommended)* bias from the training CSV: the same rolling Day-Ahead minus OLS over the 48 h before each anchor, computed from the CSV features and the SE's own Day-Ahead prices. Mirrors live behaviour without network.
   - Bias off in the SE (`live_bias_enabled=False`): simplest, but the SE then underestimates what live achieves.
   - The values from `config.json`: same as live configuration, but still needs a feature source, so it is the first variant plus a config switch.

   Either way the default `live_bias_enabled=True` of `resolve_market_slots` goes (callers pass it explicitly).
8. **D8 — SE prewarm:** not needed once D7 is in (the SE fetches nothing). If the SE ever needs archive power again, the parent process fills the cache for the window's months before starting the workers. Not built in P6.

### Steps

- **S0** Bugfix SE live bias (D7), separate commit and backlog item; SE before / after on the fixture config (expect identical totals with fixed tariffs, run time down from ~28 min).
- **S1** Parity recording on the old code: a fake transport records every request and response of the public entry points (`fetch_eu_power_hourly`, `fetch_eu_weather_hourly`, `fetch_eu_weather_forecast_hourly`, `fetch_at_day_ahead_hourly`, `build_open_meteo_climate_bundle`, `get_hourly_outdoor_forecast_c`, `get_hourly_tilted_irradiance_forecast_wm2`) for a short window incl. a DST change, plus their outputs. Stored in `tests/fixtures/opendata/` (public data: Open-Meteo CC BY 4.0, Energy-Charts CC BY 4.0, attribution in the fixture README). Committed before the refactor.
- **S2** `opendata/` skeleton: `http.py` (D3), `cache.py` (D4), `open_meteo.py`, `energy_charts.py`; import-isolation test (AST scan of `opendata/**`: only stdlib, `requests`, `pandas`, `numpy`; no Earnie top-level package).
- **S3** Open-Meteo moved: house-site archive (`_archive_http_get` → package; D5 keeps the cache layer), house-site forecast (shadow transport injected), EU grid archive and forecast.
- **S4** Energy-Charts moved: `public_power` and `price` through the package with the monthly disk cache (D4); `fetch_eu_power_hourly` fail-loud (D6). `eu_market_features` keeps the country list, grid, weights and EU sum.
- **S5** Earnie adapters: `data/opendata_session.py` (D2); the old retry loops and `requests` imports in the four modules go.
- **S6** Tests: parity against S1 (same outputs, same request list minus cache hits); cache test (second call: no HTTP; unsettled days never written; month file extended past its last settled day; atomic write under two concurrent writers; env override; repo cache untouched); fail-loud test (one country 429 five times → error naming it; live falls back to `mirrored`); retry test (`Retry-After`, last error in the message).
- **S7** Docs: this section (implementation notes, results); `docs/konfiguration/preise.md` (D6); env var in the configuration reference if `EARNIE_OPEN_METEO_CACHE_PATH` is documented there; backlog (P6 → Erledigt, SUSI P3a points at `opendata`); Edibert backlog research item *Shared library (weather)*: built in Earnie as `opendata`.

### Implementation notes (2026-10-27)

- **S0 (SE live bias):**
  - `resolve_market_slots` now defaults to `live_bias_enabled=False` and takes `live_bias_feature_frame`; `compute_rolling_epex_bias_cent` takes `feature_frame`. Without one, it fetches live as before.
  - `resolve_backtesting_slot_prices` passes `live_bias_enabled=(strategy == forecast)` and the training frame.
  - `resolve_market_slots_kwargs` passes the config switch explicitly. Before, `live_bias_enabled: false` in `config.json` was overridden by the default `True`.
  - Tests: `test_se_forecast_live_bias_reads_training_frame_not_network` and `test_resolve_market_slots_kwargs_passes_live_bias_switch`.
  - SE June 2026 (fixture config with `price_source: api`, `--workers 20`): `backtesting.csv` byte-identical to the P5 run, 5 s instead of about 28 min. Full suite 4922 passed, 26 skipped.
  - Bugfix item moved to Erledigt; `docs/konfiguration/preise.md` updated.
- **S1 (golden):**
  - `scripts/opendata_golden.py` records with the clock frozen at 2026-10-27 18:00 Vienna, `requests.get` wrapped, shadow-feed writes patched out.
  - Nine entry points, 33 responses, 34 requests. The cases cover EU power, one country across a month edge, AT price, EU grid archive and forecast, site climate bundle (two surfaces, `use_cache=False`), site PV, and site outdoor and tilted forecast.
  - Archive window: 2025-10-24 → 28, across the DST change. Responses that needed 429 retries are kept only when the last attempt was 200.
  - Fixture `tests/fixtures/opendata/` (`responses.json.gz`, `expected.json`, README with CC BY attribution).
  - Test `tests/test_opendata_parity.py`: outputs and request list per case. It was green on the old code before any change.
- **S2 (package):**
  - `opendata/http.py`:
    - `Session(timeout_s, transport, pause_after_s)` with `get_json`;
    - retry on 429 / 502 / 503 / 504, `Retry-After` honoured, the last error re-raised;
    - `ApiUnreachableError` at the first connection error or timeout;
    - `fetch_budget` / `FetchBudgetExceeded`, moved from the archive module.
  - `opendata/open_meteo.py`: `archive`, `forecast` (single and multi-location), `utc_forecast_params`.
  - `opendata/energy_charts.py`: raw `public_power` and `price`, with a 30 s timeout floor. Not used yet; S4 wires them.
  - Packaging: `opendata*` in `pyproject.toml`, `COPY opendata/` in `docker/Dockerfile`.
  - Tests: `tests/test_opendata_package.py` (AST import isolation; retry, `Retry-After`, no retry on 400, unreachable, pause per host, budget).
- **S3 (Open-Meteo moved):**
  - `data/opendata_session.py` builds the session: global timeout, 0.75 s pause for the Energy-Charts host only.
  - Site archive `_fetch_hourly_archive_chunk` goes through `open_meteo.archive`. `_archive_http_get` and the local retry and budget code are gone; `climate_fetch_budget` / `ClimateFetchBudgetExceeded` are aliases of the `opendata` ones.
  - D5 held: the cache layer and the regression patch points are unchanged.
  - Site forecast goes through `open_meteo.forecast` with `_shadow_transport` (replay in shadow mode, record in prod), which replaces `_open_meteo_payload`. `utc_forecast_params` is re-exported from `opendata.open_meteo`.
  - EU grid archive, forecast per point and multi-location forecast go through `opendata`.
  - Behaviour changes (D3):
    - a connection error on the site archive is no longer retried (`ApiUnreachableError`);
    - the site forecast and the multi-location forecast now retry 429 / 5xx;
    - the EU grid archive no longer pauses 0.75 s per point.
  - Tests patching removed internals now patch `requests.get` / `opendata.http.time.sleep` / `_shadow_transport`. `test_fetch_without_budget_keeps_retrying` (connection-error retries) is gone by D3.
- **S4 (Energy-Charts moved, disk cache, fail-loud):**
  - `fetch_country_power_hourly` and `fetch_at_day_ahead_hourly` go through `opendata.energy_charts` (`public_power`, `price`). `_http_get_json`, `API_*`, `ENERGY_CHARTS_TIMEOUT_FLOOR_SEC` and `_energy_charts_timeout_sec` are gone; `ApiUnreachableError` is re-exported from `opendata`.
  - `opendata/cache.py` `ResponseCache` + `Session.get_json_cached(url, params, last_day, settle_days)`.
    - **Deviation from D4:** one file per request (URL and parameters, raw payload as the service sent it) instead of one parsed frame per country and month. Reasons:
      - Energy-Charts cuts days in the country's own zone (PT ends at 23:00 UTC, the others at 22:00 UTC).
      - Hourly countries add the first point of the next day.
      - A larger cached range therefore cannot be sliced into the exact response of a smaller one.
      - Per-request files also avoid read-modify-write races between SE workers.
    - Same effect for the cases that matter. Training rebuilt for the same window: whole months hit, and only the partial first month and the unsettled last one are fetched. The SE fetches nothing (S0). Live asks for unsettled days, which are never stored.
    - A request is stored only when its last day is settled: Energy-Charts 2 days (`SETTLE_DAYS`), Open-Meteo archive 7 days (`ARCHIVE_SETTLE_DAYS`, ERA5 replaces the model values after about five days). D4 had one rule for both; 2 days would freeze model values in the weather archive.
    - Atomic writes (temp file + `os.replace`). Windows refuses a replace or open while another process holds the file: a refused write is logged and skipped, a refused read is retried for up to 1 s.
    - A cache file of another request fails loud.
  - `data/opendata_session.py`: cache dir `data/cache/energy_charts/` or `EARNIE_ENERGY_CHARTS_CACHE_PATH`; also holds the EU grid archive (`open_meteo.archive(..., cached=True)`). The site archive keeps its own cache (D5) and does not use this one.
  - D6: `fetch_eu_power_hourly` raises `EuPowerIncompleteError` (a `RuntimeError`) naming the country and the cause. `ApiUnreachableError` still aborts at the first country. Live catches `RuntimeError` in `build_live_feature_frame_for_slots`, so it falls back to the mirror.
  - Tests:
    - `tests/conftest.py` gives every test its own, not yet created cache dir. Module and session fixtures get a per-process dir. In a shared dir one test would read another test's fake payload.
    - Parity runs on its own cold cache (same request list as before P6). A second run on the warm cache gives the same outputs with no Energy-Charts or EU-archive request.
    - Package tests: settled hit, unsettled never stored, foreign file, Earnie tests never on the repo cache.
    - `tests/test_eu_market_features.py`: skip tests replaced by the fail-loud test; retry and unreachable tests go through `requests.get`.
  - The first test run wrote the repo cache: the parity module fixture ran before the per-test env, and two xdist workers raced on one file. The directory was deleted; the per-process default and the explicit cache dir in `scripts.opendata_golden` prevent it.
  - Full suite 4953 passed, 26 skipped; regression all 11 PASS; no `data/cache/energy_charts` after the runs.
- **S5 (Earnie adapters):**
  - `data/opendata_session.py` is the one place that builds sessions (timeout, Energy-Charts pause, cache dir).
  - `data/outdoor_forecast.py`: the shadow transport fetches through `opendata.http.requests_transport`; no `requests` import left. The replay / record wrapper stays Earnie-side (D2).
  - `data/heating_need.py`: unused `fetch_climate` removed. It was the last Open-Meteo call outside `opendata`, used `urllib` with `timezone=auto`, and had no caller.
  - No `requests` import and no retry loop is left in `eu_market_features`, `open_meteo_solar_archive` or `outdoor_forecast`.
  - `data/price_forecast_live.py` keeps `requests.HTTPError` only to put the status code into the log line of a failed feature load; that is error reporting, not access code.
  - Test `test_only_opendata_talks_to_open_meteo_and_energy_charts`: no product module (pyproject packages, repo root) names either host, except `data/edibert_live_market.py` (Edibert's Day-Ahead feed key, P4a) and the golden script. Out of scope: `share/config/prognosis-heating-need.py` (standalone prototype) and `studies/`.
  - Full suite 4953 passed, 26 skipped, 1 failed: `test_main_daemon.py::test_start_captures_stdio_not_devnull`, a process start under load (the run took 167 s instead of about 90 s); it passes when run alone (18/18). Regression all 11 PASS; no `data/cache/energy_charts` after the runs.
- **S6 (tests):** the S6 list mapped to tests:
  - Parity against S1 and the second run without network: `tests/test_opendata_parity.py` (from S4).
  - Cache, in `tests/test_opendata_package.py`:
    - second call without HTTP, and unsettled requests never stored (from S4);
    - eight threads storing and reading one request leave exactly one valid file and no temp file;
    - `EARNIE_ENERGY_CHARTS_CACHE_PATH` override and the default;
    - the repo cache stays untouched (from S4).
    - "Month file extended past its last settled day" does not apply under per-request files (S4 deviation). A rolling window asks for a new last request, which is stored once it is settled.
  - Fail-loud: `tests/test_eu_market_features.py` (error names the country, from S4) and `tests/test_price_forecast_live.py::test_live_missing_country_falls_back_to_mirror`. In that test Energy-Charts answers 429 for every request: five attempts at the first country, no further country, the log names `Land de fehlt`, and every missing slot gets `mirrored`, none `predicted`.
  - Retry through Energy-Charts: `Retry-After` wins and the 30 s timeout floor applies; after five 429 the last `HTTPError` names the URL.
  - Full suite 4959 passed, 26 skipped; regression all 11 PASS; no `data/cache/energy_charts` after the runs.

- **S7 (docs):**
  - `docs/konfiguration/preise.md`: a missing country leads to the mirror, with the reason.
  - `docs/einrichtung/betrieb.md`: `EARNIE_ENERGY_CHARTS_CACHE_PATH`, what is stored and when.
  - Backlog: P6 → Erledigt; SUSI P3a points at `opendata/open_meteo.py`; the Edibert research item *Shared library (weather)* names `opendata`. Still open there: own repository and PyPI name, and whether Edibert's `MarketArchive` moves onto it.
- **Gate (2026-10-27):**
  - Full suite 4959 passed, 26 skipped; `scripts.run_regression` all 11 PASS without `--update-golden`.
  - Training set 2025-09 (`build_training_dataset`, fixture config, cache dir in a temp folder). The first build made 27 requests (25 files plus 429 retries) in 66 s. The second build, with `requests.get` raising, took 0.3 s; the 720 rows were identical.
  - SE June 2026, `price_strategy=forecast`, `--workers 20`, run twice: each run 14–19 s, both `backtesting.csv` byte-identical to each other, to S0 and to P5. The cache dir was not even created, so the SE fetches nothing.
  - The local house config needs the data-model-5 migration (`netznutzung.base_cent_kwh`). This is unrelated to P6; the gate used the fixture config.

### Order

S0 → S1 (commit golden on old code) → S2 → S3 → S4 → S5 → S6 → S7 → gate: full suite, `scripts.run_regression` without `--update-golden` (D5 keeps the climate fixtures valid), training dataset rebuilt for one month twice (second run without network), SE twice on the same window with `price_strategy=forecast` (identical `backtesting.csv`).

### Done check

- [x] One access path: every Open-Meteo and Energy-Charts call in Earnie goes through `opendata`.
- [x] Cache test green; second training-set build for the same month needs no network.
- [x] Import-isolation test green (no Earnie imports in `opendata`).
- [x] Missing country fails loud; live falls back to the mirror with label `mirrored`.
- [x] Full suite and all regression cases green, goldens and climate fixtures unchanged; two SE runs identical.

## P7 — Editor embed (plan 2026-10-27)

Status: **done** (2026-10-27; D1–D8 accepted, all as recommended; Edibert `0.1.7`, `0.1.8`, `0.1.9` released). Backlog item *Edibert P7* (Version 2.8): embed Edibert's editor in the Szenarienkonfigurator and remove the old tariff selects (`ui/pages/scenario_editor_tariffs.py`); UI language German. **Done (backlog):** cases TE1–TE6 green in Edibert, AppTest smoke test in Earnie, Playwright tariff path adapted.

### Findings (2026-10-27)

- **Edibert's UI is a standalone page, not a component.** `edibert.ui.main.main()` calls `st.set_page_config`, draws its own sidebar (language, house settings, my tariffs, new / copy / import) and reads its configuration from env vars (`EDIBERT_DATA_DIR`, `EDIBERT_CATALOG`, `EDIBERT_LANG`). Session keys are global and unprefixed (`ui.*`, `house.*`, `open.*`, `new.*`, `copy.*`, `import.*`, `delete`). Inside Earnie this would collide with Earnie's own page config, sidebar and keys. An embed API is Edibert work.
- **Edibert keeps its own house:** `editor/house.py` saves time zone, land, region, capabilities and an own grid fee (`user_house`) in `house.json` next to the user tariffs. Earnie has all of this in the house profile already (`region` since P1, grid area since P2, `user_grid_fees.json`). A second house in the config pack would drift.
- **Editor ≠ selection.** Edibert's editor authors tariffs (create, edit, copy a catalog tariff, import JSON, delete) in `user_tariffs.json`. Earnie's `scenario_editor_tariffs.py` *selects* tariffs per scenario: land and type filters, import / export pick, *Eigener Festpreis* (`__user_fixed__`, Earnie scenario shortcut, § P2 decision 4), parameter preview, next-month rate for `monthly_table` (writes into the site catalog copy, format difference row 4 → P8), catalog notice. Edibert has no picker.
- **Edibert `0.1.h` assumes the opposite:** its TE1–TE6 describe the *selection* (filters, profile switch, own fixed price, next-month rate, month boundary, scenario switch) and say "Edibert owns the editor, so the cases belong into Edibert". Only TE4 (next month written to the tariff file) and the save-path checks touch the editor itself.
- **Reload is free:** `house_config/edibert_tariffs.py` caches the tariff set and grid fees keyed on the mtimes of `tariffs.json` and `user_tariffs.json`, so a tariff saved by the editor shows in the selection on the next rerun.
- **Dependencies:** Edibert's `ui` extra is only `streamlit`; its UI also imports `pandas` and `holidays`. Earnie has all three. P0 installs Edibert without extras.
- **Tests today:** AppTest covers the tariff selection (`tests/apptest/test_page_scenario_editor_apptest.py`, `test_issue50_ui_apptest.py`, `test_persist_scenarios_apptest.py`, P1 `test_user_tariffs_appear_in_selection`). The Playwright smoke test (`tests/apptest/e2e/test_smoke.py`) has no tariff path yet; "adapted" therefore means "added".

### Decisions (2026-10-27, recommendations accepted by the maintainer)

1. **D1 — split between editor and selection:** *(recommended)* Edibert supplies the **editor** as an embeddable component; the per-scenario **selection** stays in Earnie, because its parts are Earnie concepts (scenario settings, `__user_fixed__`, house-profile land, planning clock). "Remove the old tariff selects" becomes: remove what duplicates Edibert (D5, D6), not the pick itself. TE1–TE3, TE5, TE6 stay Earnie AppTests (most exist; gaps filled in S5); Edibert `0.1.h` keeps the editor cases (TE4 save path, rejected input leaves the file unchanged, flash message, stable keys) and its backlog text is corrected. *Alternative:* Edibert also ships a picker component (filters, pick, preview); Earnie keeps only `__user_fixed__`. More Edibert work, and the picker needs Earnie's scenario state injected anyway.
2. **D2 — where the editor lives:** *(recommended)* own page **Tarife** (wide layout, editor and preview side by side as in Edibert), linked from the tariff block in the Szenarienkonfigurator ("Benutzertarif anlegen / bearbeiten", with the selected user tariff opened). *Alternative:* an expander inside the Szenarienkonfigurator, as the backlog text says; cramped (two-column editor in a three-column form) and mixes the scenario's unsaved state with the editor's.
3. **D3 — embed API (Edibert, new phase `0.1.m`):** `edibert.ui.embed.render_editor(EmbedConfig)` with `user_file`, `catalog_file` (copy-as-template source), `context` (`PricingContext` for preview and plausibility, supplied by the host), `language`, `key_prefix`, `container` for the tariff list (instead of `st.sidebar`). No `set_page_config`, no language selector, no house expander when a context is given. All session keys go through the prefix. The standalone `main()` uses the same component with `house.json` and the sidebar, so Edibert's own page and the embed share one code path. Additive: `API_VERSION` unchanged; release `v0.1.7` only with the maintainer's approval.
4. **D4 — house context:** *(recommended)* the Tarife page picks a house profile (default: the profile of the live scenario; deep link from the Szenarienkonfigurator passes the scenario's profile) and builds the `PricingContext` through `house_config/edibert_tariffs.py` (land, region, time zone, grid area incl. `user_grid_fees.json`). No `house.json` in Earnie's config dir; the editor shows the context read-only with a link to the house profile. Capabilities (`requires`): map from house-profile components where a mapping exists (check in S1), otherwise not set and the plausibility hint stays visible; no silent "has everything".
5. **D5 — parameter preview:** *(recommended)* replace Earnie's `render_tariff_parameter_preview` (`ui/tariff_filter_helpers.py`) in the selection with Edibert's preview (typical days, price at a time; exported from the embed module as `render_preview(tariff, context)`), so a tariff's curve is drawn by one engine. *Alternative:* keep Earnie's table preview; two views of the same tariff can disagree.
6. **D6 — next-month rate:** *(recommended)* a `monthly_table` **user** tariff without the next month gets a warning with a link that opens it in the editor (the rate table lives there); the inline Earnie form stays for **catalog** tariffs only, until P8 decides the fate of the site catalog copy. *Alternative:* the inline form writes user tariffs through Edibert's `userstore`; two edit paths for one file.
7. **D7 — writes and the config pack:** the editor writes `user_tariffs.json` through Edibert's atomic `userstore` (tagged `tariff_format`), next to `tariffs.json` (`user_tariffs_path_for`). After a save the plausibility check runs once (`collect_tariff_plausibility_errors(..., with_edibert=True)`) and a scenario referencing a deleted user tariff is reported, never silently reset. Deleting a user tariff that a scenario uses asks first and names the scenarios.
8. **D8 — pin:** `edibert[ui] @ …/v0.1.7.zip`, so the dependency states that Earnie uses the UI part; no new package (streamlit is already pinned by Earnie).

### Part A — Edibert (`0.1.m`, tag `v0.1.7`)

1. `edibert/ui/embed.py` (D3): `EmbedConfig`, `render_editor`, `render_preview`; `state.py` keys through a prefix; sidebar parts take a container; house expander only without a context.
2. `main()` rebuilt on the embed (standalone behaviour unchanged; existing 11 AppTest flows green).
3. Tests: AppTest of the embed with a prefix (no unprefixed key in `st.session_state`, two embeds on one page do not share state), host context shown read-only, no `house.json` written; editor save-path cases from `0.1.h` (TE4 save path, rejected input leaves the file unchanged, flash notice after `st.rerun()`).
4. Spec `docs/spec/api.md` (UI embed section), backlog: new item `0.1.m`, `0.1.h` text corrected per D1.

### Part B — Earnie (after the pin is raised)

- **S1** Findings check: capability mapping (D4), which German Edibert texts are missing or read oddly in Earnie's context.
- **S2** Page `ui/pages/page_tariffs.py` *Tarife* (navigation, German), house-profile select, `PricingContext` from `edibert_tariffs`, `render_editor` with prefix `earnie.tariffs` (rule `streamlit-ui-state.mdc`: `session_scope` per profile).
- **S3** Szenarienkonfigurator: link to the Tarife page (selected user tariff opened, scenario profile passed); preview through `render_preview` (D5); next-month warning for user tariffs links to the editor (D6); `render_tariff_parameter_preview` and its helpers go if no other caller is left.
- **S4** Writes (D7): plausibility after save, delete guard naming the scenarios.
- **S5** Tests: AppTest smoke for the Tarife page (create a fixed user tariff → file written with `user_` prefix and `tariff_format` → appears as *· Benutzertarif* in the Szenarienkonfigurator); fill TE1–TE3, TE5, TE6 gaps in the existing selection tests; Playwright path in `tests/apptest/e2e/` (open Tarife, create, select in a scenario, save).
- **S6** Docs: German user docs `docs/konfiguration/preise.md` § Benutzertarife (editor in Earnie instead of "aus dem Tarif-Editor Edibert"), `docs/ui/` page description of *Tarife*; this section (implementation notes, results); backlog (P7 → Erledigt).

### Implementation notes (2026-10-27)

- **Part A (Edibert `0.1.m`, released as `v0.1.7`, commit `d1958ec`, approved 2026-10-27):**
  - `edibert/ui/embed.py`: `render_editor(UiConfig, list_container=..., open_tariff=...)` and `render_preview(tariff, HostHouse, language=..., key_prefix=...)`. `UiConfig` gains `key_prefix` and `host_house`; `HostHouse` carries `PricingContext`, resolved `GridFee` (or `None`), capabilities and a description.
  - Key prefix: `state.scope(prefix)` wraps each render, fixed keys go through `state.k(name)`, `on_click` callbacks through `state.bound(...)` (Streamlit runs callbacks before the render, outside the scope). The standalone page uses the empty prefix, so its keys and tests are unchanged.
  - With a host house the editor shows time zone, land, region and grid area read-only and touches no `house.json`. The embed sets the language from `config` on every run.
  - `open_tariff=(direction, id)` opens a user tariff once per distinct request (later reruns keep the edits); an unknown ID shows the new error `TARIFF_NOT_FOUND`.
  - Deviation from D3: `render_preview` takes a `HostHouse` instead of separate context / grid fee / capabilities.
  - Tests `tests/test_ui_embed.py` (11 cases, incl. the editor cases of `0.1.h`: rejected input leaves the file unchanged, notice after `st.rerun()`, TE4 file side at model level because AppTest cannot drive `st.data_editor`). Full Edibert suite 434 passed, ruff and vulture clean.
  - Edibert backlog: `0.1.m` archived, `0.1.h` rewritten per D1 (TE1–TE3, TE5, TE6 → Earnie).
- **Pin (D8):** `edibert[ui] @ …/v0.1.7.zip` in `pyproject.toml`; `tests/test_edibert_dependency.py` accepts the extra in the pin. All `tests/test_edibert*.py` and the Szenarienkonfigurator AppTests green (259 passed) on `0.1.7`.
- **S1 (findings check):**
  - **Capabilities (D4):** Edibert's vocabulary is `smart_meter`, `quarter_hour_meter`, `separate_meter`, `controllable_device`. Earnie has a source for two of them: `netznutzung` always treats the household as having a quarter-hour smart meter (`house_config/netznutzung.py`, schema: "QH smart meter assumed, not user-configurable"), so the host house gets `smart_meter` + `quarter_hour_meter` from that same documented assumption (one constant next to `METERING_UNMETERED`, not a second assumption). `separate_meter` and `controllable_device` (§14a) have no Earnie field: not set, so a tariff or rule that requires them keeps Edibert's unmet-requirement warning. Earnie's pricing ignores `requires` (display-only since P1), so this changes no price.
  - **German texts in Earnie's context:**
    - `ui.monthly_hint` ("Fehlt ein Monat, bricht die Berechnung ab, statt zu raten", EN the same) is stale since Edibert `0.1.g`: a missing month uses the prior-year / prior-month rate with the warning `MONTH_RATE_FALLBACK`. Edibert bugfix item, both catalogs; ships with the next Edibert release, not a blocker for S2.
    - Term: Edibert says *Netzentgelt* (`ui.host_grid`, `ui.invoice_off`), Earnie's UI and docs say *Netznutzung (Arbeitspreis)* for the same thing. Acceptable for now (the Tarife page caption names it once); align when Edibert's texts are touched again.
    - Address: Edibert uses *du* (`ui.start_hint`, `ui.invoice_hint`), Earnie's UI mostly avoids a direct address and uses *Sie* where it does (tariff catalog notice). Minor; no change in P7.
    - `ui.no_catalog` points at the CLI (`--catalog DATEI`); never shown in Earnie because the Tarife page always passes `tariffs.json` as catalog.
    - `ui.invoice_hint` names *Edibert*; fine (Edibert is named as the tariff library in `preise.md`).
    - `ui.start_hint` says "öffne links", which holds with the embed's default layout (list column left); S2 keeps that layout.
- **Edibert `0.1.n` (released as `v0.1.8`, approved 2026-10-27):** found in S2: the editor wrote no `land`, Earnie requires it on every user tariff (§ P2 decision 7), so the first tariff saved on the Tarife page broke the tariff load of the Szenarienkonfigurator (`land fehlt`). Step 1 now has a visible select *Land des Tarifs*, prefilled with the land of the host house (or the editor's own house settings), clearable (then no `land`). Earnie stays strict. Remaining case: a JSON import without `land` still fails Earnie's load with that message; the import keeps the tariff as given.
- **Pin:** raised to `edibert[ui] @ …/v0.1.8.zip`.
- **S2 (Tarife page):**
  - `ui/pages/page_tariffs.py` *💶 Tarife* (navigation *Konfiguration*, after the Szenarienkonfigurator, same unlock; url `tariffs`, doc link `preise.md#benutzertarife-usertariffsjson` until S6 adds the handbook section).
  - House-profile select (label select; default = profile of the live scenario via `resolve_live_profile_id`); `host_house_for_profile` in `house_config/edibert_tariffs.py` builds `HostHouse` (context, resolved grid area incl. `user_grid_fees.json`, `ASSUMED_METER_CAPABILITIES` from `house_config/netznutzung.py`, description *Hausprofil „…“*). A profile Edibert cannot resolve shows the German load error and no editor.
  - `render_editor` with `data_dir` = directory of `user_tariffs_path_for(tariffs.json)`, catalog = `tariffs.json` (copy as template), language `de`, prefix `earnie.tariffs.`.
  - **Deviation from the plan:** one prefix for all profiles instead of a `session_scope` per profile. The profile only changes the preview context; the open tariff stays open on a profile switch.
  - Shadow mode (`is_shadow_config_readonly`): info, no editor — Edibert's `userstore` writes the file directly and would bypass the read-only guard.
  - Deep link for S3: `request_tariff_page(profile_id, open_tariff)` stores the request in `st.session_state`; the profile part is used once, the `open` part stays so the editor opens the tariff once per distinct request.
  - Tests: `tests/apptest/test_page_tariffs_apptest.py` (title, profile select, read-only house and no `house.json`; all widget keys behind the prefix; create → `user_tariffs.json` with `tariff_format`, `user_` ID → *· Benutzertarif* in the Szenarienkonfigurator; request opens a tariff; unknown request → error); navigation matrix (`tests/apptest/states.py`, `test_navigation_setup.py`) and `NAV_DOC_PAGE_KEYS` extended.
  - Full suite 4965 passed, 26 skipped; `tests/fixtures/` unchanged after the run.
  - **Found, not fixed (pre-existing, also on `HEAD`):** when pytest is called with explicit files from `tests/apptest/` and `tests/` mixed (e.g. `tests/apptest/test_page_scenario_editor_apptest.py::… tests/test_doc_links.py tests/apptest/…`), the later AppTests run without `tests/apptest/conftest.py`'s `_isolated_backtesting_config` (missing from `request.fixturenames`), so they write into `tests/fixtures/backtesting/` (`backtesting_scenarios.json`, `user_tariffs.json`). The full-suite run is not affected. Own follow-up.
  - Not done: browser check of the page (planned for the P7 gate).
- **S3 (Szenarienkonfigurator):**
  - Preview (D5): under each tariff pick, Edibert's `render_preview` (hints, price curves, month select) for the scenario's house profile (`host_house_for_profile`), prefix `<session_scope>__tariff_preview_<direction>.`; without a profile a caption, an unresolvable profile or tariff the German load error. `render_tariff_parameter_preview` (`ui/tariff_filter_helpers.py`) and its unused re-imports are gone; `data/tariff_parameter_preview.py` stays (SE invoice markdown, monthly fees).
  - Links: *Benutzertarife verwalten* (Tarife page with the scenario's profile) and, when the selected import or export tariff is a user tariff, *Benutzertarif bearbeiten* (opens it). Both via `request_tariff_page` + `ui.navigation.switch_to_page("tariffs")`; disabled with a hint while the scenario form is dirty (`_active_scenario_form_is_dirty`), because a page switch drops unsaved widget state.
  - Next-month rate (D6): a user `monthly_table` without the next month gets the warning plus *Im Tarif-Editor öffnen*; catalog tariffs keep the inline form (site copy of `tariffs.json`, until P8).
  - Fixture: `monthly_test` (`tests/fixtures/backtesting/tariffs.json`) had three months of 2025 only, so Edibert's preview (current year) correctly reported *Kein Preis* in the AppTests of the scenario `entity_test`. Filled with all months of 2025 and 2026 (the three old values kept); the preview needs a rate for the current month or its prior-year / prior-month fallback, so the fixture lasts until 2027-12. Only UI tests use it.
  - Cost: the page renders about 0.1 s slower per run in AppTest (two previews).
  - Tests: `tests/apptest/test_scenario_tariff_editor_links_apptest.py` (previews drawn without error; manage button stores the profile request and switches; edit button opens the selected user tariff; no edit button for a catalog tariff). Not covered by AppTest: the next-month editor button (needs a planning clock within two days of a month end with a user monthly table) — S5.
  - Full suite 4969 passed, 26 skipped; `tests/fixtures/` unchanged by the run.
- **Edibert `0.1.o` (released as `v0.1.9`, approved 2026-10-27):** found in S4: the embed deleted a user tariff on the first click and told the host neither about saves nor deletes, so D7 could not be built on the Earnie side. `UiConfig` gains `delete_guard(direction, id) -> str | None` (a text holds the delete behind *Trotzdem löschen* / *Nicht löschen*) and `on_change(action, direction, id)` (after save, each imported tariff, delete). Without them the editor behaves as before. Edibert suite 440 passed. Pin raised to `edibert[ui] @ …/v0.1.9.zip`.
- **Edibert `v0.1.10` (pin raised 2026-10-30):** catalog `0.1.d` P1–P7 client (tariff identity, validity versions, `db_ref`, signed packages with the first built-in key `edibert-2026-1`, share section, exchange client), capacity charge engine, gross-tariff grid fee VAT fix; new dependency `cryptography`. Breaking embed change: `render_editor(..., share_default=...)` is required. Earnie passes `ShareDefault.OPT_IN` and no `contribution_transport`, so the share section shows the payload, starts with nothing selected and keeps *Ausgewählte Tarife senden* disabled (`CONTRIBUTION_TRANSPORT_OFF`). Consent and `ExchangeConfig` in Earnie come later as their own item (after the legal review of the contribution terms and privacy notice, and the TariffDB server on the VPS).
- **Edibert `v0.1.12` (pin raised 2026-10-31):** contract v2 (one tariff database; the v0.1.10 client's `/packages/free|verified` routes are gone on the server), `API_VERSION` 3, grid-area model `0.1.d2`. `tf1.tariff_format` passes `grid_fee_area` (the `netznutzung.area_id` all house profiles share, else `None` → Edibert blocker). Share consent: `runtime_store/tariff_share_consent.py` (`runtime/tariff_share.json`); the Tarife page passes `ExchangeClient` / `ServerTransport` only with consent and without `EARNIE_OFFLINE=1` / `EDIBERT_EXCHANGE_OFF=1`; `ShareDefault.OPT_IN` stays. Release of the toggle waits for the legal review (Earnie backlog "Edibert share consent — release gate").
- **S4 (writes, D7):**
  - Delete guard: `house_config/tariff_plausibility.scenarios_using_tariff(scenarios_path, direction, id)` (export IDs through `resolve_export_tariff_id`); the Tarife page's guard names the scenarios (*„…“ ist Bezugstarif in Szenario …*) and says the check will report them. An unused tariff is deleted without asking.
  - After a write: `on_change` sets a session flag, the next render of the Tarife page runs `collect_tariff_plausibility_errors(..., with_edibert=True)` once (catalog + user file, `grid_fees.json`, house profiles, scenario references) and shows the findings as `st.error`; nothing when clean. A scenario whose user tariff was deleted is reported (*unbekannte import_tariff_id*), never reset.
  - Tests: `tests/apptest/test_page_tariffs_apptest.py` (+4: unused delete without asking, used delete names the scenario and waits / cancel keeps, confirmed delete reported by the check once, save runs the check without findings) and `tests/test_tariff_plausibility.py` (+1).
  - Full suite 4974 passed, 26 skipped; `tests/fixtures/` unchanged by the run. A mixed explicit invocation (AppTests plus `tests/test_tariff_plausibility.py`) hit the known fixture leak again; restored.
- **S5 (tests):**
  - Gap check against the TE cases (Edibert `0.1.h` text): TE1 had only helper tests and L7 (filter not stored, saved tariff selectable in a new session); TE2 one session-sync test; TE3 none in the UI; TE5 none; TE6 none for tariffs.
  - `tests/apptest/test_scenario_tariff_selection_apptest.py` (8):
    - TE1: land filter DE and a type filter keep the saved AT tariff selected, nothing is stored over it;
    - TE2: a second profile (DE, added to the test's config copy) switches the land filter, a manual filter stays while the profile stays;
    - TE3: *Eigener Festpreis* shows 20.0, stores the edited cent value, deselecting hides the input and drops `user_import_cent_kwh`; a new session shows the saved value;
    - TE6: switching to another scenario after changing land filter and import shows exactly that scenario's own selects;
    - D6: a user monthly table without November, planning clock 31 Oct (`page_scenario_editor._planning_now` patched) → warning, no inline cent form, *Im Tarif-Editor öffnen* requests the editor with that tariff.
  - `tests/test_scenario_editor_next_month.py` (TE5, 3 cases, `time_machine`, planning zone Europe/Vienna): 23:30 local on 31 Oct → November; 00:30 local on 1 Nov (still October in UTC) → December; 00:30 local on 1 Jan → February of the new year.
  - Playwright (`tests/apptest/e2e/test_smoke.py::test_tariffs_user_tariff_created_and_selected_in_a_scenario`): open *Tarife*, *Neuer Bezugstarif*, name and price, save (file: `user_` ID, price, `land` AT), Szenarienkonfigurator → pick *· Benutzertarif* (the option is found only after typing into the select) → stored in the scenario, Edibert preview and *Benutzertarif bearbeiten* visible. All 6 e2e tests green locally (124 s).
  - Full suite 4985 passed, 26 skipped; `tests/fixtures/` unchanged.
- **S6 (German user docs):**
  - `docs/konfiguration/preise.md` § Benutzertarife: tariffs are made on *Konfiguration → Tarife* (embedded editor) instead of "aus dem Tarif-Editor Edibert"; check after every write, delete guard, no silent reset.
  - Handbook (`docs/user-manual/Benutzer-Handbuch-Earnie.md`): new section *Tarife (Benutzertarife)* after the Szenarienkonfigurator (house profile read-only, new / copy / import, four steps with land, save, check, delete guard). The Szenarienkonfigurator's tariff bullets now describe the Edibert preview instead of the read-only catalog parameters, the two editor links (disabled while unsaved), filters that keep the saved tariff, and the next-month warning (inline for catalog tariffs, *Im Tarif-Editor öffnen* for user tariffs).
  - **Deviation from the plan:** no separate `docs/ui/` page. `docs/ui/` describes operating pages (Betriebsmodi, Charts, EHAL-Com, Smarthome-Backend); the configuration pages are described in the handbook, so *Tarife* is a handbook section like the Szenarienkonfigurator.
  - Doc link of the page: primary *Tarife (Benutzer-Handbuch)* (`#tarife-benutzertarife`), secondary *Benutzertarife (Preise und Marktdaten)*.
  - Shadow mode is not mentioned: `tests/test_user_docs_audience.py` counts it as a developer term; the page shows its own notice.
  - Text without direct address, as in the rest of both documents.
  - `tests/test_doc_links.py` and `tests/test_user_docs_audience.py` green.
  - Backlog P7 → Erledigt waits for the gate (done check below still open).
- **Gate (2026-10-27):**
  - Full suite 4993 passed, 19 skipped (commit hook of S6).
  - `scripts.run_regression` without `--update-golden`: all 11 cases PASS. **Found:** the plain run aborts on this machine before comparing: a worker process imports `config` (via `data/opendata_session.py`, since P6), which loads the local site config (`earnie_env/config`); that site config is not on data model 5 yet (`netznutzung.base_cent_kwh`, see P3b), so loading fails. Not caused by P7 (`REG-O-autumn-nov` identical at `d0fd970a` and `HEAD` via `--compare-at`). Run green with the `EARNIE_*_PATH` variables on a copy of `tests/fixtures/backtesting/`. The cases replay their own recorded configs, so the runner should not depend on the site config; own follow-up.
  - Playwright: all 6 e2e tests green locally (incl. the new tariff path); the CI job runs on the next push.
  - Browser check (fixture config copy): Tarife page at 1440×900 and 375×812: create, save (notice, no check finding), open; on the phone the list stacks above the form, no horizontal page scroll. Minor: Edibert's `ui.start_hint` says "öffne links", while on the phone the list is above; Edibert text, not changed here.

### Order

Part A (Edibert `0.1.m`, release `v0.1.7` with approval) → pin → S1 → S2 → S3 → S4 → S5 → S6 → gate: full suite, `scripts.run_regression` without `--update-golden` (no pricing change expected), Playwright UI job, manual browser check of the Tarife page (desktop and phone width).

### Done check

- [x] Edibert editor runs embedded on the Earnie page *Tarife*, German, no key collision with Earnie (prefix test).
- [x] No `house.json` in Earnie; the editor's context comes from the house profile.
- [x] Szenarienkonfigurator: selection unchanged in behaviour, preview from Edibert, link to the editor.
- [x] TE1–TE6 green (editor cases in Edibert, selection cases in Earnie per D1); AppTest smoke and Playwright tariff path green.
- [x] Full suite and all regression cases green, goldens unchanged.

## P8 — Catalog decision (2026-10-28)

Status: **decided** (2026-10-28; D1–D6 accepted as recommended, D5 extended by the maintainer, D6 changed while writing it). Backlog item *Edibert P8* (Version 2.8): fate of the public `share/config/tariffs.json` and contributions in `LICENSE.md` § 3.

### Findings (2026-10-28)

- `share/config/tariffs.json` is public (37 import, 13 export tariffs; AT, CH, DE). `runtime_store/bootstrap.py` copies it into the site config only on first start (`_copy_template_if_missing`), so existing installations never see catalog changes; only new installations do.
- Nine tariffs are monthly tables. Seven carry `monthly_seed` and get their monthly rates from the maintained reference curves (`scripts.update_tariff_curves`, OeMAG market price, E-Control reference market value PV). A site copy gets the next month only through the inline form of the Szenarienkonfigurator (`append_monthly_rate`, P7 D6) or the prior-year fallback (`MONTH_RATE_FALLBACK`).
- `share/config/grid_fees.json` is a catalog and seed of the same kind (Edibert spec § 2: both are written by "catalog package / seed").
- Edibert already reserves `catalog/` for a signed catalog package and describes the contribution path in `CONTRIBUTING.md`; its `catalog/README.md` lists this decision as open. Edibert's conventions keep legal texts out of the repository until they are legally reviewed.
- `LICENSE.md` § 3 covers voluntary data for unknown hardware only.
- The backlog put P8 after Edibert `0.1.d`, but `0.1.d` (contribution path, signed catalog access) needs this decision and the contribution terms first.

### Decisions (2026-10-28)

1. **D1 — public catalog:** `share/config/tariffs.json` stays as a **frozen seed**. It gets **no new tariffs**; new tariffs reach the catalog only through Edibert's catalog channel (`0.1.d`). Allowed changes: corrections of existing entries (wrong price, wrong rule, ended product) and the monthly rows of the reference curves, so new installations do not start with stale feed-in rates. This holds until catalog packages deliver the monthly rates. Enforced by `tests/test_catalog_frozen.py` (fixed ID set per side).
2. **D2 — order:** P8 before Edibert `0.1.d`; `0.1.d` builds on D1 and D5.
3. **D3 — site copy:** new entries never land in the site copy; users create user tariffs (Tarife page, P7). The inline next-month form stays for catalog monthly tables until the catalog packages of `0.1.d` bring the monthly rates; then `append_monthly_rate` goes. Note for `0.1.d`: a package import must not overwrite monthly rows the user entered in the site copy without telling.
4. **D4 — grid areas:** `share/config/grid_fees.json` follows D1 and D3 (frozen seed, corrections only, new areas through the catalog channel; own values in `user_grid_fees.json`).
5. **D5 — contribution terms:** `LICENSE.md` § 3 gets paragraphs 4–8 on tariff contributions made from within Earnie (draft, legal review open; scope see D6): voluntary, non-individualized tariffs without personal data only, preview and opt-in per tariff, a simple, free, non-exclusive and perpetual right of use for the catalog bound to that purpose, deletion on request where the contribution can be attributed, no liability for tariff data, use of the software never depends on a contribution. *(A reward of one month of free catalog access per verified, time-varying tariff was added and dropped again on 2026-10-28 by the maintainer; no reward is offered.)* Terms of use for the catalog itself (redistribution, database right) are not part of § 3; they come with `0.1.d`.
6. **D6 — Edibert:** *(changed while writing it)* no terms file in Edibert, because Edibert keeps legal texts out of the repository until they are reviewed. Instead `catalog/README.md` records D1 as decided and `CONTRIBUTING.md` says which terms apply. **Scope (clarified 2026-10-28):** Earnie's `LICENSE.md` § 3 paragraphs 4–8 cover only contributions made from within Earnie. Contributions through the standalone Edibert editor fall under Edibert's own contribution terms, announced in its README (per country, national language, after legal review); once those are published they also cover contributions from Earnie and take precedence over § 3 paragraphs 4–8. Edibert's `CONTRIBUTING.md` points to both.

### Legal review (open)

Not done here; the § 3 text is a draft. Points for the review:

- Terms of contribution (purpose, scope, deletion), the privacy notice for the upload, liability for tariff data.
- Paid access (VAT, withdrawal right for digital content, payment handling) — only once a fee or subscription is offered.

**Update 2026-10-31:** § 3 paragraphs 4–8 now follow the two-database model (free database without review, verified database with own terms): opt-in per tariff stays for contributions from Earnie, also after Edibert's terms take precedence; transferred fields are tariff ID and version instead of the check-calculation result; "reliable" by active use of two installations instead of "verified"; the usage report from Earnie needs its own consent.

### Done check

- [x] Decision record (this section).
- [x] `LICENSE.md` § 3 extended for tariff contributions (draft, legal review open).
- [x] Guard test for D1 (`tests/test_catalog_frozen.py`).
- [x] Edibert `CONTRIBUTING.md` and `catalog/README.md` aligned (D6); backlogs on both sides corrected (D2).
