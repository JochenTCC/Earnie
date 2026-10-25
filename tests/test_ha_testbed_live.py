r"""Live HA testbed check as pytest (HA Testbed P4); skipped unless a bench is running.

  $env:HA_TESTBED_TOKEN = '<HA long-lived token>'
  .venv\Scripts\python.exe -m scripts.run_pytest tests/test_ha_testbed_live.py -m ha_container -n 0

Optional env: HA_TESTBED_DIR, HA_TESTBED_NAME, HA_TESTBED_CONFIG_DIR, HA_TESTBED_HA_URL,
HA_TESTBED_EARNIE_URL.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

from scripts import ha_testbed_check as chk

pytestmark = [
    pytest.mark.ha_container,
    pytest.mark.skipif(not os.getenv("HA_TESTBED_TOKEN"), reason="needs a running HA testbed (HA_TESTBED_TOKEN)"),
]


def _unreachable(url: str) -> str | None:
    """Return the failure text when ``url`` does not answer at all (HTTP errors count as reachable)."""
    try:
        urllib.request.urlopen(url, timeout=3)  # noqa: S310
    except urllib.error.HTTPError:
        return None
    except OSError as exc:
        return f"{url}: {exc}"
    return None


def test_testbed_check_passes(capsys):
    for url in (
        os.getenv("HA_TESTBED_HA_URL", "http://127.0.0.1:8123"),
        os.getenv("HA_TESTBED_EARNIE_URL", "http://127.0.0.1:8541"),
    ):
        reason = _unreachable(url)
        if reason:
            pytest.skip(f"HA testbed not reachable ({reason})")
    argv = ["--require-all"]
    for flag, env in (
        ("--testbed-dir", "HA_TESTBED_DIR"),
        ("--name", "HA_TESTBED_NAME"),
        ("--config-dir", "HA_TESTBED_CONFIG_DIR"),
        ("--ha-url", "HA_TESTBED_HA_URL"),
        ("--earnie-url", "HA_TESTBED_EARNIE_URL"),
    ):
        if os.getenv(env):
            argv += [flag, os.environ[env]]
    code = chk.main(argv)
    out = capsys.readouterr().out
    assert code == 0, out
