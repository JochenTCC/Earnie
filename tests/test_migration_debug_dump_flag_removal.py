"""dm6.debug_dump_flag_removal drops ui.chart_debug_capture_enabled."""
from __future__ import annotations

from runtime_store.data_model import CURRENT_DATA_MODEL, DATA_MODEL_KEY
from runtime_store.migration.steps.debug_dump_flag_removal import STEP


def _docs(ui: dict) -> dict:
    return {"config.json": {DATA_MODEL_KEY: CURRENT_DATA_MODEL, "ui": ui}}


def test_detects_and_removes_flag_keeps_other_ui_keys():
    docs = _docs({"chart_debug_capture_enabled": True, "chart_debug_capture_dir": "x"})
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    assert result.changed_files == ("config.json",)
    assert result.docs["config.json"]["ui"] == {"chart_debug_capture_dir": "x"}
    assert "chart_debug_capture_enabled" in docs["config.json"]["ui"]  # input untouched
    assert not STEP.detect(result.docs)


def test_no_flag_is_no_op():
    docs = _docs({"chart_debug_capture_dir": "x"})
    assert not STEP.detect(docs)
    assert STEP.apply(docs, {}).changed_files == ()


def test_config_without_ui_is_no_op():
    assert not STEP.detect({"config.json": {DATA_MODEL_KEY: CURRENT_DATA_MODEL}})
