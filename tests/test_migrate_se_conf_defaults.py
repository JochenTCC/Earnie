"""dm4.se_conf_defaults — fill missing scenario_explorer_conf keys from example."""
from __future__ import annotations

import copy

from runtime_store.config_drift import find_config_drift, _load_json
from runtime_store.migration.steps.se_conf_defaults import (
    STEP_ID,
    apply,
    detect,
)
from runtime_store.persist_paths import bundled_config_example_file


def _docs_missing_se_keys() -> dict:
    return {
        "config.json": {
            "earnie_data_model": 4,
            "live_scenario_id": "live",
            "scenario_explorer_conf": {
                "path_cons_data": "runtime/cons_data.csv",
                "cons_data_retention_months": 24,
                "cons_data_write_mode": "hourly",
                "price_source": "api",
                "price_provider": "energy_charts",
                "price_range": "last_12_months",
            },
        }
    }


def test_detect_true_when_se_keys_missing():
    assert detect(_docs_missing_se_keys()) is True


def test_detect_false_when_se_block_complete():
    docs = _docs_missing_se_keys()
    example = _load_json(bundled_config_example_file())
    docs["config.json"]["scenario_explorer_conf"] = copy.deepcopy(
        example["scenario_explorer_conf"]
    )
    assert detect(docs) is False


def test_detect_false_on_pre_dm4_packs():
    docs = _docs_missing_se_keys()
    docs["config.json"]["earnie_data_model"] = 2
    assert detect(docs) is False


def test_apply_fills_only_missing_keys_and_clears_drift():
    docs = _docs_missing_se_keys()
    before_keys = set(docs["config.json"]["scenario_explorer_conf"])
    result = apply(docs, {})
    assert result.changed_files == ("config.json",)
    sim = result.docs["config.json"]["scenario_explorer_conf"]
    assert sim["path_cons_data"] == "runtime/cons_data.csv"
    assert "season_mirror_to_last_month" in sim
    assert "export_price_series" in sim
    assert before_keys <= set(sim)
    assert detect(result.docs) is False
    example = _load_json(bundled_config_example_file())
    drift = find_config_drift(example, result.docs["config.json"])
    assert not any(item.path.startswith("scenario_explorer_conf.") for item in drift)


def test_apply_idempotent_when_nothing_missing():
    docs = _docs_missing_se_keys()
    filled = apply(docs, {}).docs
    again = apply(filled, {})
    assert again.changed_files == ()
    assert again.docs["config.json"] == filled["config.json"]


def test_step_id_stable():
    assert STEP_ID == "dm4.se_conf_defaults"
