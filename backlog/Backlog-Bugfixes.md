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



## New Bugs (Do not remove this chapter — even if empty)

## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] **SE analysis charts: show volumetric Netznutzung AP on import price** — MILP already includes house-profile `netznutzung_arbeitspreis_cent_kwh` in `k_act`. SE analysis charts currently show the import tariff without that Arbeitspreis; add it to the displayed import price so chart and optimizer match.
- [ ] Change order on Monitor side: Place sankey diagram right under Chart 1 - then Chart 2 with cost and consumption - then Simulation Details und Energievergleich
- [ ] Add a switch on page Optimierer-Dienst to switch from Silent Mode to Loud Mode (so the user does not need to edit local_settings.json)

## Document Review Findings (Do not remove this chapter — even if empty)

