"""SE page with a run of this session already in progress (fake subprocess).

``exit_code`` / ``cancel_requested`` in the session key ``_fake_run_cfg`` decide how
the fake run ends; polling returns at once, so the script run does not block.
"""
import streamlit as st

from ui.pages import page_backtesting  # first: ui.backtesting imports ui.backtesting_run
from ui import backtesting_run as br


class _FakeRun:
    def __init__(self, cancel_requested: bool) -> None:
        self.cancel_requested = cancel_requested
        self.progress_file = None

    def running(self) -> bool:
        return False


cfg = st.session_state.setdefault("_fake_run_cfg", {"exit_code": 130, "cancel_requested": True})
if "_fake_run_seeded" not in st.session_state:
    st.session_state["_fake_run_seeded"] = True
    st.session_state[br._ACTIVE_RUN_KEY] = {
        "run": _FakeRun(cfg["cancel_requested"]),
        "ctx": {"workers": 1, "preferred_progress_ids": [], "labels_for_order": {}, "eta_tracker": None},
        "status_label": "Szenario-Explorer läuft…",
        "start_month": None,
        "end_month": None,
    }
br.poll_backtesting_progress = lambda run, on_progress=None: None
br.finish_backtesting_run = lambda run: (cfg["exit_code"], "Traceback: boom")

page_backtesting.render()
