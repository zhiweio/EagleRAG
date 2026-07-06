#!/bin/sh
# Dev entrypoint for docker-compose.override frontend service.
# The anonymous /app/node_modules volume can outlive lockfile updates; re-install when
# bun.lock changes or required packages (e.g. @embedpdf/core) are missing.
set -e

cd /app

MARKER="node_modules/.deps-synced"
LOCK_SUM="$(cksum bun.lock 2>/dev/null | awk '{print $1}' || echo 0)"

need_install=0
if [ ! -d node_modules/@embedpdf/core ]; then
  need_install=1
fi
if [ ! -f "$MARKER" ] || [ "$(cat "$MARKER" 2>/dev/null)" != "$LOCK_SUM" ]; then
  need_install=1
fi

if [ "$need_install" = 1 ]; then
  echo "[frontend] Syncing dependencies (lockfile or packages changed)..."
  bun install --frozen-lockfile
  echo "$LOCK_SUM" > "$MARKER"
fi

exec bun run dev -H 0.0.0.0
