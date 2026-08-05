"""path_historical_log required; path_log rejected."""
import pytest

from settings.flexible_consumers import normalize_consumer


def test_path_historical_log_used() -> None:
    consumer = normalize_consumer(
        {
            "id": "eauto",
            "nominal_power_kw": 11.0,
            "chart_color_index": 1,
            "path_historical_log": "new.csv",
        }
    )
    assert consumer["path_historical_log"] == "new.csv"
    assert "path_log" not in consumer


def test_path_log_rejected() -> None:
    with pytest.raises(ValueError, match="path_historical_log"):
        normalize_consumer(
            {
                "id": "eauto",
                "nominal_power_kw": 11.0,
                "chart_color_index": 1,
                "path_log": "legacy.csv",
            }
        )


def test_path_log_rejected_even_with_historical() -> None:
    with pytest.raises(ValueError, match="path_historical_log"):
        normalize_consumer(
            {
                "id": "eauto",
                "nominal_power_kw": 11.0,
                "chart_color_index": 1,
                "path_historical_log": "new.csv",
                "path_log": "old.csv",
            }
        )
