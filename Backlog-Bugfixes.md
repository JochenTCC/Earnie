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

- [ ] Swimspa Filter: Ernie plant unnötig/teure Zusatz-Slots, weil natives Fenster nicht angerechnet wurde (Dump `chart_debug_20260708_083554`) — Fix v1.21.3: `ernie_filter_remaining_kwh` / `adjust_targets_for_native_filter` in Live-`remaining` und Chart-`simulate_horizon` - **Fehler ist noch nicht behoben** (siehe "C:\Users\joche\Documents\Smarthome\Python\Energy-Optimizer-fix\chart_debug_review\chart_debug_20260708_114712.zip" - inkl. Screenshot)
- [ ] Ähnlich zu Bugfix Chart 1 SoC laufende Stunde (2026-07-08). Im Zeitbereich in der aktuellen Stunde vor "Jetzt" wird der SOC evtl. auch fälschlicherweise als konstant angezeigt. Das ist zu prüfen.
- [ ] Der Verlauf des SOC - BL-Ziel ragt eine Viertelstunde zu weit in den grauen Bereich hinein


## Bugfix Verifications Pending
- [ ] **Chart 1 SwimSpa-Ist (Gesamtzähler Fall B)** — Fix v1.22.3: `resolve_flexible_consumers_live_power` mit Filter-Inferenz (natives Fenster + Gesamtzähler ≈ 0,18 kW), `flex_measured_ids` + Chart ohne MILP-Fallback; SwimSpa-Spalte = Rest (Heizung + Allgemein). Dump-Referenz `chart_debug_20260707_213204`. Prod-Abnahme: natives Fenster 10–14 → Filter ~0,18 / SwimSpa ~0; Abends Heizung variabel; kein Soll-Leak.
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