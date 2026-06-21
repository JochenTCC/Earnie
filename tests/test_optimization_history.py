# tests/test_optimization_history.py
import json
import os
from datetime import datetime

import optimization_history as oh


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
