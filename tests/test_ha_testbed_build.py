"""HA Testbed P2: external archetype roots (S4 core) and ``scripts.ha_testbed_build``."""
from __future__ import annotations

import json
import re

import pytest

from house_sim.archetype import FIXTURES_DIR, load_archetype
from house_sim.core.archetype import list_archetypes, load_archetype_from_roots
from scripts import ha_testbed_build as build
from test_house_sim_archetype_gen import _full_pack, _minimal_pack

SHIPPED = ("evcc_en", "fronius_de", "huawei_en", "sma_keba")


def _write_pack(tmp_path, pack):
    house, components = pack
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "house_profiles.json").write_text(json.dumps(house), encoding="utf-8")
    (cfg / "components.json").write_text(json.dumps(components), encoding="utf-8")
    return cfg


def _args(cfg, out, **extra):
    argv = ["--config-dir", str(cfg), "--out", str(out), "--earnie-host", "host.docker.internal", "--token", "tok-123"]
    for key, value in extra.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return argv


# --- core: external archetype root ------------------------------------------


def test_list_archetypes_merges_shipped_and_external(tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / ".hidden").mkdir()
    roots = list_archetypes(FIXTURES_DIR, tmp_path)
    assert set(SHIPPED) <= set(roots)
    assert roots["mine"] == tmp_path
    assert ".hidden" not in roots
    assert roots["evcc_en"] == FIXTURES_DIR


def test_list_archetypes_ignores_missing_external_dir(tmp_path):
    assert set(list_archetypes(FIXTURES_DIR, tmp_path / "nope")) == set(list_archetypes(FIXTURES_DIR))


def test_name_collision_is_an_error(tmp_path):
    (tmp_path / "evcc_en").mkdir()
    with pytest.raises(ValueError, match="evcc_en"):
        list_archetypes(FIXTURES_DIR, tmp_path)
    with pytest.raises(ValueError, match="evcc_en"):
        load_archetype_from_roots("evcc_en", fixtures_dir=FIXTURES_DIR, external_dir=tmp_path)


def test_load_from_roots_finds_both_and_rejects_unknown(tmp_path):
    cfg = _write_pack(tmp_path, _minimal_pack())
    assert build.main(_args(cfg, tmp_path / "ha", name="gen_pack")) == 0
    external = tmp_path / "ha" / "earnie_house_sim" / "archetypes"
    assert load_archetype_from_roots("gen_pack", fixtures_dir=FIXTURES_DIR, external_dir=external).name == "gen_pack"
    assert load_archetype_from_roots("evcc_en", fixtures_dir=FIXTURES_DIR, external_dir=external).name == "evcc_en"
    with pytest.raises(FileNotFoundError, match="nope"):
        load_archetype_from_roots("nope", fixtures_dir=FIXTURES_DIR, external_dir=external)


# --- build ------------------------------------------------------------------


@pytest.mark.parametrize("pack", [_minimal_pack, _full_pack], ids=["minimal", "full"])
def test_build_writes_filled_package_archetype_and_snippet(tmp_path, pack, capsys):
    cfg = _write_pack(tmp_path, pack())
    out = tmp_path / "ha"
    assert build.main(_args(cfg, out)) == 0
    capsys.readouterr()

    carrier = (out / "packages" / "earnie_ha_carrier.yaml").read_text(encoding="utf-8")
    assert not re.search(r"ENTITY_\w+", carrier)
    assert "http://host.docker.internal:8541" in carrier and "tok-123" in carrier
    arch_dir = out / "earnie_house_sim" / "archetypes" / "earnie_pack"
    placeholders = json.loads((arch_dir / "placeholders.json").read_text(encoding="utf-8"))
    assert placeholders and all(eid in carrier for eid in placeholders.values())
    assert load_archetype("earnie_pack", fixtures_dir=arch_dir.parent).entities
    snippet = (out / build.SNIPPET_NAME).read_text(encoding="utf-8")
    assert "packages: !include_dir_named packages" in snippet
    assert not (out / "configuration.yaml").exists()


def test_build_is_idempotent(tmp_path):
    cfg = _write_pack(tmp_path, _full_pack())
    out = tmp_path / "ha"
    assert build.main(_args(cfg, out)) == 0
    first = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert build.main(_args(cfg, out)) == 0
    assert first == {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}


def test_build_fails_when_a_placeholder_survives(tmp_path, monkeypatch):
    house, components = _minimal_pack()
    real = build.fill_yaml_placeholders
    monkeypatch.setattr(
        build,
        "fill_yaml_placeholders",
        lambda text, mapping: real(text, dict(list(mapping.items())[1:])),
    )
    with pytest.raises(ValueError, match="unfilled placeholders"):
        build.build_testbed(
            house, components, out_dir=tmp_path / "ha", earnie_host="h", earnie_port=8541, token="t"
        )
    assert not (tmp_path / "ha").exists()


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"name": "evcc_en"}, "shipped archetype"),
        ({"name": "Bad-Name"}, "must match"),
        ({"token": "PUSH_TOKEN_HIER_ERSETZEN"}, "token"),
    ],
)
def test_build_rejects_bad_inputs(tmp_path, capsys, extra, message):
    cfg = _write_pack(tmp_path, _minimal_pack())
    argv = _args(cfg, tmp_path / "ha")
    for key, value in extra.items():
        if key in ("token",):
            argv[argv.index("--token") + 1] = value
        else:
            argv += [f"--{key}", value]
    assert build.main(argv) == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / "ha").exists()


def test_build_passes_archetype_errors_through(tmp_path, capsys):
    house, components = _minimal_pack()
    del components["batteries"][0]["battery_capacity_kwh"]
    cfg = _write_pack(tmp_path, (house, components))
    assert build.main(_args(cfg, tmp_path / "ha")) == 2
    assert "battery_capacity_kwh" in capsys.readouterr().err
    assert build.main(_args(cfg, tmp_path / "ha", battery_kwh=9)) == 0
