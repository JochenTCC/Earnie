#!/bin/bash
# Sync STREAMLIT_PORT from plugin.env and host TZ → compose .env
# (Docker Compose interpolation).
# Usage: sync_streamlit_env.sh <plugin.env> <compose_dir>
set -u

PLUGIN_ENV="${1:-}"
COMPOSE_DIR="${2:-}"

if [ -z "$PLUGIN_ENV" ] || [ -z "$COMPOSE_DIR" ]; then
  echo "Usage: $0 <plugin.env> <compose_dir>" >&2
  exit 1
fi

PORT=8501
if [ -f "$PLUGIN_ENV" ]; then
  val=$(grep -E '^STREAMLIT_PORT=' "$PLUGIN_ENV" | tail -1 | cut -d= -f2- | tr -d '[:space:]')
  if echo "$val" | grep -Eq '^[0-9]+$' && [ "$val" -ge 1024 ] && [ "$val" -le 65535 ]; then
    PORT="$val"
  fi
fi

# H5: container TZ follows LoxBerry host (/etc/timezone).
TZ_VALUE="Europe/Vienna"
if [ -r /etc/timezone ]; then
  host_tz=$(tr -d '[:space:]' </etc/timezone)
  if [ -n "$host_tz" ]; then
    TZ_VALUE="$host_tz"
  fi
fi

mkdir -p "$COMPOSE_DIR"
printf 'STREAMLIT_PORT=%s\nTZ=%s\n' "$PORT" "$TZ_VALUE" > "$COMPOSE_DIR/.env"
exit 0
