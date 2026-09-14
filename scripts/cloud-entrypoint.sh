#!/bin/sh
# Cloud studio container start. Railway mounts the data volume owned by root,
# so hand it to the app user, then drop root for good before the server runs.
set -eu
mkdir -p "$STUDIO_DATA"
chown app:app "$STUDIO_DATA"
find "$STUDIO_DATA" -xdev ! -user app -exec chown app:app {} +
exec setpriv --reuid=app --regid=app --init-groups \
  env HOME=/home/app python /app/viewer/server.py --port "${PORT:-8080}"
