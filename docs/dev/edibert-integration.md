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
| 5 | `__user_fixed__` (*Eigener Festpreis*) | pseudo tariff, cent values on the scenario | no equivalent | P3a: synthetic Edibert `fixed_cent` / `fixed` tariff at resolution time, or move into `user_tariffs.json` (P2 decides) |
| 6 | `tariff_format` root key | none | not in `ROOT_FIELDS` (would be an unknown root field) | P2: add to Edibert first, then tag the three files |
| 7 | `land` | required per tariff (country filter) | optional | user tariffs without `land` fail in Earnie with a `user_tariffs.json` message; keep, or relax in P3b |
| 8 | Root maintenance keys (`earnie_data_model`, `oemag_monthly_feed_in_rates`, …) | read by Earnie | tolerated and ignored (`ROOT_FIELDS`) | none |

Row 1, measured on the catalog (2026-10-26): there are no gaps inside any table; the differences are at the edges. Six export tables end at 2026-09 and `monthly_sunny_web_recherche` at 2026-10, so Earnie prices the following months with the prior-year month (`at_oemag_gesetzlicher_marktpreis` 2026-10: Earnie 9.008 ct from 2025-10, Edibert `PRICE_MISSING`); `at_vkw_strom_duo` ends at 2027-03. Before a table starts, both fail (`at_vkw_pv_flex` 2025-03: Earnie error, Edibert `PRICE_MISSING`). The SNAP comparison in P3a must therefore run over months that every table covers, or after `0.1.g`.
