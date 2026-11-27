"""scripts/check_cognitive_complexity.py: same scope as SonarCloud python:S3776."""

from __future__ import annotations

import textwrap

import pytest

from scripts import check_cognitive_complexity as cc


def _real_patterns() -> tuple[str, ...]:
    text = cc.SONAR_PROPERTIES.read_text(encoding="utf-8")
    return cc.excluded_patterns(cc.read_properties(text))


def test_read_properties_joins_continuations_and_skips_comments():
    text = "# comment\n\na.b=1\nlist=\\\n  x,\\\n  y\n! other comment\nc = 3\n"
    assert cc.read_properties(text) == {"a.b": "1", "list": "x,y", "c": "3"}


def test_scope_follows_sonar_project_properties():
    patterns = _real_patterns()
    # S3776 exemptions and analysis exclusions are both taken from the file.
    for pattern in ("**/scripts/**", "**/studies/**", "**/tools/**", "**/tests/**"):
        assert pattern in patterns
    # Sonar skips data/ and runtime_store/, the quality gate measures them.
    assert "**/data/**" not in patterns
    assert "**/runtime_store/**" not in patterns


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("optimizer/milp_horizon.py", True),
        ("main.py", True),
        ("house_sim/core/evcs.py", True),
        ("data/edibert_slot_prices.py", True),
        ("runtime_store/migration/steps/ehal_bindings.py", True),
        ("integrations/loxone_structure.py", True),
        ("integrations/loxone_mcp_probe.py", False),
        ("scripts/run_backtesting.py", False),
        ("studies/viability/check_houses.py", False),
        ("tools/ha_loxone_bridge/mapping.py", False),
        ("tests/test_optimizer.py", False),
        ("house_sim/tests/test_core.py", False),
    ],
)
def test_in_scope(path, expected):
    assert cc.in_scope(path, _real_patterns()) is expected


def test_excluded_patterns_requires_resource_key():
    props = {
        "sonar.issue.ignore.multicriteria": "x1",
        "sonar.issue.ignore.multicriteria.x1.ruleKey": cc.RULE_KEY,
    }
    with pytest.raises(ValueError, match="x1 has no resourceKey"):
        cc.excluded_patterns(props)


def test_excluded_patterns_ignores_other_rules():
    props = {
        "sonar.issue.ignore.multicriteria": "a,b",
        "sonar.issue.ignore.multicriteria.a.ruleKey": "python:S5332",
        "sonar.issue.ignore.multicriteria.a.resourceKey": "**/lab/**",
        "sonar.issue.ignore.multicriteria.b.ruleKey": cc.RULE_KEY,
        "sonar.issue.ignore.multicriteria.b.resourceKey": "**/scripts/**",
    }
    assert cc.excluded_patterns(props) == ("**/scripts/**",)


def test_measure_uses_sonar_cognitive_complexity(tmp_path):
    # ImportError, not only ModuleNotFoundError: Windows Smart App Control may block
    # complexipy's native extension; the test then skips.
    pytest.importorskip("complexipy", exc_type=ImportError)
    # if +1, for +2 (nested once), inner if +3 (nested twice) = 6, as SonarSource counts it.
    (tmp_path / "mod.py").write_text(
        textwrap.dedent(
            """
            def nested(a, b):
                if a:
                    for x in b:
                        if x:
                            return x
                return None
            """
        ),
        encoding="utf-8",
    )
    assert cc.measure(["mod.py"], root=tmp_path) == [cc.Finding("mod.py", 2, "nested", 6)]


def test_main_fails_only_over_max(monkeypatch, capsys):
    findings = [cc.Finding("a.py", 1, "f", 16), cc.Finding("a.py", 9, "g", 15)]
    monkeypatch.setattr(cc, "tracked_python_files", lambda paths: ["a.py"])
    monkeypatch.setattr(cc, "measure", lambda files: findings)

    assert cc.main([]) == 1
    out = capsys.readouterr().out
    assert "a.py:1  f" in out
    assert "a.py:9" not in out
    assert cc.main(["--max", "16"]) == 0
