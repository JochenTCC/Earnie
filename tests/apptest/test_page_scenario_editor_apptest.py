"""AppTest-Smoketests für den Szenarienkonfigurator (echtes Rendering, headless)."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_scenario_selects_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🧪 Szenarienkonfigurator"
    labels = {sb.label for sb in at.selectbox}
    assert "Hausprofil" in labels
    assert "Bezugstarif" in labels
    assert "Einspeisetarif" in labels


def test_switch_import_tariff_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    tarif_select = next(sb for sb in at.selectbox if sb.label == "Bezugstarif")
    options = tarif_select.options
    other_option = next((o for o in options if o != tarif_select.value), None)
    if other_option is None:
        return
    tarif_select.set_value(other_option).run()
    assert not at.exception


def test_user_tariffs_appear_in_selection():
    """Edibert P1: user_tariffs.json next to tariffs.json shows up in the tariff selects."""
    import json
    import os

    user_file = Path(os.environ["EARNIE_TARIFFS_PATH"]).parent / "user_tariffs.json"
    user_file.write_text(
        json.dumps(
            {
                "tariff_format": 1,
                "import_tariffs": [
                    {
                        "id": "user_my_fixed", "label": "Mein Fixtarif", "type": "fixed_cent",
                        "land": "AT", "supplier_id": "user_me", "fix_cent_kwh": 24.5, "vat_percent": 20,
                    },
                    {
                        "id": "user_day_night", "label": "Tag/Nacht", "type": "fixed_cent",
                        "land": "AT", "supplier_id": "user_me", "fix_cent_kwh": 30.0, "vat_percent": 20,
                        "rules": [{
                            "id": "night", "time": {"from": "22:00", "to": "06:00"},
                            "effect": {"mode": "absolute_cent", "value": 22.0},
                        }],
                    },
                ],
                "export_tariffs": [],
            }
        ),
        encoding="utf-8",
    )
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception
    options = next(sb for sb in at.selectbox if sb.label == "Bezugstarif").options
    assert "Mein Fixtarif · Benutzertarif" in options
    assert "Tag/Nacht · Benutzertarif" in options  # Edibert prices rules since P3b
