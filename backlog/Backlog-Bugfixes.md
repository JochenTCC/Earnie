# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / `### Document Review …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome; plus `## Document Review Findings` (docs corrections).
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump). Docs-only findings: no version bump unless asked.
**Document Review Findings:** After the agent corrects the docs → move straight to `Backlog-Erledigt.md` (skip Verifications Pending). See skill `doc-review-findings`.

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **Virtual reserve: `advance_reserve_after_slot` / `set_trigger` wiped `target_kwh` to 0** — fix implemented (2026-10-10); live acceptance pending
  - Symptom (Nas productive, Geschirrspüler / `virtual_gs`): dishwasher running, MILP ZWANGSLADEN toward ~11.8% (≈1 kWh refill), but `powerstation_reserves.json` stayed `empty` / `stored_kwh=0` / `target_kwh=0`.
  - Cause: `get_or_init_state(..., target_kwh=0.0)` always overwrote the configured target on every slot advance / trigger latch, so charge credit was capped at `min(0, …)`.
  - Fix: `update_target=False` for advance + trigger; collect/learn still refresh the target.
  - Tests: `tests/test_powerstation_2_7_p.py` (`test_advance_and_trigger_preserve_target_kwh`).
- [ ] **Bug — config pack import accepts incompatible member files** — fix implemented (2026-10-17); live acceptance pending
  - Cause: `_migrate_and_validate_pack_docs` stamped members to current before `ensure_compatible` (would whitewash v1/v2/untagged if validate were bypassed). `validate_migrated_docs` already rejected incompatible members first.
  - Fix: ensure then stamp; `grid_fees.json` still exempt; doc `speichern-laden.md` now states members are checked too.
  - Tests: `tests/test_config_pack_and_paths.py` (`test_config_pack_rejects_v2_member_with_v4_manifest`, `test_migrate_and_validate_ensures_before_stamp`).
- [ ] **Loxone VI/VO export: Pilot→Earnie + open push token** — fix implemented (2026-10-18); live Loxone import acceptance pending
  - Remove `(2.7.q Q4)` from exported VI Comments / library VI_v2 HTML comments.
  - Export filenames: `VO_Earnie_*` / `VI_Earnie_*`, `Earnie-*-Signalliste.csv` (was Pilot).
  - Placeholder `PUSH_TOKEN_HIER_ERSETZEN`; ZIP README step 3 updated.
  - Unset `EARNIE_PUSH_TOKEN` → open LAN telemetry (no 404); empty VO token omits `?t=` / `/t/`.
  - Tests: `test_ehal_signal_list`, `test_pilot_vi_template_gen`, `test_pilot_vo_template_gen`, `test_loxone_push_inbox`.
- [ ] **SE 5-star review dialog + earnie-server `POST /review`** — fix implemented (2026-10-18); UI/cloud acceptance pending
  - Replaced cloud-demo GitHub feedback banner with reusable `@st.dialog` (`ui/star_review_dialog.py`) for all SE installs.
  - Trigger: leave Szenario-Explorer after a run was started; once per `review_id` (`runtime/feature_reviews.json`); send or abort.
  - Always POST anonymous payload to `EARNIE_REVIEW_URL`; earnie-server appends `reviews.jsonl`.
  - Tests: `tests/test_feature_review.py`, earnie-server `tests/test_usage_ping_receiver.py` (review route).

## New Bugs (Do not remove this chapter — even if empty)

- [ ] On SE page during opt-in ping pop up the shown data example is still "v1" - shouldn't it be "v2"?
- [ ] "debug-dumps\debug_dump_20261015_222809"


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] swap positions of EHAL-Com and Optimierer-Dienst in sidebar


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **Cloud demo vs „einmalig“ for SE star review** (`docs/einrichtung/betrieb.md`, `private-env.md`): with `EARNIE_CLOUD_DEMO=1` each browser session uses a temp workspace, so `feature_reviews.json` is session-scoped — “once per install” wording may overstate permanence on Community Cloud. Confirm whether docs should say once per session there.
