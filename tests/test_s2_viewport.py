"""Tests für Phone/Desktop S-2-Span-Erkennung."""
from __future__ import annotations

from ui.s2_viewport import is_phone_user_agent


def test_iphone_is_phone():
    assert is_phone_user_agent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    )


def test_android_mobile_is_phone():
    assert is_phone_user_agent(
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "Mobile Safari/537.36"
    )


def test_ipad_is_not_phone():
    assert not is_phone_user_agent(
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    )


def test_desktop_chrome_is_not_phone():
    assert not is_phone_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )


def test_empty_ua_is_not_phone():
    assert not is_phone_user_agent("")
