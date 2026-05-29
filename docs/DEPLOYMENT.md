# VaP Deployment Guide

This document covers everything needed to run VaP in a production or shared environment — from a single container on a laptop to a cloud-hosted service.

---

## Contents

1. [Deployment Architectures](#deployment-architectures)
2. [Building the React UI](#building-the-react-ui)
3. [Single-Process Deployment](#single-process-deployment)
4. [Docker](#docker)
5. [Docker Compose](#docker-compose)
6. [Nginx Reverse Proxy](#nginx-reverse-proxy)
7. [Cloud Platforms](#cloud-platforms)
   - [Railway](#railway)
   - [Render](#render)
   - [Fly.io](#flyio)
8. [Environment Variables & Configuration](#environment-variables--configuration)
9. [SQLite in Production](#sqlite-in-production)
10. [Health Checks](#health-checks)
11. [Multi-Process & Remote Ingest](#multi-process--remote-ingest)
12. [Security Considerations](#security-considerations)

---

## Deployment Architectures

Choose the architecture that fits your scale:

| Architecture | Use case | Complexity |
|---|---|---|
| **Single process** | Personal use, demos, small teams | Minimal |
| **Docker / Docker Compose** | Repeatable deployments, CI | Low |
| **Nginx + containers** | Larger teams, TLS termination | Medium |
| **CDN + API** | High-traffic, global UI distribution | High |

---

## Building the React UI

Before any production deployment, build the React UI into static files:

```bash
cd ui
npm install
npm run build     # output → ui/dist/
```

`ui/dist/` will contain `index.html` and hashed JS/CSS bundles. These files are served as-is — no Node.js runtime is required at runtime.

---

## Single-Process Deployment

The simplest production setup: a single `vap serve` process serves both the REST API and the React UI.

```bash
# 1. Install the package
pip install -e ".[all]"

# 2. Build the UI
cd ui && npm run build && cd ..

# 3. Start the server
vap serve \
  --host 0.0.0.0 \
  --port 8001 \
  --db /var/data/vap.db \
  --static-dir ui/dist \
  --log-level info
```

Open `http://your-server:8001` — the UI and API are both served from the same origin, so no CORS configuration is needed.

### `--static-dir` option

When `--static-dir` is passed, the built React files are mounted at `/` after all API routes. The `index.html` is served as a catch-all for any path that is not an API endpoint (SPA routing support).

### Running as a systemd service

```ini
# /etc/systemd/system/vap.service
[Unit]
Description=VaP Visualization Agentic Process
After=network.target

[Service]
Type=simple
User=vap
WorkingDirectory=/opt/vap
ExecStart=/opt/vap/.venv/bin/vap serve \
  --host 0.0.0.0 \
  --port 8001 \
  --db /var/data/vap.db \
  --static-dir /opt/vap/ui/dist \
  --log-level info
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable vap
sudo systemctl start vap
```

---

## Docker

A multi-stage `Dockerfile` is included in the repository root. It builds the React UI in a Node image and copies the static output into a slim Python image.

### Build

```bash
docker build -t vap:latest .
```

### Run

```bash
# In-memory store (data lost on restart)
docker run -p 8001:8001 vap:latest

# Persistent SQLite on a host volume
docker run -p 8001:8001 \
  -v $(pwd)/data:/data \
  vap:latest
```

The container exposes port `8001`. By default it persists runs to `/data/vap.db` and serves the built UI.

### Customise the command

```bash
docker run -p 9000:9000 vap:latest \
  vap serve --host 0.0.0.0 --port 9000 --db /data/vap.db --static-dir ui/dist
```

---

## Docker Compose

`docker-compose.yml` in the repository root orchestrates the container with a named volume for SQLite persistence:

```bash
# Start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

The service is reachable at `http://localhost:8001`.

To customise the port or DB path, edit `docker-compose.yml` or override with environment variables:

```yaml
services:
  vap:
    build: .
    ports:
      - "8001:8001"
    volumes:
      - vap-data:/data
    restart: unless-stopped
```

---

## Nginx Reverse Proxy

Use Nginx when you need TLS termination, a custom domain, or to host VaP alongside other services.

### Configuration

```nginx
# /etc/nginx/sites-available/vap
server {
    listen 80;
    server_name vap.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name vap.example.com;

    ssl_certificate     /etc/letsencrypt/live/vap.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vap.example.com/privkey.pem;

    # Proxy all requests to the vap container / process
    location / {
        proxy_pass         http://127.0.0.1:8001;
        proxy_http_version 1.1;

        # Required for SSE (Server-Sent Events)
        proxy_set_header   Connection "";
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;

        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

> **Important:** `proxy_buffering off` and `proxy_read_timeout 3600s` are essential for the SSE event stream (`GET /runs/{id}/events`) to work correctly. Without them, the browser will not receive live events.

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/vap /etc/nginx/sites-enabled/
sudo nginx -t && sudo nginx -s reload
```

### Obtain a TLS certificate with Let's Encrypt

```bash
sudo certbot --nginx -d vap.example.com
```

---

## Cloud Platforms

### Railway

1. Push your repository to GitHub.
2. In the Railway dashboard, click **New Project → Deploy from GitHub repo**.
3. Railway auto-detects the `Dockerfile` and builds it.
4. Add a **Volume** mounted at `/data` for SQLite persistence.
5. Set the **Start command** (or rely on the Dockerfile `CMD`):
   ```
   vap serve --host 0.0.0.0 --port $PORT --db /data/vap.db --static-dir ui/dist --log-level info
   ```
6. Set the `PORT` environment variable in Railway's settings panel (Railway injects this automatically).
7. Open the generated Railway URL — VaP is live.

### Render

1. Create a new **Web Service** from your GitHub repo.
2. Set **Environment** to `Docker`.
3. Set **Instance Type** to at least the free tier (512 MB RAM is sufficient).
4. Add a **Persistent Disk** mounted at `/data`.
5. Override the start command if needed:
   ```
   vap serve --host 0.0.0.0 --port 10000 --db /data/vap.db --static-dir ui/dist
   ```
   (Render's default port is `10000`; set it to match your `PORT` env var.)
6. Deploy — Render builds the Dockerfile and starts the service.

### Fly.io

```bash
# Install flyctl and log in
curl -L https://fly.io/install.sh | sh
fly auth login

# Launch from the repo root (detects Dockerfile automatically)
fly launch --name my-vap --region lax --no-deploy

# Add a persistent volume for SQLite
fly volumes create vap_data --size 1  # GB

# Edit fly.toml to mount the volume and set the port
```

`fly.toml`:
```toml
[build]
  dockerfile = "Dockerfile"

[[mounts]]
  source      = "vap_data"
  destination = "/data"

[http_service]
  internal_port = 8001
  force_https   = true

[[vm]]
  memory = "512mb"
  cpu_kind = "shared"
  cpus = 1
```

```bash
# Deploy
fly deploy
```

Open `https://my-vap.fly.dev` to access the UI.

---

## Environment Variables & Configuration

VaP itself does not read environment variables directly — all configuration is passed via CLI arguments or the Python `vap.configure()` API. However, you can wire environment variables into the start command:

```bash
# Shell / systemd / Docker ENV
export VAP_DB_PATH=/var/data/vap.db
export VAP_PORT=8001

vap serve --host 0.0.0.0 --port "$VAP_PORT" --db "$VAP_DB_PATH" --static-dir ui/dist
```

### All `vap serve` options

| Option | Default | Description |
|---|---|---|
| `--host` | `0.0.0.0` | Network interface to bind |
| `--port` | `8001` | TCP port |
| `--db` | *(none)* | SQLite path; omit for in-memory |
| `--static-dir` | *(none)* | Serve built React UI from this directory |
| `--reload` | off | Uvicorn auto-reload (dev only) |
| `--log-level` | `warning` | `debug` / `info` / `warning` / `error` |

---

## SQLite in Production

VaP's SQLite backend is suitable for single-server production deployments with moderate write rates (hundreds of agent runs per hour).

### File location

Store the database file on a persistent disk, not in the container's ephemeral filesystem:

```
/var/data/vap.db         # Linux VM
/data/vap.db             # Docker volume mount
```

### WAL mode

VaP enables `PRAGMA journal_mode=WAL` automatically. WAL allows concurrent reads and a single writer without blocking, which is ideal for VaP's access pattern (tracer writes one event at a time while FastAPI serves multiple SSE readers).

### Backups

SQLite's WAL mode can be backed up safely with a standard file copy if done during low-write periods, or via the SQLite Online Backup API:

```bash
# Safe hot backup (no downtime)
sqlite3 vap.db ".backup /backup/vap-$(date +%Y%m%d).db"
```

Or as a cron job:

```bash
0 2 * * * sqlite3 /data/vap.db ".backup /backup/vap-$(date +\%Y\%m\%d).db"
```

### Storage estimates

| Activity | Events/run | Bytes/event | 1 000 runs |
|---|---|---|---|
| Simple agent (5 steps) | ~10 | ~500 B | ~5 MB |
| LLM-heavy (20 nodes) | ~40 | ~2 KB | ~80 MB |

SQLite handles tens of millions of rows without issue; disk space is the only practical limit.

### Scaling limits

SQLite is a single-file database with serialised writes. For deployments with **many concurrent agent runs writing simultaneously from multiple processes**, consider:
- Using the remote ingest API (`POST /runs/{id}/events`) with a single VaP server as the event hub
- Or switching to a PostgreSQL-backed store (not yet built-in; see [Adding a custom store](ARCHITECTURE.md#implementing-a-custom-store-backend))

---

## Health Checks

The simplest health check pings `GET /runs`, which returns `200 OK` with an empty JSON array if the store is up:

```bash
curl -sf http://localhost:8001/runs > /dev/null && echo "OK"
```

### Docker health check (included in docker-compose.yml)

```yaml
healthcheck:
  test: ["CMD", "python", "-c",
         "import urllib.request; urllib.request.urlopen('http://localhost:8001/runs')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

### Kubernetes liveness/readiness probe

```yaml
livenessProbe:
  httpGet:
    path: /runs
    port: 8001
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /runs
    port: 8001
  initialDelaySeconds: 5
  periodSeconds: 10
```

---

## Multi-Process & Remote Ingest

VaP supports tracing agents that run in separate processes or on separate machines via the HTTP ingest endpoint.

### Architecture

```
┌──────────────────────────┐      POST /runs/{id}/events
│  Agent Process A         │ ──────────────────────────────┐
│  (Python, any language)  │                               │
└──────────────────────────┘                               ▼
                                              ┌────────────────────┐
┌──────────────────────────┐                  │  VaP Server        │
│  Agent Process B         │ ────────────────►│  (single process)  │
└──────────────────────────┘                  │  SQLite or memory  │
                                              └────────────────────┘
                                                        │
                                               SSE stream ▼
                                              ┌────────────────────┐
                                              │  Browser UI        │
                                              └────────────────────┘
```

### Python example

```python
import httpx, time, uuid

SERVER = "http://vap.example.com:8001"
run_id = uuid.uuid4().hex[:12]
root_id = uuid.uuid4().hex[:12]

def post(event: dict):
    httpx.post(f"{SERVER}/runs/{run_id}/events", json=event, timeout=5)

# Open run
post({
    "id": uuid.uuid4().hex[:12], "run_id": run_id,
    "timestamp": time.time(), "type": "agent_start",
    "node_id": root_id, "node_kind": "agent",
    "node_label": "My Remote Agent", "parent_id": None,
    "data": {"label": "My Remote Agent"}, "schema_version": 1,
})

# ... your agent logic with step open/close events ...

# Close run
post({
    "id": uuid.uuid4().hex[:12], "run_id": run_id,
    "timestamp": time.time(), "type": "agent_end",
    "node_id": root_id, "node_kind": "agent",
    "node_label": "My Remote Agent", "parent_id": None,
    "data": {}, "schema_version": 1,
})
```

The VaP server is language-agnostic — any HTTP client can push events (Node.js, Go, Java, curl, etc.).

---

## Security Considerations

VaP ships with **no authentication** — it is designed for internal developer tooling, not public-facing services. Before exposing VaP to the internet:

### Network isolation (recommended)

- Bind to `127.0.0.1` (localhost only) and access via SSH tunnel or VPN:
  ```bash
  vap serve --host 127.0.0.1 --port 8001 --db vap.db --static-dir ui/dist
  ```
- In Docker Compose, avoid publishing the port to `0.0.0.0` unless behind Nginx with auth.

### Basic authentication via Nginx

```nginx
location / {
    auth_basic           "VaP";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass           http://127.0.0.1:8001;
    # ... SSE headers (see above)
}
```

Create credentials:
```bash
sudo htpasswd -c /etc/nginx/.htpasswd alice
```

### TLS

Always use HTTPS in production. The [Nginx section](#nginx-reverse-proxy) above shows how to obtain free certificates via Let's Encrypt / Certbot.

### CORS

VaP's FastAPI app allows all origins by default (`allow_origins=["*"]`). If you serve the UI and API from the same origin (recommended via `--static-dir`), this is not a concern. If they are on different origins, restrict the `allow_origins` list by passing a custom `CORSMiddleware` configuration or creating the app with a patched server module.

### Sensitive data in traces

VaP stores everything passed to `step.set_input()` / `step.set_output()`. Avoid tracing PII or secrets. Use summary values instead of raw payloads when tracing production agents:

```python
# ✗ Don't trace raw API responses containing PII
step.set_output({"response": full_api_response})

# ✓ Trace summaries
step.set_output({"row_count": len(data), "status": "ok"})
```
