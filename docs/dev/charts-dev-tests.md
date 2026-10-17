# Chart developer tests

Moved from the user doc `docs/ui/charts.md` (Chart 1, deviation icons).

## Deviation test

The VS Code launch **Streamlit app.py (Deviation-Test)** writes a fictional log (`scripts/seed_deviation_test_log.py`) into the local `runtime/` and starts Streamlit. Manually: `python -m scripts.seed_deviation_test_log --force`.

## Up/down bars (scenarios A–H)

Launch **Streamlit app.py (Flow-Balance-Test)** (`scripts/seed_flow_balance_test_log.py`), or the HTML preview: `python -m scripts.export_flow_balance_chart_html --open` → `runtime/flow_balance_preview.html`.
