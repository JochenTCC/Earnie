"""RuleRef P4: SE headline and ladder table read the cost table's figures."""
from __future__ import annotations

import pytest

from ui.backtesting_ladder import (
    build_ladder_summaries,
    ladder_table_rows,
    rule_share_text,
)
from ui.backtesting_results_helpers import build_annual_cost_rows


def _meta() -> dict:
    return {
        "reference_id": "historical_reference",
        "live_scenario_id": "live",
        "scenario_ids": [
            "historical_reference",
            "ref:live",
            "l1:live",
            "l2:live",
            "other",
            "live",
        ],
        "labels": {"live": "Live", "other": "Andere"},
        "reference_by_scenario": {"live": "ref:live", "other": "ref:live"},
        "ladder_by_scenario": {
            "other": {"l1": "l1:live", "l2": "l2:live"},
            "live": {"l1": "l1:live", "l2": "l2:live"},
        },
        "summary": {
            "total_eur": {
                "historical_reference": 2000.0,
                "ref:live": 1500.0,
                "l1:live": 1200.0,
                "l2:live": 1000.0,
                "other": 950.0,
                "live": 900.0,
            }
        },
    }


def _soc_block(l1: float, l2: float) -> dict:
    return {
        "soc_end_percent": 50.0,
        "steps": {
            "l1": {"correction_eur": l1, "soc_end_percent": 40.0},
            "l2": {"correction_eur": l2, "soc_end_percent": 45.0},
        },
    }


def _live(meta: dict):
    return next(s for s in build_ladder_summaries(meta) if s.scenario_id == "live")


def test_saving_and_rule_share():
    summary = _live(_meta())
    assert summary.saving_eur == pytest.approx(100.0)
    assert summary.rule_share == pytest.approx(500.0 / 600.0)


def test_live_scenario_comes_first():
    assert [s.scenario_id for s in build_ladder_summaries(_meta())] == ["live", "other"]


def test_end_soc_term_counts_in_saving_and_share_like_the_table():
    meta = _meta()
    meta["ladder_soc_correction"] = {"live": _soc_block(2.0, 1.35)}
    summary = _live(meta)
    assert summary.saving_eur == pytest.approx(101.35)
    assert summary.rule_share == pytest.approx((1500.0 - 1001.35) / 600.0)
    row = next(row for row in build_annual_cost_rows(meta) if row["Szenario"] == "Live")
    assert row["Ersparnis vs. Standard-Regeln [€]"] == f"{summary.saving_eur:+.2f} €"


def test_fuel_counts_on_every_step():
    meta = _meta()
    meta["heat_fuel"] = {
        "ref:live": {"fuel_eur": 100.0, "co2_kg": 1.0},
        "l2:live": {"fuel_eur": 50.0, "co2_kg": 1.0},
        "live": {"fuel_eur": 20.0, "co2_kg": 1.0},
    }
    summary = _live(meta)
    assert summary.saving_eur == pytest.approx(130.0)
    assert summary.costs["l0"] == pytest.approx(1600.0)


def test_log_without_a_ladder_has_no_summary():
    meta = _meta()
    del meta["ladder_by_scenario"]
    assert build_ladder_summaries(meta) == []


def test_ladder_scenario_without_cost_fails_loud():
    meta = _meta()
    del meta["summary"]["total_eur"]["other"]
    with pytest.raises(ValueError, match="other"):
        build_ladder_summaries(meta)


def test_rule_share_without_total_saving_is_named():
    meta = _meta()
    meta["summary"]["total_eur"]["live"] = 1600.0
    assert _live(meta).rule_share is None
    assert "keine Gesamtersparnis" in rule_share_text(None)


def test_rule_share_text_is_a_percentage():
    assert rule_share_text(0.726) == "Anteil der Regeln: 73 %"


def test_table_steps_add_up_to_the_total_saving():
    meta = _meta()
    meta["ladder_soc_correction"] = {"live": _soc_block(2.0, 1.35)}
    rows = [r for r in ladder_table_rows(build_ladder_summaries(meta)) if r["Szenario"] == "Live"]
    assert [r["Kosten [€]"] for r in rows] == ["1500.00 €", "1200.00 €", "1000.00 €", "900.00 €"]
    assert [r["Ladestand am Periodenende [€]"] for r in rows] == ["—", "+2.00 €", "+1.35 €", "—"]
    assert [r["Ersparnis zur Stufe davor [€]"] for r in rows] == [
        "—",
        "+298.00 €",
        "+200.65 €",
        "+101.35 €",
    ]
    assert 298.00 + 200.65 + 101.35 == pytest.approx(1500.0 - 900.0)


def test_log_without_end_soc_valuation_shows_no_term():
    rows = ladder_table_rows(build_ladder_summaries(_meta()))
    assert all(r["Ladestand am Periodenende [€]"] == "—" for r in rows)
