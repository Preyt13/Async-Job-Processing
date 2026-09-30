#!/bin/sh
set -eu
exec celery -A app.celery_app.celery beat --loglevel="${LOG_LEVEL}"
