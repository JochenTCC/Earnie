"""Sponsor button opt-out state and sidebar rendering."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from runtime_store import sponsoring

_TIMEOUT_S = 30


@pytest.fixture
def sponsor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "sponsoring.json"
    monkeypatch.setattr(
        "runtime_store.sponsoring.sponsoring_state_file", lambda: str(path)
    )
    return path


def test_missing_state_means_not_opted_out(sponsor_state: Path) -> None:
    assert not sponsor_state.exists()
    assert sponsoring.is_opted_out() is False


def test_set_opt_out_persists_and_undoes(sponsor_state: Path) -> None:
    sponsoring.set_opt_out(True)
    assert sponsoring.is_opted_out() is True
    data = json.loads(sponsor_state.read_text(encoding="utf-8"))
    assert data["opt_out"] is True
    assert data["opt_out_changed_at"]
    sponsoring.set_opt_out(False)
    assert sponsoring.is_opted_out() is False


def test_unreadable_state_means_not_opted_out(sponsor_state: Path) -> None:
    sponsor_state.write_text("{not json", encoding="utf-8")
    assert sponsoring.is_opted_out() is False


def test_non_bool_opt_out_is_not_opt_out(sponsor_state: Path) -> None:
    sponsor_state.write_text('{"opt_out": "yes"}', encoding="utf-8")
    assert sponsoring.is_opted_out() is False


def test_sponsors_url_points_to_organisation() -> None:
    assert sponsoring.SPONSORS_URL == "https://github.com/sponsors/Earnie-HEMS"


def _sidebar_app(state_path: str) -> None:
    import runtime_store.sponsoring as mod

    mod.sponsoring_state_file = lambda: state_path
    from ui.sponsor_button import (
        render_sponsor_opt_out_checkbox,
        render_sponsor_sidebar_button,
    )

    render_sponsor_sidebar_button()
    with __import__("streamlit").sidebar:
        render_sponsor_opt_out_checkbox()


def _button_labels(at: AppTest) -> list[str]:
    return [
        getattr(el.proto, "label", "")
        for el in at.sidebar
        if getattr(el.proto, "url", "")
    ]


def _divider_count(at: AppTest) -> int:
    from ui.sponsor_button import SPONSOR_DIVIDER_HTML

    return sum(1 for el in at.sidebar.markdown if el.value == SPONSOR_DIVIDER_HTML)


def test_button_shown_hidden_and_shown_again(tmp_path: Path) -> None:
    state_path = str(tmp_path / "sponsoring.json")
    at = AppTest.from_function(_sidebar_app, args=(state_path,)).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert _button_labels(at) == ["Earnie unterstützen"]
    assert _divider_count(at) == 1

    at.sidebar.checkbox[0].check().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert _button_labels(at) == []
    assert _divider_count(at) == 0
    assert json.loads(Path(state_path).read_text(encoding="utf-8"))["opt_out"] is True

    at.sidebar.checkbox[0].uncheck().run(timeout=_TIMEOUT_S)
    assert _button_labels(at) == ["Earnie unterstützen"]


def test_sponsor_button_sits_above_backup_transfer_in_app() -> None:
    app_src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    button_idx = app_src.index("    render_sponsor_sidebar_button()\n    render_backup_transfer_sidebar()")
    assert button_idx < app_src.index("navigation.run()")
