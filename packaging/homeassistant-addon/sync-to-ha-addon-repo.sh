#!/bin/sh
# Mirrors packaging/homeassistant-addon/earnie/ (Entwicklungsquelle in diesem
# Hauptrepo) in einen lokalen Checkout von
# https://github.com/JochenTCC/ha-addon-earnie — dort muss der Add-on-Ordner
# direkt im Repo-Root liegen (Supervisor-Repository-Konvention, kein
# Unterordner-Deeplink möglich).
#
# Sync-Mechanik: manueller Kopiervorgang bei lokaler Entwicklung / Recovery.
# Automatischer Publish: .github/workflows/release.yml → publish_ha_addon.
#
# Usage: packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
set -e

SRC="$(cd "$(dirname "$0")/earnie" && pwd)"
DEST="${1:?Usage: $0 <path-to-ha-addon-earnie-checkout>}"

if [ ! -d "$DEST/.git" ]; then
    echo "Fehler: $DEST sieht nicht wie ein Git-Checkout aus (kein .git)." >&2
    exit 1
fi

rm -rf "$DEST/earnie"
mkdir -p "$DEST/earnie"
cp -r "$SRC/." "$DEST/earnie/"

echo "Synced $SRC -> $DEST/earnie/"
echo "Vor dem Commit prüfen:"
echo "  - earnie/config.yaml 'version:' gebumpt?"
echo "  - earnie/build.yaml EARNIE_VERSION passend zum neuen Earnie-Release?"
echo "  - earnie/CHANGELOG.md Eintrag ergänzt?"
echo "Danach in $DEST committen und pushen."
