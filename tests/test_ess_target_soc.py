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
BATTERY = {"max_charge_power_kw": 5.0, "max_discharge_power_kw": 5.0}


def _bindings(names: dict[str, str]):
    return patch(
        "house_config.ess_bindings.resolve_primary_ess_binding",
        side_effect=lambda kind, **kw: names.get(kind, ""),
    )


def _snapshot(names: dict[str, str], *, mode: int, target_soc: float) -> dict[str, float]:
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
            target_power_kw=0.0,
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
    assert lw.ess_target_soc_percent(raw) == sent


def test_target_soc_nan_fails_loud() -> None:
    with pytest.raises(ValueError):
        lw.ess_target_soc_percent(float("nan"))


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
