"""Ledger P8: Monitor tile figures and the wording of savings without a sign."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from ui import ledger_kpi as kpi_mod
from ui.chart_ledger_savings import build_ledger_chart_savings
from ui.chart_decorations import _savings_annotation_color
from ui.chart_colors import COLOR_COST_BASELINE
from ui.ledger_kpi import LedgerKpi, LedgerKpiNotice, build_ledger_kpi, load_ledger_kpi, tile_help, today_text
from ui.saving_text import euro_amount, saving_is_loss, saving_text, soc_correction_text

_TZ = ZoneInfo("Europe/Vienna")
CHAIN = datetime(2026, 9, 16, 15, 45, tzinfo=_TZ)
DAY_START = datetime(2026, 11, 4, 7, 9, tzinfo=_TZ)
DAY_END = datetime(2026, 11, 5, 7, 10, tzinfo=_TZ)
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=_TZ)
BATTERY = {"battery_capacity_kwh": 15.0, "efficiency": 0.94}


def _slot(start: datetime, *, with_eur: float, without_eur: float, counted: bool = True) -> dict:
    return {
        "slot_start": start.isoformat(),
        "counted": counted,
        "skip_reason": None if counted else sl.SKIP_NOT_MEAN,
        "cost_with_eur": with_eur,
        "cost_without_eur": without_eur,
        "import_kwh_with": 0.2 if counted else 0.0,
        "import_kwh_without": 0.6 if counted else 0.0,
        "export_kwh_with": 0.0,
        "export_kwh_without": 0.0,
        "k_act_cent": 40.0,
        "shadow_soc_end": 20.0,
        "house_kwh": 0.2 if counted else 0.0,
    }


def _state(*slots: dict, prev_correction: float = 0.0, soc_actual: float | None = 25.0) -> sl.LedgerState:
    return sl.LedgerState(
        savings_v=sl.SAVINGS_V,
        chain_start=CHAIN,
        chain_start_reason=sl.CHAIN_BACKFILL,
        shadow_soc=20.0,
        day_start=DAY_START,
        day_end=DAY_END,
        last_slot_start=datetime.fromisoformat(slots[-1]["slot_start"]) if slots else None,
        soc_actual_end=soc_actual,
        prev_correction_eur=prev_correction,
        slots=tuple(slots),
    )


def _row(saving: float, *, incomplete: bool = False, slots_present: int = 90, chain: datetime = CHAIN) -> dict:
    return {
        "savings_v": sl.SAVINGS_V,
        "chain_start": chain.isoformat(),
        "saving_adjusted_eur": saving,
        "incomplete": incomplete,
        "slots_present": slots_present,
        "day_start": "2026-11-01T07:04:38+01:00",
        "day_end": "2026-11-02T07:06:08+01:00",
    }


@pytest.mark.parametrize(
    ("euro", "text"),
    [
        (0.42, "0.42 € gespart"),
        (-2.18, "2.18 € mehr ausgegeben"),
        (0.0, "0.00 € gespart"),
        (-0.004, "0.00 € gespart"),
        (-0.006, "0.01 € mehr ausgegeben"),
    ],
)
def test_saving_text_has_no_sign_and_names_the_meaning(euro, text):
    assert saving_text(euro) == text


def test_soc_correction_text_names_the_direction():
    assert soc_correction_text(0.78) == "0.78 € gutgeschrieben"
    assert soc_correction_text(-0.1) == "0.10 € abgezogen"


def test_colour_follows_the_shown_cents():
    assert _savings_annotation_color(-0.004) == COLOR_COST_BASELINE
    assert saving_is_loss(-0.004) is False
    assert euro_amount(-0.004) == "0.00 €"


def test_total_counts_closed_days_of_the_current_chain_only():
    other_chain = CHAIN - timedelta(days=30)
    rows = [_row(1.0), _row(0.5, incomplete=True), _row(99.0, chain=other_chain)]

    kpi = build_ledger_kpi(_state(), BATTERY, rows, now=NOW)

    assert kpi.total_euro == pytest.approx(1.5)
    assert kpi.days == 2
    assert kpi.incomplete_days == 1
    assert kpi.chain_start == CHAIN


def test_running_day_stays_out_of_the_total():
    state = _state(_slot(DAY_START + timedelta(minutes=6), with_eur=0.1, without_eur=0.3))

    kpi = build_ledger_kpi(state, BATTERY, [_row(1.0)], now=NOW)

    assert kpi.total_euro == pytest.approx(1.0)
    assert kpi.today_saving_euro == pytest.approx(0.2)


def test_tile_and_chart2_agree_on_the_current_sa_day():
    start = DAY_START + timedelta(minutes=6)
    state = _state(
        _slot(start, with_eur=0.1, without_eur=0.3),
        _slot(start + timedelta(minutes=15), with_eur=0.3, without_eur=0.05),
        prev_correction=0.4,
    )
    slots = [start, start + timedelta(minutes=15)]

    kpi = build_ledger_kpi(state, BATTERY, [_row(1.0)], now=NOW)
    chart = build_ledger_chart_savings(
        slots, 2, state, BATTERY, [], window_start=DAY_START, window_end=DAY_END
    )

    assert kpi.today_saving_euro == chart["saving_euro"]
    assert kpi.today_correction_euro == chart["soc_correction_euro"]
    assert kpi.today_saving_euro == pytest.approx(chart["cumulative_euro"][-1])


def test_no_today_figures_without_booked_slots_or_after_the_day_ended():
    slot = _slot(DAY_START + timedelta(minutes=6), with_eur=0.1, without_eur=0.3)

    without_slots = build_ledger_kpi(_state(), BATTERY, [_row(1.0)], now=NOW)
    after_the_day = build_ledger_kpi(_state(slot), BATTERY, [_row(1.0)], now=DAY_END)

    assert without_slots.today_saving_euro is None
    assert today_text(without_slots) is None
    assert after_the_day.today_saving_euro is None


def test_today_text_uses_the_words_of_chart2():
    kpi = LedgerKpi(CHAIN, 1, 0, 1.0, -0.97, 0.78)

    assert today_text(kpi) == "Heute bisher: 0.97 € mehr ausgegeben · SoC-Korrektur: 0.78 € gutgeschrieben"


def test_no_result_when_no_slot_was_ever_counted():
    rows = [_row(0.0, slots_present=0, incomplete=True)]

    assert build_ledger_kpi(_state(), BATTERY, rows, now=NOW).total_euro is None


def test_help_states_the_counterfactual_limits_and_incomplete_days():
    text = tile_help(LedgerKpi(CHAIN, 45, 3, 1.0, None, None))

    for part in ("gleicher Verbrauch", "gleiche PV", "Herstellermodus", "gleiche Preise",
                 "Powerstations", "Wirkungsgrad", "Unvollständige Tage: 3"):
        assert part in text
    assert "Unvollständige Tage: keine" in tile_help(LedgerKpi(CHAIN, 45, 0, 1.0, None, None))


def test_load_names_a_missing_battery(monkeypatch):
    monkeypatch.setattr("config.get_battery_params_list", lambda: [])

    assert load_ledger_kpi(NOW) == LedgerKpiNotice(kpi_mod.NOTICE_NO_BATTERY)


def test_load_names_a_ledger_that_is_not_running(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [BATTERY])

    assert load_ledger_kpi(NOW) == LedgerKpiNotice(kpi_mod.NOTICE_NOT_RUNNING)


def test_load_warns_about_an_unreadable_state_and_leaves_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [BATTERY])
    path = tmp_path / "savings_ledger_state.json"
    path.write_text("{broken", encoding="utf-8")

    assert load_ledger_kpi(NOW) == LedgerKpiNotice(kpi_mod.NOTICE_UNREADABLE, is_warning=True)
    assert path.exists()


def test_load_warns_about_a_broken_ledger_file(tmp_path, monkeypatch):
    from runtime_store import savings_ledger_store as store

    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [BATTERY])
    store.save_state(_state(), str(tmp_path / "savings_ledger_state.json"))
    (tmp_path / "savings_ledger.jsonl").write_text("not json\n", encoding="utf-8")

    assert load_ledger_kpi(NOW) == LedgerKpiNotice(kpi_mod.NOTICE_UNREADABLE, is_warning=True)
