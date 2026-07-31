#!/bin/bash
# postupgrade.sh — runs as loxberry after new files are installed.

set -u

PDIR="${3:-earnie}"
PCONFIG="${LBPCONFIG:-}/$PDIR"
BAK="/tmp/earnie_plugin_env.bak"

PDATA="${LBPDATA:-}/$PDIR"

mkdir -p "$PCONFIG"
if [ -f "$BAK" ]; then
  cp -f "$BAK" "$PCONFIG/plugin.env"
  rm -f "$BAK"
  echo "<INFO> Restored plugin.env"
fi

SYNC="$PDATA/docker/sync_streamlit_env.sh"
if [ -f "$SYNC" ] && [ -f "$PCONFIG/plugin.env" ]; then
  bash "$SYNC" "$PCONFIG/plugin.env" "$PDATA/docker"
  echo "<INFO> Synced STREAMLIT_PORT to compose .env"
fi

exit 0
