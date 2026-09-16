---
name: streamlit-apptest
description: >-
  Keep Streamlit AppTest UI smokes in sync when ui/pages/page_*.py change.
  Use when adding, renaming, removing, or materially editing Streamlit pages
  under ui/pages/, their render() entrypoints, visible titles/labels, or nav
  page registration; or when touching tests/apptest/**.
---

# Streamlit AppTest page smokes

Canonical layout:

| Piece | Path |
|-------|------|
| Page module | `ui/pages/page_<name>.py` with `def render()` |
| AppTest entry | `tests/apptest/scripts/run_page_<name>.py` |
| Pytest smoke | `tests/apptest/test_page_<name>_apptest.py` |

Coverage map (new pages only): `tests/test_apptest_page_coverage.py`.
Shared fixtures / offline isolation: `tests/apptest/conftest.py`.

## When this skill applies

Run the checklist **before calling the change done** if you:

- Add / rename / remove `ui/pages/page_*.py` that exposes `render()`
- Change a page title, primary heading, or other text that an AppTest asserts
- Add a user-visible section that should stay smoke-covered (title / key widget)
- Touch `tests/apptest/**` or navigation that introduces a new page module

Non-page helpers under `ui/pages/` without `render()` (e.g. `scenario_editor_form.py`) do **not** need their own AppTest pair.

## Checklist

```
Streamlit AppTest:
- [ ] Every ui/pages/page_*.py with render() has run_page_<name>.py + test_page_<name>_apptest.py
- [ ] New page: thin script imports the module and calls render() (see existing run_page_*.py)
- [ ] New page: at least test_renders_without_exception + one visible title/label assertion
- [ ] Renamed/changed titles or asserted widgets: update matching test_page_*_apptest.py
- [ ] Removed page: delete the matching scripts/ + test file
- [ ] tests/test_apptest_page_coverage.py still green
- [ ] Optional: python -m scripts.run_pytest tests/apptest -m apptest -q
```

## Patterns

**Entry script** (keep minimal — AppTest loads the file):

```python
from ui.pages import page_example

page_example.render()
```

**Smoke test**:

```python
from pathlib import Path
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_example.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "…exact UI title…"
```

- Prefer `AppTest.from_file` over `from_function` (module imports must run).
- Raise `default_timeout` only when a page is known-slow under the full suite (see backtesting / consumer analysis).
- Do not write into shared fixtures; `tests/apptest/conftest.py` already isolates config/runtime.

## Out of scope

- Deep interaction / form-flow tests (use focused unit tests under `tests/test_*.py`)
- Auto-generating assertions for every widget
- Non-Streamlit UI surfaces
