"""2.7.n-4/n-5 gate: pin Loxone → EHAL read conversions (registry-driven).

Thin characterization around ``LoxoneAdapter.read_telemetry``, optional ESS
``get_*``, per-battery SoC, and push-inbox → required/optional errors so
Session F cannot silently change kW→W, clamps, omit semantics, or abort paths.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from ehal import loxone_push_source as src
from ehal.ess_fields import ess_field
from ehal.qualified_ids import qualified_battery_id, qualified_plant_id
from integrations import ehal_live, loxone_client
from ehal.field_registry import require_loxone_write
from integrations.loxone_adapter import (
    LoxoneAdapter,
    LoxoneAdapterError,
    LoxoneConfig,
    loxone_battery_kw_to_ehal_w,
)
from runtime_store import loxone_push_inbox as inbox

_PRIMARY_ESS = "15_kwh_speicher"


@pytest.fixture(autouse=True)
def _primary_ess_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "integrations.loxone_adapter.primary_ess_id_for_plant_read",
        lambda: _PRIMARY_ESS,
    )


def _cfg(**kwargs) -> LoxoneConfig:
    base = dict(
        adapter_id="loxone-home",
        charge_power_name="Charge",
        discharge_power_name="Discharge",
        active_power_name="Active",
        control_cmd_name="Cmd",
    )
    base.update(kwargs)
    return LoxoneConfig(**base)


def _plant_fetch(**extra) -> dict:
    values = {
        qualified_battery_id(_PRIMARY_ESS, "sens_ess_soc"): 55.0,
        qualified_plant_id("sens_pv_production_active"): 0.0,
        qualified_battery_id(_PRIMARY_ESS, "sens_ess_power"): 0.0,
        qualified_plant_id("sens_grid_power_active"): 0.0,
    }
    values.update(extra)
    return values


# ---------------------------------------------------------------------------
# Unit helpers / plant conversions (baseline)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "w"),
    [(1.5, 1500.0), (-0.5, -500.0), (0.0, 0.0)],
)
def test_char_battery_kw_to_ehal_w(kw: float, w: float) -> None:
    assert loxone_battery_kw_to_ehal_w(kw) == pytest.approx(w)


@pytest.mark.parametrize(
    ("w", "kw"),
    [(2000.0, 2.0), (0.0, 0.0), (-100.0, 0.0)],
)
def test_char_loxone_write_limit_clamps_negative(w: float, kw: float) -> None:
    assert require_loxone_write("set_ess_charge_power_limit", w) == pytest.approx(kw)


def test_char_active_power_sign_preserved() -> None:
    assert require_loxone_write("set_ess_active_power", -1500) == pytest.approx(-1.5)


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_read_telemetry_kw_to_w_and_pv_clamp(fetch_mock) -> None:
    fetch_mock.side_effect = {
        qualified_battery_id(_PRIMARY_ESS, "sens_ess_soc"): 55.0,
        qualified_plant_id("sens_pv_production_active"): -0.1,  # clamped to 0 before ×1000
        qualified_battery_id(_PRIMARY_ESS, "sens_ess_power"): 0.5,
        qualified_plant_id("sens_grid_power_active"): -1.2,
    }.get
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    assert telemetry["sens_ess_soc"] == 55.0
    assert telemetry["sens_pv_production_active"] == 0.0
    assert telemetry["sens_grid_power_active"] == pytest.approx(-1200.0)
    assert telemetry["sens_ess_power"] == pytest.approx(500.0)


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_required_marker_missing_raises(fetch_mock) -> None:
    fetch_mock.return_value = None
    with pytest.raises(LoxoneAdapterError, match="sens_ess_soc"):
        LoxoneAdapter(_cfg()).read_telemetry()


@pytest.mark.parametrize(
    ("raw", "expected_w"),
    [(3.5, 3500.0), (0.0, 0.0), (-1.0, None), (None, None)],
)
@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_export_limit_inbound(fetch_mock, raw, expected_w) -> None:
    qid = qualified_plant_id("get_grid_export_power_limit")
    values = _plant_fetch(**{qid: raw})
    fetch_mock.side_effect = values.get
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    assert telemetry.get("get_grid_export_power_limit") == expected_w


# ---------------------------------------------------------------------------
# Optional ESS get_*
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(10.0, 10.0), (-5.0, 0.0), (120.0, 100.0)],
)
@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_optional_ess_soc_limits_clamp(fetch_mock, raw, expected) -> None:
    values = _plant_fetch(
        **{
            qualified_battery_id(_PRIMARY_ESS, "get_ess_soc_min"): raw,
            qualified_battery_id(_PRIMARY_ESS, "get_ess_soc_max"): raw,
        }
    )
    fetch_mock.side_effect = values.get
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    assert telemetry["get_ess_soc_min"] == pytest.approx(expected)
    assert telemetry["get_ess_soc_max"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected_w"),
    [(2.5, 2500.0), (0.0, 0.0), (-1.0, None), (None, None), ("x", None)],
)
@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_optional_ess_power_limits(fetch_mock, raw, expected_w) -> None:
    values = _plant_fetch(
        **{
            qualified_battery_id(_PRIMARY_ESS, "get_ess_max_charge_power"): raw,
            qualified_battery_id(_PRIMARY_ESS, "get_ess_max_discharge_power"): raw,
        }
    )
    fetch_mock.side_effect = values.get
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    assert telemetry.get("get_ess_max_charge_power") == expected_w
    assert telemetry.get("get_ess_max_discharge_power") == expected_w


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_optional_ess_limits_absent_when_unconfigured(fetch_mock) -> None:
    fetch_mock.side_effect = _plant_fetch().get
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    for field in (
        "get_ess_soc_min",
        "get_ess_soc_max",
        "get_ess_max_charge_power",
        "get_ess_max_discharge_power",
    ):
        assert field not in telemetry


# ---------------------------------------------------------------------------
# Per-battery SoC
# ---------------------------------------------------------------------------


def test_char_read_ess_soc_by_id_pattern_b_address() -> None:
    ehal_live._soc_missing_warned.clear()
    batteries = [
        {
            "id": "house",
            "type": "house",
            "ehal_bindings": {ess_field("house", "sens_ess_soc"): "House_SoC"},
        },
    ]
    qid = qualified_battery_id("house", "sens_ess_soc")

    with (
        patch.object(ehal_live, "_mappable_batteries_for_soc", return_value=batteries),
        patch.object(ehal_live, "read_ess_soc", return_value=None),
        patch.object(
            ehal_live.loxone_client,
            "fetch_loxone_generic_value",
            side_effect={qid: 61.0}.get,
        ),
    ):
        by_id = ehal_live.read_ess_soc_by_id()

    assert by_id == {"house": 61.0}


def test_char_read_ess_soc_by_id_secondary_no_primary_fallback() -> None:
    ehal_live._soc_missing_warned.clear()
    batteries = [
        {
            "id": "house",
            "type": "house",
            "ehal_bindings": {ess_field("house", "sens_ess_soc"): "House_SoC"},
        },
        {"id": "pack_b", "type": "house", "ehal_bindings": {}},
    ]
    qid = qualified_battery_id("house", "sens_ess_soc")

    with (
        patch.object(ehal_live, "_mappable_batteries_for_soc", return_value=batteries),
        patch.object(ehal_live, "read_ess_soc", return_value=55.0),
        patch.object(
            ehal_live.loxone_client,
            "fetch_loxone_generic_value",
            side_effect={qid: 55.0}.get,
        ),
    ):
        by_id = ehal_live.read_ess_soc_by_id()

    assert by_id == {"house": 55.0}
    assert "pack_b" not in by_id


def test_char_read_ess_soc_by_id_primary_plant_alias() -> None:
    ehal_live._soc_missing_warned.clear()
    batteries = [{"id": "house", "type": "house", "ehal_bindings": {}}]

    with (
        patch.object(ehal_live, "_mappable_batteries_for_soc", return_value=batteries),
        patch.object(ehal_live, "read_ess_soc", return_value=42.0),
        patch.object(
            ehal_live.loxone_client,
            "fetch_loxone_generic_value",
            return_value=None,
        ),
    ):
        by_id = ehal_live.read_ess_soc_by_id()

    assert by_id == {"house": 42.0}


# ---------------------------------------------------------------------------
# Missing / stale push-inbox → required vs optional
# ---------------------------------------------------------------------------


_PUSH_HOUSE = {
    "plant": {
        "ehal_bindings": {
            "sens_pv_production_active": "PV",
            "sens_grid_power_active": "Grid",
        }
    },
    "profiles": {},
}

_PUSH_COMPONENTS = {
    "batteries": [
        {
            "id": _PRIMARY_ESS,
            "type": "house",
            "ehal_bindings": {
                ess_field(_PRIMARY_ESS, "sens_ess_soc"): "SoC",
                ess_field(_PRIMARY_ESS, "sens_ess_power"): "Bat",
                ess_field(_PRIMARY_ESS, "get_ess_soc_min"): "SocMin",
            },
        }
    ]
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _install_push_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    src.clear_source_caches()
    monkeypatch.setattr(
        src,
        "get_merker_index",
        lambda: src.build_merker_index(_PUSH_HOUSE, _PUSH_COMPONENTS),
    )
    monkeypatch.setattr(
        src,
        "get_ehal_index",
        lambda: src.build_ehal_index(_PUSH_HOUSE, _PUSH_COMPONENTS),
    )


def _seed_required_push(*, soc: str | None = "55", now: datetime | None = None) -> None:
    ref = now if now is not None else _now()
    inbox.record_push("heartbeat", "1", now=ref)
    if soc is not None:
        inbox.record_push(qualified_battery_id(_PRIMARY_ESS, "sens_ess_soc"), soc, now=ref)
    inbox.record_push(qualified_plant_id("sens_pv_production_active"), "0", now=ref)
    inbox.record_push(qualified_battery_id(_PRIMARY_ESS, "sens_ess_power"), "0", now=ref)
    inbox.record_push(qualified_plant_id("sens_grid_power_active"), "0", now=ref)


def test_char_push_missing_required_soc_raises(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    _install_push_indexes(monkeypatch)
    _seed_required_push(soc=None)
    with patch.object(loxone_client, "fetch_loxone_raw_value") as raw:
        with pytest.raises(LoxoneAdapterError, match="sens_ess_soc"):
            LoxoneAdapter(_cfg()).read_telemetry()
        raw.assert_not_called()


def test_char_push_stale_required_soc_past_last_known_raises(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    _install_push_indexes(monkeypatch)
    old = _now() - timedelta(minutes=6)
    _seed_required_push(soc="55", now=old)
    # Fresh heartbeat so link is alive; SoC row stays stale past last-known window.
    inbox.record_push("heartbeat", "1", now=_now())
    with patch.object(loxone_client, "fetch_loxone_raw_value") as raw:
        with pytest.raises(LoxoneAdapterError, match="sens_ess_soc"):
            LoxoneAdapter(_cfg()).read_telemetry()
        raw.assert_not_called()


def test_char_push_missing_optional_ess_soc_min_omitted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    _install_push_indexes(monkeypatch)
    _seed_required_push()
    with patch.object(loxone_client, "fetch_loxone_raw_value") as raw:
        telemetry = LoxoneAdapter(_cfg()).read_telemetry()
        raw.assert_not_called()
    assert telemetry["sens_ess_soc"] == pytest.approx(55.0)
    assert "get_ess_soc_min" not in telemetry
