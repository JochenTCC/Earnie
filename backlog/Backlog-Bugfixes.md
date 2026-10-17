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

Remaining after Priority-1 DE Check pass (2026-10-17). Fixed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) `### Document Review P1 DE Check …`.

### Needs maintainer decision

- [ ] **`docs/einrichtung/ha-evcc.md` — Home Assistant `weg_b` product status** (2026-10-16 / re-verified 2026-10-17)
  - Code: `ehal.ha.transport=weg_b` already switches live read (push inbox) and write (`status.json`) — Binding P5 YAML comfort package still open.
  - Doc still says lab-only / prod stays `pull`. Choose product wording (supported advanced / default `pull` / lab-only until P5), then sync `docs/ui/ehal-com.md`, `docs/referenz/ehal.md`, `docs/dev/ha-lab-setup.md`, release-notes HA notes.
- [ ] **`docs/ui/betriebsmodi.md:139-145` — internal function names** (`build_annual_cost_rows`, `_jahres_kwh_for_row`) in a user doc — drop (handbook-only) or keep as operator deep-dive?

### Still open (fact / structure; not fixed in P1 Check)

- [ ] **Handbook screenshots** — `docs/user-manual/Benutzer-Handbuch-Earnie.md` ~158 / ~289 / ~409: re-link `docs/assets/` (check UI still matches).
- [ ] **Handbook facts** — `:377` „die Einheit wird ignoriert“ vs unit-conversion registry; `:98` private-repo `Entwicklungsplan/Hardware-Registry-Ausstellung.md` link.
- [ ] **`docs/einrichtung/greenfield-dev-stack.md`** — `loxone_silent_mode` vs bootstrap `silent_mode`; nav predates SB-first onboarding; internal IDs (`1.26.0 P0`, `2.0 P2`, `7g Silent`).
- [ ] **Developer content in user-doc scope** — move to `docs/entwicklung/` / `DEVELOPER.md`, short pointer: `private-env.md`, `greenfield-dev-stack.md`, `homeassistant-addon-testumgebung.md`, `homeassistant-addon.md` Dogfood/M3/Sprint block, `container.md` Image-bauen/buildx/Live-Zyklus-Profiling, `betrieb.md` profiling/recorder/prod-dump, `ha-evcc.md` Compose A2 lab.
- [ ] **Epic IDs remaining** — `Q5`/`Q8` in `docs/ui/ehal-com.md`; `Thermals P3` in `docs/konfiguration/waermespeicher-schichtung-teq.md:143`. Consider extending `test_user_docs_audience.py` for `P\d`/`Q\d`.
- [ ] **Reader address** — impersonal default (`user-docs-style.mdc`); align `homeassistant-addon.md`, `betrieb.md`, `ha-loxone-bridge.md`, `ecoflow-delta3-loxone.md` in Style pass.
- [ ] **Stale developer specs** (`docs/workflow/`, `docs/referenz/ehal.md` — P1 EN Check later)
  - `release-notes-workflow.md`: „DRAFT — not yet implemented“ but scripts/tests exist.
  - `thermal-horizon-simulation.md`: „implemented on branch“ (merged); missing `_year_ambient_for_house_h`.
  - `docs/dev/done/ui-menu-structure.md` / `docs/dev/done/MIGRATION.md`: removed `ui/config_forms.py`.
  - `epic-deploy-user.md`, `hardware-registry-layer-c.md`: `release.yml` → `release-publish.yml`.
  - `docs/entwicklung/README.md`: Shadow backlog IDs wording after 2.7.0.
- [ ] **`docs/einrichtung/smarthome-backend-wahl.md` — style-pilot follow-ups**
  - HA snippet keys vs `share/config/ehal.ha.snippet.json` (`adapter_id`, `ha.transport`, `ha.boolean_invert`).
  - Who writes `ehal.backend` (Auswahl vs Speichern Zugangsdaten) — align with `docs/ui/smarthome-backend.md`.
  - Mention Loxone-Import; „Assistent auf EHAL-Com“ may be outdated; Silent/Loud terms.
- [ ] **`docs/einrichtung/betrieb.md` — style-edit follow-ups**
  - Log table „Review 2026-06“; aWATTar-only troubleshooting vs ENTSO-E/Energy-Charts; Earnie-Points „dauerhaft konstant“ vs `points_v`; Sankey header „Energiefluss (Live)“ vs run status.
