"""Monitor block "Leistungspreis" (P6b): shown, hidden, plan warning, unknown month, errors."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from optimizer.import_cap_report import (
    CAUSE_BATTERY_ENERGY,
    CAUSE_BATTERY_POWER,
    CAUSE_FORECAST,
    NOT_PLANNED_AUTOMATIK,
)
from tests.test_capacity_charge import _charge, _params
from tests.test_capacity_charge_panel import CAP, NOW, month_peak
from ui.capacity_charge_panel import build_capacity_panel


def _render(panel) -> None:
    from ui.capacity_charge_panel import render_capacity_charge_panel

    render_capacity_charge_panel(load=lambda: panel)


def _render_failing() -> None:
    from ui.capacity_charge_panel import render_capacity_charge_panel

    def broken():
        raise ValueError("Netzbereich kaputt")

    render_capacity_charge_panel(load=broken)


def _run(panel) -> AppTest:
    app = AppTest.from_function(_render, args=(panel,)).run(timeout=60)
    assert not app.exception
    return app


def _panel(params, peak, report=None):
    return build_capacity_panel(
        params, NOW, read_peak=lambda month: peak, report=report or {"plan": None, "measured": {}}
    )


def _slot(when: str, cause: str, causes: list[str]) -> dict:
    return {"slot": when, "month": "2027-03", "import_kw": 6.2, "limit_kw": 4.7, "over_kw": 1.5,
            "cause": cause, "causes": causes, "consumers_kw": {"wallbox": 3.7}}


def _plan(slots=(), *, planned=True) -> dict:
    return {"schema": 1, "planned": planned, "reason": None if planned else NOT_PLANNED_AUTOMATIK,
            "first_slot": "2027-03-15T12:00", "limits_kw": {"2027-03": 4.7}, "slots": list(slots),
            "months": {}}


def _metrics(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def _captions(app: AppTest) -> str:
    return " ".join(item.value for item in app.caption)


def test_nothing_to_show_renders_nothing():
    app = _run(None)
    assert not app.subheader
    assert not app.metric


def test_a_known_month_shows_peak_billed_amount_and_next_kw(tmp_path: Path):
    app = _run(_panel({**_params(tmp_path, [_charge()]), **CAP}, month_peak(3.0), {"plan": _plan(), "measured": {}}))
    assert [item.value for item in app.subheader] == ["Leistungspreis"]
    metrics = _metrics(app)
    assert list(metrics) == ["Monatsspitze", "Abgerechnet", "Bisher (brutto)", "Nächstes kW"]
    assert "3" in metrics["Monatsspitze"] and "kW" in metrics["Monatsspitze"]
    assert metrics["Bisher (brutto)"].endswith("€")
    captions = _captions(app)
    assert "Gemessen seit 01.03. 00:00" in captions
    assert "geplant wird bis" in captions
    assert "hält die Bezugsgrenze" in captions
    assert not app.warning
    assert not app.expander


def test_an_unknown_month_says_so_and_never_shows_zero(tmp_path: Path):
    app = _run(_panel(_params(tmp_path, [_charge()]), None))
    metrics = _metrics(app)
    assert metrics["Monatsspitze"] == "unbekannt"
    assert metrics["Abgerechnet"] == "unbekannt"
    assert metrics["Bisher (brutto)"].startswith("mind. ")
    assert metrics["Nächstes kW"] == "unbekannt"
    assert "noch keine Viertelstunde gemessen" in _captions(app)


def test_slots_over_the_limit_give_a_warning_with_details(tmp_path: Path):
    slots = [
        _slot("2027-03-15T18:00", CAUSE_BATTERY_ENERGY, [CAUSE_BATTERY_ENERGY]),
        _slot("2027-03-15T18:15", CAUSE_BATTERY_POWER, [CAUSE_BATTERY_POWER, CAUSE_BATTERY_ENERGY]),
        _slot("2027-03-15T18:30", CAUSE_BATTERY_POWER, [CAUSE_BATTERY_POWER]),
    ]
    event = {"slot": "2027-03-10T18:15", "import_kw": 6.0, "threshold_kw": 5.0, "over_kw": 1.0,
             "cause": CAUSE_FORECAST, "planned": False}
    report = {"plan": _plan(slots), "measured": {"2027-03": [event]}}
    app = _run(_panel({**_params(tmp_path, [_charge()]), **CAP}, month_peak(3.0), report))
    assert len(app.warning) == 1
    text = app.warning[0].value
    assert "in 3 Viertelstunde(n) nicht" in text
    assert "Erste: 15.03. 18:00" in text
    assert "Hauptursache: Batterie oder Wechselrichter an der Leistungsgrenze" in text
    assert "Gemessen über der Grenze in 03/2027: 1 Viertelstunde(n)" in _captions(app)
    assert app.expander[0].label == "Details zur Bezugsgrenze"
    assert len(app.dataframe) == 2
    assert list(app.dataframe[0].value["Viertelstunde"]) == ["15.03. 18:00", "15.03. 18:15", "15.03. 18:30"]


def test_a_cap_that_was_not_planned_is_named(tmp_path: Path):
    report = {"plan": _plan(planned=False), "measured": {}}
    app = _run(_panel({**_params(tmp_path, [_charge()]), **CAP}, month_peak(3.0), report))
    assert "nicht eingeplant: Automatikbetrieb" in app.info[0].value
    assert not app.warning


def test_a_cap_below_the_minimum_warns_and_says_it_is_used(tmp_path: Path):
    app = _run(_panel({**_params(tmp_path, [_charge(min_kw=6.0)]), **CAP}, month_peak(3.0)))
    assert "unter der Mindestleistung" in app.warning[0].value
    assert "wie eingegeben" in app.warning[0].value


def test_an_inactive_month_shows_only_the_notice(tmp_path: Path):
    app = _run(_panel({**_params(tmp_path, [_charge(valid_from="2027-06-01")]), **CAP}, None))
    assert "inaktiv bis 06/2027" in app.info[0].value
    assert not app.metric


def test_a_read_error_is_shown_in_the_block():
    app = AppTest.from_function(_render_failing).run(timeout=60)
    assert not app.exception
    assert [item.value for item in app.subheader] == ["Leistungspreis"]
    assert "Netzbereich kaputt" in app.error[0].value
