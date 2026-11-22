# Scenario editor — usability proposal

Status: **A–D implemented 2026-11-22** (before the beta); E and drag and drop open. Mockup: artboard "Szenarienkonfigurator – Vorschlag" on the canvas "Hausprofil Neuordnung" (claude.ai artifact, private to the maintainer). Companion of `docs/dev/house-profile-layout.md` (same expander pattern).

Scope: `ui/pages/page_scenario_editor.py` and `ui/pages/scenario_editor_{session,form,sections,tariffs}.py`, plus the read-only scenario list in the Scenario Explorer (`ui/backtesting.py::render_configured_scenarios`).

## 1. Problems today

1. **Explorer activation is per scenario, inside the form.** The checkbox "Aktiv für Szenario-Explorer" (`_render_scenario_identity_fields`) is only reachable after selecting a scenario. Toggling five scenarios means five selections, five auto-saves, five reruns. The scenario radio does not show which scenarios are active. The Explorer lists active scenarios as plain text and points back to the editor.
2. **Reordering is one step per click.** `_render_scenario_reorder_controls` offers ↑ / ↓ for the selected scenario only; every click writes the file and reruns. Moving from position 8 to 2 takes six clicks.
3. **"— neu —" silently clones** the last viewed scenario (`new_scenario_template`, `_SESSION_TEMPLATE_SOURCE_KEY`, label "… copy"). The source is not shown; selecting the wrong scenario first produces a copy of the wrong one.
4. **The list carries no information.** Live / active / missing references / house profile / tariffs are visible only after selecting a scenario.
5. **The form is unstructured:** components, tariff filters, tariffs, previews, tariff links, next-month rates and the import cap follow each other without grouping.
6. **"Szenario entfernen" deletes without confirmation.**

## 2. Proposal

### A. Overview table above the form (largest gain)

One row per scenario, in file order: Position · Bezeichnung (click = open in the form) · **Aktiv im Explorer (editable checkbox)** · Hausprofil · Bezugstarif · Einspeisetarif · Status (Live / OK / Verweis fehlt). Header shows "n von m im Explorer aktiv". Live is pinned to position 1 and always active (as today, `ensure_live_scenario_enabled`).

- The table is the **only writer of `enabled`**. The checkbox leaves the form (it becomes a caption pointing to the table). This avoids two widgets writing the same field: otherwise the form's auto-save could write back the old value after a table toggle.
- A toggle writes `enabled` of that one scenario via `upsert_scenario` (or a dedicated `set_scenario_enabled`), then updates `_SESSION_FILE_STAMP_KEY` and the form baseline (`store_scenario_form_baseline`) for the open scenario, so the open form does not count as dirty and does not overwrite.
- `normalize_scenario_form_snapshot` / `scenario_form_is_dirty` must stop comparing `enabled` once the form no longer renders it.
- Implementation: `st.dataframe` with row selection (`on_select`) for opening, plus `st.data_editor` (or per-row checkboxes) for the activation column. Decide during implementation which gives stable keys; per-row widgets in `st.columns` are the fallback with the least magic.

### B. Reordering

- Editable **position** per row (select 2…n); writes the new order with the existing `reorder_scenarios`. Live stays fixed at 1.
- Keep ↑ / ↓ only if the position select proves awkward.
- Drag and drop needs a third-party component (e.g. `streamlit-sortables`) — **after the beta** (new dependency).

### C. Explicit new / duplicate

- Buttons "„<selected>“ duplizieren" and "Neu (leer)" replace the "— neu —" radio entry.
- Duplicate uses `new_scenario_template(source_id=<selected>)`; empty uses the no-source branch. `_SESSION_TEMPLATE_SOURCE_KEY` is no longer needed for implicit cloning.
- Visible only with the Scenario Explorer UI mode enabled (as `allow_new` today).

### D. Form groups (expanders, same helper as the house profile)

1. **Bezeichnung** (open) — label; Live info; missing-references warning + "Fehlende Verweise entfernen".
2. **Komponenten** (open) — Hausprofil (+ location caption), Batterien, PV-Felder, imported PV option, Heizsystem.
3. **Tarife** (open) — land / type filter, Bezugs- and Einspeisetarif (+ own fixed prices), Edibert preview; nested, collapsed: next-month rates and tariff editor links.
4. **Bezugsgrenze / Leistungspreis** (collapsed, status in title) — cap, margin, live mode.
5. **Szenario entfernen …** with a confirmation step (not for Live).

### E. Explorer (after the beta)

Replace the read-only list in `render_configured_scenarios` with the same activation checkboxes, so the user decides what to compute where the computation starts. A toggle must mark existing Explorer results stale, as the editor's help text already promises.

## 3. Risk and staging

| Item | Risk | Note |
|---|---|---|
| B position select | low | existing `reorder_scenarios` |
| C duplicate / new | low | explicit instead of implicit template source |
| D groups, delete confirmation | low | widget keys unchanged |
| A activation table | medium | single writer for `enabled`; baseline / dirty check must exclude it |
| E activation in Explorer | medium | other page; stale-result handling |
| drag and drop | — | new dependency, after the beta |

**Before the beta:** A (table is the only writer), B, C, D. **After:** E, drag and drop.

## 4. Tests

- AppTest: toggle a non-open scenario in the table → file changes only in that scenario's `enabled`; open form is not dirty, no write-back.
- AppTest: toggle the open scenario → same.
- Position change → `reorder_scenarios` order; Live stays first.
- Duplicate copies the selected scenario's settings; "Neu (leer)" has empty settings.
- Delete requires confirmation; Live has no delete.
- Opening the page and switching scenarios without edits writes nothing (existing `_matches_stored_scenario` guarantee).
- User docs (`docs/konfiguration/`, user manual) updated in the same change.

## 5. Implementation notes (A–D, 2026-11-22)

- **Selection moved into the rows.** The radio `scenario_select` is gone; each row's label is a button (`scenario_open__<id>`, `type="primary"` for the open one) whose callback sets `scenario_editor_request`. `_resolve_scenario_selection` reads the request, keeps the unsaved-edit prompt (`scenario_switch_discard` / `scenario_switch_cancel`) and renders the overview (`ui/pages/scenario_editor_overview.py`, container key `scenario_overview`).
- **Row widgets only queue.** `scenario_active__<id>` and `scenario_pos__<id>` queue their change in `on_change`; `apply_pending_overview_writes` runs at the top of the next run, before the catalogs are read, writes with `set_scenario_enabled` / `reorder_scenarios` and updates the editor's file stamp, so the open form is not reseeded. Both widgets are seeded from the file on every run (a failed write snaps back).
- **`enabled` left the form:** no `scenario_enabled` widget; the save payload takes `enabled` from the scenario as read this run; `normalize_scenario_form_snapshot` no longer carries `enabled`, so a table toggle is never an unsaved edit.
- **New scenario:** „Duplizieren“ / „Neu (leer)“ set the template source (`scenario_editor_template_source`, `__empty__` for empty) and request `— neu —`; the draft is saved on its first render as before and opened.
- **Groups:** Bezeichnung, Komponenten, Tarife (open), Bezugsgrenze / Leistungspreis (collapsed, cap in the title). The next-month rate entry stays visible inside „Tarife“ (it is a time-limited prompt and must not be collapsed).
- **Delete:** „Szenario entfernen …“ → warning with „Entfernen“ (`scenario_delete_confirm_yes`) / „Abbrechen“.
- **Tests:** `tests/apptest/test_scenario_overview_apptest.py`; existing AppTests select through `tests/apptest/helpers.open_scenario`; Playwright smoke (`tests/apptest/e2e/test_smoke.py`) uses the overview container.
