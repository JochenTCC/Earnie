"""SE matrix write_json allowlist (Sonar S2083 / S8707)."""
from __future__ import annotations

from pathlib import Path

import pytest


def _bind(tmp_path: Path, monkeypatch):
    import scripts.se_calc_test_common as se

    cells = tmp_path / "cells"
    cells.mkdir()
    desc = tmp_path / "matrix_descriptors.json"
    results = tmp_path / "se-calc-test-results.json"
    monkeypatch.setattr(se, "CELLS_DIR", cells)
    monkeypatch.setattr(se, "DESCRIPTORS_PATH", desc)
    monkeypatch.setattr(se, "RESULTS_JSON", results)
    return se, cells, desc, results


def test_write_json_allows_descriptor_and_results(tmp_path, monkeypatch):
    se, _cells, desc, results = _bind(tmp_path, monkeypatch)
    se.write_json(desc, {"ok": True})
    se.write_json(results, {"rows": []})
    assert desc.is_file()
    assert results.is_file()


def test_write_json_allows_known_cell_json(tmp_path, monkeypatch):
    se, cells, _desc, _results = _bind(tmp_path, monkeypatch)
    target = cells / "M0" / "house_profiles.json"
    se.write_json(target, {"profiles": []})
    assert target.is_file()


def test_write_json_rejects_unknown_filename(tmp_path, monkeypatch):
    se, cells, _desc, _results = _bind(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="not allowed"):
        se.write_json(cells / "M0" / "secret.json", {"x": 1})


def test_write_json_rejects_unknown_cell_and_escape(tmp_path, monkeypatch):
    se, cells, _desc, _results = _bind(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="not allowed"):
        se.write_json(cells / "M9" / "house_profiles.json", {"x": 1})
    with pytest.raises(ValueError, match="allowlist"):
        se.write_json(tmp_path / "evil.json", {"x": 1})
    escaped = cells / ".." / "outside.json"
    with pytest.raises(ValueError, match="allowlist"):
        se.write_json(escaped, {"x": 1})
