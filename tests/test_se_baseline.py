"""SE cost table: baseline switchable after the run, from the stored series."""
from __future__ import annotations

import pytest

from simulation.reference_costs import HISTORICAL_REFERENCE_ID
from ui.backtesting_baseline import (
    SeBaseline,
    baseline_options,
    default_baseline,
)
from ui.backtesting_results_helpers import build_annual_cost_rows


def _meta(references: list[str] | None = ("historical", "l0", "l1")) -> dict:
    meta = {
        "live_scenario_id": "live",
        "scenario_ids": [
            HISTORICAL_REFERENCE_ID, "ref:live", "ref:dyn", "l1:live", "l1:dyn", "live", "dyn",
        ],
        "reference_by_scenario": {"live": "ref:live", "dyn": "ref:dyn"},
        "l1_by_scenario": {"live": "l1:live", "dyn": "l1:dyn"},
        "labels": {"live": "Live", "dyn": "Dynamisch"},
        "summary": {
            "total_eur": {
                HISTORICAL_REFERENCE_ID: 2000.0,
                "ref:live": 1500.0,
                "ref:dyn": 1400.0,
                "l1:live": 1200.0,
                "l1:dyn": 1100.0,
                "live": 1000.0,
                "dyn": 900.0,
            }
        },
    }
    if references is not None:
        meta["references"] = list(references)
    return meta


def _deltas(meta: dict, baseline: SeBaseline | None) -> dict[str, str]:
    column = baseline.column if baseline is not None else "Δ [€]"
    return {row["Szenario"]: row[column] for row in build_annual_cost_rows(meta, baseline)}


@pytest.mark.parametrize(
    ("baseline", "live", "dyn"),
    [
        (SeBaseline("live"), "—", "-100,00 €"),
        (SeBaseline("historical"), "-1000,00 €", "-1100,00 €"),
        (SeBaseline("l0", "own"), "-500,00 €", "-500,00 €"),
        (SeBaseline("l0", "live"), "-500,00 €", "-600,00 €"),
        (SeBaseline("l1", "own"), "-200,00 €", "-200,00 €"),
        (SeBaseline("l1", "live"), "-200,00 €", "-300,00 €"),
    ],
)
def test_every_baseline_from_the_same_log(baseline, live, dyn):
    deltas = _deltas(_meta(), baseline)
    assert deltas["Live"] == live
    assert deltas["Dynamisch"] == dyn
    # Reference rows never get a Δ.
    assert deltas["ref:dyn"] == deltas["l1:live"] == "—"


def test_column_names_say_the_baseline_and_the_series():
    assert SeBaseline("live").column == "Δ vs Live (mit Earnie) [€]"
    assert SeBaseline("l0", "own").column == "Δ vs Referenz ohne Speicher (eigene) [€]"
    assert SeBaseline("l1", "live").column == "Δ vs Wechselrichter-Eigenverbrauch (L1) von Live [€]"


def test_options_are_live_and_the_references_that_ran():
    totals = _meta()["summary"]["total_eur"]
    assert baseline_options(_meta(), totals, "live") == ["live", "historical", "l0", "l1"]
    assert baseline_options(_meta(["l1"]), totals, "live") == ["live", "l1"]
    assert baseline_options(_meta([]), totals, "live") == ["live"]
    # A narrowed run without Live has no Live baseline.
    assert baseline_options(_meta([]), {"dyn": 1.0}, "live") == []


def test_log_before_the_selection_offers_no_baseline_and_no_delta():
    meta = _meta(None)
    assert baseline_options(meta, meta["summary"]["total_eur"], "live") is None
    assert set(_deltas(meta, None).values()) == {"—"}


def test_default_is_lives_referenz_ohne_speicher_else_live():
    assert default_baseline(["live", "historical", "l0"]) == SeBaseline("l0", "live")
    assert default_baseline(["live", "l1"]) == SeBaseline("live", "live")


def test_series_defaults_to_lives_for_every_baseline():
    assert default_baseline(["live", "l1"]).series == "live"
    assert default_baseline(["historical", "l1"]).series == "live"


def test_missing_series_of_a_scenario_shows_a_dash():
    meta = _meta()
    del meta["l1_by_scenario"]["dyn"]
    assert _deltas(meta, SeBaseline("l1", "own"))["Dynamisch"] == "—"
