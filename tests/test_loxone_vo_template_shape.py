"""Repo Virtual Output templates keep the structure Loxone Config exports (2026-10-07)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "share" / "loxone" / "templates" / "VirtualOut"
_FILES = sorted(_DIR.glob("VO_Earnie_*.xml"))

_ROOT_ATTRS = ["HintText", "Title", "Comment", "Address", "CmdInit", "CloseAfterSend", "CmdSep"]
_ANALOG_ATTRS = [
    "Title", "Comment", "CmdOnMethod", "CmdOffMethod", "CmdOn", "CmdOnHTTP", "CmdOnPost", "CmdOff",
    "CmdOffHTTP", "CmdOffPost", "CmdAnswer", "Analog", "Repeat", "RepeatRate",
    "SourceValLow", "DestValLow", "SourceValHigh", "DestValHigh", "HintText",
]
_DIGITAL_ATTRS = [a for a in _ANALOG_ATTRS if not a.startswith(("SourceVal", "DestVal"))]
_BACKSLASH_V = chr(92) + "v"


def _parse(path: Path) -> ET.Element:
    return ET.fromstring(path.read_bytes().decode("utf-8-sig").encode("utf-8"))


def test_templates_found() -> None:
    assert len(_FILES) == 6


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_export_structure(path: Path) -> None:
    assert path.read_bytes().startswith(bytes([0xEF, 0xBB, 0xBF]))  # BOM like Config
    root = _parse(path)
    assert root.tag == "VirtualOut"
    assert list(root.attrib) == _ROOT_ATTRS
    info, *cmds = list(root)
    assert info.tag == "Info" and info.attrib == {"templateType": "3", "minVersion": "17010630"}
    assert cmds
    for cmd in cmds:
        assert cmd.tag == "VirtualOutCmd"
        expected = _DIGITAL_ATTRS if cmd.get("Analog") == "false" else _ANALOG_ATTRS
        assert list(cmd.attrib) == expected, cmd.get("Title")


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_value_placeholder_is_not_the_input_style_escape(path: Path) -> None:
    # In a Virtual Output command the VI-style escape arrives as the control character 0x0B.
    for cmd in _parse(path):
        assert _BACKSLASH_V not in (cmd.get("CmdOn") or ""), cmd.get("Title")


# --- Virtual Input templates (structure of VI_Earnie_Plant_Real.xml, exported by Config 2026-10-07) ---
_VI_DIR = _DIR.parent / "VirtualIn"
_VI_FILES = sorted(_VI_DIR.glob("VI_Earnie_*.xml"))
_VI_ROOT_ATTRS = ["HintText", "Title", "Comment", "Address", "PollingTime"]
_VI_CMD_ATTRS = [
    "Title", "Comment", "Check", "Signed", "Analog", "SourceValLow", "DestValLow", "SourceValHigh",
    "DestValHigh", "DefVal", "MinVal", "MaxVal", "Unit", "HintText",
]


def test_vi_templates_found() -> None:
    assert len(_VI_FILES) == 5


@pytest.mark.parametrize("path", _VI_FILES, ids=lambda p: p.name)
def test_vi_export_structure(path: Path) -> None:
    assert path.read_bytes().startswith(bytes([0xEF, 0xBB, 0xBF]))
    root = _parse(path)
    assert root.tag == "VirtualInHttp"
    assert list(root.attrib) == _VI_ROOT_ATTRS
    info, *cmds = list(root)
    assert info.tag == "Info" and info.attrib == {"templateType": "2", "minVersion": "17010630"}
    assert cmds
    for cmd in cmds:
        assert cmd.tag == "VirtualInHttpCmd"
        assert list(cmd.attrib) == _VI_CMD_ATTRS, cmd.get("Title")
        # A Virtual Input extracts the value with the escape (unlike a Virtual Output command).
        assert cmd.get("Check", "").endswith(chr(58) + _BACKSLASH_V), cmd.get("Title")
