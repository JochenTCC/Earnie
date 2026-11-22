"""AppTest: ISO-week navigation (legacy wrapper) and rolling-window date jumps.

Script: run_cov_period_navigation.py renders
``ui.consumption_comparison_panel.render_iso_week_navigation`` (key prefix
``cov_iso``) and a rolling 7-day ``render_period_navigation`` (``cov_roll``) over
the same daily series (Mon 31.08.2026 – Sun 20.09.2026 = KW 36–38).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_SCRIPT = Path(__file__).parent / "scripts" / "run_cov_period_navigation.py"
_SERIES = [
    ((date(2026, 8, 31) + timedelta(days=i)).strftime("%Y-%m-%d 12:00:00"), 1.0)
    for i in range(21)
]


def _app() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30)
    at.session_state["cov_nav_series"] = _SERIES
    return at.run()


def _result(at: AppTest, prefix: str) -> str:
    return next(m.value for m in at.markdown if m.value.startswith(prefix)).split("=", 1)[1]


def _jump(at: AppTest, key_prefix: str, text: str) -> AppTest:
    at.text_input(key=f"{key_prefix}_period_jump").input(text)
    return at.button(key=f"{key_prefix}_period_jump_btn").click().run()


def _warnings(at: AppTest) -> list[str]:
    return [c.value for c in at.caption if c.value.startswith("⚠")]


def test_iso_week_navigation_starts_at_first_week():
    at = _app()
    assert_clean(at)
    assert _result(at, "ISO_RESULT=") == "(2026, 36)"
    assert any(m.value == "**KW 36/2026 (31.08.–06.09.2026)**" for m in at.markdown)
    assert at.button(key="cov_iso_period_back").disabled


def test_empty_series_returns_none():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30).run()
    assert_clean(at)
    assert _result(at, "ISO_RESULT=") == "None"
    assert _result(at, "ROLL_RESULT=") == "None"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("38", "(2026, 38)"), ("KW 37/2026", "(2026, 37)"), ("2026-W38", "(2026, 38)")],
)
def test_iso_week_jump_selects_week(text, expected):
    at = _jump(_app(), "cov_iso", text)
    assert_clean(at)
    assert _result(at, "ISO_RESULT=") == expected
    assert _warnings(at) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("40", "⚠ KW 40 liegt außerhalb des Zeitraums."),
        ("abc", "⚠ Format: KW, z. B. 12 oder 12/2025 oder 2025-W12."),
        ("2026-W54", "⚠ Ungültige Kalenderwoche: 54."),
        ("40/2026", "⚠ KW 40/2026 (28.09.–04.10.2026) liegt außerhalb des Zeitraums."),
    ],
)
def test_iso_week_jump_errors_keep_selection(text, message):
    at = _jump(_app(), "cov_iso", text)
    assert_clean(at)
    assert _warnings(at) == [message]
    assert _result(at, "ISO_RESULT=") == "(2026, 36)"


def test_iso_week_error_clears_after_valid_jump():
    at = _jump(_app(), "cov_iso", "abc")
    at = _jump(at, "cov_iso", "37")
    assert _warnings(at) == []
    assert _result(at, "ISO_RESULT=") == "(2026, 37)"


def test_rolling_window_defaults_to_latest_and_date_jump_moves_back():
    at = _app()
    assert_clean(at)
    assert _result(at, "ROLL_RESULT=") == "2026-09-20"
    at = _jump(at, "cov_roll", "05.09.2026")
    assert_clean(at)
    assert _result(at, "ROLL_RESULT=") == "2026-09-06"
    assert _warnings(at) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("gestern", "⚠ Format: Datum, z. B. 14.09.2026."),
        ("01.01.20", "⚠ 01.01.2020 liegt außerhalb des Zeitraums."),
    ],
)
def test_rolling_date_jump_errors(text, message):
    at = _jump(_app(), "cov_roll", text)
    assert_clean(at)
    assert _warnings(at) == [message]
    assert _result(at, "ROLL_RESULT=") == "2026-09-20"
