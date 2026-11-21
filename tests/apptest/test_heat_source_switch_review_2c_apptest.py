"""2c-2: an own JAZ / fuel price belongs to one heat-source type.

Streamlit ignores ``value=`` once a key holds state, so the shared keys kept the heat pump's
own JAZ after a switch to gas (fuel demand about 4.6 times too low).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_SOURCE = "test_home__hc_g0_heat_source_0"
_HEAT_METRIC = "Geschätzter Wärmebedarf (kWh_th/a)"
_FUEL_METRIC = "Brennstoffbedarf mit diesem Heizsystem (kWh/a Endenergie)"


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache
    from tests.conftest import _reinit_config_offline

    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(path.read_text(encoding="utf-8"))
    house["profiles"][0]["annual_kwh"] = 200000.0
    path.write_text(json.dumps(house, ensure_ascii=False), encoding="utf-8")
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    _reinit_config_offline()
    yield


def _metrics(at: AppTest) -> dict[str, float]:
    labels = [m.label for m in at.metric]
    start = labels.index(_HEAT_METRIC)
    return {m.label: float(m.value) for m in list(at.metric)[start : start + 2]}


def _ok(at: AppTest) -> AppTest:
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    return at


def test_own_jaz_does_not_follow_a_switch_to_gas() -> None:
    at = _ok(AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S))
    at.checkbox(key="test_home__hc_g0_heat_eff_use_0_heat_pump").check().run(
        timeout=_TIMEOUT_S
    )
    at.number_input(key="test_home__hc_g0_heat_eff_0_heat_pump").set_value(4.2).run(
        timeout=_TIMEOUT_S
    )
    at.selectbox(key=_SOURCE).set_value("gas").run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.checkbox(key="test_home__hc_g0_heat_eff_use_0_gas").value
    metrics = _metrics(at)
    # Gas with its default Nutzungsgrad 0.95, not the heat pump's 4.2.
    assert metrics[_FUEL_METRIC] == pytest.approx(metrics[_HEAT_METRIC] / 0.95, abs=1.0)


def test_balance_mode_renders_with_scoped_sign_checkboxes() -> None:
    """2c-1/2c-4: the import keys sit under the profile scope; the sign boxes start unticked."""
    at = _ok(AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S))
    at.radio(key="test_home__house_hist_source").set_value("balance").run(timeout=_TIMEOUT_S)
    _ok(at)
    for part in ("pv", "batt", "grid"):
        assert at.checkbox(key=f"test_home__house_hist_balance_invert_{part}").value is False
