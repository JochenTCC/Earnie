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

- [ ] **Dump `debug_dump_20261030_055437` — discharge bar above zero during Zwangsentladen (2.7.0-beta.1, Loxone):** the note says 19.10. 17:00 Zwangsentladen with no battery-withdrawal bar above zero. History at 19.10. 17:00 is mode 0 (Automatik), plan −0.04 kW, Ist discharge ~0.18 kW. The chart that was open is 29.10. 07:00–31.10. 07:03. There, 29.10. 17:15–17:45 is Zwangsentladen 5 kW (Ist −4.2 / −5 / −5 kW). The chart draws „Batterie entladen (Verbrauch)“ above zero only for the house share (~0.39 / 0.50 / 0.48 kW). The rest (~3.8–4.5 kW) is „Einspeisung (Batterie)“ below zero. Confirmed gap: that export kW has no matching up bar, so the two columns differ by „Einspeisung (Batterie)“. Add an up segment of the same kW (discharge that feeds the export), stacked with „Batterie entladen (Verbrauch)“, and keep the down bar. **Arrives with the next pick from `release/2.7`** (owner, 2026-10-31).


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`; not started yet (no draft in `.github/release-notes/`, `UNRELEASED.md` only has the HA sign hint and the removed `flexible_consumers`). Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) the EU feature pause after an unreachable host (#59), the new HA package automation `earnie_watchdog_release_force` (default on, 300 s; #60), the templated `set_value` action for `input_number` targets (#60) and the report page / daemon start after the migration (#61).


## Document Review Findings (Do not remove this chapter — even if empty)

