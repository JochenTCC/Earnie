"""AppTest: the SE cost table switches its baseline after the run, without a new run."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_backtesting_cost_table.py"


def _delta(at: AppTest, label: str) -> tuple[str, str]:
    frame = at.dataframe[0].value
    column = next(name for name in frame.columns if name.startswith("Δ vs"))
    return column, frame.set_index("Szenario").loc[label, column]


def test_default_is_lives_referenz_ohne_speicher_and_the_switch_recomputes_nothing():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30).run()
    assert not at.exception
    assert at.selectbox(key="backtesting_baseline").options == [
        "Live (mit Earnie)",
        "Historisch",
        "Referenz ohne Speicher",
        "Wechselrichter-Eigenverbrauch (L1)",
    ]
    assert _delta(at, "Dynamisch") == ("Δ vs Referenz ohne Speicher von Live [€]", "-600,00 €")

    at.radio(key="backtesting_baseline_series").set_value("own").run()
    assert _delta(at, "Dynamisch") == ("Δ vs Referenz ohne Speicher (eigene) [€]", "-500,00 €")

    at.selectbox(key="backtesting_baseline").set_value("l1").run()
    assert _delta(at, "Dynamisch") == ("Δ vs Wechselrichter-Eigenverbrauch (L1) (eigene) [€]", "-200,00 €")

    at.selectbox(key="backtesting_baseline").set_value("live").run()
    assert not at.radio
    assert _delta(at, "Dynamisch") == ("Δ vs Live (mit Earnie) [€]", "-100,00 €")
    assert _delta(at, "Live")[1] == "—"


def test_log_from_before_the_selection_says_so():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30)
    at.session_state["_meta"] = {
        "live_scenario_id": "live",
        "scenario_ids": ["live"],
        "labels": {"live": "Live"},
        "summary": {"total_eur": {"live": 1000.0}},
    }
    at.run()
    assert not at.exception
    assert not at.selectbox
    assert any("Neuberechnung" in info.value for info in at.info)
