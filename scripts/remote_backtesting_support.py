"""Hilfsfunktionen für scripts.remote_backtesting (Share-Sync und SSH)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "remote_backtesting.json"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "remote_backtesting.example.json"


class RemoteBacktestingError(Exception):
    """Konfigurations- oder Laufzeitfehler beim Remote-Backtesting."""


def load_remote_config(path: Path | str | None = None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.is_file():
        raise RemoteBacktestingError(
            f"Konfiguration fehlt: {cfg_path}\n"
            f"Kopiere {EXAMPLE_CONFIG_PATH} nach {DEFAULT_CONFIG_PATH} und passe Host/Pfade an."
        )
    with open(cfg_path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return validate_remote_config(data)


def validate_remote_config(data: dict) -> dict:
    if not isinstance(data, dict):
        raise RemoteBacktestingError("remote_backtesting.json muss ein JSON-Objekt sein.")
    share_root = str(data.get("share_root", "")).strip()
    if not share_root:
        raise RemoteBacktestingError("share_root ist Pflicht (SMB-Freigabe oder lokaler Sync-Ordner).")
    ssh = data.get("ssh")
    if not isinstance(ssh, dict):
        raise RemoteBacktestingError("ssh-Block fehlt in remote_backtesting.json.")
    for key in ("host", "user", "remote_repo"):
        if not str(ssh.get(key, "")).strip():
            raise RemoteBacktestingError(f"ssh.{key} ist Pflicht.")
    sync_paths = data.get("sync_paths")
    if not isinstance(sync_paths, list) or not sync_paths:
        raise RemoteBacktestingError("sync_paths muss ein nicht-leeres Array sein.")
    result_files = data.get("result_files")
    if not isinstance(result_files, list) or not result_files:
        raise RemoteBacktestingError("result_files muss ein nicht-leeres Array sein.")
    return data


def share_path(cfg: dict) -> Path:
    return Path(os.path.expandvars(str(cfg["share_root"]).strip()))


def remote_share_path(cfg: dict) -> Path:
    raw = str(cfg.get("remote_share_root") or cfg["share_root"]).strip()
    return Path(os.path.expandvars(raw))


def result_share_dir(cfg: dict) -> Path:
    sub = str(cfg.get("result_dir", "results")).strip() or "results"
    return share_path(cfg) / sub


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_path(repo_rel: str, src_root: Path, dst_root: Path) -> None:
    src = src_root / repo_rel
    dst = dst_root / repo_rel
    if not src.exists():
        raise RemoteBacktestingError(f"Sync-Quelle fehlt: {src}")
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return
    _copy_file(src, dst)


def push_to_share(cfg: dict, repo_root: Path = REPO_ROOT) -> None:
    """Lokales Repo → Share (gemeinsame Basis)."""
    target = share_path(cfg)
    target.mkdir(parents=True, exist_ok=True)
    result_share_dir(cfg).mkdir(parents=True, exist_ok=True)
    for rel in cfg["sync_paths"]:
        _copy_path(str(rel), repo_root, target)
    print(f"Push abgeschlossen: {target}")


def pull_from_share(cfg: dict, repo_root: Path = REPO_ROOT) -> None:
    """Share/results → lokales Repo-Root."""
    source = result_share_dir(cfg)
    if not source.is_dir():
        raise RemoteBacktestingError(f"Ergebnisordner fehlt auf dem Share: {source}")
    for name in cfg["result_files"]:
        src = source / name
        if not src.is_file():
            raise RemoteBacktestingError(f"Ergebnisdatei fehlt auf dem Share: {src}")
        _copy_file(src, repo_root / name)
    print(f"Pull abgeschlossen nach {repo_root}")


def ssh_argv(cfg: dict) -> list[str]:
    ssh = cfg["ssh"]
    cmd = ["ssh"]
    port = int(ssh.get("port") or 22)
    if port != 22:
        cmd.extend(["-p", str(port)])
    identity = str(ssh.get("identity_file", "")).strip()
    if identity:
        cmd.extend(["-i", os.path.expanduser(identity)])
    cmd.append(f"{ssh['user']}@{ssh['host']}")
    return cmd


def _quote_ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_bash(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_remote_run_command(cfg: dict, backtesting_args: list[str]) -> str:
    """Shell-Befehl auf dem Remote-PC: Share → Repo, Lauf, Ergebnisse → Share."""
    ssh = cfg["ssh"]
    shell = str(ssh.get("shell", "powershell")).lower().strip()
    remote_repo = str(ssh["remote_repo"]).strip()
    remote_share = str(remote_share_path(cfg)).strip()
    result_sub = str(cfg.get("result_dir", "results")).strip() or "results"
    python_bin = str(ssh.get("python", "python")).strip()
    run_args = " ".join(backtesting_args)

    if shell == "bash":
        parts = [
            f"cd {_quote_bash(remote_repo)}",
            (
                f"rsync -a --delete --exclude {_quote_bash(result_sub)} "
                f"{_quote_bash(remote_share + '/')} ./"
            ),
            f"{python_bin} -m scripts.run_backtesting {run_args}",
            f"mkdir -p {_quote_bash(remote_share + '/' + result_sub)}",
        ]
        for name in cfg["result_files"]:
            parts.append(
                f"cp {_quote_bash(name)} {_quote_bash(remote_share + '/' + result_sub + '/' + name)}"
            )
        return " && ".join(parts)

    share_literal = _quote_ps(remote_share)
    repo_literal = _quote_ps(remote_repo)
    result_literal = _quote_ps(f"{remote_share}\\{result_sub}")
    lines = [
        f"Set-Location {repo_literal}",
        (
            f"robocopy {share_literal} {repo_literal} /E /XD {result_sub} .git "
            f"/NFL /NDL /NJH /NJS /nc /ns /np | Out-Null; "
            f"if ($LASTEXITCODE -ge 8) {{ exit $LASTEXITCODE }}"
        ),
        f"& {python_bin} -m scripts.run_backtesting {run_args}",
        f"New-Item -ItemType Directory -Force -Path {result_literal} | Out-Null",
    ]
    for name in cfg["result_files"]:
        dest = _quote_ps(f"{remote_share}\\{result_sub}\\{name}")
        lines.append(f"Copy-Item -Force {_quote_ps(name)} {dest}")
    return "; ".join(lines)


def run_remote_backtesting(cfg: dict, backtesting_args: list[str]) -> None:
    remote_cmd = build_remote_run_command(cfg, backtesting_args)
    shell = str(cfg["ssh"].get("shell", "powershell")).lower().strip()
    if shell == "bash":
        remote_invocation = f"bash -lc {_quote_bash(remote_cmd)}"
    else:
        remote_invocation = f"powershell -NoProfile -Command {_quote_bash(remote_cmd)}"
    final = ssh_argv(cfg) + [remote_invocation]
    print("+", " ".join(final))
    subprocess.run(final, check=True, cwd=REPO_ROOT)
