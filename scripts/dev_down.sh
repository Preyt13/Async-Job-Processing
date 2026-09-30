#!/bin/sh
# Stop local stack started by scripts/dev_up.sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.run"
CLI="$ROOT/.tools/redis-7.2.7/src/redis-cli"

stop_one() {
  name="$1"
  pidfile="$RUN_DIR/$name.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      # uvicorn/celery may leave children
      sleep 0.3
      kill -9 "$pid" 2>/dev/null || true
      echo "stopped $name ($pid)"
    fi
    rm -f "$pidfile"
  fi
}

stop_one api
stop_one worker
stop_one beat

# Also clear stray celery/uvicorn from this project if pidfiles were lost
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "celery -A app.celery_app.celery" 2>/dev/null || true

if [ -x "$CLI" ]; then
  "$CLI" shutdown nosave >/dev/null 2>&1 || true
  echo "stopped redis"
fi

echo "Local stack down."
