"""Live Energy-Charts disk cache: skip fetch when fresh; prefer cache over aWATTar."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data import live_market_prices as lmp
from data.live_price_cache import (
    cache_covers_window,
    cache_is_fresh_for_day_ahead,
    cache_path_for_zone,
    load_live_price_cache,
    network_fetch_start,
    save_live_price_cache,
)

TZ = ZoneInfo("Europe/Vienna")


def _slot(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _qh_series(start: datetime, hours: int, base: float = 10.0) -> list[dict]:
    rows: list[dict] = []
    for index in range(hours * 4):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "timestamp": slot,
                "hour": slot.hour,
                "price_buy": round(base + (index % 4) * 0.1, 4),
            }
        )
    return rows


def test_cache_covers_window_requires_full_span():
    prices = _qh_series(_slot(2026, 10, 3, 0), hours=24)
    assert cache_covers_window(
        [{"timestamp": p["timestamp"].isoformat(), "price_buy": p["price_buy"]} for p in prices],
        _slot(2026, 10, 3, 0),
        _slot(2026, 10, 3, 23, 45),
        fallback_tz=TZ,
    )
    assert not cache_covers_window(
        [{"timestamp": p["timestamp"].isoformat(), "price_buy": p["price_buy"]} for p in prices],
        _slot(2026, 10, 2, 23),
        _slot(2026, 10, 3, 23, 45),
        fallback_tz=TZ,
    )


def test_cache_freshness_flips_at_day_ahead_publish():
    fetched_morning = _slot(2026, 10, 4, 10)
    assert cache_is_fresh_for_day_ahead(fetched_morning, _slot(2026, 10, 4, 11))
    assert not cache_is_fresh_for_day_ahead(fetched_morning, _slot(2026, 10, 4, 13))
    fetched_afternoon = _slot(2026, 10, 4, 13)
    assert cache_is_fresh_for_day_ahead(fetched_afternoon, _slot(2026, 10, 4, 18))


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    live = _qh_series(_slot(2026, 10, 3, 0), hours=2)
    path = save_live_price_cache(
        "AT",
        live,
        fetched_at=_slot(2026, 10, 3, 14),
        window_start=_slot(2026, 10, 3, 0),
        window_end=_slot(2026, 10, 3, 1, 45),
    )
    assert path == cache_path_for_zone("AT")
    loaded = load_live_price_cache("AT", fallback_tz=TZ)
    assert loaded is not None
    assert loaded["fetched_at"] == _slot(2026, 10, 3, 14)
    assert len(loaded["prices"]) == 8


def test_fetch_skips_network_when_cache_covers_and_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(lmp.config, "get_planning_timezone", lambda: "Europe/Vienna")
    start = _slot(2026, 9, 27, 0)
    end = _slot(2026, 10, 5, 12)
    live = _qh_series(start, hours=int((end - start).total_seconds() // 3600) + 1)
    save_live_price_cache(
        "AT",
        live,
        fetched_at=_slot(2026, 10, 4, 13),
        window_start=start,
        window_end=end,
    )
    planning_end = _slot(2026, 10, 5, 12)
    with patch.object(lmp, "_runtime_market_zone", return_value="AT"):
        with patch.object(lmp, "_now_slot", return_value=_slot(2026, 10, 4, 15)):
            with patch.object(
                lmp, "awattar_fetch_window", return_value=(start, end)
            ):
                with patch.object(
                    lmp, "fetch_energy_charts_prices"
                ) as fetch_ec:
                    with patch.object(
                        lmp, "_fetch_awattar_live_fallback"
                    ) as awattar:
                        result = lmp.fetch_live_day_ahead_prices(
                            planning_end=planning_end
                        )
    assert result is not None
    assert len(result) == len(live)
    fetch_ec.assert_not_called()
    awattar.assert_not_called()


def test_fetch_uses_stale_cache_before_awattar_on_outage(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(lmp.config, "get_planning_timezone", lambda: "Europe/Vienna")
    start = _slot(2026, 9, 27, 0)
    end = _slot(2026, 10, 5, 12)
    live = _qh_series(start, hours=int((end - start).total_seconds() // 3600) + 1)
    # Fetched before today's 12:00 → stale for skip-fetch, still usable on outage.
    save_live_price_cache(
        "AT",
        live,
        fetched_at=_slot(2026, 10, 4, 10),
        window_start=start,
        window_end=end,
    )
    planning_end = _slot(2026, 10, 5, 12)
    with patch.object(lmp, "_runtime_market_zone", return_value="AT"):
        with patch.object(lmp, "_now_slot", return_value=_slot(2026, 10, 4, 15)):
            with patch.object(
                lmp, "awattar_fetch_window", return_value=(start, end)
            ):
                with patch.object(
                    lmp,
                    "fetch_energy_charts_prices",
                    side_effect=RuntimeError("503"),
                ):
                    with patch.object(
                        lmp, "_fetch_awattar_live_fallback", return_value=[{"ok": True}]
                    ) as awattar:
                        result = lmp.fetch_live_day_ahead_prices(
                            planning_end=planning_end
                        )
    assert result is not None
    assert result[0]["price_buy"] == pytest.approx(live[0]["price_buy"])
    awattar.assert_not_called()


def test_fetch_falls_back_to_awattar_without_usable_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(lmp.config, "get_planning_timezone", lambda: "Europe/Vienna")
    planning_end = _slot(2026, 10, 6, 7, 26)
    start, end = _slot(2026, 9, 27, 0), planning_end
    with patch.object(lmp, "_runtime_market_zone", return_value="AT"):
        with patch.object(lmp, "_now_slot", return_value=_slot(2026, 10, 4, 15)):
            with patch.object(
                lmp, "awattar_fetch_window", return_value=(start, end)
            ):
                with patch.object(
                    lmp,
                    "fetch_energy_charts_prices",
                    side_effect=RuntimeError("503"),
                ):
                    with patch.object(
                        lmp,
                        "_fetch_awattar_live_fallback",
                        return_value=[{"ok": True}],
                    ) as awattar:
                        result = lmp.fetch_live_day_ahead_prices(
                            planning_end=planning_end
                        )
    assert result == [{"ok": True}]
    awattar.assert_called_once()


def test_successful_fetch_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(lmp.config, "get_planning_timezone", lambda: "Europe/Vienna")
    start = _slot(2026, 10, 4, 0)
    end = _slot(2026, 10, 5, 0)
    index = pd.date_range(start.replace(tzinfo=None), periods=8, freq="15min")
    df = pd.DataFrame({"price_cent_kwh": [11.0 + i for i in range(8)]}, index=index)
    with patch.object(lmp, "_runtime_market_zone", return_value="AT"):
        with patch.object(lmp, "_now_slot", return_value=_slot(2026, 10, 4, 13)):
            with patch.object(
                lmp, "awattar_fetch_window", return_value=(start, end)
            ):
                with patch.object(lmp, "fetch_energy_charts_prices", return_value=df):
                    result = lmp.fetch_live_day_ahead_prices(planning_end=end)
    assert result is not None
    assert len(result) == 8
    loaded = load_live_price_cache("AT", fallback_tz=TZ)
    assert loaded is not None
    assert len(loaded["prices"]) == 8


def test_network_fetch_start_uses_today_when_history_cached():
    needed_start = _slot(2026, 9, 27, 0)
    needed_end = _slot(2026, 10, 5, 12)
    now = _slot(2026, 10, 4, 15)
    cached = _qh_series(needed_start, hours=24 * 8)
    assert network_fetch_start(needed_start, needed_end, cached, now) == _slot(
        2026, 10, 4, 0
    )
    assert network_fetch_start(needed_start, needed_end, None, now) == needed_start


def test_refresh_fetches_from_today_and_merges_cache_history(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setattr(lmp.config, "get_planning_timezone", lambda: "Europe/Vienna")
    needed_start = _slot(2026, 9, 27, 0)
    needed_end = _slot(2026, 10, 5, 12)
    now = _slot(2026, 10, 4, 15)
    # Stale vs Day-Ahead publish (fetched before 12:00) but history complete.
    cached = _qh_series(needed_start, hours=int((needed_end - needed_start).total_seconds() // 3600) + 1)
    save_live_price_cache(
        "AT",
        cached,
        fetched_at=_slot(2026, 10, 4, 10),
        window_start=needed_start,
        window_end=needed_end,
    )
    today = _slot(2026, 10, 4, 0)
    index = pd.date_range(today.replace(tzinfo=None), periods=8, freq="15min")
    df = pd.DataFrame({"price_cent_kwh": [90.0 + i for i in range(8)]}, index=index)

    with patch.object(lmp, "_runtime_market_zone", return_value="AT"):
        with patch.object(lmp, "_now_slot", return_value=now):
            with patch.object(
                lmp, "awattar_fetch_window", return_value=(needed_start, needed_end)
            ):
                with patch.object(
                    lmp, "fetch_energy_charts_prices", return_value=df
                ) as fetch_ec:
                    result = lmp.fetch_live_day_ahead_prices(planning_end=needed_end)

    assert fetch_ec.call_count == 1
    call_start = fetch_ec.call_args.args[0]
    assert pd.Timestamp(call_start) == pd.Timestamp(today.replace(tzinfo=None))
    assert result is not None
    # History from cache kept; refreshed slots use new EC values.
    by_ts = {row["timestamp"]: row["price_buy"] for row in result}
    assert by_ts[_slot(2026, 9, 27, 0)] == pytest.approx(cached[0]["price_buy"])
    assert by_ts[today] == pytest.approx(90.0)
