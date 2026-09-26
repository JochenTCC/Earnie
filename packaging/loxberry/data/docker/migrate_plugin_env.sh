#!/bin/bash
# Shared helper: ensure plugin.env has channel keys; drop dead IMAGE=.
# Sourced by postinstall / postupgrade / postroot (not installed alone).
# Usage: earnie_migrate_plugin_env <plugin.env path>

earnie_migrate_plugin_env() {
  local envfile="$1"
  local tmp
  [ -n "$envfile" ] || return 1
  mkdir -p "$(dirname "$envfile")"

  if [ ! -f "$envfile" ]; then
    {
      echo "# Earnie LoxBerry plugin — local notes (do not commit secrets here)"
      echo "EARNIE_CHANNEL=stable"
      echo "EARNIE_PINNED_VERSION="
      echo "EARNIE_AUTO_UPDATE=1"
      echo "STREAMLIT_PORT=8501"
    } > "$envfile"
    return 0
  fi

  tmp="${envfile}.tmp.$$"
  # Drop dead IMAGE= (H13); keep everything else.
  grep -v -E '^IMAGE=' "$envfile" > "$tmp" 2>/dev/null || : > "$tmp"
  mv -f "$tmp" "$envfile"

  if ! grep -q -E '^EARNIE_CHANNEL=' "$envfile"; then
    echo "EARNIE_CHANNEL=stable" >> "$envfile"
  fi
  if ! grep -q -E '^EARNIE_PINNED_VERSION=' "$envfile"; then
    echo "EARNIE_PINNED_VERSION=" >> "$envfile"
  fi
  if ! grep -q -E '^EARNIE_AUTO_UPDATE=' "$envfile"; then
    echo "EARNIE_AUTO_UPDATE=1" >> "$envfile"
  fi
  if ! grep -q -E '^STREAMLIT_PORT=' "$envfile"; then
    echo "STREAMLIT_PORT=8501" >> "$envfile"
  fi
  return 0
}
