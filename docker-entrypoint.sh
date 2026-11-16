#!/bin/sh
# Starts the app as the unprivileged `app` user. A new Fly volume is mounted owned by root, so this runs as
# root just long enough to give /app/data to `app`, then gives up root for good before the server starts.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    chown -R app:app /app/data
    exec env HOME=/home/app setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
