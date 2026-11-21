"""Tarife page: a new request for the tariff opened last opens it again (UI review 4c)."""
from __future__ import annotations

import streamlit as st
from edibert.ui import state as edibert_state

from ui.pages import page_tariffs


def test_reset_forgets_the_tariff_opened_last():
    with edibert_state.scope(page_tariffs.KEY_PREFIX):
        edibert_state.set_opened(("import", "user_a"))
    page_tariffs._reset_opened_tariff()
    with edibert_state.scope(page_tariffs.KEY_PREFIX):
        assert edibert_state.opened() is None


def test_request_is_marked_fresh():
    page_tariffs.request_tariff_page("home", ("import", "user_a"))
    assert st.session_state[page_tariffs.REQUEST_KEY]["fresh"] is True
