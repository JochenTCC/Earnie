# Spezifikation: Preisprognose für extrapolierte Slots (EU-Wetter & Erzeugung)

**Version:** 0.2  
**Status:** Phase 0–2 abgeschlossen (2026-07-06); Jahres-Evaluation läuft  
**Epic-Kurzname:** **Preis-Prognose**  
**Ersetzt:** Backlog-Research „Preis-Spiegelung Mittelung“  
**Bezug:** [UI Sunset-2-Sunset](ui-sunset2sunset.md) §5 (grüne Zone), `data/market_prices.py` (`resolve_market_slots`)

## 1. Ziel

Für Stunden **ohne Day-Ahead-Preis** (grüner Chart-Bereich bis SA₁/SA₂) soll die Optimierung **prognostizierte** statt gespiegelte EPEX-Bezugspreise nutzen.

Grundidee: AT-Spotpreise korrelieren mit der **europäischen** erneuerbaren Verfügbarkeit (Wind + Solar). Dafür zwei Feature-Familien parallel:

| Familie | Quelle (Training) | Quelle (Live, später) | Variablen |
|---------|-------------------|----------------------|-----------|
| **Wetter** | Open-Meteo ERA5-Archiv | Open-Meteo Forecast | kapazitätsgewichteter EU-Mittelwert: `wind_speed_10m`, `shortwave_radiation` |
| **Erzeugung** | Energy-Charts `public_power` | Energy-Charts `public_power_forecast` | summierte EU-MW: `wind_mw`, `solar_mw` |

Zielzone Preise: **AT Day-Ahead** (`bzn=AT`, EPEX-kompatibel).

## 2. Abgrenzung

| Im Epic | Nicht im Epic |
|---------|----------------|
| Offline-Training-Dataset (1 Jahr) | Live-Integration in `resolve_market_slots` (Phase 3) |
| Einfaches Korrelationsmodell (OLS / Binning) | ML-Framework, Gas/Nachfrage-Modell |
| Evaluation vs. Spiegelung | Änderung MILP-Kern |
| Explizite Config `missing_price_strategy` | UI-Label „prognostiziert“ (optional Phase 3) |

**Fallback:** Spiegelung bleibt erhalten, wenn Prognose-API oder Modell ausfällt.

## 3. Grüner Bereich (Kontext)

| Zone | Bedeutung | Preisquelle heute |
|------|-----------|-------------------|
| Neutral | Day-Ahead verfügbar | aWATTar / EPEX |
| Grün | Kein Day-Ahead | Spiegelung (gleiche Uhrzeit, 1–7 Tage zurück) |

Prognose ersetzt **nur** grüne Slots. `price_source` wird später `predicted` (neben `day_ahead`, `mirrored`).

## 4. Phase 0 — Scope (festgelegt)

### 4.1 Preisziel

- **Bidding Zone AT** (Energy-Charts / aWATTar-kompatibel)
- Einheit Training: **EPEX Cent/kWh** (`EUR/MWh ÷ 10`), Brutto-Aufschläge erst bei MILP (`epex_to_brutto_cent`)

### 4.2 Europäische Abdeckung

Länder mit hohem EPEX-Gewicht (Energy-Charts `country`-Code):

`de`, `at`, `fr`, `nl`, `be`, `pl`, `es`, `it`, `dk`, `se`, `cz`, `pt`

**Erzeugung:** Summe Wind (onshore + offshore) und Solar je Stunde über alle Länder → `eu_wind_mw`, `eu_solar_mw`.

**Wetter:** 11 Gitterpunkte (Länder-Zentroiden) mit kapazitätsnahen Gewichten für Wind bzw. Solar getrennt → `eu_wind_speed_kmh`, `eu_shortwave_radiation_wm2`.

Gewichte und Punkte: `data/eu_market_features.py` (`WEATHER_GRID`, `GENERATION_COUNTRIES`).

### 4.3 Modell (Phase 2, Vorschau)

Einfaches lineares Modell ohne neue Dependencies:

```
price_cent(h) ≈ β₀ + β₁·eu_wind_mw(h) + β₂·eu_solar_mw(h)
              + β₃·eu_wind_speed(h) + β₄·eu_radiation(h)
              + β₅·sin(2π·h/24) + β₆·cos(2π·h/24) + β₇·weekday + β₈·month
```

OLS via `numpy.linalg.lstsq`. Koeffizienten als JSON versionieren. **Kein stiller Default** — Live-Umschaltung nur per Config.

### 4.4 Akzeptanz (gesamt)

1. Walk-forward-Backtest: MAE/MAPE **besser als Spiegelung** auf extrapolierten Slots
2. MILP-Entscheidungsänderung dokumentiert (Stichprobe)
3. API-Ausfall → Spiegelung ohne Optimierungs-Abbruch

## 5. Phase 1 — Datenpipeline (umgesetzt)

### 5.1 Artefakte

| Pfad | Inhalt |
|------|--------|
| `data/eu_market_features.py` | Fetch, Normalisierung, Merge |
| `scripts/build_price_training_dataset.py` | CLI: Jahres-CSV erzeugen |
| `data/cache/price_training_*.csv` | Lokales Training-Dataset (gitignored) |

### 5.2 CLI

```powershell
.venv\Scripts\python.exe scripts/build_price_training_dataset.py
.venv\Scripts\python.exe scripts/build_price_training_dataset.py --start 2025-01-01 --end 2025-12-31
```

Standard: rollierende 12 Monate bis gestern. Output: `data/cache/price_training_<start>_<end>.csv`.

### 5.3 CSV-Spalten

| Spalte | Beschreibung |
|--------|--------------|
| `slot_datetime` | Stunden-Slot Europe/Vienna |
| `price_epex_cent_kwh` | AT Day-Ahead (Zielvariable) |
| `eu_wind_mw` | Summe Wind EU (Ist-Erzeugung) |
| `eu_solar_mw` | Summe Solar EU |
| `eu_wind_speed_kmh` | gewichteter Mittelwert Gitter |
| `eu_shortwave_radiation_wm2` | gewichteter Mittelwert Gitter |
| `eu_load_mw` | Summe Last EU (Energy-Charts „Load“) |
| `eu_residual_load_mw` | Summe Residuallast EU |
| `hour`, `weekday`, `month` | Kalenderfeatures (Modell nutzt `hour_sin`/`hour_cos`) |

Bestehende CSVs ohne Last-Spalten: `python -m scripts.enrich_price_training_dataset <csv>`.

Zeitliche Auflösung: **stündlich**. Energy-Charts 15-min-Daten → stündlicher Mittelwert.

**API-Hinweis:** Energy-Charts limitiert Abrufe (HTTP 429). `_http_get_json` nutzt Retry mit Backoff und Pause (~0,75 s) zwischen Requests. Volles Jahr (~300 Requests) dauert ca. 15–30 min.

## 6. Phase 2 — Modell & Evaluation (umgesetzt)

### 6.1 Artefakte

| Pfad | Inhalt |
|------|--------|
| `data/price_forecast_model.py` | OLS fit/predict, JSON-Serialisierung |
| `data/price_forecast_eval.py` | Spiegel-Baseline, Holdout, Walk-forward |
| `scripts/train_price_forecast_model.py` | Training + Holdout-Metriken |
| `scripts/evaluate_price_forecast.py` | Evaluation (holdout / walk_forward / full) |
| `data/cache/price_model_coefficients.json` | Trainierte Koeffizienten (gitignored) |

### 6.2 CLI

```powershell
.venv\Scripts\python.exe -m scripts.train_price_forecast_model
.venv\Scripts\python.exe -m scripts.evaluate_price_forecast --mode holdout --train-ratio 0.8
.venv\Scripts\python.exe -m scripts.evaluate_price_forecast --mode walk_forward --train-days 90 --test-days 7
```

### 6.3 Modell-JSON (Version 2)

Nach OLS-Fit: additive **Bias-Korrektur** aus Nicht-Peak-Stunden (Ist-Preis unter Perzentil, Standard P90). Peaks werden bei der Kalibrierung ausgeschlossen.

```json
{
  "version": 2,
  "feature_names": ["intercept", "eu_wind_mw", "..."],
  "coefficients": [ ... ],
  "bias_correction_cent_kwh": -0.33,
  "bias_correction_peak_percentile": 90.0,
  "bias_correction_peak_threshold_cent_kwh": 12.5,
  "bias_correction_non_peak_hours": 6300,
  "trained_range_start": "...",
  "trained_range_end": "...",
  "training_rows": 8760,
  "feature_variant": "extended"
}
```

`predict_prices` wendet die Korrektur standardmäßig an (`apply_bias_correction=False` für Roh-OLS).

### 6.4 Erste Erkenntnisse (7-Tage-Stichprobe, 2025-07-01..08)

Holdout (25 %): **Spiegelung MAE ≈ 3,0 Cent/kWh**, Modell MAE ≈ 3,7 — auf kurzer Stichprobe noch **schlechter als Spiegelung**. Volle Jahres-Evaluation entscheidet über Phase 3.

## 7. Phase 3 — Vorbereitung (UI & Live-Hooks)

### 7.1 UI-Modus „Preis-Prognose (Dev)“

Sidebar-Betriebsmodus (nur wenn `ENERGY_OPTIMIZER_UI_MODES` leer oder `price_forecast` enthalten):

- Zeitreihe: Ist vs. OLS vs. Spiegelung (Holdout)
- Scatter Ist vs. Prognose
- MAE je Tagesstunde
- Metriken MAE/RMSE Modell vs. Spiegel

Modul: `ui/price_forecast.py`

### 7.2 Live-Hooks (noch nicht in `resolve_market_slots`)

| Artefakt | Zweck |
|----------|--------|
| `data/price_forecast_live.py` | Config lesen, Modell laden, `PRICE_SOURCE_PREDICTED` |
| `data/market_prices.py` | Konstante `PRICE_SOURCE_PREDICTED` |
| `config.market_prices` | `missing_price_strategy`: `mirror` \| `forecast` |
| `optimizer/simulation.py` | `is_extrapolated_source()` für Chart-Feld |

### 7.3 Offen (Phase 3 Abschluss)

- `resolve_market_slots`: bei `forecast` fehlende Slots per Modell befüllen, Fallback Spiegelung
- Feature-Fetch Live (Open-Meteo Forecast / Energy-Charts Prognose)

## 8. Architektur (Zielbild Phase 3 Live)

```
aWATTar (Day-Ahead) ──▶ resolve_market_slots
                              │
Open-Meteo / Energy-Charts ──▶│ predict missing slots
                              │     (price_model.json)
                              ▼
                       Optimierungs-Matrix
                              │
                       Fallback: mirror
```

## 9. Phasenplan

| Phase | Inhalt | Status |
|-------|--------|--------|
| **0** | Scope, Länder, Features, Akzeptanz | ✅ festgelegt (§4) |
| **1** | Dataset-Skript + `eu_market_features` | ✅ umgesetzt |
| **2** | Modell trainieren, Walk-forward-Backtest vs. Spiegelung | ✅ umgesetzt (Eval auf Jahres-CSV ausstehend) |
| **3** | Live in `resolve_market_slots`, Config, UI-Eval | 🔄 vorbereitet |
| **4** | Doku `preise.md`, optional monatliches Re-Training | offen |

## 10. Risiken

- Wetter ≠ Erzeugung: beide Feature-Familien parallel evaluieren
- Nur Wind+Solar erklären Preis nicht vollständig (Gas, Nachfrage, Netz)
- Prognosegüte der Wetter-API für D+2-Horizont
- DST: Slots über `normalize_price_slot` / Europe/Vienna

## 11. Bezug

- Preise Live: [preise.md](../konfiguration/preise.md)
- UI grüne Zone: [ui-sunset2sunset.md](ui-sunset2sunset.md) §5
- Backlog: `Backlog.md` Research Items

## Änderungshistorie

| Datum | Version | Inhalt |
|-------|---------|--------|
| 2026-07-06 | 0.2 | Phase 2: OLS-Modell, Evaluation vs. Spiegelung |
| 2026-07-06 | 0.1 | Initiale Spec; Phase 0 Scope; Phase 1 Pipeline |
