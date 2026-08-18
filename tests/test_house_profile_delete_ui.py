"""Hausprofil delete handler session updates."""
from __future__ import annotations

from unittest.mock import MagicMock

import ui.house_config_profile_form as form


def test_handle_house_profile_delete_sets_fallback(monkeypatch):
    session = {}
    monkeypatch.setattr(form.st, "session_state", session)
    monkeypatch.setattr(form.st, "rerun", MagicMock())
    monkeypatch.setattr(form, "delete_house_profile", MagicMock())
    form._handle_house_profile_delete("extra", ["home", "extra"])
    assert session[form._SESSION_SELECT_PENDING_KEY] == "home"
    assert session[form._SESSION_SYNC_KEY] is None
    form.st.rerun.assert_called_once()


def test_handle_house_profile_delete_shows_error(monkeypatch):
    session = {}
    err = MagicMock()
    monkeypatch.setattr(form.st, "session_state", session)
    monkeypatch.setattr(form.st, "error", err)
    monkeypatch.setattr(form.st, "rerun", MagicMock())
    monkeypatch.setattr(
        form, "delete_house_profile", MagicMock(side_effect=ValueError("blocked"))
    )
    form._handle_house_profile_delete("home", ["home"])
    err.assert_called_once_with("blocked")
    form.st.rerun.assert_not_called()
    assert form._SESSION_SELECT_PENDING_KEY not in session
