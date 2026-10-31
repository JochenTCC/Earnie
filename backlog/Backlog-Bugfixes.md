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

- [ ] **[release/2.7] Forced-charge deviation (`battery_charge_energy_below_ratio`): absolute shortfall threshold.** The rule fired on the ratio alone (delivered slot energy < `params.max_ratio` × target energy), so small Soll amounts raised false alarms when only a few Wh were missing. Fix: both forced-charge rules fire only when the ratio is violated **and** the shortfall (target − delivered energy per slot) exceeds `params.min_shortfall_kwh` (shipped 0.1, per rule in the pack); a rule using the predicate without either parameter fails loud. Migration step `dm4.deviation_energy_shortfall` adds `min_shortfall_kwh` (0.1) where missing and keeps custom values. Needs a pick to `main`. Live check still open: forced-charge markers over a day with small Soll amounts.

- [ ] **[release/2.7] Heat-pump deviation („Freigabe, aber nicht angesprungen“): grade like forced charging.** The rule had only `power_mismatch_positive` with the global `tolerances.power_kw` (0.05 kW), so any shortfall above 50 W raised the hint, even when the heat pump ran and only drew a bit less. Fix: new consumer predicate `power_energy_below_ratio`: slot energy < `params.max_ratio` × Soll energy **and** shortfall > `params.min_shortfall_kwh` (shipped 0.5 / 0.1 kWh, per rule, separate from the forced-charge rules). No verdict without the consumer's closed-interval slot mean (`closed_interval.flex_kw`); the tooltip shows % and kWh. `dm4.deviation_energy_shortfall` rewrites the rule while it has the shipped form (ids `wp_heating_enable_no_start` / `waermepumpe_enable_no_start`) and keeps a custom message. Needs a pick to `main`. Live check still open: heat-pump hints over a day.

## New Bugs (Do not remove this chapter — even if empty)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
