# tests/conftest.py
from __future__ import annotations

import atexit
import itertools
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.fixtures.historical_fixtures import CONS_DATA_FILE, fixture_available
from tests.regression.baseline import GIT_LOCATION_ENV

# pytest runs inside .githooks/pre-commit, where git exports GIT_DIR / GIT_INDEX_FILE.
# Tests that run git in a tmp repo would inherit them and write to the real repo
# (config, index, refs). Drop them for the whole test process.
for _key in GIT_LOCATION_ENV:
    os.environ.pop(_key, None)


def _configure_console_utf8() -> None:
    """Windows cp1252 stdout cannot encode repo Unicode (→, ₀, umlauts)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


_configure_console_utf8()

TEST_TIMEZONE = "Europe/Vienna"


def _pin_local_timezone() -> None:
    """Naive local time in the code under test must match the Vienna fixtures.

    CI runners are UTC; without this the early-start equivalence tests see
    1-2 h shifted hours/days. Windows has no ``tzset`` (uses the system zone).
    """
    if hasattr(time, "tzset"):
        os.environ["TZ"] = TEST_TIMEZONE
        time.tzset()


_pin_local_timezone()

ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATHS = (ROOT / "earnie_env" / "config" / ".env", ROOT / ".env")
DEFAULT_TEST_CONFIG_PATH = ROOT / "tests" / "fixtures" / "backtesting" / "config.json"
_USE_LIVE_CONFIG_ENV = "EARNIE_TEST_USE_LIVE_CONFIG"


def _apply_default_test_config_env() -> None:
    """Fixture-Config erzwingen — unabhängig von lokaler .env/NAS-Pfad."""
    if os.getenv(_USE_LIVE_CONFIG_ENV) == "1":
        return
    os.environ["EARNIE_CONFIG_PATH"] = str(DEFAULT_TEST_CONFIG_PATH)
    os.environ.setdefault("EARNIE_OFFLINE", "1")
    bt_dir = DEFAULT_TEST_CONFIG_PATH.parent
    # Force-overwrite (not setdefault): after monkeypatch undo / xdist workers,
    # leftover sidecar paths must not stick to a previous test's tmp_path.
    os.environ["EARNIE_TARIFFS_PATH"] = str(bt_dir / "tariffs.json")
    os.environ["EARNIE_HOUSE_PROFILES_PATH"] = str(bt_dir / "house_profiles.json")
    os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"] = str(
        bt_dir / "backtesting_scenarios.json"
    )
    os.environ["EARNIE_COMPONENTS_PATH"] = str(bt_dir / "components.json")
    os.environ.pop("EARNIE_DEVIATION_RULES_PATH", None)
    # Do not force EARNIE_GRID_FEES_PATH here — bootstrap tests must seed
    # config/grid_fees.json from share/. AppTest sets the public catalog path.


_apply_default_test_config_env()

from tests.fixtures.backtesting_fixtures import install_fixture_flex_consumers  # noqa: E402

install_fixture_flex_consumers()


def _has_runtime_cons_data() -> bool:
    return (ROOT / "cons_data.csv").is_file() or (
        ROOT / "runtime" / "cons_data.csv"
    ).is_file()


requires_historical_data = pytest.mark.skipif(
    not fixture_available(),
    reason=(
        "tests/fixtures/historical/cons_data.csv fehlt "
        "(python -m scripts.extract_historical_fixtures)"
    ),
)


requires_runtime_cons_data = pytest.mark.skipif(
    not _has_runtime_cons_data(),
    reason="runtime/cons_data.csv wird für Backtesting-Smoke-Tests benötigt",
)


@pytest.fixture(scope="module")
def historical_cons_data():
    """Pfad zur isolierten cons_data-Test-Fixture (unabhängig von runtime/)."""
    if not fixture_available():
        pytest.skip(
            "tests/fixtures/historical/cons_data.csv fehlt "
            "(python -m scripts.extract_historical_fixtures)"
        )
    return str(CONS_DATA_FILE)


def _load_dotenv_for_tests() -> None:
    for dotenv_path in DOTENV_PATHS:
        if dotenv_path.is_file():
            load_dotenv(dotenv_path, override=False)
            break
    _apply_default_test_config_env()


_load_dotenv_for_tests()

import config as _config_module


def _isolate_open_meteo_disk_cache() -> Path:
    """Point the Open-Meteo archive cache at a per-process temp dir.

    The climate mock patches only the HTTP fetch; ``build_open_meteo_climate_bundle``
    still writes its result to ``data/cache/open_meteo_utc`` (relative to the repo).
    Without this, every pytest run poisons the real cache with mock irradiance
    (constant 500 W/m², day and night), which ``scripts.run_regression`` and the
    app then read back as real PV input.
    """
    import atexit
    import shutil
    import tempfile

    from data import open_meteo_solar_archive as _archive

    cache_dir = Path(tempfile.mkdtemp(prefix="earnie-open-meteo-test-"))
    _archive.OPEN_METEO_CACHE_DIR = cache_dir
    _archive.clear_open_meteo_bundle_mem_cache()
    atexit.register(shutil.rmtree, cache_dir, ignore_errors=True)
    return cache_dir


_isolate_open_meteo_disk_cache()


def _reinit_config_offline() -> None:
    """reinit_config() ohne Live-Open-Meteo-Fetch (Fixture-Profile enthalten
    thermal_annual-Verbraucher, deren Baseload-Berechnung sonst
    archive-api.open-meteo.com kontaktiert — in CI ohne Netzwerkzugriff
    bricht das mit ReadTimeout ab, bevor überhaupt ein Test läuft)."""
    from tests.fixtures.open_meteo_mock import _fake_fetch_hourly_archive_chunk
    from data import open_meteo_solar_archive as _archive

    original = _archive._fetch_hourly_archive_chunk
    _archive._fetch_hourly_archive_chunk = _fake_fetch_hourly_archive_chunk
    try:
        _config_module.reinit_config()
    finally:
        _archive._fetch_hourly_archive_chunk = original


_reinit_config_offline()


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_config():
    """Stellt sicher, dass CONFIG nach Session-Start auf der Fixture-Config basiert."""
    _apply_default_test_config_env()
    _reinit_config_offline()



@pytest.fixture(autouse=True)
def _restore_default_test_config_after_test():
    """Reset fixture env before/after each test; reinit after (xdist-safe).

    Before: overwrite sidecar env left by the previous test's monkeypatch undo.
    After: env + reinit once monkeypatch has torn down (outer autouse teardown).
    """
    _apply_default_test_config_env()
    yield
    _apply_default_test_config_env()
    _reinit_config_offline()


@pytest.fixture(autouse=True)
def _isolated_runtime_dir(tmp_path_factory):
    """Give every test its own runtime dir and drop process-wide runtime caches.

    Without it all tests of a worker (and all xdist workers) share the default runtime
    path: the push inbox, the publish ledger and the state files then leak between
    tests (intermittent failures that depend on the order). Tests that need a specific
    runtime dir still set ``EARNIE_RUNTIME_PATH`` themselves — that overrides this.
    Plain ``os.environ`` (no ``monkeypatch``) for the same teardown-order reason as above.
    """
    if os.getenv(_USE_LIVE_CONFIG_ENV) == "1":
        yield
        return
    from integrations import ehal_write
    from runtime_store import ehal_push_inbox

    previous = os.environ.get("EARNIE_RUNTIME_PATH")
    os.environ["EARNIE_RUNTIME_PATH"] = str(tmp_path_factory.mktemp("runtime"))
    ehal_push_inbox.reset_memory_for_tests()
    ehal_write.clear_published_for_tests()
    try:
        yield
    finally:
        ehal_push_inbox.reset_memory_for_tests()
        ehal_write.clear_published_for_tests()
        if previous is None:
            os.environ.pop("EARNIE_RUNTIME_PATH", None)
        else:
            os.environ["EARNIE_RUNTIME_PATH"] = previous


_OPENDATA_CACHE_ROOT = Path(tempfile.mkdtemp(prefix="earnie-opendata-test-"))
atexit.register(shutil.rmtree, _OPENDATA_CACHE_ROOT, ignore_errors=True)
_opendata_cache_ids = itertools.count()
# Module- and session-scoped fixtures run before the per-test dir below is set.
os.environ["EARNIE_ENERGY_CHARTS_CACHE_PATH"] = str(_OPENDATA_CACHE_ROOT / "process")


@pytest.fixture(autouse=True)
def _isolated_opendata_cache():
    """Every test gets its own (not yet created) Energy-Charts / EU archive cache dir.

    Tests serve fake payloads for settled days; in a shared dir one test would read another
    test's payload, and in the repo dir the app would read it as real data. Plain
    ``os.environ`` for the same teardown-order reason as ``_isolated_runtime_dir``.
    """
    previous = os.environ.get("EARNIE_ENERGY_CHARTS_CACHE_PATH")
    os.environ["EARNIE_ENERGY_CHARTS_CACHE_PATH"] = str(_OPENDATA_CACHE_ROOT / str(next(_opendata_cache_ids)))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("EARNIE_ENERGY_CHARTS_CACHE_PATH", None)
        else:
            os.environ["EARNIE_ENERGY_CHARTS_CACHE_PATH"] = previous


@pytest.fixture(autouse=True)
def _clear_thermal_year_caches():
    """Year-model memo is process-wide; a monkeypatched loader must not see old hits."""
    from optimizer.thermal_year_cache import clear_year_model_caches

    clear_year_model_caches()
    yield
    clear_year_model_caches()


@pytest.fixture(autouse=True)
def _clear_live_feature_failure_backoff():
    """The EU feature failure backoff is process-wide; one failing test must not skip the next."""
    from data import price_forecast_live

    price_forecast_live._feature_failure_until.clear()
    yield
    price_forecast_live._feature_failure_until.clear()


class NetworkBlockedError(AssertionError):
    """Raised when a test tries a real (non-loopback) HTTP request."""


@pytest.fixture(autouse=True)
def _block_real_http(request):
    """Fail fast on real HTTP: unmocked calls otherwise burn minutes in retry/sleep loops.

    Loopback hosts stay allowed (local test servers). Tests that really need the
    network must carry ``@pytest.mark.requires_loxone`` / ``requires_live_config``.
    """
    if (
        request.node.get_closest_marker("requires_loxone")
        or request.node.get_closest_marker("requires_live_config")
        or os.getenv(_USE_LIVE_CONFIG_ENV) == "1"
    ):
        yield
        return
    from urllib.parse import urlparse

    import requests.adapters

    original = requests.adapters.HTTPAdapter.send

    def _send(self, req, *args, **kwargs):
        host = urlparse(req.url).hostname or ""
        if host not in {"localhost", "127.0.0.1", "::1"} and not host.endswith(".localhost"):
            raise NetworkBlockedError(f"real HTTP request blocked in tests: {req.method} {req.url}")
        return original(self, req, *args, **kwargs)

    # No ``monkeypatch`` here: requesting it would tear it down after
    # ``_restore_default_test_config_after_test`` and break its reinit.
    requests.adapters.HTTPAdapter.send = _send
    try:
        yield
    finally:
        requests.adapters.HTTPAdapter.send = original


_EARNIE_SERVER_POST_MODULES = ("runtime_store.usage_ping", "runtime_store.feature_review")
_blocked_earnie_server_posts: list[str] = []


@pytest.fixture(scope="session", autouse=True)
def _block_earnie_server_posts():
    """Never POST to the production earnie-server (ping / review) from tests.

    ``post_json`` uses urllib, so ``_block_real_http`` does not see it; unmocked
    consent / points paths minted a fresh install id per test and counted as real
    installs. Session scope: a ping thread finishing after its test must still hit
    the stub. No marker opts out. Loopback test servers (``endpoint_url``) pass.
    """
    import importlib

    from runtime_store.server_endpoints import SERVER_BASE

    patched = []
    for name in _EARNIE_SERVER_POST_MODULES:
        module = importlib.import_module(name)
        original = module.post_json

        def _post_json(url, body, timeout, *, log_name, _original=original):
            if url.startswith(SERVER_BASE):
                _blocked_earnie_server_posts.append(f"{log_name}: POST {url}")
                raise NetworkBlockedError(f"earnie-server POST blocked in tests: {url}")
            return _original(url, body, timeout, log_name=log_name)

        module.post_json = _post_json
        patched.append((module, original))
    try:
        yield
    finally:
        for module, original in patched:
            module.post_json = original


@pytest.fixture(autouse=True)
def _fail_on_blocked_earnie_server_post():
    """Fail the test whose code tried to reach the production earnie-server."""
    from runtime_store import usage_ping

    _blocked_earnie_server_posts.clear()
    yield
    deadline = time.monotonic() + 2.0
    while usage_ping._send_in_flight and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.01)
    if _blocked_earnie_server_posts:
        hits = list(_blocked_earnie_server_posts)
        _blocked_earnie_server_posts.clear()
        pytest.fail("test tried to POST to the production earnie-server:\n" + "\n".join(hits))


def _loxone_integration_enabled() -> bool:
    if os.getenv("EARNIE_SKIP_LOXONE_INTEGRATION") == "1":
        return False
    if os.getenv(_USE_LIVE_CONFIG_ENV) != "1":
        return False
    if not (
        (ROOT / "config.json").is_file()
        or (ROOT / "earnie_env" / "config" / "config.json").is_file()
        or (ROOT / "config" / "config.json").is_file()
    ):
        return False
    _load_dotenv_for_tests()
    return all(
        str(os.getenv(key, "")).strip()
        for key in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS")
    )


requires_loxone = pytest.mark.skipif(
    not _loxone_integration_enabled(),
    reason=(
        "Loxone-Integration: EARNIE_TEST_USE_LIVE_CONFIG=1, .env mit "
        "LOXONE_IP/USER/PASS und config.json erforderlich "
        "(EARNIE_SKIP_LOXONE_INTEGRATION=1 zum Überspringen)"
    ),
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_loxone: Integrationstest gegen echten Loxone-Miniserver",
    )
    config.addinivalue_line(
        "markers",
        "slow: Längerer Backtesting- oder MILP-Integrationslauf",
    )
    config.addinivalue_line(
        "markers",
        "requires_live_config: bewusst NAS/Prod-config.json (EARNIE_TEST_USE_LIVE_CONFIG=1)",
    )
    config.addinivalue_line(
        "markers",
        "regression: Release golden-master suite (deselected by default)",
    )
    config.addinivalue_line(
        "markers",
        "e2e: Playwright-Smoketests gegen einen echten streamlit-Server (deselected by default)",
    )


def _marker_explicitly_selected(config, name: str, env_flag: str) -> bool:
    if os.environ.get(env_flag) == "1":
        return True
    markexpr = (getattr(config.option, "markexpr", None) or "").strip()
    if not markexpr:
        return False
    # Plain "-m <name>" (or expressions that require the marker).
    if f"not {name}" in markexpr:
        return False
    return name in markexpr


def _regression_explicitly_selected(config) -> bool:
    return _marker_explicitly_selected(config, "regression", "EARNIE_RUN_REGRESSION")


def _e2e_explicitly_selected(config) -> bool:
    return _marker_explicitly_selected(config, "e2e", "EARNIE_RUN_E2E")


def pytest_collection_modifyitems(config, items):
    """Deselect regression and e2e by default; keep ``slow`` tests at the end."""
    deselect_names = []
    if not _regression_explicitly_selected(config):
        deselect_names.append("regression")
    if not _e2e_explicitly_selected(config):
        deselect_names.append("e2e")
    if deselect_names:
        kept: list = []
        deselected: list = []
        for item in items:
            if any(item.get_closest_marker(name) is not None for name in deselect_names):
                deselected.append(item)
            else:
                kept.append(item)
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = kept
    items.sort(key=lambda item: item.get_closest_marker("slow") is not None)
