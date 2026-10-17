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

- [ ] This warning pops up quite often:
  2026-10-16 07:44:45 [WARNING] (data.price_forecast_live:322) - Preisprognose: EU-Features nicht ladbar (ValueError, mode=live_forecast) — Spiegelung als Fallback für fehlende Slots.
  Can you find the reason and propose fixing (better than fallback to mirroring)?

## Minor changes (no bugs - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **`docs/einrichtung/ha-evcc.md` (Home Assistant `weg_b` transport) is probably outdated** — to clarify (2026-10-16, found while removing internal backlog IDs from user docs)
  - Current text (line 38): `weg_b` switches the live paths to push and `status.json`, "bisher nur im Labor erprobt" — productive use stays `pull`. Before the ID cleanup the sentence said `weg_b` would only switch the live paths with a later step and `pull` should be used until then; the code already does it (`integrations/ha_push_read.py`, `ehal.ha.transport` in `settings/config_loaders.py`).
  - Maintainer view: the document is not up to date. Open: what is the real status of `weg_b` (productive, supported, still lab-only)? Rewrite the transport paragraph accordingly.
  - Check the same statement in: `docs/ui/ehal-com.md` (lines ~18 and ~291), `docs/spec/ehal.md` § Home Assistant, `docs/spec/ha-lab-setup.md` §9 ("optional after 2.7.r"), `docs/einrichtung/homeassistant-addon.md`, and the HA notes in the 2.7.0-alpha.1 release-notes draft ("Plattformhinweise → Home Assistant").
  - Related open item: Binding P5 "Home Assistant Weg B comfort" in `Backlog.md` (full YAML package pre-filled from bindings).

- [ ] **Pre-2.7.0-alpha doc↔code audit (2026-10-17) — broken links / anchors**
  - `ui/doc_links.py`: in-app help fragments `analyse-verbrauch-kosten` and `gesamtkosten-und-verbrauch-jahres-verbrauch-kwh` do not match the GitHub slugs (`&` / ` -` produce double hyphens: `analyse-verbrauch--kosten`, `gesamtkosten-und--verbrauch-jahres-verbrauch-kwh`) — help links land at page top. Fix fragments or add explicit `<a id>` in the handbook; extend `tests/test_doc_links.py` to verify fragments against headings.
  - `docs/ui/betriebsmodi.md:147` and `docs/ui/charts.md:170` link to handbook `#gesamtkosten-jahres-verbrauch-kwh` — the explicit anchor was removed in b64bc626 (2.4.0).
  - `docs/einrichtung/loxone-anbindung.md:104` → `ehal-com.md#q5--write-push-only-27q-qd` (heading is now "Write push-only").
  - `docs/referenz/loxone-signals.md:166` → `ehal-com.md#loxone-structure--ehal-mapping` (heading no longer exists).
  - Markdown links wrapped in backticks render as code, not links: `smarthome-backend-wahl.md:35-36`, `loxberry-plugin.md:5`, `container.md:9`.
  - `docs/einrichtung/homeassistant-addon.md:7`: "EHAL-HA-Adapter … siehe Loxone-Anbindung" — should point to `ha-evcc.md`.
- [ ] **Handbook lost its screenshots** — `docs/user-manual/Benutzer-Handbuch-Earnie.md` lines ~158, ~289, ~409 only show the alt text ("Hauskonfigurator", "Monatliche Stromkosten", "Earnie Monitor"); the image links were dropped in b64bc626 (2.4.0). Assets still exist under `docs/assets/` (also unused: HA add-on installation screenshots, Sankey, Szenenkonfigurator, …). Re-add images (check they still match the current UI).
- [ ] **Stale facts in user docs**
  - `docs/konfiguration/speichern-laden.md:33-37`: says `earnie_data_model` is `3`, import accepts `1`/`2`, v2→v3 rename helper "noch ausstehend". Code: `CURRENT_DATA_MODEL = 4`, only 4 compatible, 3 migratable via the migration wizard (`runtime_store/data_model.py`, `runtime_store/migration/`); DM 1/2 blocked (as `betrieb.md` says). Rewrite and link `betrieb.md#update-und-migration`.
  - `docs/einrichtung/betrieb.md:291`: "Echtzeit-Umgebung → EHAL-Com" — nav section is **Daemon Control**. Line 22: "Planungs- und Echtzeit-Seiten" (old naming). Line 9: "Liest Loxone" — backend-agnostic now (EHAL).
  - `docs/einrichtung/betrieb.md:326`: internal codename "Tarif-Spur mit Edbert" in a user doc.
  - `docs/einrichtung/greenfield-dev-stack.md:43,159`: `loxone_silent_mode` — bootstrap writes `silent_mode`; line 28/58 nav description predates Smarthome-Backend-first onboarding; many internal IDs (`1.26.0 P0`, `2.0 P2`, `7g Silent`).
  - `docs/einrichtung/homeassistant-addon.md`: options table lacks `usage_ping` (exists in `config.yaml`, mentioned in `betrieb.md`); "nicht Teil von 2.6" / version example `2.6.0-alpha.10` stale for 2.7; "Dogfood-Checkliste", "M3-Persistenz-Nachweis", "Sprint 2" are developer content; uninstall section only mentions `/data`, not `addon_configs`.
  - `docs/einrichtung/container.md:118`: alpha compose image "aktuell 2.6.0-alpha.12" — files pin `2.6.1-beta.1` (also a release-checklist step for 2.7.0-alpha); line 168 "Backlog 2.0 P6"; line 226 2.0 log rename note obsolete.
  - `docs/einrichtung/loxone-anbindung.md`: tables still talk about "Merker" read/write and list ESS setpoints as `plant.ehal_bindings.set_ess_*` although line 62 says ESS bindings are entity-scoped `ess.{slug}.*` on `batteries[]`; "Loxone-Merker sind sticky" wording vs. push/`status.json`.
  - `docs/user-manual/Benutzer-Handbuch-Earnie.md:377`: "die Einheit wird ignoriert" — check against `ehal-unit-conversion` (Loxone role blocks / HA `ha_units`); line 98 points users to a private-repo file (`Entwicklungsplan/Hardware-Registry-Ausstellung.md`).
  - `docs/ui/smarthome-backend.md:21`: links `backlog/SB-Identification-Draft.md` and labels a spec "Entwicklungsplan" in a user doc.
  - `docs/ui/betriebsmodi.md:139-145`: internal function names (`build_annual_cost_rows`, `_jahres_kwh_for_row`) in a user doc; line 36 spec version "(v0.8.1)".
  - `docs/konfiguration/flexible-verbraucher.md:220`: "Live-Abfrage und Adaption der Nennleistung folgen in einer späteren Version" — verify (live `sens_power_act` is used for reserve release).
  - `docs/ui/charts.md:156`, `docs/ui/betriebsmodi.md:95`: Sankey flex nodes / EV SoC label "heute nur Loxone" — verify for HA.
  - `README.md`: Roadmap "2.6 / 2.7" stale for 2.7.0; HA add-on missing in "Betrieb" and the installation table.
- [ ] **Developer content in the user-doc scope** (`german-user-docs.mdc`) — move to `docs/entwicklung/` or `DEVELOPER.md`, keep a short pointer: `einrichtung/private-env.md` (maintainer's private repos, regression intake), `einrichtung/greenfield-dev-stack.md`, `einrichtung/homeassistant-addon-testumgebung.md`, `container.md` §§ "Image bauen und deployen", buildx, "Live-Zyklus-Profiling (NAS-Einmal-Test)", `betrieb.md` §§ "Live-Zyklus-Profiling", "Cycle-Recorder (Regression R-Rec)", "Prod-Dump als Regression-Fixture"; `ha-evcc.md` § "Compose starten (A2)" (HA lab stack).
- [ ] **Epic phase IDs still in user docs** although `german-user-docs.mdc` forbids them (`P5`/`Q8` style is not caught by `tests/test_user_docs_audience.py`, `backlog_id_baseline` is empty): `Q5`/`Q8` in `loxone-anbindung.md`, `referenz/loxone-signals.md`, `ui/ehal-com.md`; `P4` in `loxone-signals.md:182`; `Topology P2` (`batterie-pv.md:104`), `Thermals P2/P3` (`flexible-verbraucher.md:85`, `waermespeicher-schichtung-teq.md:143`). Remove and consider extending the test regex.
- [ ] **Inconsistent reader address in user docs** — handbook and most pages use "Sie"; `homeassistant-addon.md`, `betrieb.md` (migration section) use "du"; `betrieb.md:14`, `ha-loxone-bridge.md`, `ecoflow-delta3-loxone.md` use "ihr/eure". Decide one form and align (part of the style edit).
- [ ] **Stale developer specs** (`docs/spec/`)
  - `release-notes-workflow.md`: header says "DRAFT — not yet implemented" — scripts `release_notes_collect` / `release_notes_finalize`, `audience.toml` and tests exist.
  - `thermal-horizon-simulation.md`: "implemented on branch" — merged via PR #37 (2.7.0-dev.57); line 22 references `optimizer/thermal_live_store._year_ambient_for_house_h`, which no longer exists.
  - `ui-menu-structure.md:6,83`, `MIGRATION.md`: reference removed `ui/config_forms.py` (historical docs — mark or leave).
  - `epic-deploy-user.md`, `hardware-registry-layer-c.md:93`: `.github/workflows/release.yml` — workflow is `release-publish.yml`.
  - `docs/entwicklung/README.md`: Shadow line still carries backlog IDs (`2.7.f`, `2.+1`) — fine for dev docs, but check wording after 2.7.0.
