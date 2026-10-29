"""Exported VO / VI templates keep the structure Loxone Config exports (2026-10-07).

The templates are generated per configuration from the Signal list
(``ehal.signal_export.build_export_zip``); there are no static library templates.
"""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from ehal.signal_export import build_export_zip

_ROOT_ATTRS = ["HintText", "Title", "Comment", "Address", "CmdInit", "CloseAfterSend", "CmdSep"]
_ANALOG_ATTRS = [
    "Title", "Comment", "CmdOnMethod", "CmdOffMethod", "CmdOn", "CmdOnHTTP", "CmdOnPost", "CmdOff",
    "CmdOffHTTP", "CmdOffPost", "CmdAnswer", "Analog", "Repeat", "RepeatRate",
    "SourceValLow", "DestValLow", "SourceValHigh", "DestValHigh", "HintText",
]
_DIGITAL_ATTRS = [a for a in _ANALOG_ATTRS if not a.startswith(("SourceVal", "DestVal"))]
_BACKSLASH_V = chr(92) + "v"

_VI_ROOT_ATTRS = ["HintText", "Title", "Comment", "Address", "PollingTime"]
_VI_CMD_ATTRS = [
    "Title", "Comment", "Check", "Signed", "Analog", "SourceValLow", "DestValLow", "SourceValHigh",
    "DestValHigh", "DefVal", "MinVal", "MaxVal", "Unit", "HintText",
]


def _docs() -> tuple[dict, dict]:
    """One entity of every exported group (plant, battery, generic, heat pump, pool, EV)."""
    house = {
        "plant": {"ehal_bindings": {"sens_grid_power_active": ""}},
        "profiles": {
            "live": {
                "consumers": [
                    {"id": "waschmaschine", "type": "generic", "ehal_bindings": {}},
                    {"id": "waermepumpe", "type": "thermal_annual", "ehal_bindings": {}},
                    {"id": "pool_filter", "type": "pool_filter", "ehal_bindings": {}},
                    {"id": "e_auto", "type": "ev", "ehal_bindings": {}},
                ]
            }
        },
    }
    components = {"batteries": [{"id": "haus", "control": "full", "ehal_bindings": {}}]}
    return house, components


@pytest.fixture(scope="module")
def export() -> dict[str, bytes]:
    house, components = _docs()
    payload = build_export_zip(house, components, host="192.168.1.10", port=8541, mode="all")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _parse(raw: bytes) -> ET.Element:
    return ET.fromstring(raw.decode("utf-8-sig").encode("utf-8"))


def _cmds(export: dict[str, bytes], name: str) -> dict[str, ET.Element]:
    return {c.get("Title"): c for c in _parse(export[name]) if c.tag != "Info"}


def _cmd_on(export: dict[str, bytes], name: str) -> dict[str, str]:
    # Drop the push token query so assertions read like the wire path.
    return {t: (c.get("CmdOn") or "").split("?", 1)[0] for t, c in _cmds(export, name).items()}


def _names(export: dict[str, bytes], prefix: str) -> list[str]:
    return sorted(n for n in export if n.startswith(prefix) and n.endswith(".xml"))


def test_export_has_one_template_per_group(export: dict[str, bytes]) -> None:
    groups = ["Batterie_haus", "EV", "Heartbeat", "Plant", "Pool", "Verbraucher", "Waermepumpe"]
    vo_groups = sorted(groups + ["Status"])
    assert _names(export, "VO_Earnie_") == [f"VO_Earnie_{g}.xml" for g in vo_groups]
    assert _names(export, "VI_Earnie_") == [f"VI_Earnie_{g}.xml" for g in groups]


def test_vo_export_structure(export: dict[str, bytes]) -> None:
    for name in _names(export, "VO_Earnie_"):
        raw = export[name]
        assert raw.startswith(bytes([0xEF, 0xBB, 0xBF])), name  # BOM like Config
        root = _parse(raw)
        assert root.tag == "VirtualOut"
        assert list(root.attrib) == _ROOT_ATTRS
        info, *cmds = list(root)
        assert info.tag == "Info" and info.attrib == {"templateType": "3", "minVersion": "17010630"}
        assert cmds, name
        for cmd in cmds:
            assert cmd.tag == "VirtualOutCmd"
            expected = _DIGITAL_ATTRS if cmd.get("Analog") == "false" else _ANALOG_ATTRS
            assert list(cmd.attrib) == expected, (name, cmd.get("Title"))
            # In a Virtual Output command the VI-style escape arrives as the control character 0x0B.
            assert _BACKSLASH_V not in (cmd.get("CmdOn") or ""), (name, cmd.get("Title"))


def test_vo_titles_match_push_ehal_ids(export: dict[str, bytes]) -> None:
    from ehal.push_signals import title_from_qualified_id

    for name in _names(export, "VO_Earnie_"):
        if name == "VO_Earnie_Status.xml":
            continue  # POST control command, see test_status_template_request_optimize
        for title, cmd_on in _cmd_on(export, name).items():
            parts = cmd_on.strip("/").split("/")
            assert len(parts) >= 3 and parts[:2] == ["ehal", "telemetry"], (name, title)
            if parts[2] == "heartbeat_smarthome":
                assert title == "Push_Earnie_Heartbeat"
            else:
                assert title == title_from_qualified_id(parts[2]), (name, title)


def test_plant_template_grid_uses_grid_meter_namespace_and_no_ess(export: dict[str, bytes]) -> None:
    cmds = _cmd_on(export, "VO_Earnie_Plant.xml")
    assert cmds["Push_grid_meter_sens_grid_power_active"] == (
        "/ehal/telemetry/grid.meter.sens_grid_power_active/<v.3>"
    )
    assert cmds["Push_grid_meter_get_grid_export_power_limit"] == (
        "/ehal/telemetry/grid.meter.get_grid_export_power_limit/<v.3>"
    )
    assert not any("ess" in title for title in cmds)


def test_plant_template_house_wide_reads(export: dict[str, bytes]) -> None:
    cmds = _cmds(export, "VO_Earnie_Plant.xml")
    on = _cmd_on(export, "VO_Earnie_Plant.xml")
    assert on["Push_sens_temperature_outside"] == "/ehal/telemetry/sens_temperature_outside/<v.1>"
    absent = cmds["Push_sens_absent_mode"]
    assert absent.get("Analog") == "false"
    assert on["Push_sens_absent_mode"] == "/ehal/telemetry/sens_absent_mode/1"


def test_status_template_request_optimize(export: dict[str, bytes]) -> None:
    root = _parse(export["VO_Earnie_Status.xml"])
    assert root.get("Address") == "http://192.168.1.10:8541"
    cmds = _cmds(export, "VO_Earnie_Status.xml")
    assert list(cmds) == ["Earnie_Request_Optimize"]
    cmd = cmds["Earnie_Request_Optimize"]
    assert cmd.get("CmdOnMethod") == "POST"
    assert cmd.get("CmdOn") == "/ehal/loxone/request_optimize"  # no push token on this route
    assert cmd.get("CmdOnHTTP") == "Content-Type: application/json"
    assert cmd.get("CmdOnPost") == "{}"
    assert cmd.get("Repeat") == "0"


def test_consumer_template_energy_counter_mono_and_digital_active(export: dict[str, bytes]) -> None:
    cmds = _cmds(export, "VO_Earnie_Verbraucher.xml")
    on = _cmd_on(export, "VO_Earnie_Verbraucher.xml")
    assert on["Push_consumer_waschmaschine_sens_energy_total"] == (
        "/ehal/telemetry/consumer.waschmaschine.sens_energy_total/<v.3>"
    )
    assert "Push_consumer_waschmaschine_sens_energy_export" not in on
    active = cmds["Push_consumer_waschmaschine_sens_consumer_active"]
    assert active.get("Analog") == "false"
    assert "flex." not in "".join(on.values())


def test_battery_template_full_push_and_bipolar_energy(export: dict[str, bytes]) -> None:
    cmds = _cmd_on(export, "VO_Earnie_Batterie_haus.xml")
    for field, placeholder in (
        ("sens_ess_soc", "<v.1>"),
        ("sens_ess_power", "<v.3>"),
        ("sens_ess_energy_charge", "<v.3>"),
        ("sens_ess_energy_discharge", "<v.3>"),
        ("get_ess_soc_min", "<v.1>"),
    ):
        assert cmds[f"Push_ess_haus_{field}"] == f"/ehal/telemetry/ess.haus.{field}/{placeholder}"


def test_ev_template_includes_fertigum_and_soc_min_immediate(export: dict[str, bytes]) -> None:
    cmds = _cmds(export, "VO_Earnie_EV.xml")
    fertig = cmds["Push_ev_e_auto_get_evcs_ready_by_time"]
    assert fertig.get("Analog") == "true"
    # ElementTree unescapes &lt;v&gt; in the attribute value.
    assert (fertig.get("CmdOn") or "").split("?", 1)[0] == (
        "/ehal/telemetry/ev.e_auto.get_evcs_ready_by_time/<v>"
    )
    assert "Push_ev_e_auto_get_evcs_soc_min_immediate" in cmds


def test_vi_export_structure(export: dict[str, bytes]) -> None:
    for name in _names(export, "VI_Earnie_"):
        raw = export[name]
        assert raw.startswith(bytes([0xEF, 0xBB, 0xBF])), name
        root = _parse(raw)
        assert root.tag == "VirtualInHttp"
        assert list(root.attrib) == _VI_ROOT_ATTRS
        info, *cmds = list(root)
        assert info.tag == "Info" and info.attrib == {"templateType": "2", "minVersion": "17010630"}
        assert cmds, name
        for cmd in cmds:
            assert cmd.tag == "VirtualInHttpCmd"
            assert list(cmd.attrib) == _VI_CMD_ATTRS, (name, cmd.get("Title"))
            # A Virtual Input extracts the value with the escape (unlike a Virtual Output command).
            assert cmd.get("Check", "").endswith(chr(58) + _BACKSLASH_V), (name, cmd.get("Title"))


def test_vi_checks_use_qualified_keys(export: dict[str, bytes]) -> None:
    checks = [
        cmd.get("Check") or ""
        for name in _names(export, "VI_Earnie_")
        for cmd in _parse(export[name])
        if cmd.tag == "VirtualInHttpCmd"
    ]
    joined = "\n".join(checks)
    for frag in (
        "Earnie_Verbraucher_Freigabe",
        "Earnie_Waermepumpe_Freigabe",
        "Earnie_EAuto_Soll_A",
        "Earnie_Pool_Freigabe",
    ):
        assert frag not in joined
    for key in (
        "consumer.waschmaschine.set_enable",
        "heatpump.waermepumpe.set_enable",
        "pool.pool_filter.set_enable",
        "evcs.e_auto.set_evcs_max_current",
        "evcs.e_auto.set_evcs_mode",
        "heartbeat_earnie",
    ):
        assert f'"{key}":{_BACKSLASH_V}' in checks, key


def test_signal_list_csv_names_ehal_ids(export: dict[str, bytes]) -> None:
    rows = list(
        csv.reader(io.StringIO(export["Earnie-VO-Signalliste.csv"].decode("utf-8-sig")), delimiter=";")
    )
    assert rows[0] == ["Datei", "VO-Cmd-Titel", "EHAL-ID", "Bisheriger Name", "Typ"]
    ids = {row[2] for row in rows[1:]}
    assert "ev.e_auto.get_evcs_soc_min_immediate" in ids
    assert {"sens_temperature_outside", "sens_absent_mode", "request_optimize"} <= ids
