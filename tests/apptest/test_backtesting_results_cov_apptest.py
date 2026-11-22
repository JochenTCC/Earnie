"""Szenario-Explorer result view with a real (small) SE log: results, calendar, detail, charts.

The log comes from a real two-day ``run_simulation`` of the fixture scenario ``live``
(fixed_24h, 2026-06-24..25, ~6 s, once per worker) written with ``save_backtesting_log``
into the isolated runtime dir; the critical cases are set by the test. No full SE run,
no subprocess (the window diagnosis subprocess is faked).
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

_SCRIPTS = Path(__file__).parent / "scripts"
_PAGE = _SCRIPTS / "run_page_backtesting.py"
_PROGRESS = _SCRIPTS / "run_cov_backtesting_progress.py"
_CALENDAR = _SCRIPTS / "run_cov_backtesting_calendar.py"
_TIMEOUT = 60

_START = "2026-06-24"
_END = "2026-06-25"
_SIM_CACHE: dict[str, tuple[pd.DataFrame, object]] = {}


def _simulated_live() -> tuple[pd.DataFrame, object]:
    if "live" not in _SIM_CACHE:
        import config
        from simulation.engine import HistoricalDataCache, run_simulation
        from tests.fixtures.backtesting_fixtures import build_synthetic_prices_df

        start, end = pd.Timestamp(_START), pd.Timestamp(_END)
        params = dict(config.get_backtesting_scenarios()["live"])
        frame, report, _events = run_simulation(
            start,
            end,
            params,
            build_synthetic_prices_df(start, end),
            cache=HistoricalDataCache(),
            scenario_id="live",
            horizon_mode="fixed_24h",
        )
        _SIM_CACHE["live"] = (frame, report)
    return _SIM_CACHE["live"]


def _anchor_iso(day: date) -> str:
    from simulation.engine import window_anchor_for_date

    return window_anchor_for_date(day).isoformat()


def _default_cases() -> list[dict]:
    first = _anchor_iso(date(2026, 6, 24))
    second = _anchor_iso(date(2026, 6, 25))
    return [
        {
            "kind": "consumption_tolerance",
            "scenario_id": "live",
            "window_anchor": first,
            "historical_kwh": 3.087,
            "optimized_kwh": 3.5,
            "diff_kwh": 0.413,
        },
        {
            # Reference rows are never listed.
            "kind": "consumption_tolerance",
            "scenario_id": "historical_reference",
            "window_anchor": first,
            "historical_kwh": 3.0,
            "optimized_kwh": 9.0,
            "diff_kwh": 6.0,
        },
        {
            "kind": "strict_slow",
            "scenario_id": "live",
            "window_anchor": second,
            "slot_datetime": "2026-06-25T13:00:00",
            "simulation_hour_index": 5,
            "strict_elapsed_sec": 4.5,
            "strict_limit_sec": 3.0,
            "gap_rel": 0.0123,
            "strict_status": "TimeLimit",
            "window_consumption_ok": True,
            "consumer_targets_kwh": {"wp": 1.5},
            "window_consumption_diff_kwh": 0.2,
            "historical_kwh": 4.0,
        },
        {
            # Window outside the calendar (beyond the period).
            "kind": "milp_no_optimal",
            "scenario_id": "live",
            "window_anchor": "2026-07-10T00:00:00",
        },
    ]


def _write_log(
    *,
    cases: list[dict] | None = None,
    extra_meta: dict | None = None,
    drop_window_anchors: bool = False,
    stale: bool = False,
) -> dict:
    """Real SE log (JSON + CSV) of the two simulated days in the isolated runtime dir."""
    from scripts.run_backtesting import calendar_window_anchors
    from simulation.backtesting_fingerprint import fingerprint_for_current_config
    from simulation.backtesting_log import save_backtesting_log
    from simulation.engine import HISTORICAL_REFERENCE_ID

    frame, report = _simulated_live()
    runtime_dir = os.environ["EARNIE_RUNTIME_PATH"]
    period = {
        "start": _START,
        "end": _END,
        "windows": 2,
        "window_anchors": calendar_window_anchors(
            pd.Timestamp(_START), pd.Timestamp(_END), "fixed_24h"
        ),
        "horizon_mode": "fixed_24h",
        "start_month": 6,
        "end_month": 6,
        "backtesting_year": 2026,
        "references": ["historical"],
        "live_scenario_id": "live",
    }
    if drop_window_anchors:
        del period["window_anchors"]
    save_backtesting_log(
        {HISTORICAL_REFERENCE_ID: frame.copy(), "live": frame.copy()},
        {HISTORICAL_REFERENCE_ID: "Historisch", "live": "Live"},
        {"live": report},
        period,
        log_dir=runtime_dir,
        booked_consumption={},
    )
    json_path = Path(runtime_dir) / "backtesting_log.json"
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    meta["critical_cases"] = _default_cases() if cases is None else cases
    meta.update(extra_meta or {})
    meta["config_fingerprint"] = (
        "stale" if stale else fingerprint_for_current_config(period=meta["period"])
    )
    json_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def _page() -> AppTest:
    return AppTest.from_file(str(_PAGE), default_timeout=_TIMEOUT)


def _texts(elements) -> list[str]:
    return [str(element.value) for element in elements]


def _synthetic_window_prices(monkeypatch) -> None:
    """The fixture prices.csv has no AT column (``live`` plans in zone AT): synthetic prices."""
    from simulation import backtesting_single_window as sw
    from tests.fixtures.backtesting_fixtures import build_synthetic_prices_df

    def _prices(anchor, *, market_zone=None):
        day = pd.Timestamp(anchor).normalize()
        return build_synthetic_prices_df(day - pd.Timedelta(days=3), day + pd.Timedelta(days=1))

    monkeypatch.setattr(sw, "_load_prices_for_anchor", _prices)


def _detail_charts(at: AppTest) -> AppTest:
    at.radio(key="backtesting_deviation_detail_mode").set_value("charts")
    return at.run()


# --- results block -------------------------------------------------------------------


def test_results_block_shows_log_caption_notices_tables_and_monthly_chart():
    _write_log(
        extra_meta={
            "imported_pv_scenario_ids": ["live"],
            "imported_pv_missing_scenario_ids": ["entity_test"],
            "heating_hints_by_scenario": {"live": ["Heizstab doppelt gezählt?"]},
        }
    )
    at = _page().run()
    assert not at.exception
    subheaders = _texts(at.subheader)
    for expected in (
        "Szenario-Explorer-Log",
        "Gesamtkosten und -Verbrauch",
        "Monatlicher Kostenvergleich",
        "Detaillierte Simulationsansicht",
    ):
        assert expected in subheaders
    captions = " | ".join(_texts(at.caption))
    assert "Zeitraum: 2026-06-24 – 2026-06-25 (2 Fenster)" in captions
    assert "Horizont: 24h (E-Auto-Anker)" in captions
    assert "backtesting_log.json" in captions
    warnings = _texts(at.warning)
    assert "Testlauf — nur Monat 06/2026" in warnings
    # meta["labels"] wins over the config labels: ids without a log label stay ids.
    assert any(
        text.startswith("Szenarien wollten importiertes PV") and text.endswith(": entity_test.")
        for text in warnings
    )
    infos = _texts(at.info)
    assert any("importiertes PV-Profil" in text and "Live" in text for text in infos)
    assert "Live: Heizstab doppelt gezählt?" in infos
    # A log that matches the configuration: no stale warning, results not hidden.
    assert not any("passt nicht zur aktuellen Konfiguration" in text for text in warnings)
    assert at.get("plotly_chart"), "monthly cost chart missing"
    # The horizon box follows the stored log.
    assert at.session_state["backtesting_horizon_mode"] == "fixed_24h"
    assert at.session_state["_backtesting_log_anchor"]


def test_scenario_consumption_table_lists_the_optimized_scenario():
    _write_log()
    at = _page().run()
    frames = [df.value for df in at.dataframe]
    consumption = [
        frame for frame in frames if "Optimiert (kWh)" in getattr(frame, "columns", [])
    ]
    assert consumption, "consumption table missing"
    assert any("Live" in " ".join(map(str, row)) for row in consumption[0].values.tolist())
    assert any(
        "Soll Fenster = Summe der Fenster-Sollwerte" in text for text in _texts(at.caption)
    )


def test_monthly_chart_without_monthly_values_shows_info():
    _write_log(extra_meta={"summary": {"total_eur": {"live": 1.0}, "monthly_eur": {}}})
    at = _page().run()
    assert not at.exception
    assert "Keine Monatswerte im Log." in _texts(at.info)


# --- deviation list: summary, calendar, overview ------------------------------------


def test_deviation_summary_counts_cases_and_windows_outside_the_calendar():
    _write_log()
    at = _page().run()
    captions = _texts(at.caption)
    assert any(
        text.startswith("3 Abweichungen in 3 Fenstern; 1 davon in Fenstern, die der Kalender nicht zeigt")
        for text in captions
    ), captions
    # Stored window anchors: no "older run" notice.
    assert not any("Älterer Lauf ohne gespeicherte Fensteranker" in text for text in captions)


def test_overview_defaults_to_first_deviation_day_and_shows_header():
    _write_log()
    at = _page().run()
    # Default: first in-run day with a deviation, button drawn as selected only after a click.
    scenario_radio = at.radio(key="backtesting_cal_scenario_2026-06-24")
    assert scenario_radio.value == "live"
    assert scenario_radio.options == ["🟡 Live"]
    markdown = " | ".join(_texts(at.markdown))
    assert "**Szenario:** Live" in markdown
    assert "**Art:** Verbrauchstoleranz" in markdown
    assert "**Δ kWh (Soll/Ist):** +0,41 (+13,4%)" in markdown
    assert any(
        text.startswith("Soll/Ist-Summen (24h): historisch 3,1 kWh · optimiert 3,5 kWh")
        for text in _texts(at.caption)
    )
    assert any("Charts & Diagnose laden" in text for text in _texts(at.info))
    # Calendar: June shown, other months without run days locked.
    assert at.button(key="backtesting_calendar_month_6").disabled  # selected month
    assert at.button(key="backtesting_calendar_month_1").disabled  # no run days
    assert at.button(key="cal_day_2026-06-24").label == "🟡24"
    assert at.button(key="cal_day_2026-06-25").label == "⚪25"
    assert at.button(key="cal_off_2026-06-01").disabled
    assert any("**2026**" == text for text in _texts(at.markdown))


def test_click_on_calendar_day_selects_cbc_case_with_facts_caption():
    _write_log()
    at = _page().run()
    at.button(key="cal_day_2026-06-25").click().run()
    assert not at.exception
    assert at.session_state["backtesting_calendar_date"] == date(2026, 6, 25)
    assert at.button(key="cal_day_2026-06-25").proto.type == "primary"
    markdown = " | ".join(_texts(at.markdown))
    assert "**Art:** CBC strict (langsam)" in markdown
    assert "**Δ kWh (Soll/Ist):** +0,20 (+5,0%)" in markdown
    facts = [text for text in _texts(at.caption) if text.startswith("Slot:")]
    assert facts == [
        "Slot: 2026-06-25 13:00 · Simulationsstunde: 5 · Strict-Laufzeit: 4,50 s · "
        "Strict-Limit: 3,00 s · Gap: 0,0123 · Status: TimeLimit · "
        "24h-Gesamtverbrauch: innerhalb Toleranz · Verbraucherziele: wp=1,500 kWh"
    ]


def test_day_without_deviation_shows_keine_abweichung():
    _write_log(cases=[])
    at = _page().run()
    assert not at.exception
    assert any(
        "Keine auffälligen Abweichungen" in text for text in _texts(at.caption)
    )
    markdown = " | ".join(_texts(at.markdown))
    assert "**Szenario:** Live · **Keine Abweichung**" in markdown
    # Without deviations the first in-run day is the default.
    assert at.radio(key="backtesting_cal_scenario_2026-06-24").options == ["Live"]


def test_older_log_without_window_anchors_uses_hourly_series_and_notice():
    _write_log(drop_window_anchors=True)
    at = _page().run()
    assert not at.exception
    assert any(
        "Älterer Lauf ohne gespeicherte Fensteranker" in text for text in _texts(at.caption)
    )
    # Days still come from the hourly series of the run.
    assert at.button(key="cal_day_2026-06-24").label == "🟡24"
    assert at.session_state["backtesting_deviation_run_anchors"]["anchors"]


# --- detail charts and window diagnosis ---------------------------------------------


class _FakeProc:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_subprocess(monkeypatch, *, returncode=0, raise_timeout=False) -> list:
    from ui import backtesting_diag_single_window as diag

    calls: list = []

    class _Fake:
        TimeoutExpired = subprocess.TimeoutExpired

        @staticmethod
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if raise_timeout:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return _FakeProc(returncode, "diag out", "diag err")

    monkeypatch.setattr(diag, "subprocess", _Fake)
    return calls


def test_charts_mode_simulates_window_on_demand_and_draws_both_charts(monkeypatch):
    _synthetic_window_prices(monkeypatch)
    _write_log()
    at = _page().run()
    charts_before = len(at.get("plotly_chart"))
    at = _detail_charts(at)
    assert not at.exception
    assert not at.error, _texts(at.error)
    # Chart 1 (power/SoC) and chart 2 (price/savings) for the window.
    assert len(at.get("plotly_chart")) == charts_before + 2
    # The on-demand window is saved into the log's snapshot file.
    snapshots = Path(os.environ["EARNIE_RUNTIME_PATH"]) / "backtesting_window_snapshots.jsonl"
    lines = [json.loads(line) for line in snapshots.read_text(encoding="utf-8").splitlines()]
    assert [(s["window_anchor"], s["scenario_id"]) for s in lines] == [
        (_anchor_iso(date(2026, 6, 24)), "live")
    ]
    # Session caches hold the window and the display bundle.
    assert at.session_state["backtesting_on_demand_snapshots"]
    assert at.session_state["backtesting_display_bundle_cache"]
    # Fixed 24h log: no SA segment radio.
    assert not [r for r in at.radio if r.key == "backtesting_deviation_sa_segment"]
    # Window diagnosis: CLI command with the start SoC of the series.
    codes = [c.value for c in at.code if c.language == "powershell"]
    assert len(codes) == 1
    assert "--scenario live" in codes[0]
    assert "--initial-soc" in codes[0]
    assert "--start-month 6 --end-month 6" in codes[0]


@pytest.mark.parametrize(
    ("returncode", "raise_timeout", "expect_success", "expect_error"),
    [
        (0, False, "Diagnose abgeschlossen.", None),
        (2, False, None, "Diagnose beendet mit Exit-Code 2."),
        (0, True, None, "Diagnose nach 180 s abgebrochen (Zeitlimit)."),
    ],
    ids=["ok", "exit_code", "timeout"],
)
def test_window_diagnosis_button_runs_subprocess_and_reports(
    monkeypatch, returncode, raise_timeout, expect_success, expect_error
):
    calls = _fake_subprocess(monkeypatch, returncode=returncode, raise_timeout=raise_timeout)
    _synthetic_window_prices(monkeypatch)
    _write_log()
    at = _detail_charts(_page().run())
    button_key = f"diag_single_window_{_anchor_iso(date(2026, 6, 24))}_live"
    at.button(key=button_key).click().run()
    assert not at.exception
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert "--anchor" in argv and kwargs["timeout"] == 180 and kwargs["capture_output"]
    if expect_success:
        assert expect_success in _texts(at.success)
        assert "diag outdiag err" in _texts(at.text)
    else:
        assert expect_error in _texts(at.error)


def test_charts_mode_on_stale_log_refuses_on_demand_window():
    _write_log(stale=True)
    at = _detail_charts(_page().run())
    assert not at.exception
    assert any(
        "Für dieses Fenster liegt im Log kein gespeicherter Plan vor" in text
        for text in _texts(at.error)
    )
    assert not (Path(os.environ["EARNIE_RUNTIME_PATH"]) / "backtesting_window_snapshots.jsonl").exists()


def test_charts_mode_without_bundle_shows_info(monkeypatch):
    from ui import backtesting_deviation_list as dl

    monkeypatch.setattr(dl, "resolve_backtesting_display_bundle", lambda *a, **k: None)
    _write_log()
    at = _detail_charts(_page().run())
    assert not at.exception
    assert "Chart-Daten für dieses Fenster konnten nicht geladen werden." in _texts(at.info)


def test_diag_panel_without_soc_for_window_shows_error(monkeypatch):
    from simulation import backtesting_single_window as sw

    def _no_soc(*_a, **_k):
        raise ValueError("ohne SoC")

    monkeypatch.setattr(sw, "initial_soc_for_anchor", _no_soc)
    monkeypatch.setattr(
        "ui.backtesting_deviation_list.resolve_backtesting_display_bundle",
        lambda *a, **k: None,
    )
    _write_log()
    at = _detail_charts(_page().run())
    assert "Fenster-Diagnose nicht verfügbar: ohne SoC" in _texts(at.error)


# --- deviation list edge cases (from_function) ---------------------------------------


def _deviation_list_app():
    import pandas as pd
    import streamlit as st

    import ui.backtesting  # noqa: F401
    from ui.backtesting_deviation_list import render_deviation_list

    hourly = st.session_state.get("_hourly")
    render_deviation_list(
        st.session_state["_meta"],
        {"live": "Live"},
        log_dir=st.session_state["_log_dir"],
        hourly_df=hourly if hourly is not None else pd.DataFrame(),
    )


def test_deviation_list_without_run_windows_shows_info(tmp_path):
    at = AppTest.from_function(_deviation_list_app, default_timeout=_TIMEOUT)
    at.session_state["_meta"] = {"scenario_ids": ["live"]}
    at.session_state["_log_dir"] = str(tmp_path)
    at.run()
    assert not at.exception
    assert "Keine Simulationsfenster im Backtesting-Zeitraum." in _texts(at.info)


def test_deviation_list_without_optimized_scenario_shows_info(tmp_path):
    anchor = _anchor_iso(date(2026, 6, 24))
    hourly = pd.DataFrame(
        {
            "ts": pd.date_range("2026-06-24", periods=24, freq="h"),
            "scenario_id": ["live"] * 24,
        }
    )
    at = AppTest.from_function(_deviation_list_app, default_timeout=_TIMEOUT)
    at.session_state["_meta"] = {
        "scenario_ids": ["historical_reference", "ref:live"],
        "period": {
            "start": _START,
            "end": _START,
            "backtesting_year": 2026,
            "window_anchors": {_START: anchor},
        },
    }
    at.session_state["_hourly"] = hourly
    at.session_state["_log_dir"] = str(tmp_path)
    at.run()
    assert not at.exception
    assert "Kein optimiertes Szenario für den gewählten Tag." in _texts(at.info)


# --- run progress, cancel, season mirror ---------------------------------------------


def test_progress_callback_draws_captions_and_bars():
    at = AppTest.from_file(str(_PROGRESS), default_timeout=_TIMEOUT)
    at.session_state["_fake_progress_cfg"] = {
        "running": True,
        "workers": 2,
        "snapshot": {"live": {"current": 12, "total": 48, "phase": "Optimierung", "scenario": "Live"}},
    }
    at.run()
    assert not at.exception
    captions = _texts(at.caption)
    assert "Parallele Berechnung: 2 Worker · 3 aktive Tasks" in captions
    assert any(text.startswith("Live") and "12" in text and "48" in text for text in captions)
    bars = [element.proto.value for element in at.get("progress")]
    # Historisch and the reference wait (0 %), Live is at 12/48.
    assert bars == [0, 25, 0]


def test_progress_with_single_worker_has_no_parallel_caption():
    at = AppTest.from_file(str(_PROGRESS), default_timeout=_TIMEOUT)
    at.session_state["_fake_progress_cfg"] = {
        "running": True,
        "workers": 1,
        "snapshot": {"live": {"current": 48, "total": 48, "phase": "", "scenario": "Live"}},
    }
    at.run()
    assert not any("Parallele Berechnung" in text for text in _texts(at.caption))
    assert [element.proto.value for element in at.get("progress")] == [0, 100, 0]


def test_cancel_button_cancels_the_active_run():
    at = AppTest.from_file(str(_PROGRESS), default_timeout=_TIMEOUT)
    at.session_state["_fake_progress_cfg"] = {"running": True}
    at.run()
    at.button(key="backtesting_cancel_btn").click().run()
    assert not at.exception
    assert at.session_state["_fake_cancel_calls"] == ["cancel"]
    assert at.button(key="backtesting_cancel_btn").disabled
    assert any("Abbruch angefordert" in text for text in _texts(at.caption))


def test_finished_run_stores_its_calendar_month():
    at = AppTest.from_file(str(_PROGRESS), default_timeout=_TIMEOUT)
    at.session_state["_fake_progress_cfg"] = {"running": False, "exit_code": 0}
    at.session_state["backtesting_calendar_date"] = date(2026, 1, 1)
    at.run()
    assert not at.exception
    assert at.session_state["backtesting_calendar_month"] == 6
    assert "backtesting_calendar_date" not in at.session_state
    assert "_backtesting_active_run" not in at.session_state


def test_season_mirror_checkbox_writes_config():
    config_path = Path(os.environ["EARNIE_CONFIG_PATH"])
    at = _page().run()
    box = at.checkbox(key="backtesting_season_mirror_to_last_month")
    assert box.value is False
    box.check().run()
    assert not at.exception
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["scenario_explorer_conf"]["season_mirror_to_last_month"] is True
    assert any("Season-Mirror aktiv" in text for text in _texts(at.caption))
    at.checkbox(key="backtesting_season_mirror_to_last_month").uncheck().run()
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["scenario_explorer_conf"]["season_mirror_to_last_month"] is False


# --- calendar (standalone script) -----------------------------------------------------


def _rolling_calendar(**session) -> AppTest:
    """Rolling period Okt 2025 – Sep 2026 with run days in Nov 2025 and Jun 2026."""
    days = [date(2025, 11, 3), date(2025, 11, 4), date(2026, 6, 10)]
    at = AppTest.from_file(str(_CALENDAR), default_timeout=_TIMEOUT)
    at.session_state["_cal_meta"] = {
        "period": {"start": "2025-10-01", "end": "2026-09-30", "backtesting_year": 2025}
    }
    at.session_state["_cal_anchors"] = [_anchor_iso(day) for day in days]
    at.session_state["_cal_cases"] = [
        {
            "kind": "milp_no_optimal",
            "scenario_id": "live",
            "window_anchor": _anchor_iso(date(2026, 6, 10)),
        }
    ]
    for key, value in session.items():
        at.session_state[key] = value
    return at.run()


def test_calendar_rolling_period_shows_both_years_and_deviation_month():
    at = _rolling_calendar()
    assert not at.exception
    assert "**2025–2026**" in _texts(at.markdown)
    # The month with the most deviation days opens first.
    assert at.session_state["backtesting_calendar_month"] == 6
    assert at.button(key="cal_day_2026-06-10").label == "🔴10"
    assert not at.button(key="backtesting_calendar_month_11").disabled
    assert at.button(key="backtesting_calendar_month_1").disabled
    assert at.session_state["_cal_returned"] is None


def test_calendar_month_button_switches_visible_month():
    at = _rolling_calendar()
    at.button(key="backtesting_calendar_month_11").click().run()
    assert not at.exception
    assert at.session_state["backtesting_calendar_month"] == 11
    assert at.button(key="cal_day_2025-11-03").label == "🟢3"
    assert at.button(key="cal_off_2025-11-05").disabled


def test_calendar_restores_stored_date_given_as_iso_string():
    at = _rolling_calendar(backtesting_calendar_date="2025-11-04")
    assert at.session_state["_cal_returned"] == date(2025, 11, 4)
    assert at.session_state["backtesting_calendar_month"] == 11
    assert at.button(key="cal_day_2025-11-04").proto.type == "primary"


@pytest.mark.parametrize("stored", ["kein-datum", "2025-11-20"], ids=["garbage", "not_in_run"])
def test_calendar_drops_unusable_stored_date(stored):
    at = _rolling_calendar(backtesting_calendar_date=stored)
    assert not at.exception
    assert at.session_state["_cal_returned"] is None
    if stored == "2025-11-20":
        assert "backtesting_calendar_date" not in at.session_state


def test_sa_segment_toggle_only_for_sunrise_logs(tmp_path):
    at = _rolling_calendar(
        _toggle_meta={"period": {"horizon_mode": "sunrise_window"}},
        _toggle_log_dir=str(tmp_path),
    )
    assert not at.exception
    radio = at.radio(key="backtesting_deviation_sa_segment")
    # No stored snapshot for the window: the booked segment SA₁→SA₂ is preselected.
    assert radio.value == "SA₁→SA₂"
    assert at.session_state["_toggle_returned"] == "SA₁→SA₂"
    radio.set_value("SA₀→SA₁").run()
    assert at.session_state["_toggle_returned"] == "SA₀→SA₁"

    fixed = _rolling_calendar(
        _toggle_meta={"period": {"horizon_mode": "fixed_24h"}},
        _toggle_log_dir=str(tmp_path),
    )
    assert fixed.session_state["_toggle_returned"] == "SA₀→SA₁"
    assert not [r for r in fixed.radio if r.key == "backtesting_deviation_sa_segment"]
