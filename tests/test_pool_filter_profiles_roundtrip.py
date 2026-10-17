"""Regression: house_profiles save must not strip MILP pool_filter fields.

Without this, dm4.pool_filter migration succeeds then Hauskonfigurator / any
``save_house_profiles_document`` reverts the consumer and the startup wizard loops.
"""
from __future__ import annotations

import json
from pathlib import Path

from house_config.migrate_pool_filter import (
    needs_pool_filter_migration,
    promote_pool_filter_milp,
)
from house_config.profiles_store import (
    _normalize_consumer,
    _serialize_consumer,
    save_house_profiles_document,
)


def _pre_migration_pool_filter() -> dict:
    return {
        "id": "pool_filter",
        "label": "Pool-Filter",
        "type": "generic",
        "nominal_power_kw": 0.18,
        "use_profile_csv": False,
        "absent_mode_enabled": False,
        "annual_kwh": 262.08,
        "schedule": {
            "runs_per_week": 7,
            "duration_h": 4.0,
            "start_hour": 12,
            "start_shift_h": 0.0,
        },
        "earnie_role": "known",
        "ehal_bindings": {
            "get_filter_remaining_hours": "",
            "pool.pool_filter.set_enable": "",
        },
    }


def test_serialize_keeps_milp_pool_filter_fields():
    raw = _pre_migration_pool_filter()
    promoted, _, _ = promote_pool_filter_milp(
        {"profiles": [{"id": "home", "label": "Home", "consumers": [raw]}]}
    )
    consumer = promoted["profiles"][0]["consumers"][0]
    assert consumer.get("daily_target_source") == "loxone_remaining_hours"
    assert isinstance(consumer.get("filter_schedule"), dict)

    spec = _normalize_consumer(consumer, 0, "home")
    assert "earnie_role" not in spec
    assert spec["daily_target_source"] == "loxone_remaining_hours"
    assert isinstance(spec["filter_schedule"], dict)

    out = _serialize_consumer(spec)
    assert "earnie_role" not in out
    assert out["daily_target_source"] == "loxone_remaining_hours"
    assert isinstance(out["filter_schedule"], dict)
    assert out.get("signal_type") == "binary"
    assert out.get("min_on_quarterhours") == 2


def test_save_document_does_not_reopen_pool_filter_migration(tmp_path: Path):
    backup = {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 10000.0,
                "consumers": [_pre_migration_pool_filter()],
            }
        ],
        "earnie_data_model": 4,
    }
    promoted, changed, _ = promote_pool_filter_milp(backup)
    assert changed
    assert not needs_pool_filter_migration(promoted, None)

    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), promoted)
    roundtrip = json.loads(path.read_text(encoding="utf-8"))
    assert not needs_pool_filter_migration(roundtrip, None)
