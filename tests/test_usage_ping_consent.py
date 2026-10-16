"""UsagePing P3 — consent gate helpers (editor open; no Streamlit dialog rendering)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime_store import usage_ping as up


@pytest.fixture
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    monkeypatch.delenv("EARNIE_USAGE_PING", raising=False)
    return tmp_path / "runtime"


def test_editor_prompt_opens_dialog_when_unset(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui import usage_ping_consent as consent

    session: dict[str, Any] = {}
    monkeypatch.setattr(consent.st, "session_state", session)
    opened: list[int] = []
    monkeypatch.setattr(consent, "_consent_dialog", lambda: opened.append(1))

    consent.maybe_prompt_consent_on_editor()
    assert opened == [1]
    assert up.load_state().get("stage") != "explorer"
    assert consent._SESSION_EDITOR_ACTIVATED not in session  # noqa: SLF001


def test_editor_prompt_activates_when_consent_on(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui import usage_ping_consent as consent

    up.set_consent("on")
    session: dict[str, Any] = {}
    monkeypatch.setattr(consent.st, "session_state", session)
    opened: list[int] = []
    monkeypatch.setattr(consent, "_consent_dialog", lambda: opened.append(1))

    consent.maybe_prompt_consent_on_editor()
    assert opened == []
    assert up.load_state()["stage"] == "explorer"
    assert session[consent._SESSION_EDITOR_ACTIVATED] is True  # noqa: SLF001

    consent.maybe_prompt_consent_on_editor()
    assert opened == []


def test_editor_prompt_after_answered_choice(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui import usage_ping_consent as consent

    up.set_consent("on")
    session: dict[str, Any] = {
        consent._SESSION_DIALOG_CHOICE: "answered",  # noqa: SLF001
    }
    monkeypatch.setattr(consent.st, "session_state", session)
    opened: list[int] = []
    monkeypatch.setattr(consent, "_consent_dialog", lambda: opened.append(1))

    consent.maybe_prompt_consent_on_editor()
    assert opened == []
    assert consent._SESSION_DIALOG_CHOICE not in session  # noqa: SLF001
    assert up.load_state()["stage"] == "explorer"


def test_editor_prompt_cancel_skips_activation(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui import usage_ping_consent as consent

    session: dict[str, Any] = {
        consent._SESSION_DIALOG_CHOICE: "cancel",  # noqa: SLF001
    }
    monkeypatch.setattr(consent.st, "session_state", session)
    opened: list[int] = []
    monkeypatch.setattr(consent, "_consent_dialog", lambda: opened.append(1))

    consent.maybe_prompt_consent_on_editor()
    assert opened == []
    assert up.load_state().get("stage") != "explorer"
    assert consent._SESSION_EDITOR_ACTIVATED not in session  # noqa: SLF001


def test_dialog_intro_advertising_copy() -> None:
    from ui import usage_ping_consent as consent

    assert "Um die Qualität von Earnie permanent zu verbessern" in consent._DIALOG_INTRO
