#!/bin/sh
# Start Redis inside this container (no Docker-in-Docker required).
# Build once: make -C .tools/redis-7.2.7 MALLOC=libc redis-server redis-cli
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.tools/redis-7.2.7/src/redis-server"
CLI="$ROOT/.tools/redis-7.2.7/src/redis-cli"
DATA="$ROOT/.tools/redis-data"

if [ ! -x "$BIN" ]; then
  echo "Redis binary missing. Build with:" >&2
  echo "  make -C .tools/redis-7.2.7 MALLOC=libc -j\$(nproc) redis-server redis-cli" >&2
  exit 1
fi

mkdir -p "$DATA"
if "$CLI" ping >/dev/null 2>&1; then
  echo "Redis already running on :6379"
  exit 0
fi

"$BIN" --daemonize yes --port 6379 --dir "$DATA" --appendonly yes \
  --logfile "$DATA/redis.log" --pidfile "$DATA/redis.pid"
"$CLI" ping
echo "Redis started (data: $DATA)"
