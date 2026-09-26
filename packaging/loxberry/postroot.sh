#!/bin/bash
# postroot.sh — runs as ROOT, last install/upgrade step.

set -u

PDIR="${3:-earnie}"
PDATA="${LBPDATA:-}/$PDIR"
PCONFIG="${LBPCONFIG:-}/$PDIR"

mkdir -p "$PDATA/earnie_env/config" "$PDATA/earnie_env/runtime"
chown -R loxberry:loxberry "$PDATA/earnie_env" 2>/dev/null || true

# shellcheck source=data/docker/migrate_plugin_env.sh
. "$PDATA/docker/migrate_plugin_env.sh"
earnie_migrate_plugin_env "$PCONFIG/plugin.env"
chown loxberry:loxberry "$PCONFIG/plugin.env" 2>/dev/null || true

if [ ! -f "$PDATA/docker/docker-compose.yml" ]; then
  echo "<ERROR> Missing $PDATA/docker/docker-compose.yml"
  exit 2
fi

if [ ! -f "$PDATA/docker/earnie.service" ]; then
  echo "<ERROR> Missing $PDATA/docker/earnie.service"
  exit 2
fi

bash "$PDATA/docker/sync_compose_env.sh" "$PCONFIG/plugin.env" "$PDATA/docker"
chown loxberry:loxberry "$PDATA/docker/.env" 2>/dev/null || true

cp -f "$PDATA/docker/earnie.service" /etc/systemd/system/earnie.service
systemctl daemon-reload
systemctl enable earnie

# Daily image auto-update (~03:30); earnie_ctl auto-pull respects channel + EARNIE_AUTO_UPDATE.
if [ -f "$PDATA/docker/earnie-update.service" ] && [ -f "$PDATA/docker/earnie-update.timer" ]; then
  cp -f "$PDATA/docker/earnie-update.service" /etc/systemd/system/earnie-update.service
  cp -f "$PDATA/docker/earnie-update.timer" /etc/systemd/system/earnie-update.timer
  systemctl daemon-reload
  systemctl enable earnie-update.timer
  systemctl start earnie-update.timer
  echo "<INFO> Enabled earnie-update.timer (daily ~03:30; skipped for pinned / AUTO_UPDATE=0)"
fi

echo "<INFO> Pulling Earnie image and starting container..."
cd "$PDATA/docker" || exit 2
/usr/bin/docker compose pull
/usr/bin/docker compose up -d --remove-orphans
systemctl restart earnie

exit 0
