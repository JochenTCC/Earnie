#!/bin/bash
# Sync STREAMLIT_PORT, EARNIE_IMAGE_TAG, TZ, EARNIE_LAN_SUBNET from plugin.env /
# host routing → compose .env (Docker Compose interpolation).
# Usage: sync_compose_env.sh <plugin.env> <compose_dir>
set -u

PLUGIN_ENV="${1:-}"
COMPOSE_DIR="${2:-}"

if [ -z "$PLUGIN_ENV" ] || [ -z "$COMPOSE_DIR" ]; then
  echo "Usage: $0 <plugin.env> <compose_dir>" >&2
  exit 1
fi

read_env_val() {
  local key="$1"
  local val=""
  if [ -f "$PLUGIN_ENV" ]; then
    val=$(grep -E "^${key}=" "$PLUGIN_ENV" | tail -1 | cut -d= -f2- | tr -d '[:space:]')
  fi
  printf '%s' "$val"
}

PORT=8501
val="$(read_env_val STREAMLIT_PORT)"
if echo "$val" | grep -Eq '^[0-9]+$' && [ "$val" -ge 1024 ] && [ "$val" -le 65535 ]; then
  PORT="$val"
fi

CHANNEL="$(read_env_val EARNIE_CHANNEL)"
if [ -z "$CHANNEL" ]; then
  CHANNEL="stable"
fi

PINNED="$(read_env_val EARNIE_PINNED_VERSION)"
TAG="latest"

case "$CHANNEL" in
  prerelease)
    TAG="next"
    ;;
  pinned)
    if echo "$PINNED" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$'; then
      TAG="$PINNED"
    else
      echo "sync_compose_env: invalid EARNIE_PINNED_VERSION='${PINNED}', falling back to latest" >&2
      TAG="latest"
    fi
    ;;
  *)
    # stable (default) and unknown → latest
    TAG="latest"
    ;;
esac

# H5: container TZ follows LoxBerry host (/etc/timezone).
TZ_VALUE="Europe/Vienna"
if [ -r /etc/timezone ]; then
  host_tz=$(tr -d '[:space:]' </etc/timezone)
  if [ -n "$host_tz" ]; then
    TZ_VALUE="$host_tz"
  fi
fi

# H9: host LAN /24 for OpenEMS active scan inside the container.
# Prefer existing plugin.env / compose override; else derive from default route.
LAN_SUBNET="$(read_env_val EARNIE_LAN_SUBNET)"
if [ -z "$LAN_SUBNET" ] && [ -f "$COMPOSE_DIR/.env" ]; then
  LAN_SUBNET=$(grep -E '^EARNIE_LAN_SUBNET=' "$COMPOSE_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '[:space:]')
fi
if [ -z "$LAN_SUBNET" ]; then
  LAN_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')
  if echo "$LAN_IP" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    # Skip Docker-ish 172.16.0.0/12 on the host (unusual for LoxBerry).
    o1=$(echo "$LAN_IP" | cut -d. -f1)
    o2=$(echo "$LAN_IP" | cut -d. -f2)
    if [ "$o1" != "172" ] || [ "$o2" -lt 16 ] || [ "$o2" -gt 31 ]; then
      prefix=$(echo "$LAN_IP" | cut -d. -f1-3)
      LAN_SUBNET="${prefix}.0/24"
    fi
  fi
fi

mkdir -p "$COMPOSE_DIR"
{
  printf 'STREAMLIT_PORT=%s\nEARNIE_IMAGE_TAG=%s\nTZ=%s\n' \
    "$PORT" "$TAG" "$TZ_VALUE"
  if [ -n "$LAN_SUBNET" ]; then
    printf 'EARNIE_LAN_SUBNET=%s\n' "$LAN_SUBNET"
  fi
} > "$COMPOSE_DIR/.env"
exit 0
