"""SE page whose run button records the subprocess arguments instead of starting it."""
import streamlit as st

from ui.pages import page_backtesting  # first: ui.backtesting imports ui.backtesting_run
from ui import backtesting_run as br


class _FakeRun:
    cancel_requested = False
    progress_file = None

    def running(self) -> bool:
        return False


def _start(**kwargs):
    st.session_state["_captured_start"] = kwargs
    return _FakeRun()


br.start_backtesting_subprocess = _start
br.poll_backtesting_progress = lambda run, on_progress=None: None
br.finish_backtesting_run = lambda run: (1, "nicht gestartet (Test)")

page_backtesting.render()
