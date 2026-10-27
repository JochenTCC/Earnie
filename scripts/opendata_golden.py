"""Recorded HTTP responses and golden outputs of the weather / power-data access (Edibert P6 parity).

``record`` runs every public entry point of the Open-Meteo and Energy-Charts access once against
the real services with the clock frozen at :data:`FROZEN_NOW`, and writes each response
(``responses.json.gz``, keyed by URL and parameters) and each output (``expected.json``) to
``tests/fixtures/opendata/``. ``tests/test_opendata_parity.py`` replays the responses (no network)
and compares the outputs and the request list. Both run on an empty Energy-Charts cache dir of
their own, never on ``data/cache/energy_charts``.

    python -m scripts.opendata_golden record
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

FIXTURE_DIR = Path("tests/fixtures/opendata")
RESPONSES_FILE = "responses.json.gz"
EXPECTED_FILE = "expected.json"
VIENNA = ZoneInfo("Europe/Vienna")
# Recording moment; the forecast calls count their days from it.
FROZEN_NOW = datetime(2026, 10, 27, 18, 0, tzinfo=VIENNA)
# Archive window across the autumn clock change (2025-10-26).
WINDOW = (date(2025, 10, 24), date(2025, 10, 28))
# Crosses a month boundary (two Energy-Charts chunks).
MONTH_EDGE = (date(2025, 10, 30), date(2025, 11, 2))
SITE = {"lat": 47.5, "lon": 14.0}
SURFACES = ((30.0, 0.0), (90.0, -90.0))


def request_key(url: str, params: dict[str, Any] | None) -> str:
    items = sorted((str(k), str(v)) for k, v in (params or {}).items())
    return url + "?" + "&".join(f"{k}={v}" for k, v in items)


class RecordedResponse:
    """The part of ``requests.Response`` the access code uses."""

    def __init__(self, url: str, status_code: int, body: Any) -> None:
        self.url = url
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url: {self.url}", response=self)


def _frame_json(value: pd.DataFrame | pd.Series) -> Any:
    return json.loads(value.to_json(orient="split", date_format="iso", double_precision=15))


def output_json(value: Any) -> Any:
    """Outputs as JSON: frames and series in ``split`` orientation, bundles per field."""
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return _frame_json(value)
    if hasattr(value, "temperature_c") and hasattr(value, "tilted_wm2"):
        return {
            "temperature_c": _frame_json(value.temperature_c),
            "tilted_wm2": {
                f"{s.tilt_deg}/{s.azimuth_deg}": _frame_json(series)
                for s, series in sorted(value.tilted_wm2.items(), key=lambda kv: (kv[0].tilt_deg, kv[0].azimuth_deg))
            },
        }
    return value


def _surfaces():
    from data.open_meteo_solar_archive import TiltedSurface

    return [TiltedSurface(tilt, azimuth) for tilt, azimuth in SURFACES]


def cases() -> dict[str, Callable[[], Any]]:
    """Name → call of one public entry point (imports inside, so the replay patches apply)."""
    from data import eu_market_features as eu
    from data import open_meteo_solar_archive as archive
    from data import outdoor_forecast as outdoor

    start = FROZEN_NOW.replace(tzinfo=None, minute=0)
    today = FROZEN_NOW.date()
    return {
        "eu_power": lambda: eu.fetch_eu_power_hourly(*WINDOW),
        "country_power_month_edge": lambda: eu.fetch_country_power_hourly("at", *MONTH_EDGE),
        "at_day_ahead": lambda: eu.fetch_at_day_ahead_hourly(*WINDOW),
        "eu_weather_archive": lambda: eu.fetch_eu_weather_hourly(*WINDOW),
        "eu_weather_forecast": lambda: eu.fetch_eu_weather_forecast_hourly(today, date.fromordinal(today.toordinal() + 2)),
        "site_climate_bundle": lambda: archive.build_open_meteo_climate_bundle(
            WINDOW[0], WINDOW[1], timezone="Europe/Vienna", surfaces=_surfaces(), use_cache=False, **SITE
        ),
        "site_pv_kw": lambda: archive.fetch_hourly_pv_kw_series(
            WINDOW[0], WINDOW[1], tilt=30.0, azimuth=0.0, kwp=10.0, timezone="Europe/Vienna", **SITE
        ),
        "site_outdoor_forecast": lambda: outdoor.get_hourly_outdoor_forecast_c(
            horizon=48, latitude=SITE["lat"], longitude=SITE["lon"], start=start
        ),
        "site_tilted_forecast": lambda: outdoor.get_hourly_tilted_irradiance_forecast_wm2(
            horizon=48, tilt_deg=30.0, azimuth_deg=0.0, latitude=SITE["lat"], longitude=SITE["lon"], start=start
        ),
    }


def _clear_memory_caches() -> None:
    from data import open_meteo_solar_archive as archive
    from data import outdoor_forecast as outdoor

    outdoor._CACHE.clear()
    outdoor._TILTED_CACHE.clear()
    archive.clear_open_meteo_bundle_mem_cache()


@contextmanager
def frozen_access(get: Callable[..., Any], *, sleep: bool, cache_dir: Path) -> Iterator[None]:
    """Clock at :data:`FROZEN_NOW`, ``requests.get`` replaced, no shadow-feed writes.

    ``sleep=False`` (replay) skips the pauses and retry waits. ``cache_dir`` is the Energy-Charts /
    EU archive cache.
    """
    import time

    import time_machine

    with time_machine.travel(FROZEN_NOW, tick=False), patch("requests.get", get), patch(
        "runtime_store.shadow.transport.record_transport"
    ), patch("time.sleep", time.sleep if sleep else (lambda _s: None)), patch.dict(
        os.environ, {"EARNIE_ENERGY_CHARTS_CACHE_PATH": str(cache_dir)}
    ):
        _clear_memory_caches()
        yield


def run_cases(
    get: Callable[..., Any], *, cache_dir: Path, sleep: bool = False
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Outputs and the request keys per case, with ``get`` serving ``requests.get``."""
    requested: list[str] = []

    def _tracking_get(url, params=None, **kwargs):
        requested.append(request_key(url, params))
        return get(url, params=params, **kwargs)

    outputs: dict[str, Any] = {}
    calls: dict[str, list[str]] = {}
    with frozen_access(_tracking_get, sleep=sleep, cache_dir=cache_dir):
        for name, call in cases().items():
            requested.clear()
            outputs[name] = output_json(call())
            calls[name] = list(requested)
    return outputs, calls


def record() -> None:
    import requests

    real_get = requests.get
    responses: dict[str, dict[str, Any]] = {}

    last_status: dict[str, int] = {}

    def _recording_get(url, params=None, **kwargs):
        response = real_get(url, params=params, **kwargs)
        last_status[request_key(url, params)] = response.status_code
        if response.status_code != 200:
            # Retries (HTTP 429) are not part of the golden; the replay answers at once.
            return response
        responses[request_key(url, params)] = {
            "url": url,
            "status": response.status_code,
            "body": response.json(),
        }
        return response

    with tempfile.TemporaryDirectory(prefix="opendata-golden-") as cache_dir:
        outputs, calls = run_cases(_recording_get, sleep=True, cache_dir=Path(cache_dir))
    failed = sorted(key for key, status in last_status.items() if status != 200)
    if failed:
        raise RuntimeError(f"Anfragen ohne Erfolg (z. B. ein übersprungenes Land): {failed}; später erneut aufnehmen.")
    calls = {name: list(dict.fromkeys(keys)) for name, keys in calls.items()}
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURE_DIR / RESPONSES_FILE, "wt", encoding="utf-8") as fh:
        json.dump(responses, fh, separators=(",", ":"), sort_keys=True)
    with (FIXTURE_DIR / EXPECTED_FILE).open("w", encoding="utf-8", newline="\n") as fh:
        json.dump({"outputs": outputs, "requests": calls}, fh, separators=(",", ":"), sort_keys=True)
        fh.write("\n")
    print(f"{len(responses)} Antworten, {len(outputs)} Fälle: " + ", ".join(f"{k}={len(v)}" for k, v in calls.items()))


def load_responses() -> dict[str, dict[str, Any]]:
    with gzip.open(FIXTURE_DIR / RESPONSES_FILE, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def replay_get(responses: dict[str, dict[str, Any]]) -> Callable[..., RecordedResponse]:
    def _get(url, params=None, **_kwargs):
        key = request_key(url, params)
        if key not in responses:
            raise AssertionError(f"Nicht aufgezeichnete Anfrage: {key}")
        hit = responses[key]
        return RecordedResponse(hit["url"], hit["status"], hit["body"])

    return _get


def main() -> None:
    import config  # noqa: F401  (load before data.* to avoid the config ↔ optimizer import cycle)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("record",))
    parser.parse_args()
    record()


if __name__ == "__main__":
    main()
