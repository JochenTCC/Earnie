"""OpenEMS has no channel for the feed-in cap / target SoC: never report them as written."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from ehal import EHAL_SCHEMA_VERSION
from integrations import ehal_live
from integrations.ehal_live_records import SKIPPED_MESSAGE, build_ehal_write_records
from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig


def _adapter() -> OpenemsAdapter:
    return OpenemsAdapter(
        OpenemsConfig(
            base_url="http://edge:8084",
            username="x",
            password="admin",
            adapter_id="openems-lab",
        )
    )


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"value": None}
    return response


def _setpoint(**extra) -> dict:
    doc = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-11-18T12:00:00Z",
        "adapter_id": "openems-lab",
        "set_ess_charge_power_limit": 1000.0,
        "set_ess_discharge_power_limit": 2000.0,
    }
    doc.update(extra)
    return doc


@patch("integrations.openems_adapter.requests.post")
def test_export_limit_is_skipped_not_posted(post_mock):
    post_mock.return_value = _ok_response()
    adapter = _adapter()
    error = adapter.write_setpoints(_setpoint(set_grid_export_power_limit=0.0))
    assert error is None
    assert adapter.last_skipped_fields() == ["set_grid_export_power_limit"]
    assert adapter.last_unconfigured_fields() == []
    # Only the two ESS limits went out; no write for the export cap.
    assert post_mock.call_count == 2


@patch("integrations.openems_adapter.requests.post")
def test_target_soc_is_unconfigured(post_mock):
    post_mock.return_value = _ok_response()
    adapter = _adapter()
    assert adapter.write_setpoints(_setpoint(set_ess_target_soc=80.0)) is None
    assert adapter.last_unconfigured_fields() == ["set_ess_target_soc"]
    assert adapter.last_skipped_fields() == []


@patch("integrations.openems_adapter.requests.post")
def test_unwired_fields_warn_once_per_adapter(post_mock, caplog):
    post_mock.return_value = _ok_response()
    adapter = _adapter()
    with caplog.at_level(logging.WARNING, logger="integrations.openems_adapter"):
        for _ in range(3):
            adapter.write_setpoints(
                _setpoint(set_grid_export_power_limit=0.0, set_ess_target_soc=50.0)
            )
    messages = [rec.getMessage() for rec in caplog.records]
    export = [m for m in messages if "set_grid_export_power_limit" in m]
    soc = [m for m in messages if "set_ess_target_soc" in m]
    assert len(export) == 1 and "NOT enforced" in export[0]
    assert len(soc) == 1
    # A second adapter instance (e.g. after config reload) warns again.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="integrations.openems_adapter"):
        _adapter().write_setpoints(_setpoint(set_grid_export_power_limit=0.0))
    assert any("set_grid_export_power_limit" in rec.getMessage() for rec in caplog.records)


@patch("integrations.openems_adapter.requests.post")
def test_ess_write_clears_stale_evcs_skip(post_mock):
    post_mock.return_value = _ok_response()
    adapter = _adapter()
    adapter.write_evcs_setpoints(
        "unknown_box",
        {
            "schema_version": EHAL_SCHEMA_VERSION,
            "ts": "2026-11-18T12:00:00Z",
            "adapter_id": "openems-lab",
            "set_evcs_max_current": 10,
        },
        voltage_v=230,
        phases=1,
    )
    assert adapter.last_skipped_fields() == ["set_evcs_max_current"]
    adapter.write_setpoints(_setpoint())
    assert adapter.last_skipped_fields() == []
    assert adapter.last_unconfigured_fields() == []


@patch("integrations.openems_adapter.requests.post")
@patch("optimizer.live_export_limit.live_unconstrained_export_kw", return_value=None)
@patch("integrations.ehal_live.persist_write_error")
@patch("integrations.ehal_live.get_openems_adapter")
@patch("integrations.ehal_live.config")
def test_live_trace_shows_export_cap_as_skipped(
    config_mock, adapter_factory, _persist, _unconstrained, post_mock
):
    ehal_live.reset_adapter_cache()
    config_mock.get.side_effect = lambda key, default=None: {
        "EHAL_BACKEND": "openems",
        "EHAL_ADAPTER_ID": "openems-lab",
    }.get(key, default)
    config_mock.get_battery_params.return_value = {"max_power_kw": 5.0}
    post_mock.return_value = _ok_response()
    adapter_factory.return_value = _adapter()

    error, records = ehal_live.write_ess_setpoints_from_control(0, 0.0, export_cap_kw=0.0)

    assert error is None
    by_field = {row["field"]: row for row in records}
    export = by_field["set_grid_export_power_limit"]
    assert export["success"] is False
    assert export["skipped"] is True
    assert "kein OpenEMS-Kanal" in export["message"]
    assert export["message"] != SKIPPED_MESSAGE
    assert export["value"] == 0.0
    assert by_field["set_ess_charge_power_limit"]["success"] is True


@patch("integrations.openems_adapter.requests.post")
def test_skipped_message_only_for_export_limit(post_mock):
    post_mock.return_value = _ok_response()
    adapter = _adapter()
    adapter.write_setpoints(_setpoint(set_grid_export_power_limit=0.0))
    assert set(adapter.last_skipped_messages()) == {"set_grid_export_power_limit"}
    adapter.write_setpoints(_setpoint())
    assert adapter.last_skipped_messages() == {}


def test_records_fall_back_to_generic_skip_message():
    rows = build_ehal_write_records(
        {"a": 1.0, "b": 2.0},
        written_at="2026-11-18T12:00:00Z",
        error=None,
        skipped=["a", "b"],
        skipped_messages={"a": "Übersprungen: speziell"},
    )
    by_field = {row["field"]: row["message"] for row in rows}
    assert by_field == {"a": "Übersprungen: speziell", "b": SKIPPED_MESSAGE}
