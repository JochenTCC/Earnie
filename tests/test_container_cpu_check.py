"""Container x86-64-v2 preflight (dump 20260925, Proxmox CPU type kvm64)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CPU_CHECK = _ROOT / "docker" / "cpu_check.sh"
_ENTRYPOINT = _ROOT / "docker" / "entrypoint.sh"
_DOCKERFILE = _ROOT / "docker" / "Dockerfile"
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


def _run_check(tmp_path: Path, arch: str, flags: str | None) -> subprocess.CompletedProcess[str]:
    cpuinfo = tmp_path / "cpuinfo"
    if flags is not None:
        cpuinfo.write_text(f"processor\t: 0\nflags\t\t: {flags}\n", encoding="utf-8")
    script = (
        f'. "{_CPU_CHECK.as_posix()}"\n'
        f'_check_x86_64_v2 "{arch}" "{cpuinfo.as_posix()}" "{_DOCS_URL}"\n'
    )
    return subprocess.run([_SH, "-c", script], capture_output=True, text=True, check=False)


def test_entrypoint_runs_cpu_check_before_bootstrap() -> None:
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    call = '_check_x86_64_v2 "$(uname -m)" "${EARNIE_CPUINFO_FILE:-/proc/cpuinfo}"'
    assert ". /app/docker/cpu_check.sh" in text
    assert call in text
    assert "|| exit 1" in text
    assert text.index(call) < text.index("python -m scripts.bootstrap_runtime")
    assert "container.md#cpu-voraussetzung-amd64" in text


def test_dockerfile_strips_crlf_from_cpu_check() -> None:
    assert "docker/cpu_check.sh" in _DOCKERFILE.read_text(encoding="utf-8")


def test_addon_points_cpu_hint_at_addon_docs() -> None:
    text = _RUN_SH.read_text(encoding="utf-8")
    export = "export EARNIE_CPU_CHECK_DOCS_URL="
    assert export in text
    assert "homeassistant-addon.md#voraussetzungen-gono-go" in text
    assert text.index(export) < text.index("exec /bin/sh docker/entrypoint.sh")


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_kvm64_cpu_fails_with_actionable_message(tmp_path: Path) -> None:
    result = _run_check(tmp_path, "x86_64", _KVM64_FLAGS)
    assert result.returncode == 1
    assert "x86-64-v2" in result.stderr
    assert "popcnt" in result.stderr and "sse4_2" in result.stderr
    assert '"host"' in result.stderr
    assert _DOCS_URL in result.stderr


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
def test_modern_cpu_passes(tmp_path: Path) -> None:
    result = _run_check(tmp_path, "x86_64", _HOST_FLAGS)
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.skipif(_SH is None, reason="POSIX sh not available")
@pytest.mark.parametrize(("arch", "flags"), [("aarch64", _KVM64_FLAGS), ("x86_64", None)])
def test_non_x86_or_unreadable_cpuinfo_is_skipped(tmp_path: Path, arch: str, flags: str | None) -> None:
    assert _run_check(tmp_path, arch, flags).returncode == 0
