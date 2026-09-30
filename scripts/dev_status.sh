#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a
. "$ROOT/.env"
set +a
echo "== health =="
curl -s "http://127.0.0.1:${API_PORT}/health" || echo "API not reachable"
echo
echo "== processes =="
for name in api worker beat; do
  pidfile="$ROOT/.run/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name: running (pid $(cat "$pidfile"))"
  else
    echo "$name: not running"
  fi
done
if [ -x "$ROOT/.tools/redis-7.2.7/src/redis-cli" ]; then
  echo -n "redis: "
  "$ROOT/.tools/redis-7.2.7/src/redis-cli" ping 2>/dev/null || echo "down"
fi
