"""Unit tests for compact form layout helpers (no Streamlit runtime)."""
from __future__ import annotations

from ui.form_layout import DEFAULT_RATIOS, WIDE_LABEL_RATIOS, _with_collapsed_label


def test_default_and_wide_ratios() -> None:
    assert DEFAULT_RATIOS == (2.0, 3.0)
    assert WIDE_LABEL_RATIOS == (3.0, 5.0)
    assert sum(DEFAULT_RATIOS) > 0
    assert sum(WIDE_LABEL_RATIOS) > 0


def test_with_collapsed_label_forces_visibility() -> None:
    original = {"key": "x", "label_visibility": "visible", "min_value": 1}
    out = _with_collapsed_label(original)
    assert out["label_visibility"] == "collapsed"
    assert out["key"] == "x"
    assert out["min_value"] == 1
    assert original["label_visibility"] == "visible"
