# Produktiv-Dump-Archiv (Regressionstests)

Versionierte Snapshots von Produktiv-Fällen, in denen ein Fehler aufgefallen ist.

## Workflow

### A) Unified Debug-Dump aus der UI (empfohlen)

1. Im Live-Cockpit Debug-Dump aktivieren und Typ **Prod** wählen (optional Titel/Symptom).
2. ZIP speichern (`runtime/chart_debug/debug_dump_prod_YYYYMMDD_HHMMSS.zip`).
3. Als Fixture archivieren:

```bash
python scripts/archive_prod_dump.py \
  --id eauto_deadline_missed_2026-06-27 \
  --title "E-Auto nicht voll bis Fertig-Uhrzeit" \
  --symptom "Nur ~6.6 kWh geladen statt 16 kWh bis 09:30" \
  --source runtime/chart_debug/debug_dump_prod_….zip
```

Inputs und Historie kommen aus dem ZIP; CLI-Titel/Symptom überschreiben die Dump-Metadaten.

Vorab prüfen:

```bash
python -m scripts.replay_debug_dump runtime/chart_debug/debug_dump_prod_….zip
```

### B) NAS-Kopie (klassisch)

1. NAS-Daten nach `runtime-prod/` kopieren (bleibt gitignored).
2. Archiv anlegen:

```bash
python scripts/archive_prod_dump.py \
  --id eauto_deadline_missed_2026-06-27 \
  --title "E-Auto nicht voll bis Fertig-Uhrzeit" \
  --symptom "Nur ~6.6 kWh geladen statt 16 kWh bis 09:30" \
  --source runtime-prod/runtime.zip
```

3. Regressionstests laufen automatisch mit `pytest tests/test_prod_dump_regression.py`.

## Struktur je Fall (Fixture-Ordner)

```
tests/fixtures/prod_dumps/<fall-id>/
  manifest.json              # Metadaten, Symptom, erwartete Regression-Checks
  optimization_history.jsonl
  flexible_consumers_state.json
  optimizer_run_state.json   # optional
  inputs/                    # aus Capture-ZIP oder Live-Pfaden
```

Große Dateien (`cons_data_hourly.csv`, `earnie.log`) werden nicht versioniert;
sie bleiben im lokalen Capture-ZIP bzw. `runtime-prod/` zur manuellen Analyse.

## Capture-ZIP (schema v2, dump_type=prod)

```
debug_dump_prod_YYYYMMDD_HHMMSS.zip
  manifest.json
  README.txt
  inputs/…
  runtime/optimization_history.jsonl   # Pflicht
  runtime/*.json                       # optional
```

## Fixture manifest.json

Pflichtfelder: `id`, `title`, `symptom`, `recorded_at`, `app_version`, `files`, `regression`.

`regression` beschreibt messbare Invarianten, die der Code künftig erfüllen muss
(siehe `tests/test_prod_dump_regression.py`).

## Archivierte Fälle

| ID | Kurzbeschreibung |
|----|------------------|
| `eauto_deadline_missed_2026-06-27` | Zu wenig Ladung bis Fertig-Uhrzeit |
| `eauto_urgent_deferred_cheap_hours_2026-06-28` | Laden erst im urgent-Fenster statt zu günstigen Stunden |
| `eauto_urgent_deferred_cheap_hours_2026-07-09` | Laden erst 05–07 Uhr statt günstiger Nacht 02–04 (Deadline 07:45) |
| `eauto_false_complete_2026-06-29` | Session fälschlich voll (Plan-Buchung), Loxone-Sofortladen ohne Ernie-Sollwert |
