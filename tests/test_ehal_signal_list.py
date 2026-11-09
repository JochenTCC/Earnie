"""Signal list rows + export ZIP (2.7.q Q7 / Binding P5b)."""
from __future__ import annotations

import zipfile
from io import BytesIO

from unittest.mock import patch

from ehal.signal_catalog import set_binding_activation
import pytest

from ehal.signal_export import build_export_zip, normalize_export_host
from ehal.signal_list import build_signal_rows, signals_for_export
from ui.ehal_signal_list import _default_host, _table_records
from ui.ehal_unit_display import units_for_field


def _minimal_docs() -> tuple[dict, dict]:
    house = {
        "plant": {
            "ehal_bindings": {
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
    assert "grid.meter.sens_grid_power_active" in ids
    assert "sens_pv_production_active" not in ids
    assert "grid.meter.set_grid_export_power_limit" in ids
    assert "consumer.waschmaschine.set_enable" in ids
    assert "ess.15_kwh_speicher.sens_ess_soc" in ids
    assert "heartbeat_smarthome" in ids
    assert "heartbeat_earnie" in ids
    assert "request_optimize" in ids
    hb_read = next(r for r in rows if r.ehal_id == "heartbeat_smarthome")
    assert hb_read.direction == "read"
    assert hb_read.is_required is True
    assert hb_read.is_activated is True
    assert hb_read.binding_key == ""
    assert "Smarthome" in hb_read.meaning
    hb_write = next(r for r in rows if r.ehal_id == "heartbeat_earnie")
    assert hb_write.direction == "write"
    assert hb_write.is_required is True
    assert hb_write.binding_key == ""
    assert "Earnie" in hb_write.meaning
    opt = next(r for r in rows if r.ehal_id == "request_optimize")
    assert opt.direction == "read"
    assert opt.group == "Status"
    assert opt.match_kind == "never"
    assert opt.is_required is False
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
    grid = next(r for r in rows if r.ehal_id == "grid.meter.sens_grid_power_active")
    assert grid.direction == "read"
    assert grid.is_required is True
    assert grid.is_activated is True
    write = next(r for r in rows if r.ehal_id == "grid.meter.set_grid_export_power_limit")
    assert write.direction == "write"
    assert write.match_kind == "published"
    assert any("Einspeiseleistung" in label for label in write.required_by)


def test_catalog_includes_optional_inactive() -> None:
    house, components = _minimal_docs()
    rows = build_signal_rows(house, components, inbox={}, published={}, fetched_at=None)
    # Optional ESS limits are in the role catalog but not activated in fixtures.
    opt = next(
        (r for r in rows if r.ehal_id.endswith("get_ess_soc_max")),
        None,
    )
    assert opt is not None
    assert opt.is_required is False
    assert opt.is_activated is False
    assert opt.match_kind == "inactive"
    # Grid-tied house battery: plant ESS power is derived from it (HA testbed F14).
    power = next(r for r in rows if r.ehal_id.endswith("sens_ess_power"))
    assert power.is_required is True
    assert power.is_activated is False
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


def _ev_house(bindings: dict[str, str]) -> dict:
    return {
        "plant": {"ehal_bindings": {}},
        "profiles": {
            "live": {
                "consumers": [
                    {"id": "e_auto", "type": "ev", "ehal_bindings": bindings},
                ]
            }
        },
    }


def test_flat_and_qualified_consumer_key_are_one_signal() -> None:
    # The dm4 migration keeps the flat key and adds the qualified twin next to it.
    from ehal.push_signals import write_signals_from_docs

    house = _ev_house({"set_evcs_max_current": "", "evcs.e_auto.set_evcs_max_current": ""})
    ids = [s.ehal_id for s in write_signals_from_docs(house, {})]
    assert ids == ["evcs.e_auto.set_evcs_max_current"]


def test_duplicate_signal_keeps_the_loxone_name_of_either_spelling() -> None:
    from ehal.push_signals import write_signals_from_docs

    flat_named = _ev_house({"set_evcs_max_current": "EV_A", "evcs.e_auto.set_evcs_max_current": ""})
    qualified_named = _ev_house({"set_evcs_max_current": "", "evcs.e_auto.set_evcs_max_current": "EV_A"})
    for house in (flat_named, qualified_named):
        (signal,) = write_signals_from_docs(house, {})
        assert signal.old_name == "EV_A"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.168.1.10", "192.168.1.10"),
        (" http://192.168.1.10/ ", "192.168.1.10"),
        ("HTTPS://earnie.local", "earnie.local"),
    ],
)
def test_normalize_export_host_strips_pasted_scheme(raw: str, expected: str) -> None:
    # Reporter pasted the browser address; the VO/VI Address got the scheme twice.
    assert normalize_export_host(raw) == expected


@pytest.mark.parametrize(
    "raw", ["http://192.168.1.10:8541", "192.168.1.10/ehal", "ftp://192.168.1.10"]
)
def test_normalize_export_host_rejects_port_or_path(raw: str) -> None:
    with pytest.raises(ValueError, match="ohne Port"):
        normalize_export_host(raw)


def test_export_zip_address_has_one_scheme_after_normalizing() -> None:
    house, components = _minimal_docs()
    payload = build_export_zip(
        house, components, host=normalize_export_host("http://192.168.1.10"), port=8541
    )
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        xml = [zf.read(n).decode("utf-8-sig") for n in zf.namelist() if n.endswith(".xml")]
    assert xml
    assert all("http://http" not in text for text in xml)
    assert any('Address="http://192.168.1.10:8541' in text for text in xml)


def test_export_includes_the_plant_energy_counters_live_read_expects() -> None:
    house, components = _minimal_docs()
    house["plant"]["ehal_bindings"]["sens_pv_energy"] = ""
    reads, _writes = signals_for_export(house, components, mode="needed")
    needed = {s.ehal_id for s in reads}
    assert "sens_pv_energy" in needed
    assert "grid.meter.sens_grid_energy_import" not in needed  # optional, not activated
    reads_all, _ = signals_for_export(house, components, mode="all")
    assert {
        "sens_pv_energy",
        "grid.meter.sens_grid_energy_import",
        "grid.meter.sens_grid_energy_export",
    } <= {s.ehal_id for s in reads_all}


def test_every_plant_live_read_field_is_in_the_export() -> None:
    """Live-Lesen and the export must cover the same plant reads (regression: energy counters)."""
    from ehal.qualified_ids import field_kind
    from integrations.ehal_debug_fields import PLANT_HOUSE_LIVE_READ_FIELDS

    house, components = _minimal_docs()
    reads_all, _ = signals_for_export(house, components, mode="all")
    exported_kinds = {field_kind(s.ehal_id) for s in reads_all if s.group == "Plant"}
    assert set(PLANT_HOUSE_LIVE_READ_FIELDS) <= exported_kinds


# Signal list of a real setup (Live-Lesen, 2026-10-31); IDs depend on the entity ids.
_SETUP_LIVE_READ_IDS = {
    "grid.meter.sens_grid_power_active",
    "sens_power_consumers",
    "sens_temperature_outside",
    "sens_absent_mode",
    "grid.meter.get_grid_export_power_limit",
    "sens_pv_energy",
    "grid.meter.sens_grid_energy_import",
    "grid.meter.sens_grid_energy_export",
    "ess.5_kwh_speicher.sens_ess_soc",
    "ess.5_kwh_speicher.sens_ess_power",
    "ess.5_kwh_speicher.sens_ess_energy_charge",
    "ess.5_kwh_speicher.sens_ess_energy_discharge",
    "ess.5_kwh_speicher.get_ess_soc_min",
    "ess.5_kwh_speicher.get_ess_soc_max",
    "ess.5_kwh_speicher.get_ess_max_charge_power",
    "ess.5_kwh_speicher.get_ess_max_discharge_power",
    "inv.wr_main.sens_inv_power_ac",
    "inv.wr_main.sens_inv_power_pv",
    "inv.wr_main.get_inv_max_ac_power",
    "inv.wr_main.get_inv_max_pv_power",
    "pv.dach_sued.sens_pv_production_active",
    "heatpump.waermepumpe.sens_power_act",
    "heatpump.waermepumpe.sens_consumer_active",
    "heatpump.waermepumpe.sens_energy_total",
    "heatpump.waermepumpe.sens_temperature_heat_storage",
    "heatpump.waermepumpe.sens_temperature_heat_storage_low",
    "evcs.e_auto.sens_evcs_active_power",
    "evcs.e_auto.sens_evcs_connected",
    "ev.e_auto.sens_evcs_soc_act",
    "evcs.e_auto.get_evcs_nominal_current",
    "ev.e_auto.sens_evcs_bat_capacity",
    "ev.e_auto.get_evcs_ready_by_time",
    "ev.e_auto.get_evcs_limit_soc",
    "ev.e_auto.get_evcs_soc_min_immediate",
    "ev.e_auto.sens_ev_connected",
    "ev.e_auto.sens_ev_charge_power",
    "ev.e_auto.sens_energy_total",
    "consumer.verbraucher.sens_power_act",
    "consumer.verbraucher.sens_consumer_active",
    "consumer.verbraucher.sens_energy_total",
}


def _setup_docs() -> tuple[dict, dict]:
    consumers = [
        {"id": "waermepumpe", "type": "thermal_annual", "ehal_bindings": {}},
        {"id": "e_auto", "type": "ev", "ehal_bindings": {}},
        {"id": "verbraucher", "type": "generic", "ehal_bindings": {}},
    ]
    house = {"plant": {"ehal_bindings": {}}, "profiles": {"live": {"consumers": consumers}}}
    components = {
        "batteries": [{"id": "5_kwh_speicher", "control": "limits_only", "ehal_bindings": {}}],
        "inverters": [{"id": "wr_main", "ehal_bindings": {}}],
        "pv_systems": [{"id": "dach_sued", "inverter_id": "wr_main", "ehal_bindings": {}}],
    }
    return house, components


def test_export_covers_every_live_read_signal_of_a_real_setup() -> None:
    house, components = _setup_docs()
    reads, _writes = signals_for_export(house, components, mode="all")
    exported = {s.ehal_id for s in reads}
    assert _SETUP_LIVE_READ_IDS <= exported, sorted(_SETUP_LIVE_READ_IDS - exported)


def test_export_reads_match_live_read_fields(monkeypatch) -> None:
    """Export and Live-Lesen derive from the same entities, so they list the same reads."""
    from ehal.push_signals import HEARTBEAT_ID, REQUEST_OPTIMIZE_ID
    from integrations import ehal_debug_mapping as m

    house, components = _setup_docs()
    monkeypatch.setattr(m, "_all_live_batteries", lambda: components["batteries"])
    monkeypatch.setattr(m, "_all_live_inverters", lambda: components["inverters"])
    monkeypatch.setattr(m, "_all_live_pv_systems", lambda: components["pv_systems"])
    monkeypatch.setattr(
        m, "_all_live_consumers", lambda: house["profiles"]["live"]["consumers"]
    )
    live = set(m.expected_live_read_fields()) - {REQUEST_OPTIMIZE_ID}
    reads, _writes = signals_for_export(house, components, mode="all")
    exported = {s.ehal_id for s in reads} - {HEARTBEAT_ID}
    assert live == _SETUP_LIVE_READ_IDS
    assert exported == live, (sorted(live - exported), sorted(exported - live))
