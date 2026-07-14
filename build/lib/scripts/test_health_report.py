"""Test effectiveness metrics: JUnit history, coverage triage, legacy hints.

Typical workflow:
  # Weekly (or before release) — full metrics + report:
  .venv\\Scripts\\python.exe -m scripts.test_health_report run --coverage
  .venv\\Scripts\\python.exe -m scripts.test_health_report report

  # Pre-commit only ingests the last JUnit file (see .githooks/pre-commit).

  # Optional mutation spike (pip install -e \".[mutation]\"):
  mutmut run
  mutmut html
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = ROOT / ".pytest_cache" / "test-metrics"
JUNIT_HISTORY = METRICS_DIR / "junit-history"
JUNIT_LAST = METRICS_DIR / "junit-last.xml"
COVERAGE_XML = METRICS_DIR / "coverage.xml"
STATS_PATH = METRICS_DIR / "stats.json"
REPORT_PATH = METRICS_DIR / "health-report.md"

PROTECTED_TEST_FILES = frozenset(
    {
        "test_prod_dump_regression.py",
        "test_historical_24h_consistency.py",
        "test_deviation_scenario_catalog.py",
        "test_deviation_eval.py",
    }
)

LEGACY_TEST_SYMBOLS = (
    "subtract_consumer_ids",
    "swimspa_filter",
    "legacy_id",
    "_raw_config.get(\"swimspa\")",
    "get_swimspa_settings",
    "ENERGY_OPTIMIZER_CONFIG_PATH",
)

COV_SOURCE_PACKAGES = (
    "optimizer",
    "data",
    "house_config",
    "simulation",
    "settings",
    "runtime_store",
)


@dataclass
class TestRunCounts:
    passed: int = 0
    failed: int = 0
    error: int = 0
    skipped: int = 0
    last_run_at: str | None = None
    last_failure_at: str | None = None

    @property
    def runs(self) -> int:
        return self.passed + self.failed + self.error + self.skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="pytest ausführen und Ergebnisse ingestieren")
    run_p.add_argument("--coverage", action="store_true", help="Coverage-XML erzeugen (wöchentlich)")
    run_p.add_argument("-q", action="store_true", help="pytest -q (Default)")

    ingest_p = sub.add_parser("ingest", help="Vorhandenes JUnit-XML in die Historie übernehmen")
    ingest_p.add_argument("--junit", default=str(JUNIT_LAST), help="Pfad zum JUnit-XML")

    report_p = sub.add_parser("report", help="Review-Kandidaten als Markdown schreiben")
    report_p.add_argument("--min-runs", type=int, default=5, help="Mindestanzahl Läufe für Triage")
    report_p.add_argument("--top", type=int, default=40, help="Max. Kandidaten in der Ausgabe")
    report_p.add_argument(
        "--output",
        default=str(REPORT_PATH),
        help="Zielpfad für health-report.md",
    )
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_metrics_dir() -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    JUNIT_HISTORY.mkdir(parents=True, exist_ok=True)


def _load_stats() -> dict:
    if not STATS_PATH.is_file():
        return {"runs": 0, "tests": {}}
    return json.loads(STATS_PATH.read_text(encoding="utf-8"))


def _save_stats(stats: dict) -> None:
    _ensure_metrics_dir()
    STATS_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")


def _nodeid_from_junit(classname: str, name: str) -> str:
    if classname.startswith("tests."):
        rel = classname[len("tests.") :].replace(".", "/")
        path = f"tests/{rel}.py"
    else:
        path = f"tests/{classname.replace('.', '/')}.py"
    return f"{path}::{name}"


def _parse_junit_cases(xml_path: Path) -> dict[str, str]:
    """nodeid -> outcome (passed|failed|error|skipped)."""
    root = ET.parse(xml_path).getroot()
    cases: dict[str, str] = {}
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        nodeid = _nodeid_from_junit(classname, name)
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed" if case.find("failure") is not None else "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        cases[nodeid] = outcome
    return cases


def _case_to_counts() -> dict[str, TestRunCounts]:
    stats = _load_stats()
    result: dict[str, TestRunCounts] = {}
    for nodeid, raw in stats.get("tests", {}).items():
        result[nodeid] = TestRunCounts(
            passed=int(raw.get("passed", 0)),
            failed=int(raw.get("failed", 0)),
            error=int(raw.get("error", 0)),
            skipped=int(raw.get("skipped", 0)),
            last_run_at=raw.get("last_run_at"),
            last_failure_at=raw.get("last_failure_at"),
        )
    return result


def ingest_junit(xml_path: Path) -> int:
    """Archiviert JUnit und aktualisiert stats.json. Gibt Anzahl Testfälle zurück."""
    if not xml_path.is_file():
        raise FileNotFoundError(f"JUnit-XML fehlt: {xml_path}")

    _ensure_metrics_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = JUNIT_HISTORY / f"junit-{stamp}.xml"
    shutil.copy2(xml_path, archive)

    cases = _parse_junit_cases(xml_path)
    stats = _load_stats()
    stats["runs"] = int(stats.get("runs", 0)) + 1
    now = _utc_now()
    tests: dict = stats.setdefault("tests", {})

    for nodeid, outcome in cases.items():
        entry = tests.setdefault(
            nodeid,
            {
                "passed": 0,
                "failed": 0,
                "error": 0,
                "skipped": 0,
                "last_run_at": None,
                "last_failure_at": None,
            },
        )
        entry[outcome] = int(entry.get(outcome, 0)) + 1
        entry["last_run_at"] = now
        if outcome in ("failed", "error"):
            entry["last_failure_at"] = now

    _save_stats(stats)
    return len(cases)


def _pytest_command(*, with_coverage: bool, quiet: bool) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "tests"]
    if quiet:
        cmd.append("-q")
    cmd.append(f"--junitxml={JUNIT_LAST}")
    if with_coverage:
        cov_args = [f"--cov={pkg}" for pkg in COV_SOURCE_PACKAGES]
        cmd.extend(cov_args)
        cmd.append(f"--cov-report=xml:{COVERAGE_XML}")
    return cmd


def run_pytest(*, with_coverage: bool, quiet: bool = True) -> int:
    _ensure_metrics_dir()
    cmd = _pytest_command(with_coverage=with_coverage, quiet=quiet)
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if JUNIT_LAST.is_file():
        count = ingest_junit(JUNIT_LAST)
        print(f"test_health_report: {count} Testfälle ingestiert (stats.json).")
    return result.returncode


def _test_file_from_nodeid(nodeid: str) -> str:
    path_part = nodeid.split("::", 1)[0]
    return Path(path_part).name


def _is_protected(nodeid: str) -> bool:
    return _test_file_from_nodeid(nodeid) in PROTECTED_TEST_FILES


def _mock_density(test_path: Path) -> float:
    if not test_path.is_file():
        return 0.0
    text = test_path.read_text(encoding="utf-8", errors="replace")
    mocks = len(re.findall(r"\b(monkeypatch|Mock\(|patch\()", text))
    asserts = len(re.findall(r"\bassert\b", text))
    if asserts == 0:
        return float(mocks)
    return mocks / asserts


def _legacy_hits(test_path: Path) -> list[str]:
    if not test_path.is_file():
        return []
    text = test_path.read_text(encoding="utf-8", errors="replace")
    return [symbol for symbol in LEGACY_TEST_SYMBOLS if symbol in text]


def _module_coverage() -> dict[str, float]:
    if not COVERAGE_XML.is_file():
        return {}
    root = ET.parse(COVERAGE_XML).getroot()
    packages: dict[str, float] = {}
    for package in root.findall(".//package"):
        name = package.get("name", "")
        line_rate = float(package.get("line-rate", 0.0) or 0.0)
        packages[name] = round(line_rate * 100.0, 1)
    return packages


def _guess_modules_for_test(test_file: str) -> list[str]:
    stem = test_file.removeprefix("test_").removesuffix(".py")
    parts = stem.split("_")
    guesses: list[str] = []
    if parts:
        guesses.append(parts[0])
        if len(parts) >= 2:
            guesses.append(f"{parts[0]}_{parts[1]}")
    return guesses


def _related_coverage(test_file: str, module_cov: dict[str, float]) -> float | None:
    if not module_cov:
        return None
    for guess in _guess_modules_for_test(test_file):
        for pkg, pct in module_cov.items():
            if guess in pkg.replace(".", "_").replace("/", "_"):
                return pct
    return None


def _build_candidates(min_runs: int) -> list[dict]:
    stats = _load_stats()
    total_runs = int(stats.get("runs", 0))
    effective_min = min(min_runs, total_runs) if total_runs else min_runs
    module_cov = _module_coverage()
    candidates: list[dict] = []

    for nodeid, counts in _case_to_counts().items():
        if _is_protected(nodeid):
            continue
        if counts.failed + counts.error > 0:
            continue
        if counts.runs < effective_min:
            continue
        test_file = _test_file_from_nodeid(nodeid)
        test_path = ROOT / "tests" / test_file
        mock_density = _mock_density(test_path)
        legacy = _legacy_hits(test_path)
        cov_pct = _related_coverage(test_file, module_cov)
        score = 0
        reasons: list[str] = []
        if mock_density >= 1.5:
            score += 2
            reasons.append(f"mock-heavy ({mock_density:.1f} mocks/assert)")
        if cov_pct is not None and cov_pct < 30.0:
            score += 1
            reasons.append(f"low related coverage ({cov_pct:.0f}%)")
        if legacy:
            score += 2
            reasons.append(f"legacy symbols: {', '.join(legacy[:3])}")
        if counts.skipped == counts.runs:
            score += 3
            reasons.append("always skipped")
        if score == 0:
            continue
        candidates.append(
            {
                "nodeid": nodeid,
                "runs": counts.runs,
                "score": score,
                "reasons": reasons,
                "last_run_at": counts.last_run_at,
            }
        )

    candidates.sort(key=lambda item: (-item["score"], item["nodeid"]))
    return candidates


def write_report(*, min_runs: int, top: int, output: Path) -> Path:
    stats = _load_stats()
    candidates = _build_candidates(min_runs)[:top]
    module_cov = _module_coverage()
    lines = [
        "# Test health report",
        "",
        f"Generated: {_utc_now()}",
        f"Recorded pytest runs: {stats.get('runs', 0)}",
        f"Triage rule: never failed, ≥{min_runs} runs, not protected, heuristic flags.",
        "",
        "> Review queue only — never auto-delete tests from this list.",
        "",
    ]
    if module_cov:
        lines.append("## Package coverage (last `run --coverage`)")
        lines.append("")
        for pkg, pct in sorted(module_cov.items()):
            lines.append(f"- `{pkg}`: {pct:.1f}%")
        lines.append("")

    lines.extend(["## Review candidates", ""])
    if not candidates:
        lines.append("_No candidates with current thresholds._")
    else:
        lines.append("| Score | Runs | Test | Reasons |")
        lines.append("|------:|-----:|------|---------|")
        for item in candidates:
            reasons = "; ".join(item["reasons"])
            lines.append(f"| {item['score']} | {item['runs']} | `{item['nodeid']}` | {reasons} |")

    lines.extend(["", "## Protected tests (never auto-flagged)", ""])
    for name in sorted(PROTECTED_TEST_FILES):
        lines.append(f"- `{name}`")

    lines.extend(
        [
            "",
            "## Mutation testing (weekly)",
            "",
            "```powershell",
            "pip install -e \".[mutation]\"",
            "mutmut run",
            "mutmut results",
            "mutmut html",
            "```",
            "",
        ]
    )

    _ensure_metrics_dir()
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"test_health_report: {output}")
    return output


def main() -> int:
    args = parse_args()
    if args.command == "run":
        return run_pytest(with_coverage=args.coverage, quiet=args.q or not args.coverage)
    if args.command == "ingest":
        ingest_junit(Path(args.junit))
        print(f"test_health_report: ingest OK ({args.junit})")
        return 0
    if args.command == "report":
        write_report(min_runs=args.min_runs, top=args.top, output=Path(args.output))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
