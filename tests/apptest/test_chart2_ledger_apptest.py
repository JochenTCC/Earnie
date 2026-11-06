"""AppTest: Chart 2 account view with a ledger state file and without one, anchor switch (Account view P2)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui.chart_account_render import SESSION_ANCHOR_MODE
from ui.chart_account_view import ANCHOR_NOW, ANCHOR_START
from ui.chart_ledger_savings import HINT_NOT_RUNNING

_SCRIPT = Path(__file__).parent / "scripts" / "run_chart2_ledger.py"
_TZ = ZoneInfo("Europe/Vienna")


def _run(tmp_path, monkeypatch) -> AppTest:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception
    return at


def _captions(at: AppTest) -> list[str]:
    return [item.value for item in at.caption]


def _chart_spec(at: AppTest) -> str:
    return at.get("plotly_chart")[0].proto.spec


def _labels(at: AppTest) -> list[str]:
    import json

    layout = json.loads(_chart_spec(at))["layout"]
    return [item["text"] for item in layout.get("annotations", [])]


def test_without_ledger_state_the_past_counts_zero_and_the_chart_gives_the_hint(tmp_path, monkeypatch):
    at = _run(tmp_path, monkeypatch)

    assert HINT_NOT_RUNNING in _captions(at)
    assert "Bisher: 0,00 € gespart" in _labels(at)


def _with_ledger(tmp_path, monkeypatch) -> None:
    start = datetime(2026, 11, 4, 8, 0, tzinfo=_TZ)
    state = sl.LedgerState(
        savings_v=sl.SAVINGS_V,
        chain_start=start,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=20.0,
        day_start=datetime(2026, 11, 4, 7, 9, tzinfo=_TZ),
        day_end=datetime(2026, 11, 5, 7, 10, tzinfo=_TZ),
        last_slot_start=start,
        soc_actual_end=25.0,
        prev_correction_eur=0.0,
        slots=(
            {
                "slot_start": start.isoformat(),
                "counted": True,
                "skip_reason": None,
                "cost_with_eur": 0.1,
                "cost_without_eur": 0.3,
                "import_kwh_with": 0.2,
                "import_kwh_without": 0.6,
                "export_kwh_with": 0.0,
                "export_kwh_without": 0.0,
                "k_act_cent": 40.0,
                "shadow_soc_end": 20.0,
            },
        ),
    )
    store.save_state(state, str(tmp_path / "savings_ledger_state.json"))
    monkeypatch.setattr(
        "config.get_battery_params_list",
        lambda: [{"battery_capacity_kwh": 15.0, "efficiency": 0.94}],
    )



def test_with_ledger_state_the_chart_draws_the_booked_lines(tmp_path, monkeypatch):
    _with_ledger(tmp_path, monkeypatch)
    at = _run(tmp_path, monkeypatch)

    assert "Mit Earnie (gebucht)" in _chart_spec(at)
    assert not any("Ersparnis-Buch" in text for text in _captions(at))
    assert "Bisher: 0,20 € gespart" in _labels(at)
    assert "Erwartet: 0,04 € gespart" in _labels(at)


def test_anchor_switch_defaults_to_now_and_keeps_the_choice(tmp_path, monkeypatch):
    _with_ledger(tmp_path, monkeypatch)
    at = _run(tmp_path, monkeypatch)
    assert at.session_state[SESSION_ANCHOR_MODE] == ANCHOR_NOW

    at.radio(key=SESSION_ANCHOR_MODE).set_value(ANCHOR_START).run()
    assert not at.exception
    assert "Gesamt: 0,24 € gespart" in _labels(at)

    at.run()
    assert at.session_state[SESSION_ANCHOR_MODE] == ANCHOR_START
    assert "Gesamt: 0,24 € gespart" in _labels(at)
