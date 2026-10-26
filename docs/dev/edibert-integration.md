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

## P1 — Data files and read-only coexistence

To be filled in P1, including the format differences found for P3a (missing month, unknown fields, `user_` prefix rule, edited site copy of the catalog, `user_fixed` pseudo tariff, `tariff_format` root key).
