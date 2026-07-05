# Historische cons_data für Integrationstests

Isolierte Kopie von `runtime/cons_data_hourly.csv` (≥12 Monate), damit Tests
unabhängig von der laufenden Runtime-Datei sind.

## Regenerieren

```bash
python -m scripts.generate_cons_data --source loxone
python -m scripts.extract_historical_fixtures
```

Verwendet von `test_historical_24h_consistency.py` (`@requires_historical_data`).
