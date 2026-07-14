#!/usr/bin/env python3
"""
Greenfield Docker stack smoke test — Earnie rename / compose verification.

Prepares greenfield/config + greenfield/runtime, starts docker-compose-greenfield.yml,
and checks container names, bootstrap files, worker log, and Streamlit on :8502.

Usage:
  python -m scripts.smoke_greenfield_docker --prepare-only
  python -m scripts.smoke_greenfield_docker
  python -m scripts.smoke_greenfield_docker --reset
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose-greenfield.yml"
GREENFIELD_ROOT = REPO_ROOT / "greenfield"
CONFIG_DIR = GREENFIELD_ROOT / "config"
RUNTIME_DIR = GREENFIELD_ROOT / "runtime"

WORKER_CONTAINER = "earnie-greenfield-worker"
UI_CONTAINER = "earnie-greenfield-ui"
UI_HOST_PORT = 8502

REQUIRED_CONFIG_FILES = (
    "config.json",
    ".env",
    "house_profiles.json",
    "tariffs.json",
    "backtesting_scenarios.json",
)
REQUIRED_RUNTIME_FILES = (
    "local_settings.json",
    "cons_data_hourly.csv",
)

LOG_OK_MARKERS = (
    "Logging-System initialisiert",
    "Earnie Live-Abfrage gestartet",
    "Loxone-Startup-Prüfung übersprungen",
    "Loxone-Zugangsdaten noch nicht hinterlegt",
)
LOG_FATAL_MARKERS = (
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "ImportError:",
)


def ensure_greenfield_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def reset_greenfield_volumes(*, compose_down: bool = True) -> None:
    if compose_down and COMPOSE_FILE.is_file():
        _run_compose("down", check=False)
    for path in (CONFIG_DIR, RUNTIME_DIR):
        if path.exists():
            shutil.rmtree(path)
    ensure_greenfield_dirs()


def _run_compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    print("+", " ".join(cmd))
    try:
        return subprocess.run(cmd, cwd=REPO_ROOT, check=check, text=True)
    except subprocess.CalledProcessError as exc:
        print(
            f"FEHLER: docker compose exit {exc.returncode}. "
            "Bei Build-Fehlern: gültige SemVer in version.py prüfen (z. B. 2.0.0).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def container_running(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def wait_for_containers(
    names: tuple[str, ...],
    *,
    timeout_sec: float,
    poll_sec: float = 2.0,
) -> list[str]:
    deadline = time.monotonic() + timeout_sec
    pending = set(names)
    while pending and time.monotonic() < deadline:
        for name in tuple(pending):
            if container_running(name):
                pending.discard(name)
        if pending:
            time.sleep(poll_sec)
    return sorted(pending)


def fetch_container_logs(name: str, *, tail: int = 80) -> str:
    result = subprocess.run(
        ["docker", "logs", "--tail", str(tail), name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "") + (result.stderr or "")


def bootstrap_missing_paths(config_dir: Path, runtime_dir: Path) -> list[str]:
    missing: list[str] = []
    for filename in REQUIRED_CONFIG_FILES:
        if not (config_dir / filename).is_file():
            missing.append(f"config/{filename}")
    for filename in REQUIRED_RUNTIME_FILES:
        if not (runtime_dir / filename).is_file():
            missing.append(f"runtime/{filename}")
    return missing


def logs_indicate_healthy_worker(log_text: str) -> tuple[bool, str]:
    if any(marker in log_text for marker in LOG_FATAL_MARKERS):
        return False, "Worker-Log enthält Python-Traceback/Import-Fehler"
    if any(marker in log_text for marker in LOG_OK_MARKERS):
        return True, "Worker-Log enthält erwarteten Start-Marker"
    return False, "Worker-Log ohne erwarteten Start-Marker (noch kein Bootstrap?)"


def wait_for_worker_healthy(
    *,
    timeout_sec: float,
    poll_sec: float = 3.0,
) -> tuple[bool, str, str]:
    deadline = time.monotonic() + timeout_sec
    last_log = ""
    while time.monotonic() < deadline:
        last_log = fetch_container_logs(WORKER_CONTAINER, tail=120)
        healthy, detail = logs_indicate_healthy_worker(last_log)
        if healthy:
            return True, detail, last_log
        if any(marker in last_log for marker in LOG_FATAL_MARKERS):
            return False, "Worker-Log enthält Python-Traceback/Import-Fehler", last_log
        time.sleep(poll_sec)
    healthy, detail = logs_indicate_healthy_worker(last_log)
    return healthy, detail, last_log


def streamlit_reachable(port: int, *, timeout_sec: float = 3.0) -> bool:
    url = f"http://127.0.0.1:{port}/"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def validate_greenfield_config(config_path: Path) -> tuple[bool, str]:
    if not config_path.is_file():
        return False, "config.json fehlt"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"config.json ungültig: {exc}"
    if payload.get("runtime_settings") is not None:
        return False, "runtime_settings in config.json ist entfernt (2.0 P2)"
    live_id = str(payload.get("live_scenario_id", "live") or "live").strip()
    scenarios_path = config_path.parent / "backtesting_scenarios.json"
    if not scenarios_path.is_file():
        return False, "backtesting_scenarios.json fehlt"
    try:
        scenarios_doc = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"backtesting_scenarios.json ungültig: {exc}"
    scenario_ids = {
        str(entry.get("id", "")).strip()
        for entry in scenarios_doc.get("scenarios", [])
        if isinstance(entry, dict)
    }
    if live_id not in scenario_ids:
        return False, f"Live-Szenario '{live_id}' fehlt in backtesting_scenarios.json"
    return True, f"config.json live_scenario_id={live_id!r}"


def run_smoke(
    *,
    build: bool,
    reset: bool,
    timeout_sec: float,
) -> int:
    if shutil.which("docker") is None:
        print("FEHLER: docker nicht im PATH.", file=sys.stderr)
        return 2
    if not COMPOSE_FILE.is_file():
        print(f"FEHLER: {COMPOSE_FILE} fehlt.", file=sys.stderr)
        return 2

    if reset:
        print("Greenfield-Volumes zurücksetzen …")
        reset_greenfield_volumes()
    else:
        ensure_greenfield_dirs()

    up_args = ["up", "-d"]
    if build:
        up_args.append("--build")
    _run_compose(*up_args)

    still_down = wait_for_containers(
        (WORKER_CONTAINER, UI_CONTAINER),
        timeout_sec=timeout_sec,
    )
    if still_down:
        print(f"FEHLER: Container nicht running: {', '.join(still_down)}", file=sys.stderr)
        return 1

    missing = bootstrap_missing_paths(CONFIG_DIR, RUNTIME_DIR)
    if missing:
        print(f"FEHLER: Bootstrap-Dateien fehlen: {', '.join(missing)}", file=sys.stderr)
        return 1

    ok, detail = validate_greenfield_config(CONFIG_DIR / "config.json")
    if not ok:
        print(f"FEHLER: {detail}", file=sys.stderr)
        return 1
    print(f"OK: {detail}")

    healthy, log_detail, worker_log = wait_for_worker_healthy(timeout_sec=min(90.0, timeout_sec))
    if not healthy:
        print(f"FEHLER: {log_detail}", file=sys.stderr)
        print("--- worker log (tail) ---", file=sys.stderr)
        print(worker_log[-4000:], file=sys.stderr)
        return 1
    print(f"OK: {log_detail}")

    if not streamlit_reachable(UI_HOST_PORT):
        print(
            f"FEHLER: Streamlit nicht erreichbar unter http://localhost:{UI_HOST_PORT}/",
            file=sys.stderr,
        )
        return 1
    print(f"OK: Streamlit antwortet auf http://localhost:{UI_HOST_PORT}/")

    print(
        f"\nGreenfield smoke test passed — {WORKER_CONTAINER}, {UI_CONTAINER}, port {UI_HOST_PORT}."
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Greenfield Docker smoke test (earnie-greenfield-* containers)."
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Nur greenfield/config und greenfield/runtime anlegen, kein Docker.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Stack stoppen, greenfield/ leeren, neu starten.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="docker compose up ohne --build (schneller wenn Image aktuell).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Sekunden bis beide Container running sein müssen (Standard: 120).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.prepare_only:
        ensure_greenfield_dirs()
        print(f"Vorbereitet: {CONFIG_DIR} und {RUNTIME_DIR}")
        print("Start: python -m scripts.smoke_greenfield_docker")
        return 0
    return run_smoke(
        build=not args.no_build,
        reset=args.reset,
        timeout_sec=args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
