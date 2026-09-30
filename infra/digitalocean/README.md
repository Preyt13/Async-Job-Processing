# DigitalOcean App Platform

Deploy the async job API, Celery worker, Celery Beat, and managed Valkey
(Redis-compatible) as one App Platform application.

## Topology

```text
Internet
   │
   ▼
┌─────────────┐     ┌──────────────────┐
│  api (web)  │────►│ jobs-redis       │
│  :8080      │     │ (managed Valkey) │
└─────────────┘     └────────▲─────────┘
                             │
┌─────────────────┐          │
│ celery-worker   │──────────┤
└─────────────────┘          │
┌─────────────────┐          │
│ celery-beat (1) │──────────┘
└─────────────────┘
```

| Component | Type | Role |
| --- | --- | --- |
| `api` | service | FastAPI HTTP (`POST/GET /jobs`, DLQ, health) |
| `celery-worker` | worker | Processes jobs from the Celery queue |
| `celery-beat` | worker | Schedules stuck-job reaper + TTL purge (**always 1 instance**) |
| `jobs-redis` | database | Job state, idempotency, DLQ, Celery broker |

Spec file: [`.do/app.yaml`](../../.do/app.yaml)

## CI/CD from GitHub Actions

After the app exists and secrets are set, every push to `main` that passes
tests triggers:

```text
pytest → doctl apps update --spec → doctl apps create-deployment --wait
```

Required GitHub Actions secrets:

- `DIGITALOCEAN_ACCESS_TOKEN`
- `DIGITALOCEAN_APP_ID`

See root [README](../../README.md#cicd-github-actions) for details.

## Prerequisites

1. DigitalOcean account + [doctl](https://docs.digitalocean.com/reference/doctl/)
2. GitHub (or GitLab) repo with this project
3. `doctl auth init`

## One-time setup

1. Edit [`.do/app.yaml`](../../.do/app.yaml): replace **all three** `YOUR_GITHUB_ORG/async-job-processing` values with your repo.
2. Optional: change `region`, instance sizes, or Valkey size.
3. Create the app:

```bash
doctl apps create --spec .do/app.yaml
```

4. Note the app id and live URL:

```bash
doctl apps list
doctl apps get <APP_ID>
```

## Updates

```bash
doctl apps update <APP_ID> --spec .do/app.yaml
```

Or push to `main` when `deploy_on_push: true`.

## Smoke test after deploy

```bash
APP_URL="https://<your-app>.ondigitalocean.app"

curl -s "$APP_URL/health"
# {"status":"ok","redis":"ok","queue":"celery"}

curl -s -X POST "$APP_URL/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"data": {"task": "do-smoke"}, "work_seconds": 1}'

# poll with returned id
curl -s "$APP_URL/jobs/<id>"
```

## Scaling

| Knob | Where |
| --- | --- |
| More HTTP capacity | `services.api.instance_count` / larger `instance_size_slug` |
| More job throughput | `workers.celery-worker.instance_count` and/or `CELERY_CONCURRENCY` |
| Beat | **Never** scale above `instance_count: 1` |

## Cost notes (dev defaults)

Current spec uses `basic-xxs` compute and a small non-production Valkey node.
Raise sizes before production load.

## Local vs DigitalOcean

| | Local (this repo) | App Platform |
| --- | --- | --- |
| Redis | `./scripts/run_redis.sh` or Compose | Managed Valkey (`${jobs-redis.DATABASE_URL}`) |
| API / worker / beat | `./scripts/run_*.sh` | App components from same Dockerfile |
| Config | `.env` | App-level `envs` in `.do/app.yaml` |
| TLS to Redis | usually off (`redis://`) | on (`rediss://`) — handled in code |

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Deploy build fails | Dockerfile path, `.dockerignore`, GitHub access |
| `/health` redis error | Valkey binding, TLS (`rediss://`), component logs |
| Jobs stuck `queued` | `celery-worker` running; same `CELERY_QUEUE` / broker URL |
| Duplicate scheduled reap | Beat `instance_count` must be `1` |
