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

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Error in NAS alpha ("P:\earnie-alpha") when starting main.py
  EHAL Schreibfehler: Powerstation ESS fields have no own Merker; refusing plant-flat house-battery fallback: ess.15_kwh_speicher_copy_3.set_ess_charge_power_limit; ess.15_kwh_speicher_copy_3.set_ess_discharge_power_limit (set_ess_charge_power_limit, set_ess_discharge_power_limit)

- [ ] 2026-10-06 05:37:40 [WARNING] (main:199) - SoC-Lesung korrigiert: Miniserver 11.0% → 100.0% (Integration aus 100.0%, Batterie 0.52 kW).  --> Why this?

- [ ] Loxone mapping: duplicate `PLANT_FIELDS` — heuristic proposals miss fields
  - `ui/ehal_loxone_mapping_ui.py:52` holds an older copy of `PLANT_FIELDS`; the current one is in `ui/ehal_loxone_mapping.py:56` (cleaned up in 2.7.m: `_PLANT_ESS_MOVED` removed from the list, `set_ess_source_select` and `set_grid_export_power_limit` added).
  - The copy still contains the ESS fields and filters setpoints with `startswith("set_ess_")`, so `set_grid_export_power_limit` is missing. It feeds only `_run_structure_scan` → `heuristic_propose` (name proposals after the HTTP probe).
  - Effect 1: `set_grid_export_power_limit` never gets a proposal although `_HINTS` has entries for it (`integrations/loxone_ehal_mapping.py:134`).
  - Effect 2 (found by reading; confirm with a test before the fix): proposals are keyed by flat field name (`sens_ess_soc`), battery rows look up `ess.<id>.<kind>` (`proposals.get(field)` in `_render_field_selects`, `ui/ehal_loxone_mapping.py:707`), so battery rows probably never get a proposal.
  - Fix sketch: delete the copy and use the list from `ui/ehal_loxone_mapping.py`; test that every mapping field is also in the proposal field list; map `ess.<id>.<kind>` → `<kind>` for proposals. Check the HA side for the same error (`ui/ehal_ha_mapping.py`, `_proposed_entity_id`; `heuristic_propose(scanned)` returns flat keys while battery rows use Pattern B).

- [ ] Loxone: physical powerstation writes are not part of the write trace
  - `_write_powerstation_loxone` discards the result of `_send_loxone_value_traced`; `main.py` puts only `huawei_writes + flex_writes` into the write records, and `build_sent_loxone_snapshot` knows only plant and consumers. Found by reading, not run: EHAL-Com → Live-Schreiben shows no value/success for `ess.<id>.set_ess_charge_power_limit` of a powerstation; only the log line ("Loxone API: … erfolgreich auf …") shows it.
  - Fix sketch: return the records from `write_physical_powerstation_charges` / `write_standby_source_selects` and append them to `loxone_writes` and the `loxone_sent` snapshot; test via a powerstation fixture.

- [ ] Second battery: missing or wrong SoC binding silently falls back to the primary battery's SoC
  - `ehal_live.read_ess_soc_by_id` → `_read_soc_from_address` returns `None` on a missing binding or read error and the caller substitutes the primary SoC; the only trace is a debug log. A misnamed SoC Merker of a second battery therefore looks plausible in operation.
  - Fix sketch: log a warning once per battery and show the fallback in EHAL-Com (Live-Lesen row status); decide whether a physical powerstation without own SoC should be planned at all.

- [ ] EcoFlow Delta 3 bridge: Miniserver self-write of a Virtual Input is overwritten by HA (2026-10-07, not analysed yet)
  - Setup: the Miniserver writes its own Virtual Input via a Virtual Output command (`/dev/sps/io/<Input>/\v`, device = the Miniserver itself), e.g. bypass state (`Delta3_Grid_ByPass`) and charge limit (`Delta3_P_ChargeLimit`). HA mirrors these inputs through the Loxone integration (PyLoxone) and drives the EcoFlow entities from automations (`docs/einrichtung/ecoflow-delta3-loxone.md`, steps 5/6).
  - Symptom: in between, the input value changes to a different value that the Miniserver logic did not write; HA seems to set it. Which writer and when is unknown.
  - To check: (1) does an HA `rest_command` (SoC / power / SOC min/max pushes) target the same input name, or does a name collision exist between inputs; (2) does the HA start trigger or a state-trigger automation push a value back into an input; (3) does the Virtual Output command repeat or fire on every cycle (Repeat setting); (4) does the Loxone integration write entity states back to the Miniserver; (5) compare timestamps of the HA log (`rest_command`) with the Miniserver's online monitor.
  - Fix idea if confirmed: let HA only read these inputs (no `rest_command` to them) or switch the bridge to the webhook variant (step 5/6, variant B). Update the guide's "Hinweis zum Eingang" once the cause is known.


## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
