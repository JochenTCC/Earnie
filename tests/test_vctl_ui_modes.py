"""The VMware ``vctl`` install path starts the same UI modes as the production Compose stacks."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_MODES = re.compile(r"EARNIE_UI_MODES[=:]\s*([a-z0-9_,]+)")


def _modes(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    found = [m.group(1) for m in _MODES.finditer(text)]
    assert found, f"no EARNIE_UI_MODES in {path}"
    return found


def test_production_compose_modes_include_scenario_explorer() -> None:
    (prod,) = set(_modes(ROOT / "docker/compose/proxmox_productive.yml"))
    assert "scenario_explorer" in prod.split(",")


def test_vctl_script_starts_production_ui_modes() -> None:
    (prod,) = set(_modes(ROOT / "docker/compose/proxmox_productive.yml"))
    assert _modes(ROOT / "scripts/run_earnie_vctl.ps1") == [prod]


def test_vctl_doc_manual_run_starts_production_ui_modes() -> None:
    (prod,) = set(_modes(ROOT / "docker/compose/proxmox_productive.yml"))
    assert _modes(ROOT / "docs/einrichtung/vmware-vctl.md") == [prod]
