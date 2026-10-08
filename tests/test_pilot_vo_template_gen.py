"""Pilot (spike/vo-push-pilot): VO template generator."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import pilot_vo_template_gen as gen


def test_pilot_id_namespaces() -> None:
    assert gen.pilot_id("plant", "plant", "sens_grid_power_active") == "sens_grid_power_active"
    assert gen.pilot_id("battery", "x", "ess.x.sens_ess_soc") == "ess.x.sens_ess_soc"
    assert gen.pilot_id("battery", "x", "sens_ess_soc") == "ess.x.sens_ess_soc"
    assert gen.pilot_id("consumer", "waschmaschine", "flex.waschmaschine.sens_power_act", "generic") == (
        "consumer.waschmaschine.sens_power_act"
    )
    assert gen.pilot_id("consumer", "waermepumpe", "sens_temperature_heat_storage", "thermal_annual") == (
        "heatpump.waermepumpe.sens_temperature_heat_storage"
    )
    assert gen.pilot_id("consumer", "pool_swimspa", "sens_temperature_water", "thermal_rc") == (
        "pool.pool_swimspa.sens_temperature_water"
    )
    assert gen.pilot_id("consumer", "e_auto", "sens_evcs_active_power", "ev") == "evcs.e_auto.sens_evcs_active_power"
    assert gen.pilot_id("consumer", "e_auto", "sens_evcs_soc_act", "ev") == "ev.e_auto.sens_evcs_soc_act"
    assert gen.pilot_id("consumer", "e_auto", "get_evcs_ready_by_time", "ev") == (
        "ev.e_auto.get_evcs_ready_by_time"
    )


def test_ascii_title() -> None:
    assert gen.ascii_title("Zähler Wärmepumpe") == "Push_Zaehler_Waermepumpe"
    assert gen.ascii_title("Earnie_LadeLeistungs-Limit") == "Push_Earnie_LadeLeistungs-Limit"
    assert gen.ascii_title("   ") == "Push_unbenannt"


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "house_profiles.json").write_text(
        json.dumps(
            {
                "plant": {"ehal_bindings": {"sens_grid_power_active": "Earnie_Netzleistung",
                                            "set_grid_export_power_limit": "Earnie_Limit",
                                            "sens_absent_mode": "Earnie_Abwesend"}},
                "profiles": {"p": {"consumers": [
                    {"id": "e_auto", "type": "ev", "ehal_bindings": {
                        "sens_evcs_connected": "Earnie_EAuto_Angeschlossen",
                        "sens_evcs_soc_act": "Earnie_EAuto_SOC",
                        "get_evcs_ready_by_time": "Ladewecker",
                        "set_evcs_max_current": "Earnie_EAuto_Soll_A"}},
                    {"id": "pool_swimspa", "type": "thermal_rc", "ehal_bindings": {
                        "sens_temperature_water": "Earnie_Pool_Temp_Ist"}},
                    {"id": "trockner", "type": "generic", "ehal_bindings": {
                        "flex.trockner.sens_power_act": "Zähler Trockner",
                        "flex.trockner.set_enable": "Earnie_Verbraucher_Freigabe"}},
                ]}},
            }
        ),
        encoding="utf-8",
    )
    (cfg / "components.json").write_text(
        json.dumps({"batteries": [{"id": "15_kwh_speicher", "ehal_bindings": {
            "ess.15_kwh_speicher.sens_ess_soc": "Earnie_Batterie_SoC",
            "ess.15_kwh_speicher.set_ess_mode": "Earnie_Steuerbefehl"}}]}),
        encoding="utf-8",
    )
    return cfg


def test_collect_only_reads_and_valid_ids(tmp_path: Path) -> None:
    signals = {s.ehal_id: s for s in gen.collect_read_signals(_config(tmp_path))}
    assert set(signals) == {
        "sens_grid_power_active",
        "sens_absent_mode",
        "evcs.e_auto.sens_evcs_connected",
        "ev.e_auto.sens_evcs_soc_act",
        "ev.e_auto.get_evcs_ready_by_time",
        "consumer.trockner.sens_power_act",
        "pool.pool_swimspa.sens_temperature_water",
        "ess.15_kwh_speicher.sens_ess_soc",
    }
    assert signals["sens_absent_mode"].digital
    assert signals["evcs.e_auto.sens_evcs_connected"].digital
    assert not signals["sens_grid_power_active"].digital
    assert signals["consumer.trockner.sens_power_act"].title == "Push_Zaehler_Trockner"
    assert signals["consumer.trockner.sens_power_act"].group == "Verbraucher"
    assert signals["pool.pool_swimspa.sens_temperature_water"].group == "Pool"
    assert signals["ev.e_auto.sens_evcs_soc_act"].group == "EV"


# Attribute order of a Cmd as exported by Loxone Config (2026-10-07, analog / digital).
ANALOG_ATTRS = [
    "Title", "Comment", "CmdOnMethod", "CmdOffMethod", "CmdOn", "CmdOnHTTP", "CmdOnPost", "CmdOff",
    "CmdOffHTTP", "CmdOffPost", "CmdAnswer", "Analog", "Repeat", "RepeatRate",
    "SourceValLow", "DestValLow", "SourceValHigh", "DestValHigh", "HintText",
]
DIGITAL_ATTRS = [a for a in ANALOG_ATTRS if a not in ("SourceValLow", "DestValLow", "SourceValHigh", "DestValHigh")]


def _render_plant(tmp_path: Path, **kwargs) -> tuple[str, ET.Element]:
    sigs = gen.collect_read_signals(_config(tmp_path))
    plant = [s for s in sigs if s.group == "Plant"]
    text = gen.render_template("Plant", plant, host="192.168.178.35", port=8541, token="abcd1234efgh", **kwargs)
    return text, ET.fromstring(text.encode("utf-8"))


def test_template_matches_the_loxone_config_export_shape(tmp_path: Path) -> None:
    text, root = _render_plant(tmp_path)
    assert text.startswith('<?xml version="1.0" encoding="utf-8"?>' + chr(10) + "<VirtualOut HintText=")
    assert list(root.attrib) == ["HintText", "Title", "Comment", "Address", "CmdInit", "CloseAfterSend", "CmdSep"]
    assert root.get("Address") == "http://192.168.178.35:8541"
    info, *cmds = list(root)
    assert info.tag == "Info" and info.attrib == {"templateType": "3", "minVersion": "17010630"}
    by_title = {c.get("Title"): c for c in cmds}
    assert list(by_title["Push_Earnie_Netzleistung"].attrib) == ANALOG_ATTRS
    assert list(by_title["Push_Earnie_Abwesend"].attrib) == DIGITAL_ATTRS
    assert "/>" in text and " />" not in text  # self-closing like the export
    assert chr(9) + "<VirtualOutCmd" in text  # tab indent


def test_template_values_placeholder_repeat_and_digital(tmp_path: Path) -> None:
    text, root = _render_plant(tmp_path)
    assert "&lt;v&gt;" in text and "<v>" not in text
    cmds = {c.get("Title"): c for c in root if c.tag == "VirtualOutCmd"}
    analog = cmds["Push_Earnie_Netzleistung"]
    assert analog.get("CmdOn") == "/ehal/loxone/telemetry/sens_grid_power_active/<v>?t=abcd1234efgh"
    assert (analog.get("Analog"), analog.get("Repeat"), analog.get("RepeatRate")) == ("true", "10", "10")
    digital = cmds["Push_Earnie_Abwesend"]
    assert digital.get("CmdOn") == "/ehal/loxone/telemetry/sens_absent_mode/1?t=abcd1234efgh"
    assert digital.get("CmdOff") == "/ehal/loxone/telemetry/sens_absent_mode/0?t=abcd1234efgh"
    assert digital.get("Analog") == "false"
    _text, root0 = _render_plant(tmp_path, repeat="0", repeat_rate="0")
    assert {c.get("Repeat") for c in root0 if c.tag == "VirtualOutCmd"} == {"0"}


def test_write_template_has_bom(tmp_path: Path) -> None:
    out = tmp_path / "t.xml"
    gen.write_template(out, "<a/>")
    assert out.read_bytes().startswith(bytes([0xEF, 0xBB, 0xBF]))
    ET.parse(out)  # Python's parser tolerates the BOM like Loxone does


@pytest.mark.parametrize("token", ["", "short", "has space 12345", "a&b=12345678", "q?uery12345"])
def test_token_must_be_url_safe(tmp_path: Path, token: str) -> None:
    env = tmp_path / ".env"
    env.write_text(f"EARNIE_PILOT_PUSH_TOKEN={token}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        gen.read_token(env)


def test_token_ok(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("EARNIE_PILOT_PUSH_TOKEN=dummytoken0123456\n", encoding="utf-8")
    assert gen.read_token(env) == "dummytoken0123456"


def test_heartbeat_template_and_analog_has_no_off_command() -> None:
    text = gen.render_template(
        "Heartbeat", [gen.heartbeat_signal()], host="192.168.178.35", port=8541, token="abcd1234efgh"
    )
    cmd = next(c for c in ET.fromstring(text.encode("utf-8")) if c.tag == "VirtualOutCmd")
    assert cmd.get("Title") == "Push_Earnie_Heartbeat"
    assert cmd.get("CmdOn") == "/ehal/loxone/telemetry/heartbeat/<v>?t=abcd1234efgh"
    assert cmd.get("Analog") == "true"
    assert cmd.get("CmdOff") == ""  # analog outputs have no Off command
    assert (cmd.get("Repeat"), cmd.get("RepeatRate")) == ("10", "10")


def test_all_collected_analog_commands_have_empty_off(tmp_path: Path) -> None:
    sigs = [s for s in gen.collect_read_signals(_config(tmp_path)) if not s.digital]
    root = ET.fromstring(gen.render_template("X", sigs, host="h", port=1, token="abcd1234").encode("utf-8"))
    assert all(c.get("CmdOff") == "" for c in root if c.tag == "VirtualOutCmd")


def test_token_in_address_moves_the_token_out_of_the_commands(tmp_path: Path) -> None:
    sigs = gen.collect_read_signals(_config(tmp_path)) + [gen.heartbeat_signal()]
    text = gen.render_template(
        "X", sigs, host="192.168.178.35", port=8541, token="abcd1234efgh", token_in_address=True
    )
    root = ET.fromstring(text.encode("utf-8"))
    assert root.get("Address") == "http://192.168.178.35:8541/t/abcd1234efgh"
    cmds = [c for c in root if c.tag == "VirtualOutCmd"]
    assert cmds
    for cmd in cmds:
        assert "abcd1234efgh" not in (cmd.get("CmdOn") or "") + (cmd.get("CmdOff") or "")
        assert "?t=" not in (cmd.get("CmdOn") or "")
    by_title = {c.get("Title"): c for c in cmds}
    assert by_title["Push_Earnie_Netzleistung"].get("CmdOn") == "/ehal/loxone/telemetry/sens_grid_power_active/<v>"
    assert by_title["Push_Earnie_Abwesend"].get("CmdOn") == "/ehal/loxone/telemetry/sens_absent_mode/1"
    assert by_title["Push_Earnie_Abwesend"].get("CmdOff") == "/ehal/loxone/telemetry/sens_absent_mode/0"


def test_default_keeps_the_token_in_every_command(tmp_path: Path) -> None:
    sigs = gen.collect_read_signals(_config(tmp_path))
    text = gen.render_template("X", sigs, host="h", port=1, token="abcd1234efgh")
    root = ET.fromstring(text.encode("utf-8"))
    assert root.get("Address") == "http://h:1"
    assert all("t=abcd1234efgh" in (c.get("CmdOn") or "") for c in root if c.tag == "VirtualOutCmd")
