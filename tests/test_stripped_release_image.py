"""Release image without dev-only replay tools and the Shadow client.

``.dockerignore`` leaves out the offline replay / regression tools and the Shadow
client (``runtime_store/shadow/hooks.py`` ``CLIENT_FILES``). These tests check
that the shipped code does not import them and that Prod starts without them.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from runtime_store.shadow.hooks import CLIENT_FILES

REPO_ROOT = Path(__file__).resolve().parents[1]

# Leaf modules only imported by scripts and tests.
DEV_TOOL_FILES = (
    "runtime_store/recorder_replay.py",
    "scripts/run_regression.py",
    "scripts/run_regression_r0_study.py",
    "scripts/replay_debug_dump.py",
)
EXCLUDED_FILES = DEV_TOOL_FILES + CLIENT_FILES

# Directories and files that docker/Dockerfile copies into the image.
IMAGE_DIRS = (
    "optimizer",
    "data",
    "integrations",
    "runtime_store",
    "ui",
    "simulation",
    "scripts",
    "docker",
    "house_config",
    "settings",
    "ehal",
    "opendata",
)
IMAGE_TOP_FILES = ("logger_config.py", "app.py", "main.py", "config.py", "version.py")

# Shadow-only UI module: may be imported lazily inside an ``is_shadow_mode()`` branch.
LAZY_ONLY = {"ui.shadow_banner"}


def _module_name(rel: str) -> str:
    return rel[: -len(".py")].replace("/", ".")


EXCLUDED_MODULES = {_module_name(f) for f in EXCLUDED_FILES}


def _dockerignore_lines() -> set[str]:
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    return {ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")}


def _shipped_files() -> list[str]:
    out = [f for f in IMAGE_TOP_FILES if (REPO_ROOT / f).is_file()]
    for top in IMAGE_DIRS:
        for path in (REPO_ROOT / top).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" in rel or rel in EXCLUDED_FILES:
                continue
            out.append(rel)
    return sorted(out)


def _imported_modules(tree: ast.AST) -> list[tuple[str, bool]]:
    """(module, is_module_level) for every import; ``from a import b`` yields a and a.b."""
    found: list[tuple[str, bool]] = []
    top_level = {id(node) for node in getattr(tree, "body", [])}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, id(node) in top_level))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module, id(node) in top_level))
            for alias in node.names:
                found.append((f"{node.module}.{alias.name}", id(node) in top_level))
    return found


def test_excluded_files_exist_and_are_in_dockerignore():
    ignored = _dockerignore_lines()
    for rel in EXCLUDED_FILES:
        assert (REPO_ROOT / rel).is_file(), rel
        assert rel in ignored, f"{rel} missing in .dockerignore"


def test_push_read_replay_stays_in_image():
    """The live push inbox uses its capture."""
    assert "runtime_store/push_read_replay.py" not in _dockerignore_lines()


def test_shipped_code_does_not_import_excluded_modules():
    violations: list[str] = []
    for rel in _shipped_files():
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
        for module, module_level in _imported_modules(tree):
            if module not in EXCLUDED_MODULES:
                continue
            if module in LAZY_ONLY and not module_level:
                continue
            violations.append(f"{rel}: {module}")
    assert not violations, (
        "Shipped code imports modules left out of the release image "
        "(use runtime_store.shadow.hooks):\n" + "\n".join(violations)
    )


_BLOCKER = r"""
import importlib.abc, sys

BLOCKED = set(sys.argv[1].split(","))

class _Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r} (stripped image)", name=name)
        return None

sys.meta_path.insert(0, _Blocker())
"""

_PROD_IMPORTS = r"""
import importlib, pkgutil

import config, main  # noqa: E401  (entry points first, like a real start)
import integrations.loxone_structure  # noqa: F401  (loxone_mcp_probe alone is a circular import)

for pkg in ("runtime_store", "integrations", "data", "optimizer", "house_config", "settings", "ehal"):
    mod = importlib.import_module(pkg)
    for info in pkgutil.walk_packages(mod.__path__, pkg + "."):
        if info.name in BLOCKED:
            continue
        importlib.import_module(info.name)

from runtime_store.shadow import hooks
assert hooks.client_available() is False
assert hooks.refuse_shadow_startup_or_exit() == {}
assert hooks.shadow_migration_mode_refusal(None) is None
assert hooks.block_write_if_shadow(backend="x", target="t", value=1) is False
hooks.assert_not_shadow_backend("probe")
assert hooks.lookup_record("loxone:io:x") is None
assert hooks.maybe_clear_auth_gate() is False
assert hooks.prepare_shadow_cycle("quarter", optimize_trigger="opt").skipped is False
assert hooks.resolve_next_trigger(None, "quarter", optimize_trigger="opt") == "quarter"
assert hooks.should_invoke_setpoint_writes(silent=False) is True
print("PROD_OK")
"""

_SHADOW_REFUSE = r"""
from runtime_store.shadow import hooks
assert hooks.shadow_migration_mode_refusal(None) == hooks.CLIENT_MISSING_MESSAGE
hooks.refuse_shadow_startup_or_exit()
"""


def _run_stripped(body: str, *, shadow: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("EARNIE_SHADOW", None)
    if shadow:
        env["EARNIE_SHADOW"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + body, ",".join(sorted(EXCLUDED_MODULES))],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )


def test_prod_imports_and_hooks_work_without_excluded_modules():
    proc = _run_stripped(_PROD_IMPORTS, shadow=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PROD_OK" in proc.stdout


def test_shadow_without_client_refuses_to_start():
    proc = _run_stripped(_SHADOW_REFUSE, shadow=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "nicht enthalten" in proc.stdout
