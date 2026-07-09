"""CSV-Format für historische Verbrauchsprofile: timestamp;power_kw (stündlich)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path


def load_hourly_profile_csv(path: str) -> list[tuple[str, float]]:
    """Liest stündliches Profil; liefert (ISO-timestamp, kW)-Paare."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Profil-CSV nicht gefunden: {path}")
    rows: list[tuple[str, float]] = []
    with file_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader, None)
        if header is None:
            return rows
        col_ts = 0
        col_kw = 1
        if header and header[0].strip().lower() == "timestamp":
            for index, name in enumerate(header):
                if name.strip().lower() in ("power_kw", "kw", "leistung_kw"):
                    col_kw = index
                    break
        else:
            handle.seek(0)
            reader = csv.reader(handle, delimiter=";")
        for line_no, row in enumerate(reader, start=2 if header else 1):
            if not row or len(row) <= col_kw:
                continue
            ts_raw = row[col_ts].strip()
            kw_raw = row[col_kw].strip().replace(",", ".")
            if not ts_raw or ts_raw.lower() == "timestamp":
                continue
            try:
                power_kw = float(kw_raw)
            except ValueError as exc:
                raise ValueError(
                    f"{path} Zeile {line_no}: power_kw ungültig ({kw_raw!r})."
                ) from exc
            datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])
            rows.append((ts_raw, power_kw))
    if not rows:
        raise ValueError(f"Profil-CSV '{path}' enthält keine Datenzeilen.")
    return rows
