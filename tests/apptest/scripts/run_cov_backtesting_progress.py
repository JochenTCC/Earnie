"""SE page with a fake run of this session that reports progress (coverage tests).

Session key ``_fake_progress_cfg``:
- ``snapshot``: progress snapshot handed to the page's ``on_progress`` callback
- ``running``: True stops the script while the run is "still going" (cancel button stays)
- ``workers``: worker count in the run context
Cancel calls are recorded in ``_fake_cancel_calls``.
"""
import streamlit as st

from ui.pages import page_backtesting  # first: ui.backtesting imports ui.backtesting_run
from ui import backtesting_run as br
from simulation.backtesting_progress import ProgressEtaTracker


class _FakeRun:
    def __init__(self) -> None:
        self.cancel_requested = False
        self.progress_file = None

    def running(self) -> bool:
        return False


cfg = st.session_state.setdefault("_fake_progress_cfg", {})
st.session_state.setdefault("_fake_cancel_calls", [])
if "_fake_progress_seeded" not in st.session_state:
    st.session_state["_fake_progress_seeded"] = True
    st.session_state[br._ACTIVE_RUN_KEY] = {
        "run": _FakeRun(),
        "ctx": {
            "workers": cfg.get("workers", 2),
            "preferred_progress_ids": ["historical_reference", "live", "ref:live"],
            "labels_for_order": {
                "historical_reference": "Historisch",
                "live": "Live",
                "ref:live": "Referenz Live",
            },
            "eta_tracker": ProgressEtaTracker(),
        },
        "status_label": "Szenario-Explorer läuft…",
        "calendar_month": 6,
    }


def _poll(run, on_progress=None):
    if on_progress is not None and cfg.get("snapshot") is not None:
        on_progress(cfg["snapshot"])
    if cfg.get("running"):
        st.stop()


def _cancel(run):
    run.cancel_requested = True
    st.session_state["_fake_cancel_calls"].append("cancel")


br.poll_backtesting_progress = _poll
br.cancel_backtesting_run = _cancel
br.finish_backtesting_run = lambda run: (cfg.get("exit_code", 0), "")

page_backtesting.render()
