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

- [ ] **2.7.h — productive Earnie dogfood** (code archived in Erledigt; not yet verified live)
  - Physical `role: standby_backup` + `set_ess_source_select` (EcoFlow Delta 3 / Loxone Merker `Earnie_Speicher_Quellenwahl` → HA `switch.*_grid_bypass`): price-driven grid vs battery island flips, reserve sizing, charge in cheap slots
  - After successful live check: remove this item; add **Verified live** note on the **2.7.h** Erledigt entry

- [ ] **Physical powerstation ESS writes fall back to the house battery's plant-flat entity** — fix implemented (2026-10-06); live acceptance pending before **2.7.h** dogfood with limits
  - `optimizer/powerstation_live.py`: no plant-flat remap for charge/discharge (HA + Loxone); explicit exception only for `set_ess_source_select` (EcoFlow bridge); missing binding → skip + `runtime/ehal_write_error.json`
  - Docs: `docs/konfiguration/batterie-pv.md`; regression: `tests/test_powerstation_2_7_h.py` (`test_ha_charge_does_not_remap_to_house_battery`, Loxone charge isolation, HA source_select plant-flat)

- [ ] **Loxone `status.json`: physical powerstation limits overwrote the house battery's flat keys** — fix implemented on branch `fix/status-json-powerstation-keys`; live acceptance pending
  - Cause: `_write_powerstation_loxone` cached sent values under the flat field kind (`set_ess_charge_power_limit`, `set_ess_mode`, …) and `build_loxone_status_payload` wrote them into the house battery's flat keys; with two powerstations the last write won. Only the Virtual HTTP Input mirror was affected, not direct `/dev/sps/io/` writes. The per-battery `ess.<id>.*` check keys of a VI never received data.
  - Fix: `optimizer/powerstation_live.py` caches under the Pattern B key `ess.<id>.<kind>` (`_status_key`); only the shared EcoFlow-bridge `set_ess_source_select` stays flat. `integrations/loxone_status_json.py` emits Pattern B keys and no longer touches the flat limit / mode keys.
  - Tests: `tests/test_loxone_status_json.py` (house keys untouched, two powerstations, shared Quellenwahl flat, write path end to end); `tests/test_powerstation_2_7_h.py` adjusted. Four of them fail without the fix.
  - **Note:** after the fix the VI commands `Earnie_Delta3_*` receive mirror values for the first time. A VI scale with `DestValHigh="-100"` inverts the sign of such a mirrored value; check the scaling before rollout.
  - After a successful live check: remove this item → `Backlog-Erledigt.md`.

- [ ] **Loxone: silent `loxone_sent` omitted physical powerstation setpoints** — fix implemented (2026-10-09); live acceptance pending
  - Loud `loxone_writes` merge was already done (Erledigt 2026-10-07). Remaining gap: Silent Live-Schreiben / watchdog Soll from `loxone_sent`.
  - Fix: `planned_powerstation_loxone_sent` in `optimizer/powerstation_live.py` (Merker → wire, no publish); `main.py` merges into `loxone_sent` after `build_sent_loxone_snapshot`. Does not update `_last_powerstation_sent` in silent.
  - Tests: `tests/test_powerstation_2_7_h.py`, `tests/test_main_loxone_writes.py`, `tests/test_loxone_debug.py`.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Don't show "main.py nicht aktiv" on Monitor page while main.py is running and currently optimizing

- [ ] 2026-10-06 05:37:40 [WARNING] (main:199) - SoC-Lesung korrigiert: Miniserver 11.0% → 100.0% (Integration aus 100.0%, Batterie 0.52 kW).  --> Why this?
- [ ] 2026-10-08 07:07:14 [WARNING] (data.outdoor_forecast:209) - Außentemperatur-Prognose fehlgeschlagen (503 Server Error: Service Unavailable for url: https://api.open-meteo.com/v1/forecast?latitude=47.40409024399311&longitude=9.742743769241422&hourly=temperature_2m&forecast_days=3&timezone=auto) – konstante Fallback-Temperatur 14.10 °C  --> This warning is quite often - please check

- [ ] EcoFlow Delta 3 bridge: Miniserver self-write of a Virtual Input is overwritten by HA (2026-10-07, not analysed yet)
  - Setup: the Miniserver writes its own Virtual Input via a Virtual Output command (`/dev/sps/io/<Input>/\v`, device = the Miniserver itself), e.g. bypass state (`Delta3_Grid_ByPass`) and charge limit (`Delta3_P_ChargeLimit`). HA mirrors these inputs through the Loxone integration (PyLoxone) and drives the EcoFlow entities from automations (`docs/einrichtung/ecoflow-delta3-loxone.md`, steps 5/6).
  - Symptom: in between, the input value changes to a different value that the Miniserver logic did not write; HA seems to set it. Which writer and when is unknown.
  - To check: (1) does an HA `rest_command` (SoC / power / SOC min/max pushes) target the same input name, or does a name collision exist between inputs; (2) does the HA start trigger or a state-trigger automation push a value back into an input; (3) does the Virtual Output command repeat or fire on every cycle (Repeat setting); (4) does the Loxone integration write entity states back to the Miniserver; (5) compare timestamps of the HA log (`rest_command`) with the Miniserver's online monitor.
  - Fix idea if confirmed: let HA only read these inputs (no `rest_command` to them) or switch the bridge to the webhook variant (step 5/6, variant B). Update the guide's "Hinweis zum Eingang" once the cause is known.


## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
