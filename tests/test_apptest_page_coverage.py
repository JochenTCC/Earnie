"""Coverage map: every ui/pages/page_*.py with render() has an AppTest pair.

Catches new Streamlit page modules that lack
tests/apptest/scripts/run_page_<name>.py and
tests/apptest/test_page_<name>_apptest.py.
Does not assert widget content (that stays in the AppTests themselves).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = ROOT / "ui" / "pages"
APPTEST_DIR = ROOT / "tests" / "apptest"
SCRIPTS_DIR = APPTEST_DIR / "scripts"


def _module_defines_render(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "render":
            return True
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "render":
            return True
    return False


def _page_modules_with_render() -> list[str]:
    names: list[str] = []
    for path in sorted(PAGES_DIR.glob("page_*.py")):
        if _module_defines_render(path):
            names.append(path.stem)  # page_cockpit
    return names


def _expected_pair(page_stem: str) -> tuple[Path, Path]:
    # page_cockpit → run_page_cockpit.py / test_page_cockpit_apptest.py
    short = page_stem.removeprefix("page_")
    script = SCRIPTS_DIR / f"run_page_{short}.py"
    test = APPTEST_DIR / f"test_page_{short}_apptest.py"
    return script, test


@pytest.fixture(scope="module")
def page_stems() -> list[str]:
    stems = _page_modules_with_render()
    assert stems, f"No page_*.py with render() under {PAGES_DIR}"
    return stems


def test_every_page_with_render_has_apptest_pair(page_stems: list[str]):
    missing: list[str] = []
    for stem in page_stems:
        script, test = _expected_pair(stem)
        if not script.is_file():
            missing.append(f"missing {script.relative_to(ROOT)}")
        if not test.is_file():
            missing.append(f"missing {test.relative_to(ROOT)}")
    assert not missing, "AppTest coverage gaps:\n- " + "\n- ".join(missing)


def test_run_page_script_calls_matching_render(page_stems: list[str]):
    """Entry scripts must import ui.pages.page_<name> and call .render()."""
    problems: list[str] = []
    for stem in page_stems:
        script, _ = _expected_pair(stem)
        if not script.is_file():
            continue
        text = script.read_text(encoding="utf-8")
        if f"from ui.pages import {stem}" not in text and f"import ui.pages.{stem}" not in text:
            problems.append(f"{script.name}: expected import of {stem}")
        if f"{stem}.render()" not in text and ".render()" not in text:
            problems.append(f"{script.name}: expected a render() call")
    assert not problems, "Bad AppTest entry scripts:\n- " + "\n- ".join(problems)


def test_no_orphan_apptest_pairs_for_missing_pages(page_stems: list[str]):
    """run_page_* / test_page_*_apptest without a matching page_*.py render()."""
    known = {stem.removeprefix("page_") for stem in page_stems}
    orphans: list[str] = []
    for script in sorted(SCRIPTS_DIR.glob("run_page_*.py")):
        short = script.stem.removeprefix("run_page_")
        if short not in known:
            orphans.append(str(script.relative_to(ROOT)))
    for test in sorted(APPTEST_DIR.glob("test_page_*_apptest.py")):
        short = test.stem.removeprefix("test_page_").removesuffix("_apptest")
        if short not in known:
            orphans.append(str(test.relative_to(ROOT)))
    assert not orphans, "Orphan AppTest files (no page render):\n- " + "\n- ".join(orphans)
