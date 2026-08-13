# Backtesting Offline-Fixtures

Versionierte Mini-Daten für Backtesting-Tests **ohne** lokale `cons_data.csv`.

## Inhalt

| Datei | Zweck |
|-------|--------|
| `cons_data.csv` | Auszug aus Produktiv-Logs (158 Stunden) |
| `config.json` | Minimale Config mit Pfad auf diese CSV |
| `backtesting_scenarios.json` | Ein schnelles 5-kWh-Szenario |

## Testfälle in den Daten

| Tag | Rolle |
|-----|--------|
| `2026-06-25` | Wenig E-Auto (`eauto_kw` ≈ 0) – schneller Smoke-Pfad |
| `2026-06-23` | Hohe E-Auto-Ladung (~16 kWh) – kritischer MILP-Fall |
| `2024-07-04` | Stunden mit Flex > Total – Grundlast-Kantenfall |

## Regenerieren

```bash
python scripts/extract_backtesting_fixtures.py
```

(Nur bei bewusster Aktualisierung der Fixture-Daten aus `runtime/cons_data.csv`.)
