"""Navigation im Bereich Konfiguration: N1 (Seitenmatrix) und N2 (EARNIE_UI_MODES).

N1 läuft direkt gegen ``ui.navigation.build_page_specs()``; ``PageSpec`` ist unabhängig von
Streamlit. Die Setup-Zustände (Onboarding, Planungsbereitschaft, Szenarieneditor, Smarthome-
Backend, Cloud-Demo) werden als Prädikate ersetzt, die Matrix steht in
``tests/apptest/states.py``. N2 prüft die Hinweise in der Sidebar per AppTest.
"""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from tests.apptest.states import (
    NAV_CASES,
    NAV_READY,
    NAV_SECTIONS,
    UI_MODES_ENV_CASES,
)
from ui import navigation

_PREDICATES = {
    "restricted": (navigation, "is_setup_navigation_restricted"),
    "betrieb": (navigation, "is_betrieb_unlocked"),
    "planning": (navigation, "is_planning_ready"),
    "editor": (navigation, "is_scenario_editor_unlocked"),
}


def _apply_setup(monkeypatch, **overrides) -> None:
    state = {**NAV_READY, **overrides}
    for key, (module, name) in _PREDICATES.items():
        monkeypatch.setattr(module, name, lambda value=state[key]: value)
    # ``needs_sb_setup`` und ``is_cloud_demo`` werden erst beim Aufruf importiert.
    import runtime_store.cloud_demo as cloud_demo
    import ui.setup_readiness as setup_readiness

    monkeypatch.setattr(setup_readiness, "needs_sb_setup", lambda: state["sb_setup"])
    monkeypatch.setattr(cloud_demo, "is_cloud_demo", lambda: state["cloud_demo"])


@pytest.mark.parametrize("case_id,modes,setup,expected_paths,expected_default", NAV_CASES,
                         ids=[c[0] for c in NAV_CASES])
def test_n1_page_list_per_mode_and_setup_state(
    monkeypatch, case_id, modes, setup, expected_paths, expected_default
) -> None:
    _apply_setup(monkeypatch, **setup)

    specs = navigation.build_page_specs(modes)

    assert [s.url_path for s in specs] == expected_paths
    defaults = [s.url_path for s in specs if s.default]
    assert defaults == [expected_default], "genau eine Startseite erwartet"
    assert {s.url_path: s.section for s in specs} == {p: NAV_SECTIONS[p] for p in expected_paths}
    assert len({s.title for s in specs}) == len(specs)


def test_n1_matrix_covers_every_registered_page() -> None:
    """Jede Seite aus ``NAV_SECTIONS`` kommt in mindestens einem Fall der Matrix vor."""
    seen = {path for _id, _modes, _setup, paths, _default in NAV_CASES for path in paths}
    assert seen == set(NAV_SECTIONS)


# --- N2: EARNIE_UI_MODES ----------------------------------------------------------------


def _notices_app() -> None:
    from ui.mode_selector import render_ui_mode_env_notices

    render_ui_mode_env_notices()


@pytest.mark.parametrize("raw,expected_keys,info_fragments,expects_warning", UI_MODES_ENV_CASES)
def test_n2_env_value_gives_expected_modes_and_sidebar_hints(
    monkeypatch, raw, expected_keys, info_fragments, expects_warning
) -> None:
    from ui.mode_selector import get_enabled_ui_mode_keys

    monkeypatch.setenv("EARNIE_UI_MODES", raw)
    assert get_enabled_ui_mode_keys() == expected_keys

    at = AppTest.from_function(_notices_app).run()

    assert not at.exception
    infos = [i.value for i in at.sidebar.info]
    warnings = [w.value for w in at.sidebar.warning]
    for fragment in info_fragments:
        assert any(fragment in text for text in infos), (fragment, infos)
    assert (len(infos) > 0) is bool(info_fragments)
    assert (len(warnings) > 0) is expects_warning
    if expects_warning:
        assert "Ungültige EARNIE_UI_MODES" in warnings[0]


def test_n2_unset_env_shows_no_hint_and_uses_default_modes(monkeypatch) -> None:
    from ui.mode_selector import get_enabled_ui_mode_keys

    monkeypatch.delenv("EARNIE_UI_MODES", raising=False)

    at = AppTest.from_function(_notices_app).run()

    assert not at.exception
    assert not at.sidebar.info and not at.sidebar.warning
    assert get_enabled_ui_mode_keys()[:3] == ["sunset2sunset", "scenario_explorer", "live_environment"]


@pytest.mark.parametrize("raw", ["", "   "])
def test_n2_blank_env_is_treated_as_unset(monkeypatch, raw) -> None:
    from ui.mode_selector import get_enabled_ui_mode_keys

    monkeypatch.setenv("EARNIE_UI_MODES", raw)

    at = AppTest.from_function(_notices_app).run()

    assert not at.sidebar.info and not at.sidebar.warning
    assert get_enabled_ui_mode_keys()[:3] == ["sunset2sunset", "scenario_explorer", "live_environment"]
