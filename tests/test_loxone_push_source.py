"""Entity source switch + Merker intercept for VO push."""
from __future__ import annotations

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
    assert "Earnie_Fertig" not in index  # AlarmClock never pushed


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
