#!/bin/bash
# Sync STREAMLIT_PORT, EARNIE_IMAGE_TAG, TZ from plugin.env → compose .env
# (Docker Compose interpolation).
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

mkdir -p "$COMPOSE_DIR"
printf 'STREAMLIT_PORT=%s\nEARNIE_IMAGE_TAG=%s\nTZ=%s\n' \
  "$PORT" "$TAG" "$TZ_VALUE" > "$COMPOSE_DIR/.env"
exit 0
