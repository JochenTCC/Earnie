"""Korreliert Cursor-Token-Verbrauch (Usage-CSV) mit Kapiteln (Minor-Bumps).

Ordnet jedes Token-Event aus dem Cursor-Usage-Export dem Zeitfenster zwischen
zwei Minor-Bump-Commits (= Kapitel laut versioning.mdc) zu und aggregiert
mehrere Kennzahlen pro Kapitel.

Grenzen (bewusst, siehe Backlog-Diskussion):
- Das CSV enthaelt **keine Chat-/Session-ID** -> die Zuordnung ist rein
  zeitbasiert, nicht chat-genau. Parallele/Hintergrund-Agenten mischen sich mit.
- Der Export ist ein rollierendes Fenster; Kapitel ausserhalb der CSV-Abdeckung
  werden als "teilweise"/"keine Daten" markiert, nicht geschaetzt.

Beispiel:
    .venv\\Scripts\\python.exe -m scripts.token_commit_report \\
        --usage-csv "C:\\Users\\joche\\Downloads\\usage-events-2026-07-07.csv"

Nach jedem Commit (interaktiv): post-commit-Hook oder
    sh scripts/run_token_commit_report_interactive.sh
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_COLUMNS = (
    "Date",
    "Cache Read",
    "Output Tokens",
    "Total Tokens",
    "Cost",
)
_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([0-9]+)\.([0-9]+)\.([0-9]+)["\']')
_UNIT = "\x1f"  # ASCII unit separator als Feldtrenner fuer git-Ausgabe


@dataclass
class UsageEvent:
    when: datetime  # timezone-aware, UTC
    total_tokens: int
    cache_read: int
    output_tokens: int
    cost_eur: float


@dataclass
class Chapter:
    version: str  # "MAJOR.MINOR"
    commit: str  # kurzer Hash
    subject: str
    end: datetime  # UTC, Commit-Zeit (Kapitelende)
    start: datetime | None  # UTC, vorheriges Kapitelende (None = offen nach unten)
    events: list[UsageEvent] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--usage-csv", required=True, help="Pfad zum Cursor-Usage-CSV-Export")
    p.add_argument("--repo", default=".", help="Repo-Pfad (Default: aktuelles Verzeichnis)")
    p.add_argument(
        "--include-head",
        action="store_true",
        help="Offene Arbeit nach dem letzten Minor-Bump als eigene Zeile ausweisen",
    )
    return p.parse_args()


def _to_utc(raw: str) -> datetime:
    """ISO-8601 (auch mit 'Z') robust in eine UTC-aware datetime wandeln."""
    text = raw.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Zeitstempel ohne Zeitzone: {raw!r}")
    return dt.astimezone(timezone.utc)


def _as_int(value: str) -> int:
    value = (value or "").strip()
    return int(value) if value else 0


def _as_cost(value: str) -> float:
    """Cost-Spalte: 'Included'/leer -> 0.0, sonst EUR-Betrag."""
    value = (value or "").strip()
    try:
        return float(value)
    except ValueError:
        return 0.0


def read_usage_events(csv_path: Path) -> list[UsageEvent]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Usage-CSV nicht gefunden: {csv_path}")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"CSV fehlen erwartete Spalten {missing}. Gefunden: {reader.fieldnames}"
            )
        events = [
            UsageEvent(
                when=_to_utc(row["Date"]),
                total_tokens=_as_int(row["Total Tokens"]),
                cache_read=_as_int(row["Cache Read"]),
                output_tokens=_as_int(row["Output Tokens"]),
                cost_eur=_as_cost(row["Cost"]),
            )
            for row in reader
        ]
    if not events:
        raise ValueError(f"Keine Datenzeilen im CSV: {csv_path}")
    return events


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} fehlgeschlagen: {result.stderr.strip()}")
    return result.stdout


def _version_at(repo: Path, commit: str) -> tuple[int, int] | None:
    """(major, minor) von version.py bei einem Commit; None wenn nicht vorhanden."""
    try:
        content = _git(repo, "show", f"{commit}:version.py")
    except RuntimeError:
        return None
    match = _VERSION_RE.search(content)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def latest_commit_time(repo: Path) -> datetime | None:
    """Zeitpunkt des jüngsten Commits (HEAD), UTC; None wenn kein Commit."""
    raw = _git(repo, "log", "-1", "--format=%cI").strip()
    return _to_utc(raw) if raw else None


def collect_version_commits(repo: Path) -> list[tuple[datetime, str, str, tuple[int, int]]]:
    """Commits, die version.py beruehren, aufsteigend nach Zeit, mit (major, minor)."""
    raw = _git(repo, "log", f"--format=%H{_UNIT}%cI{_UNIT}%s", "--", "version.py")
    rows: list[tuple[datetime, str, str, tuple[int, int]]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        full_hash, iso, subject = line.split(_UNIT, 2)
        version = _version_at(repo, full_hash)
        if version is None:
            continue
        rows.append((_to_utc(iso), full_hash[:7], subject, version))
    rows.sort(key=lambda r: r[0])
    return rows


def detect_chapters(version_commits: list[tuple[datetime, str, str, tuple[int, int]]]) -> list[Chapter]:
    """Minor-Bump-Commits als Kapitelgrenzen; Fenster = (voriges Kapitelende, dieses]."""
    chapters: list[Chapter] = []
    prev_version: tuple[int, int] | None = None
    prev_end: datetime | None = None
    for when, short, subject, version in version_commits:
        is_bump = prev_version is None or version > prev_version
        if is_bump and version != prev_version:
            chapters.append(
                Chapter(
                    version=f"{version[0]}.{version[1]}",
                    commit=short,
                    subject=subject,
                    end=when,
                    start=prev_end,
                )
            )
            prev_end = when
        prev_version = version if prev_version is None else max(prev_version, version)
    return chapters


def assign_events(chapters: list[Chapter], events: list[UsageEvent], head: Chapter | None) -> None:
    buckets = chapters + ([head] if head else [])
    for event in events:
        for ch in buckets:
            lower_ok = ch.start is None or event.when > ch.start
            upper_ok = event.when <= ch.end
            if lower_ok and upper_ok:
                ch.events.append(event)
                break


def _coverage_status(ch: Chapter, csv_min: datetime, csv_max: datetime) -> str:
    lo = ch.start or datetime.min.replace(tzinfo=timezone.utc)
    if ch.end < csv_min or lo > csv_max:
        return "keine Daten"
    if lo >= csv_min and ch.end <= csv_max:
        return "voll"
    return "teilweise"


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def build_report(chapters: list[Chapter], csv_min: datetime, csv_max: datetime) -> str:
    header = (
        f"{'Kapitel':<9} {'Commit':<8} {'Ende (lokal)':<17} "
        f"{'Events':>7} {'Total Tok':>14} {'Tok o.Cache':>14} {'Kosten EUR':>11} {'Abdeckung':<11}"
    )
    lines = [header, "-" * len(header)]
    for ch in sorted(chapters, key=lambda c: c.end, reverse=True):
        total = sum(e.total_tokens for e in ch.events)
        ex_cache = sum(e.total_tokens - e.cache_read for e in ch.events)
        cost = sum(e.cost_eur for e in ch.events)
        local_end = ch.end.astimezone().strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"{ch.version:<9} {ch.commit:<8} {local_end:<17} "
            f"{len(ch.events):>7} {_fmt_int(total):>14} {_fmt_int(ex_cache):>14} "
            f"{cost:>11.2f} {_coverage_status(ch, csv_min, csv_max):<11}"
        )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    repo = Path(args.repo).resolve()
    events = read_usage_events(Path(args.usage_csv))
    csv_min = min(e.when for e in events)
    csv_max = max(e.when for e in events)

    version_commits = collect_version_commits(repo)
    if not version_commits:
        raise RuntimeError("Keine version.py-Commits gefunden - falsches Repo?")
    chapters = detect_chapters(version_commits)

    head: Chapter | None = None
    if args.include_head:
        latest = chapters[-1] if chapters else None
        if latest and csv_max > latest.end:
            head = Chapter(
                version="offen",
                commit="HEAD",
                subject="(nach letztem Minor-Bump)",
                end=csv_max,
                start=latest.end,
            )

    assign_events(chapters, events, head)
    report_chapters = chapters + ([head] if head else [])

    print(build_report(report_chapters, csv_min, csv_max))
    print()
    print(
        f"CSV-Abdeckung: {csv_min.astimezone():%Y-%m-%d %H:%M} "
        f"bis {csv_max.astimezone():%Y-%m-%d %H:%M} (lokal), {len(events)} Events."
    )
    print(
        "Hinweis: zeitbasierte Zuordnung (kein Chat-ID im Export). "
        "'Tok o.Cache' = Total minus Cache-Read."
    )

    head_time = latest_commit_time(repo)
    if head_time and head_time > csv_max:
        delta_h = (head_time - csv_max).total_seconds() / 3600
        print(
            f"ACHTUNG: Neuere Commits ({head_time.astimezone():%Y-%m-%d %H:%M} lokal, "
            f"+{delta_h:.1f} h) liegen NACH dem CSV-Ende - bitte frischen Usage-Export "
            "aus dem Cursor-Dashboard laden."
        )


if __name__ == "__main__":
    main()
