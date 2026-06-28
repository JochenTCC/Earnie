"""Tests für urgent-Regel-Observability (Logging / Historie)."""
from __future__ import annotations

from datetime import datetime

from optimizer.charging_context import summarize_urgent_rule_usage


def _summary(**kwargs):
    defaults = {
        "pre_urgent_indices": [0, 1],
        "urgent_indices": [2, 3],
        "effective_target_kwh": 8.0,
        "planned_pre_urgent_kwh": 0.0,
        "planned_urgent_kwh": 0.0,
        "deadline": datetime(2026, 6, 29, 7, 45),
        "must_start": datetime(2026, 6, 29, 5, 30),
    }
    defaults.update(kwargs)
    return summarize_urgent_rule_usage(**defaults)


class TestSummarizeUrgentRuleUsage:
    def test_nicht_aktiv_without_target(self):
        assert _summary(effective_target_kwh=0.0)["role"] == "nicht_aktiv"

    def test_nur_urgent_fenster_without_pre_slots(self):
        assert _summary(pre_urgent_indices=[], planned_urgent_kwh=8.0)["role"] == (
            "nur_urgent_fenster"
        )

    def test_nachholen_when_urgent_carries_energy(self):
        assert _summary(planned_pre_urgent_kwh=2.0, planned_urgent_kwh=6.0)["role"] == (
            "nachholen"
        )

    def test_redundant_when_only_pre_urgent_used(self):
        assert _summary(planned_pre_urgent_kwh=8.0, planned_urgent_kwh=0.0)["role"] == (
            "redundant"
        )

    def test_includes_deadline_fields(self):
        summary = _summary()
        assert summary["deadline"] == "2026-06-29T07:45:00"
        assert summary["must_start"] == "2026-06-29T05:30:00"
        assert summary["target_kwh"] == 8.0
