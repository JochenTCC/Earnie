"""``ui.flash``: notices survive ``st.rerun()`` and show exactly once."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = """
import streamlit as st
from ui.flash import flash, render_flash_notices

render_flash_notices()
if st.button("save", key="save"):
    flash("success", "gespeichert")
    flash("warning", "aber Vorsicht")
    st.rerun()
"""


def test_flash_notices_are_shown_after_rerun_and_only_once() -> None:
    at = AppTest.from_string(_SCRIPT).run()
    at.button(key="save").click().run()

    assert [e.value for e in at.success] == ["gespeichert"]
    assert [e.value for e in at.warning] == ["aber Vorsicht"]

    at.run()
    assert not at.success
    assert not at.warning


def test_flash_rejects_unknown_kind() -> None:
    from ui.flash import flash

    with pytest.raises(ValueError, match="Unknown flash kind"):
        flash("fatal", "x")
