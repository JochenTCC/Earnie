#!/bin/bash
# earnie_ctl.sh — passwordless sudo via plugin sudoers + bin/ for Plugin Admin UI.
# Usage: earnie_ctl.sh start|stop|restart|status|pull|auto-pull
# Installed to REPLACELBPBINDIR (LoxBerry only installs plugin bin/, not sbin/).

set -u

ACTION="${1:-}"
SERVICE="earnie"
COMPOSE_DIR="REPLACELBPDATADIR/docker"
PLUGIN_ENV="REPLACELBPCONFIGDIR/plugin.env"
CONTAINER="earnie-productive"

env_val() {
  local key="$1"
  local val=""
  if [ -f "$PLUGIN_ENV" ]; then
    val=$(grep -E "^${key}=" "$PLUGIN_ENV" | tail -1 | cut -d= -f2- | tr -d '[:space:]')
  fi
  printf '%s' "$val"
}

do_pull() {
  if [ -d "$COMPOSE_DIR" ]; then
    # Refresh compose .env from plugin.env before pull (tag may have changed).
    SYNC="$COMPOSE_DIR/sync_compose_env.sh"
    if [ -f "$SYNC" ] && [ -f "$PLUGIN_ENV" ]; then
      bash "$SYNC" "$PLUGIN_ENV" "$COMPOSE_DIR" || true
    fi
    cd "$COMPOSE_DIR" || exit 1
    /usr/bin/docker compose pull
    /usr/bin/docker compose up -d --remove-orphans
  fi
  systemctl restart "$SERVICE"
}

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
    do_pull
    ;;
  auto-pull)
    # Daily timer: only stable/prerelease with EARNIE_AUTO_UPDATE=1. Never for pinned.
    CHANNEL="$(env_val EARNIE_CHANNEL)"
    if [ -z "$CHANNEL" ]; then
      CHANNEL="stable"
    fi
    AUTO="$(env_val EARNIE_AUTO_UPDATE)"
    if [ -z "$AUTO" ]; then
      AUTO="1"
    fi
    case "$CHANNEL" in
      stable|prerelease)
        case "$AUTO" in
          1|true|yes|on)
            do_pull
            ;;
          *)
            echo "auto-pull skipped: EARNIE_AUTO_UPDATE=$AUTO" >&2
            ;;
        esac
        ;;
      *)
        echo "auto-pull skipped: channel=$CHANNEL" >&2
        ;;
    esac
    ;;
  status)
    systemctl show --value --property ActiveState "$SERVICE" 2>/dev/null || echo "unknown"
    docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true
    ;;
  *)
    echo "Usage: $0 start|stop|restart|status|pull|auto-pull" >&2
    exit 1
    ;;
esac

exit 0
