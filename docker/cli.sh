#!/bin/sh
# The `cli` command inside the container. `docker exec` runs as root by default,
# so go through the entrypoint to run the CLI as the "app" user owning the data.
exec /app/docker/entrypoint.sh python /app/cli.py "$@"
