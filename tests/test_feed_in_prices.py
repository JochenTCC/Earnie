"""Tests für stündliche vs. fixe Einspeisevergütung."""
from __future__ import annotations

import pytest

from data.feed_in_prices import (
    FEED_IN_MODE_DYNAMIC_EPEX,
    FEED_IN_MODE_FIXED,
    FeedInSettings,
    epex_to_feed_in_cent,
    enrich_matrix_feed_in_prices,
    feed_in_settings_from_dict,
    k_push_act_for_matrix_row,
    resolve_k_push_act,
    validate_feed_in_mode,
)


def test_validate_feed_in_mode_rejects_unknown():
    with pytest.raises(ValueError, match="Unbekannter feed_in_mode"):
        validate_feed_in_mode("hourly_magic")


def test_epex_to_feed_in_cent_sunny_spot_formula():
    assert epex_to_feed_in_cent(10.0, 0.19, 0.0) == pytest.approx(8.1)
    assert epex_to_feed_in_cent(-5.0, 0.19, 0.0) == pytest.approx(-5.95)


def test_fixed_mode_uses_k_push_cent():
    settings = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
    )
    assert resolve_k_push_act(100.0, settings) == 3.7
    assert resolve_k_push_act(None, settings) == 3.7


def test_dynamic_mode_requires_epex():
    settings = FeedInSettings(
        mode=FEED_IN_MODE_DYNAMIC_EPEX,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
    )
    assert resolve_k_push_act(10.0, settings) == pytest.approx(8.1)
    with pytest.raises(ValueError, match="price_buy"):
        resolve_k_push_act(None, settings)


def test_feed_in_settings_from_dict_requires_fee_for_dynamic():
    runtime = {"k_push_cent": 3.7, "feed_in_mode": "dynamic_epex"}
    with pytest.raises(ValueError, match="feed_in_fee_factor"):
        feed_in_settings_from_dict(runtime, {})


def test_enrich_matrix_feed_in_prices():
    matrix = [
        {"hour": 0, "k_act": 20.0, "price_buy": 10.0, "expected_p_pv": 0.0, "expected_p_act": 1.0},
        {"hour": 1, "k_act": 25.0, "price_buy": 5.0, "expected_p_pv": 0.0, "expected_p_act": 1.0},
    ]
    settings = FeedInSettings(
        mode=FEED_IN_MODE_DYNAMIC_EPEX,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
    )
    enrich_matrix_feed_in_prices(matrix, settings)
    assert matrix[0]["k_push_act"] == pytest.approx(8.1)
    assert matrix[1]["k_push_act"] == pytest.approx(4.05)


def test_k_push_act_for_matrix_row_prefers_matrix_value():
    row = {"k_push_act": 12.5, "k_act": 30.0}
    assert k_push_act_for_matrix_row(row, 3.5) == 12.5


def test_k_push_act_for_matrix_row_uses_fallback():
    row = {"k_act": 30.0}
    assert k_push_act_for_matrix_row(row, 3.5) == 3.5
