# Spezifikation: Preisprognose für extrapolierte Slots (EU-Wetter & Erzeugung)

**Version:** 0.5  
**Status:** Phase 0–3 live path done (2026-09-29); **2.5.e+:** Live Day-Ahead is QH; forecast **features stay hourly** and are **held onto parent-hour QH slots** (no QH retrain in Version 2.5). **Research (§11):** EU `public_power_forecast` + rolling live bias — gated off, not for public release.  
**Epic-Kurzname:** **Preis-Prognose**  
**Ersetzt:** Backlog-Research „Preis-Spiegelung Mittelung“  
**Bezug:** [UI Sunset-2-Sunset](ui-sunset2sunset.md) §5 (grüne Zone), `data/market_prices.py` (`resolve_market_slots`), [quarter-hour-slots.md](quarter-hour-slots.md)

## 1. Ziel

Für Stunden **ohne Day-Ahead-Preis** (grüner Chart-Bereich bis SA₁/SA₂) soll die Optimierung **prognostizierte** statt gespiegelte EPEX-Bezugspreise nutzen.

Grundidee: AT-Spotpreise korrelieren mit der **europäischen** erneuerbaren Verfügbarkeit (Wind + Solar). Dafür zwei Feature-Familien parallel:

| Familie | Quelle (Training) | Quelle (Live) | Variablen |
|---------|-------------------|---------------|-----------|
| **Wetter** | Open-Meteo ERA5-Archiv | Open-Meteo Forecast | kapazitätsgewichteter EU-Mittelwert: `wind_speed_10m`, `shortwave_radiation` |
| **Erzeugung** | Energy-Charts `public_power` | **Default:** hour-of-day stand-in from last archive day. **Research (off):** `public_power_forecast` via `eu_power_live_source=energy_charts_forecast` | summierte EU-MW: `wind_mw`, `solar_mw` |

Zielzone Preise: **AT Day-Ahead** (`bzn=AT`, EPEX-kompatibel).

## 2. Abgrenzung

| Im Epic | Nicht im Epic |
|---------|----------------|
| Offline-Training-Dataset (1 Jahr) | ML-Framework, Gas/Nachfrage-Modell |
| Einfaches Korrelationsmodell (OLS / Binning) | Änderung MILP-Kern |
| Evaluation vs. Spiegelung | — |
| Explizite Config `missing_price_strategy` | — |
| Live-Integration in `resolve_market_slots` (Phase 3) | — |

**Fallback:** Spiegelung bleibt erhalten, wenn Prognose-API oder Modell ausfällt.

## 3. Grüner Bereich (Kontext)

| Zone | Bedeutung | Preisquelle |
|------|-----------|-------------|
| Neutral | Day-Ahead verfügbar | aWATTar / EPEX |
| Grün | Kein Day-Ahead | **`forecast` (Standard):** OLS → `price_source=predicted`; Fallback Spiegelung bei Modell-/Feature-Ausfall. Alternativ Config `mirror`. |

Prognose ersetzt **nur** grüne Slots. Config: `market_prices.missing_price_strategy` = `forecast` \| `mirror`; Modellpfad Default `share/data/price_model_coefficients.json`. User doc: [preise.md](../konfiguration/preise.md).

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

Sidebar-Betriebsmodus (nur wenn `EARNIE_UI_MODES` leer oder `price_forecast` enthalten):

- Zeitreihe: Ist vs. OLS vs. Spiegelung (Holdout)
- Scatter Ist vs. Prognose
- MAE je Tagesstunde
- Metriken MAE/RMSE Modell vs. Spiegel

Modul: `ui/price_forecast.py`

### 7.2 Live-Hooks (in `resolve_market_slots`)

| Artefakt | Zweck |
|----------|--------|
| `data/price_forecast_live.py` | Config lesen, Modell laden, Live-Features, `PRICE_SOURCE_PREDICTED` |
| `data/eu_market_features.py` | Open-Meteo Forecast-Wetter + Archiv-Stand-in für EU-Leistung |
| `data/market_prices.py` | Konstante `PRICE_SOURCE_PREDICTED`; `forecast`-Pfad in `resolve_market_slots` |
| `config.market_prices` | `missing_price_strategy`: `mirror` \| `forecast` (Default `forecast`) |
| `share/data/price_model_coefficients.json` | Ship-Modell für Prod/Container |
| `optimizer/simulation.py` | `is_extrapolated_source()` für Chart-Feld |

### 7.3 Phase 3 Abschluss (2026-09-29)

- ✅ `resolve_market_slots`: bei `forecast` fehlende Slots per OLS befüllen, Fallback Spiegelung
- ✅ Live-Features: Open-Meteo Forecast-Wetter + stündliches EU-Leistungs-Stand-in aus dem letzten Archivtag
- **Research (not product default):** Energy-Charts `public_power_forecast` as live generation features; rolling live EPEX bias; tariff-extras parity checks — see §11

## 8. Architektur (Phase 3 Live)

```
aWATTar (Day-Ahead) ──▶ resolve_market_slots
                              │
Open-Meteo Forecast ──────────▶│ predict missing slots
EU power stand-in (archive) ──▶│     (share/data/price_model_coefficients.json)
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
| **3** | Live in `resolve_market_slots`, Config, UI-Eval | ✅ umgesetzt (Default `forecast`) |
| **4** | Doku `preise.md`, optional monatliches Re-Training | ✅ `preise.md`; Re-Training optional offen |

## 10. Risiken

- Wetter ≠ Erzeugung: beide Feature-Familien parallel evaluieren
- Nur Wind+Solar erklären Preis nicht vollständig (Gas, Nachfrage, Netz)
- Prognosegüte der Wetter-API für D+2-Horizont
- DST: Slots über `normalize_price_slot` / Europe/Vienna

## 11. Research gates (internal only — not for public release)

Ship defaults stay **archive hour-of-day power stand-in** and **no live bias**. Enable only in local `earnie_env` / `earnie_shadow` for value checks.

| Config key (`market_prices`) | Default | Research value |
|------------------------------|---------|----------------|
| `eu_power_live_source` | `archive_hod` | `energy_charts_forecast` → Energy-Charts `public_power_forecast` (solar + wind on/offshore, day-ahead then current) |
| `live_bias_enabled` | `false` | `true` → rolling mean residual (Day-Ahead − OLS) over lookback, capped, applied only to **predicted** EPEX |
| `live_bias_lookback_hours` | `48` | lookback window when bias enabled |
| `live_bias_cap_cent_kwh` | `5.0` | absolute cap on live bias |

Tariff extras (settlement, markup, Netznutzung, VAT) apply via `epex_to_brutto_cent` / `import_cent_kwh` for **both** Day-Ahead and predicted slots; regression: `test_predicted_and_day_ahead_same_tariff_extras_for_equal_epex`.

Compare script: `python -m scripts.compare_live_price_prognosis_research` (optional `--with-live-bias`).

### Disk cache + non-blocking live (research)

When `eu_power_live_source=energy_charts_forecast`:

- Frames persist under `runtime/cache/` (`eu_power_forecast_*.json`, `eu_weather_forecast_*.json`) with TTL **45 min** (same as in-memory).
- Status sidecar: `runtime/cache/eu_forecast_cache_status.json` (states: `missing` / `warming` / `ready` / `stale` / `error`).
- Cold miss does **not** block `main.py`: background refresh + temporary **`mirror`** for missing Day-Ahead slots until cache is ready; **stale-while-revalidate** keeps using expired disk frames while refresh runs.
- Country HTTP fan-out uses a small thread pool; Optimierer-Dienst shows **Preisprognose-Cache** (reads disk/sidecar — Streamlit ≠ daemon process).

## 12. Bezug

- Preise Live: [preise.md](../konfiguration/preise.md)
- UI grüne Zone: [ui-sunset2sunset.md](ui-sunset2sunset.md) §5
- Backlog: `backlog/Backlog.md` Research Items

## Änderungshistorie

| Datum | Version | Inhalt |
|-------|---------|--------|
| 2026-10-02 | 0.6 | Research: disk cache + non-blocking warmup/mirror; Optimierer-Dienst cache status |
| 2026-10-01 | 0.5 | Research gates: EU power forecast + live bias + tariff parity (§11); not product default |
| 2026-09-29 | 0.4 | Phase 3 live: Default `forecast`/OLS; Open-Meteo Features; ship-Modell `share/data/` |
| 2026-07-06 | 0.2 | Phase 2: OLS-Modell, Evaluation vs. Spiegelung |
| 2026-07-06 | 0.1 | Initiale Spec; Phase 0 Scope; Phase 1 Pipeline |
