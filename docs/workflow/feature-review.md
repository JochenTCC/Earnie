# Anonymous feature reviews (star ratings)

**Status:** client + receiver implemented. Earnie opens a reusable Streamlit dialog; earnie-server accepts `POST /review` and appends to `reviews.jsonl`.

## 1. Goal

Collect voluntary, anonymous product feedback (1–5 stars on up to three criteria + optional short comment) after the user has used a feature. First call site: Szenario-Explorer, once per install, when leaving the page after a simulation was started.

Non-goals: linking reviews to UsagePing install ids, GitHub Issues, config uploads, analytics profiles.

## 2. Principles

- **Explicit send:** the user presses **Senden**; that is consent for this payload only. Abort marks the prompt done without POSTing.
- **Once per `review_id`:** state in `runtime/feature_reviews.json`; after send or abort the dialog never returns for that id.
- **Data minimisation:** fixed whitelist payload; no install UUID, no config, no prices, no locations.
- **Fail loud on send:** missing `EARNIE_REVIEW_URL` or non-2xx → error in the dialog; do not mark done (retry or abort).
- **Reusable UI:** `ui/star_review_dialog.open_star_review_dialog(review_id, overall_question, star_questions)` with 1–3 questions.

## 3. Client

| Piece | Path |
|-------|------|
| State + POST | `runtime_store/feature_review.py` |
| Dialog | `ui/star_review_dialog.py` |
| Leave-SE hook | `app.py` arms pending on leave, then calls `maybe_prompt` every run until done |
| Env | `EARNIE_REVIEW_URL` (full URL, e.g. `http://host:8787/review`) |

State shape:

```json
{
  "scenario_explorer": {
    "done_at": "2026-10-18T21:00:00+00:00",
    "sent": true
  }
}
```

Payload schema v1 (exact keys):

```json
{
  "v": 1,
  "review_id": "scenario_explorer",
  "app_version": "2.7.0",
  "ratings": [5, 4, 3],
  "comment": ""
}
```

- `ratings`: length 1–3, each int 1–5 (same order as the dialog questions).
- `comment`: string ≤ 500 chars (`""` when empty).

## 4. Server (earnie-server)

Same process as UsagePing: `POST /review` → 204, append-only `reviews.jsonl` with server `received_at` (UTC). Shared in-memory per-IP rate limiter; no access log; no IP persistence. Body limit 4 KiB (a 500-char comment of 4-byte UTF-8 characters must fit). `review_id` must match `[a-z0-9_]{1,64}`.

## 5. SE call site

- After a backtesting run is started → session flag `earnie_se_sim_started`.
- When the user navigates away from Szenario-Explorer → dialog once if not done.
- Questions: configuration ease, result clarity, result plausibility (German UI copy).
