#!/bin/sh
set -eu
# DigitalOcean App Platform injects PORT; local/dev uses API_PORT from .env
bind_port="${PORT:-${API_PORT}}"
exec uvicorn app.main:app --host "${API_HOST}" --port "${bind_port}"
