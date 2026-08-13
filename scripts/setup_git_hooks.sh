#!/bin/sh
# Aktiviert versionierte Git-Hooks aus .githooks/ für dieses Repository.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git config core.hooksPath .githooks
echo "Git hooksPath gesetzt auf .githooks"
echo "pre-commit führt 'pytest tests' aus (übersprungen bei nur *.md, *.png, docs/, .cursor/, .github/, .githooks/)."
echo "JUnit wird in .pytest_cache/test-metrics/ ingestiert (scripts.test_health_report)."
echo "post-commit fragt interaktiv nach Token-Report (Download / vorhandene CSV / Skip)."
