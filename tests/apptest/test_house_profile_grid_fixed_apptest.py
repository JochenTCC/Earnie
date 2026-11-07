"""Hausprofil: was ein Netzbereich neben dem Arbeitspreis kostet, und was beim Speichern bleibt."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean, messages

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_PROFILE = "test_home"
_AREA_KEY = f"{_PROFILE}__house_profile_nne_area"


def _user_grid_path() -> Path:
    return Path(os.environ["EARNIE_GRID_FEES_PATH"]).with_name("user_grid_fees.json")


def test_catalog_area_caption_names_parts_and_fixed_amounts() -> None:
    shutil.copy("share/config/grid_fees.json", os.environ["EARNIE_GRID_FEES_PATH"])
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)

    at.selectbox(key=_AREA_KEY).set_value("AT-VBG").run(timeout=_TIMEOUT_S)

    assert_clean(at)
    captions = " ".join(messages(at)["caption"])
    assert "Netzverlust und Abgaben: **1,113" in captions
    assert "feste Beträge: **76,82 €/Jahr**" in captions


def test_own_area_shows_and_keeps_its_fixed_amount() -> None:
    path = _user_grid_path()
    doc = json.loads(path.read_text(encoding="utf-8"))
    own = next(area for area in doc["areas"] if area["id"] == f"user_{_PROFILE}")
    own["fixed_eur_year"] = [{"id": "grid_base_fee", "label": "Grundgebühr", "eur_year": 36.0}]
    path.write_text(json.dumps(doc), encoding="utf-8")

    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert any(
        "bleibt erhalten" in text and "36,00 €/Jahr" in text for text in messages(at)["caption"]
    )

    # Changing the region saves the profile, and with it the own area
    at.selectbox(key=f"{_PROFILE}__house_profile_region_AT").set_value("9").run(timeout=_TIMEOUT_S)

    assert_clean(at)
    stored = json.loads(path.read_text(encoding="utf-8"))
    own = next(area for area in stored["areas"] if area["id"] == f"user_{_PROFILE}")
    assert own["label"].startswith("Eigener Arbeitspreis")
    assert own["fixed_eur_year"][0]["eur_year"] == 36.0
