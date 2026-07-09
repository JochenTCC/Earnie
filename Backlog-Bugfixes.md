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

## Bugfix Verifications Pending

- [ ] **E-Auto: urgent-Nebenbedingung entfernt** (2026-07-09)
  - MILP: separate `urgent >= target`-Constraint entfernt; Deadline weiter über `eligible`-Slots bis Fertigstellungszeit
  - Observability bleibt (`role` post-hoc); Parsing für ISO-Deadlines ergänzt
  - Regression: `eauto_urgent_deferred_cheap_hours_2026-06-28`, neu `eauto_urgent_deferred_cheap_hours_2026-07-09`; xfail entfernt
  - **Prod-Abnahme:** nächster Ladezyklus mit Deadline 07:45 — Plan nutzt günstige Nachtstunden (02–04), `urgent_rule_observability.eauto.role == redundant`

## Neue Bugs (Das Kapitel nicht entfernen - auch wenn es leer ist)

## Bugs nach Test von 1.25.0
- [ ] Loxone-Zugangsdaten erst abfragen, wenn Live-Betrieb aktiviert wird und getestet werden soll, ob alle Merker richtig sind (auf später verschieben)


## E-Auto: urgent-Regel, Prod-Dump, PWM
Verknüpfte Themen — gemeinsam priorisieren und abarbeiten.

- [ ] **urgent-Regel Observability-Review** (bis ca. **2026-07-12**, nach Prod-Abnahme)
  - Nebenbedingung entfernt → Auswertung: `urgent_rule_observability` in Log + `optimization_history.jsonl` (`role`: erwartet `redundant`)
  - Akzeptanz: durchgehend `redundant` über mehrere Ladezykklus → Review abschließen, Observability-Logging ggf. vereinfachen
- [ ] **PWM für E-Auto-Laden** — nur für Ströme < A_min; sonst Mindestlademenge pro h (Zähler runterzählen, bei jedem Ladevorgang reset → bei Null fünf Minuten mit Mindest-Strom laden)
