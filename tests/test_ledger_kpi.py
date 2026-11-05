"""Ledger P8: Monitor tile figures and the wording of savings without a sign."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from ui import ledger_kpi as kpi_mod
from ui.chart_ledger_savings import _no_ledger, build_ledger_chart_savings
from ui.chart_account_render import saving_color
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
        "saving_eur": saving,
        "saving_adjusted_eur": saving,
        "incomplete": incomplete,
        "slots_present": slots_present,
        "day_start": "2026-11-01T07:04:38+01:00",
        "day_end": "2026-11-02T07:06:08+01:00",
    }


@pytest.mark.parametrize(
    ("euro", "text"),
    [
        (0.42, "0,42 € gespart"),
        (-2.18, "2,18 € mehr ausgegeben"),
        (0.0, "0,00 € gespart"),
        (-0.004, "0,00 € gespart"),
        (-0.006, "0,01 € mehr ausgegeben"),
    ],
)
def test_saving_text_has_no_sign_and_names_the_meaning(euro, text):
    assert saving_text(euro) == text


def test_soc_correction_text_names_the_direction():
    assert soc_correction_text(0.78) == "0,78 € gutgeschrieben"
    assert soc_correction_text(-0.1) == "0,10 € abgezogen"


def test_colour_follows_the_shown_cents():
    assert saving_color(-0.004) == COLOR_COST_BASELINE
    assert saving_is_loss(-0.004) is False
    assert euro_amount(-0.004) == "0,00 €"


def test_total_counts_closed_days_of_the_current_chain_only():
    other_chain = CHAIN - timedelta(days=30)
    rows = [_row(1.0), _row(0.5, incomplete=True), _row(99.0, chain=other_chain)]

    kpi = build_ledger_kpi(_state(), rows)

    assert kpi.total_euro == pytest.approx(1.5)
    assert kpi.days == 2
    assert kpi.incomplete_days == 1
    assert kpi.chain_start == CHAIN


def _chart_ledger(state: sl.LedgerState, *, rows=(), window_start=DAY_START, window_end=DAY_END, slots=()):
    return build_ledger_chart_savings(
        list(slots), len(slots), state, BATTERY, list(rows),
        window_start=window_start, window_end=window_end,
    )


def _two_slot_state() -> sl.LedgerState:
    start = DAY_START + timedelta(minutes=6)
    return _state(
        _slot(start, with_eur=0.1, without_eur=0.3),
        _slot(start + timedelta(minutes=15), with_eur=0.3, without_eur=0.05),
        prev_correction=0.4,
    )


def test_running_day_stays_out_of_the_total():
    state = _state(_slot(DAY_START + timedelta(minutes=6), with_eur=0.1, without_eur=0.3))

    assert build_ledger_kpi(state, [_row(1.0)]).total_euro == pytest.approx(1.0)


def test_tile_and_chart2_read_the_same_figures_of_the_current_sa_day():
    """Same dict, same words: the today line and Chart 2 cannot show different amounts.

    Chart 2's "Bisher" over a window that starts at the open day is the sum of the
    ledger's slots; its SoC label reads the same ``soc_correction_euro``.
    """
    state = _two_slot_state()
    window_slots = [datetime.fromisoformat(slot["slot_start"]) for slot in state.slots]
    ledger = _chart_ledger(state, slots=window_slots)
    chart_saving = sum(
        without - with_ for with_, without in zip(ledger["slot_with_eur"], ledger["slot_without_eur"])
    )

    assert chart_saving == pytest.approx(ledger["saving_euro"])
    assert today_text(ledger, NOW) == (
        f"Heute bisher: {saving_text(chart_saving)} · "
        f"SoC-Korrektur: {soc_correction_text(ledger['soc_correction_euro'])}"
    )


def test_open_day_figures_do_not_depend_on_the_paged_window():
    """Paging Chart 2 back builds the dict for another window; the today line stays."""
    state = _two_slot_state()
    closed = {
        **_row(0.7),
        "day_start": (DAY_START - timedelta(days=1)).isoformat(),
        "day_end": DAY_START.isoformat(),
    }
    earlier_start = DAY_START - timedelta(days=1)
    today = _chart_ledger(state, rows=[closed], slots=[DAY_START + timedelta(minutes=6)])
    earlier = _chart_ledger(
        state,
        rows=[closed],
        window_start=earlier_start,
        window_end=DAY_START,
        slots=[earlier_start + timedelta(minutes=15)],
    )

    for key in ("open_day_start", "open_day_end", "saving_euro", "soc_correction_euro"):
        assert today[key] == earlier[key]
    assert today_text(earlier, NOW) == today_text(today, NOW)


def test_no_today_line_without_a_bundle_without_figures_or_outside_the_day():
    ledger = _chart_ledger(_state(_slot(DAY_START + timedelta(minutes=6), with_eur=0.1, without_eur=0.3)))

    assert today_text(None, NOW) is None
    assert today_text(_no_ledger(0, 0, "Hinweis"), NOW) is None
    assert today_text(_chart_ledger(_state()), NOW) is None
    assert today_text(ledger, DAY_END) is None
    assert today_text(ledger, DAY_START - timedelta(minutes=1)) is None


def test_chart2_invents_no_figures_before_the_first_booked_slot():
    ledger = _chart_ledger(_state())

    assert ledger["saving_euro"] is None
    assert ledger["soc_correction_euro"] is None
    assert ledger["open_day_start"] == DAY_START.isoformat()


def test_today_text_uses_the_words_of_chart2():
    ledger = {
        **_chart_ledger(_two_slot_state()),
        "saving_euro": -0.97,
        "soc_correction_euro": 0.78,
    }

    assert today_text(ledger, NOW) == (
        "Heute bisher: 0,97 € mehr ausgegeben · SoC-Korrektur: 0,78 € gutgeschrieben"
    )


def test_no_result_when_no_slot_was_ever_counted():
    rows = [_row(0.0, slots_present=0, incomplete=True)]

    assert build_ledger_kpi(_state(), rows).total_euro is None


def test_help_states_the_counterfactual_limits_and_incomplete_days():
    text = tile_help(LedgerKpi(CHAIN, 45, 3, 1.0))

    for part in ("gleicher Verbrauch", "gleiche PV", "Herstellermodus", "gleiche Preise",
                 "Powerstations", "Wirkungsgrad", "Unvollständige Tage: 3"):
        assert part in text
    assert "Unvollständige Tage: keine" in tile_help(LedgerKpi(CHAIN, 45, 0, 1.0))


def test_load_names_a_missing_battery(monkeypatch):
    monkeypatch.setattr("config.get_battery_params_list", lambda: [])

    assert load_ledger_kpi() == LedgerKpiNotice(kpi_mod.NOTICE_NO_BATTERY)


def test_load_names_a_ledger_that_is_not_running(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [BATTERY])

    assert load_ledger_kpi() == LedgerKpiNotice(kpi_mod.NOTICE_NOT_RUNNING)


def test_load_warns_about_an_unreadable_state_and_leaves_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [BATTERY])
    path = tmp_path / "savings_ledger_state.json"
    path.write_text("{broken", encoding="utf-8")

    assert load_ledger_kpi() == LedgerKpiNotice(kpi_mod.NOTICE_UNREADABLE, is_warning=True)
    assert path.exists()


def test_load_warns_about_a_broken_ledger_file(tmp_path, monkeypatch):
    from runtime_store import savings_ledger_store as store

    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [BATTERY])
    store.save_state(_state(), str(tmp_path / "savings_ledger_state.json"))
    (tmp_path / "savings_ledger.jsonl").write_text("not json\n", encoding="utf-8")

    assert load_ledger_kpi() == LedgerKpiNotice(kpi_mod.NOTICE_UNREADABLE, is_warning=True)
