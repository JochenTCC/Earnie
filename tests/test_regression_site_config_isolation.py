"""The regression runner never loads the local site config (``earnie_env/config``)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.fixtures.backtesting_fixtures import FIXTURE_CONFIG_ENV, FIXTURES_ROOT

ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import json, os
import scripts.run_regression  # noqa: F401
import config  # loads the bound config at import time
print(json.dumps({key: os.environ.get(key) for key in %r}))
"""


def test_runner_binds_fixtures_even_with_a_broken_site_config(tmp_path):
    site = tmp_path / "site"
    (site / "config").mkdir(parents=True)
    (site / "config" / "config.json").write_text("{not json", encoding="utf-8")
    (site / "config" / "house_profiles.json").write_text("{not json", encoding="utf-8")
    keys = [*FIXTURE_CONFIG_ENV, "EARNIE_ENV_PATH", "EARNIE_DEVIATION_RULES_PATH"]
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "EARNIE_ENV_PATH": str(site),
        "EARNIE_CONFIG_PATH": str(site / "config"),
        "EARNIE_HOUSE_PROFILES_PATH": str(site / "config" / "house_profiles.json"),
        "EARNIE_DEVIATION_RULES_PATH": str(site / "config" / "deviation_rules.json"),
    }
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE % (keys,)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    bound = json.loads(proc.stdout.strip().splitlines()[-1])
    for key, name in FIXTURE_CONFIG_ENV.items():
        assert bound[key] == str(FIXTURES_ROOT / name)
    assert bound["EARNIE_ENV_PATH"] is None
    assert bound["EARNIE_DEVIATION_RULES_PATH"] is None
