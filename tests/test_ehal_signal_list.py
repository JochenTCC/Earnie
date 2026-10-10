"""Signal list rows + export ZIP (2.7.q Q7)."""
from __future__ import annotations

import zipfile
from io import BytesIO

from ehal.signal_export import build_export_zip
from ehal.signal_list import build_signal_rows
from ui.ehal_signal_list import _table_records
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
    pv = next(r for r in rows if r.ehal_id == "sens_pv_production_active")
    assert pv.direction == "read"
    assert pv.match_kind in ("ok", "stale")
    write = next(r for r in rows if r.ehal_id == "grid.meter.set_grid_export_power_limit")
    assert write.direction == "write"
    assert write.match_kind == "published"
    assert any("Einspeiseleistung" in label for label in write.required_by)


def test_signal_list_table_has_hub_and_ehal_units() -> None:
    house, components = _minimal_docs()
    rows = build_signal_rows(house, components, inbox={}, published={}, fetched_at=None)
    table = _table_records(rows)
    ess_power = next(
        (r for r in table if r["EHAL-ID"].endswith("sens_ess_soc")),
        None,
    )
    assert ess_power is not None
    assert ess_power["Hub-Einheit"] == "%"
    assert ess_power["EHAL-Einheit"] == "%"
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


def test_export_zip_contains_vo_and_vi() -> None:
    house, components = _minimal_docs()
    payload = build_export_zip(house, components, host="192.168.1.10", port=8541)
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        names = set(zf.namelist())
    assert "README.txt" in names
    assert "Pilot-VO-Signalliste.csv" in names
    assert "Pilot-VI-Signalliste.csv" in names
    assert any(n.startswith("VO_Pilot_") and n.endswith(".xml") for n in names)
    assert any(n.startswith("VI_Pilot_") and n.endswith(".xml") for n in names)
