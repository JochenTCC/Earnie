"""Entity source switch + Merker intercept for VO push."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from ehal import loxone_push_source as src
from integrations import loxone_client
from runtime_store import loxone_push_inbox as inbox


HOUSE = {
    "plant": {
        "ehal_bindings": {
            "sens_grid_power_active": "Earnie_Netz",
            "sens_pv_production_active": "Earnie_PV",
            "sens_absent_mode": "Earnie_Abwesend",
        }
    },
    "profiles": {
        "live": {
            "consumers": [
                {
                    "id": "trockner",
                    "type": "generic",
                    "ehal_bindings": {"sens_power_act": "Earnie_Trockner"},
                },
                {
                    "id": "e_auto",
                    "type": "ev",
                    "ehal_bindings": {
                        "sens_evcs_active_power": "Earnie_WB",
                        "get_evcs_ready_by_time": "Earnie_Fertig",
                    },
                },
            ]
        }
    },
}
COMPONENTS = {
    "batteries": [
        {
            "id": "15_kwh_speicher",
            "ehal_bindings": {"sens_ess_soc": "Earnie_SoC"},
        }
    ]
}


@pytest.fixture(autouse=True)
def _clear():
    src.clear_source_caches()
    inbox.reset_memory_for_tests()
    yield
    src.clear_source_caches()
    inbox.reset_memory_for_tests()


def test_entity_keys_and_merker_index() -> None:
    index = src.build_merker_index(HOUSE, COMPONENTS)
    assert index["Earnie_Netz"].entity_key == "plant"
    assert index["Earnie_Netz"].ehal_id == "sens_grid_power_active"
    assert index["Earnie_Trockner"].entity_key == "consumer:trockner"
    assert index["Earnie_Trockner"].ehal_id == "consumer.trockner.sens_power_act"
    assert index["Earnie_SoC"].entity_key == "battery:15_kwh_speicher"
    assert index["Earnie_Fertig"].entity_key == "consumer:e_auto"
    assert index["Earnie_Fertig"].ehal_id == "ev.e_auto.get_evcs_ready_by_time"


def test_heartbeat_source_is_always_push() -> None:
    assert src.source_for_ehal_id("heartbeat") == "push"
    assert src.source_for_ehal_id("") == "poll"


def test_parse_push_entities() -> None:
    assert src.parse_push_entities(["plant", " consumer:trockner ", ""]) == frozenset(
        {"plant", "consumer:trockner"}
    )
    assert src.parse_push_entities(None) == frozenset()


def test_source_for_merker_respects_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(src, "get_push_entities", lambda: frozenset({"consumer:trockner"}))
    assert src.source_for_merker("Earnie_Trockner") == "push"
    assert src.source_for_merker("Earnie_Netz") == "poll"


def test_push_entities_cache_reloads_when_config_mtime_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streamlit stays up across config edits — cache must follow config.json mtime."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        '{"ehal":{"loxone_push":{"entities":["consumer:trockner"]}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime_store.persist_paths.resolve_config_json_path",
        lambda: str(cfg),
    )
    src.clear_source_caches()
    assert src.get_push_entities() == frozenset({"consumer:trockner"})
    # Same mtime → cache hit
    assert src.get_push_entities() == frozenset({"consumer:trockner"})
    time.sleep(0.02)
    cfg.write_text(
        '{"ehal":{"loxone_push":{"entities":["consumer:trockner","consumer:waermepumpe"]}}}',
        encoding="utf-8",
    )
    assert src.get_push_entities() == frozenset(
        {"consumer:trockner", "consumer:waermepumpe"}
    )


def test_fetch_uses_push_when_entity_switched(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    now = datetime.now(timezone.utc)
    inbox.record_push("heartbeat", "1", now=now)
    inbox.record_push("consumer.trockner.sens_power_act", "1.5", now=now)
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(src, "get_push_entities", lambda: frozenset({"consumer:trockner"}))
    with patch.object(loxone_client, "fetch_loxone_raw_value") as raw:
        value = loxone_client.fetch_loxone_generic_value("Earnie_Trockner")
        assert value == pytest.approx(1.5)
        raw.assert_not_called()
        # plant still polls
        raw.return_value = "2.0 kW"
        assert loxone_client.fetch_loxone_generic_value("Earnie_Netz") == pytest.approx(2.0)
        raw.assert_called_once()


def test_ready_by_time_uses_push_when_ev_switched(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    now = datetime.now(timezone.utc)
    inbox.record_push("heartbeat", "1", now=now)
    inbox.record_push("ev.e_auto.get_evcs_ready_by_time", "1735689600", now=now)
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(src, "get_push_entities", lambda: frozenset({"consumer:e_auto"}))
    with patch.object(loxone_client, "_fetch_loxone_io_all") as poll_all:
        got = loxone_client.fetch_loxone_ready_by_time("Earnie_Fertig")
        assert got == pytest.approx(1735689600.0)
        poll_all.assert_not_called()


def test_ready_by_time_polls_when_ev_not_switched(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(src, "get_push_entities", lambda: frozenset())
    with patch.object(loxone_client, "_fetch_loxone_io_all", return_value=None), patch.object(
        loxone_client, "fetch_loxone_raw_value", return_value="Morgen, 08:00"
    ) as raw:
        assert loxone_client.fetch_loxone_ready_by_time("Earnie_Fertig") == "Morgen, 08:00"
        raw.assert_called_once()
