"""Tests für optimizer.appliance_recommendation (Schritt 3a)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer.appliance_recommendation import (
    STAR_MAX,
    STAR_MIN,
    STAR_NEUTRAL,
    StarThresholdSettings,
    recommend_start_times,
    run_cost_eur,
)

BASE = datetime(2026, 7, 7, 18, 0)


def make_slots(
    prices_cent: list[float],
    *,
    k_push_act: float = 0.0,
    expected_p_pv: float = 0.0,
    expected_p_act: float = 0.0,
) -> list[dict]:
    """Baut stündliche Planungs-Slots; Default ohne PV-Überschuss (= Import-only)."""
    return [
        {
            "slot_datetime": BASE + timedelta(hours=i),
            "k_act": price,
            "k_push_act": k_push_act,
            "expected_p_pv": expected_p_pv,
            "expected_p_act": expected_p_act,
        }
        for i, price in enumerate(prices_cent)
    ]


def make_slots_detailed(
    rows: list[tuple[float, float, float, float]],
) -> list[dict]:
    """Slots aus (k_act, k_push_act, expected_p_pv, expected_p_act)."""
    return [
        {
            "slot_datetime": BASE + timedelta(hours=i),
            "k_act": k_act,
            "k_push_act": k_push,
            "expected_p_pv": p_pv,
            "expected_p_act": p_act,
        }
        for i, (k_act, k_push, p_pv, p_act) in enumerate(rows)
    ]


def test_cheapest_hour_is_identified():
    slots = make_slots([30.0, 10.0, 20.0, 40.0, 25.0, 35.0])
    result = recommend_start_times(slots, power_kw=2.0, runtime_h=1.0)
    assert result.cheapest.start_datetime == BASE + timedelta(hours=1)
    # 2 kW * 1 h * 10 ct/kWh = 20 ct = 0,20 €
    assert result.cheapest.cost_eur == pytest.approx(0.20)


def test_cost_over_multiple_full_hours():
    slots = make_slots([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    weights = [1.0, 1.0]
    # 1 kW * (10 + 20) ct = 30 ct = 0,30 €
    assert run_cost_eur(slots, 0, 1.0, weights) == pytest.approx(0.30)


def test_fractional_runtime_weights_last_hour():
    slots = make_slots([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    result = recommend_start_times(slots, power_kw=1.0, runtime_h=1.5)
    # Start 0: 1 kW * (1*10 + 0.5*20) ct = 20 ct = 0,20 €
    assert result.immediate.cost_eur == pytest.approx(0.20)


def test_stars_five_within_abs_margin():
    slots = make_slots([10.0, 10.04, 10.03, 40.0, 50.0, 60.0])
    settings = StarThresholdSettings(0.05, 10.0, 30.0)
    result = recommend_start_times(
        slots, power_kw=1.0, runtime_h=1.0, star_settings=settings
    )
    assert result.options[0].stars == STAR_MAX
    assert result.options[1].stars == STAR_MAX
    assert result.options[2].stars == STAR_MAX


def test_stars_one_above_pct_threshold():
    slots = make_slots([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    settings = StarThresholdSettings(0.05, 10.0, 30.0)
    result = recommend_start_times(
        slots, power_kw=1.0, runtime_h=1.0, star_settings=settings
    )
    assert result.options[0].stars == STAR_MAX
    assert result.options[-1].stars == STAR_MIN


def test_stars_interpolate_between_pct_thresholds():
    slots = make_slots([10.0, 11.5, 30.0, 40.0, 50.0, 60.0])
    settings = StarThresholdSettings(0.05, 10.0, 30.0)
    result = recommend_start_times(
        slots, power_kw=1.0, runtime_h=1.0, star_settings=settings
    )
    # Start 1: cost 0.115 vs min 0.10 → 15 % mehr → zwischen 4 und 1 Sternen
    assert 1 < result.options[1].stars < 4


def test_stars_neutral_when_all_equal():
    slots = make_slots([25.0, 25.0, 25.0, 25.0, 25.0, 25.0])
    result = recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)
    assert {o.stars for o in result.options} == {STAR_NEUTRAL}


def test_savings_vs_now():
    slots = make_slots([30.0, 10.0, 20.0, 40.0, 25.0, 35.0])
    result = recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)
    # sofort (Slot 0) = 0,30 €, günstigster (Slot 1) = 0,10 € → Ersparnis 0,20 €
    assert result.cheapest.savings_vs_now_eur == pytest.approx(0.20)
    assert result.immediate.savings_vs_now_eur == pytest.approx(0.0)


def test_run_may_extend_beyond_horizon():
    slots = make_slots([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0])
    result = recommend_start_times(slots, power_kw=1.0, runtime_h=3.0, horizon_h=6)
    # Alle 6 Startstunden bleiben gültig (Slots 6..8 decken den Überhang)
    assert len(result.options) == 6
    assert result.skipped_start_slots == 0


def test_skips_start_slots_without_enough_data():
    slots = make_slots([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    result = recommend_start_times(slots, power_kw=1.0, runtime_h=3.0, horizon_h=6)
    # Nur Starts 0..3 lassen 3 volle Slots zu (6 Slots insgesamt)
    assert len(result.options) == 4
    assert result.skipped_start_slots == 2


def test_horizon_limits_number_of_options():
    slots = make_slots([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0])
    result = recommend_start_times(slots, power_kw=1.0, runtime_h=1.0, horizon_h=6)
    assert len(result.options) == 6


@pytest.mark.parametrize("power_kw", [0.0, -1.0])
def test_invalid_power_raises(power_kw):
    slots = make_slots([10.0, 20.0])
    with pytest.raises(ValueError, match="power_kw"):
        recommend_start_times(slots, power_kw=power_kw, runtime_h=1.0)


@pytest.mark.parametrize("runtime_h", [0.0, -0.5])
def test_invalid_runtime_raises(runtime_h):
    slots = make_slots([10.0, 20.0])
    with pytest.raises(ValueError, match="runtime_h"):
        recommend_start_times(slots, power_kw=1.0, runtime_h=runtime_h)


def test_empty_slots_raises():
    with pytest.raises(ValueError, match="slots"):
        recommend_start_times([], power_kw=1.0, runtime_h=1.0)


def test_runtime_longer_than_all_slots_raises():
    slots = make_slots([10.0, 20.0])
    with pytest.raises(ValueError, match="keine Empfehlung"):
        recommend_start_times(slots, power_kw=1.0, runtime_h=5.0)


def test_missing_k_act_raises():
    slots = [
        {
            "slot_datetime": BASE,
            "k_push_act": 5.0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.0,
        },
        {
            "slot_datetime": BASE + timedelta(hours=1),
            "k_push_act": 5.0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.0,
        },
    ]
    with pytest.raises(ValueError, match="k_act"):
        recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)


def test_missing_k_push_act_raises():
    slots = make_slots([10.0, 20.0])
    del slots[0]["k_push_act"]
    with pytest.raises(ValueError, match="k_push_act"):
        recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)


def test_missing_expected_p_pv_raises():
    slots = make_slots([10.0, 20.0])
    del slots[0]["expected_p_pv"]
    with pytest.raises(ValueError, match="expected_p_pv"):
        recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)


def test_missing_expected_p_act_raises():
    slots = make_slots([10.0, 20.0])
    del slots[0]["expected_p_act"]
    with pytest.raises(ValueError, match="expected_p_act"):
        recommend_start_times(slots, power_kw=1.0, runtime_h=1.0)


def test_no_surplus_equals_import_only():
    slots = make_slots(
        [30.0],
        k_push_act=8.0,
        expected_p_pv=1.0,
        expected_p_act=1.0,
    )
    weights = [1.0]
    # surplus 0 → 2 kW * 30 ct = 60 ct = 0,60 €
    assert run_cost_eur(slots, 0, 2.0, weights) == pytest.approx(0.60)


def test_full_surplus_uses_export_tariff():
    slots = make_slots(
        [40.0],
        k_push_act=8.0,
        expected_p_pv=5.0,
        expected_p_act=1.0,
    )
    weights = [1.0]
    # surplus 4 kW ≥ power 2 → 2 * 8 ct = 16 ct = 0,16 €
    assert run_cost_eur(slots, 0, 2.0, weights) == pytest.approx(0.16)


def test_partial_surplus_splits_import_and_export():
    slots = make_slots(
        [40.0],
        k_push_act=10.0,
        expected_p_pv=3.0,
        expected_p_act=1.0,
    )
    weights = [1.0]
    # surplus 2, power 3 → 2*10 + 1*40 = 60 ct = 0,60 €
    assert run_cost_eur(slots, 0, 3.0, weights) == pytest.approx(0.60)


def test_ranking_prefers_pv_surplus_over_low_import():
    # Slot 0: low import, no surplus → full k_act
    # Slot 1: high import, full surplus at low export → cheaper opportunity cost
    slots = make_slots_detailed(
        [
            (10.0, 5.0, 0.0, 0.0),
            (50.0, 5.0, 4.0, 0.0),
            (40.0, 5.0, 0.0, 0.0),
            (40.0, 5.0, 0.0, 0.0),
            (40.0, 5.0, 0.0, 0.0),
            (40.0, 5.0, 0.0, 0.0),
        ]
    )
    result = recommend_start_times(slots, power_kw=2.0, runtime_h=1.0)
    assert result.cheapest.start_datetime == BASE + timedelta(hours=1)
    # 2 kW * 5 ct = 10 ct = 0,10 € (vs slot 0: 2*10 = 0,20 €)
    assert result.cheapest.cost_eur == pytest.approx(0.10)


def test_stars_abs_margin_on_fictitious_series():
    # Effective prices ~5.00 / 5.04 / 5.03 (full surplus) → within 0.05 margin
    slots = make_slots_detailed(
        [
            (40.0, 5.0, 5.0, 0.0),
            (40.0, 5.04, 5.0, 0.0),
            (40.0, 5.03, 5.0, 0.0),
            (40.0, 20.0, 0.0, 0.0),
            (40.0, 20.0, 0.0, 0.0),
            (40.0, 20.0, 0.0, 0.0),
        ]
    )
    settings = StarThresholdSettings(0.05, 10.0, 30.0)
    result = recommend_start_times(
        slots, power_kw=1.0, runtime_h=1.0, star_settings=settings
    )
    assert result.options[0].stars == STAR_MAX
    assert result.options[1].stars == STAR_MAX
    assert result.options[2].stars == STAR_MAX
