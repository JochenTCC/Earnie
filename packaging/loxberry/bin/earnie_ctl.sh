#!/bin/bash
# earnie_ctl.sh — passwordless sudo via plugin sudoers + bin/ for Plugin Admin UI.
# Usage: earnie_ctl.sh start|stop|restart|status|pull
# Installed to REPLACELBPBINDIR (LoxBerry only installs plugin bin/, not sbin/).

set -u

ACTION="${1:-}"
SERVICE="earnie"
COMPOSE_DIR="REPLACELBPDATADIR/docker"
CONTAINER="earnie-productive"

# #region agent log
_EARNIE_DBG="/tmp/debug-3c62b0.log"
_earnie_dbg() {
  # $1=hypothesisId $2=location $3=message $4=json-data-object
  printf '{"sessionId":"3c62b0","hypothesisId":"%s","location":"%s","message":"%s","data":%s,"timestamp":%s}\n' \
    "$1" "$2" "$3" "${4:-{}}" "$(date +%s%3N)" >> "$_EARNIE_DBG" 2>/dev/null || true
}
_svc_state() { systemctl show --value --property ActiveState "$SERVICE" 2>/dev/null || echo "unknown"; }
_ctr_state() { docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "missing"; }
_compose_exists=no
[ -d "$COMPOSE_DIR" ] && _compose_exists=yes
_earnie_dbg "H2" "earnie_ctl.sh:entry" "ctl invoked" \
  "{\"action\":\"$ACTION\",\"svc\":\"$(_svc_state)\",\"ctr\":\"$(_ctr_state)\",\"compose_dir\":\"$COMPOSE_DIR\",\"compose_dir_exists\":\"$_compose_exists\"}"
# #endregion

case "$ACTION" in
  start)
    systemctl start "$SERVICE"
    _rc=$?
    # #region agent log
    _earnie_dbg "H3" "earnie_ctl.sh:start" "after systemctl start" \
      "{\"rc\":$_rc,\"svc\":\"$(_svc_state)\",\"ctr\":\"$(_ctr_state)\"}"
    # #endregion
    ;;
  stop)
    # #region agent log
    _earnie_dbg "H3" "earnie_ctl.sh:stop" "before systemctl stop" \
      "{\"svc\":\"$(_svc_state)\",\"ctr\":\"$(_ctr_state)\"}"
    # #endregion
    systemctl stop "$SERVICE"
    _rc=$?
    # #region agent log
    _earnie_dbg "H4" "earnie_ctl.sh:stop" "after systemctl stop" \
      "{\"rc\":$_rc,\"svc\":\"$(_svc_state)\",\"ctr\":\"$(_ctr_state)\"}"
    # #endregion
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
