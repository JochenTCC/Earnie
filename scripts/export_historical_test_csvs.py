#!/usr/bin/env python3
"""
Export Loxone-shaped CSVs from Live System cons_data for Hauskonfigurator import tests.

Writes:
  - PV-Ertrag: Datum/Uhrzeit;Leistung Produktion [kW]
  - Energiemonitor: Datum;Zeit;Leistung Produktion [kW];Leistung Verbrauch [kW]

Example:
  python -m scripts.export_historical_test_csvs --out-dir Historical-Data/export-test
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from house_config.consumption_csv import MIN_HOURS_FULL_YEAR

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "Historical-Data" / "export-test"
PV_FILENAME = "pv_ertrag.csv"
ENERGIEMONITOR_FILENAME = "energiemonitor.csv"

_PV_HEADER = "Datum/Uhrzeit;Leistung Produktion [kW]"
_EM_HEADER = (
    "Datum;Zeit;Leistung Produktion [kW];Leistung Verbrauch [kW]"
)


def _format_de_kw(value: float) -> str:
    return f"{float(value):.3f}".replace(".", ",")


def _parse_bound(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    return pd.Timestamp(value)


def _load_cons_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"cons_data fehlt: {path}")
    df = pd.read_csv(path, sep=";", decimal=".")
    if "timestamp" not in df.columns:
        raise ValueError(f"{path}: Spalte 'timestamp' fehlt.")
    for col in ("pv_kw", "total_kw"):
        if col not in df.columns:
            raise ValueError(f"{path}: Spalte '{col}' fehlt.")
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _filter_range(
    df: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> pd.DataFrame:
    out = df
    if start is not None:
        out = out[out.index >= start]
    if end is not None:
        out = out[out.index <= end]
    return out


def _require_full_year(df: pd.DataFrame) -> None:
    if len(df) < MIN_HOURS_FULL_YEAR:
        raise ValueError(
            f"Zu wenig Stunden nach Filter: {len(df)} "
            f"(mindestens {MIN_HOURS_FULL_YEAR} nötig)."
        )


def write_pv_ertrag_csv(df: pd.DataFrame, path: Path) -> int:
    """Write separate PV-Ertrag CSV (Loxone single-series layout)."""
    lines = [_PV_HEADER]
    for ts, row in df.iterrows():
        stamp = pd.Timestamp(ts).strftime("%d.%m.%Y %H:%M:%S")
        lines.append(f"{stamp};{_format_de_kw(row['pv_kw'])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return len(df)


def write_energiemonitor_csv(df: pd.DataFrame, path: Path) -> int:
    """Write Energiemonitor CSV with only Produktion + Verbrauch columns."""
    lines = [_EM_HEADER]
    for ts, row in df.iterrows():
        stamp = pd.Timestamp(ts)
        date_s = stamp.strftime("%d.%m.%Y")
        time_s = stamp.strftime("%H:%M:%S")
        lines.append(
            f"{date_s};{time_s};"
            f"{_format_de_kw(row['pv_kw'])};{_format_de_kw(row['total_kw'])}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return len(df)


def export_historical_test_csvs(
    cons_data: Path,
    out_dir: Path,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> dict[str, Path]:
    """Export PV-Ertrag + Energiemonitor CSVs from cons_data; return output paths."""
    df = _filter_range(_load_cons_frame(cons_data), start, end)
    _require_full_year(df)
    pv_path = out_dir / PV_FILENAME
    em_path = out_dir / ENERGIEMONITOR_FILENAME
    write_pv_ertrag_csv(df, pv_path)
    write_energiemonitor_csv(df, em_path)
    return {"pv_ertrag": pv_path, "energiemonitor": em_path}


def _default_cons_data_path() -> Path:
    from runtime_store.config_load import load_config_or_exit

    load_config_or_exit()
    from data.cons_data_store import get_output_path

    return Path(get_output_path())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cons-data",
        type=Path,
        default=None,
        help="Pfad zu cons_data.csv (Default: path_cons_data aus config)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Zielverzeichnis (Default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument("--from", dest="date_from", default=None, help="Start YYYY-MM-DD[ HH:MM:SS]")
    parser.add_argument("--to", dest="date_to", default=None, help="Ende YYYY-MM-DD[ HH:MM:SS]")
    args = parser.parse_args(argv)

    cons_path = args.cons_data or _default_cons_data_path()
    try:
        paths = export_historical_test_csvs(
            cons_path,
            args.out_dir,
            start=_parse_bound(args.date_from),
            end=_parse_bound(args.date_to),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(f"PV-Ertrag:      {paths['pv_ertrag']}")
    print(f"Energiemonitor: {paths['energiemonitor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
