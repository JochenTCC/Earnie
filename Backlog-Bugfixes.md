# Offene Bugfixes

Erledigte Punkte → [Backlog-Erledigt.md](Backlog-Erledigt.md) (Abschnitte `### Bugfix …` / Regressionen)

Feature-Roadmap → [Backlog.md](Backlog.md)

## Einordnung

**Hier:** Prod-Abweichung, Regression (`xfail`), bekannte Fehlverhalten, Review mit klarem Beheben/Entfernen-Ergebnis.
**Nicht hier:** Neues Verhalten, UX, Modelle, Research — siehe Feature-Backlog in `Backlog.md`.
**Versionierung:** abgeschlossene Bugfixes → nur **PATCH** in `version.py` (kein Minor-Bump).

## Bugfix SwimSpa Leistung
- [ ] Versionsanzeige ganz oben im Sidebar statt im Titel vom Cockpit
- [ ] Im Chart 1 wird offensichtlich der Verbrauch des Swimspa (Heizung) nicht korrekt berechnet / angezeigt. Siehe Dump ("C:\Users\joche\Documents\Smarthome\Python\Energy-Optimizer-fix\chart_debug_review\chart_debug_20260707_213204.zip")
- [ ] Swimspa Leistungen für Heizung und Filter sind im Sankey-Diagramm nicht sauber getrennt
- [ ] Schaltzeiten für Swimspa Filter scheinen nicht kostenoptimal zu sein
- [ ] Chart 2: Kosten und Verbräuche sollten an der Grenze grau | neutral doch verbunden werden. Die Einsparungen werden für den gesamten Bereich SA_0 - SA_2 berechnet und es wird neu angefangen, wenn SA_0 gewechselt wird.
- [ ] SOC Verlauf in der aktuellen Stunde nicht kostant halten, sondern auch für den Bereich vor "Jetzt" extrapolieren

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
