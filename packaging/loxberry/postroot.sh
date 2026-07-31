#!/bin/bash
# postroot.sh — runs as ROOT, last install/upgrade step.

set -u

PDIR="${3:-earnie}"
PDATA="${LBPDATA:-}/$PDIR"
PCONFIG="${LBPCONFIG:-}/$PDIR"

mkdir -p "$PDATA/earnie_env/config" "$PDATA/earnie_env/runtime"
chown -R loxberry:loxberry "$PDATA/earnie_env" 2>/dev/null || true

if [ ! -f "$PCONFIG/plugin.env" ]; then
  {
    echo "IMAGE=ghcr.io/jochentcc/earnie-energy:latest"
    echo "STREAMLIT_PORT=8501"
  } > "$PCONFIG/plugin.env"
  chown loxberry:loxberry "$PCONFIG/plugin.env"
fi

if [ ! -f "$PDATA/docker/docker-compose.yml" ]; then
  echo "<ERROR> Missing $PDATA/docker/docker-compose.yml"
  exit 2
fi

if [ ! -f "$PDATA/docker/earnie.service" ]; then
  echo "<ERROR> Missing $PDATA/docker/earnie.service"
  exit 2
fi

bash "$PDATA/docker/sync_streamlit_env.sh" "$PCONFIG/plugin.env" "$PDATA/docker"
chown loxberry:loxberry "$PDATA/docker/.env" 2>/dev/null || true

cp -f "$PDATA/docker/earnie.service" /etc/systemd/system/earnie.service
systemctl daemon-reload
systemctl enable earnie

echo "<INFO> Pulling Earnie image and starting container..."
cd "$PDATA/docker" || exit 2
/usr/bin/docker compose pull
/usr/bin/docker compose up -d --remove-orphans
systemctl restart earnie

exit 0
