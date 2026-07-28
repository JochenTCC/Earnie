#!/bin/bash
# postupgrade.sh — runs as loxberry after new files are installed.

set -u

PDIR="${3:-earnie}"
PCONFIG="${LBPCONFIG:-}/$PDIR"
BAK="/tmp/earnie_plugin_env.bak"

mkdir -p "$PCONFIG"
if [ -f "$BAK" ]; then
  cp -f "$BAK" "$PCONFIG/plugin.env"
  rm -f "$BAK"
  echo "<INFO> Restored plugin.env"
fi

exit 0
