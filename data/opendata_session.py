"""Earnie's sessions for the ``opendata`` package (Edibert P6).

The package has no Earnie imports; this module hands it the global timeout, the pause between
Energy-Charts requests and the disk cache for settled archive days.
"""
from __future__ import annotations

from pathlib import Path

import config
from opendata import Session
from opendata.energy_charts import HOST as ENERGY_CHARTS_HOST
from opendata.http import Transport, requests_transport
from runtime_store.env_vars import read_env

# Energy-Charts answers HTTP 429 when asked many times in a row.
ENERGY_CHARTS_PAUSE_S = 0.75
# Energy-Charts power and price, and the Open-Meteo archive of the EU weather grid.
OPENDATA_CACHE_DIR = Path("data/cache/energy_charts")


def cache_dir() -> Path:
    """``EARNIE_ENERGY_CHARTS_CACHE_PATH`` if set, else ``OPENDATA_CACHE_DIR``."""
    override = read_env("ENERGY_CHARTS_CACHE_PATH")
    return Path(override) if override else OPENDATA_CACHE_DIR


def session(*, transport: Transport = requests_transport) -> Session:
    return Session(
        timeout_s=float(config.get_global_timeout()),
        transport=transport,
        pause_after_s={ENERGY_CHARTS_HOST: ENERGY_CHARTS_PAUSE_S},
        cache_dir=cache_dir(),
    )
