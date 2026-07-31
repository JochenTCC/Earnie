#!/bin/bash
# postinstall.sh — runs as loxberry after files are copied.

set -u

PDIR="${3:-earnie}"
PDATA="${LBPDATA:-}/$PDIR"
PCONFIG="${LBPCONFIG:-}/$PDIR"

mkdir -p "$PDATA/earnie_env/config" "$PDATA/earnie_env/runtime" "$PDATA/docker"
mkdir -p "$PCONFIG"

# Marker so UI/docs can show install path; survives upgrades via pre/postupgrade.
if [ ! -f "$PCONFIG/plugin.env" ]; then
  {
    echo "# Earnie LoxBerry plugin — local notes (do not commit secrets here)"
    echo "IMAGE=ghcr.io/jochentcc/earnie-energy:latest"
    echo "STREAMLIT_PORT=8501"
  } > "$PCONFIG/plugin.env"
fi

SYNC="$PDATA/docker/sync_streamlit_env.sh"
if [ -x "$SYNC" ] || [ -f "$SYNC" ]; then
  bash "$SYNC" "$PCONFIG/plugin.env" "$PDATA/docker"
fi

exit 0
