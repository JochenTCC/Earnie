# Produktiv-Dump-Archiv (Regressionstests)

Versionierte Snapshots von NAS-`runtime/`-Dumps, in denen ein Fehler aufgefallen ist.

## Workflow

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

## Struktur je Fall

```
tests/fixtures/prod_dumps/<fall-id>/
  manifest.json              # Metadaten, Symptom, erwartete Regression-Checks
  optimization_history.jsonl
  flexible_consumers_state.json
  optimizer_run_state.json   # optional
```

Große Dateien (`cons_data_hourly.csv`, `energy_optimizer.log`) werden nicht versioniert;
sie bleiben im lokalen `runtime-prod/`-Zip zur manuellen Analyse.

## manifest.json

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
