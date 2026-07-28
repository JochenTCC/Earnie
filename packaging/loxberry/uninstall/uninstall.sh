#!/bin/bash
# uninstall.sh — runs as ROOT on plugin uninstall only (not on upgrade).
# Stops the container and removes the systemd unit.
# Keeps earnie_env/config + earnie_env/runtime under the plugin data dir
# until LoxBerry removes plugin directories — if data is under LBPDATA and
# LoxBerry wipes the plugin data folder, users should copy earnie_env out
# first. We intentionally do NOT docker rmi the Earnie image.

set -u

systemctl stop earnie 2>/dev/null || true
systemctl disable earnie 2>/dev/null || true
rm -f /etc/systemd/system/earnie.service
systemctl daemon-reload 2>/dev/null || true

# Fallback if ExecStop did not run compose down
docker rm -f earnie-productive 2>/dev/null || true

echo "<INFO> Earnie container stopped. Persistent earnie_env data is left in place if still present."
echo "<INFO> Manual wipe (optional): remove data/plugins/earnie/earnie_env/ after uninstall."

exit 0
