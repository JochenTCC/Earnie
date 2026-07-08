# Offene Bugs

Erledigte Punkte → [Backlog-Erledigt.md](Backlog-Erledigt.md) (Abschnitte `### Bugfix …` / Regressionen)

Feature-Roadmap → [Backlog.md](Backlog.md)

## Einordnung

**Hier:** Prod-Abweichung, Regression (`xfail`), bekannte Fehlverhalten, Review mit klarem Beheben/Entfernen-Ergebnis.
**Nicht hier:** Neues Verhalten, UX, Modelle, Research — siehe Feature-Backlog in `Backlog.md`.
**Versionierung:** abgeschlossene Bugfixes → nur **PATCH** in `version.py` (kein Minor-Bump).

### `## Bugfix Verifications Pending`

Fix ist **implementiert** (Code + Tests + ggf. PATCH in `version.py`), aber die **Prod-/Live-Abnahme** steht noch aus.

- Punkt aus dem thematischen Bugfix-Kapitel hierher verschieben, sobald der Fix committed ist — **nicht** direkt nach `Backlog-Erledigt.md`.
- Kurz vermerken, was geändert wurde (Commit/Version), falls hilfreich.
- Nach erfolgreicher Verifikation: aus diesem Kapitel entfernen → `Backlog-Erledigt.md` (`### Bugfix …`) mit `- [x]`.
- Schlägt die Verifikation fehl: zurück ins offene Bugfix-Kapitel oder Follow-up formulieren; PATCH ggf. dokumentieren, aber nicht als erledigt archivieren.


## Neue Bugs (Das Kapitel nicht entfernen - auch wenn es leer ist)



## Bugfix Verifications Pending
- [ ] **Sankey + Chart 1 SwimSpa/Filter (Gesamtzähler Fall B)** — Prod-Symptom im **Sankey** (Dump `chart_debug_20260708_114712`, Screenshot `newplot.png`): im nativen Fenster 10–14 Uhr „SwimSpa (live 0,18 kW · Soll 0,00 kW)“ mit Abweichungsfarbe — native Filterleistung (~0,18 kW) am Gesamtzähler, nicht unter „SwimSpa Filter“. Ernie korrekt inaktiv (`Ernie_Swimspa_Filter_Freigabe` = 0, `consumer_remaining_kwh.swimspa_filter` = 0); kein MILP-Zusatz-Soll im Chart. Ursprünglicher Verdacht (unnötige Ernie-Planung, Dump `083554`) durch v1.21.3 (`ernie_filter_remaining_kwh` / `adjust_targets_for_native_filter`) im Chart und ab ~09:30 Live behoben. Fixes **v1.21.2** (Sankey-Live-Zuordnung + Fall-B-Abzug) und **v1.22.3** (Chart-Filter-Inferenz, `flex_measured_ids`) gemeinsam abnehmen: natives Fenster 10–14 → Filter ~0,18 / SwimSpa-Rest ~0; Sankey ohne irreführendes Soll-Ist-Mismatch; Abends Heizung variabel; kein Soll-Leak. Referenz auch `chart_debug_20260707_213204`.

## E-Auto: urgent-Regel, Prod-Dump, PWM
Verknüpfte Themen — gemeinsam priorisieren und abarbeiten.

- [ ] **urgent-Regel auf Notwendigkeit prüfen** (Review bis ca. **2026-07-12**)
  - Auswertung: `urgent_rule_observability` in Log + `optimization_history.jsonl` (`role`: `redundant` / `nachholen` / `nur_urgent_fenster`)
  - Akzeptanz: durchgehend nur `redundant` → Nebenbedingung entfernen; sonst behalten und begründen
- [ ] **Prod-Dump-Regression: urgent-Nebenbedingung infeasible** (Stand 2026-07-03, Commit `a743318`)
  - Fixture: `eauto_urgent_deferred_cheap_hours_2026-06-28` (~7,99 kWh Rest)
  - Live Modus A: MILP mit urgent → **Infeasible**; ohne urgent → **Optimal**
  - `@pytest.mark.xfail` in `tests/test_prod_dump_regression.py` (2 Tests)
  - Nächster Schritt: Live urgent + Modus A prüfen; `xfail` entfernen wenn feasible
- [ ] **PWM für E-Auto-Laden** — nur für Ströme < A_min; sonst Mindestlademenge pro h (Zähler runterzählen, bei jedem Ladevorgang reset → bei Null fünf Minuten mit Mindest-Strom laden)