---
name: streamlit-apptest
description: >-
  Keep Streamlit AppTest UI smokes and the persistence/logic tests in sync when
  ui/ changes. Use when adding, renaming, removing, or materially editing
  Streamlit pages or forms under ui/ (widgets, keys, save paths, buttons,
  messages, nav registration), or when touching tests/apptest/**.
---

# Streamlit AppTest: page smokes, persistence and logic tests

Canonical layout:

| Piece | Path |
|-------|------|
| Page module | `ui/pages/page_<name>.py` with `def render()` |
| AppTest entry | `tests/apptest/scripts/run_page_<name>.py` |
| Pytest smoke | `tests/apptest/test_page_<name>_apptest.py` |

Coverage map (new pages only): `tests/test_apptest_page_coverage.py`.
Shared fixtures / offline isolation: `tests/apptest/conftest.py`.

Beyond the smokes, the suite tests **persistence** (value survives save and a new session) and **logic** (state → allowed actions → shown result). Concept: "Earnie UI-Persistenztests" (project folder `Entwicklungsplan/Offen/`).

| Piece | Path |
|-------|------|
| Persistence tests (T1–T5, T8, L8) | `tests/apptest/test_persist_*_apptest.py`, `test_session_switch_apptest.py` |
| Field lists (one row per widget) | `tests/apptest/fields.py` |
| Logic tests (states, actions, errors) | `tests/apptest/test_<area>_logic.py` (e.g. `test_daemon_logic.py`) |
| State tables | `tests/apptest/states.py` (daemon states, navigation matrix, `EARNIE_UI_MODES`) |
| Helpers | `tests/apptest/helpers.py`: `click`, `messages`, `assert_clean`, `file_snapshot` |
| Fixtures | `tests/apptest/conftest.py`: `fake_daemon`, `shadow_mode`, `local_settings`, `log_file` |
| Form scripts | `tests/apptest/scripts/run_form_*.py` |
| Navigation matrix (no AppTest) | `tests/test_navigation_specs.py` |
| Level 2 (real browser) | `tests/apptest/e2e/` (marker `e2e`, Playwright, deselected by default) |

## When this skill applies

Run the checklist **before calling the change done** if you:

- Add / rename / remove `ui/pages/page_*.py` that exposes `render()`
- Change a page title, primary heading, or other text that an AppTest asserts
- Add a user-visible section that should stay smoke-covered (title / key widget)
- Touch `tests/apptest/**` or navigation that introduces a new page module

Non-page helpers under `ui/pages/` without `render()` (e.g. `scenario_editor_form.py`) do **not** need their own AppTest pair.

## Checklist (page smokes)

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

## Checklist (forms, save paths, logic)

Run it when you add or change an input widget, a save path, a button action, or a user message:

```
Persistence and logic tests:
- [ ] New/changed input widget has a stable key `<scope>__<field>` (language independent)
- [ ] One new row in tests/apptest/fields.py (valid value, boundaries, rejected values) instead of a new test
- [ ] Save path: T1 value survives save + new session; T3 rejected input shows an error and leaves the file byte-identical; T4 form/button: unsaved change is not persisted
- [ ] New state or action: one row in tests/apptest/states.py, assert enabled buttons, status text, called function (fake_daemon), error text
- [ ] Message set directly before st.rerun() is never visible: use a flash message and assert it
- [ ] Profile/scenario-scoped widgets: switching the object shows no value of the old one (test_session_switch_apptest.py)
- [ ] A bug found by a test: xfail(strict=True) with the reason + entry in backlog/Backlog-Bugfixes.md (New Bugs); fix only when asked, then drop the xfail
- [ ] python -m scripts.run_pytest tests/apptest tests/test_navigation_specs.py -q
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

**Persistence test** (field list driven):

```python
@pytest.mark.parametrize("spec", HOUSE_PROFILE_FIELDS, ids=lambda s: s.id)
def test_t1_value_survives_save_and_new_session(spec):
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=15)
    getattr(at, spec.kind)(key=_KEY_PREFIX + spec.suffix).set_value(spec.valid)
    at.run(timeout=15)                       # autosave: the rerun is the save
    assert stored_value(spec) == spec.valid  # read the file, not the widget
    fresh = AppTest.from_file(str(_SCRIPT)).run(timeout=15)   # new instance = new session
    assert getattr(fresh, spec.kind)(key=_KEY_PREFIX + spec.suffix).value == spec.valid
```

**Logic test** (clicks without side effects): `fake_daemon` replaces `status/start/stop/restart` in `ui.pages.page_daemon`, so buttons are clickable and no `main.py` starts; assert `fake.calls`, the status markdown and `at.error`. Never click lifecycle buttons without it.

**Traps found so far**

- `AppTest.set_value` clamps numbers to the widget `min_value`/`max_value`; "invalid" numbers inside the range are only rejected by domain rules (labels, SoC, power).
- Autosave normalizes files on the first render: take the "unchanged" baseline **after** the first run.
- `at.code` also contains non-log blocks (e.g. usage ping JSON): filter by `language`.
- `from tests.x import *` in a test module imports its tests too.
- Level 2: act only after the script has been idle for a second (`stStatusWidget` gone), Streamlit commits text inputs on Enter/blur, and some bugs exist only in the browser (session state lives in the frontend). Start with `python -m scripts.run_pytest tests/apptest/e2e -m e2e -n 0`; browser once via `python -m playwright install chromium`.

## Out of scope

- Pixel layout, chart details and visual design
- Auto-generating assertions for every widget
- Non-Streamlit UI surfaces
- Tests that start real daemons or talk to hardware (Loxone, Modbus, MQTT)
