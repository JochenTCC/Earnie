"""Switching a consumer to "Haus Wärme" on the house profile tab (dogfooding bug).

The expander title computes the annual kWh from a live preview before the type-specific
fields render. On the switch rerun the heat-source selectbox has no session value yet,
so the preview must take the heat source the selectbox is about to show.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from house_config.profiles_store import clear_house_profiles_doc_cache

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_TYPE_KEY = "test_home__hc_g0_type_0"


def _profile_with_single_generic_consumer() -> None:
    path = os.environ["EARNIE_HOUSE_PROFILES_PATH"]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    doc["profiles"][0]["consumers"] = [
        {
            "id": "wasch", "label": "Waschmaschine", "type": "generic",
            "annual_kwh": 300.0, "nominal_power_kw": 2.0,
            "schedule": {
                "runs_per_week": 3, "duration_h": 2.0, "start_hour": 10, "start_shift_h": 1.0,
            },
        }
    ]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False)
    clear_house_profiles_doc_cache()


def test_switch_to_haus_waerme_renders_with_preselected_heat_source() -> None:
    _profile_with_single_generic_consumer()
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not at.exception

    at.selectbox(key=_TYPE_KEY).set_value("thermal_annual")
    at.run(timeout=_TIMEOUT_S)

    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="test_home__hc_g0_heat_source_0").value == "heat_pump"
    assert at.selectbox(key="test_home__hc_g0_wp_0").value == "luft"
    assert any("(Haus Wärme)" in exp.label for exp in at.expander)
