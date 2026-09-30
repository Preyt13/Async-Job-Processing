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
curl -sf http://127.0.0.1:8000/health
echo
echo "Deploy finished."
