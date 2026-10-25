"""dm4.flexible_consumers_overlay — drop the legacy config.json overlay block."""
from __future__ import annotations

import pytest

from runtime_store.migration.steps.flexible_consumers_overlay import (
    STEP_ID,
    apply,
    detect,
)
from settings.legacy_config_gates import reject_legacy_config_blocks


def _docs(overlay) -> dict:
    return {"config.json": {"earnie_data_model": 4, "flexible_consumers": overlay}}


def test_detect_true_when_key_present():
    assert detect(_docs([])) is True


def test_detect_false_when_key_absent():
    assert detect({"config.json": {"earnie_data_model": 4}}) is False


def test_apply_drops_empty_overlay():
    result = apply(_docs([]), {})
    assert not result.blockers
    assert result.changed_files == ("config.json",)
    assert "flexible_consumers" not in result.docs["config.json"]
    assert detect(result.docs) is False


def test_apply_blocks_non_empty_overlay_and_keeps_docs():
    docs = _docs([{"id": "swimspa"}, {"id": "ev"}])
    result = apply(docs, {})
    assert result.changed_files == ()
    assert [b.step_id for b in result.blockers] == [STEP_ID]
    assert "swimspa" in result.blockers[0].message_de
    assert result.docs == docs


@pytest.mark.parametrize("overlay", [[], [{"id": "swimspa"}]])
def test_gate_rejects_leftover_block(overlay):
    with pytest.raises(ValueError, match="flexible_consumers"):
        reject_legacy_config_blocks({"flexible_consumers": overlay})
