#!/bin/bash
# Run on the Droplet by GitHub Actions over SSH (or manually).
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/async-jobs}"
BRANCH="${REPO_BRANCH:-Main}"

cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps

echo "Waiting for /health..."
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/health; then
    echo
    echo "Deploy finished."
    exit 0
  fi
  sleep 2
done

echo "Health check failed after waiting. Recent API logs:" >&2
docker compose --env-file .env.docker logs --tail=80 api >&2
exit 1
