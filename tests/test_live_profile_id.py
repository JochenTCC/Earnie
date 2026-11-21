"""Live-Szenario house profile resolution (Tarife page, Loxone meter energy)."""
from __future__ import annotations

import json
import logging

from ui.house_config_entities_io import resolve_live_profile_id


def _live_refs(monkeypatch, house_profile_id: str) -> None:
    monkeypatch.setattr(
        "ui.house_config_entities_io.get_live_scenario_refs",
        lambda: {"house_profile_id": house_profile_id},
    )


def test_live_profile_id_known(monkeypatch):
    _live_refs(monkeypatch, "b")
    assert resolve_live_profile_id({"profiles": {"a": {}, "b": {}}}) == "b"
    assert resolve_live_profile_id({"profiles": [{"id": "a"}, {"id": "b"}]}) == "b"


def test_live_profile_id_empty_uses_first_like_the_daemon(monkeypatch):
    _live_refs(monkeypatch, "")
    assert resolve_live_profile_id({"profiles": {"a": {}, "b": {}}}) == "a"
    assert resolve_live_profile_id({"profiles": [{"id": "a"}, {"id": "b"}]}) == "a"
    assert resolve_live_profile_id({"profiles": {}}) == ""


def test_live_profile_id_unknown_is_not_replaced_by_another_profile(monkeypatch):
    _live_refs(monkeypatch, "deleted")
    assert resolve_live_profile_id({"profiles": {"a": {}, "b": {}}}) == ""
    assert resolve_live_profile_id({"profiles": [{"id": "a"}]}) == ""


def test_meter_energy_reads_no_consumers_for_unknown_live_profile(
    monkeypatch, tmp_path, caplog
):
    from integrations import loxone_meter_energy

    path = tmp_path / "house_profiles.json"
    path.write_text(
        json.dumps({"profiles": {"a": {"consumers": [{"id": "c1", "type": "flex"}]}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime_store.persist_paths.resolve_house_profiles_json_path", lambda: str(path)
    )
    monkeypatch.setattr(
        "house_config.profiles_store.load_house_profiles_document",
        lambda p: json.loads(open(p, encoding="utf-8").read()),
    )
    _live_refs(monkeypatch, "deleted")
    with caplog.at_level(logging.WARNING, logger=loxone_meter_energy.__name__):
        assert loxone_meter_energy.load_live_profile_consumers() == []
    assert "house_profile_id" in caplog.text

    _live_refs(monkeypatch, "a")
    assert [c["id"] for c in loxone_meter_energy.load_live_profile_consumers()] == ["c1"]
