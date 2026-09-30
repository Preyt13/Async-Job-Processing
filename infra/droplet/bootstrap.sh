#!/bin/bash
# One-time (or idempotent) bootstrap on a DigitalOcean Droplet.
# Usage (on the droplet):
#   bash infra/droplet/bootstrap.sh
# Or after cloning:
#   cd /opt/async-jobs && bash infra/droplet/bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Preyt13/Async-Job-Processing.git}"
REPO_BRANCH="${REPO_BRANCH:-Main}"
APP_DIR="${APP_DIR:-/opt/async-jobs}"

export DEBIAN_FRONTEND=noninteractive

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin missing; reinstalling docker..."
  curl -fsSL https://get.docker.com | sh
fi

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Cloning $REPO_URL ($REPO_BRANCH) → $APP_DIR"
  rm -rf "$APP_DIR"
  git clone -b "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
else
  echo "Updating existing checkout..."
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout "$REPO_BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
fi

cd "$APP_DIR"
cp -n .env.docker .env 2>/dev/null || cp .env.docker .env

echo "Starting stack..."
docker compose --env-file .env.docker up -d --build

echo "Waiting for health..."
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    curl -s http://127.0.0.1:8000/health
    echo
    echo "Deploy OK. Public test: curl http://$(curl -s ifconfig.me):8000/health"
    exit 0
  fi
  sleep 2
done

echo "Health check failed. Logs:" >&2
docker compose --env-file .env.docker logs --tail=80
exit 1
