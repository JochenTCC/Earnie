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

### UI-Bugs 1.23.1
- [ ] Wenn mehrere manuelle Verbraucher im Chart 1 (aktuelle Ansicht) aktiv sind, dann mit unterschiedlichen Schraffuren ausstatten. Machbarkeit prüfen.
- [ ] Ranking-Tabelle für manuelle Verbraucher möglichst kompakt halten, damit sie auf Mobilgeräten auch als Tabelle angezeigt werden kann (derzeit wird das Design komplett aufgelöst)
  - Checkbox direkt vor Uhrzeit
  - Möglichst kleine Breiten der einzelnen Spalten
  - Kostenspalte weglassen
  - Überschrift "Delta zu bestem Zeitpunkt" einkürzen in "Delta"
- Klappbare Legenden sind nur dann sinnvoll, wenn der Platz für die Legende im Chart selbst nicht leer bleibt (Motivation dafür ist, die Anzeige möglichst kompakt zu halten). Prüfen, ob Legendenplatz eingespaart werden kann. Ansonsten alte Lösung wieder herstellen.
- [ ] Änderung der Nennleistung bei man. Verbrauchern (direktes Eingeben) wird nicht in Optimierung übernommen, wenn schon ein Check gesetzt wurde. Feld für Nennleistung un Dauer deaktivieren bei gesetztem Check
- [ ] SOC-BL-Ziel hat ähnliche Fehler, wie SOC-Verlaub an den Grenzen zu grauem (da fällt es nicht auf) und grünem Bereich. 
- [ ] Preiskurve: Beim Übergang in grünen Bereich (bei grau auch?) fehlt der senkrechte Strich, damit der Verlauf nicht unterbrochen ist

## Bugfix Verifications Pending
- [ ] **Mobile Legende Cockpit (Chart 1/2)** — Plotly-Legende unter 768px per CSS aus; farbiges `<details>` als Ersatz (nur mobil sichtbar). Desktop: nur Plotly-Legende, kein Expander (`ui/chart_legend_mobile.py`).
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