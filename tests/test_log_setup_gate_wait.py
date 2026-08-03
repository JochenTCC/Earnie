"""Throttle setup-gate wait logs (once at level, then DEBUG)."""
from __future__ import annotations

import logging

from runtime_store.setup_gate_log import log_setup_gate_wait


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_log_setup_gate_wait_warns_once_then_debug() -> None:
    log = logging.getLogger("test_setup_gate_wait")
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    handler = _ListHandler()
    log.addHandler(handler)
    state: dict = {}

    log_setup_gate_wait(state, "planning_offline", "msg %s", 1, log=log)
    log_setup_gate_wait(state, "planning_offline", "msg %s", 2, log=log)
    log_setup_gate_wait(state, "planning_offline", "msg %s", 3, log=log)

    levels = [r.levelno for r in handler.records]
    assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    assert handler.records[0].getMessage() == "msg 1"


def test_log_setup_gate_wait_resets_on_gate_change() -> None:
    log = logging.getLogger("test_setup_gate_wait_change")
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    handler = _ListHandler()
    log.addHandler(handler)
    state: dict = {}

    log_setup_gate_wait(state, "a", "first", log=log)
    log_setup_gate_wait(state, "a", "again", log=log)
    log_setup_gate_wait(state, "b", "other", level=logging.INFO, log=log)
    log_setup_gate_wait(state, "b", "other-again", level=logging.INFO, log=log)

    levels = [r.levelno for r in handler.records]
    assert levels == [
        logging.WARNING,
        logging.DEBUG,
        logging.INFO,
        logging.DEBUG,
    ]
