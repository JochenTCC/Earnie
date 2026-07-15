# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome.
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump).

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.

## Bugfix Verifications Pending

- [x] **Earnie Monitor S-2 navigation SA₀→SA₁ → SA₁→SA₂** — implementation → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Bugfix Earnie Monitor S-2 chart navigation (2026-07-15); verify **→** switches both charts to SA₁→SA₂ and **←** returns to SA₀→SA₁.
- [x] **UI: Cockpit from main.py persistence** — implementation → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Bugfix UI: Cockpit from main.py persistence (2026-07-15); verify Cockpit + Manuelle Geräte after one `main.py` quarter-hour run on silent stack / NAS.
- [x] **EV FertigUm when fully charged (plugged in)** — implementation → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Bugfix EV FertigUm when fully charged (2026-07-15); verify plugged-in full SOC ignores FertigUm, unplug restores absent-forecast path.
- [x] **SoC BL Ziel segment before Jetzt (Chart 1)** — implementation → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Bugfix SoC BL Ziel segment before Jetzt (2026-07-15); verify dotted baseline stops at Jetzt marker.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Hauskonfigurator | PV-Anlage** — Bezeichnung empty; parameters show unplausible values (data not loaded or shown correctly)
- [ ] **Chart 1 — generic `known` consumers** — part of Grundlast overlay for optimization but not shown as separate flex traces in Chart 1
