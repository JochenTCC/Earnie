"""HA backend: going back to automatic releases a forced ``set_ess_active_power`` (bench L18).

The HA ``number`` for the active power is sticky. Earnie used to return to automatic by
omitting the active power and publishing ``set_ess_mode = 0``; the old force value stayed in
the ledger and in HA and the battery kept charging. Decision 2026-10-22 (option a): publish
``set_ess_active_power = 0`` on automatic (the Huawei force automation releases at |power| < 1).
"""
from __future__ import annotations

import pytest

from integrations import ehal_live
from integrations.ehal_write import load_published
from integrations.ha_adapter import HaAdapter, HaConfig

ACTIVE_QID = "ess.house.set_ess_active_power"
KEYS = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
)


@pytest.fixture
def ha(monkeypatch: pytest.MonkeyPatch):
    def install(*, control: str = "full", active_activated: bool = True, ha_backend: bool = True):
        entities = {f"ess.house.{k}": "" for k in KEYS if active_activated or k != KEYS[0]}
        adapter = HaAdapter(
            HaConfig(
                base_url="http://ha:8123",
                token="t",
                adapter_id="test",
                entities=entities,
                setpoint_qids={k: k for k in entities},
            )
        )
        monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: ha_backend)
        monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
        monkeypatch.setattr(
            ehal_live.config,
            "get_battery_params",
            lambda: {"control": control, "max_charge_power_kw": 5.0, "max_discharge_power_kw": 5.0},
        )
        return adapter

    return install


def test_automatic_after_a_force_publishes_zero_active_power(ha) -> None:
    ha()
    ehal_live.write_ess_setpoints_from_control(1, 2.0)
    assert load_published()[ACTIVE_QID] == pytest.approx(-2000.0)

    error, rows = ehal_live.write_ess_setpoints_from_control(0, 0.0)

    assert error is None
    assert load_published()[ACTIVE_QID] == 0.0
    assert any(r["field"] == "set_ess_active_power" and r["value"] == 0.0 for r in rows)


def test_discharge_block_also_releases_the_force(ha) -> None:
    ha()
    ehal_live.write_ess_setpoints_from_control(1, 2.0)
    ehal_live.write_ess_setpoints_from_control(2, 0.0)  # MODE_ENTLADESPERRE
    assert load_published()[ACTIVE_QID] == 0.0


def test_a_force_is_still_published_as_is(ha) -> None:
    ha()
    ehal_live.write_ess_setpoints_from_control(3, 1.5)  # force discharge
    assert load_published()[ACTIVE_QID] == pytest.approx(1500.0)


def test_limits_only_battery_never_gets_an_active_power(ha) -> None:
    ha(control="limits_only")
    ehal_live.write_ess_setpoints_from_control(0, 0.0)
    assert ACTIVE_QID not in load_published()


def test_nothing_is_published_when_the_active_power_is_not_activated(ha) -> None:
    ha(active_activated=False)
    ehal_live.write_ess_setpoints_from_control(0, 0.0)
    assert ACTIVE_QID not in load_published()


def test_other_backends_keep_omitting_the_active_power(ha, monkeypatch) -> None:
    adapter = ha(ha_backend=False)
    sent: list[dict] = []
    monkeypatch.setattr(adapter, "write_setpoints", lambda doc: sent.append(dict(doc)))
    ehal_live.write_ess_setpoints_from_control(0, 0.0)
    assert "set_ess_active_power" not in sent[0]
