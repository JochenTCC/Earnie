"""Container preflight (H0/H1) and HEALTHCHECK contracts (2.6.m)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PREFLIGHT = _ROOT / "docker" / "preflight.sh"
_ENTRYPOINT = _ROOT / "docker" / "entrypoint.sh"
_DOCKERFILE = _ROOT / "docker" / "Dockerfile"
_HEALTHCHECK_SH = _ROOT / "docker" / "healthcheck.sh"
_RUN_SH = _ROOT / "packaging" / "homeassistant-addon" / "earnie" / "run.sh"
_DOCS_URL = "https://example.invalid/docs#cpu"

# Real flag sets: QEMU kvm64 model (no SSE4.x/POPCNT) vs. a modern host CPU.
_KVM64_FLAGS = (
    "fpu de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush "
    "mmx fxsr sse sse2 syscall nx lm rep_good nopl cpuid pni cx16 hypervisor lahf_lm"
)
_HOST_FLAGS = (
    "fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush "
    "mmx fxsr sse sse2 ht syscall nx lm pni pclmulqdq ssse3 fma cx16 sse4_1 sse4_2 "
    "movbe popcnt aes xsave avx f16c rdrand hypervisor lahf_lm abm avx2"
)

_SH = shutil.which("sh")


def _run_cpu_check(tmp_path: Path, arch: str, flags: str | None) -> subprocess.CompletedProcess[str]:
    cpuinfo = tmp_path / "cpuinfo"
    if flags is not None:
        cpuinfo.write_text(f"processor\t: 0\nflags\t\t: {flags}\n", encoding="utf-8")
    script = (
        f'. "{_PREFLIGHT.as_posix()}"\n'
        f'_check_x86_64_v2 "{arch}" "{cpuinfo.as_posix()}" "{_DOCS_URL}"\n'
    )
    return subprocess.run([_SH, "-c", script], capture_output=True, text=True, check=False)


def _run_preflight_env(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text(f"processor\t: 0\nflags\t\t: {_HOST_FLAGS}\n", encoding="utf-8")
    merged = os.environ.copy()
    merged.update(env)
    merged["EARNIE_CPUINFO_FILE"] = str(cpuinfo)
    script = (
        f'. "{_PREFLIGHT.as_posix()}"\n'
        f'run_preflight "x86_64" "{cpuinfo.as_posix()}" "{_DOCS_URL}"\n'
    )
    return subprocess.run(
        [_SH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=merged,
        cwd=str(tmp_path),
    )


def test_entrypoint_runs_preflight_before_bootstrap() -> None:
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    call = 'run_preflight "$(uname -m)" "${EARNIE_CPUINFO_FILE:-/proc/cpuinfo}"'
    assert ". /app/docker/preflight.sh" in text
    assert call in text
    assert "|| exit 1" in text
    assert text.index(call) < text.index("python -m scripts.bootstrap_runtime")
    assert "container.md#cpu-voraussetzung-amd64" in text


def test_dockerfile_strips_crlf_and_healthcheck() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert "docker/preflight.sh" in text
    assert "docker/healthcheck.sh" in text
    assert "ARG BUILD_DATE=" in text
    assert "docker/BUILD_DATE" in text
    assert "HEALTHCHECK" in text
    assert "docker/healthcheck.sh" in text


def test_healthcheck_sh_invokes_python_module() -> None:
    text = _HEALTHCHECK_SH.read_text(encoding="utf-8")
    assert "scripts.container_healthcheck" in text


def test_addon_points_cpu_hint_at_addon_docs() -> None:
    text = _RUN_SH.read_text(encoding="utf-8")
    export = "export EARNIE_CPU_CHECK_DOCS_URL="
    assert export in text
    assert "homeassistant-addon.md#voraussetzungen-gono-go" in text
    assert text.index(export) < text.index("exec /bin/sh docker/entrypoint.sh")
    assert "preflight.sh" in text


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_kvm64_cpu_fails_with_actionable_message(tmp_path: Path) -> None:
    result = _run_cpu_check(tmp_path, "x86_64", _KVM64_FLAGS)
    assert result.returncode == 1
    assert "x86-64-v2" in result.stderr
    assert "popcnt" in result.stderr and "sse4_2" in result.stderr
    assert '"host"' in result.stderr
    assert _DOCS_URL in result.stderr


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_modern_cpu_passes(tmp_path: Path) -> None:
    result = _run_cpu_check(tmp_path, "x86_64", _HOST_FLAGS)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
@pytest.mark.parametrize(("arch", "flags"), [("aarch64", _KVM64_FLAGS), ("x86_64", None)])
def test_non_x86_or_unreadable_cpuinfo_is_skipped(
    tmp_path: Path, arch: str, flags: str | None
) -> None:
    assert _run_cpu_check(tmp_path, arch, flags).returncode == 0


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_writable_dirs_pass(tmp_path: Path) -> None:
    config = tmp_path / "config"
    runtime = tmp_path / "runtime"
    config.mkdir()
    runtime.mkdir()
    result = _run_preflight_env(
        tmp_path,
        {
            "EARNIE_CONFIG_PATH": str(config),
            "EARNIE_RUNTIME_PATH": str(runtime),
            "EARNIE_BUILD_DATE_FILE": str(tmp_path / "missing_build_date"),
        },
    )
    assert result.returncode == 0


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_writable_dirs_fail_on_readonly(tmp_path: Path) -> None:
    config = tmp_path / "config"
    runtime = tmp_path / "runtime"
    config.mkdir()
    runtime.mkdir()
    runtime.chmod(0o555)
    try:
        if os.access(runtime, os.W_OK):
            pytest.skip("filesystem ignores chmod write bits (e.g. Windows)")
        result = _run_preflight_env(
            tmp_path,
            {
                "EARNIE_CONFIG_PATH": str(config),
                "EARNIE_RUNTIME_PATH": str(runtime),
                "EARNIE_BUILD_DATE_FILE": str(tmp_path / "missing_build_date"),
            },
        )
        assert result.returncode == 1
        assert "nicht beschreibbar" in result.stderr or "nicht anlegbar" in result.stderr
    finally:
        runtime.chmod(0o755)


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_clock_before_build_date_aborts(tmp_path: Path) -> None:
    config = tmp_path / "config"
    runtime = tmp_path / "runtime"
    config.mkdir()
    runtime.mkdir()
    build_date = tmp_path / "BUILD_DATE"
    # Far future — system clock cannot catch up.
    build_date.write_text("2099-01-01T00:00:00Z", encoding="utf-8")
    result = _run_preflight_env(
        tmp_path,
        {
            "EARNIE_CONFIG_PATH": str(config),
            "EARNIE_RUNTIME_PATH": str(runtime),
            "EARNIE_BUILD_DATE_FILE": str(build_date),
            "EARNIE_PREFLIGHT_CLOCK_WAIT_SEC": "0",
        },
    )
    assert result.returncode == 1
    assert "Systemuhr" in result.stderr


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_clock_ok_when_build_date_in_past(tmp_path: Path) -> None:
    config = tmp_path / "config"
    runtime = tmp_path / "runtime"
    config.mkdir()
    runtime.mkdir()
    build_date = tmp_path / "BUILD_DATE"
    build_date.write_text("2020-01-01T00:00:00Z", encoding="utf-8")
    result = _run_preflight_env(
        tmp_path,
        {
            "EARNIE_CONFIG_PATH": str(config),
            "EARNIE_RUNTIME_PATH": str(runtime),
            "EARNIE_BUILD_DATE_FILE": str(build_date),
            "EARNIE_PREFLIGHT_CLOCK_WAIT_SEC": "0",
        },
    )
    assert result.returncode == 0
