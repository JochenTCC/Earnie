"""AppTest: optimization result display (Chart 1 + 2, table, energy comparison, S-2 nav).

Synthetic MILP rows for segment SA1->SA2, no optimizer run. Script:
``scripts/run_cov_optimization_display.py``.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_SCRIPT = Path(__file__).parent / "scripts" / "run_cov_optimization_display.py"
_TIMEOUT = 60


def _run(mode: str) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT)
    at.session_state["cov_mode"] = mode
    at.run()
    assert_clean(at)
    return at


def _figures(at: AppTest) -> list[dict]:
    return [json.loads(chart.proto.spec) for chart in at.get("plotly_chart")]


def _trace_names(figure: dict) -> list[str]:
    return [str(trace.get("name") or "") for trace in figure["data"]]


def _values(raw) -> list:
    """Plotly packs numeric arrays as ``{"dtype", "bdata"}`` (base64)."""
    if isinstance(raw, dict) and "bdata" in raw:
        return np.frombuffer(base64.b64decode(raw["bdata"]), dtype=raw["dtype"]).tolist()
    return list(raw)


def test_results_render_chart1_chart2_table_and_energy_comparison() -> None:
    at = _run("results")
    figures = _figures(at)
    assert len(figures) >= 2  # Chart 1 (power/SoC) and Chart 2 (account)
    chart1 = figures[0]
    names = _trace_names(chart1)
    assert any("SoC" in name for name in names), names
    # The PV forecast of the rows is drawn with its values.
    pv = [t for t in chart1["data"] if t.get("name") == "PV"]
    assert pv, names
    values = [float(v) for v in _values(pv[0]["y"]) if v is not None and v == v]
    assert max(values) == 2.0 and min(values) == 0.0

    labels = [e.label for e in at.expander]
    assert "⚡ Energievergleich Baseline vs. Optimierung" in labels
    assert "📋 Simulations-Details (Sunset-2-Sunset-Fenster)" in labels

    comparison = next(
        df.value for df in at.dataframe if "Verbraucher" in getattr(df.value, "columns", [])
    )
    records = comparison.to_dict("records")
    assert records[0]["Verbraucher"] == "Pool"
    assert records[0]["BL Profil (kWh)"].endswith(" kWh")
    assert records[0]["Optimierung"].endswith("kWh (Tagesziel)")
    assert records[1]["Optimierung"].endswith(" kWh")  # no source -> no suffix
    assert "(" not in records[1]["Optimierung"]
    assert records[1]["BL Ziel (kWh)"].startswith("0")  # missing value counts 0

    # Frozen simulation table: one HTML block with the MILP rows labelled "MILP".
    html = "\n".join(str(m.value) for m in at.markdown) + "\n".join(
        str(getattr(h, "proto", "")) for h in at.get("html")
    )
    assert "MILP" in html


def test_results_s2_navigation_forward_then_today() -> None:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT)
    at.session_state["cov_mode"] = "results"
    at.session_state["s2_span_override"] = "segment"  # phone layout: 24 h segments
    at.run()
    assert_clean(at)
    keys = {b.key for b in at.button}
    assert {"s2_nav_back", "s2_nav_today", "s2_nav_forward"} <= keys
    # Live window: "Heute" is disabled, "vor" leads to SA1->SA2.
    assert at.button(key="s2_nav_today").disabled
    assert not at.button(key="s2_nav_forward").disabled
    at.button(key="s2_nav_forward").click().run()
    assert_clean(at)
    assert at.session_state["s2_cycle_offset"] == 0
    assert at.session_state["s2_segment_index"] == 1
    assert not at.button(key="s2_nav_today").disabled
    at.button(key="s2_nav_today").click().run()
    assert_clean(at)
    assert at.session_state["s2_segment_index"] == 0


def test_snapshot_bundle_renders_chart1_and_the_data_basis_expander() -> None:
    at = _run("snapshot")
    assert at.session_state["cov_bundle_none"] is False
    # Hourly MILP rows are spread over the quarter-hour chart slots.
    assert at.session_state["cov_bundle_rows"] == at.session_state["cov_chart_slot_count"]
    assert at.session_state["cov_bundle_rows"] > at.session_state["cov_row_count"]
    assert at.session_state["cov_bundle_matched"] is True
    assert len(_figures(at)) == 1
    # Data basis expander: label is the production-log path, body says "Merge-Pfad".
    body = "\n".join(str(m.value) for m in at.markdown)
    assert "Datenbasis Produktiv-Log" in body
    assert "Merge-Pfad aktiv" in body


def test_snapshot_without_rows_builds_no_bundle() -> None:
    at = _run("empty_snapshot")
    assert at.session_state["cov_bundle_none"] is True
    assert _figures(at) == []


# --- PV forecast comparison toggle above Chart 1 (chart_pv_compare) ---------------------

_TOGGLE_KEY = "cov_chart1_pv_compare"


def test_pv_compare_is_hidden_without_the_logger_dir(monkeypatch) -> None:
    monkeypatch.delenv("EARNIE_PV_FORECAST_COMPARE_DIR", raising=False)
    at = _run("snapshot")
    assert [t.key for t in at.toggle if t.key == _TOGGLE_KEY] == []


def test_pv_compare_with_missing_logger_file_warns_and_keeps_the_chart(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_PV_FORECAST_COMPARE_DIR", str(tmp_path / "pvcmp"))
    at = _run("snapshot")
    assert at.toggle(key=_TOGGLE_KEY).value is True
    assert any("Test-Prognosen PV nicht lesbar" in w.value for w in at.warning)
    assert len(_figures(at)) == 1


def test_pv_compare_draws_one_line_per_source_and_toggle_off_hides_it(tmp_path, monkeypatch) -> None:
    from runtime_store import pv_forecast_compare_view as view

    monkeypatch.setenv("EARNIE_PV_FORECAST_COMPARE_DIR", str(tmp_path))
    seen: dict = {}

    def _series(path, hour_starts):
        seen["path"] = path
        seen["count"] = len(hour_starts)
        return {"solcast": {view.hour_key(h): 1.5 for h in hour_starts}}

    monkeypatch.setattr(view, "cached_series_by_source", _series)
    at = _run("snapshot")
    assert seen["path"] == tmp_path / view.FORECASTS_FILENAME
    assert seen["count"] == at.session_state["cov_chart_slot_count"]
    (figure,) = _figures(at)
    compare = [t for t in figure["data"] if t.get("name") == view.source_label("solcast")]
    assert len(compare) == 1
    assert set(_values(compare[0]["y"])) == {1.5}

    at.toggle(key=_TOGGLE_KEY).set_value(False).run()
    assert_clean(at)
    (figure,) = _figures(at)
    assert view.source_label("solcast") not in _trace_names(figure)
