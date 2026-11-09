"""``set_ess_target_soc``: the optimizer's target SoC goes out again as an optional setpoint.

Removed in 2.4.j; back on 2026-11-09 for the hold test on the maintainer's plant. Earnie
keeps ``set_ess_mode`` 1 during Entladesperre and adds the target SoC (= current SoC);
the Huawei then leaves the forced charge at that SoC instead of charging ~0.2 kW from the
grid. Written only where the battery maps the field.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import integrations.loxone_writes as lw
from integrations import ehal_live
from integrations.ehal_write import load_published
from integrations.ha_adapter import HaAdapter, HaConfig

ESS_NAMES = {
    "set_ess_active_power": "Earnie_Batterie_Sollleistung",
    "set_ess_charge_power_limit": "Earnie_LadeLeistungs-Limit",
    "set_ess_discharge_power_limit": "Earnie_EntladeLeistungs-Limit",
    "set_ess_mode": "Earnie_Steuerbefehl",
    "set_ess_target_soc": "Earnie_Ziel_SOC",
}
BATTERY = {
    "max_charge_power_kw": 5.0,
    "max_discharge_power_kw": 5.0,
    "battery_capacity_kwh": 15.0,
    "min_soc": 5.0,
    "max_soc": 100.0,
}


def _bindings(names: dict[str, str]):
    return patch(
        "house_config.ess_bindings.resolve_primary_ess_binding",
        side_effect=lambda kind, **kw: names.get(kind, ""),
    )


def _snapshot(
    names: dict[str, str], *, mode: int, target_soc: float, target_power_kw: float = 0.0
) -> dict[str, float]:
    with (
        _bindings(names),
        patch.object(lw.config, "get_battery_params", return_value=BATTERY),
        patch.object(lw.config, "get_flexible_consumers", return_value=[]),
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=False,
        ),
    ):
        return lw.build_sent_loxone_snapshot(
            mode=mode,
            target_power_kw=target_power_kw,
            target_soc=target_soc,
            consumer_powers={},
            charging_contexts={},
        )


def test_hold_sends_mode_1_and_the_current_soc_as_target() -> None:
    snap = _snapshot(ESS_NAMES, mode=2, target_soc=63.44)  # MODE_ENTLADESPERRE
    assert snap["Earnie_Steuerbefehl"] == 1.0
    assert snap["Earnie_Ziel_SOC"] == 63.4


def test_target_soc_is_not_sent_when_not_mapped() -> None:
    names = {k: v for k, v in ESS_NAMES.items() if k != "set_ess_target_soc"}
    snap = _snapshot(names, mode=2, target_soc=63.4)
    assert "Earnie_Ziel_SOC" not in snap
    assert snap["Earnie_Steuerbefehl"] == 1.0


def test_live_write_publishes_the_target_soc() -> None:
    published: list[tuple[str, float]] = []

    def _publish(field: str, value: float, *, io_name: str = ""):
        published.append((field, value))
        return lw.LoxoneWriteRecord(
            io_name=io_name, value=value, success=True, written_at="t"
        )

    with (
        _bindings(ESS_NAMES),
        patch.object(lw, "_publish_setpoint_traced", side_effect=_publish),
        patch.object(
            lw, "_ess_c1_exchange_field", side_effect=lambda kind, *a, **kw: f"ess.house.{kind}"
        ),
        patch("integrations.ehal_debug_mapping.build_loxone_setpoint_io_index", return_value={}),
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=True,
        ),
        patch("integrations.loxone_client.config.get_battery_params", return_value=BATTERY),
    ):
        lw.send_huawei_modbus_states(2, 0.0, 58.0)

    assert ("ess.house.set_ess_mode", 1.0) in published
    assert ("ess.house.set_ess_target_soc", 58.0) in published


@pytest.mark.parametrize(("raw", "sent"), [(99.0, 99.0), (101.2, 100.0), (-3.0, 0.0), (47.06, 47.1)])
def test_target_soc_percent_is_clamped_and_rounded(raw: float, sent: float) -> None:
    assert (
        lw.ess_target_soc_percent(raw, mode=0, target_power_kw=0.0, battery_params=BATTERY)
        == sent
    )


def test_target_soc_nan_fails_loud() -> None:
    with pytest.raises(ValueError):
        lw.ess_target_soc_percent(
            float("nan"), mode=0, target_power_kw=0.0, battery_params=BATTERY
        )


# Huawei reports whole-percent SoC: forced modes get a buffer beyond the slot-end SoC,
# 1 % reporting step + 25 % of the slot's SoC change at the target power.
# 5 kW on 15 kWh for 15 min = 8.33 % slot change -> buffer 3.08 %.


def test_forced_discharge_target_soc_gets_power_dependent_buffer() -> None:
    sent = lw.ess_target_soc_percent(
        60.5, mode=3, target_power_kw=5.0, battery_params=BATTERY
    )
    assert sent == pytest.approx(57.4)


def test_buffer_grows_with_target_power() -> None:
    low = lw.ess_target_soc_buffer_percent(3, 1.0, 15.0, dt_h=0.25)
    high = lw.ess_target_soc_buffer_percent(3, 5.0, 15.0, dt_h=0.25)
    assert low == pytest.approx(1.0 + 0.25 * 1.0 * 0.25 / 15.0 * 100.0)
    assert high == pytest.approx(1.0 + 0.25 * 5.0 * 0.25 / 15.0 * 100.0)
    assert high > low > 1.0


def test_forced_charge_target_soc_buffer_goes_up_and_stops_at_max_soc() -> None:
    assert lw.ess_target_soc_percent(
        80.0, mode=1, target_power_kw=5.0, battery_params=BATTERY
    ) == pytest.approx(83.1)
    assert (
        lw.ess_target_soc_percent(99.0, mode=1, target_power_kw=5.0, battery_params=BATTERY)
        == 100.0
    )


def test_discharge_buffer_stops_at_min_soc_and_never_raises_the_plan() -> None:
    assert (
        lw.ess_target_soc_percent(6.0, mode=3, target_power_kw=5.0, battery_params=BATTERY)
        == 5.0
    )
    assert (
        lw.ess_target_soc_percent(4.0, mode=3, target_power_kw=5.0, battery_params=BATTERY)
        == 4.0
    )


@pytest.mark.parametrize("mode", [0, 2])
def test_automatik_and_hold_get_no_buffer(mode: int) -> None:
    assert (
        lw.ess_target_soc_percent(63.4, mode=mode, target_power_kw=5.0, battery_params=BATTERY)
        == 63.4
    )


def test_buffer_without_capacity_fails_loud() -> None:
    with pytest.raises(ValueError):
        lw.ess_target_soc_buffer_percent(3, 5.0, 0.0, dt_h=0.25)


def test_snapshot_sends_the_buffered_discharge_target() -> None:
    snap = _snapshot(ESS_NAMES, mode=3, target_soc=60.5, target_power_kw=5.0)
    assert snap["Earnie_Ziel_SOC"] == pytest.approx(57.4)


def test_ha_publishes_the_buffered_discharge_target(ha) -> None:
    ha(target_activated=True)
    error, _rows = ehal_live.write_ess_setpoints_from_control(3, 5.0, target_soc=60.5)
    assert error is None
    assert load_published()["ess.house.set_ess_target_soc"] == pytest.approx(57.4)


@pytest.fixture
def ha(monkeypatch: pytest.MonkeyPatch):
    def install(*, target_activated: bool):
        keys = [
            "set_ess_active_power",
            "set_ess_charge_power_limit",
            "set_ess_discharge_power_limit",
            "set_ess_mode",
        ]
        if target_activated:
            keys.append("set_ess_target_soc")
        entities = {f"ess.house.{k}": "" for k in keys}
        adapter = HaAdapter(
            HaConfig(
                base_url="http://ha:8123",
                token="t",
                adapter_id="test",
                entities=entities,
                setpoint_qids={k: k for k in entities},
            )
        )
        monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
        monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
        monkeypatch.setattr(
            ehal_live.config,
            "get_battery_params",
            lambda: {"control": "full", **BATTERY},
        )
        return adapter

    return install


def test_ha_publishes_the_target_soc_when_activated(ha) -> None:
    ha(target_activated=True)
    error, rows = ehal_live.write_ess_setpoints_from_control(2, 0.0, target_soc=71.0)
    assert error is None
    assert load_published()["ess.house.set_ess_target_soc"] == 71.0
    assert any(r["field"] == "set_ess_target_soc" and r["value"] == 71.0 for r in rows)


def test_ha_skips_the_target_soc_when_not_activated(ha) -> None:
    ha(target_activated=False)
    error, _rows = ehal_live.write_ess_setpoints_from_control(2, 0.0, target_soc=71.0)
    assert error is None
    assert "ess.house.set_ess_target_soc" not in load_published()


def test_startup_safe_push_sends_the_automatik_target_soc(monkeypatch) -> None:
    """The safe push at daemon start must not send target SoC 0 (seen on dev.12)."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        ehal_live, "write_huawei_modbus_states", lambda *a, **kw: calls.append(a) or []
    )
    monkeypatch.setattr(ehal_live, "write_flexible_consumer_states", lambda *a, **kw: [])
    monkeypatch.setattr(ehal_live, "write_inv_ac_limits_from_plan", lambda **kw: (None, []))
    ehal_live._push_safe_setpoints_loxone()
    assert calls == [(0, 0.0, 99.0)]
