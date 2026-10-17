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

## New Bugs (Do not remove this chapter — even if empty)

- [ ] "debug-dumps\debug_dump_20261015_222809"

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **`homeassistant-addon.md` — internal planning vocabulary:** "Add-on 0.2", "Feature-Stufe 0.2", "M3-Persistenz-Nachweis", "Sprint 2", Dogfood checklist (HAOS-in-VM). Keep, reword for users, or move Dogfood to `docs/dev/`?
- [ ] **`homeassistant-addon.md` image name:** text says add-on starts `ghcr.io/jochentcc/earnie-energy`; published image is `earnie-addon-{arch}` (FROM earnie-energy). Reword?
- [ ] **`homeassistant-addon.md` port 8541:** "nur bei `ehal.backend=loxone`" — also used for `ehal.ha.transport=weg_b`. Clarify?
- [ ] **Alpha compose pin `2.6.1-beta.1`:** matches YAML but latest official is `v2.6.2`. Update compose pins (release process) or soften doc wording?
- [ ] **`ha-evcc.md` optional map fields:** claims Außentemperatur / Flex-/Pool can be stored in UI but do not run in HA live path; `sens_temperature_outside` not in `HA_MAP_FIELDS`. Reword or drop?
- [ ] **`smarthome-backend-wahl.md` HA snippet:** says snippet has `ehal.backend` and `sign` only; file also has `adapter_id`, `transport`, `boolean_invert`. Extend description?
- [ ] **`betriebsmodi.md` Leistungspreis:** "Leistungspreis und netzgebietsspezifische Tabellen fehlen" — per-area Arbeitstarife exist in `grid_fees.json`; only Leistungspreis missing. Reword?
- [ ] **Internal jargon in user docs:** "S-2-Modus", "(v0.8.1)", "Pool C.6", "§C.6", "design-C1" in `betriebsmodi.md` / `charts.md` / `flexible-verbraucher.md` / `loxone-signals.md`. Scrub per `german-user-docs.mdc`?
- [ ] **`betriebsmodi.md` links to `docs/dev/done/ui-sunset2sunset.md`:** keep for power users or drop from user doc?
- [ ] **`speichern-laden.md` stamping claims:** `grid_fees.json` never stamped; pack members stamped before compatibility check; v3→v4 also via `apply_chain` not only wizard. Align wording?
- [ ] **`flexible-verbraucher.md` legacy overlay:** "beim Laden abgelehnt bzw. ignoriert" — overlay still loaded/bridged. Precise wording?
- [ ] **`loxone-signals.md` language:** English under `docs/referenz/` (only `ehal.md` exempt). Translate to German or grant exemption?
- [ ] **`streamlit-ports.md` VS Code launch names** differ from local `.vscode/launch.json`; Shadow 8542/8543 and chart_debug 8502 undocumented. Align?
- [ ] **`docs/README.md` TOC:** `homeassistant-addon-testumgebung.md` missing — add or move file to `docs/dev/`?
- [ ] **`ehal-com.md` backlog IDs:** Q5/Q8/q.D remain; scrub and lower `backlog_id_baseline`?
- [ ] **`ehal-com.md` Write push-only / historical cutover tables:** keep, shorten, or move to `docs/dev/`?
- [ ] **`ehal.md` `sens_pv_production_active` required vs optional asterisk** vs `telemetry.schema.json`; entity-scoped fields vs schema `additionalProperties: false`. Align schema or doc note?
- [ ] **Registry `invalid_sig` for expired entitlement** not mentioned in handbook / Betrieb. Add?
- [ ] **Handbuch → `Entwicklungsplan/Hardware-Registry-Ausstellung.md`:** internal Earnie-Projekt path; remove or replace for end users?
- [ ] **Handbuch first-start nav:** „vor allem Konfiguration und Daemon Control“ vs app opens on **Smarthome-Backend**; Optimierer-Dienst / EHAL-Com gated. Update?
- [ ] **Handbuch Silent/Loud:** claims EHAL-Com shows status while switch is on Optimierer-Dienst — still accurate?
- [ ] **`betrieb.md` Cycle-Recorder / Prod-Dump sections:** developer content in user doc — move to `docs/entwicklung/` or `docs/dev/`?
- [ ] **`betrieb.md` „bis die Tarifverwaltung mit dem Tarif-Editor kommt“:** future promise; reword when Edbert lands?
- [ ] **`betrieb.md` `EARNIE_UI_MODES` „sunset2sunset (Live-Cockpit)“** vs Monitor page name — align?
- [ ] **`docs/README.md` TOC:** Greenfield / OpenEMS-Lab / HA–Loxone Bridge POC still under user Einrichtung — keep or move to Entwickler?
- [ ] **`docs/README.md` „Scope-A-Plugin“** wording — internal?
- [ ] **`loxberry-plugin.md` Go/No-Go table** vs `container.md` (extra MILP row / wording drift). Sync?
- [ ] **`loxberry-plugin.md` parallelbetrieb:** Host-Port alone may not avoid `earnie-productive` name clash.
- [ ] **`container.md` tariff validation command** may check `share/config/tariffs.json` instead of productive `earnie_env/config/tariffs.json`.
- [ ] **`loxone-anbindung.md` Vorzeichen table** still uses old Merker titles (`Earnie_Netzleistung`, …) vs push-only VO/VI naming.
- [ ] **`smarthome-backend.md` „Loxone-Import“ label** vs actual UI caption from greenfield import section.
- [ ] **`betriebsmodi.md` planned features / internal function names** in user doc (calendar-day recalc, Parameter-Anpassung, `build_annual_cost_rows`, …). Scrub or move?
- [ ] **`charts.md` developer test / Flow-Balance / changelog wording** — move to `docs/dev/`?
- [ ] **`preise.md` „Fehlende Zukunftspreise“** still names aWATTar as primary; cascade is ENTSO-E / Energy-Charts first.
- [ ] **`preise.md` heading „Preise & aWATTar“** overstates aWATTar (linked from `doc_links.py`) — rename?
- [ ] **`streamlit-ports.md` audience:** mostly lab/dev rows in user `referenz/` — move to `docs/entwicklung/`?
- [ ] **`ui/ehal_write_test.py` Statusleiste string** — UI copy mentions status bar that does not exist (code, not doc).
- [ ] **`ehal.md` envelope.schema.json `schema_version` const 1** vs wire version 4 — schema debt.
- [ ] **`loxone-signals.md` Flex enable:** binding key `flex.{slug}.set_enable` vs wire check `heatpump|pool|consumer.{slug}.set_enable` — clarify binding vs wire.
- [ ] **Move lab docs out of user TOC?** `greenfield-dev-stack.md`, `openems-lab.md`, `homeassistant-addon-testumgebung.md` (and maybe split `private-env.md`) → `docs/entwicklung/` / `docs/dev/` — contradicts `entwicklung/README.md` vs `docs/README.md`.
- [ ] **`waermespeicher-schichtung-teq.md` „Thermals P3“** internal ID; Entwicklungsplan §3.5 external link.
- [ ] **`verbrauchs-csv.md` Cursor plan link** `energieflussmonitor_hausprofil_blueprint_a` — drop?
- [ ] **`tarife-quellen.md` audit „Stand 2026-07-21“** vs catalog `catalog_as_of` 2026-09-28 — refresh?
- [ ] **`proxmox` bootstrap.sh** creates `config/`/`runtime/` under Earnie dir vs compose `earnie_env/` — code/doc mismatch (script).
- [ ] **`ecoflow-delta3-loxone.md` mapping story:** L37 says do not map mode/power/source_select; Step 7 says map mode/power — which path is current?
- [ ] **`greenfield-dev-stack.md` backlog IDs** (`7g`, `1.26.0 P0`, …) scrub. *(Style pass scrubbed IDs; confirm Live-Pfad parity-test row and double “3.” numbering.)*
- [ ] **`ecoflow-delta3-loxone.md` EHAL-Com path** still says „Loxone Structure → EHAL Mapping“; UI uses Signalliste / HA mapping.
- [ ] **`ecoflow-delta3-loxone.md` step 1:** „vier“ entities vs five-row table; device-name `_` rule for `delta_3`.
- [ ] **`ha-loxone-bridge.md` live-test status** box vs „am Miniserver getestet“ body — reconcile.
- [ ] **`abbreviations.md` language:** English glossary vs German TOC „Abkürzungen“ — translate or exempt?
- [ ] **`abbreviations.md` EHAL-Com row** still mentions backend choice (moved to Smarthome-Backend).
- [ ] **`entwicklung/README.md` Shadow status** (`S2+S3` / `2.7.f` / `2.+1`) — verify vs backlog.


