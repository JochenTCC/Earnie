"""AppTest: SE headline and ladder expander render from a log (RuleRef P4)."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_backtesting_ladder.py"


def test_headline_and_expander_render():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30).run()
    assert not at.exception
    assert at.subheader[0].value == "Ersparnis gegen Standard-Regeln"
    metric = at.metric[0]
    assert metric.label == "Live"
    assert metric.value == "100,00 € gespart"
    assert metric.delta == "Anteil der Regeln: 83 %"
    assert len(at.expander) == 1
    assert not at.expander[0].proto.expanded
    assert list(at.expander[0].dataframe[0].value["Stufe"]) == [
        "Ohne Steuerung",
        "Wechselrichter-Eigenverbrauch",
        "Standard-Regeln",
        "Earnie",
    ]
