"""Always-push source switch + Merker/EHAL intercept for VO push."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from ehal import loxone_push_source as src
from integrations import loxone_client
from optimizer import charging_schedule as cs
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
    assert index["Earnie_Netz"].ehal_id == "grid.meter.sens_grid_power_active"
    assert index["Earnie_Trockner"].entity_key == "consumer:trockner"
    assert index["Earnie_Trockner"].ehal_id == "consumer.trockner.sens_power_act"
    assert index["Earnie_SoC"].entity_key == "battery:15_kwh_speicher"
    assert index["Earnie_Fertig"].entity_key == "consumer:e_auto"
    assert index["Earnie_Fertig"].ehal_id == "ev.e_auto.get_evcs_ready_by_time"


def test_empty_merker_still_in_ehal_index() -> None:
    house = {
        "plant": {"ehal_bindings": {"sens_grid_power_active": ""}},
        "profiles": {},
    }
    ehal = src.build_ehal_index(house, {})
    assert "grid.meter.sens_grid_power_active" in ehal
    assert ehal["grid.meter.sens_grid_power_active"].merker == ""
    assert src.build_merker_index(house, {}) == {}


def test_heartbeat_source_is_always_push() -> None:
    assert src.source_for_ehal_id("heartbeat") == "push"
    assert src.source_for_ehal_id("") == "poll"
    assert src.source_for_ehal_id("sens_grid_power_active") == "push"
    assert src.source_for_ehal_id("sens_pv_energy") == "push"
    assert src.source_for_ehal_id("sens_grid_energy_import") == "push"
    assert src.source_for_ehal_id("sens_grid_energy_export") == "push"
    assert src.is_pushable_kind("sens_energy_total")
    assert src.is_pushable_kind("sens_energy_export")


def test_parse_push_entities_legacy() -> None:
    assert src.parse_push_entities(["plant", " consumer:trockner ", ""]) == frozenset(
        {"plant", "consumer:trockner"}
    )
    assert src.parse_push_entities(None) == frozenset()
    assert src.load_push_entities_from_config({"ehal": {"loxone_push": {"entities": ["plant"]}}}) == frozenset()


def test_source_for_merker_always_push_when_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(
        src,
        "get_ehal_index",
        lambda: src.build_ehal_index(HOUSE, COMPONENTS),
    )
    assert src.source_for_merker("Earnie_Trockner") == "push"
    assert src.source_for_merker("Earnie_Netz") == "push"
    assert src.source_for_merker("Unknown_Merker") == "poll"


def test_fetch_uses_push_for_all_indexed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    now = datetime.now(timezone.utc)
    inbox.record_push("heartbeat", "1", now=now)
    inbox.record_push("consumer.trockner.sens_power_act", "1.5", now=now)
    inbox.record_push("grid.meter.sens_grid_power_active", "2.25", now=now)
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(
        src,
        "get_ehal_index",
        lambda: src.build_ehal_index(HOUSE, COMPONENTS),
    )
    with patch.object(loxone_client, "fetch_loxone_raw_value") as raw:
        assert loxone_client.fetch_loxone_generic_value("Earnie_Trockner") == pytest.approx(
            1.5
        )
        assert loxone_client.fetch_loxone_generic_value("Earnie_Netz") == pytest.approx(
            2.25
        )
        raw.assert_not_called()


def test_fetch_by_ehal_id_without_merker(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    now = datetime.now(timezone.utc)
    inbox.record_push("heartbeat", "1", now=now)
    inbox.record_push("grid.meter.sens_grid_power_active", "3.0", now=now)
    house = {"plant": {"ehal_bindings": {"sens_grid_power_active": ""}}, "profiles": {}}
    monkeypatch.setattr(src, "get_merker_index", lambda: src.build_merker_index(house, {}))
    monkeypatch.setattr(src, "get_ehal_index", lambda: src.build_ehal_index(house, {}))
    with patch.object(loxone_client, "fetch_loxone_raw_value") as raw:
        assert loxone_client.fetch_loxone_generic_value(
            "grid.meter.sens_grid_power_active"
        ) == pytest.approx(3.0)
        raw.assert_not_called()


def test_ready_by_time_uses_push_numeric(
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
    monkeypatch.setattr(
        src,
        "get_ehal_index",
        lambda: src.build_ehal_index(HOUSE, COMPONENTS),
    )
    with patch.object(loxone_client, "_fetch_loxone_io_all") as poll_all:
        got = loxone_client.fetch_loxone_ready_by_time("Earnie_Fertig")
        assert got == pytest.approx(1735689600.0)
        poll_all.assert_not_called()


def test_ready_by_time_push_text_reaches_wecker_parser(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: inbox Tna text → fetch → parse_loxone_ready_by_time."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    now = datetime.now(timezone.utc)
    inbox.record_push("heartbeat", "1", now=now)
    inbox.record_push("ev.e_auto.get_evcs_ready_by_time", "Morgen, 07:00", now=now)
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(
        src,
        "get_ehal_index",
        lambda: src.build_ehal_index(HOUSE, COMPONENTS),
    )
    with patch.object(loxone_client, "_fetch_loxone_io_all") as poll_all:
        raw = loxone_client.fetch_loxone_ready_by_time("Earnie_Fertig")
        assert raw == "Morgen, 07:00"
        poll_all.assert_not_called()
    from_dt = datetime(2026, 10, 8, 12, 0, 0)
    assert cs.parse_loxone_ready_by_time(raw, from_dt) == datetime(2026, 10, 9, 7, 0, 0)


def test_ready_by_time_no_poll_fallback_when_bound(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(HOUSE, COMPONENTS),
    )
    monkeypatch.setattr(
        src,
        "get_ehal_index",
        lambda: src.build_ehal_index(HOUSE, COMPONENTS),
    )
    with patch.object(loxone_client, "_fetch_loxone_io_all") as poll_all, patch.object(
        loxone_client, "fetch_loxone_raw_value"
    ) as raw:
        assert loxone_client.fetch_loxone_ready_by_time("Earnie_Fertig") is None
        poll_all.assert_not_called()
        raw.assert_not_called()
