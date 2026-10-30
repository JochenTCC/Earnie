"""Reusable anonymous 5-star feature-review dialog (Streamlit)."""
from __future__ import annotations

import logging
from collections.abc import Sequence

import streamlit as st

from runtime_store.feature_review import (
    MAX_COMMENT_LEN,
    MAX_RATINGS,
    MIN_RATINGS,
    REVIEW_ID_SCENARIO_EXPLORER,
    SESSION_SE_REVIEW_PENDING_KEY,
    is_review_done,
    mark_review_done,
    se_simulation_started,
    send_review,
)

logger = logging.getLogger(__name__)

_STAR_OPTIONS = (1, 2, 3, 4, 5)
_ANONYMITY_CAPTION = (
    "Es werden nur **anonyme** Sternebewertungen und optional Ihr Kommentar "
    "gesendet — keine Konfiguration, keine Geräte-, Preis- oder Standortdaten."
)


def _validate_questions(star_questions: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(star_questions, (list, tuple)):
        raise ValueError("star_questions must be a sequence of strings")
    cleaned = tuple(str(q).strip() for q in star_questions)
    if not MIN_RATINGS <= len(cleaned) <= MAX_RATINGS:
        raise ValueError(
            f"star_questions must have length {MIN_RATINGS}..{MAX_RATINGS}, got {len(cleaned)}"
        )
    if any(not q for q in cleaned):
        raise ValueError("star_questions must not contain empty strings")
    return cleaned


def _format_star(n: int) -> str:
    return f"{'★' * n}{'☆' * (5 - n)} ({n})"


@st.dialog("Feedback")
def _review_dialog(
    review_id: str,
    overall_question: str,
    star_questions: tuple[str, ...],
) -> None:
    st.markdown(f"**{overall_question}**")
    st.caption(_ANONYMITY_CAPTION)

    ratings: list[int] = []
    for index, question in enumerate(star_questions):
        value = st.select_slider(
            question,
            options=_STAR_OPTIONS,
            value=3,
            format_func=_format_star,
            key=f"star_review_{review_id}_q{index}",
        )
        ratings.append(int(value))

    comment = st.text_area(
        "Kommentar (optional)",
        key=f"star_review_{review_id}_comment",
        height=100,
        max_chars=MAX_COMMENT_LEN,
        placeholder="Was hat gut funktioniert, was war unklar oder fehlte?",
    )

    col_send, col_abort = st.columns(2)
    with col_send:
        if st.button("Senden", type="primary", key=f"star_review_{review_id}_send"):
            try:
                send_review(
                    review_id=review_id,
                    ratings=ratings,
                    comment=(comment or "").strip(),
                )
            except (ValueError, RuntimeError) as exc:
                logger.warning("feature_review send failed: %s", exc)
                st.error(f"Feedback konnte nicht gesendet werden: {exc}")
                return
            mark_review_done(review_id, sent=True)
            st.rerun()
    with col_abort:
        if st.button("Abbrechen", key=f"star_review_{review_id}_abort"):
            mark_review_done(review_id, sent=False)
            st.rerun()


def open_star_review_dialog(
    review_id: str,
    overall_question: str,
    star_questions: Sequence[str],
) -> None:
    """Open the reusable star-review dialog (caller decides when).

    Parameters
    ----------
    review_id:
        Stable id (persisted in ``runtime/feature_reviews.json``).
    overall_question:
        Dialog headline / overall question text.
    star_questions:
        One to three criterion labels for 1–5 star sliders.
    """
    if not isinstance(review_id, str) or not review_id.strip():
        raise ValueError("review_id must be a non-empty string")
    overall = str(overall_question or "").strip()
    if not overall:
        raise ValueError("overall_question must be a non-empty string")
    questions = _validate_questions(star_questions)
    _review_dialog(review_id.strip(), overall, questions)


def arm_scenario_explorer_review_prompt() -> None:
    """Arm the leave-SE review dialog (keep calling ``maybe_prompt`` until done)."""
    st.session_state[SESSION_SE_REVIEW_PENDING_KEY] = True


def maybe_prompt_scenario_explorer_review() -> None:
    """Leave-SE hook: once per install after a simulation was started this session.

    Must be called on every script run while the prompt is pending so the
    ``@st.dialog`` stays open across widget interactions.
    """
    if not st.session_state.get(SESSION_SE_REVIEW_PENDING_KEY):
        return
    if not se_simulation_started() or is_review_done(REVIEW_ID_SCENARIO_EXPLORER):
        st.session_state[SESSION_SE_REVIEW_PENDING_KEY] = False
        return
    open_star_review_dialog(
        REVIEW_ID_SCENARIO_EXPLORER,
        "Wie war die Simulation? Mit der Beantwortung der Fragen helfen Sie uns, Earnie zu verbessern.",
        (
            "Die Konfiguration der Szenarios war einfach",
            "Die Ergebnisdarstellung ist verständlich",
            "Das Ergebnis ist plausibel",
        ),
    )
