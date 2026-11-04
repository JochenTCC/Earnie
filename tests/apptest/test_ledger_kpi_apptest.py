"""AppTest: Monitor tile "Mit Earnie gespart" in its states (Ledger P8)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui import ledger_kpi as kpi_mod

_SCRIPT = Path(__file__).parent / "scripts" / "run_ledger_kpi.py"
_TZ = ZoneInfo("Europe/Vienna")
_CHAIN = datetime(2026, 9, 16, 15, 45, tzinfo=_TZ)
_SLOT = datetime(2026, 11, 4, 8, 0, tzinfo=_TZ)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(
        "config.get_battery_params_list",
        lambda: [{"battery_capacity_kwh": 15.0, "efficiency": 0.94}],
    )
    return tmp_path


def _write_state(runtime: Path) -> None:
    state = sl.LedgerState(
        savings_v=sl.SAVINGS_V,
        chain_start=_CHAIN,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=20.0,
        day_start=datetime(2026, 11, 4, 7, 9, tzinfo=_TZ),
        day_end=datetime(2026, 11, 5, 7, 10, tzinfo=_TZ),
        last_slot_start=_SLOT,
        soc_actual_end=20.0,
        prev_correction_eur=0.0,
        slots=(
            {
                "slot_start": _SLOT.isoformat(),
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
                "house_kwh": 0.2,
            },
        ),
    )
    store.save_state(state, str(runtime / "savings_ledger_state.json"))


def _write_rows(runtime: Path, *savings: float, slots_present: int = 90, incomplete: bool = False) -> None:
    for saving in savings:
        store.append_row(
            {
                "savings_v": sl.SAVINGS_V,
                "chain_start": _CHAIN.isoformat(),
                "saving_adjusted_eur": saving,
                "slots_present": slots_present,
                "incomplete": incomplete,
            },
            str(runtime / "savings_ledger.jsonl"),
        )


def _run() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception
    return at


def _captions(at: AppTest) -> list[str]:
    return [item.value for item in at.caption]


def test_saved_total_with_date_days_and_today(runtime):
    _write_state(runtime)
    _write_rows(runtime, 10.0, 2.34)

    at = _run()

    assert at.metric[0].label == "Mit Earnie gespart"
    assert at.metric[0].value == "12.34 €"
    assert "gleiche PV" in at.metric[0].proto.help
    captions = _captions(at)
    assert "seit 16.09.2026 (2 Tage)" in captions
    assert "Heute bisher: 0.20 € gespart · SoC-Korrektur: 0.00 € gutgeschrieben" in captions


def test_negative_total_changes_the_words_and_drops_the_sign(runtime):
    _write_state(runtime)
    _write_rows(runtime, -2.18)

    at = _run()

    assert at.metric[0].label == "Mit Earnie mehr ausgegeben"
    assert at.metric[0].value == "2.18 €"
    assert "seit 16.09.2026 (1 Tag)" in _captions(at)


def test_incomplete_days_are_named_in_the_help(runtime):
    _write_state(runtime)
    _write_rows(runtime, 1.0, incomplete=True)

    assert "Unvollständige Tage: 1" in _run().metric[0].proto.help


def test_first_day_shows_no_figure_but_the_start_date(runtime):
    _write_state(runtime)

    at = _run()

    assert not at.metric
    assert any("Noch kein abgeschlossener Tag, Zählung seit 16.09.2026" in text for text in _captions(at))


def test_no_counted_slot_is_not_shown_as_zero(runtime):
    _write_state(runtime)
    _write_rows(runtime, 0.0, slots_present=0, incomplete=True)

    at = _run()

    assert not at.metric
    assert any("nicht auswertbar" in text for text in _captions(at))


def test_without_state_there_is_a_notice_and_no_figure(runtime):
    at = _run()

    assert not at.metric
    assert kpi_mod.NOTICE_NOT_RUNNING in _captions(at)


def test_unreadable_state_is_a_warning(runtime):
    (runtime / "savings_ledger_state.json").write_text("{broken", encoding="utf-8")

    at = _run()

    assert not at.metric
    assert [item.value for item in at.warning] == [kpi_mod.NOTICE_UNREADABLE]
