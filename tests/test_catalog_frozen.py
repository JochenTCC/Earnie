"""The public catalog is a frozen seed (Edibert P8, D1 and D4).

``share/config/tariffs.json`` and ``share/config/grid_fees.json`` get corrections and the
monthly rows of the reference curves, but no new entries: new tariffs and grid areas reach
users only through Edibert's catalog channel (``docs/dev/edibert-integration.md`` § P8).
Removing an entry (an ended product) is allowed; adding one is not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SHARE = Path(__file__).resolve().parents[1] / "share" / "config"

FROZEN_IMPORT_IDS = frozenset(
    {
        "at_tiwag_flex_privat",
        "at_aae_naturstrom_naturstrom_spot_stunde_ii",
        "at_pullstrom_pullstrom_ora",
        "at_smartenergy_smartcontrol",
        "at_oekostrom_oeko_spot",
        "at_spotty_smart_active",
        "at_energie_steiermark_e1_floater",
        "at_elektrizitaetswerk_perg_heimatstrom_spot",
        "at_hofer_gruenstrom_hofer_gruenstrom_spot",
        "at_verbund_v_strom_spot",
        "at_wuesterstrom_wuesterstrom_spot",
        "at_kittel_muehle_aquavento_flex_smart",
        "at_wien_energie_optima_voll_aktiv",
        "at_avia_energy_avia_strom_plus_stundenfloater",
        "awattar_at",
        "at_energie_ag_oberoesterreich_oekostrom_spot",
        "at_wels_strom_privat_strom_spot",
        "at_stadtwerke_klagenfurt_ekg_strom_flex",
        "at_schlau_pv_gmbh_spot",
        "at_energie_steiermark_first_energy_steirerstrom_spot",
        "de_tibber_tibber_dynamic",
        "de_eprimo_eprimo_smart",
        "de_awattar_de_hourly_de",
        "ch_ekz_elektrizitaetswerke_des_kantons_zuerich_dynamischer_tarif",
        "ch_groupe_e_vario",
        "at_verbund_v_strom_sterreich",
        "at_wien_energie_optima_entspannt_plus",
        "at_smartenergy_smarttimes",
        "at_tiwag_tiwag_komfort_strom",
        "at_energie_steiermark_steirerstrom_fix",
        "at_energie_ag_ober_sterreich_kostrom_garant_12",
        "de_eprimo_eprimostrom_primaklima_pur",
        "ch_ekz_elektrizit_tswerke_des_kantons_z_rich_ekz_mix_standard",
        "at_vkw_strom_dynamisch",
        "at_vkw_strom_duo",
        "at_vkw_strom_duo_normalpreis",
        "at_vkw_strom_einfach",
    }
)
FROZEN_EXPORT_IDS = frozenset(
    {
        "dynamic_epex",
        "at_smartenergy_smartsun_spot",
        "at_oemag_gesetzlicher_marktpreis",
        "at_energie_ag_ober_sterreich_team_sonne_float",
        "at_evn_evn_sonnenstrom_garant_float",
        "at_wien_energie_optima_sonnenstrom_float",
        "at_verbund_v_strom_sonneneinspeisung_fix",
        "at_tiwag_tiwag_einspeisung_fix",
        "de_tibber_tibber_einspeisung_monats_marktwert",
        "ch_ekz_elektrizitaetswerke_des_kantons_zuerich_ekz_ruecklieferung_fix",
        "monthly_sunny_web_recherche",
        "at_vkw_pv_dynamisch",
        "at_vkw_pv_flex",
    }
)
FROZEN_GRID_AREA_IDS = frozenset(
    {
        "AT-BGLD",
        "AT-KTN",
        "AT-KLGF",
        "AT-NOE",
        "AT-OOE",
        "AT-LINZ",
        "AT-SBG",
        "AT-STMK",
        "AT-GRAZ",
        "AT-TIROL",
        "AT-IBK",
        "AT-VBG",
        "AT-WIEN",
        "AT-KLWT",
    }
)
FROZEN_GRID_RULE_SET_IDS = frozenset(
    {
        "AT_NE7",
    }
)

_HINT = (
    "The public catalog is a frozen seed (Edibert P8): new entries go through Edibert's "
    "catalog channel, not into share/config/."
)


def _read(name: str) -> dict:
    return json.loads((SHARE / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "list_key,frozen",
    [("import_tariffs", FROZEN_IMPORT_IDS), ("export_tariffs", FROZEN_EXPORT_IDS)],
)
def test_tariff_catalog_gets_no_new_tariffs(list_key, frozen):
    ids = {str(tariff["id"]) for tariff in _read("tariffs.json")[list_key]}
    assert not ids - frozen, f"{list_key}: new {sorted(ids - frozen)}. {_HINT}"


def test_grid_fee_catalog_gets_no_new_areas_or_rule_sets():
    doc = _read("grid_fees.json")
    areas = {str(area["id"]) for area in doc["areas"]}
    rule_sets = set(doc["rule_sets"])
    assert not areas - FROZEN_GRID_AREA_IDS, f"areas: new {sorted(areas - FROZEN_GRID_AREA_IDS)}. {_HINT}"
    assert not rule_sets - FROZEN_GRID_RULE_SET_IDS, (
        f"rule_sets: new {sorted(rule_sets - FROZEN_GRID_RULE_SET_IDS)}. {_HINT}"
    )
