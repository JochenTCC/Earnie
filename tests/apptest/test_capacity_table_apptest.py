"""SE results: the capacity table shows only when the log has a capacity block."""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _render(meta: dict) -> None:
    import ui.backtesting  # noqa: F401  # as in the app: this module first, the two import each other
    from ui.backtesting_results import render_capacity_table

    render_capacity_table(meta)


def _month() -> dict:
    return {
        "month": "2027-01",
        "charge_id": "lp_2027",
        "peak_kw": 5.0,
        "peak_slot": "2027-01-12T18:15:00",
        "billed_kw": 5.0,
        "net_eur": 7.5,
        "gross_eur": 9.0,
    }


def _meta(block: dict | None) -> dict:
    meta: dict = {
        "scenario_ids": ["s"],
        "labels": {"s": "S"},
        "summary": {"total_eur": {"s": 1.0}},
    }
    if block is not None:
        meta["capacity_by_scenario"] = {"s": block}
    return meta


def test_table_shows_for_a_result_with_months():
    app = AppTest.from_function(
        _render, args=(_meta({"months": [_month()], "skipped": {}, "not_convex": [], "gross_eur": 9.0}),)
    ).run(timeout=60)
    assert not app.exception
    assert [item.value for item in app.subheader] == ["Leistungspreis"]
    assert len(app.dataframe) == 1
    assert list(app.dataframe[0].value["Monat"]) == ["2027-01"]
    assert not app.info


def test_skipped_entry_gives_a_notice_without_table():
    app = AppTest.from_function(
        _render,
        args=(_meta({"months": [], "skipped": {"lp_2027": "entwurf"}, "not_convex": [], "gross_eur": 0.0}),),
    ).run(timeout=60)
    assert not app.exception
    assert not app.dataframe
    assert "lp_2027 (Status entwurf)" in app.info[0].value


def test_older_log_shows_nothing():
    app = AppTest.from_function(_render, args=(_meta(None),)).run(timeout=60)
    assert not app.exception
    assert not app.subheader
    assert not app.dataframe
    assert not app.info
