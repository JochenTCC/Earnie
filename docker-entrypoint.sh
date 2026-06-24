#!/bin/sh
set -e
python -m scripts.bootstrap_runtime
exec "$@"
