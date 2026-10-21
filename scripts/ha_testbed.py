"""Drive the HA contract testbed container (HA Testbed P3).

  python -m scripts.ha_testbed up [--with-earnie]
  python -m scripts.ha_testbed install
  python -m scripts.ha_testbed status
  python -m scripts.ha_testbed down
  python -m scripts.ha_testbed reset --yes [--all]

Inputs for HA come from ``scripts.ha_testbed_build --out <testbed>/homeassistant``.
HA onboarding and adding the *Earnie House Simulator* integration stay manual
(plan § WP5; the optional REST automation is not implemented).
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker" / "compose" / "ha-sim-testbed.yml"
DEFAULT_TESTBED_DIR = REPO_ROOT / "ha_lab" / "testbed"
INTEGRATION_SRC = (
    REPO_ROOT / "house_sim" / "ha_integration" / "custom_components" / "earnie_house_sim"
)
HA_CONTAINER = "earnie_testbed_ha"
PACKAGES_LINE = "packages: !include_dir_named packages"
ARCHETYPES_RELPATH = Path("earnie_house_sim") / "archetypes"

Runner = Callable[[Sequence[str], dict[str, str]], int]


def _run(cmd: Sequence[str], env: dict[str, str]) -> int:
    return subprocess.run(list(cmd), cwd=REPO_ROOT, env=env, check=False).returncode


def _compose_cmd(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(REPO_ROOT),
        "-f",
        str(COMPOSE_FILE),
        *args,
    ]


def _env(testbed_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["TESTBED_DIR"] = str(testbed_dir)
    return env


def ha_dir(testbed_dir: Path) -> Path:
    return testbed_dir / "homeassistant"


def patch_configuration(text: str) -> tuple[str, bool]:
    """Ensure ``homeassistant: packages: !include_dir_named packages``; returns (text, changed).

    Raises ``ValueError`` when ``packages`` is already set to something else.
    """
    lines = text.splitlines()
    ha_idx = next((i for i, ln in enumerate(lines) if ln.rstrip() == "homeassistant:"), None)
    if ha_idx is None:
        if any(ln.strip().startswith("packages:") for ln in lines):
            raise ValueError(
                "configuration.yaml has 'packages:' outside a plain 'homeassistant:' block"
            )
        body = text.rstrip("\n")
        return (body + "\n\n" if body else "") + f"homeassistant:\n  {PACKAGES_LINE}\n", True
    end = len(lines)
    for i in range(ha_idx + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith((" ", "\t", "#")):
            end = i
            break
    for ln in lines[ha_idx + 1 : end]:
        if ln.strip().startswith("packages:"):
            if ln.strip() == PACKAGES_LINE:
                return text, False
            raise ValueError(
                f"configuration.yaml already sets {ln.strip()!r}; "
                f"set it to '{PACKAGES_LINE}' by hand or merge the packages directory"
            )
    lines.insert(ha_idx + 1, f"  {PACKAGES_LINE}")
    return "\n".join(lines) + "\n", True


def cmd_up(testbed_dir: Path, *, with_earnie: bool, run: Runner) -> int:
    for sub in ("homeassistant", "config", "runtime"):
        (testbed_dir / sub).mkdir(parents=True, exist_ok=True)
    profile = ["--profile", "earnie"] if with_earnie else []
    build = ["--build"] if with_earnie else []
    return run(_compose_cmd(*profile, "up", "-d", *build), _env(testbed_dir))


def cmd_down(testbed_dir: Path, *, run: Runner) -> int:
    return run(_compose_cmd("--profile", "earnie", "down"), _env(testbed_dir))


def cmd_install(testbed_dir: Path, *, run: Runner, restart: bool = True) -> int:
    if not INTEGRATION_SRC.is_dir():
        raise FileNotFoundError(f"integration source missing: {INTEGRATION_SRC}")
    root = ha_dir(testbed_dir)
    config = root / "configuration.yaml"
    # Validate the existing config before touching anything.
    original = config.read_text(encoding="utf-8") if config.is_file() else "default_config:\n"
    patched, changed = patch_configuration(original)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "custom_components" / "earnie_house_sim"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(INTEGRATION_SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if changed or not config.is_file():
        config.write_text(patched, encoding="utf-8")
    print(f"integration -> {dest}")
    print(f"configuration.yaml: {'patched' if changed else 'already has the packages include'}")
    if not (root / "packages" / "earnie_ha_carrier.yaml").is_file():
        print(
            "note: packages/earnie_ha_carrier.yaml missing - run scripts.ha_testbed_build first",
            file=sys.stderr,
        )
    if restart:
        env = _env(testbed_dir)
        if run(["docker", "inspect", "-f", "{{.State.Running}}", HA_CONTAINER], env) == 0:
            return run(["docker", "restart", HA_CONTAINER], env)
        print(f"{HA_CONTAINER} is not running - 'up' starts it with the new files")
    return 0


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def status_report(
    testbed_dir: Path, *, port_open: Callable[[int], bool] = _port_open
) -> list[tuple[str, bool, str]]:
    root = ha_dir(testbed_dir)
    config = root / "configuration.yaml"
    archetypes = root / ARCHETYPES_RELPATH
    names = sorted(p.name for p in archetypes.iterdir() if p.is_dir()) if archetypes.is_dir() else []
    manifest = root / "custom_components" / "earnie_house_sim" / "manifest.json"
    return [
        ("integration installed", manifest.is_file(), ""),
        (
            "configuration.yaml packages include",
            config.is_file() and PACKAGES_LINE in config.read_text(encoding="utf-8"),
            "",
        ),
        ("carrier package", (root / "packages" / "earnie_ha_carrier.yaml").is_file(), ""),
        ("generated archetypes", bool(names), ", ".join(names)),
        ("HA reachable :8123", port_open(8123), ""),
        ("Earnie daemon reachable :8541", port_open(8541), "needs --with-earnie or a native Earnie"),
    ]


def cmd_status(testbed_dir: Path, *, run: Runner) -> int:
    print(f"testbed dir: {testbed_dir}")
    for label, ok, note in status_report(testbed_dir):
        print(f"  [{'ok' if ok else '--'}] {label}{(' - ' + note) if note else ''}")
    run(_compose_cmd("--profile", "earnie", "ps"), _env(testbed_dir))
    return 0


def _clear_dir(path: Path) -> None:
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def cmd_reset(testbed_dir: Path, *, wipe_all: bool, run: Runner) -> int:
    code = cmd_down(testbed_dir, run=run)
    if code != 0:
        print("docker compose down failed - not deleting data", file=sys.stderr)
        return code
    for sub in ["homeassistant"] + (["config", "runtime"] if wipe_all else []):
        _clear_dir(testbed_dir / sub)
        print(f"cleared {testbed_dir / sub}")
    return 0


def main(argv: list[str] | None = None, *, run: Runner = _run) -> int:
    parser = argparse.ArgumentParser(description="HA contract testbed (HA Testbed P3)")
    parser.add_argument("--testbed-dir", type=Path, default=DEFAULT_TESTBED_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    p_up = sub.add_parser("up", help="start HA (and Earnie with --with-earnie)")
    p_up.add_argument("--with-earnie", action="store_true")
    sub.add_parser("down", help="stop and remove the containers")
    sub.add_parser("install", help="copy the sim integration, patch configuration.yaml, restart HA")
    sub.add_parser("status", help="show what is installed and reachable")
    p_reset = sub.add_parser("reset", help="stop and delete HA state (factory reset)")
    p_reset.add_argument("--yes", action="store_true", help="confirm the deletion")
    p_reset.add_argument("--all", action="store_true", help="also delete the Earnie config/runtime dirs")
    args = parser.parse_args(argv)
    testbed_dir = args.testbed_dir.resolve()
    try:
        if args.command == "up":
            return cmd_up(testbed_dir, with_earnie=args.with_earnie, run=run)
        if args.command == "down":
            return cmd_down(testbed_dir, run=run)
        if args.command == "install":
            return cmd_install(testbed_dir, run=run)
        if args.command == "status":
            return cmd_status(testbed_dir, run=run)
        if not args.yes:
            print("error: reset deletes the HA state; pass --yes", file=sys.stderr)
            return 2
        return cmd_reset(testbed_dir, wipe_all=args.all, run=run)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
