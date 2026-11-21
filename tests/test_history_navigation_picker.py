"""Monitor date picker: a new SA0 day in the live window resets the picker (UI review 4d)."""
from __future__ import annotations

from datetime import date
from typing import Any

from ui import history_navigation as hn


def test_picker_follows_a_new_sa0_day_in_the_same_cycle(monkeypatch):
    session: dict[str, Any] = {}
    monkeypatch.setattr(hn.st, "session_state", session)
    hn._prepare_date_picker_state(0, date(2026, 11, 20))  # noqa: SLF001
    assert session[hn.SESSION_S2_DATE_PICKER] == date(2026, 11, 20)
    # Sunrise: cycle 0 now starts on the next day.
    hn._prepare_date_picker_state(0, date(2026, 11, 21))  # noqa: SLF001
    assert session[hn.SESSION_S2_DATE_PICKER] == date(2026, 11, 21)


def test_picker_keeps_a_user_pick_while_the_day_is_unchanged(monkeypatch):
    session: dict[str, Any] = {}
    monkeypatch.setattr(hn.st, "session_state", session)
    hn._prepare_date_picker_state(0, date(2026, 11, 20))  # noqa: SLF001
    session[hn.SESSION_S2_DATE_PICKER] = date(2026, 11, 10)
    hn._prepare_date_picker_state(0, date(2026, 11, 20))  # noqa: SLF001
    assert session[hn.SESSION_S2_DATE_PICKER] == date(2026, 11, 10)
