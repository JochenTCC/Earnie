"""Edibert P1: tariff files load through ``edibert.api`` (prices since P3b via Edibert too)."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from house_config.edibert_tariffs import (
    EdibertLoadError,
    collect_edibert_load_errors,
    holiday_regions,
    load_grid_fees,
    load_tariff_set,
    pricing_context_for_profile,
    region_label,
)
from house_config.tariffs_store import (
    ORIGIN_KEY,
    load_tariffs_document,
    normalize_tariffs_document,
    tariff_display_label,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "share" / "config" / "tariffs.json"
GRID_FEES = REPO_ROOT / "share" / "config" / "grid_fees.json"


def _catalog_ids(section: str) -> list[str]:
    doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    return [item["id"] for item in doc[section]]


def _grid_area_ids() -> list[str]:
    doc = json.loads(GRID_FEES.read_text(encoding="utf-8"))
    areas = doc["areas"]
    return list(areas) if isinstance(areas, dict) else [a["id"] for a in areas]


USER_FIXED = {
    "id": "user_my_fixed",
    "label": "Mein Fixtarif",
    "type": "fixed_cent",
    "land": "AT",
    "supplier_id": "user_my_supplier",
    "fix_cent_kwh": 24.5,
    "prices_include_vat": True,
    "vat_percent": 20,
    "source": "Preisblatt 2026",
    "last_verified": "2026-10-01",
}
USER_DAY_NIGHT = {
    "id": "user_day_night",
    "label": "Tag/Nacht",
    "type": "fixed_cent",
    "land": "AT",
    "supplier_id": "user_my_supplier",
    "fix_cent_kwh": 30.0,
    "prices_include_vat": True,
    "vat_percent": 20,
    "rules": [
        {
            "id": "night",
            "label": "Nacht",
            "time": {"from": "22:00", "to": "06:00"},
            "effect": {"mode": "absolute_cent", "value": 22.0},
        }
    ],
}
USER_EXPORT = {
    "id": "user_my_feed_in",
    "label": "Meine Einspeisung",
    "type": "fixed",
    "land": "AT",
    "supplier_id": "user_my_supplier",
    "k_push_cent": 7.5,
    "vat_percent": 0,
}


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    shutil.copy(CATALOG, tmp_path / "tariffs.json")
    return tmp_path


def _write_user(directory: Path, imports: list[dict], exports: list[dict] | None = None) -> Path:
    path = directory / "user_tariffs.json"
    path.write_text(
        json.dumps({"tariff_format": 1, "import_tariffs": imports, "export_tariffs": exports or []}),
        encoding="utf-8",
    )
    return path


# --- Done clause: catalog and grid areas load through Edibert --------------------------


def test_catalog_counts_through_edibert() -> None:
    tariffs = load_tariff_set(str(CATALOG))
    assert (len(tariffs.imports), len(tariffs.exports)) == (37, 13)
    assert len(load_grid_fees(str(GRID_FEES)).areas) == 14


@pytest.mark.parametrize("tariff_id", _catalog_ids("import_tariffs"))
def test_catalog_import_tariff_loads_through_edibert(tariff_id: str) -> None:
    tariffs = load_tariff_set(str(CATALOG))
    assert tariffs.origin[("import", tariff_id)] == "catalog"


@pytest.mark.parametrize("tariff_id", _catalog_ids("export_tariffs"))
def test_catalog_export_tariff_loads_through_edibert(tariff_id: str) -> None:
    tariffs = load_tariff_set(str(CATALOG))
    assert tariffs.origin[("export", tariff_id)] == "catalog"


@pytest.mark.parametrize("area_id", _grid_area_ids())
def test_grid_area_loads_through_edibert(area_id: str) -> None:
    assert area_id in load_grid_fees(str(GRID_FEES)).areas


def test_edibert_and_earnie_see_the_same_catalog_ids() -> None:
    edibert = load_tariff_set(str(CATALOG))
    earnie = load_tariffs_document(str(CATALOG))
    assert set(edibert.imports) == set(earnie["import_tariffs"])
    assert set(edibert.exports) == set(earnie["export_tariffs"])


# --- user_tariffs.json in Earnie's read path ----------------------------------------------


def test_without_user_file_document_is_catalog_only(catalog_dir: Path) -> None:
    raw = json.loads((catalog_dir / "tariffs.json").read_text(encoding="utf-8"))
    assert load_tariffs_document(str(catalog_dir / "tariffs.json")) == normalize_tariffs_document(raw)


def test_user_tariffs_are_merged_with_origin(catalog_dir: Path) -> None:
    _write_user(catalog_dir, [USER_FIXED, USER_DAY_NIGHT], [USER_EXPORT])
    doc = load_tariffs_document(str(catalog_dir / "tariffs.json"))
    assert doc["import_tariffs"]["user_my_fixed"][ORIGIN_KEY] == "user"
    assert doc["import_tariffs"]["user_my_fixed"]["fix_cent_kwh"] == 24.5
    assert doc["export_tariffs"]["user_my_feed_in"]["k_push_cent"] == 7.5
    # catalog entries keep their exact shape (no origin key)
    assert all(ORIGIN_KEY not in t for i, t in doc["import_tariffs"].items() if not i.startswith("user_"))


def test_rule_user_tariff_is_listed_like_any_user_tariff(catalog_dir: Path) -> None:
    """Since P3b Edibert prices rules too: no 'erst ab Engine-Umstellung' marker any more."""
    _write_user(catalog_dir, [USER_DAY_NIGHT])
    doc = load_tariffs_document(str(catalog_dir / "tariffs.json"))
    tariff = doc["import_tariffs"]["user_day_night"]
    assert tariff_display_label(tariff).endswith("· Benutzertarif")


def test_display_labels() -> None:
    assert tariff_display_label({"id": "x", "label": "Katalog"}) == "Katalog"
    assert tariff_display_label({"id": "u", "label": "Mein", ORIGIN_KEY: "user"}) == "Mein · Benutzertarif"


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ({**USER_FIXED, "id": "my_fixed"}, "ID_PREFIX_MISSING"),
        ({**USER_FIXED, "tarif_typo": 1}, "TARIFF_UNKNOWN_FIELD"),
    ],
)
def test_bad_user_file_fails_loud(catalog_dir: Path, entry: dict, code: str) -> None:
    _write_user(catalog_dir, [entry])
    with pytest.raises(EdibertLoadError) as info:
        load_tariffs_document(str(catalog_dir / "tariffs.json"))
    assert info.value.code == code
    assert "user_tariffs.json" in str(info.value)


def test_duplicate_user_tariff_fails_loud(catalog_dir: Path) -> None:
    _write_user(catalog_dir, [USER_FIXED, USER_FIXED])
    with pytest.raises(EdibertLoadError) as info:
        load_tariffs_document(str(catalog_dir / "tariffs.json"))
    assert info.value.code == "ID_COLLISION"


def test_user_tariff_without_land_fails_loud(catalog_dir: Path) -> None:
    entry = {k: v for k, v in USER_FIXED.items() if k != "land"}
    _write_user(catalog_dir, [entry])
    with pytest.raises(ValueError, match="user_tariffs.json.*land fehlt"):
        load_tariffs_document(str(catalog_dir / "tariffs.json"))


# --- Plausibility, readiness ---------------------------------------------------------------


def _scenarios(path: Path, import_id: str, export_id: str = "") -> Path:
    path.write_text(
        json.dumps(
            {
                "earnie_data_model": 5,
                "scenarios": [
                    {"id": "s1", "settings": {"import_tariff_id": import_id, "export_tariff_id": export_id}}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_plausibility_accepts_scenarios_on_user_tariffs(catalog_dir: Path) -> None:
    """Since P3b a user tariff with rules is priceable: no plausibility error."""
    from house_config.tariff_plausibility import collect_tariff_plausibility_errors

    _write_user(catalog_dir, [USER_FIXED, USER_DAY_NIGHT])
    errors = collect_tariff_plausibility_errors(
        tariffs_path=str(catalog_dir / "tariffs.json"),
        scenarios_path=str(_scenarios(catalog_dir / "scen.json", "user_day_night")),
    )
    assert errors == []
    ok = collect_tariff_plausibility_errors(
        tariffs_path=str(catalog_dir / "tariffs.json"),
        scenarios_path=str(_scenarios(catalog_dir / "scen.json", "user_my_fixed")),
        with_edibert=True,
        grid_fees_path=str(GRID_FEES),
    )
    assert ok == []


def test_readiness_accepts_user_tariff_ids(catalog_dir: Path) -> None:
    from ui.setup_readiness import _missing_live_tariff_items

    _write_user(catalog_dir, [USER_FIXED], [USER_EXPORT])
    missing = _missing_live_tariff_items(
        {"import_tariff_id": "user_my_fixed", "export_tariff_id": "user_my_feed_in"},
        str(catalog_dir / "tariffs.json"),
    )
    assert missing == []


# --- House profile region and pricing context ---------------------------------------------


def test_pricing_context_with_region() -> None:
    ctx = pricing_context_for_profile("p", {"land": "AT", "region": "9"})
    assert (ctx.land, ctx.region, ctx.timezone) == ("AT", "9", "Europe/Vienna")


def test_unknown_region_is_coded_error() -> None:
    with pytest.raises(EdibertLoadError) as info:
        pricing_context_for_profile("p", {"land": "AT", "region": "XX"})
    assert info.value.code == "HOLIDAY_REGION_UNKNOWN"
    errors = collect_edibert_load_errors(
        tariffs_path=str(CATALOG), profiles={"p": {"land": "AT", "region": "XX"}}
    )
    assert len(errors) == 1 and "Hausprofil 'p'" in errors[0]


def test_holiday_regions_and_labels() -> None:
    assert holiday_regions("AT") == [str(n) for n in range(1, 10)]
    assert "BY" in holiday_regions("DE") and "ZH" in holiday_regions("CH")
    assert region_label("AT", "8") == "8 – Vorarlberg"
    assert region_label("DE", "BY") == "BY"


def _profile(**extra) -> dict:
    return {
        "id": "h", "label": "Haus", "land": "AT", "latitude": 47.4, "longitude": 9.7,
        "netznutzung": {"area_id": "AT-VBG"}, "consumers": [], **extra,
    }


def test_profile_region_is_optional_and_round_trips() -> None:
    from house_config.profiles_store import _serialize_profile, normalize_house_profiles_document

    without = normalize_house_profiles_document({"profiles": [_profile()]})["profiles"]["h"]
    assert "region" not in without
    assert "region" not in _serialize_profile(without)
    with_region = normalize_house_profiles_document({"profiles": [_profile(region="8")]})["profiles"]["h"]
    assert with_region["region"] == "8"
    assert _serialize_profile(with_region)["region"] == "8"


def test_profile_unknown_region_rejected() -> None:
    from house_config.profiles_store import normalize_house_profiles_document

    with pytest.raises(ValueError, match="region 'BY' ist für Land AT unbekannt"):
        normalize_house_profiles_document({"profiles": [_profile(region="BY")]})


def test_house_profiles_schema_accepts_region() -> None:
    import jsonschema

    schema = json.loads((REPO_ROOT / "share" / "config" / "house_profiles.schema.json").read_text(encoding="utf-8"))
    example = json.loads((REPO_ROOT / "share" / "config" / "house_profiles.example.json").read_text(encoding="utf-8"))
    example["profiles"][0]["region"] = "9"
    jsonschema.validate(example, schema)


# --- Persistence: tariff track, config pack --------------------------------------------


def test_user_tariffs_path_is_next_to_tariffs(monkeypatch, tmp_path: Path) -> None:
    from runtime_store.persist_paths import resolve_user_tariffs_json_path

    monkeypatch.setenv("EARNIE_TARIFFS_PATH", str(tmp_path / "x" / "tariffs.json"))
    assert Path(resolve_user_tariffs_json_path()) == tmp_path / "x" / "user_tariffs.json"


def test_write_json_dict_never_stamps_user_tariffs(tmp_path: Path) -> None:
    from settings.json_io import write_json_dict

    path = tmp_path / "user_tariffs.json"
    write_json_dict(str(path), {"tariff_format": 1, "import_tariffs": [], "export_tariffs": []})
    assert "earnie_data_model" not in json.loads(path.read_text(encoding="utf-8"))


def test_config_pack_carries_user_tariffs_unstamped(monkeypatch, tmp_path: Path) -> None:
    from runtime_store.config_pack import build_config_pack_bytes, import_config_pack_bytes

    for key in (
        "EARNIE_ENV_PATH", "EARNIE_RUNTIME_PATH", "EARNIE_TARIFFS_PATH", "EARNIE_GRID_FEES_PATH",
        "EARNIE_HOUSE_PROFILES_PATH", "EARNIE_BACKTESTING_SCENARIOS_PATH", "EARNIE_COMPONENTS_PATH",
        "EARNIE_DEVIATION_RULES_PATH",
    ):  # fmt: skip
        monkeypatch.delenv(key, raising=False)
    # Default sidecar paths are relative to the cwd (earnie_env/config): keep them in tmp_path,
    # never on the developer's real site config.
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(src))
    (src / "config.json").write_text(json.dumps({"earnie_data_model": 5}), encoding="utf-8")
    # user_tariffs.json follows tariffs.json, so the config dir has both (as every install does).
    shutil.copy(CATALOG, src / "tariffs.json")
    user_doc = {"tariff_format": 1, "import_tariffs": [USER_FIXED], "export_tariffs": []}
    (src / "user_tariffs.json").write_text(json.dumps(user_doc), encoding="utf-8")

    payload = build_config_pack_bytes()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert json.loads(archive.read("user_tariffs.json")) == user_doc

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "config.json").write_text("{}", encoding="utf-8")
    shutil.copy(CATALOG, dest / "tariffs.json")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(dest))
    written = import_config_pack_bytes(payload)
    assert "user_tariffs.json" in written
    assert json.loads((dest / "user_tariffs.json").read_text(encoding="utf-8")) == user_doc
