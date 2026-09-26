#!/usr/bin/env python3
"""
ha_addon_smoke.py — Supervisor-free start test for a published HA add-on image.

Pre-gate check in release-publish.yml (runs before the manual release approval):
starts ``ghcr.io/jochentcc/earnie-addon-{arch}:<version>`` the way the Supervisor
would (``/data/options.json`` + ``addon_config`` on ``/config``, no
SUPERVISOR_TOKEN → Streamlit directly on :8501) and fails if

  - the container exits before Streamlit is healthy (e.g. missing module),
  - ``/_stcore/health`` does not answer within ``--timeout``,
  - ``config.json`` is not seeded under ``/config`` (addon_config path), or
    lands in the legacy ``/data/earnie_env/config`` instead,
  - the container dies shortly after becoming healthy.

Usage (needs Docker; stdlib only):
  python -m scripts.ha_addon_smoke --image ghcr.io/jochentcc/earnie-addon-amd64:2.6.0-alpha.7
  python -m scripts.ha_addon_smoke --image ... --platform linux/arm64 --timeout 600
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_CONFIG_YAML = REPO_ROOT / "packaging" / "homeassistant-addon" / "earnie" / "config.yaml"
CONTAINER_UI_PORT = 8501
LEGACY_CONFIG_JSON = Path("earnie_env") / "config" / "config.json"

_OPTION_LINE = re.compile(r"^  ([A-Za-z0-9_]+):\s*(.*?)\s*$")


def _parse_scalar(raw: str) -> object:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_default_options(config_yaml_text: str) -> dict[str, object]:
    """Flat ``options:`` block of an add-on config.yaml (scalars only, no PyYAML)."""
    options: dict[str, object] = {}
    in_block = False
    for line in config_yaml_text.splitlines():
        if not in_block:
            in_block = line.rstrip() == "options:"
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _OPTION_LINE.match(line)
        if match is None:
            break
        options[match.group(1)] = _parse_scalar(match.group(2))
    return options


def docker_run_command(
    *,
    image: str,
    name: str,
    platform: str | None,
    host_port: int,
    data_dir: Path,
    config_dir: Path,
) -> list[str]:
    cmd = ["docker", "run", "-d", "--name", name]
    if platform:
        cmd.extend(["--platform", platform])
    cmd.extend(
        [
            "-p",
            f"127.0.0.1:{host_port}:{CONTAINER_UI_PORT}",
            "-v",
            f"{data_dir}:/data",
            "-v",
            f"{config_dir}:/config",
            "-e",
            "OPENBLAS_NUM_THREADS=1",
            image,
        ]
    )
    return cmd


def check_seeded_config(data_dir: Path, config_dir: Path) -> list[str]:
    """Errors if config.json is not under addon_config /config (alpha.6 regression)."""
    errors: list[str] = []
    if not (config_dir / "config.json").is_file():
        errors.append("config.json not seeded under /config (addon_config)")
    if (data_dir / LEGACY_CONFIG_JSON).is_file():
        errors.append(f"config.json seeded under legacy /data/{LEGACY_CONFIG_JSON.as_posix()}")
    return errors


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # NOSONAR pythonsecurity:S8705 — fixed docker CLI args
        ["docker", *args], capture_output=True, text=True, check=False
    )


def _container_running(name: str) -> bool:
    result = _docker("inspect", "--format", "{{.State.Running}}", name)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _health_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _wait_healthy(name: str, url: str, timeout_sec: float) -> str | None:
    """None when healthy; otherwise an error message."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _container_running(name):
            return "container exited before Streamlit became healthy"
        if _health_ok(url):
            return None
        time.sleep(3.0)
    return f"Streamlit not healthy at {url} within {timeout_sec:.0f}s"


def run_smoke(
    *, image: str, platform: str | None, host_port: int, timeout_sec: float, settle_sec: float
) -> int:
    name = f"earnie-addon-smoke-{host_port}"
    work = Path(tempfile.mkdtemp(prefix="earnie-addon-smoke-"))
    data_dir = work / "data"
    config_dir = work / "config"
    data_dir.mkdir()
    config_dir.mkdir()
    options = parse_default_options(ADDON_CONFIG_YAML.read_text(encoding="utf-8"))
    (data_dir / "options.json").write_text(json.dumps(options), encoding="utf-8")
    print(f"ha-addon-smoke: {image} ({platform or 'native'}) options={options}")

    _docker("rm", "-f", name)
    cmd = docker_run_command(
        image=image,
        name=name,
        platform=platform,
        host_port=host_port,
        data_dir=data_dir,
        config_dir=config_dir,
    )
    print("+", " ".join(cmd))
    started = subprocess.run(cmd, check=False)  # NOSONAR pythonsecurity:S8705
    errors: list[str] = []
    try:
        if started.returncode != 0:
            errors.append(f"docker run failed (exit {started.returncode})")
        else:
            url = f"http://127.0.0.1:{host_port}/_stcore/health"
            failure = _wait_healthy(name, url, timeout_sec)
            if failure:
                errors.append(failure)
            else:
                print(f"ha-addon-smoke: healthy at {url}; settling {settle_sec:.0f}s")
                time.sleep(settle_sec)
                if not _container_running(name):
                    errors.append("container exited shortly after becoming healthy")
                errors.extend(check_seeded_config(data_dir, config_dir))
    finally:
        logs = _docker("logs", "--tail", "200", name)
        print("----- container logs (tail) -----")
        print(logs.stdout + logs.stderr)
        _docker("rm", "-f", name)
        shutil.rmtree(work, ignore_errors=True)

    if errors:
        for err in errors:
            print(f"ha-addon-smoke: FAIL — {err}", file=sys.stderr)
        return 1
    print("ha-addon-smoke: OK")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start test for an Earnie HA add-on image.")
    parser.add_argument("--image", required=True, help="e.g. ghcr.io/jochentcc/earnie-addon-amd64:<version>")
    parser.add_argument("--platform", help="docker --platform (e.g. linux/arm64 under QEMU)")
    parser.add_argument("--port", type=int, default=18501, help="host port for the UI (default 18501)")
    parser.add_argument("--timeout", type=float, default=240.0, help="seconds until healthy (default 240)")
    parser.add_argument("--settle", type=float, default=15.0, help="seconds to stay up after healthy")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_smoke(
        image=args.image,
        platform=args.platform,
        host_port=args.port,
        timeout_sec=args.timeout,
        settle_sec=args.settle,
    )


if __name__ == "__main__":
    raise SystemExit(main())
