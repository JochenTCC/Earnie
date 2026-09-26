#!/bin/sh
# Docker HEALTHCHECK entry (H4). Logic lives in Python (urllib, no curl).
exec python -m scripts.container_healthcheck
