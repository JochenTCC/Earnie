#!/bin/bash
# earnie_ctl.sh — passwordless sudo via LoxBerry sbin/ for Plugin Admin UI.
# Usage: earnie_ctl.sh start|stop|restart|status|pull

set -u

ACTION="${1:-}"
SERVICE="earnie"
COMPOSE_DIR="REPLACELBPDATADIR/docker"
CONTAINER="earnie-productive"

case "$ACTION" in
  start)
    systemctl start "$SERVICE"
    ;;
  stop)
    systemctl stop "$SERVICE"
    ;;
  restart)
    systemctl restart "$SERVICE"
    ;;
  pull)
    if [ -d "$COMPOSE_DIR" ]; then
      cd "$COMPOSE_DIR" || exit 1
      /usr/bin/docker compose pull
      /usr/bin/docker compose up -d --remove-orphans
    fi
    systemctl restart "$SERVICE"
    ;;
  status)
    systemctl show --value --property ActiveState "$SERVICE" 2>/dev/null || echo "unknown"
    docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true
    ;;
  *)
    echo "Usage: $0 start|stop|restart|status|pull" >&2
    exit 1
    ;;
esac

exit 0
