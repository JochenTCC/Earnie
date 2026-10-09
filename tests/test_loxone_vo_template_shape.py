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
    assert len(_FILES) == 7


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


def test_ev_template_includes_fertigum_ready_by_time() -> None:
    path = _DIR / "VO_Earnie_EV.xml"
    cmds = {c.get("Title"): c for c in _parse(path) if c.tag == "VirtualOutCmd"}
    fertig = cmds["Earnie_EAuto_FertigUm"]
    assert fertig.get("Analog") == "true"
    # ElementTree unescapes &lt;v&gt; in the attribute value.
    assert fertig.get("CmdOn") == (
        "/ehal/loxone/telemetry/ev.{ev_id}.get_evcs_ready_by_time/<v>"
    )


def test_plant_template_includes_energy_counters() -> None:
    path = _DIR / "VO_Earnie_Plant.xml"
    cmds = {c.get("Title"): c.get("CmdOn") for c in _parse(path) if c.tag == "VirtualOutCmd"}
    assert cmds["Push_sens_pv_energy"] == "/ehal/loxone/telemetry/sens_pv_energy/<v>"
    assert cmds["Push_grid_meter_sens_grid_energy_import"] == (
        "/ehal/loxone/telemetry/grid.meter.sens_grid_energy_import/<v>"
    )
    assert cmds["Push_grid_meter_sens_grid_energy_export"] == (
        "/ehal/loxone/telemetry/grid.meter.sens_grid_energy_export/<v>"
    )


def test_plant_template_grid_uses_grid_meter_namespace() -> None:
    path = _DIR / "VO_Earnie_Plant.xml"
    cmds = {c.get("Title"): c.get("CmdOn") for c in _parse(path) if c.tag == "VirtualOutCmd"}
    assert cmds["Push_grid_meter_sens_grid_power_active"] == (
        "/ehal/loxone/telemetry/grid.meter.sens_grid_power_active/<v>"
    )
    assert cmds["Push_grid_meter_get_grid_export_power_limit"] == (
        "/ehal/loxone/telemetry/grid.meter.get_grid_export_power_limit/<v>"
    )


def test_plant_template_titles_match_push_ehal_ids() -> None:
    """Library VO Titles = Push_<EHAL-ID> (same rule as pilot_vo_template_gen)."""
    from ehal.push_signals import title_from_qualified_id

    path = _DIR / "VO_Earnie_Plant.xml"
    for cmd in _parse(path):
        if cmd.tag != "VirtualOutCmd":
            continue
        cmd_on = cmd.get("CmdOn") or ""
        # /ehal/loxone/telemetry/<ehal_id>/<v|0|1>
        parts = cmd_on.strip("/").split("/")
        assert len(parts) >= 4 and parts[0] == "ehal" and parts[2] == "telemetry"
        ehal_id = parts[3]
        assert cmd.get("Title") == title_from_qualified_id(ehal_id), cmd.get("Title")
        assert "ess" not in ehal_id, ehal_id


def test_plant_template_has_no_ess_fields() -> None:
    path = _DIR / "VO_Earnie_Plant.xml"
    titles = [c.get("Title") or "" for c in _parse(path) if c.tag == "VirtualOutCmd"]
    assert titles
    assert not any("ess" in t for t in titles)


def test_consumer_template_includes_energy_counter_mono_only() -> None:
    path = _DIR / "VO_Earnie_Consumer.xml"
    cmds = {c.get("Title"): c.get("CmdOn") for c in _parse(path) if c.tag == "VirtualOutCmd"}
    assert cmds["Push_consumer_{hk_id}_sens_energy_total"] == (
        "/ehal/loxone/telemetry/consumer.{hk_id}.sens_energy_total/<v>"
    )
    assert "Push_consumer_{hk_id}_sens_energy_export" not in cmds


def test_battery_template_full_push_and_bipolar_energy() -> None:
    path = _DIR / "VO_Earnie_Battery.xml"
    cmds = {c.get("Title"): c.get("CmdOn") for c in _parse(path) if c.tag == "VirtualOutCmd"}
    assert cmds["Push_ess_{bat_id}_sens_ess_soc"] == (
        "/ehal/loxone/telemetry/ess.{bat_id}.sens_ess_soc/<v>"
    )
    assert cmds["Push_ess_{bat_id}_sens_ess_power"] == (
        "/ehal/loxone/telemetry/ess.{bat_id}.sens_ess_power/<v>"
    )
    assert cmds["Push_ess_{bat_id}_sens_ess_energy_charge"] == (
        "/ehal/loxone/telemetry/ess.{bat_id}.sens_ess_energy_charge/<v>"
    )
    assert cmds["Push_ess_{bat_id}_sens_ess_energy_discharge"] == (
        "/ehal/loxone/telemetry/ess.{bat_id}.sens_ess_energy_discharge/<v>"
    )
    assert cmds["Push_ess_{bat_id}_get_ess_soc_min"] == (
        "/ehal/loxone/telemetry/ess.{bat_id}.get_ess_soc_min/<v>"
    )


# --- Virtual Input templates (structure of VI_Earnie_Plant_Real.xml, exported by Config 2026-10-07) ---
_VI_DIR = _DIR.parent / "VirtualIn"
_VI_LEGACY = sorted(p for p in _VI_DIR.glob("VI_Earnie_*.xml") if "_v2" not in p.name)
_VI_V2 = sorted(_VI_DIR.glob("VI_Earnie_*_v2.xml"))
_VI_FILES = sorted(_VI_DIR.glob("VI_Earnie_*.xml"))
_VI_ROOT_ATTRS = ["HintText", "Title", "Comment", "Address", "PollingTime"]
_VI_CMD_ATTRS = [
    "Title", "Comment", "Check", "Signed", "Analog", "SourceValLow", "DestValLow", "SourceValHigh",
    "DestValHigh", "DefVal", "MinVal", "MaxVal", "Unit", "HintText",
]


def test_vi_templates_found() -> None:
    assert len(_VI_LEGACY) == 5
    assert len(_VI_V2) == 5
    assert len(_VI_FILES) == 10


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


def test_vi_v2_checks_use_qualified_keys() -> None:
    """v2 library templates must not use legacy Merker Check keys."""
    legacy_check_frags = (
        "Earnie_Verbraucher_Freigabe",
        "Earnie_Waermepumpe_Freigabe",
        "Earnie_EAuto_Soll_A",
        "Earnie_Pool_Freigabe",
    )
    for path in _VI_V2:
        for cmd in _parse(path):
            if cmd.tag != "VirtualInHttpCmd":
                continue
            check = cmd.get("Check") or ""
            for frag in legacy_check_frags:
                assert frag not in check, (path.name, check)
    consumer = (_VI_DIR / "VI_Earnie_Consumer_v2.xml").read_bytes().decode("utf-8-sig")
    assert "consumer.{hk_id}.set_enable" in consumer
    ev = (_VI_DIR / "VI_Earnie_EV_v2.xml").read_bytes().decode("utf-8-sig")
    assert "evcs.{ev_id}.set_evcs_max_current" in ev
    assert "evcs.{ev_id}.set_evcs_mode" in ev
    pool = (_VI_DIR / "VI_Earnie_Pool_v2.xml").read_bytes().decode("utf-8-sig")
    assert "pool.pool_filter.set_enable" in pool


def test_vi_legacy_checks_unchanged() -> None:
    consumer = (_VI_DIR / "VI_Earnie_Consumer.xml").read_bytes().decode("utf-8-sig")
    assert "flex.{hk_id}.Earnie_Verbraucher_Freigabe" in consumer
    ev = (_VI_DIR / "VI_Earnie_EV.xml").read_bytes().decode("utf-8-sig")
    assert "ev.{ev_id}.Earnie_EAuto_Soll_A" in ev
