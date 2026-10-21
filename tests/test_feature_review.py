"""Anonymous feature-review client (star ratings → earnie-server)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime_store import feature_review
from runtime_store.server_endpoints import PATH_REVIEW, url_for


@pytest.fixture
def review_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "feature_reviews.json"
    monkeypatch.setattr(
        "runtime_store.feature_review.feature_reviews_state_file",
        lambda: str(path),
    )
    return path


def test_build_payload_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_review, "_app_version", lambda: "2.7.0-test")
    payload = feature_review.build_payload(
        review_id="scenario_explorer",
        ratings=[5, 4, 3],
        comment="ok",
    )
    assert set(payload.keys()) == feature_review.PAYLOAD_KEYS_V1
    assert payload["v"] == 1
    assert payload["ratings"] == [5, 4, 3]
    assert payload["comment"] == "ok"
    assert payload["app_version"] == "2.7.0-test"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ratings": []},
        {"ratings": [1, 2, 3, 4]},
        {"ratings": [0, 5, 5]},
        {"ratings": [True, 2, 3]},
        {"comment": "x" * 501},
        {"review_id": ""},
    ],
)
def test_build_payload_rejects(kwargs: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_review, "_app_version", lambda: "1.0.0")
    base = {
        "review_id": "scenario_explorer",
        "ratings": [5, 4, 3],
        "comment": "",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        feature_review.build_payload(**base)


def test_mark_and_is_review_done(review_state: Path) -> None:
    assert feature_review.is_review_done("scenario_explorer") is False
    feature_review.mark_review_done("scenario_explorer", sent=True)
    assert feature_review.is_review_done("scenario_explorer") is True
    data = json.loads(review_state.read_text(encoding="utf-8"))
    assert data["scenario_explorer"]["sent"] is True
    assert data["scenario_explorer"]["done_at"]


def test_send_review_default_endpoint_is_composed_base_plus_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feature_review, "_app_version", lambda: "2.7.0")
    sent: list[tuple[str, bytes]] = []

    def _transport(url: str, body: bytes, timeout: float) -> int:
        sent.append((url, body))
        return 204

    feature_review.send_review(
        review_id="scenario_explorer",
        ratings=[5],
        transport=_transport,
    )
    assert sent[0][0] == url_for(PATH_REVIEW)


def test_send_review_blank_override_raises() -> None:
    with pytest.raises(ValueError, match="endpoint_url"):
        feature_review.send_review(
            review_id="scenario_explorer",
            ratings=[5],
            endpoint_url="",
        )


def test_send_review_posts_and_checks_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_review, "_app_version", lambda: "2.7.0")
    sent: list[tuple[str, bytes]] = []

    def _transport(url: str, body: bytes, timeout: float) -> int:
        sent.append((url, body))
        return 204

    feature_review.send_review(
        review_id="scenario_explorer",
        ratings=[5, 4, 3],
        comment="",
        transport=_transport,
        endpoint_url="http://example.test/review",
    )
    assert sent[0][0] == "http://example.test/review"
    payload = json.loads(sent[0][1].decode("utf-8"))
    assert payload["ratings"] == [5, 4, 3]


def test_send_review_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_review, "_app_version", lambda: "2.7.0")

    def _transport(url: str, body: bytes, timeout: float) -> int:
        return 400

    with pytest.raises(RuntimeError, match="400"):
        feature_review.send_review(
            review_id="scenario_explorer",
            ratings=[5],
            transport=_transport,
            endpoint_url="http://example.test/review",
        )


def test_mark_se_simulation_started(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_state: dict = {}
    monkeypatch.setitem(
        __import__("sys").modules,
        "streamlit",
        SimpleNamespace(session_state=fake_state),
    )
    feature_review.mark_se_simulation_started()
    assert fake_state[feature_review.SESSION_SE_SIM_STARTED_KEY] is True


def test_open_star_review_dialog_rejects_bad_questions() -> None:
    from ui.star_review_dialog import open_star_review_dialog

    with pytest.raises(ValueError, match="star_questions"):
        open_star_review_dialog("x", "Frage?", [])
    with pytest.raises(ValueError, match="star_questions"):
        open_star_review_dialog("x", "Frage?", ["a", "b", "c", "d"])
