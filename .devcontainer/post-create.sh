#!/usr/bin/env bash
set -euo pipefail

echo "Installing Earnie (editable) with dev extras..."
# Wheel-only deps (shell:S8541); local -e project and the pinned edibert tag archive are source by design.
pip install --no-cache-dir --only-binary=:all: --no-binary=edibert -e '.[dev]'

mkdir -p earnie_env/config earnie_env/runtime
echo "Bootstrapping earnie_env (creates missing files only)..."
python -m scripts.bootstrap_runtime

python -c "from house_config.geo_timezone import timezone_for_land; assert timezone_for_land('AT') == 'Europe/Vienna'; print('timezone_for_land OK')"

echo "Dev container ready. Use F5: Streamlit app.py (:8531 lokal (earnie_env))."
