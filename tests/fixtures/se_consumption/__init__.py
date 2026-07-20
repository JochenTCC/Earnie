"""Load SE consumption mini-profiles (normalized like house_profiles.json)."""
from __future__ import annotations

import json
from pathlib import Path

from house_config.profiles_store import normalize_house_profiles_document

FIXTURE_DIR = Path(__file__).resolve().parent

PROFILE_IDS = (
    "ev_power_capped",
    "ev_power_ok",
    "thermal_overnight",
    "thermal_pulse_tight",
    "known_plus_manual",
    "greenfield_like",
    "mixed_csv_thermal",
)


def load_se_consumption_profile(profile_id: str) -> dict:
    """Return one normalized house profile from ``tests/fixtures/se_consumption``."""
    path = FIXTURE_DIR / f"{profile_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"SE consumption fixture missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    doc = normalize_house_profiles_document({"profiles": [raw]})
    profiles = doc["profiles"]
    if profile_id not in profiles:
        raise KeyError(f"Fixture id mismatch: expected {profile_id!r} in {path.name}")
    return profiles[profile_id]
