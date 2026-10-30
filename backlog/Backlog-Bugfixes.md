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

- [ ] **Recorder replay still missed the live plan for cycles with a virtual reserve refill or a plugged-in EV (found 2026-10-30 testing PR #86):** shadow cycle 30.10. 12:55 (2.7.0-beta.2, with recorded outdoor forecast): live forced-charged 4.979 kW, replay 1.532 kW, and replay planned `e_auto` that live left out. Two inputs were not recorded. (1) The active powerstation reserves (`powerstation_reserves.json` after the telemetry trigger sync) shape the battery params (`_virtual_reserve_asap_kwh`, which also skips the PV-only sunrise limit); replay used plain config params. (2) The EV charging context reads Loxone after `begin_cycle` (plugged in, SoC, ready time, limits); replay read the local inbox and built a not-plugged-in forecast context instead of „plugged in, charge complete“. On the NAS dump `e_auto` was missing from the live setpoints in 298 of 634 cycles. Fix: the recorder stores `start_state.active_reserves` (from `main.py`) and `start_state.push_reads` (every `read_push_value` / `read_push_counter` / `read_push_ready_by_time` between `begin_cycle` and `finish_cycle`, first value per id, `runtime_store/push_read_replay.py`). Replay applies the reserves to the battery params and serves the push reads, failing loud on a read the live cycle did not make; cycles without these keys replay as before. Verified on a fresh local shadow cycle (30.10. 14:59:58): replay hash `e374d1efc23ad984` equals live. Still open: check NAS cycles after the rollout (replay vs. live hash over a day); HA backends read through the adapter, not the push inbox, and are not covered.

- [ ] **Dump `debug_dump_20261030_055437` — „Zwangs-Laden nicht ausgeführt“ at 30.10. 01:15 and 02:15 (2.7.0-beta.1, Loxone):** rule `battery_forced_charge_missing` (tolerance 0.1 kW). Both slots are Zwangsladen 0.213 kW (SoC 12 % → target SoC 12.3 %). Earnie wrote `set_ess_mode=1`, `set_ess_active_power=-0.213`, discharge limit 0, and the writes succeeded. Slot-mean Ist was discharge (+0.266 / +0.240 kW, Loxone sign), so the marker matches the quarter-hour mean. At the decision instant the battery was still discharging ~2 kW (previous slot Automatik); by the next cycle the snapshot had flipped to about −0.21 kW charge, after the 15-min mean was already closed. The same 0.213 kW command at 02:30, issued while already charging, held (mean −0.21 kW). Larger commands in between (1.489 kW, 3.766 kW) did charge inside the slot. Same class as the closed #50 / #57 case for a mean that never moves. Chosen follow-up, implemented: yellow Warnung `battery_forced_charge_target_missed` when the slot mean moves toward charge by more than `tolerances.power_kw` but delivered charge stays below Soll; the red error stays when the mean does not move. Existing packs pick the rule up via migration step `dm4.forced_charge_hint`; `dm4.deviation_marker_colors` sets Hinweis green / Warnung yellow and moves the rule to `warning` (`316bb844`). A rules file without category blocks no longer blocks the config-pack import on that step (`dfbd052d`). Both cherry-picked to `main` in PR #86 (one commit; on `main` both steps gate on data model >= 4). Testing on this dump showed the movement warning fired on 136 of 627 forced-charge slots (22 %, median 82 % delivered). Reworked 2026-10-30 on `release/2.7`: both forced-charge rules grade the delivered slot energy (slot mean × slot length) against the target energy (Soll × slot length), predicate `battery_charge_energy_below_ratio`: >= 80 % ok, 60–80 % yellow `battery_forced_charge_target_missed`, < 60 % red `battery_forced_charge_missing`. The thresholds are `params.max_ratio` in the pack, and the tooltips show % and kWh. There is no verdict without a closed-interval slot mean. 01:15 and 02:15 (0 % delivered) are red again under this rule. `dm4.forced_charge_hint` moves beta.2 packs and the shipped error rule to the energy form (needs a new pick to `main`). Live check still open.

- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).


## New Bugs (Do not remove this chapter — even if empty)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
