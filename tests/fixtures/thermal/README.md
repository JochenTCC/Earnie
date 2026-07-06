# Thermische CSV-Fixtures

Minimale Loxone-CSV-Zeitreihen für `test_thermal_calibration.py` und `test_thermal_backtest.py`.

| Datei | Rolle |
|-------|--------|
| `SwimSpa_currenttemperature_fixture.csv` | Ist-Temperatur (Abkühlphase) |
| `Aussentemperatur_Einfahrt_fixture.csv` | Außen-/Einfahrt-Temperatur |
| `SwimSpa_Verbrauchszaehler_fixture.csv` | Leistung (Spalte `Leistung`) |

## Regenerieren

```powershell
python -m scripts.generate_thermal_fixtures
```

Die Daten sind synthetisch (72 h Abkühlphase + kurze Heizphase) und dienen der CI-Stabilität ohne produktive Loxone-Logs.
