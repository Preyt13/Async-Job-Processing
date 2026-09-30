#!/bin/sh
set -eu
exec celery -A app.celery_app.celery worker \
  --loglevel="${LOG_LEVEL}" \
  --concurrency="${CELERY_CONCURRENCY}" \
  -Q "${CELERY_QUEUE}"
