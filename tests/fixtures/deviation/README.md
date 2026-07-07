# Soll/Ist-Szenarien (Epic Soll-Ist)

Acceptance-Katalog für Abweichungsregeln in Chart 1. Vollständige Spec: [docs/spec/soll-ist-abweichung.md](../../../docs/spec/soll-ist-abweichung.md) §5.2.

## Szenario-Tabelle

| ID | Test | Regel | Kategorie |
|----|------|-------|-----------|
| S1 | `test_s1_swimspa_warning` | `swimspa_thermal_band_ok` | Warnung |
| S2 | `test_s2_eauto_error` | `eauto_should_charge` | Fehler |
| S3 | `test_s3_forced_charge_error` | `battery_forced_charge_missing` | Fehler |
| S4 | `test_s4_no_deviation_within_tolerance` | — | kein Icon |
| S5 | `test_s5_waermepumpe_hint` | `waermepumpe_enable_no_start` | Hinweis |
| S6 | `test_s3b_forced_discharge_error` | `battery_forced_discharge_missing` | Fehler |
| S7 | `test_s2b_eauto_pv_follow_error` | `eauto_pv_follow_missing` | Fehler |
| S8 | `test_s8_should_run_but_missing` | `swimspa_filter_should_run_missing` | Fehler |
| S9 | `test_s9_runs_unexpectedly_outside_native_window` | `swimspa_filter_runs_unexpectedly` | Fehler |
| S10 | `test_s10_over_nominal_warning` | `swimspa_filter_over_nominal` | Warnung |

Parametrisierte Gesamtprüfung: `tests/test_deviation_scenario_catalog.py` (S1–S8; S9/S10 brauchen `slot_start`/Config-Nennleistung → `tests/test_deviation_eval.py`).

## Fiktives Produktiv-Log

Keine statischen JSONL-Fixtures — das Seed-Skript erzeugt ein remapped Log für die UI:

```powershell
python -m scripts.seed_deviation_test_log --force
```

VS Code: Launch **Streamlit app.py (Deviation-Test)** (seedet automatisch, lokales `runtime/`).

## Tests ausführen

```powershell
.venv\Scripts\python.exe -m pytest tests/test_deviation_*.py tests/test_seed_deviation_test_log.py -q
```
