"""AppTest: account view on the analysis page (Account view P3)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui.chart_account_render import SESSION_ANCHOR_MODE, SESSION_PERIOD_PREFIX
from ui.chart_account_view import ANCHOR_NOW, ANCHOR_START

_SCRIPT = Path(__file__).parent / "scripts" / "run_period_account.py"
_TZ = ZoneInfo("Europe/Vienna")
_KEY = f"{SESSION_PERIOD_PREFIX}{SESSION_ANCHOR_MODE}"


def _slot(minute: int, with_eur: float, without_eur: float) -> dict:
    return {
        "slot_start": datetime(2026, 11, 4, 8, minute, tzinfo=_TZ).isoformat(),
        "counted": True,
        "skip_reason": None,
        "cost_with_eur": with_eur,
        "cost_without_eur": without_eur,
        "import_kwh_with": 0.0,
        "import_kwh_without": 0.0,
        "export_kwh_with": 0.0,
        "export_kwh_without": 0.0,
        "k_act_cent": 40.0,
        "shadow_soc_end": 20.0,
    }


def _run(tmp_path, monkeypatch) -> AppTest:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    slots = (_slot(0, 0.1, 0.3), _slot(15, 0.2, 0.25))
    state = sl.LedgerState(
        savings_v=sl.SAVINGS_V,
        chain_start=datetime(2026, 11, 4, 7, 9, tzinfo=_TZ),
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=20.0,
        shadow_soc_day_start=20.0,
        day_start=datetime(2026, 11, 4, 7, 9, tzinfo=_TZ),
        day_end=datetime(2026, 11, 5, 7, 10, tzinfo=_TZ),
        last_slot_start=datetime.fromisoformat(slots[-1]["slot_start"]),
        soc_actual_end=20.0,
        prev_correction_eur=0.0,
        slots=slots,
    )
    store.save_state(state, str(tmp_path / "savings_ledger_state.json"))
    monkeypatch.setattr(
        "config.get_battery_params_list",
        lambda: [{"battery_capacity_kwh": 15.0, "efficiency": 0.94}],
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=10).run()
    assert not at.exception
    return at


def _labels(at: AppTest) -> list[str]:
    layout = json.loads(at.get("plotly_chart")[0].proto.spec)["layout"]
    return [item["text"] for item in layout.get("annotations", [])]


def test_period_shows_the_saving_of_the_window(tmp_path, monkeypatch):
    at = _run(tmp_path, monkeypatch)

    assert "Zeitraum: 0,25 € gespart" in _labels(at)
    assert "Ersparnis seit Fensterstart" in at.get("plotly_chart")[0].proto.spec


def test_period_switch_has_its_own_state(tmp_path, monkeypatch):
    at = _run(tmp_path, monkeypatch)
    assert at.session_state[_KEY] == ANCHOR_NOW
    assert SESSION_ANCHOR_MODE not in at.session_state

    at.radio(key=_KEY).set_value(ANCHOR_START).run()

    assert not at.exception
    assert at.session_state[_KEY] == ANCHOR_START
    assert "Zeitraum: 0,25 € gespart" in _labels(at)
