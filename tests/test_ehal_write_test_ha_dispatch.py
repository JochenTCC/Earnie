"""HA backend: the Schreibtest publishes every ticked row (bench finding B2 / F16-F20).

The UI reported ``Schreiben OK (published)`` for the inverter AC limit and the flex
``set_enable`` although nothing reached the publish ledger (and so never ``status.json``):
the inverter key was handed to the ESS/EVCS-only ``write_setpoints`` and the flex path was a
no-op on every network backend.
"""
from __future__ import annotations

import pytest

from integrations import ehal_live
from integrations import ehal_write_test as ewt
from integrations.ehal_write import load_published
from integrations.ehal_write_test import write_probes
from integrations.ha_adapter import HaAdapter, HaConfig

INV_QID = "inv.wr_main.set_inv_ac_power_limit"
HEATPUMP_QID = "heatpump.waermepumpe.set_enable"
ESS_QID = "ess.house.set_ess_charge_power_limit"


@pytest.fixture
def ha_adapter(monkeypatch: pytest.MonkeyPatch) -> HaAdapter:
    adapter = HaAdapter(
        HaConfig(
            base_url="http://ha:8123",
            token="t",
            adapter_id="test",
            entities={
                INV_QID: "",
                ESS_QID: "",
                "set_evcs_max_current": "",
            },
            setpoint_qids={
                ESS_QID: ESS_QID,
                HEATPUMP_QID: HEATPUMP_QID,
                "set_evcs_max_current": "evcs.e_auto.set_evcs_max_current",
            },
        )
    )
    monkeypatch.setattr(ewt.config, "is_silent_mode", lambda: False)
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "is_openems_backend", lambda: False)
    monkeypatch.setattr(ehal_live, "is_ehal_network_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "get_ha_adapter", lambda: adapter)
    monkeypatch.setattr(ehal_live, "get_adapter", lambda: adapter)
    return adapter


def test_inverter_ac_limit_is_published(ha_adapter: HaAdapter) -> None:
    error, _ = write_probes({INV_QID: 3000.0}, max_power_kw=10.0)
    assert error is None
    assert load_published()[INV_QID] == pytest.approx(3000.0)


def test_flex_set_enable_is_published(ha_adapter: HaAdapter) -> None:
    error, _ = write_probes({HEATPUMP_QID: 1}, max_power_kw=10.0)
    assert error is None
    assert load_published()[HEATPUMP_QID] == pytest.approx(1.0)


def test_a_mixed_selection_publishes_all_rows(ha_adapter: HaAdapter) -> None:
    error, _ = write_probes(
        {INV_QID: 2000.0, HEATPUMP_QID: 1, ESS_QID: 1500.0}, max_power_kw=10.0
    )
    assert error is None
    published = load_published()
    assert published[INV_QID] == pytest.approx(2000.0)
    assert published[HEATPUMP_QID] == pytest.approx(1.0)
    assert published[ESS_QID] == pytest.approx(1500.0)


def test_an_unmapped_flex_row_fails_loudly(ha_adapter: HaAdapter) -> None:
    with pytest.raises(ValueError, match="pool.pool_filter.set_enable"):
        write_probes({"pool.pool_filter.set_enable": 1}, max_power_kw=10.0)
    assert "pool.pool_filter.set_enable" not in load_published()
