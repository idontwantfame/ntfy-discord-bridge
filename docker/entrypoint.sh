#!/bin/sh
# Container entrypoint: runs the given command as the unprivileged "app" user.
#
# When started as root (the default), it first gives "app" ownership of the
# data directory, because volumes created by older versions of this image,
# which ran as root, are owned by root. Then it drops root for good.
set -eu

if [ "$(id -u)" = "0" ]; then
    data_dir="$(dirname "${DB_PATH:-/app/data/bridge.db}")"
    mkdir -p "$data_dir"
    chown -R app:app "$data_dir"
    exec setpriv --reuid=app --regid=app --init-groups -- "$@"
fi

exec "$@"
