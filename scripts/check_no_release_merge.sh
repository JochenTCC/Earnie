#!/bin/sh
# Verhindert, dass ein release/*-Branch als Ganzes nach main zurueckfliesst.
# Erlaubt sind nur einzelne Fixes per Cherry-Pick (neue SHAs). Siehe
# docs/workflow/branching-hotfix-playbook.md.
#
# Aufruf: check_no_release_merge.sh <base-sha> <head-sha>
# Schlaegt fehl, wenn ein Commit aus base..head auch auf einem release/*-Branch liegt
# (lokal oder origin), der base nicht schon enthaelt.
set -e

BASE="$1"
HEAD="$2"
if [ -z "$BASE" ] || [ -z "$HEAD" ]; then
  echo "usage: $0 <base-sha> <head-sha>" >&2
  exit 2
fi

ZERO="0000000000000000000000000000000000000000"
# Neuer Branch / unbekannte Basis: nichts Sinnvolles zu vergleichen.
[ "$BASE" = "$ZERO" ] && exit 0
git cat-file -e "$BASE^{commit}" 2>/dev/null || exit 0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git rev-list "$BASE..$HEAD" | sort > "$TMP/pushed"
[ -s "$TMP/pushed" ] || exit 0
git rev-list --branches='release/*' --remotes='origin/release/*' --not "$BASE" | sort > "$TMP/release_only"
comm -12 "$TMP/pushed" "$TMP/release_only" > "$TMP/hits"

if [ -s "$TMP/hits" ]; then
  echo "release-guard: diese Commits liegen auf einem release/*-Branch und duerfen nicht als Ganzes nach main:" >&2
  head -n 10 "$TMP/hits" | while read -r SHA; do
    git log -1 --format='  %h %s' "$SHA" >&2
  done
  echo "release-guard: Einzelne Fixes per 'git cherry-pick -x <sha>' auf einen Branch von main uebernehmen (PR)." >&2
  exit 1
fi
