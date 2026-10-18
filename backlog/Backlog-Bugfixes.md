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

## New Bugs (Do not remove this chapter — even if empty)

- [ ] On SE page during opt-in ping pop up the shown data example is still "v1" - this should be more accurate --> currently "v2"
- [ ] swap positions of EHAL-Com and Optimierer-Dienst in sidebar
- [ ] substitute the message "Sie haben gerade den Szenario-Explorer gestartet. Was hat gut funktioniert, was war unklar oder fehlte? Kurzes Feedback hilft uns, Earnie zu verbessern (öffentliches GitHub-Issue — keine Secrets pasten)." with a pop-up dialog where the user can give a 5-star-review for these criterias:
  - Die Konfiguration der Szenarios war einfach
  - Die Ergebnisdarstellung ist verständlich
  - Das Ergebnis ist plausibel
  Also add an open field (optional) for comments
  The pop-up appears when the user scrolls to "Detaillierte Simulationsansicht" (with a delay of 10 sec.)
  The user can send the review or abort the dialog
  When user sends it could also be sent to the earnie-server
  The dialog emphasizes that only anonymous data is sent 
  Make the popup dialog reusable (Open parameter is a review-ID, the overall-question text and the 5-star-questions (max three))
- [ ] In the Signalliste (EHAL-com page) there are two signals "heartbeat" and "hearbeat_ts" one for reading - one for writing / both optional. Please rename these signals to make it clearer what is what - and both must be mandatory (however they are not shown in the expander "Optionale Signale aktiveren ...")
- [ ] Earnie-Host (LAN-IP für den Hub) -> rephrase to "IP-Adresse des Geräts, auf dem Earnie läuft" and pre-fill it with the local-host IP (because this is usually the host)

- [ ] "debug-dumps\debug_dump_20261015_222809"

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
