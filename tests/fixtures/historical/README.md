# Historische cons_data für Integrationstests

Isolierte Kopie von `runtime/cons_data.csv` (≥12 Monate), damit Tests
unabhängig von der laufenden Runtime-Datei sind.

## Preise (offline)

[`tests/test_historical_24h_consistency.py`](../../test_historical_24h_consistency.py)
lädt Marktpreise über die Backtesting-Fixture-Config
(`tests/fixtures/backtesting/config.json`): `price_source=csv` →
`tests/fixtures/backtesting/prices.csv` (Energy-Charts-CSV-Form, synthetisch,
ohne Netzwerk). Kein Energy-Charts-/aWATTar-Abruf in pre-commit.

## MILP-Matrix

- **Katalog-Check:** weiterhin ~12 Monate × high/low PV (≥20 Fälle) — prüft nur
  die Fixture-Abdeckung.
- **CBC-Läufe:** nur die letzten **2** Kalendermonate (≈4 Fälle), damit die
  Suite unter pre-commit robust bleibt.

## Regenerieren

```bash
python -m scripts.generate_cons_data --source loxone
python -m scripts.extract_historical_fixtures
```

Verwendet von `test_historical_24h_consistency.py` (`@requires_historical_data`).
Wenn `prices.csv` den neuen `cons_data`-Zeitraum nicht mehr abdeckt, die
synthetische Preis-CSV entsprechend erweitern (gleiche Spalten wie Energy-Charts-
Export: `Datum (MEZ)`, `Day Ahead Auktion (DE-LU)`, Zeile 2 = Einheiten).
