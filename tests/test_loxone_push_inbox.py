"""Pilot (spike/vo-push-pilot): Virtual Output push inbox + telemetry endpoint."""
from __future__ import annotations

import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from integrations import loxone_request_http as http_mod
from runtime_store import loxone_push_inbox as inbox


@pytest.fixture(autouse=True)
def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.delenv(http_mod.PUSH_TOKEN_ENV, raising=False)
    monkeypatch.delenv(inbox.REPEAT_ENV, raising=False)
    inbox.reset_memory_for_tests()
    http_mod.stop_loxone_request_http()
    yield
    http_mod.stop_loxone_request_http()
    inbox.reset_memory_for_tests()


@pytest.mark.parametrize(
    "ehal_id",
    [
        "sens_ess_soc",
        "get_ess_max_charge_power",
        "sens_absent_mode",
        "ess.ecoflow_delta_3.sens_ess_soc",
        "flex.waschmaschine.sens_power_act",  # legacy alias
        "consumer.waschmaschine.sens_power_act",
        "heatpump.waermepumpe.sens_temperature_heat_storage",
        "pool.pool_swimspa.sens_temperature_water",
        "evcs.garage.sens_evcs_connected",
        "ev.garage.sens_evcs_soc_act",
        "heartbeat",
    ],
)
def test_valid_ids(ehal_id: str) -> None:
    assert inbox.is_valid_ehal_id(ehal_id)


@pytest.mark.parametrize(
    "ehal_id",
    [
        "",
        "set_ess_charge_power_limit",  # setpoints are never pushed from Loxone
        "ess.x.set_ess_mode",
        "../etc/passwd",
        "ess.Bad Slug.sens_ess_soc",
        "sens_ess_soc/extra",
        "unknown.slug.sens_ess_soc",
        "sens_" + "a" * 100,
    ],
)
def test_invalid_ids(ehal_id: str) -> None:
    assert not inbox.is_valid_ehal_id(ehal_id)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12.5", 12.5),
        ("12,5", 12.5),
        ("-3.2", -3.2),
        ("3.5 kW", 3.5),
        ("55%", 55.0),
        ("0", 0.0),
        ("", None),
        ("abc", None),
        ("nan", None),
        ("inf", None),
        ("1" * 40, None),
    ],
)
def test_parse_push_value(raw: str, expected: float | None) -> None:
    assert inbox.parse_push_value(raw) == expected


def test_record_push_tracks_count_interval_and_peer() -> None:
    t0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
    assert inbox.record_push("sens_ess_soc", "55", "10.0.0.5", now=t0) == "new"
    assert inbox.record_push("sens_ess_soc", "56", "10.0.0.5", now=t0 + timedelta(seconds=30)) == "ok"
    assert inbox.record_push("sens_ess_soc", "56", "10.0.0.5", now=t0 + timedelta(seconds=60)) == "ok"
    row = inbox.load_inbox()["sens_ess_soc"]
    assert row["count"] == 3
    assert row["value"] == 56.0
    assert row["raw"] == "56"
    assert row["peer"] == "10.0.0.5"
    assert row["parse_ok"] is True
    assert row["interval_ema_s"] == pytest.approx(30.0)


def test_unparseable_value_is_kept_for_inspection() -> None:
    assert inbox.record_push("sens_ess_soc", "n/a", "x") == "new"
    row = inbox.load_inbox()["sens_ess_soc"]
    assert row["parse_ok"] is False
    assert row["value"] is None
    assert row["raw"] == "n/a"


def test_record_push_rejects_bad_input_and_caps_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    assert inbox.record_push("bad id", "1") == "bad_id"
    assert inbox.record_push("sens_ess_soc", "") == "bad_raw"
    assert inbox.record_push("sens_ess_soc", "1" * 40) == "bad_raw"
    monkeypatch.setattr(inbox, "MAX_IDS", 2)
    assert inbox.record_push("sens_a", "1") == "new"
    assert inbox.record_push("sens_b", "1") == "new"
    assert inbox.record_push("sens_c", "1") == "full"
    assert inbox.record_push("sens_a", "2") == "ok"  # existing IDs keep updating
    assert set(inbox.load_inbox()) == {"sens_a", "sens_b"}


def test_staleness_uses_configured_repeat_not_smoothed_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(inbox.REPEAT_ENV, raising=False)
    t0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
    # Bursts of changes (7 s, 15 s gaps) pull the smoothed interval far below the repeat.
    for offset in (0, 7, 22, 37):
        inbox.record_push("sens_ess_soc", "55", now=t0 + timedelta(seconds=offset))
    row = inbox.load_inbox()["sens_ess_soc"]
    assert row["interval_ema_s"] < 20
    last = t0 + timedelta(seconds=37)
    assert not inbox.is_stale(row, now=last + timedelta(seconds=10))  # next repeat is due
    assert not inbox.is_stale(row, now=last + timedelta(seconds=25))
    assert inbox.is_stale(row, now=last + timedelta(seconds=35))  # > 3 x 10 s


def test_staleness_respects_repeat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(inbox.REPEAT_ENV, "60")
    t0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
    inbox.record_push("sens_ess_soc", "55", now=t0)
    row = inbox.load_inbox()["sens_ess_soc"]
    assert not inbox.is_stale(row, now=t0 + timedelta(seconds=170))
    assert inbox.is_stale(row, now=t0 + timedelta(seconds=190))
    monkeypatch.setenv(inbox.REPEAT_ENV, "garbage")
    assert inbox.expected_repeat_s() == inbox.DEFAULT_REPEAT_S


def _get(port: int, path: str, headers: dict[str, str] | None = None) -> int:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=2) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_endpoint_disabled_without_token() -> None:
    port = http_mod.start_loxone_request_http(0).server_address[1]
    assert _get(port, "/ehal/loxone/telemetry/sens_ess_soc/55") == 404
    assert inbox.load_inbox() == {}


def test_endpoint_token_validation_and_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, "s3cret")
    port = http_mod.start_loxone_request_http(0).server_address[1]
    base = "/ehal/loxone/telemetry/"
    assert _get(port, base + "sens_ess_soc/55") == 401
    assert _get(port, base + "sens_ess_soc/55?t=wrong") == 401
    assert _get(port, base + "sens_ess_soc/55?t=s3cret") == 204
    assert _get(port, base + "ess.ecoflow_delta_3.sens_ess_soc/61,5", {http_mod.PUSH_TOKEN_HEADER: "s3cret"}) == 204
    assert _get(port, base + "set_ess_mode/1?t=s3cret") == 400
    assert _get(port, base + "sens_ess_soc?t=s3cret") == 400  # no value
    rows = inbox.load_inbox()
    assert rows["sens_ess_soc"]["value"] == 55.0
    assert rows["ess.ecoflow_delta_3.sens_ess_soc"]["value"] == 61.5
    assert "set_ess_mode" not in rows


def test_existing_endpoints_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, "s3cret")
    port = http_mod.start_loxone_request_http(0).server_address[1]
    assert _get(port, "/ehal/loxone/alive") == 204
    assert _get(port, "/ehal/loxone/status.json") == 200
    assert _get(port, "/nope") == 404


# --- derived value state -------------------------------------------------------------------
def _now():
    from datetime import datetime, timezone

    return datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def _row(value: float | None, age_s: float, *, parse_ok: bool = True) -> dict:
    from datetime import timedelta

    last = _now() - timedelta(seconds=age_s)
    return {"value": value, "raw": str(value), "parse_ok": parse_ok, "last_ts": last.isoformat(), "count": 3}


def test_link_alive_from_fresh_nonzero_analog_or_heartbeat() -> None:
    assert inbox.link_alive({"heartbeat": _row(1.0, 5)}, now=_now())
    assert inbox.link_alive({"sens_ess_soc": _row(55.0, 20)}, now=_now())
    assert not inbox.link_alive({"sens_ess_soc": _row(55.0, 35)}, now=_now())  # older than 3 x 10 s
    assert not inbox.link_alive({"sens_grid_power_active": _row(0.0, 5)}, now=_now())  # zero is no proof
    assert not inbox.link_alive({"sens_absent_mode": _row(1.0, 5)}, now=_now())  # digital is edge-based
    assert not inbox.link_alive({}, now=_now())


def test_derive_state_analog() -> None:
    def d(row, link):
        return inbox.derive_state("sens_ess_soc", row, link=link, now=_now())

    assert d(_row(55.0, 20), True) == (inbox.STATE_OK, 55.0)
    assert d(_row(55.0, 200), True) == (inbox.STATE_ZERO_ASSUMED_SILENT, 0.0)
    assert d(_row(55.0, 200), False) == (inbox.STATE_UNKNOWN, None)
    assert d(None, True) == (inbox.STATE_ZERO_ASSUMED_NEVER, 0.0)
    assert d(None, False) == (inbox.STATE_UNKNOWN, None)
    assert d(_row(0.0, 500), True) == (inbox.STATE_ZERO_HELD, 0.0)
    assert d(_row(0.0, 500), False) == (inbox.STATE_ZERO_HELD_NO_LINK, 0.0)
    assert d(_row(None, 5, parse_ok=False), True) == (inbox.STATE_UNREADABLE, None)


def test_derive_state_digital_is_held_until_next_edge() -> None:
    def d(row, link):
        return inbox.derive_state("sens_evcs_connected", row, link=link, now=_now())

    assert d(_row(1.0, 20), True) == (inbox.STATE_OK, 1.0)
    assert d(_row(1.0, 900), True) == (inbox.STATE_DIGITAL_HELD, 1.0)  # no repeat needed
    assert d(_row(1.0, 900), False) == (inbox.STATE_DIGITAL_HELD, 1.0)
    assert d(_row(0.0, 900), True) == (inbox.STATE_ZERO_HELD, 0.0)


def test_read_push_ready_by_time_numeric_and_text() -> None:
    eid = "ev.e_auto.get_evcs_ready_by_time"
    now = _now()
    assert inbox.is_valid_ehal_id(eid)
    inbox.record_push(eid, "1735689600", now=now)
    assert inbox.read_push_ready_by_time(eid, now=now) == pytest.approx(1735689600.0)
    inbox.reset_memory_for_tests()
    inbox.record_push(eid, "Morgen, 16:03", now=now)
    assert inbox.read_push_ready_by_time(eid, now=now) == "Morgen, 16:03"


def test_read_push_ready_by_time_stale_holds_numeric_not_zero() -> None:
    eid = "ev.e_auto.get_evcs_ready_by_time"
    t0 = _now()
    inbox.record_push(eid, "1735689600", now=t0)
    stale = t0 + timedelta(seconds=120)
    assert inbox.read_push_ready_by_time(eid, now=stale) == pytest.approx(1735689600.0)
    too_old = t0 + timedelta(seconds=400)
    assert inbox.read_push_ready_by_time(eid, now=too_old) is None
    inbox.clear_inbox()
    assert inbox.read_push_ready_by_time(eid, now=t0) is None
    inbox.record_push(eid, "Morgen, 08:00", now=t0)
    assert inbox.read_push_ready_by_time(eid, now=t0 + timedelta(seconds=120)) is None


# --- token as address prefix: http://host:8541/t/<token> + command /ehal/loxone/telemetry/... ----
def test_split_token_prefix() -> None:
    split = http_mod.split_token_prefix
    assert split("/t/abc123/ehal/loxone/telemetry/sens_ess_soc/5") == ("abc123", "/ehal/loxone/telemetry/sens_ess_soc/5")
    assert split("/t/abc%2D1/x?y=1") == ("abc-1", "/x?y=1")
    assert split("/ehal/loxone/telemetry/sens_ess_soc/5") == (None, "/ehal/loxone/telemetry/sens_ess_soc/5")
    assert split("/t/abc") == ("abc", "/")


def test_endpoint_accepts_token_in_address_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, "s3cret-token")
    port = http_mod.start_loxone_request_http(0).server_address[1]
    base = "/ehal/loxone/telemetry/"
    assert _get(port, "/t/s3cret-token" + base + "sens_ess_soc/55.5") == 204
    assert _get(port, "/t/wrong" + base + "sens_ess_soc/56") == 401
    assert _get(port, "/t/s3cret-token" + base + "set_ess_mode/1") == 400  # setpoints never accepted
    assert _get(port, "/t/s3cret-token/ehal/loxone/status.json") == 404  # other routes not via prefix
    assert _get(port, "/t/s3cret-token/ehal/loxone/alive") == 404
    # older variants still work
    assert _get(port, base + "sens_pv_production_active/1?t=s3cret-token") == 204
    assert _get(port, base + "heartbeat/1", {http_mod.PUSH_TOKEN_HEADER: "s3cret-token"}) == 204
    rows = inbox.load_inbox()
    assert rows["sens_ess_soc"]["value"] == 55.5
    assert set(rows) == {"sens_ess_soc", "sens_pv_production_active", "heartbeat"}


def test_header_wins_over_prefix_and_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, "s3cret-token")
    port = http_mod.start_loxone_request_http(0).server_address[1]
    path = "/t/s3cret-token/ehal/loxone/telemetry/sens_ess_soc/1"
    assert _get(port, path, {http_mod.PUSH_TOKEN_HEADER: "wrong"}) == 401


def test_prefix_endpoint_disabled_without_token() -> None:
    port = http_mod.start_loxone_request_http(0).server_address[1]
    assert _get(port, "/t/anything/ehal/loxone/telemetry/sens_ess_soc/1") == 404
    assert inbox.load_inbox() == {}
