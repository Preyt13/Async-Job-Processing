#!/bin/sh
# Single-shot local stack for the dockerized interview env (no Docker-in-Docker).
# Starts: Redis (workspace binary) + API + Celery worker + Celery beat
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example"
fi

# shellcheck disable=SC1091
set -a
# Prefer .env for localhost Redis
. "$ROOT/.env"
set +a

REDIS_BIN="$ROOT/.tools/redis-7.2.7/src/redis-server"
REDIS_CLI="$ROOT/.tools/redis-7.2.7/src/redis-cli"

ensure_redis_binary() {
  if [ -x "$REDIS_BIN" ]; then
    return 0
  fi
  echo "Building Redis once into .tools/ (no sudo / no Docker)..."
  mkdir -p "$ROOT/.tools"
  if [ ! -d "$ROOT/.tools/redis-7.2.7" ]; then
    curl -fsSL -o "$ROOT/.tools/redis.tar.gz" \
      https://download.redis.io/releases/redis-7.2.7.tar.gz
    tar -xzf "$ROOT/.tools/redis.tar.gz" -C "$ROOT/.tools"
  fi
  make -C "$ROOT/.tools/redis-7.2.7" MALLOC=libc -j"$(nproc)" redis-server redis-cli
}

start_bg() {
  name="$1"
  shift
  pidfile="$RUN_DIR/$name.pid"
  logfile="$RUN_DIR/$name.log"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))"
    return 0
  fi
  "$@" >"$logfile" 2>&1 &
  echo $! >"$pidfile"
  echo "started $name (pid $(cat "$pidfile")) → $logfile"
}

ensure_redis_binary
./scripts/run_redis.sh

if [ ! -d "$ROOT/.venv" ]; then
  python -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
. "$ROOT/.venv/bin/activate"
pip install -q -r requirements.txt

start_bg api ./scripts/run_api.sh
start_bg worker ./scripts/run_worker.sh
start_bg beat ./scripts/run_beat.sh

echo "Waiting for /health..."
i=0
while [ "$i" -lt 30 ]; do
  if curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    echo
    echo "Stack is up."
    echo "  Health:  curl -s http://127.0.0.1:${API_PORT}/health"
    echo "  Docs:    http://127.0.0.1:${API_PORT}/docs"
    echo "  Submit:  curl -s -X POST http://127.0.0.1:${API_PORT}/jobs -H 'Content-Type: application/json' -d '{\"data\":{\"task\":\"hi\"},\"work_seconds\":1}'"
    echo "  Stop:    ./scripts/dev_down.sh"
    curl -s "http://127.0.0.1:${API_PORT}/health"
    echo
    exit 0
  fi
  i=$((i + 1))
  sleep 0.5
done

echo "API did not become healthy. Check logs in $RUN_DIR/" >&2
ls -la "$RUN_DIR" || true
tail -n 40 "$RUN_DIR/api.log" 2>/dev/null || true
exit 1
