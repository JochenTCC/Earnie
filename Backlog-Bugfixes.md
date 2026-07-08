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


## Bug Ersparnis Manuelle Geräte

- [ ] Ersparnis numerische Werte haben falsches Vorzeichen: Gespartes Geld IMMER mit Minus ausgeben.
- [ ] Nennleistung immer editierbar machen. Adaptierter Wert gilt bis auf weiteres nur als Hinweis

## Neue Bugs (Das Kapitel nicht entfernen - auch wenn es leer ist)

- [ ] Im Chart 1 wird offensichtlich der Verbrauch des Swimspa (Heizung) nicht korrekt berechnet / angezeigt. Siehe Dump (`chart_debug_review/chart_debug_20260707_213204.zip`) — Fix v1.21.2: Chart-Ist aus `flex_live_kw`, `homie_bwa_spa_filter1` als `alternate_binary_power_name` Fix implementiert, Live-/Prod-Abnahme nicht bestanden (siehe **Einordnung** oben).  - **Fehler ist noch nicht korrekt behoben**
- [ ] Swimspa Filter: Ernie plant unnötig/teure Zusatz-Slots, weil natives Fenster nicht angerechnet wurde (Dump `chart_debug_20260708_083554`) — Fix v1.21.3: `ernie_filter_remaining_kwh` / `adjust_targets_for_native_filter` in Live-`remaining` und Chart-`simulate_horizon` - **Fehler ist noch nicht behoben** (siehe "C:\Users\joche\Documents\Smarthome\Python\Energy-Optimizer-fix\chart_debug_review\chart_debug_20260708_114712.zip" - inkl. Screenshot)
- [ ] Ähnlich zu Bugfix Chart 1 SoC laufende Stunde (2026-07-08). Im Zeitbereich in der aktuellen Stunde vor "Jetzt" wird der SOC evtl. auch fälschlicherweise als konstant angezeigt. Das ist zu prüfen.
- [ ] Der Verlauf des SOC - BL-Ziel ragt eine Viertelstunde zu weit in den grauen Bereich hinein


## Bugfix Verifications Pending
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