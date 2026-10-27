"""Edibert P6: the ``opendata`` package stands alone and has one retry policy."""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

import opendata
from opendata import http

PACKAGE_DIR = Path(opendata.__file__).resolve().parent
ALLOWED_THIRD_PARTY = {"requests", "pandas", "numpy"}


def _imported_top_level(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_package_imports_only_stdlib_and_allowed_libraries():
    allowed = set(sys.stdlib_module_names) | ALLOWED_THIRD_PARTY | {"opendata", "__future__"}
    offending = {
        path.name: sorted(_imported_top_level(path) - allowed)
        for path in sorted(PACKAGE_DIR.rglob("*.py"))
        if _imported_top_level(path) - allowed
    }
    assert offending == {}


class _Response:
    def __init__(self, status: int, body=None, headers=None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url: x", response=self)


def _session(responses, **kwargs):
    calls = []

    def transport(url, params, timeout_s):
        calls.append((url, dict(params), timeout_s))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return http.Session(timeout_s=5.0, transport=transport, **kwargs), calls


def test_retries_429_then_returns_payload():
    session, calls = _session([_Response(429), _Response(503), _Response(200, {"ok": 1})])
    with patch("opendata.http.time.sleep") as sleep:
        assert session.get_json("https://example.org/a", {"x": 1}) == {"ok": 1}
    assert len(calls) == 3
    assert [c.args[0] for c in sleep.call_args_list] == [2.0, 4.0]


def test_retry_after_header_wins_over_backoff():
    session, _calls = _session([_Response(429, headers={"Retry-After": "7"}), _Response(200, {})])
    with patch("opendata.http.time.sleep") as sleep:
        session.get_json("https://example.org/a", {})
    assert sleep.call_args.args[0] == 7.0


def test_exhausted_retries_raise_the_last_http_error():
    session, calls = _session([_Response(429) for _ in range(5)])
    with patch("opendata.http.time.sleep"):
        with pytest.raises(requests.HTTPError, match="429"):
            session.get_json("https://example.org/a", {})
    assert len(calls) == 5


def test_client_error_is_not_retried():
    session, calls = _session([_Response(400)])
    with pytest.raises(requests.HTTPError, match="400"):
        session.get_json("https://example.org/a", {})
    assert len(calls) == 1


def test_connection_error_raises_unreachable_at_once():
    session, calls = _session([requests.ConnectionError("down")])
    with pytest.raises(opendata.ApiUnreachableError, match="nicht erreichbar"):
        session.get_json("https://example.org/a", {})
    assert len(calls) == 1


def test_pause_after_success_per_host():
    session, _calls = _session([_Response(200, {}), _Response(200, {})], pause_after_s={"slow.example": 0.75})
    with patch("opendata.http.time.sleep") as sleep:
        session.get_json("https://slow.example/a", {})
        session.get_json("https://fast.example/a", {})
    assert [c.args[0] for c in sleep.call_args_list] == [0.75]


def test_budget_stops_waiting_and_names_the_last_error():
    session, _calls = _session([_Response(429) for _ in range(5)])
    with opendata.fetch_budget(1.0):
        with pytest.raises(opendata.FetchBudgetExceeded, match="429"):
            session.get_json("https://example.org/a", {})


def test_settled_request_is_served_from_disk_on_the_second_call(tmp_path):
    from datetime import date

    session, calls = _session([_Response(200, {"v": [1, 2]})], cache_dir=tmp_path)
    for _ in range(2):
        payload = session.get_json_cached(
            "https://example.org/a/b", {"y": 2, "x": 1}, last_day=date(2020, 1, 31), settle_days=2
        )
        assert payload == {"v": [1, 2]}
    assert len(calls) == 1
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()] == [
        "example.org/a/b/x=1&y=2.json"
    ]


def test_unsettled_request_is_fetched_every_time_and_never_stored(tmp_path):
    from opendata.cache import settled_through

    session, calls = _session([_Response(200, {"v": 1}), _Response(200, {"v": 2})], cache_dir=tmp_path)
    last_day = settled_through(2).fromordinal(settled_through(2).toordinal() + 1)
    assert session.get_json_cached("https://example.org/a", {}, last_day=last_day, settle_days=2) == {"v": 1}
    assert session.get_json_cached("https://example.org/a", {}, last_day=last_day, settle_days=2) == {"v": 2}
    assert len(calls) == 2
    assert not any(tmp_path.iterdir())


def test_cache_file_of_another_request_fails_loud(tmp_path):
    import json
    from datetime import date

    from opendata.cache import ResponseCache

    cache = ResponseCache(tmp_path)
    path = cache.path("https://example.org/a", {"x": 1})
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"url": "https://example.org/other", "params": {"x": "1"}, "payload": 1}))
    session, _calls = _session([], cache_dir=tmp_path)
    with pytest.raises(RuntimeError, match="anderen Anfrage"):
        session.get_json_cached("https://example.org/a", {"x": 1}, last_day=date(2020, 1, 1), settle_days=2)


def test_earnie_tests_never_use_the_repo_cache():
    from data import opendata_session

    assert opendata_session.cache_dir().resolve() != opendata_session.OPENDATA_CACHE_DIR.resolve()


# Product packages (pyproject ``packages.find``) plus the entry points in the repo root.
PRODUCT_DIRS = ("optimizer", "data", "integrations", "runtime_store", "ui", "simulation", "scripts", "ehal")
# Day-Ahead prices come from Edibert's market module (Edibert P4a); the host only names the shadow feed.
HOST_NAMED_OUTSIDE_OPENDATA = {"data/edibert_live_market.py"}
# Records the pre-P6 behaviour on purpose (parity golden).
GOLDEN_SCRIPT = "scripts/opendata_golden.py"


def test_only_opendata_talks_to_open_meteo_and_energy_charts():
    root = PACKAGE_DIR.parent
    files = [p for d in PRODUCT_DIRS for p in (root / d).rglob("*.py")] + list(root.glob("*.py"))
    naming = sorted(
        rel
        for path in files
        if (rel := path.relative_to(root).as_posix()) != GOLDEN_SCRIPT
        and any(host in path.read_text(encoding="utf-8") for host in ("open-meteo.com", "energy-charts.info"))
    )
    assert naming == sorted(HOST_NAMED_OUTSIDE_OPENDATA)


def test_parallel_writers_and_readers_leave_one_valid_file(tmp_path):
    """SE workers share the cache dir: concurrent stores of one request never corrupt it."""
    import threading

    from opendata.cache import ResponseCache

    url, params, payload = "https://example.org/a", {"x": 1}, {"v": list(range(2000))}
    errors: list[BaseException] = []

    def _work() -> None:
        cache = ResponseCache(tmp_path)
        try:
            for _ in range(30):
                cache.store(url, params, payload)
                assert cache.load(url, params) in (None, payload)
        except BaseException as exc:  # noqa: BLE001  (collected for the assert below)
            errors.append(exc)

    threads = [threading.Thread(target=_work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert ResponseCache(tmp_path).load(url, params) == payload
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["x=1.json"]


def test_cache_dir_env_override(monkeypatch, tmp_path):
    from data import opendata_session

    monkeypatch.setenv("EARNIE_ENERGY_CHARTS_CACHE_PATH", str(tmp_path / "ec"))
    assert opendata_session.session().cache.root == tmp_path / "ec"
    monkeypatch.delenv("EARNIE_ENERGY_CHARTS_CACHE_PATH")
    assert opendata_session.session().cache.root == opendata_session.OPENDATA_CACHE_DIR


def test_energy_charts_honours_retry_after_and_floors_the_timeout():
    from datetime import date

    from opendata import energy_charts

    session, calls = _session(
        [_Response(429, headers={"Retry-After": "3"}), _Response(200, {"unix_seconds": [1]})]
    )
    with patch("opendata.http.time.sleep") as sleep:
        payload = energy_charts.public_power(session, country="de", start=date(2025, 7, 1), end=date(2025, 7, 1))
    assert payload == {"unix_seconds": [1]}
    assert [c.args[0] for c in sleep.call_args_list] == [3.0]
    assert [c[2] for c in calls] == [30.0, 30.0]


def test_energy_charts_raises_the_last_http_error_after_five_429():
    from datetime import date

    from opendata import energy_charts

    session, calls = _session([_Response(429) for _ in range(5)])
    with patch("opendata.http.time.sleep"):
        with pytest.raises(requests.HTTPError, match="429 for url: https://api.energy-charts.info/price"):
            energy_charts.price(session, bzn="AT", start=date(2025, 7, 1), end=date(2025, 7, 1))
    assert len(calls) == 5
