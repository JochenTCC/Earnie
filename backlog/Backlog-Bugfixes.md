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

- [ ] **Monitor S₀→S₂ desktop plot (hide on phones)** — implemented (`ui/s2_viewport.py`: phones keep 24h segments; tablets/desktop get full SA₀→SA₂ span; navigation switch still 24h-based). **Verify on a real mobile device after next pre-release** (phone UA must not show full S₀→S₂; desktop/tablet unchanged).
- [ ] **Chart 1 Ist battery vs SoC direction (interim)** — `_reconcile_history_battery_with_soc` replaces `Ist Batterie-Leistung` when sign opposes the SoC step to the next present slot (`runtime_store/history_chart_rows.py`, `soc_plausibility.py`). Docs: `docs/ui/charts.md`. Tests: `tests/test_soc_battery_reconcile.py`. **v2.5.2**. Full QH energy accounting still open under New Bugs — verify on dump slot 14.09. 13:00 (discharge bar while SoC 42%→50%).

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Chart 1 / Produktiv-Log: slot energy from one power sample (QH) — accounting inconsistent**
  - **Symptom** (`debug-dumps\debug_dump_20260914_134015`, 14.09. 13:00): Chart 1 gray bar showed full battery **discharge** while SoC **rose** in the same slot (42%→50%). Power meters at the run were Kirchhoff-consistent with discharge; SoC delta implied net charge — typical when power reverses inside the quarter hour after a single sample.
  - **Root cause:** `main.py` reads instantaneous plant/flex **power (kW)** once per Viertelstunden-Lauf and stores `consumption_snapshot`. Chart 1 history, Kosten/Analyse, and “Ist” bars treat that sample as if it held for 15 min (`kW × dt`). That is a sloppy energy integration. Streamlit live polls (Sankey, EHAL-Com) are separate and are not the meter-of-record for history.
  - **Interim mitigation:** shipped in **v2.5.2** — see Verifications Pending (SoC↔Ist reconcile). Can break visual Kirchhoff; not a durable architecture.
  - **Required — plan a changed implementation** (do not keep one-sample×QH as architecture):
    1. **Preferred (near-term): high-rate power sampling in `main.py` (≤ 60 s)** — background sampler for plant + flex (+ SoC); on QH close write **slot mean kW** and/or **energy_kwh** for the *previous* interval into the Produktiv-Log; Chart 1 gray bars + Verbrauch & Kosten use mean/energy; keep a **decision snapshot** (instantaneous) for the optimizer tick; Sankey/EHAL-Com stay live instantaneous; narrow SoC↔Ist reconcile to fallback when sample count is too low. Daemon remains meter-of-record (not Streamlit).
    2. **Later optional A — energy counters (ΔkWh) where available:** Prefer counter deltas for grid± / PV when mapped (Loxone EFM/Zähler at least; extend EHAL optionally). Same chart contract: bars = average power from slot energy. Battery/flex may still use sampled mean if no reliable AC energy counter. Combine with (1): counters for channels that have them, sampling elsewhere.
    3. **Review deviation handling"" - Check if false deviation messaging may also is caused by the current / old approach
  - **Out of scope for the interim:** changing control setpoints to depend on mid-slot averages; rewriting old single-sample log rows without a migration rule (document how pre-change slots are displayed).


## Document Review Findings (Do not remove this chapter — even if empty)


