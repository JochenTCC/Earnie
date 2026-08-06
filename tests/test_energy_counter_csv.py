"""Tests for cumulative energy-counter CSV → power conversion."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from house_config.consumption_csv import (
    MIN_HOURS_FULL_YEAR,
    detect_and_load_grid_raw_series,
    load_and_normalize_profile_csv,
)
from house_config.energy_counter_csv import (
    counter_kwh_to_power_kw,
    load_energy_counter_as_power_kw,
    looks_like_energy_counter,
)


def _write_loxone_counter(path: Path, series: pd.Series, *, header: str) -> None:
    lines = [header]
    for ts, value in series.items():
        stamp = pd.Timestamp(ts)
        value_txt = f"{float(value):.6f}".replace(".", ",")
        lines.append(
            f"{stamp.strftime('%d.%m.%Y')};{stamp.strftime('%H:%M:%S')};{value_txt}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def _write_loxone_dual(
    path: Path,
    *,
    header: str,
    times: list[datetime],
    col_a: list[float],
    col_b: list[float],
) -> None:
    lines = [header]
    for ts, a, b in zip(times, col_a, col_b, strict=True):
        stamp = pd.Timestamp(ts)
        a_txt = f"{float(a):.6f}".replace(".", ",")
        b_txt = f"{float(b):.6f}".replace(".", ",")
        lines.append(
            f"{stamp.strftime('%d.%m.%Y')};{stamp.strftime('%H:%M:%S')};{a_txt};{b_txt}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def _integrate_power_to_energy(power: pd.Series, *, e0: float) -> pd.Series:
    """E[0]=e0; E[i+1]=E[i]+P[i]*Δt_h. Appends a final counter stamp after last P."""
    times = list(power.index)
    energies = [e0]
    energy_times = [times[0]]
    for i in range(len(power)):
        t0 = times[i]
        if i + 1 < len(power):
            t1 = times[i + 1]
        else:
            # Close last interval with same Δt as previous, or 1 h default.
            if i > 0:
                prev_dt = times[i] - times[i - 1]
            else:
                prev_dt = pd.Timedelta(hours=1)
            t1 = t0 + prev_dt
        dt_h = (t1 - t0).total_seconds() / 3600.0
        energies.append(energies[-1] + float(power.iloc[i]) * dt_h)
        energy_times.append(t1)
    return pd.Series(energies, index=pd.DatetimeIndex(energy_times), dtype=float)


def test_counter_to_power_and_back_roundtrip() -> None:
    """Power → integrate → counter → ΔE/Δt recovers original power (irregular Δt)."""
    start = datetime(2025, 3, 1, 0, 0, 0)
    # Irregular intervals: 1 h, 30 min, 2 h, 15 min
    deltas = [
        timedelta(hours=1),
        timedelta(minutes=30),
        timedelta(hours=2),
        timedelta(minutes=15),
    ]
    powers = [2.0, 4.0, 1.5, 0.0]
    times = [start]
    for delta in deltas[:-1]:
        times.append(times[-1] + delta)
    power = pd.Series(powers, index=pd.DatetimeIndex(times), dtype=float)

    energy = _integrate_power_to_energy(power, e0=1000.0)
    recovered = counter_kwh_to_power_kw(energy, source="roundtrip")
    assert len(recovered) == len(power)
    for ts, expected in power.items():
        assert recovered.loc[ts] == pytest.approx(float(expected), rel=1e-9, abs=1e-9)

    # Reverse: counter → power → re-integrate matches original ΔE.
    re_energy = _integrate_power_to_energy(recovered, e0=float(energy.iloc[0]))
    assert float(re_energy.iloc[-1]) == pytest.approx(
        float(energy.iloc[-1]), rel=1e-9, abs=1e-9
    )
    assert float(re_energy.iloc[-1] - re_energy.iloc[0]) == pytest.approx(
        float(energy.iloc[-1] - energy.iloc[0]), rel=1e-9, abs=1e-9
    )


def test_csv_roundtrip_irregular_power(tmp_path: Path) -> None:
    start = datetime(2025, 6, 1, 8, 0, 0)
    times = [
        start,
        start + timedelta(minutes=20),
        start + timedelta(hours=1),
        start + timedelta(hours=1, minutes=30),
    ]
    power = pd.Series([3.0, 0.0, 6.0], index=pd.DatetimeIndex(times[:-1]), dtype=float)
    # Build energy with explicit closing stamps matching power intervals.
    energy_times = times
    energies = [5000.0]
    for i in range(len(power)):
        dt_h = (energy_times[i + 1] - energy_times[i]).total_seconds() / 3600.0
        energies.append(energies[-1] + float(power.iloc[i]) * dt_h)
    energy = pd.Series(energies, index=pd.DatetimeIndex(energy_times), dtype=float)

    path = tmp_path / "counter.csv"
    _write_loxone_counter(path, energy, header="Datum;Zeit;Counter [kWh]")
    loaded = load_energy_counter_as_power_kw(str(path))
    assert list(loaded.values) == pytest.approx(list(power.values), rel=1e-6, abs=1e-6)


def test_counter_drop_warns_and_zeros(caplog: pytest.LogCaptureFixture) -> None:
    idx = pd.to_datetime(
        ["2025-01-01 00:00:00", "2025-01-01 01:00:00", "2025-01-01 02:00:00"]
    )
    energy = pd.Series([100.0, 90.0, 95.0], index=idx)
    with caplog.at_level(logging.WARNING):
        power = counter_kwh_to_power_kw(energy, source="drop-test")
    assert power.iloc[0] == pytest.approx(0.0)
    assert power.iloc[1] == pytest.approx(5.0)
    assert any("counter drop" in rec.message for rec in caplog.records)


def test_detect_zaehlerstand_kwh(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    energy = pd.Series(
        [100.0 + i for i in range(5)],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(5)]),
    )
    path = tmp_path / "zaehler.csv"
    _write_loxone_counter(path, energy, header="Datum;Zeit;Zählerstand [kWh]")
    assert looks_like_energy_counter(path) is True


def test_detect_leistung_kw_is_power(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    power = pd.Series(
        [1.2, 0.0, 3.4, 2.1, 0.5],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(5)]),
    )
    path = tmp_path / "leistung.csv"
    _write_loxone_counter(path, power, header="Datum;Zeit;Leistung Produktion [kW]")
    assert looks_like_energy_counter(path) is False


def test_detect_ertrag_heuristic_without_kwh(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    energy = pd.Series(
        [5652.226 + i * 0.1 for i in range(10)],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(10)]),
    )
    path = tmp_path / "ertrag.csv"
    # Mangled/missing unit — name hint "Ertrag" still marks energy.
    _write_loxone_counter(path, energy, header="Datum;Zeit;Ertrag gesamt")
    assert looks_like_energy_counter(path) is True


def test_detect_monotonic_large_values_heuristic(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    energy = pd.Series(
        [2000.0 + i for i in range(20)],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(20)]),
    )
    path = tmp_path / "plain.csv"
    _write_loxone_counter(path, energy, header="Datum;Zeit;Wert")
    assert looks_like_energy_counter(path) is True


def test_normalize_full_year_counter_conserves_energy(tmp_path: Path) -> None:
    start = datetime(2024, 1, 1)
    hours = MIN_HOURS_FULL_YEAR + 1  # +1 counter stamp for final interval
    e0 = 1000.0
    # Constant 2 kW → +2 kWh per hour
    energies = [e0 + 2.0 * i for i in range(hours)]
    times = [start + timedelta(hours=i) for i in range(hours)]
    energy = pd.Series(energies, index=pd.DatetimeIndex(times), dtype=float)
    path = tmp_path / "year_counter.csv"
    _write_loxone_counter(path, energy, header="Datum;Zeit;Zählerstand [kWh]")

    rows = load_and_normalize_profile_csv(str(path))
    assert len(rows) >= MIN_HOURS_FULL_YEAR
    total_kwh = sum(p for _, p in rows)
    expected_delta = energies[-1] - energies[0]
    # ZOH hourly mean over closed year of constant power ≈ ΔE.
    assert total_kwh == pytest.approx(expected_delta, rel=1e-6, abs=0.01)


def test_grid_kw_path_keeps_bipolar_sign(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    power = pd.Series(
        [2.0, -1.5, 0.0, 3.0],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(4)]),
    )
    path = tmp_path / "netz_kw.csv"
    _write_loxone_counter(path, power, header="Datum;Zeit;Netz [kW]")
    series = detect_and_load_grid_raw_series(str(path))
    assert list(series.values) == pytest.approx([2.0, -1.5, 0.0, 3.0], abs=1e-9)


def test_grid_single_kwh_rejected(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    energy = pd.Series(
        [100.0 + i for i in range(5)],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(5)]),
    )
    path = tmp_path / "netz_single_kwh.csv"
    _write_loxone_counter(path, energy, header="Datum;Zeit;Bezug [kWh]")
    with pytest.raises(ValueError, match="zwei Spalten"):
        detect_and_load_grid_raw_series(str(path))


def test_grid_dual_kwh_combines_import_minus_export(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1, 0, 0, 0)
    # Three stamps → two intervals. Bezug: +2 kWh/h, Einspeisung: +0.5 kWh/h → net +1.5
    times = [start + timedelta(hours=i) for i in range(3)]
    bezug = [1000.0, 1002.0, 1004.0]
    einspeisung = [200.0, 200.5, 201.0]
    path = tmp_path / "netz_dual_kwh.csv"
    _write_loxone_dual(
        path,
        header="Datum;Zeit;Bezug [kWh];Einspeisung [kWh]",
        times=times,
        col_a=bezug,
        col_b=einspeisung,
    )
    series = detect_and_load_grid_raw_series(str(path))
    assert len(series) == 2
    assert float(series.iloc[0]) == pytest.approx(1.5, abs=1e-9)
    assert float(series.iloc[1]) == pytest.approx(1.5, abs=1e-9)


def test_non_grid_single_kwh_still_works(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1)
    energy = pd.Series(
        [100.0 + 2.0 * i for i in range(5)],
        index=pd.DatetimeIndex([start + timedelta(hours=i) for i in range(5)]),
    )
    path = tmp_path / "last_kwh.csv"
    _write_loxone_counter(path, energy, header="Datum;Zeit;Zählerstand [kWh]")
    loaded = load_energy_counter_as_power_kw(str(path))
    assert list(loaded.values) == pytest.approx([2.0, 2.0, 2.0, 2.0], abs=1e-9)
