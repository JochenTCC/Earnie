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


- [ ] **Bugfix — forecast.solar refreshes only one PV system per cycle (found 2026-10-30):** `data/pv_forecast.py` kept one global 15-min cooldown stamp (`_LAST_API_CALL`) for all forecast.solar URLs. After the first system was fetched, every other system in the same cycle returned its old cache. On the NAS (2.7.0-beta.1, two roofs) the second roof was last refreshed the evening before, so its cached forecast ended with today and the next day planned 0 kW for it (36 vs. 72 kWh PV in the horizon). Fix: cooldown per URL (`_LAST_API_CALL_BY_URL`); the 429 retry-at block stays global (the limit is per IP). Test: `tests/test_pv_forecast.py::test_cooldown_is_per_system_so_every_system_refreshes`. Verify on the NAS: both `ext:pv_forecast:*` keys in the shadow feed get a fresh 200 record every 15–30 min, and the second roof shows values for the next day.
- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Synthetic PV fallback ignores orientation and is silent in Shadow mode (found 2026-10-30):** when no forecast.solar data is available (Shadow with a stale feed record, or no cache after restart), `_generate_seasonal_fallback` plans a parabola with 40 % of kWp in October, independent of azimuth/tilt and weather (a north roof got 2.72 kW peak, the same curve on both days). Only a WARNING line in the log shows it. Decide: louder signal (UI/health), a better substitute (e.g. Open-Meteo irradiance with orientation), or no plan with that system (`no-implicit-fallbacks.mdc`).
- [ ] **Recorder replay plan differs from the live plan in 7 of 16 NAS cycles (found 2026-10-28):** all 16 cycles of the 2.7.0-beta.1 dump `debug_dump_20261028_103550` replay offline, but 7 plan hashes differ from the recorded ones (e.g. 09:44 replay runs `pool_swimspa` at 2.8 kW, live did not; 10:29 replay charges the battery at 2.745 kW, live mode 2). Suspected: inputs the replay still reads fresh instead of from the recording (outdoor forecast in `optimizer/thermal_targets.py`), and the recorder reading the thermal values a second time after the live run. Not investigated. The plan is info-level in the regression suite; the private case `REG-76-nas-thermal-replay` uses a matching cycle (09:59).

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue


## Document Review Findings (Do not remove this chapter — even if empty)

