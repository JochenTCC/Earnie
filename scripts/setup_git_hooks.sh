#!/bin/sh
# Aktiviert versionierte Git-Hooks aus .githooks/ für dieses Repository.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git config core.hooksPath .githooks
echo "Git hooksPath gesetzt auf .githooks"
echo "pre-commit führt 'pytest tests' aus (übersprungen bei nur *.md, docs/, .cursor/)."
