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
- [ ] **Delta 3 standby charge exceeds HK / live ESS limits** (dump `debug_dump_20261015_222809`) — fix implemented (2026-10-19); overnight Chart1 / write acceptance pending
  - Symptom: Chart1 SoC for Ecoflow Delta 3 jumped steeply around 03:00 (implied ~1.5 kW/QH) above the intended HK / Smarthome max-charge ceiling.
  - Cause: `collect_standby_packs` used raw HK charge power and skipped 2.7.j effective limits; live resolve could also loosen HK.
  - Fix: standby packs + writes use HK ∩ live; live never loosens HK; PS live gets are entity-scoped only.
  - Tests: `tests/test_ess_limits_2_7_j.py`, `tests/test_powerstation_2_7_h.py` (`test_collect_standby_packs_applies_hk_and_live_charge_cap`).
  - [ ] **Live golden dump (private REG):** when the fixed version is running on productive NAS, capture a debug dump (with `recorder/`) around a cheap-slot Delta 3 refill and intake as a private golden case confirming charge ≤ HK ∩ live.

- [ ] **Cockpit pages disabled after EHAL PV retirement + migration** — fix implemented (2026-10-19); live acceptance pending
  - Symptom: After `dm4.retire_plant_pv_binding` / inv-PV required signals, Live-Cockpit (Monitor / Manuelle Geräte) disappeared on NAS productive.
  - Cause: (1) `_REQUIRED_PLANT_LIVE_FIELDS` still required retired plant `sens_pv_production_active`; (2) Binding-P5 consumers with only `ehal_bindings` kept `needs_planning_onboarding` true, so the markers gate applied.
  - Fix: drop plant PV from Cockpit gate; require `inv.*.sens_inv_power_pv` activation; treat `ehal_bindings` consumers as live wiring.
  - Tests: `tests/test_setup_readiness.py` (`test_needs_planning_onboarding_false_for_ehal_bindings_consumers`, `test_betrieb_unlocked_with_ehal_consumers_without_plant_pv`).


## New Bugs (Do not remove this chapter — even if empty)



## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Review and modify text in SE review pop-up dialogue


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **Cloud demo vs „einmalig“ for SE star review** (`docs/einrichtung/betrieb.md`, `private-env.md`): with `EARNIE_CLOUD_DEMO=1` each browser session uses a temp workspace, so `feature_reviews.json` is session-scoped — “once per install” wording may overstate permanence on Community Cloud. Confirm whether docs should say once per session there.
