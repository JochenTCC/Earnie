# tests/test_optimization_history.py
import json
from datetime import datetime

import runtime_store.optimization_history as oh


def test_legacy_csv_mixed_column_count(tmp_path, monkeypatch):
    """Ältere CSV-Zeilen ohne Target_SoC_% dürfen das Einlesen nicht abbrechen."""
    legacy = tmp_path / "legacy.csv"
    monkeypatch.setattr(oh, "LEGACY_CSV_FILE", str(legacy))
    monkeypatch.setattr(oh, "HISTORY_FILE", str(tmp_path / "missing.jsonl"))

    legacy.write_text(
        "Timestamp,SoC_%,Awattar_Price,PV_Forecast_kW,Consumption_Forecast_kW,"
        "Ernie_Mode,Target_Power_kW\n"
        "2026-06-16 07:08:01,10.0,13.17,0.299,0.49,0,0.0\n"
        "2026-06-16 10:02:59,51.0,2.83,0.9,1.784,1,2.5,90.0\n",
        encoding="utf-8",
    )

    df = oh.load_optimization_history(days_back=None)
    assert len(df) == 2
    oldest = df.iloc[1]
    newest = df.iloc[0]
    assert float(oldest["target_soc_percent"]) == 0.0
    assert float(newest["target_soc_percent"]) == 90.0


def test_merge_prefers_jsonl_over_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(oh, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(oh, "HISTORY_FILE", str(tmp_path / "optimization_history.jsonl"))
    monkeypatch.setattr(oh, "LEGACY_CSV_FILE", str(tmp_path / "legacy.csv"))

    ts = datetime(2026, 6, 21, 15, 0, 0)
    entry = {
        "completed_at": ts.isoformat(timespec="seconds"),
        "source": "main.py",
        "soc_percent": 80.0,
        "mode": 1,
        "target_power_kw": 2.0,
        "target_soc_percent": 90.0,
        "market_price_cent": 12.0,
        "forecast_pv_kw": 3.0,
        "forecast_consumption_kw": 1.0,
        "battery_plan_kw": 1.5,
        "consumer_powers_kw": {"swimspa": 2.8},
    }
    with open(oh.HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    with open(oh.LEGACY_CSV_FILE, "w", encoding="utf-8") as f:
        f.write(
            "Timestamp,SoC_%,Awattar_Price,PV_Forecast_kW,Consumption_Forecast_kW,"
            "Ernie_Mode,Target_Power_kW,Target_SoC_%\n"
            f"{ts.strftime('%Y-%m-%d %H:%M:%S')},50.0,10.0,1.0,1.0,0,0.0,99.0\n"
        )

    df = oh.load_optimization_history(days_back=None)
    assert len(df) == 1
    assert float(df.iloc[0]["soc_percent"]) == 80.0
    assert df.iloc[0]["source"] == "main.py"
