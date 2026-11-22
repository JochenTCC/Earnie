"""AppTest: "Gehe nach Oben" under the service log scrolls back to the log anchor.

The button only sets a pending flag and reruns; the log fragment then injects the
scroll script once and clears the flag. No lifecycle button is clicked here.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_daemon.py"
_PENDING_KEY = "daemon_log_scroll_top"


def _scroll_scripts(at: AppTest) -> list[str]:
    return [
        str(el.proto.body)
        for el in at.get("html")
        if "scrollIntoView" in str(el.proto.body)
    ]


def test_go_top_injects_scroll_script_once_and_clears_flag():
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=30)
    assert not at.exception
    assert _scroll_scripts(at) == []

    at.button(key="daemon_log_go_top").click().run(timeout=30)
    assert not at.exception
    scripts = _scroll_scripts(at)
    assert len(scripts) == 1
    assert "getElementById('daemon-log-top')" in scripts[0]
    assert _PENDING_KEY not in at.session_state

    at.run(timeout=30)
    assert _scroll_scripts(at) == []
