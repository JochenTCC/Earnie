"""Shadow R3 daemon orchestration helpers (callable without full main)."""
from __future__ import annotations

from runtime_store.shadow.daemon import (
    after_prod_cycle,
    maybe_clear_auth_gate,
    maybe_flush_after_sampler,
    prepare_shadow_cycle,
    resolve_next_trigger,
)


def test_maybe_flush_after_sampler_prod_only(monkeypatch):
    calls: list[str] = []
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.setattr(
        "runtime_store.shadow.feed.flush_after_sampler",
        lambda: calls.append("flush"),
    )
    maybe_flush_after_sampler()
    assert calls == ["flush"]

    calls.clear()
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    maybe_flush_after_sampler()
    assert calls == []


def test_maybe_flush_after_sampler_swallows_errors(monkeypatch):
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)

    def boom():
        raise RuntimeError("flush failed")

    monkeypatch.setattr("runtime_store.shadow.feed.flush_after_sampler", boom)
    maybe_flush_after_sampler()  # must not raise


def test_maybe_clear_auth_gate_shadow(monkeypatch):
    cleared: list[bool] = []
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setattr(
        "runtime_store.loxone_auth_error.clear_loxone_auth_error",
        lambda: cleared.append(True),
    )
    assert maybe_clear_auth_gate() is True
    assert cleared == [True]


def test_maybe_clear_auth_gate_prod(monkeypatch):
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    assert maybe_clear_auth_gate() is False


def test_prepare_shadow_cycle_skip(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setattr(
        "runtime_store.shadow.cycle.consume_optimize_trigger",
        lambda: False,
    )
    monkeypatch.setattr(
        "runtime_store.shadow.cycle.wait_for_prod_cycle",
        lambda: {"skipped": True, "reason": "stale"},
    )
    prep = prepare_shadow_cycle("quarter", optimize_trigger="optimize")
    assert prep.skipped is True
    assert prep.reason == "stale"
    assert prep.trigger == "quarter"


def test_prepare_shadow_cycle_optimize_trigger(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setattr(
        "runtime_store.shadow.cycle.consume_optimize_trigger",
        lambda: True,
    )
    monkeypatch.setattr(
        "runtime_store.shadow.cycle.wait_for_prod_cycle",
        lambda: {"skipped": False},
    )
    prep = prepare_shadow_cycle("quarter", optimize_trigger="optimize")
    assert prep.skipped is False
    assert prep.trigger == "optimize"


def test_prepare_shadow_cycle_prod_passthrough(monkeypatch):
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    prep = prepare_shadow_cycle("quarter", optimize_trigger="optimize")
    assert prep.skipped is False
    assert prep.trigger == "quarter"


def test_after_prod_cycle_invokes_flush_and_superset(monkeypatch):
    calls: list[str] = []
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.setattr(
        "runtime_store.shadow.superset.run_after_cycle",
        lambda: calls.append("superset"),
    )
    monkeypatch.setattr(
        "runtime_store.shadow.feed.flush_after_cycle",
        lambda: calls.append("flush"),
    )
    after_prod_cycle()
    assert calls == ["superset", "flush"]

    calls.clear()
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    after_prod_cycle()
    assert calls == []


def test_resolve_next_trigger_early_and_shadow_mirror(monkeypatch):
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    assert (
        resolve_next_trigger("optimize", "quarter", optimize_trigger="optimize")
        == "optimize"
    )
    assert (
        resolve_next_trigger(None, "quarter", optimize_trigger="optimize")
        == "quarter"
    )

    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setattr(
        "runtime_store.shadow.cycle.consume_optimize_trigger",
        lambda: True,
    )
    assert (
        resolve_next_trigger(None, "quarter", optimize_trigger="optimize")
        == "optimize"
    )
