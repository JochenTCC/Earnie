"""An aborted live cycle (no SoC yet) backs off instead of spinning (bench finding L12)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import main as main_module
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR, TRIGGER_REQUEST_OPTIMIZE
from tests.main_run_harness import patch_main_run


def _network_backend_without_soc(monkeypatch) -> None:
    patch_main_run(monkeypatch)
    monkeypatch.setattr(main_module.ehal_live, "read_ess_soc", lambda: None)
    monkeypatch.setattr(main_module.ehal_live, "is_ehal_network_backend", lambda: True)


def test_cycle_without_soc_reports_that_it_did_not_complete(monkeypatch):
    _network_backend_without_soc(monkeypatch)
    assert main_module.main(run_trigger=TRIGGER_QUARTER_HOUR) is False


def test_a_missing_soc_is_a_waiting_warning_not_an_error(monkeypatch, caplog):
    _network_backend_without_soc(monkeypatch)
    with caplog.at_level(logging.INFO, logger="main"):
        main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)
    waiting = [r for r in caplog.records if "wartet auf den EHAL-SoC" in r.getMessage()]
    assert len(waiting) == 1
    assert waiting[0].levelno == logging.WARNING
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_missing_soc_on_loxone_stays_an_error(monkeypatch, caplog):
    patch_main_run(monkeypatch)
    monkeypatch.setattr(main_module.ehal_live, "read_ess_soc", lambda: None)
    monkeypatch.setattr(main_module.ehal_live, "is_ehal_network_backend", lambda: False)
    with caplog.at_level(logging.INFO, logger="main"):
        assert main_module.main(run_trigger=TRIGGER_QUARTER_HOUR) is False
    assert any("Kein Zugriff auf Loxone SoC" in r.getMessage() for r in caplog.records)


def test_a_completed_cycle_reports_true(monkeypatch):
    patch_main_run(monkeypatch)
    assert main_module.main(run_trigger=TRIGGER_QUARTER_HOUR) is True


def test_backoff_waits_at_least_the_push_interval(monkeypatch):
    waited = MagicMock(return_value=None)
    monkeypatch.setattr(main_module, "wait_until_next_run", waited)
    assert main_module._wait_after_aborted_cycle() == TRIGGER_QUARTER_HOUR
    assert waited.call_args.kwargs["total_wait_sec"] >= 10.0


def test_backoff_returns_an_optimize_request_that_woke_it(monkeypatch):
    monkeypatch.setattr(
        main_module, "wait_until_next_run", lambda **_kw: TRIGGER_REQUEST_OPTIMIZE
    )
    assert main_module._wait_after_aborted_cycle() == TRIGGER_REQUEST_OPTIMIZE
