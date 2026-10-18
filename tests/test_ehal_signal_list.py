"""Signal list rows + export ZIP (2.7.q Q7 / Binding P5b)."""
from __future__ import annotations

import zipfile
from io import BytesIO

from unittest.mock import patch

from ehal.signal_catalog import set_binding_activation
from ehal.signal_export import build_export_zip
from ehal.signal_list import build_signal_rows, signals_for_export
from ui.ehal_signal_list import _default_host, _table_records
from ui.ehal_unit_display import units_for_field


def _minimal_docs() -> tuple[dict, dict]:
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_pv_production_active": "PV",
                "sens_grid_power_active": "Grid",
                "set_grid_export_power_limit": "ExportLimit",
            }
        },
        "profiles": {
            "live": {
                "consumers": [
                    {
                        "id": "waschmaschine",
                        "type": "generic",
                        "ehal_bindings": {
                            "flex.waschmaschine.sens_power_act": "WM_P",
                            "flex.waschmaschine.set_enable": "WM_En",
                        },
                    }
                ]
            }
        },
    }
    components = {
        "batteries": [
            {
                "id": "15_kwh_speicher",
                "control": "limits_only",
                "ehal_bindings": {
                    "ess.15_kwh_speicher.sens_ess_soc": "SoC",
                    "ess.15_kwh_speicher.set_ess_charge_power_limit": "ChgLim",
                },
            }
        ]
    }
    return house, components


def test_build_signal_rows_has_read_and_write() -> None:
    house, components = _minimal_docs()
    rows = build_signal_rows(
        house,
        components,
        inbox={"sens_pv_production_active": {"last_ts": "2026-10-09T12:00:00+00:00"}},
        published={
            "grid.meter.set_grid_export_power_limit": {
                "value": 1000.0,
                "published_at": "2026-10-09T12:01:00+00:00",
            }
        },
        fetched_at="2026-10-09T12:01:05+00:00",
    )
    ids = {r.ehal_id for r in rows}
    assert "sens_pv_production_active" in ids
    assert "grid.meter.set_grid_export_power_limit" in ids
    assert "consumer.waschmaschine.set_enable" in ids
    assert "ess.15_kwh_speicher.sens_ess_soc" in ids
    assert "heartbeat" in ids
    assert "heartbeat_ts" in ids
    assert "request_optimize" in ids
    opt = next(r for r in rows if r.ehal_id == "request_optimize")
    assert opt.direction == "read"
    assert opt.group == "Status"
    assert opt.match_kind == "never"
    old = build_signal_rows(
        house,
        components,
        inbox={
            "request_optimize": {
                "last_ts": "2026-01-01T00:00:00+00:00",
                "value": 1.0,
            }
        },
        published={},
        fetched_at=None,
    )
    opt_old = next(r for r in old if r.ehal_id == "request_optimize")
    assert opt_old.match_kind == "ok"
    assert opt_old.match_text.startswith("vor ")
    pv = next(r for r in rows if r.ehal_id == "sens_pv_production_active")
    assert pv.direction == "read"
    assert pv.match_kind in ("ok", "stale")
    assert pv.is_required is True
    assert pv.is_activated is True
    write = next(r for r in rows if r.ehal_id == "grid.meter.set_grid_export_power_limit")
    assert write.direction == "write"
    assert write.match_kind == "published"
    assert any("Einspeiseleistung" in label for label in write.required_by)


def test_catalog_includes_optional_inactive() -> None:
    house, components = _minimal_docs()
    rows = build_signal_rows(house, components, inbox={}, published={}, fetched_at=None)
    # Optional ESS power is in the role catalog but not activated in fixtures.
    opt = next(
        (r for r in rows if r.ehal_id.endswith("sens_ess_power")),
        None,
    )
    assert opt is not None
    assert opt.is_required is False
    assert opt.is_activated is False
    assert opt.match_kind == "inactive"
    soc = next(r for r in rows if r.ehal_id.endswith("sens_ess_soc"))
    assert soc.is_required is True
    assert soc.is_activated is True


def test_signal_list_table_has_pflicht_and_units() -> None:
    house, components = _minimal_docs()
    rows = build_signal_rows(house, components, inbox={}, published={}, fetched_at=None)
    table = _table_records(rows, backend="loxone")
    ess_power = next(
        (r for r in table if r["EHAL-ID"].endswith("sens_ess_soc")),
        None,
    )
    assert ess_power is not None
    assert ess_power["Hub-Einheit"] == "%"
    assert ess_power["EHAL-Einheit"] == "%"
    assert ess_power["Pflicht"] == "Pflicht"
    assert ess_power["aktiviert"] == "ja"
    charge = next(
        (
            r
            for r in table
            if r["EHAL-ID"].endswith("set_ess_charge_power_limit")
        ),
        None,
    )
    assert charge is not None
    units = units_for_field(charge["EHAL-ID"], "loxone")
    assert charge["Hub-Einheit"] == units.hub_unit == "kW"
    assert charge["EHAL-Einheit"] == units.ehal_unit == "W"
    ha_table = _table_records(rows, backend="ha")
    assert "Hub-Einheit" not in ha_table[0]


def test_export_mode_all_includes_inactive() -> None:
    house, components = _minimal_docs()
    needed_r, needed_w = signals_for_export(house, components, mode="needed")
    all_r, all_w = signals_for_export(house, components, mode="all")
    needed_ids = {s.ehal_id for s in needed_r + needed_w}
    all_ids = {s.ehal_id for s in all_r + all_w}
    assert "ess.15_kwh_speicher.sens_ess_soc" in needed_ids
    assert "ess.15_kwh_speicher.sens_ess_power" not in needed_ids
    assert "ess.15_kwh_speicher.sens_ess_power" in all_ids
    assert needed_ids <= all_ids


def test_set_binding_activation_optional_toggle() -> None:
    house, components = _minimal_docs()
    key = "ess.15_kwh_speicher.sens_ess_power"
    house2, components2 = set_binding_activation(
        house,
        components,
        component_kind="battery",
        entity_id="15_kwh_speicher",
        binding_key=key,
        activated=True,
    )
    assert key in components2["batteries"][0]["ehal_bindings"]
    assert components2["batteries"][0]["ehal_bindings"][key] == ""
    _, components3 = set_binding_activation(
        house2,
        components2,
        component_kind="battery",
        entity_id="15_kwh_speicher",
        binding_key=key,
        activated=False,
    )
    assert key not in components3["batteries"][0]["ehal_bindings"]


def test_set_binding_activation_rejects_required_off() -> None:
    house, components = _minimal_docs()
    try:
        set_binding_activation(
            house,
            components,
            component_kind="battery",
            entity_id="15_kwh_speicher",
            binding_key="ess.15_kwh_speicher.sens_ess_soc",
            activated=False,
            is_required=True,
        )
    except ValueError as exc:
        assert "required" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_export_zip_contains_vo_and_vi() -> None:
    house, components = _minimal_docs()
    payload = build_export_zip(house, components, host="192.168.1.10", port=8541)
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        names = set(zf.namelist())
        readme = zf.read("README.txt").decode("utf-8")
    assert "README.txt" in names
    assert "Earnie-VO-Signalliste.csv" in names
    assert "Earnie-VI-Signalliste.csv" in names
    assert any(n.startswith("VO_Earnie_") and n.endswith(".xml") for n in names)
    assert any(n.startswith("VI_Earnie_") and n.endswith(".xml") for n in names)
    assert "PUSH_TOKEN_HIER_ERSETZEN" in readme
    assert "PILOT_TOKEN_HIER_ERSETZEN" not in readme
    assert "VO_Earnie_*.xml" in readme


def test_default_host_prefers_env_over_local_ip(monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_LAN_IP", "192.168.178.40")
    with patch(
        "integrations.ha_supervisor.supervisor_host_lan_ipv4", return_value="10.0.0.1"
    ), patch(
        "integrations.integration_scanner.local_ipv4_address",
        return_value="192.168.1.5",
    ):
        assert _default_host() == "192.168.178.40"


def test_default_host_uses_local_ipv4_when_env_empty(monkeypatch) -> None:
    monkeypatch.delenv("EARNIE_LAN_IP", raising=False)
    monkeypatch.delenv("EARNIE_HOST", raising=False)
    with patch(
        "integrations.ha_supervisor.supervisor_host_lan_ipv4", return_value=None
    ), patch(
        "integrations.integration_scanner.local_ipv4_address",
        return_value="192.168.1.5",
    ):
        assert _default_host() == "192.168.1.5"


def test_default_host_skips_docker_bridge_ipv4(monkeypatch) -> None:
    monkeypatch.delenv("EARNIE_LAN_IP", raising=False)
    monkeypatch.delenv("EARNIE_HOST", raising=False)
    with patch(
        "integrations.ha_supervisor.supervisor_host_lan_ipv4", return_value=None
    ), patch(
        "integrations.integration_scanner.local_ipv4_address",
        return_value="172.17.0.2",
    ):
        assert _default_host() == ""
