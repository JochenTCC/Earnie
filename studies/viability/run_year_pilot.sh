#!/bin/sh
# Full-year pilot for the four pilot houses (packs built beforehand), PR 1.0 (Earnie native) and PR 0.8.
cd "$(dirname "$0")/../.." || exit 1
PY=.venv/Scripts/python.exe
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
for pr in 100 80; do
  if [ "$pr" = 100 ]; then ratio=1.0; dir=packs; else ratio=0.8; dir=packs_pr80; fi
  for h in A09-m A18-m A13-m A21-m; do
    $PY -m studies.poc_cloud.run_poc --study-dir studies/viability/$dir/$h --cache-dir studies/viability/cache/open_meteo \
      --allow-network --harvest --start-month 1 --end-month 12 --out studies/viability/$dir/$h/results/year \
      > studies/viability/$dir/$h/year.log 2>&1
    echo "$dir $h exit=$? $(grep -o 'Done in [0-9]* s' studies/viability/$dir/$h/year.log)"
  done
done
