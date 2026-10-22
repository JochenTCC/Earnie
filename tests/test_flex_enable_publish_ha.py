"""HA backend: the live cycle publishes the flex ``set_enable`` (bench finding B1 / L14).

The network-backend branch of ``main.py`` wrote ESS limits, the EVCS current and the WR
AC limits only; the optimizer's heat pump / pool / generic enables never reached
``status.json``. The EV current is written through the EVCS adapter, so it must not be
published a second time.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import main as main_module
from integrations import ehal_live
from integrations.loxone_comm_trace import LoxoneWriteRecord
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
from tests.main_run_harness import patch_main_run

HEATPUMP_QID = "heatpump.waermepumpe.set_enable"
POOL_QID = "pool.pool_filter.set_enable"


def _consumers() -> list[dict]:
    return [
        {
            "id": "e_auto",
            "name": "E-Auto",
            "type": "ev",
            "nominal_power_kw": 11.0,
            "min_power_kw": 1.4,
            "ehal_bindings": {
                "set_evcs_max_current": "",
                "evcs.e_auto.set_evcs_max_current": "",
                "evcs.e_auto.set_evcs_mode": "",
            },
        },
        {
            "id": "waermepumpe",
            "name": "Haus Wärme",
            "type": "thermal_annual",
            "nominal_power_kw": 3.5,
            "ehal_bindings": {HEATPUMP_QID: ""},
        },
        {
            "id": "pool_filter",
            "name": "Pool",
            "type": "thermal_rc",
            "nominal_power_kw": 2.8,
            "ehal_bindings": {POOL_QID: ""},
        },
    ]


def _record(qid, value, *, io_name=""):
    return LoxoneWriteRecord(
        io_name=io_name or qid, value=float(value), success=True, written_at="2026-10-22T14:54:38"
    )


def test_flex_enables_are_published_and_the_ev_current_is_not():
    published: list[tuple[str, float]] = []

    def _pub(qid, value, *, io_name=""):
        published.append((qid, float(value)))
        return _record(qid, value, io_name=io_name)

    powers = {"e_auto": 2.0, "waermepumpe": 3.5, "pool_filter": 0.0}
    with patch(
        "integrations.loxone_writes.config.get_flexible_consumers",
        return_value=_consumers(),
    ), patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub):
        from integrations.loxone_writes import send_flexible_consumer_enables

        records = send_flexible_consumer_enables(powers, {}, {})

    assert published == [(HEATPUMP_QID, 1.0), (POOL_QID, 0.0)]
    assert len(records) == 2
    assert not any("evcs" in qid for qid, _ in published)


def test_the_loxone_path_still_publishes_every_flex_output():
    # send_flexible_consumer_states keeps publishing the EV current and mode as before.
    published: list[str] = []

    def _pub(qid, value, *, io_name=""):
        published.append(qid)
        return _record(qid, value, io_name=io_name)

    powers = {"e_auto": 2.0, "waermepumpe": 3.5, "pool_filter": 0.0}
    with patch(
        "integrations.loxone_writes.config.get_flexible_consumers",
        return_value=_consumers(),
    ), patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub):
        from integrations.loxone_writes import send_flexible_consumer_states

        send_flexible_consumer_states(powers, {}, {})

    assert "evcs.e_auto.set_evcs_max_current" in published
    assert HEATPUMP_QID in published and POOL_QID in published


def test_write_flex_enables_for_ha_returns_run_state_rows():
    records = [_record(HEATPUMP_QID, 1.0), _record(POOL_QID, 0.0)]
    with patch.object(ehal_live, "write_flexible_consumer_enables", return_value=records):
        rows = ehal_live.write_flex_enables_for_ha({"waermepumpe": 3.5})
    assert rows == [
        {"field": HEATPUMP_QID, "value": 1.0, "success": True, "written_at": "2026-10-22T14:54:38", "message": ""},
        {"field": POOL_QID, "value": 0.0, "success": True, "written_at": "2026-10-22T14:54:38", "message": ""},
    ]


def _patch_network_branch(monkeypatch, *, ha: bool):
    patch_main_run(monkeypatch, silent=False)
    monkeypatch.setattr(main_module.ehal_live, "is_ehal_network_backend", lambda: True)
    monkeypatch.setattr(main_module.ehal_live, "is_ha_backend", lambda: ha)
    monkeypatch.setattr(main_module.ehal_live, "write_ess_setpoints_from_control", lambda *a, **k: (None, []))
    monkeypatch.setattr(main_module.ehal_live, "write_evcs_max_current_from_consumers", lambda *a, **k: (None, []))
    monkeypatch.setattr(main_module.ehal_live, "write_inv_ac_limits_from_plan", lambda *a, **k: (None, []))
    loxone_flex = MagicMock(return_value=[])
    monkeypatch.setattr(main_module.ehal_live, "write_flexible_consumer_states", loxone_flex)
    saved: list[dict] = []
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda payload: saved.append(payload))
    return saved, loxone_flex


def test_main_ha_cycle_publishes_flex_enables_and_traces_them(monkeypatch):
    saved, loxone_flex = _patch_network_branch(monkeypatch, ha=True)
    rows = [{"field": HEATPUMP_QID, "value": 1.0, "success": True, "written_at": "t", "message": ""}]
    flex_enables = MagicMock(return_value=rows)
    monkeypatch.setattr(main_module.ehal_live, "write_flex_enables_for_ha", flex_enables)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    flex_enables.assert_called_once()
    loxone_flex.assert_not_called()  # the Loxone writer must not run on the network backend
    assert saved and saved[0]["ehal_writes"] == rows
    assert saved[0]["loxone_writes"] is None


def test_main_openems_cycle_does_not_publish_flex_enables(monkeypatch):
    saved, _loxone_flex = _patch_network_branch(monkeypatch, ha=False)
    flex_enables = MagicMock(return_value=[])
    monkeypatch.setattr(main_module.ehal_live, "write_flex_enables_for_ha", flex_enables)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    flex_enables.assert_not_called()
    assert saved and saved[0]["ehal_writes"] == []
