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

- [ ] **Recorder replay fails offline for installations with an EV `get_evcs_limit_soc` binding:** fixed on `main` (`5aa2ff23`, `56c5ea6d`; no version bump) in `runtime_store/cycle_recorder.py` + `runtime_store/recorder_replay.py`: the recorder now stores the resolved limit SoC per EV in `start_state.ev_limit_soc_percent`; replay serves it for the bound marker and fails loud (`ValueError`) at the actual marker read for cycles recorded without it (golden regression cases that bind the marker but never read it stay replayable). Tests in `tests/test_recorder_replay.py`. **Pending (prod acceptance):** cycles recorded before the fix (e.g. the productive-NAS dump of 2026-10-22) stay unreplayable; verify with a fresh dump from a NAS running this build (`--intake ... --update-golden`), then move to `Backlog-Erledigt.md`.

- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).

- [ ] **Issue #50 / [#61](https://github.com/JochenTCC/Earnie/issues/61) — Migration wizard: PV systems all on `wr_main`, no restart hint (reporter mail 2026-10-24):** (a) PV: `dm4.inverters` (`house_config/migrate_inverters.py`) puts every `pv_systems` entry without `inverter_id` on `wr_main` (confirmed); the migration cannot know the wiring, so the report now gets a manual to-do naming the affected systems and pointing at Hauskonfigurator > Wechselrichter / PV-Felder (`runtime_store/migration/steps/inverters.py`; tests in `tests/test_migration_registry.py`). No question: it would have to ask per system for an inverter that does not exist yet. (b) `main.py` after the migration - **reproduced and fixed (live run 2026-10-24, isolated pack + Streamlit + browser):** `app.py` rendered the migration report only while `_migration_mode` was true; after a successful run the plan is empty, so the app jumped straight to the Monitor and the report page (backup, applied steps, manual to-dos, daemon state, "Weiter zur App" -> auto start) was never shown. The daemon was then started by nobody, which matches the reporter's dead EHAL port, and he never saw the to-dos either. Fixes (no version bump): `app.py` keeps the report on screen while the session phase is `report` (`ui/pages/page_config_migration.py::report_pending`, AppTest red before); with `EARNIE_AUTO_START_MAIN=1` the daemon starts right after a successful run (`_start_daemon_after_migration`, decision 2026-10-24) and the report shows PID / already running / auto start off / the start error; a failed start no longer ends in an exception. The PV to-do of (a) is produced by `dm4.v3_to_v4` as well, because the 2.6 path assigns the PV systems inside that step (it was missing from the first version; found in the same live run). Tests: `tests/apptest/test_page_config_migration_apptest.py`, `tests/test_migration_registry.py`; `docs/einrichtung/betrieb.md`. **Verified live (isolated pack, EHAL port 18541, offline):** wizard shows the PV to-do, report page appears after the run with backup, steps, to-dos and the daemon line; with auto start on `main.py` ran (PID, listener on 18541, heartbeat, `runtime/main_stdio.log`), with it off the report says so. **Pending:** run in the reporter's container (is `EARNIE_AUTO_START_MAIN` set there?) with a real 2.6 install.



## New Bugs (Do not remove this chapter — even if empty)



Source of the next four items: [issue #50](https://github.com/JochenTCC/Earnie/issues/50) (live feedback, AT, HA backend, Docker image digest = `v2.6.2`; fixed import tariff + spot-indexed export). Findings were checked against `release/2.7` (2.7.0-alpha.9).

- [ ] **Issue #50 / 4 ([#57](https://github.com/JochenTCC/Earnie/issues/57)) — "Zwangsladen nicht ausgeführt" (deviation S3, `battery_power_below_tolerance`):** reporter's data (2.6.2, 3 slots, no restart, `the HA battery power sensor` positive while charging, 2.6.2 ran with `ehal.ha.sign: negate`) does **not yet show a sign bug**: `closed_interval` of a log entry at T covers the *previous* slot [T-15, T), so pairing it with that entry's `target_power_kw` (Soll for the *new* slot) is misleading; e.g. 11:47 shows snapshot -1.24 / closed -1.156 for a plan of 1.247 → consistent. **Next:** ask for the `closed_interval` of the *following* entry (T+15 min) for the three slots, plus `sample_count`; the 09:30 row (snapshot -2.49 but closed mean 0.0 over 23 samples) and the 11:32 row (snapshot -0.0 shortly after the slot start) stay unexplained until then. Candidates unchanged: decision-time snapshot fallback (`MIN_SAMPLE_COUNT_FOR_MEAN`), sign handling of the sampler vs. snapshot. Decision so far: do **not** harden the sampler state across restarts. **Mail of the reporter, 2026-10-24: no new data** (the mail does not mention forced charging or the `closed_interval` of the following entries); still waiting for the requested log entries.
- [ ] **Issue #50 / [#58](https://github.com/JochenTCC/Earnie/issues/58) — Forced-charge target stuck at 0.624 kW in many slots:** reporter sees `target_power_kw` exactly 0.624 across many slots and concludes the cap comes from the optimizer, not the inverter. **Next:** ask for the battery entry (max charge power, `conversion`/η, SoC window) from `components.json` / `house_profiles.json` and a few slots; check `optimizer/battery.py` and the MILP charge bounds (SoC headroom, inverter clipping, `battery_max_power_kw` vs. DC/AC conversion) for a limit that yields 0.624 kW. **Mail of the reporter, 2026-10-24: no new data** (battery entry, `conversion`/η and sample slots still requested).
- [ ] **Issue #50 / [#60](https://github.com/JochenTCC/Earnie/issues/60) — HA YAML package: stale export hint, `input_number` targets, no watchdog (reporter mail 2026-10-24):** (a) `ui/ehal_signal_list.py` still says "HA-YAML-Paket folgt mit Binding P5c" although the download exists (`ui/ha_carrier_download.py`, shown in `ui/pages/page_loxone_debug.py` under "HA Push-Carrier"); the reporter used the CLI `python -m scripts.ha_carrier_yaml_gen` instead. Fix the text or point to the download. (b) The generated apply step always uses `number.set_value` (`integrations/ha_carrier_yaml.py`); `input_number` targets need `input_number.set_value` (code confirmed, HA behaviour not reproduced). (c) With Earnie down the last forced setpoint stays; the reporter built a watchdog (`status.json` unreachable > 2 min -> setpoint 0) and suggests it for the package (safety decision first).
- [ ] **Issue #50 — Loxone export: doubled scheme in `Address="http://..."` of the VO/VI XMLs (reporter mail 2026-10-24, unverified, no issue yet):** I found no code that builds the `Address` with a scheme (only `ui/ehal_signal_list.py::_default_host` provides the host), and the quoted text in the mail looks like a Gmail auto-link artifact (`http://` followed by a `google.com/url?q=...` redirect around the private LAN address). **Next:** ask the reporter for the exact `Address` attribute of a generated VI/VO XML (and the value entered in the host field of the export); open an issue only if the doubled scheme is real.


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue
- [ ] **Issue #50 — tariff preview shows "Abwicklungsgebühr" for fixed tariffs:** `_append_fee_vat_fields` in `data/tariff_parameter_preview.py` lists `settlement_fee_cent_kwh` for every type; hide it for `fixed_cent` / `monthly_table` (the field has no effect there, see the load warning).
- [ ] **Issue #50 — optional hint "0 = no grid costs" in the house profile (Netznutzung):** a grid fee of 0 silently means that no volumetric grid costs are applied. Not decided; add a short caption in the Hauskonfigurator if wanted.
- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`. Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) and the EU feature pause after an unreachable host (#59).


## Document Review Findings (Do not remove this chapter — even if empty)

