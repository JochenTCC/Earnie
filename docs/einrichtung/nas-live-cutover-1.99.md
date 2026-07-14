# NAS Live-Cutover (1.99 P6b)

**Voraussetzung:** Phasen **1.95–1.97** abgeschlossen, Silent-Stack (`silent-migration-test/`) lokal und auf dem NAS validiert. Implementierungsplan: [`docs/spec/nas-consumer-migration-1.95-1.99.md`](../spec/nas-consumer-migration-1.95-1.99.md).

## Zielzustand (Prod)

- `flexible_consumers: []` in `config.json`
- Kein Block `appliances[]`, kein root `eauto_milp`
- EV-MILP-Parameter nur in `house_profiles.json` (`charging_schedule.milp`)
- Loxone-Bindings auf **bridged** MILP-Einträge (`legacy_id` für cons_data-Kontinuität)

## Ablauf

1. **Legacy-Worker stoppen** auf dem NAS (`docker/earnie/`).
2. **Neuer Stack:** Silent-Modus deaktivieren (`loxone_silent_mode: false` in `local_settings.json` oder Eintrag entfernen); Worker neu starten.
3. **Tägliche Nutzung** auf den neuen Stack umstellen (UI-Port); altes `docker/earnie/` gestoppt lassen (Rollback-Fenster).
4. **Rollback:** neuen Stack stoppen → Legacy-Compose auf `docker/earnie/` starten → UI wieder auf Port 8501.

## Manuelle Abnahme

| Bereich | Prüfpunkt |
|---------|-----------|
| SwimSpa | Heiz-Indikation (`homie_bwa_spa_heating`), Fall-B-Zuordnung im Chart |
| EV | Modus A/B, Preset-Schwellen unverändert vs. Legacy |
| Haus Wärme | MILP-Puls-Timing vs. PWM-Referenz |
| Chart 1 / Sankey | Alle Prod-Flex-Segmente sichtbar (Consumers P1) |
| Geräte | WM/Trockner/GS-Segmente wenn **1.96d** migriert |
| Loxone-Kommunikation | Seite **Echtzeit-Umgebung → Loxone-Kommunikation**: Live-Lesen OK, Schreibvorgänge erfolgreich (nur wenn Silent-Modus aus) — siehe [`docs/ui/loxone-kommunikation.md`](../ui/loxone-kommunikation.md) |

## Release

Nach Abnahme: `version.py` → **`2.0.0`** nur nach expliziter Freigabe (kein automatischer Bump).
