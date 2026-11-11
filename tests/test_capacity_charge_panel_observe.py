"""Monitor block "Leistungspreis" in the cap's observe mode (max-power tariff P6d-2)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from optimizer.import_cap_report import CAUSE_BATTERY_ENERGY, CAUSE_FORECAST, NOT_PLANNED_SHADOW
from tests.test_capacity_charge import VAT_FACTOR, _charge, _params
from tests.test_capacity_charge_panel import NOW, _peaks, month_peak
from ui.capacity_charge_panel import build_capacity_panel

OBSERVE = {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3, "import_cap_mode": "observe"}
OPTIMIZE = {**OBSERVE, "import_cap_mode": "optimize"}


def _observe_block(*, extra: float | None = 0.42) -> dict:
    return {
        "slot": "2027-03-15T12:00",
        "delta_import_kw": -1.5,
        "executed": {"import_kw": 6.5, "battery_kw": 0.0, "consumers_kw": {"wallbox": 3.7}},
        "shadow": {"import_kw": 5.0, "battery_kw": 1.0, "consumers_kw": {"wallbox": 3.2}},
        "energy_cost_extra_eur": extra,
    }


def _plan(*, mode: str = "observe", slots=(), planned=True, reason=None) -> dict:
    plan = {
        "schema": 2, "mode": mode, "planned": planned, "reason": reason,
        "first_slot": "2027-03-15T12:00", "limits_kw": {"2027-03": 4.7}, "slots": list(slots),
        "months": {},
    }
    if mode == "observe":
        plan["observe"] = _observe_block(extra=0.42 if planned else None)
    return plan


def _intervention(slot: str = "2027-03-12T18:00", cause: str | None = None) -> dict:
    return {
        "slot": slot, "measured_kw": 6.5, "hypothetical_kw": 5.0, "delta_kw": -1.5,
        "executed": _observe_block()["executed"], "shadow": _observe_block()["shadow"],
        "cause": cause,
    }


REAL_EVENT = {"slot": "2027-03-10T18:15", "import_kw": 7.0, "threshold_kw": 5.0, "over_kw": 2.0,
              "cause": CAUSE_FORECAST, "planned": False}
HYPOTHETICAL_EVENT = {**REAL_EVENT, "slot": "2027-03-11T18:15", "import_kw": 5.6, "over_kw": 0.6,
                      "cause": CAUSE_BATTERY_ENERGY, "hypothetical": True, "measured_kw": 7.1}


def _report(plan=None, interventions=(), measured=(REAL_EVENT, HYPOTHETICAL_EVENT)) -> dict:
    return {"plan": plan, "measured": {"2027-03": list(measured)},
            "interventions": {"2027-03": list(interventions)}}


def _panel(params, peak, observe_peak, report, baseline=None):
    return build_capacity_panel(
        params, NOW, read_peak=_peaks(peak), report=report,
        read_observe_peak=_peaks(observe_peak), read_observe_baseline=_peaks(baseline),
    )


# --- what the block holds -------------------------------------------------------------------


def test_the_saving_compares_both_peaks_of_the_observed_quarter_hours(tmp_path: Path):
    """The real peak from before observing (12 kW) does not enter the saving."""
    observed = replace(month_peak(5.0), first_slot="2027-03-05T00:00:00")
    baseline = replace(month_peak(6.0), first_slot="2027-03-05T00:00:00")
    panel = _panel(
        {**_params(tmp_path, [_charge()]), **OBSERVE}, month_peak(12.0), observed,
        _report(_plan(), [_intervention()]), baseline,
    )
    assert panel.observe
    assert panel.gross_eur == pytest.approx(21.0 * VAT_FACTOR)
    assert panel.observe_baseline_peak.peak_kw == 6.0
    assert panel.saving_gross_eur == pytest.approx(1.5 * VAT_FACTOR)
    assert panel.planning_limit_kw == pytest.approx(4.7)  # the shadow plan's ratchet: 5.0 − 0.3
    assert [e["slot"] for e in panel.measured] == ["2027-03-11T18:15"]
    assert len(panel.interventions) == 1


def test_an_unknown_hypothetical_month_gives_no_saving(tmp_path: Path):
    panel = _panel({**_params(tmp_path, [_charge()]), **OBSERVE}, month_peak(7.0), None, _report())
    assert panel.observe_peak is None
    assert panel.saving_gross_eur is None
    assert panel.planning_limit_kw == pytest.approx(4.7)
    without_baseline = _panel(
        {**_params(tmp_path, [_charge()]), **OBSERVE}, month_peak(7.0), month_peak(5.0), _report()
    )
    assert without_baseline.saving_gross_eur is None


def test_optimize_mode_shows_only_its_own_checks(tmp_path: Path):
    panel = _panel(
        {**_params(tmp_path, [_charge()]), **OPTIMIZE}, month_peak(7.0), month_peak(5.0),
        _report(_plan(mode="optimize"), [_intervention()]), month_peak(6.0),
    )
    assert not panel.observe
    assert panel.observe_peak is None
    assert panel.observe_baseline_peak is None
    assert panel.saving_gross_eur is None
    assert panel.interventions == ()
    assert [e["slot"] for e in panel.measured] == ["2027-03-10T18:15"]
    assert panel.planning_limit_kw == pytest.approx(6.7)


def test_a_cap_without_mode_or_without_the_hypothetical_store_fails_loud(tmp_path: Path):
    params = _params(tmp_path, [_charge()])
    with pytest.raises(ValueError, match="import_cap_mode fehlt"):
        build_capacity_panel(
            {**params, "import_cap_kw": 5.0, "import_cap_margin_kw": 0.3}, NOW,
            read_peak=_peaks(None), report=_report(),
        )
    with pytest.raises(ValueError, match="Beobachtungsmodus"):
        build_capacity_panel({**params, **OBSERVE}, NOW, read_peak=_peaks(None), report=_report())
    with pytest.raises(ValueError, match="Beobachtungsmodus"):
        build_capacity_panel(
            {**params, **OBSERVE}, NOW, read_peak=_peaks(None), report=_report(),
            read_observe_peak=_peaks(None),
        )


# --- what the block shows -------------------------------------------------------------------


def _render(panel) -> None:
    from ui.capacity_charge_panel import render_capacity_charge_panel

    render_capacity_charge_panel(load=lambda: panel)


def _run(panel) -> AppTest:
    app = AppTest.from_function(_render, args=(panel,)).run(timeout=60)
    assert not app.exception
    return app


def _captions(app: AppTest) -> str:
    return " ".join(item.value for item in app.caption)


def test_the_observed_block_shows_the_saving_and_where_earnie_would_have_acted(tmp_path: Path):
    observed = replace(month_peak(5.0), first_slot="2027-03-05T00:00:00", slots_missing=3)
    baseline = replace(month_peak(6.0), first_slot="2027-03-05T00:00:00", slots_missing=3)
    over = {"slot": "2027-03-15T18:00", "month": "2027-03", "import_kw": 6.2, "limit_kw": 4.7,
            "over_kw": 1.5, "cause": CAUSE_BATTERY_ENERGY, "causes": [CAUSE_BATTERY_ENERGY],
            "consumers_kw": {}}
    app = _run(_panel(
        {**_params(tmp_path, [_charge()]), **OBSERVE}, month_peak(7.0), observed,
        _report(_plan(slots=[over]), [_intervention(cause=CAUSE_BATTERY_ENERGY)]), baseline,
    ))
    assert "Beobachtungsmodus" in app.info[0].value
    metrics = {metric.label: metric.value for metric in app.metric}
    assert list(metrics) == [
        "Monatsspitze", "Abgerechnet", "Bisher (brutto)", "Nächstes kW",
        "Spitze ohne Earnie", "Spitze mit Earnie", "Ersparnis (geschätzt)", "Mehrkosten Energie",
    ]
    assert "6" in metrics["Spitze ohne Earnie"]
    assert "5" in metrics["Spitze mit Earnie"]
    assert "1,80" in metrics["Ersparnis (geschätzt)"]
    assert "0,42" in metrics["Mehrkosten Energie"]
    captions = _captions(app)
    assert "Beide Spitzen seit 05.03. 00:00" in captions
    assert "3 Viertelstunden ohne Vergleich zählen nicht" in captions
    assert "der Vergleichsplan rechnet bis" in captions
    assert "Eingegriffen hätte Earnie in 03/2027 in 1 Viertelstunde(n)" in captions
    assert "Mit Earnie geschätzt über der Grenze in 03/2027: 1 Viertelstunde(n)" in captions
    assert "Der Vergleichsplan mit Grenze hält die Bezugsgrenze in 1 Viertelstunde(n) nicht" in app.warning[0].value
    assert len(app.dataframe) == 3
    steps = app.dataframe[0].value
    assert list(steps["Änderung (kW)"]) == [-1.5]
    assert list(steps["Verbraucher"]) == ["wallbox 3,70 → 3,20 kW"]
    assert list(steps["Batterie ohne → mit Grenze (kW)"]) == ["0,00 → 1,00"]
    assert list(app.dataframe[2].value["Mit Earnie geschätzt (kW)"]) == [5.6]


def test_a_failed_comparison_plan_is_named(tmp_path: Path):
    plan = _plan(planned=False, reason=NOT_PLANNED_SHADOW)
    app = _run(_panel(
        {**_params(tmp_path, [_charge()]), **OBSERVE}, month_peak(7.0), month_peak(5.0),
        _report(plan, measured=()),
    ))
    assert any("Vergleichsplan mit Grenze war nicht lösbar" in item.value for item in app.info)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Mehrkosten Energie"] == "unbekannt"


def test_a_report_of_the_other_mode_waits_for_the_next_cycle(tmp_path: Path):
    app = _run(_panel(
        {**_params(tmp_path, [_charge()]), **OPTIMIZE}, month_peak(3.0), None,
        _report(_plan(), measured=()),
    ))
    assert "Noch kein Bericht des Optimierer-Dienstes" in _captions(app)
    assert not any("Beobachtungsmodus" in item.value for item in app.info)
    assert "Spitze mit Earnie" not in [metric.label for metric in app.metric]


def test_a_cap_below_the_minimum_names_the_comparison_plan(tmp_path: Path):
    app = _run(_panel(
        {**_params(tmp_path, [_charge(min_kw=6.0)]), **OBSERVE}, month_peak(7.0), None, _report(),
    ))
    assert "Der Vergleichsplan rechnet mit der Grenze wie eingegeben" in app.warning[0].value
