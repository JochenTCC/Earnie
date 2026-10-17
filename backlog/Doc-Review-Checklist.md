# Docs review checklist (since `v2.3.2`)
## Priority 1 — User-facing
- [x] `docs/user-manual/Benutzer-Handbuch-Earnie.md` — large rewrite; main handbook
- [x] `docs/ui/ehal-com.md` — **new** (~290 lines); replaces `docs/ui/loxone-kommunikation.md`
- [x] `docs/referenz/loxone-signale.md` — heavy rewrite; Virtual In/Out assets; **merged** former `loxone-earnie-library.md` (2026-08-06)
- [x] ~~`docs/einrichtung/loxone-earnie-library.md`~~ — merged into `loxone-signale.md`
- [x] `docs/einrichtung/loxberry-plugin.md` — **new**; LoxBerry plugin setup
- [x] `docs/einrichtung/adapter-wahl.md` — **new**; adapter selection
- [x] `docs/einrichtung/ha-evcc.md` — **new**; HA / evcc path
- [x] `docs/einrichtung/openems-lab.md` — **new**; OpenEMS lab path
- [x] `docs/einrichtung/loxone-anbindung.md` — medium rewrite; Loxone connection
- [x] `docs/README.md` — TOC / entry updates
- [x] `README.md` — landing page; logos

## 2.5.0 — QH MILP wording (2026-08-16)
- [x] `README.md` / `docs/README.md` — Daemon + MILP are 15‑min slots (no “hourly MILP”)
- [x] `docs/user-manual/Benutzer-Handbuch-Earnie.md` — Live-Betrieb: Viertelstunden-Slots
- [x] `docs/ui/charts.md` — Chart-1 bar width 15 min across horizon
- [x] `.github/ISSUE_TEMPLATE/bug.yml` — version placeholder `2.5.0`
- [x] `docs/dev/done/swimspa-filter.md` / `docs/dev/done/ui-menu-structure.md` — QH matrix granularity
- [x] `docs/konfiguration/preise.md` — already documents QH plan vs hourly settlement (`settlement_mtu`)
- [x] `docs/konfiguration/batterie-pv.md` — `standby_power_kw` already documented

## 2.6.0 — HA / HouseSim / entity-scoped (2026-09-25)
- [x] `docs/referenz/ehal.md` — entity-scoped truth: HA entity IDs in `plant` / `consumers[].ehal_bindings`; flat `ehal.ha.entities` one-shot migrate+clear (**2.6.g**)
- [x] `docs/einrichtung/ha-evcc.md` — entity-scoped storage + `sens_*` field names; optional energy-counter maps; no refill of `ehal.ha.entities`
- [x] `docs/einrichtung/smarthome-backend-wahl.md` — already entity-scoped for HA/Loxone mapping paths
- [x] `docs/ui/ehal-com.md` — HA Entity → EHAL Mapping + energy counters already on plant bindings; HouseSim note in Schreibtest
- [x] `docs/ui/charts.md` — HA-Energiezähler wording → `plant.ehal_bindings` (was stale `ehal.ha.entities`)
- [x] `docs/dev/ha-lab-setup.md` — HITL / accept table / §4.2 aligned to entity-scoped + `sens_*` keys
- [x] `docs/dev/house-sim.md` — already documents HouseSim S1–S4 vs HA Lab; entity-scoped merge for golden maps
- [x] `share/config/ehal.ha.snippet.json` — drop empty legacy `entities` key (backend + `sign` only)
- [x] `docs/einrichtung/homeassistant-addon.md` — version example → `2.6.0` / `2.6.0-alpha.1`
- [x] `.github/ISSUE_TEMPLATE/bug.yml` — version placeholder `2.6.0`
- [x] Landing `README.md` / `docs/README.md` — EHAL backends already correct; no entity-scoped detail needed at landing depth
- [x] Handbook live-mapping step — already cites `plant.ehal_bindings` / `consumers[].ehal_bindings`

## 2026-09-29 — Doc↔code sync pass (alpha.9)

- [x] `README.md` — PV = forecast.solar + Open-Meteo climate; Optimierer-Dienst shipped (out of Roadmap)
- [x] `docs/einrichtung/container.md` + `docs/DEVELOPER.md` / root `DEVELOPER.md` — `release-publish.yml` + promote vs local tags
- [x] `set_evcs_mode` off/pv/now in `ehal-com.md` §B + `loxone-signals.md`
- [x] `ui/doc_links.py` handbook fragments
- [x] HA live subset wording (`ha-evcc.md`, `ehal-com.md`, `ehal.md`)
- [x] Earnie-Projekt: CLAUDE.md, Entwicklungsplan status, Businessplan MCP, FB Status-Update historical note
- [x] `.github/ISSUE_TEMPLATE/bug.yml` placeholder `2.6.0-alpha.10`

## 2026-09-29 — Doc↔code sync pass (alpha.11)

- [x] `docs/ui/charts.md` + `betriebsmodi.md` — Monitor order Chart 1 → Nav → Sankey → Chart 2
- [x] `docs/user-manual/Benutzer-Handbuch-Earnie.md` — Silent/Loud on Optimierer-Dienst (not „Silent → Live“ under EHAL-Com)
- [x] `docs/dev/done/price-forecast-renewables.md` — green zone = OLS/`forecast` default (Phase 3 done)
- [x] `docs/ui/betriebsmodi.md` — Silent/Loud toggle note under Daemon Control
- [x] `docs/referenz/tarife-quellen.md` — **Eigener Festpreis** / `__user_fixed__`
- [x] `docs/konfiguration/overview.md` — German user-doc language
- [x] `docs/spec/ui-sunset2sunset.md` + `ui-menu-structure.md` — Sankey placement / `page_cockpit`
- [x] `docs/README.md` + `docs/dev/shadow-mode.md` — S1 shipped; S2+S3 → **2.7.f**

## 2026-10-17 — Full doc review before 2.7.0-alpha (check + style edit)

Rules: `.cursor/rules/user-docs-style.mdc`, `german-user-docs.mdc`; agents `docs-editor-de` (Opus 5.5) / `docs-editor-en` (Sonnet 5.5), **one run per document**. Findings → `## Document Review Findings` in `Backlog-Bugfixes.md`.

Status per column: `x` done · `~` partial (truncated read / keyword scan only) · ` ` open. **Check** = content verified against code; **Style** = edited per style rule (EN docs: clarity only).

### Priority 1 — user-facing, alpha-relevant (DE → docs-editor-de)

Check pass 2026-10-17 (parent, todos 1–2): full read vs code; clear fact fixes applied where decision-free. Style still open except handbook / smarthome-backend-wahl / betrieb.

| File | Check | Style |
|---|---|---|
| `docs/user-manual/Benutzer-Handbuch-Earnie.md` | x | x |
| `docs/einrichtung/smarthome-backend-wahl.md` | x | x |
| `docs/einrichtung/betrieb.md` | x | x |
| `docs/README.md` | x | |
| `README.md` (landing) | x | |
| `docs/einrichtung/homeassistant-addon.md` | x | |
| `docs/einrichtung/loxberry-plugin.md` | x | |
| `docs/einrichtung/container.md` | x | |
| `docs/einrichtung/ha-evcc.md` | x | |
| `docs/einrichtung/loxone-anbindung.md` | x | |
| `docs/ui/smarthome-backend.md` | x | |
| `docs/ui/betriebsmodi.md` | x | |
| `docs/ui/charts.md` | x | |
| `docs/konfiguration/speichern-laden.md` | x | |
| `docs/konfiguration/overview.md` | x | |
| `docs/konfiguration/batterie-pv.md` | x | |
| `docs/konfiguration/flexible-verbraucher.md` | x | |
| `docs/konfiguration/preise.md` | x | |
| `docs/referenz/loxone-signals.md` | x | |
| `docs/referenz/streamlit-ports.md` | x | |

### Priority 2 — user-facing, less central (DE → docs-editor-de)

| File | Check | Style |
|---|---|---|
| `docs/konfiguration/verbrauchs-csv.md` | ~ | |
| `docs/konfiguration/waermespeicher-schichtung-teq.md` | ~ | |
| `docs/referenz/abbreviations.md` | ~ | |
| `docs/referenz/tarife-quellen.md` | ~ | |
| `docs/referenz/oemag-referenzmarktwert.md` | ~ | |
| `docs/einrichtung/proxmox-lxc.md` | ~ | |
| `docs/einrichtung/vmware-vctl.md` | ~ | |
| `docs/einrichtung/ecoflow-delta3-loxone.md` (~900 lines) | ~ | |
| `docs/einrichtung/ha-loxone-bridge.md` | x | |
| `docs/einrichtung/openems-lab.md` | x | |
| `docs/einrichtung/greenfield-dev-stack.md` (dev content → move?) | x | |
| `docs/einrichtung/private-env.md` (dev content → move?) | x | |
| `docs/einrichtung/homeassistant-addon-testumgebung.md` (dev content → move?) | x | |

### Priority 1 — English, user-facing or release-relevant (→ docs-editor-en)

| File | Check | Style |
|---|---|---|
| `docs/ui/ehal-com.md` | ~ | |
| `docs/workflow/release-checklist.md` | ~ | |
| `docs/workflow/release-notes-workflow.md` | ~ | |
| `docs/workflow/config-migration.md` | ~ | |
| `docs/workflow/branching-hotfix-playbook.md` | ~ | |
| `docs/referenz/ehal.md` | ~ | |
| `docs/workflow/usage-ping.md` | ~ | |
| `docs/workflow/earnie-points.md` | ~ | |
| `DEVELOPER.md` | ~ | |

### Priority 2 — developer specs and dev docs (→ docs-editor-en; `docs/entwicklung/` is German → docs-editor-de)

| File | Check | Style |
|---|---|---|
| `docs/workflow/regression-suite.md` | ~ | |
| `docs/workflow/hardware-registry-layer-c.md` | ~ | |
| `docs/workflow/tariff-monthly-scan.md` | ~ | |
| `docs/entwicklung/README.md` | ~ | |
| `docs/entwicklung/shadow-betrieb.md` | | |

### Excluded — `docs/dev/` (moved 2026-10-17)

Working notes, drafts and finished epics live in `docs/dev/` and `docs/dev/done/` (index: `docs/dev/README.md`). They are **not** checked or updated in this review or in the quality gate (15 files: 6 open incl. the lab setups HA / OpenEMS, HouseSim and Shadow Mode, 9 done; the duplicate `MIGRATION.md` was merged into `docs/dev/done/MIGRATION.md`).

### Linked from the docs, not yet in scope (decide)

- `CONTRIBUTING.md`, `docker/README.md`, `packaging/homeassistant-addon/README.md`, `packaging/loxberry/README.md`, `tests/fixtures/prod_dumps/README.md`
- Hover help texts in `share/config/*.schema.json` (user-facing via `$schema`)
- Screenshots in `docs/assets/` vs. current UI

