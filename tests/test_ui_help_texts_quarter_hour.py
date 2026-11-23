"""UI help texts describe quarter-hour planning, not hourly zones (doc review 2.8)."""
from __future__ import annotations

import contextlib

import pandas as pd
import pytest

from ui import history_navigation, simulation_results


@pytest.mark.parametrize("span", ["full", "segment"])
def test_s2_zone_help_neutral_zone_is_plan_from_now(monkeypatch, span):
    monkeypatch.setattr(history_navigation, "get_s2_span", lambda: span)
    text = history_navigation.s2_zone_help_text()
    assert "aktuelle Stunde" not in text
    assert "neutral = Plan ab Jetzt" in text


class _FakeSt:
    def __init__(self) -> None:
        self.markdown_calls: list[str] = []

    def expander(self, _title):
        return contextlib.nullcontext()

    def warning(self, _text) -> None:
        pass

    def markdown(self, text) -> None:
        self.markdown_calls.append(str(text))


def test_simulation_details_help_describes_quarter_hour_milp(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(simulation_results, "st", fake)
    monkeypatch.setattr(simulation_results, "_render_simulation_table", lambda *_a, **_k: None)
    simulation_results.render_simulation_details(pd.DataFrame())
    text = "\n".join(fake.markdown_calls)
    assert "laufende Stunde" not in text
    assert "1 h ab voller Stunde" not in text
    assert "15-min-Soll-Slots ab Jetzt" in text
