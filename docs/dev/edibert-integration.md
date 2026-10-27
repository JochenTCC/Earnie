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
| 1 | Missing month in `monthly_table` | exact → same month prior year → prior month, logged once as a warning; error only if none exists | same order since Edibert `v0.1.4` (`0.1.g`), coded warning `MONTH_RATE_FALLBACK` (`rule`, `used_month`); `PRICE_MISSING` only when none of the three exists | done in P3a-2: the adapter logs the warning once per tariff and month and returns it to reports; harness and test check rule, month and price against Earnie |
| 2 | Unknown tariff fields | ignored silently by the normalizer | `TARIFF_UNKNOWN_FIELD` (error) | none for the catalog (loads clean); user files are already checked strictly |
| 3 | `user_` prefix | no rule | user IDs must start with `user_`, catalog IDs must not (`ID_PREFIX_*`) | none; enforced since P1 |
| 4 | Edited site copy of the catalog | `earnie_env/config/tariffs.json` is seeded from `share/` and may be edited (`append_monthly_rate`) | treated as catalog; every entry gets origin `catalog` | P8 decides whether new entries may still land there |
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

## P4a — Market prices, live chain (plan 2026-10-27)

Status: **planned**. Backlog item *Edibert P4a* (Version 2.8). Goal: `data/live_market_prices.py`, `integrations/entsoe_client.py` and `integrations/awattar_client.py` are replaced by Edibert's market module; `price_source` per slot comes from Edibert's forecast method. **Done:** a live cycle runs on Edibert prices, recorder-format regression goldens green.

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

### Order

Part A (release, pin) → B1 → B2 → B3 → B4 → B5 → gate: full suite (`scripts.run_pytest`), `scripts.run_regression` without `--update-golden`, live cycle on the maintainer site (the site needs the data-model-5 migration first, see P3b). The pandas-free chain (`fetch_energy_charts_prices` in `data/data_loader.py`) is P4b.

### Done check

- [ ] Edibert `0.1.k` released, Earnie pin raised.
- [ ] The three old modules are gone; live callers use Edibert.
- [ ] Shadow record / replay works for all three sources.
- [ ] Full suite and all regression cases green, goldens unchanged.
- [ ] A live cycle on the maintainer site runs on Edibert prices.
