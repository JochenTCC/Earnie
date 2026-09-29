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

- [ ] **Docker image missing `share/ehal` schemas** — After S6470 explicit COPY, image only had `share/config/`; live EHAL validation failed every ~30s (`EHAL schema not found: /app/share/ehal/telemetry.schema.json`). Same fix as `main` / 2.6.0-alpha.8: `docker/Dockerfile` `COPY share/ share/` + regression assert in `test_dockerfile_strips_crlf_and_healthcheck`. Rebuild/redeploy alpha image; NAS live acceptance pending.
- [ ] **False “Zwangs-Entladen nicht ausgeführt”** (`debug_dump_20260923_201155`) — Fix implemented: deviation uses full-entry `closed_by` (not `by_slot` winners); `battery_power_below_tolerance` = Ist ≤ tol only (S6 “nicht ausgeführt”). Tests: `test_deviation_timeline` / `test_deviation_eval`. Dump evening 19:15–19:45 cleared; live Monitor acceptance still pending. Commit/PATCH when ending session.
- [ ] **Monitor Chart 2 daily Kosten KPIs** — Implemented: SA-day annotation columns (full span = two cols; segment = visible day); plan-based **Ersparnis bisher** line in gray zone (`ui/chart_day_costs.py`). Live Monitor acceptance pending.
- [ ] **Stale SoC sanitize chain** (`debug_dump_20260927_083552`) — Fix implemented: trust plant SoC when closed-interval sampler confirms against history (`closed_interval_confirms_reported` + `reported_soc_percent` consecutive count). Live acceptance pending.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Negative export tariff + battery discharge** (`debug_dump_20260927_090524`) — Forced grid discharge while `k_push < 0` does **not** make sense. Dump: live 08:23–09:01 `Zwangsentladen` at **positive** `k_push` (~10–14 ct, room-making OK); plan ~13:45–14:15 `Zwangsentladen` + ~5 kW export at **≈ −0.8 ct** (bug). Replay: hard `export_cap=0` → MILP **Infeasible** (no PV curtailment); without caps Optimal still `dch`+`sell` on negative slots. **Partial fix (2026-09-27):** Monitor/plan chart no longer invents grid export when `k_push_act < 0` (`clip_grid_kw_to_export_cap` in `sim_chart_rows` / finalize) — post-fix `exporting_neg: 0`. **Still open:** PV curtailment var so hard cap stays feasible when SoC full; soft pay-to-export behaviour for live dogfood (2.7.a). Open question: Monitor plan vs live discharge after `k_push` already negative.
- [ ] Tariff preview seems to not work with the model - just by mirroring existing tariff data. Check reasons

## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] **SE analysis charts: show volumetric Netznutzung AP on import price** — MILP already includes house-profile `netznutzung_arbeitspreis_cent_kwh` in `k_act`. SE analysis charts currently show the import tariff without that Arbeitspreis; add it to the displayed import price so chart and optimizer match.
- [ ] Change order on Monitor side: Place sankey diagram right under Chart 1 - then Chart 2 with cost and consumption - then Simulation Details und Energievergleich

## Document Review Findings (Do not remove this chapter — even if empty)

