"""Tests für Chart-Hilfsfunktionen."""
from __future__ import annotations

import math

import pandas as pd

from ui.charts import _consumer_bar_pattern_shapes, _safe_int_flag


def test_safe_int_flag_treats_nan_as_zero():
    assert _safe_int_flag(float("nan")) == 0
    assert _safe_int_flag(None) == 0
    assert _safe_int_flag(1) == 1


def test_consumer_bar_pattern_shapes_ignore_nan_flags():
    segment = pd.DataFrame([
        {
            "E-Auto (kW)": 2.0,
            "E-Auto sofort_laden": float("nan"),
            "E-Auto pv_follow": float("nan"),
        }
    ])
    shapes = _consumer_bar_pattern_shapes(
        segment,
        "E-Auto (kW)",
        "E-Auto pv_follow",
        "E-Auto sofort_laden",
    )
    assert shapes == [""]
