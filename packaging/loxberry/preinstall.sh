#!/bin/bash
# preinstall.sh — runs as loxberry before files are copied. Exit >=2 aborts install.

set -u

echo "<INFO> Checking Docker availability for Earnie plugin..."

if ! command -v docker >/dev/null 2>&1; then
  echo "<ERROR> Docker not found. Install and activate the LoxBerry Docker plugin first."
  exit 2
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "<ERROR> 'docker compose' (v2) not available. Update the LoxBerry Docker plugin."
  exit 2
fi

curl -s --unix-socket /var/run/docker.sock http://ping >/dev/null 2>&1
if [ "$?" != "0" ]; then
  echo "<ERROR> Cannot reach Docker socket as user loxberry."
  echo "<ERROR> Ensure the Docker plugin is active and user loxberry is in the docker group."
  exit 2
fi

ARCH="$(uname -m 2>/dev/null || true)"
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
  echo "<WARNING> Host architecture is '$ARCH'. Official Earnie LoxBerry images target aarch64."
fi

echo "<OK> Docker is available."
exit 0
