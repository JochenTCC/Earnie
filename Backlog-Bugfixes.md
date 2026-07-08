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

## Bug SwimSpa Leistung
- [ ] Chart 2: Kosten und Verbräuche sollten an der Grenze grau | neutral doch verbunden werden. Die Einsparungen werden für den gesamten Bereich SA_0 - SA_2 berechnet und es wird neu angefangen, wenn SA_0 gewechselt wird.
- [ ] SOC Verlauf in der aktuellen Stunde nicht kostant halten, sondern für den Bereich nach "Jetzt" in dieser Stunde extrapolieren  (also maximal von Stunde_Jetzt:15 - Stunde_Jetzt+1:00), so dass KEINE Treppe entsteht

## Bugfix Verifications Pending

Fix implementiert, Live-/Prod-Abnahme ausstehend (siehe **Einordnung** oben).

- [ ] Swimspa Filter: Ernie plant unnötig/teure Zusatz-Slots, weil natives Fenster nicht angerechnet wurde (Dump `chart_debug_20260708_083554`) — Fix v1.21.3: `ernie_filter_remaining_kwh` / `adjust_targets_for_native_filter` in Live-`remaining` und Chart-`simulate_horizon`
- [ ] Im Chart 1 wird offensichtlich der Verbrauch des Swimspa (Heizung) nicht korrekt berechnet / angezeigt. Siehe Dump (`chart_debug_review/chart_debug_20260707_213204.zip`) — Fix v1.21.2: Chart-Ist aus `flex_live_kw`, `homie_bwa_spa_filter1` als `alternate_binary_power_name`
- [ ] Swimspa Leistungen für Heizung und Filter sind im Sankey-Diagramm nicht sauber getrennt — Fix v1.21.2: gleiche Live-Zuordnung + Fall-B-Abzug (mit obigem Punkt verifizieren)

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
