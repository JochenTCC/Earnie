"""2.7.q Q4: VI template generator with qualified Check keys."""
from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import pilot_vi_template_gen as gen


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "house_profiles.json").write_text(
        json.dumps(
            {
                "plant": {
                    "ehal_bindings": {
                        "sens_grid_power_active": "Earnie_Netzleistung",
                        "set_grid_export_power_limit": "Earnie_Limit",
                        "set_ess_active_power": "Earnie_Batterie_Sollleistung",
                    }
                },
                "profiles": {
                    "p": {
                        "consumers": [
                            {
                                "id": "e_auto",
                                "type": "ev",
                                "ehal_bindings": {
                                    "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                                    "set_evcs_mode": "Earnie_EAuto_Modus",
                                    "sens_evcs_soc_act": "Earnie_EAuto_SOC",
                                },
                            },
                            {
                                "id": "waermepumpe",
                                "type": "thermal_annual",
                                "ehal_bindings": {
                                    "set_enable": "Earnie_Waermepumpe_Freigabe",
                                },
                            },
                            {
                                "id": "pool_swimspa",
                                "type": "thermal_rc",
                                "ehal_bindings": {
                                    "set_enable": "Earnie_Pool_Freigabe",
                                },
                            },
                            {
                                "id": "pool_filter",
                                "type": "thermal_rc",
                                "ehal_bindings": {
                                    "set_enable": "Earnie_Pool_Filter_Freigabe",
                                },
                            },
                            {
                                "id": "trockner",
                                "type": "generic",
                                "ehal_bindings": {
                                    "flex.trockner.set_enable": "Earnie_Verbraucher_Freigabe",
                                    "flex.trockner.sens_power_act": "Zähler Trockner",
                                },
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (cfg / "components.json").write_text(
        json.dumps(
            {
                "batteries": [
                    {
                        "id": "15_kwh_speicher",
                        "ehal_bindings": {
                            "ess.15_kwh_speicher.set_ess_mode": "Earnie_Steuerbefehl",
                            "ess.15_kwh_speicher.sens_ess_soc": "Earnie_Batterie_SoC",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return cfg


def test_collect_only_writes_with_qualified_ids(tmp_path: Path) -> None:
    signals = {s.ehal_id: s for s in gen.collect_write_signals(_config(tmp_path))}
    assert set(signals) == {
        "set_grid_export_power_limit",
        "set_ess_active_power",
        "evcs.e_auto.set_evcs_max_current",
        "evcs.e_auto.set_evcs_mode",
        "heatpump.waermepumpe.set_enable",
        "pool.pool_swimspa.set_enable",
        "pool.pool_filter.set_enable",
        "consumer.trockner.set_enable",
        "ess.15_kwh_speicher.set_ess_mode",
    }
    assert signals["consumer.trockner.set_enable"].title == "consumer_trockner_set_enable"
    assert signals["evcs.e_auto.set_evcs_max_current"].group == "EV"
    assert signals["heatpump.waermepumpe.set_enable"].group == "Waermepumpe"
    assert signals["pool.pool_swimspa.set_enable"].group == "Pool"


def test_vi_title_from_qualified_id() -> None:
    assert gen.vi_title_from_qualified_id("consumer.trockner.set_enable") == (
        "consumer_trockner_set_enable"
    )
    assert gen.vi_title_from_qualified_id("heartbeat_ts") == "heartbeat_ts"


def test_render_check_and_sticky_analog(tmp_path: Path) -> None:
    sigs = [
        s
        for s in gen.collect_write_signals(_config(tmp_path))
        if s.ehal_id == "consumer.trockner.set_enable"
    ]
    text = gen.render_template("Verbraucher", sigs, host="192.168.1.10", port=8541)
    root = ET.fromstring(text.encode("utf-8"))
    assert root.tag == "VirtualInHttp"
    assert root.get("Address") == "http://192.168.1.10:8541/ehal/loxone/status.json"
    assert root.get("PollingTime") == "10"
    info, *cmds = list(root)
    assert info.attrib == {"templateType": "2", "minVersion": "17010630"}
    cmd = cmds[0]
    assert cmd.get("Title") == "consumer_trockner_set_enable"
    assert cmd.get("Analog") == "true"
    assert cmd.get("Check") == '"consumer.trockner.set_enable":\\v'
    assert cmd.get("MinVal") == "0" and cmd.get("MaxVal") == "1"
    assert "&quot;consumer.trockner.set_enable&quot;:\\v" in text


def test_heartbeat_write_signal() -> None:
    sig = gen.heartbeat_write_signal()
    assert sig.ehal_id == "heartbeat_ts"
    assert sig.title == "heartbeat_ts"
    text = gen.render_template("Heartbeat", [sig], host="h", port=8541)
    cmd = next(c for c in ET.fromstring(text.encode("utf-8")) if c.tag == "VirtualInHttpCmd")
    assert cmd.get("Check") == '"heartbeat_ts":\\v'


def test_write_template_has_bom(tmp_path: Path) -> None:
    out = tmp_path / "t.xml"
    gen.write_template(out, "<a/>")
    assert out.read_bytes().startswith(bytes([0xEF, 0xBB, 0xBF]))


def test_main_writes_files_and_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "pilot_vi_template_gen",
            "--config-dir",
            str(cfg),
            "--host",
            "10.0.0.1",
            "--out-dir",
            str(out),
        ],
    )
    assert gen.main() == 0
    xmls = sorted(out.glob("VI_Pilot_*.xml"))
    assert xmls
    assert (out / "Pilot-VI-Signalliste.csv").is_file()
    with open(out / "Pilot-VI-Signalliste.csv", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[0] == ["Datei", "VI-Cmd-Titel", "EHAL-ID", "Bisheriger Name (Merker)", "Typ"]
    ehal_ids = {r[2] for r in rows[1:]}
    assert "consumer.trockner.set_enable" in ehal_ids
    assert "heartbeat_ts" in ehal_ids
