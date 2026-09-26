#!/bin/bash
# postinstall.sh — runs as loxberry after files are copied.

set -u

PDIR="${3:-earnie}"
PDATA="${LBPDATA:-}/$PDIR"
PCONFIG="${LBPCONFIG:-}/$PDIR"

mkdir -p "$PDATA/earnie_env/config" "$PDATA/earnie_env/runtime" "$PDATA/docker"
mkdir -p "$PCONFIG"

# shellcheck source=data/docker/migrate_plugin_env.sh
. "$PDATA/docker/migrate_plugin_env.sh"
earnie_migrate_plugin_env "$PCONFIG/plugin.env"

SYNC="$PDATA/docker/sync_compose_env.sh"
if [ -x "$SYNC" ] || [ -f "$SYNC" ]; then
  bash "$SYNC" "$PCONFIG/plugin.env" "$PDATA/docker"
fi

exit 0
