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

- [ ] **Recorder replay fails offline for installations with an EV `get_evcs_limit_soc` binding:** fixed in `runtime_store/cycle_recorder.py` + `runtime_store/recorder_replay.py` (no version bump): the recorder now stores the resolved limit SoC per EV in `start_state.ev_limit_soc_percent`; replay serves it for the bound marker and fails loud (`ValueError`) for cycles recorded without it. Tests in `tests/test_recorder_replay.py`. **Pending:** old cycles (e.g. the productive-NAS dump) stay unreplayable — verify with a fresh dump from the NAS (`--intake ... --update-golden`).

- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).


## New Bugs (Do not remove this chapter — even if empty)

Source of the next four items: [issue #50](https://github.com/JochenTCC/Earnie/issues/50) (live feedback, AT, HA backend, Docker image digest = `v2.6.2`; fixed import tariff + spot-indexed export). Findings were checked against `release/2.7` (2.7.0-alpha.9).

- [ ] **Issue #50 / 1 — `settlement_fee_cent_kwh` is silently ignored on `fixed_cent` and `monthly_table` import tariffs:** `data/tariff_pricing.py` applies the fee only in `_spot_import_cent`; the fixed and monthly branches add only the house-profile `netznutzung`. No warning, no schema hint, so a user who sets the fee on a fixed tariff to adjust grid costs sees no effect (same behaviour in 2.6.2 and 2.7). **Decision:** do not honour the fee on these types (a fixed price is already the full supplier work price; a second place for grid costs would add confusion). **Change:** warn when loading a `fixed_cent` / `monthly_table` tariff whose `settlement_fee_cent_kwh` is non-zero, pointing at `netznutzung` in the house profile (`house_config/tariffs_store.py`, `_normalize_dach_fields` area); hide/disable the field for these types in the tariff UI if it is shown there; tests for the warning. Docs: see Document Review Findings below.
- [ ] **Issue #50 / 1b — Check VAT handling of `netznutzung` on tariffs with `prices_include_vat: true`:** `_add_netzentgelt` adds the net grid fee to the work price and `_apply_vat` returns the price unchanged when `prices_include_vat` is true (catalog default for `fixed_cent`). The grid fee is then added without VAT, i.e. ~20 % too low in AT. **Confirmed by reading (2026-10-24):** tests `test_resolve_user_fixed_import_adds_netznutzung_no_extra_vat` and `test_spot_import_netznutzung_arbeitspreis` pin the current behaviour (gross 11.4 + net 5.0 = 16.4 ct instead of 17.4 ct at 20 % VAT) — it looks intended for the supplier price but not for the net grid fee. **Research (2026-10-24):** the Vorarlberger Energienetze price sheet 2026 (`Preisblatt_NNE_2026_NEU.pdf`, from `vorarlbergnetz.at/media/`) states that all listed prices are net prices plus the statutory VAT (currently 20 %); Austrian bill breakdowns also apply 20 % VAT on all components incl. grid fees. So VAT on the grid fee is due in every case. **Implemented (uncommitted, 2026-10-24):** `data/tariff_pricing.py` (`grid_fee_on_tariff_basis`), `simulation/se_invoice_netznutzung.py`, user-fixed import gets the land VAT via `apply_land_vat_to_user_fixed_import` (`house_config/tariffs_store.py`, called from `scenario_resolution.py`), warning for gross import tariffs without `vat_percent`, `share/config/tariffs.example.json` completed, tests adjusted/added; public golden-master regression passes unchanged (private cases not run). Follow-up VAT model: feature item in `Backlog.md` (Version 2.+1). Previously: fix needed (affects most catalog tariffs, which use `prices_include_vat: true`; golden-master regression expected to change). Recompute with a numeric example (fixed 12 ct incl. VAT + 9.08 ct net grid fee) against `docs/konfiguration/preise.md` ("Eigener Festpreis ... Netznutzung wird weiterhin addiert"), then fix in `data/tariff_pricing.py` (apply `vat_percent` to the grid fee when the tariff price is gross) and add regression tests for `fixed_cent`, `monthly_table` and `__user_fixed__`. The reporter's own setup (net prices, factor 1.2) is not affected. May change computed import prices → check golden-master regression cases (`scripts.run_regression`) before `--update-golden`.
- [ ] **Issue #50 / 2 — Origin of a grid fee of 12.0 ct/kWh unexplained:** reporter saw an import price of 28.8 ct instead of ~25.3 ct, caused by `netznutzung_arbeitspreis_cent_kwh = 12.0`. In `v2.6.2` and `release/2.7` the code default is 0 (`house_config/profiles_store.py`, `data/grid_fees.py`), the public seed has no such value. **Next:** ask the reporter where the 12.0 in `house_profiles.json` came from (manual entry, import, Hauskonfigurator). Fix only if a code path producing 12.0 is found. Optional UI hint that 0 means "no grid costs applied" (not decided).
- [ ] **Issue #50 / 4 — "Zwangsladen nicht ausgeführt" (deviation S3, `battery_power_below_tolerance`) possibly a false positive:** there is no confirmation timeout; the icon is a post-hoc Soll/Ist check per 15-min slot (`optimizer/deviation_eval.py`). Slot-mean sampling is already in 2.6.2 (since 2.5.3; HA energy counters since 2.6.c), so a single-sample extrapolation is not the default cause. Candidates: (a) `closed_interval.sample_count` < 3 (`MIN_SAMPLE_COUNT_FOR_MEAN`, e.g. after a daemon restart) → `runtime_store/slot_ist_powers.py` falls back to the decision-time snapshot taken before the inverter ramps up; (b) battery power sign convention of the HA sensor (rule expects negative = charging). **Next:** collect from the reporter 2-3 affected `optimization_history.jsonl` entries (`mode`, `target_power_kw`, `consumption_snapshot.battery_kw`, `closed_interval.sample_count` / `battery_kw`), the sensor sign and whether the daemon restarted in those slots. Decision so far: do **not** harden the sampler state across restarts (restarts are rare; the warning can be ignored). Revisit only if the data shows (b) or a systematic (a).

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue
- [ ] **Issue #50 / 3 — "Jetzt neu berechnen" button on the Optimierer-Dienst page:** config changes only take effect at the next quarter-hour cycle (`main.py` reloads config per cycle), a daemon restart does not speed this up. Add a button that sends the existing Request-Optimize POST (`/ehal/loxone/request_optimize`, daemon port from `config.get_ehal_http_port()`) to the local daemon. Enabled only while the daemon runs **and** a plan-input file (`config`, `tariffs`, `house_profiles`, `backtesting_scenarios`, `components`, `grid_fees`) is newer than `completed_at` of the last run. No hint on every config change; describe the quarter-hour cycle and the button in the user manual instead. Draft (uncommitted, untested): `runtime_store/optimize_request.py`, `ui/pages/page_daemon.py`; tests still to write (mtime logic, HTTP failure).


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **Issue #50 / 1 — `settlement_fee_cent_kwh` description misleads:** `docs/konfiguration/preise.md` (field table) and `docs/referenz/tarife-quellen.md` call it "Fixer Aufschlag Netz/Gebühren" without saying it applies to spot types only. State: supplier surcharge on the exchange price, spot types only, no effect on `fixed_cent` / `monthly_table`; grid costs belong to `netznutzung` in the house profile and apply to all import types (0 = off). The 2.6.2 docs carry the same misleading wording (no backport planned). Draft already in the working tree for `preise.md`; `tarife-quellen.md` still open.
- [ ] **Issue #50 / 3 — User manual:** section "Optimierer-Dienst" in `docs/user-manual/Benutzer-Handbuch-Earnie.md` should explain the quarter-hour cycle, that config changes act from the next run, and the "Jetzt neu berechnen" button (draft text already in the working tree).
