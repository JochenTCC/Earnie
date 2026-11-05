"""AppTest entry: SE headline and ladder expander on a fixed log (RuleRef P4)."""
from ui.backtesting_ladder import render_ladder_headline

render_ladder_headline(
    {
        "reference_id": "historical_reference",
        "live_scenario_id": "live",
        "scenario_ids": ["historical_reference", "ref:live", "l1:live", "l2:live", "live"],
        "labels": {"live": "Live"},
        "reference_by_scenario": {"live": "ref:live"},
        "ladder_by_scenario": {"live": {"l1": "l1:live", "l2": "l2:live"}},
        "summary": {
            "total_eur": {
                "historical_reference": 2000.0,
                "ref:live": 1500.0,
                "l1:live": 1200.0,
                "l2:live": 1000.0,
                "live": 900.0,
            }
        },
    }
)
