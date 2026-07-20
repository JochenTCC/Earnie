---
name: UI mode live_environment
overview: Add EARNIE_UI_MODES key `live_environment` to show/hide the Echtzeit-Umgebung section (Live-Konfiguration, Optimierer-Dienst, Loxone-Kommunikation), matching the existing sunset2sunset Betrieb gate — and update prod compose defaults so local/Synology behavior stays unchanged.
todos:
  - id: mode-selector
    content: Add live_environment to UI_MODE_KEYS/LABELS and unset-env default
    status: completed
  - id: navigation
    content: Split Planung/Echtzeit specs; gate Echtzeit (incl. restricted nav) on live_environment
    status: completed
  - id: compose-launch
    content: Append live_environment to compose + launch.json EARNIE_UI_MODES
    status: completed
  - id: docs-tests
    content: Update betriebsmodi/betrieb docs and mode/navigation tests
    status: completed
isProject: false
---

# Add `live_environment` UI mode

## Decision (fixed)

- **Key:** `live_environment` (English snake_case, aligned with `scenario_explorer` / page url `live-environment`).
- **Pages gated:** entire **Echtzeit-Umgebung** — Live-Konfiguration, Optimierer-Dienst, Loxone-Kommunikation.
- **Default when `EARNIE_UI_MODES` unset:** `sunset2sunset`, `scenario_explorer`, `live_environment` (+ `price_forecast` only if config enables it).
- **Explicit env lists:** must include `live_environment` or Echtzeit is hidden (same exclusive semantics as today).
- **Restricted / greenfield nav:** also respects the key (so Community Cloud `scenario_explorer` alone hides Echtzeit during setup).

## Implementation

### 1. Mode registry — [`ui/mode_selector.py`](ui/mode_selector.py)

- Add `"live_environment"` to `UI_MODE_KEYS` and label `"Echtzeit-Umgebung"` in `UI_MODE_LABELS`.
- Extend unset-env default: `keys = ["sunset2sunset", "scenario_explorer", "live_environment"]`.
- Update docstrings / invalid-mode notice text if it still says “nur Sunset-2-Sunset”.

### 2. Navigation gate — [`ui/navigation.py`](ui/navigation.py)

Split [`_planning_page_specs`](ui/navigation.py) into:

- `_planung_page_specs(...)` — Hauskonfigurator (+ Szenarieneditor when unlocked)
- `_echtzeit_page_specs()` — the three Echtzeit pages

Wire gating:

```python
# restricted + full nav
specs = _planung_page_specs(...)
if "live_environment" in enabled_mode_keys:
    specs.extend(_echtzeit_page_specs())
```

- `_restricted_page_specs` must take `enabled_mode_keys` (today it ignores modes).
- `build_page_specs` passes keys into restricted path and only appends Echtzeit when the key is present (full nav path too).
- Refresh module docstring.

### 3. Deploy / launch defaults (required so prod does not lose Echtzeit)

Append `,live_environment` everywhere modes are set explicitly:

- [`docker/compose/synology.yml`](docker/compose/synology.yml), [`proxmox.yml`](docker/compose/proxmox.yml), [`loxberry.yml`](docker/compose/loxberry.yml), [`greenfield.yml`](docker/compose/greenfield.yml)
- [`.vscode/launch.json`](.vscode/launch.json) (Greenfield entries)
- Comments in those files that document the prod string

Prod / greenfield value becomes:

`sunset2sunset,scenario_explorer,live_environment`

Community Cloud stays:

`EARNIE_UI_MODES=scenario_explorer` → no Betrieb, no Echtzeit.

### 4. Docs (German user docs)

- [`docs/ui/betriebsmodi.md`](docs/ui/betriebsmodi.md) — table row for `live_environment`; remove Live-*/Loxone from “not gated” list; Cloud example notes Betrieb + Echtzeit hidden; update default example string.
- [`docs/einrichtung/betrieb.md`](docs/einrichtung/betrieb.md) — env table for `EARNIE_UI_MODES`.
- Brief touch on [`docs/einrichtung/greenfield-dev-stack.md`](docs/einrichtung/greenfield-dev-stack.md) / [`docs/einrichtung/private-env.md`](docs/einrichtung/private-env.md) if they quote the mode string.
- Spec mention optional: one line in [`docs/spec/ui-sunset2sunset.md`](docs/spec/ui-sunset2sunset.md) prod example (keep light).

### 5. Tests

- [`tests/test_mode_selector.py`](tests/test_mode_selector.py) — default modes include Echtzeit-Umgebung; env parse includes new key.
- [`tests/test_ui_navigation.py`](tests/test_ui_navigation.py):
  - Existing full-nav cases that expect Live-Konfiguration must pass `live_environment` in `enabled_mode_keys`.
  - Extend `test_scenario_explorer_only_hides_betrieb` (or add sibling) to assert Live-Konfiguration / Optimierer-Dienst / Loxone-Kommunikation are **absent** without the key.
  - Keep Planung pages visible without `live_environment`.

## Out of scope

- No `version.py` bump.
- No gating of Planung or Verbraucheranalyse.
- No change to Streamlit Cloud secrets (already `scenario_explorer`).
