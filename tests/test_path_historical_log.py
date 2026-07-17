"""Legacy path_log alias for path_historical_log."""
from settings.flexible_consumers import normalize_consumer


def test_path_historical_log_preferred() -> None:
    consumer = normalize_consumer(
        {
            "id": "eauto",
            "nominal_power_kw": 11.0,
            "chart_color_index": 1,
            "path_historical_log": "new.csv",
            "path_log": "old.csv",
        }
    )
    assert consumer["path_historical_log"] == "new.csv"
    assert "path_log" not in consumer


def test_path_log_legacy_fallback() -> None:
    consumer = normalize_consumer(
        {
            "id": "eauto",
            "nominal_power_kw": 11.0,
            "chart_color_index": 1,
            "path_log": "legacy.csv",
        }
    )
    assert consumer["path_historical_log"] == "legacy.csv"
