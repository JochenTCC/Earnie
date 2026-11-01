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

- [ ] **Recorder replay misses the live plan for some SwimSpa and heat pump cycles** *(found 2026-10-31)*: follow-up of the archived push-reads fix. Replay of all 112 NAS cycles with `start_state.push_reads` (30.10. 15:49 – 31.10. 17:59, 2.7.0-beta.2, `release/2.7` @ `10491702`, `solver_mode="production"`): 108 replay hashes equal live. Reserve refill and plugged-in EV are covered now (EV connected 105/107, `e_auto` in live setpoints 17/19, reserve-refill cycles 4/6; all four misses are explained by the consumers below). The four misses:
  - **30.10. 23:59:57:** same setpoints (Zwangsladen 0.213 kW), but live writes `pool_swimspa: 0.0` in `consumer_powers_kw` and replay leaves the key out, so the hash differs. Live and replay build a different consumer set.
  - **31.10. 08:59:53:** live switched the heat pump off (Automatik, battery 0.5 kW); replay keeps `waermepumpe` 1.9 kW (battery −1.4 kW). The 08:44 cycle before (heat pump 1.9 kW live) matches.
  - **31.10. 14:14:52 and 14:29:52** (both with a pending virtual reserve refill): live Entladesperre (mode 2) with `pool_swimspa` 2.8 kW; replay Automatik without SwimSpa (battery 0.635 / 1.652 kW). The matching 13:59 and 14:44 cycles have the same SwimSpa `push_reads` and `thermal_readings` (36 °C, setpoint 35 °C, heating active).
  - Suspected cause: a SwimSpa / heat pump state from the previous cycle (run or session state) that the live cycle reads and the recorder does not store; `flexible_consumers_state` is empty in every cycle. Not proven.
  - **Note:** the outage cycle 31.10. 14:49:58 (`flags.outage`) carries the same live hash as 14:14 — check whether the outage path re-writes the last plan, and whether outage cycles are excluded from replay checks.
  - Done when the four cycles replay to their live hash (or the remaining difference is a documented, intended non-input) and a regression test pins the missing input.
  - **Analysis (2026-11-01):** `flexible_consumers_state` is not empty (it holds `delivered`, e.g. `pool_swimspa` 14.0 kWh on 30.10.). Two causes, none of them SwimSpa / heat pump run state:
    - **Planning clock (23:59:57, 08:59:53):** every NAS cycle is an early start (a few seconds before its tick) and live plans with `planning_now() = max(real now, tick)`. Replay froze the clock at the recorded `timestamp`, so 23:59:57 counted as 30.10. (SwimSpa target already delivered, `pool_filter` still in the set) and 08:59:53 as the 08:00 hour (heat pump window). Replay now freezes at `max(timestamp, planning_window.start)` (`_recorded_planning_moment`); `planning_window.start` is the anchored tick, so no new input is needed. Both cycles replay to their live hash.
    - **Solver time limit (14:14:52, 14:29:52):** these solves take ~3.2–3.7 s against the 3.0 s strict time limit. HiGHS returns its incumbent with status `Optimal` at the limit, so `strict_fallback` never fires and the plan depends on CPU load and timing. Sequential replays of the same entry give the live plan or the other one (objective 315.88 vs 316.48); all 12 cycles slower than 2.85 s (31.10. 13:44–17:44) are affected, all faster cycles match. Documented non-input (wall clock), not fixable by recording inputs; see the follow-up below.
    - **Telemetry limits:** live applies the HK + inbound export cap (`hk_max_export_kw`, `inbound_export_limit_kw`) and the effective `get_ess_*` limits; replay applied neither and did not drop ESS without own SoC. The recorder now stores `start_state.export_limits` and `start_state.ess_limits`; replay applies them and `filter_planning_batteries_with_soc` (cycles without the keys replay as before). Not the cause of the four misses (export cap 11 kW, limits equal to HK in these cycles), but live inputs replay could not see.
    - **Outage note:** `flags.outage` is set for out-of-band triggers (`bool(out_of_band)` in `main.py`), not for an outage. 14:49:58 runs a full fresh MILP; its hash equals 14:14 because the setpoints are equal (mode 2, SwimSpa 2.8 kW) — the hash covers only mode, target, battery plan and consumer powers. `list_full_horizon_cycles(require_unflagged=True)` excludes flagged cycles from the regression selection; ad-hoc replays of all cycles include them. The flag name is misleading (follow-up).
    - **Result:** replay of all 112 cycles, one worker: 110/112 match; the two misses (14:49:58, 14:50:11) are time-limited solves (14:14 and 14:29 matched in that run, missed in others). Tests: `tests/test_recorder_replay.py` (tick freeze, ESS / export limits), `tests/test_cycle_recorder.py` (recorded keys).
    - **Follow-up (open):** make time-limited live solves visible or reproducible, e.g. record the strict elapsed time / time-limit hit and the objective in `outputs`, and treat a HiGHS time-limit stop as not optimal so `strict_fallback` fires; rename `flags.outage` to `out_of_band`.
    - **Landed (2026-11-01):** fix committed on `release/2.7`; cherry-pick to `main` pending (collected pick).


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
