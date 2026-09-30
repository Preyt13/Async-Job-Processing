# Droplet deploy (recommended over App Platform for this project)

Simplest production path on DigitalOcean: **one Droplet + Docker Compose**.

```text
GitHub Actions (pytest)
        │ pass on Main/main
        ▼
SSH → Droplet → git pull → docker compose up -d --build
```

You get API + worker + beat + Redis with one stack. No App Platform multi-component UI.

## 1) Create a Droplet (UI, ~2 minutes)

1. DigitalOcean → **Create** → **Droplets**
2. Image: **Ubuntu 24.04 LTS**
3. Size: **Basic** — 1 GB / 1 vCPU is enough to demo
4. Region: Bangalore (or nearest)
5. Auth: **SSH key** (add your public key)
6. Hostname: e.g. `async-jobs`
7. Create Droplet → copy the **public IPv4**

Open ports (Droplet firewall / cloud firewall):
- `22` (SSH)
- `80` (optional, if you terminate HTTP later)
- `8000` (API for the demo)

## 2) One-time setup on the Droplet

From your **Windows PowerShell** (or any machine with SSH):

```powershell
ssh root@YOUR_DROPLET_IP
```

Then on the Droplet:

```bash
curl -fsSL https://raw.githubusercontent.com/Preyt13/Async-Job-Processing/Main/infra/droplet/bootstrap.sh | bash
# OR if Main branch URL 404, clone first:
git clone -b Main https://github.com/Preyt13/Async-Job-Processing.git /opt/async-jobs
cd /opt/async-jobs
bash infra/droplet/bootstrap.sh
```

`bootstrap.sh` installs Docker, checks out the repo (if needed), and starts Compose.

Manual equivalent:

```bash
apt-get update && apt-get install -y git curl
curl -fsSL https://get.docker.com | sh
git clone -b Main https://github.com/Preyt13/Async-Job-Processing.git /opt/async-jobs
cd /opt/async-jobs
cp .env.docker .env
docker compose --env-file .env.docker up -d --build
curl -s http://127.0.0.1:8000/health
```

## 3) Test from your laptop

```powershell
curl http://YOUR_DROPLET_IP:8000/health

curl -X POST http://YOUR_DROPLET_IP:8000/jobs `
  -H "Content-Type: application/json" `
  -d "{\"data\":{\"task\":\"droplet\"},\"work_seconds\":1}"
```

## 4) GitHub Actions → Droplet deploy

Repo secrets:

| Secret | Value |
| --- | --- |
| `DROPLET_HOST` | Droplet public IP |
| `DROPLET_USER` | `root` (or your user) |
| `DROPLET_SSH_KEY` | Private SSH key (full PEM) that can log into the Droplet |

On push to `Main`/`main`: tests run → if green → SSH deploy.

## 5) Useful droplet commands

```bash
cd /opt/async-jobs
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f api worker
docker compose --env-file .env.docker up -d --build
```

## App Platform?

Kept under [`.do/app.yaml`](../../.do/app.yaml) if you want it later. For evaluation, **Droplet + Compose is the reliable path**.
