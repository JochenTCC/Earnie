"""Entity-scoped get_ess_* enrichment for powerstation / ESS live limits."""
from __future__ import annotations

from unittest.mock import patch

from integrations.ehal_live_ess_limits import enrich_telemetry_with_ess_live_limits


def test_enrich_adds_entity_scoped_soc_limits_for_limits_from_live():
    bat = {
        "id": "ecoflow_delta_3",
        "limits_from_live": True,
        "ehal_bindings": {
            "ess.ecoflow_delta_3.get_ess_soc_min": "",
            "ess.ecoflow_delta_3.get_ess_soc_max": "",
        },
    }

    def _fake_read(address: str, kind: str):
        if kind == "get_ess_soc_min":
            return 10.0
        if kind == "get_ess_soc_max":
            return 95.0
        return None

    with (
        patch(
            "integrations.ehal_live_ess_limits._batteries_needing_live_limits",
            return_value=[bat],
        ),
        patch(
            "integrations.ehal_live_ess_limits._read_limit_from_address",
            side_effect=_fake_read,
        ),
    ):
        out = enrich_telemetry_with_ess_live_limits({})

    assert out["ess.ecoflow_delta_3.get_ess_soc_min"] == 10.0
    assert out["ess.ecoflow_delta_3.get_ess_soc_max"] == 95.0


def test_enrich_skips_when_limits_from_live_off():
    with patch(
        "integrations.ehal_live_ess_limits._batteries_needing_live_limits",
        return_value=[],
    ):
        out = enrich_telemetry_with_ess_live_limits({"get_ess_soc_max": 80.0})
    assert out == {"get_ess_soc_max": 80.0}
