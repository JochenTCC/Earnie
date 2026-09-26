#!/bin/sh
# Mirrors packaging/homeassistant-addon/earnie/ and earnie_prerelease/
# (Entwicklungsquelle in diesem Hauptrepo) in einen lokalen Checkout von
# https://github.com/JochenTCC/ha-addon-earnie — Add-on-Ordner liegen direkt
# im Repo-Root (Supervisor-Repository-Konvention).
#
# Sync-Mechanik: manueller Kopiervorgang bei lokaler Entwicklung / Recovery.
# Automatischer Publish: .github/workflows/release-publish.yml → publish_ha_addon
# (official → both; pre-release → earnie_prerelease only).
#
# Usage: packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?Usage: $0 <path-to-ha-addon-earnie-checkout>}"

if [ ! -d "$DEST/.git" ]; then
    echo "Fehler: $DEST sieht nicht wie ein Git-Checkout aus (kein .git)." >&2
    exit 1
fi

for slug in earnie earnie_prerelease; do
    SRC="$ROOT/$slug"
    if [ ! -d "$SRC" ]; then
        echo "Fehler: Quelle fehlt: $SRC" >&2
        exit 1
    fi
    rm -rf "$DEST/$slug"
    mkdir -p "$DEST/$slug"
    cp -r "$SRC/." "$DEST/$slug/"
    echo "Synced $SRC -> $DEST/$slug/"
done

echo "Vor dem Commit prüfen:"
echo "  - earnie/ + earnie_prerelease/ config.yaml 'version:'"
echo "  - build.yaml EARNIE_VERSION / image: ghcr.io/jochentcc/earnie-addon-{arch}"
echo "  - CHANGELOG.md"
echo "Danach in $DEST committen und pushen."
