#!/bin/bash
# preupgrade.sh — runs as loxberry before old plugin tree is removed.

set -u

PDIR="${3:-earnie}"
PCONFIG="${LBPCONFIG:-}/$PDIR"
BAK="/tmp/earnie_plugin_env.bak"

if [ -f "$PCONFIG/plugin.env" ]; then
  cp -f "$PCONFIG/plugin.env" "$BAK"
  echo "<INFO> Backed up plugin.env to $BAK"
fi

exit 0
