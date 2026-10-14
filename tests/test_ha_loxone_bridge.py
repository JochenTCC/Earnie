"""tools.ha_loxone_bridge: mapping validation, HA package, Loxone VO template (POC EcoFlow Delta 3)."""
from __future__ import annotations

import ast
import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.ha_loxone_bridge.__main__ import CHECKLIST_FILE, PACKAGE_FILE, XML_FILE, generate, main
from tools.ha_loxone_bridge.checklist import render_checklist
from tools.ha_loxone_bridge.ha_yaml import render_package
from tools.ha_loxone_bridge.loxone_xml import render_virtual_out
from tools.ha_loxone_bridge.mapping import MappingError, parse_mapping

_PKG_DIR = Path(__file__).resolve().parents[1] / "tools" / "ha_loxone_bridge"
_EXAMPLE = _PKG_DIR / "examples" / "delta3.mapping.json"
_BACKSLASH_V = chr(92) + "v"


def _raw() -> dict:
    raw = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
    for point in raw["points"]:
        if "webhook_id" in point:
            point["webhook_id"] = f"test_{point['name']}_Zq81xKp"
    return raw


def _mapping(raw: dict | None = None):
    return parse_mapping(raw if raw is not None else _raw())


def _load_package(text: str) -> dict:
    yaml = pytest.importorskip("yaml")

    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_constructor("!secret", lambda loader, node: f"<secret:{loader.construct_scalar(node)}>")
    return yaml.load(text, Loader=_Loader)


def _jinja_env(states: dict[str, str] | None = None):
    jinja2 = pytest.importorskip("jinja2")

    def _is_number(value) -> bool:
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True

    env = jinja2.Environment()
    env.filters["is_number"] = _is_number
    env.globals["states"] = lambda entity: (states or {}).get(entity, "unknown")
    return env


def _render(template: str, states: dict[str, str] | None = None, **context) -> str:
    return _jinja_env(states).from_string(template).render(**context)


def _automation(package: dict, name: str) -> dict:
    return next(a for a in package["automation"] if a["id"] == f"ha_loxone_bridge_{name}")


# --- mapping validation ---------------------------------------------------------------


def test_example_mapping_needs_real_webhook_ids() -> None:
    raw = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
    with pytest.raises(MappingError, match="CHANGE_ME"):
        parse_mapping(raw)
    assert len(parse_mapping(raw, allow_placeholder=True).points) == 6


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.update(extra=1), "unknown keys"),
        (lambda r: r["points"][0].update(direction="both"), "direction must be"),
        (lambda r: r["points"][0].update(webhook_id="x"), "only applies to loxone_to_ha"),
        (lambda r: r["points"][4].update(refresh_minutes=5), "only applies to ha_to_loxone"),
        (lambda r: r["points"][5].update(min=0), "do not apply to a switch"),
        (lambda r: r["points"][4].update(min=2000), "min 2000.0 > max"),
        (lambda r: r["points"][4].update(step=0), "step must be > 0"),
        (lambda r: r["points"][5].update(webhook_id=r["points"][4]["webhook_id"]), "duplicate webhook_id"),
        (lambda r: r["points"][1].update(name="ess_soc"), "duplicate point name"),
        (lambda r: r["points"][1].update(loxone_input="Earnie_Batterie_SoC"), "duplicate Loxone input"),
        (lambda r: r["points"][0].update(loxone_input="Bad Name"), "Loxone name must match"),
        (lambda r: r["points"][4].update(ha_entity="select.delta_3_mode"), "unsupported target domain"),
        (lambda r: r["points"][0].update(ha_entity="switch.delta_3_x"), "only supported for loxone_to_ha"),
        (lambda r: r["loxone"].update(host="http://192.168.178.10"), "bare IP/hostname"),
        (lambda r: r["derived_sensors"][0].update(name="Other Name"), "derives the entity id from the name"),
        (lambda r: r["derived_sensors"][0].update(plus=[]), "at least one entity"),
    ],
)
def test_invalid_mapping_fails_loud(mutate, message: str) -> None:
    raw = copy.deepcopy(_raw())
    mutate(raw)
    with pytest.raises(MappingError, match=message):
        parse_mapping(raw)


# --- HA package -----------------------------------------------------------------------


def test_package_is_valid_yaml_with_expected_blocks() -> None:
    package = _load_package(render_package(_mapping()))
    assert set(package) == {"rest_command", "template", "automation"}
    assert package["rest_command"]["loxone_push_ess_soc"] == {
        "url": "http://192.168.178.10/jdev/sps/io/Earnie_Batterie_SoC/{{ value }}",
        "username": "<secret:loxone_user>",
        "password": "<secret:loxone_pass>",
    }
    # Loxone -> HA points never get a rest_command: there is no Virtual Input on that path.
    assert set(package["rest_command"]) == {
        "loxone_push_ess_soc", "loxone_push_ess_power", "loxone_push_ess_soc_max", "loxone_push_ess_soc_min",
    }
    assert [a["id"] for a in package["automation"]] == [
        f"ha_loxone_bridge_{n}"
        for n in ("ess_soc", "ess_power", "ess_soc_max", "ess_soc_min", "ac_charge_limit", "grid_bypass")
    ]


def test_loxone_port_appears_only_when_not_default() -> None:
    raw = _raw()
    raw["loxone"]["port"] = 8080
    package = _load_package(render_package(_mapping(raw)))
    assert package["rest_command"]["loxone_push_ess_soc"]["url"].startswith("http://192.168.178.10:8080/jdev/")


def test_push_automation_triggers_and_guard() -> None:
    auto = _automation(_load_package(render_package(_mapping())), "ess_soc")
    assert auto["triggers"] == [
        {"trigger": "state", "entity_id": "sensor.delta_3_main_battery_level"},
        {"trigger": "homeassistant", "event": "start"},
        {"trigger": "time_pattern", "minutes": "/5"},
    ]
    guard = auto["conditions"][0]["value_template"]
    entity = "sensor.delta_3_main_battery_level"
    assert _render(guard, {entity: "55"}) == "True"
    assert _render(guard, {entity: "unavailable"}) == "False"
    value = auto["actions"][0]["data"]["value"]
    assert _render(value, {entity: "55"}) == "55.0"


def test_push_automation_without_refresh_has_no_time_pattern() -> None:
    raw = _raw()
    del raw["points"][0]["refresh_minutes"]
    auto = _automation(_load_package(render_package(_mapping(raw))), "ess_soc")
    assert [t["trigger"] for t in auto["triggers"]] == ["state", "homeassistant"]


def test_derived_net_power_and_availability() -> None:
    sensor = _load_package(render_package(_mapping()))["template"][0]["sensor"][0]
    assert sensor["unique_id"] == "ecoflow_ess_power_ehal"
    states = {"sensor.delta_3_total_out_power": "120", "sensor.delta_3_total_in_power": "800"}
    assert float(_render(sensor["state"], states)) == -680.0  # EHAL sign: + discharge, - charge
    assert _render(sensor["availability"], states) == "True"
    states["sensor.delta_3_total_in_power"] = "unavailable"
    # No silent 0: the sensor turns unavailable and the push automation's guard blocks it.
    assert _render(sensor["availability"], states) == "False"


def test_webhook_automation_for_number_clamps_and_rounds() -> None:
    auto = _automation(_load_package(render_package(_mapping())), "ac_charge_limit")
    trigger = auto["triggers"][0]
    assert trigger == {
        "trigger": "webhook",
        "webhook_id": "test_ac_charge_limit_Zq81xKp",
        "allowed_methods": ["GET"],
        "local_only": True,
    }
    target = auto["actions"][0]["variables"]["target"]

    def evaluate(v: str) -> float:
        return float(_render(target, trigger={"query": {"v": v}}))

    assert evaluate("812.000") == 800.0  # Loxone <v> sends three decimals
    assert evaluate("830") == 850.0
    assert evaluate("20") == 100.0
    assert evaluate("9999") == 1500.0

    guard = auto["conditions"][0]["value_template"]
    assert _render(guard, trigger={"query": {"v": "800.000"}}) == "True"
    assert _render(guard, trigger={"query": {"v": "abc"}}) == "False"
    assert _render(guard, trigger={"query": {}}) == "False"

    assert auto["actions"][2]["action"] == "number.set_value"
    assert auto["actions"][2]["target"] == {"entity_id": "number.delta_3_ac_charging_power"}


def test_webhook_automation_skips_unchanged_number() -> None:
    auto = _automation(_load_package(render_package(_mapping())), "ac_charge_limit")
    differs = auto["actions"][1]["value_template"]
    entity = "number.delta_3_ac_charging_power"
    assert _render(differs, {entity: "800.0"}, target=800.0) == "False"
    assert _render(differs, {entity: "500.0"}, target=800.0) == "True"


def test_webhook_automation_for_switch_maps_1_to_on() -> None:
    auto = _automation(_load_package(render_package(_mapping())), "grid_bypass")
    want_on = auto["actions"][0]["variables"]["want_on"]
    assert _render(want_on, trigger={"query": {"v": "1"}}) == "True"
    assert _render(want_on, trigger={"query": {"v": "0"}}) == "False"
    choose = auto["actions"][2]["choose"][0]
    assert choose["sequence"][0]["action"] == "switch.turn_on"
    assert auto["actions"][2]["default"][0]["action"] == "switch.turn_off"
    assert auto["actions"][2]["default"][0]["target"] == {"entity_id": "switch.delta_3_grid_bypass"}


def test_webhook_local_only_can_be_disabled() -> None:
    raw = _raw()
    raw["ha"]["webhook_local_only"] = False
    auto = _automation(_load_package(render_package(_mapping(raw))), "grid_bypass")
    assert auto["triggers"][0]["local_only"] is False


# --- Loxone Virtual Output template ---------------------------------------------------

_ROOT_ATTRS = ["HintText", "Title", "Comment", "Address", "CmdInit", "CloseAfterSend", "CmdSep"]
_ANALOG_ATTRS = [
    "Title", "Comment", "CmdOnMethod", "CmdOffMethod", "CmdOn", "CmdOnHTTP", "CmdOnPost", "CmdOff",
    "CmdOffHTTP", "CmdOffPost", "CmdAnswer", "Analog", "Repeat", "RepeatRate",
    "SourceValLow", "DestValLow", "SourceValHigh", "DestValHigh", "HintText",
]
_DIGITAL_ATTRS = [a for a in _ANALOG_ATTRS if not a.startswith(("SourceVal", "DestVal"))]


def test_virtual_out_has_loxone_export_shape_and_webhook_commands() -> None:
    root = ET.fromstring(render_virtual_out(_mapping()))
    assert root.tag == "VirtualOut"
    assert list(root.attrib) == _ROOT_ATTRS
    assert root.get("Address") == "http://192.168.178.20:8123"
    info, *cmds = list(root)
    assert info.tag == "Info" and info.attrib == {"templateType": "3", "minVersion": "17010630"}
    by_title = {c.get("Title"): c for c in cmds}
    assert set(by_title) == {"HA_Delta3_AcChargeLimit", "HA_Delta3_GridBypass"}

    analog = by_title["HA_Delta3_AcChargeLimit"]
    assert list(analog.attrib) == _ANALOG_ATTRS
    assert analog.get("Analog") == "true"
    assert analog.get("CmdOn") == "/api/webhook/test_ac_charge_limit_Zq81xKp?v=<v>"
    assert analog.get("CmdOff") == ""
    assert (analog.get("Repeat"), analog.get("RepeatRate")) == ("30", "30")

    digital = by_title["HA_Delta3_GridBypass"]
    assert list(digital.attrib) == _DIGITAL_ATTRS
    assert digital.get("Analog") == "false"
    assert digital.get("CmdOn") == "/api/webhook/test_grid_bypass_Zq81xKp?v=1"
    assert digital.get("CmdOff") == "/api/webhook/test_grid_bypass_Zq81xKp?v=0"

    for cmd in cmds:
        # In a Virtual Output command the VI-style escape arrives as the control character 0x0B.
        assert _BACKSLASH_V not in (cmd.get("CmdOn") or "")


# --- checklist and CLI ----------------------------------------------------------------


def test_checklist_lists_inputs_and_commands_without_webhook_ids() -> None:
    text = render_checklist(_mapping(), package_file=PACKAGE_FILE, xml_file=XML_FILE)
    assert "`Earnie_Batterie_SoC`" in text
    assert "`HA_Delta3_AcChargeLimit`" in text
    assert "begrenzt auf 100.0…1500.0, Raster 50" in text
    assert "Zq81xKp" not in text


def test_generate_writes_package_xml_and_checklist(tmp_path: Path) -> None:
    mapping_file = tmp_path / "m.json"
    mapping_file.write_text(json.dumps(_raw()), encoding="utf-8")
    written = generate(mapping_file, tmp_path / "out")
    assert [p.name for p in written] == [PACKAGE_FILE, XML_FILE, CHECKLIST_FILE]
    assert (tmp_path / "out" / XML_FILE).read_bytes().startswith(bytes([0xEF, 0xBB, 0xBF]))


def test_generate_skips_xml_without_outgoing_points(tmp_path: Path) -> None:
    raw = _raw()
    raw["points"] = [p for p in raw["points"] if p["direction"] == "ha_to_loxone"]
    mapping_file = tmp_path / "m.json"
    mapping_file.write_text(json.dumps(raw), encoding="utf-8")
    assert [p.name for p in generate(mapping_file, tmp_path / "out")] == [PACKAGE_FILE, CHECKLIST_FILE]


def test_cli_returns_2_on_placeholder(tmp_path: Path, capsys) -> None:
    assert main(["--mapping", str(_EXAMPLE), "--out-dir", str(tmp_path)]) == 2
    assert "CHANGE_ME" in capsys.readouterr().err
    assert not (tmp_path / PACKAGE_FILE).exists()


def test_tool_stays_decoupled_from_earnie_runtime() -> None:
    forbidden = ("ehal", "config", "house_config", "integrations", "optimizer", "settings", "runtime_store")
    for path in _PKG_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name} imports {name}"
