"""Tests for scripts.export_historical_test_csvs (SE Live → import test CSVs)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from house_config.consumption_csv import (
    MIN_HOURS_FULL_YEAR,
    import_energiemonitor_to_canonical,
    load_and_normalize_profile_csv,
    load_hourly_profile_csv,
)
from scripts.export_historical_test_csvs import (
    ENERGIEMONITOR_FILENAME,
    PV_FILENAME,
    export_historical_test_csvs,
)


def _write_cons_data(path: Path, hours: int) -> None:
    start = datetime(2023, 1, 1)
    rows = []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        rows.append(
            {
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "total_kw": 0.5 + (i % 24) * 0.01,
                "baseload_kw": 0.3,
                "pv_kw": max(0.0, 2.0 - abs(12 - (i % 24)) * 0.2),
                "source": "synthetic",
            }
        )
    pd.DataFrame(rows).to_csv(path, sep=";", index=False, decimal=".")


def test_export_requires_full_year(tmp_path: Path) -> None:
    cons = tmp_path / "cons_data.csv"
    _write_cons_data(cons, hours=100)
    with pytest.raises(ValueError, match="8760"):
        export_historical_test_csvs(cons, tmp_path / "out")


def test_export_round_trip_energiemonitor_and_pv(tmp_path: Path) -> None:
    cons = tmp_path / "cons_data.csv"
    _write_cons_data(cons, hours=MIN_HOURS_FULL_YEAR)
    out_dir = tmp_path / "export"
    paths = export_historical_test_csvs(cons, out_dir)

    assert paths["pv_ertrag"].name == PV_FILENAME
    assert paths["energiemonitor"].name == ENERGIEMONITOR_FILENAME
    assert paths["pv_ertrag"].is_file()
    assert paths["energiemonitor"].is_file()

    pv_rows = load_and_normalize_profile_csv(str(paths["pv_ertrag"]))
    assert len(pv_rows) >= MIN_HOURS_FULL_YEAR
    assert pv_rows[12][1] == pytest.approx(2.0, abs=0.01)

    verbrauch_dest = tmp_path / "verbrauch.csv"
    produktion_dest = tmp_path / "produktion.csv"
    result = import_energiemonitor_to_canonical(
        str(paths["energiemonitor"]),
        verbrauch_dest=str(verbrauch_dest),
        produktion_dest=str(produktion_dest),
    )
    assert result["total_profile_csv"] == str(verbrauch_dest)
    assert result["pv_profile_csv"] == str(produktion_dest)
    verbrauch = load_hourly_profile_csv(str(verbrauch_dest))
    produktion = load_hourly_profile_csv(str(produktion_dest))
    assert len(verbrauch) >= MIN_HOURS_FULL_YEAR
    assert len(produktion) >= MIN_HOURS_FULL_YEAR
    assert verbrauch[0][1] == pytest.approx(0.5, abs=0.01)
    assert produktion[12][1] == pytest.approx(2.0, abs=0.01)


def test_export_date_filter(tmp_path: Path) -> None:
    cons = tmp_path / "cons_data.csv"
    _write_cons_data(cons, hours=MIN_HOURS_FULL_YEAR + 48)
    out_dir = tmp_path / "filtered"
    export_historical_test_csvs(
        cons,
        out_dir,
        start=pd.Timestamp("2023-01-01"),
        end=pd.Timestamp("2023-12-31 23:00:00"),
    )
    header = (out_dir / ENERGIEMONITOR_FILENAME).read_text(encoding="latin-1").splitlines()[0]
    assert "Leistung Produktion [kW]" in header
    assert "Leistung Verbrauch [kW]" in header
    assert "Energieversorger" not in header
