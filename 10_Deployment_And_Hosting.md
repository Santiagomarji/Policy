# 10 — Deployment & Hosting (3 Ways, Independent of Amazon)

*Orbit's buildable core is a pure-standard-library Python app. It has **zero
runtime dependencies** and stores state in a **local JSON file**, so it runs
anywhere Python or Docker runs — on your laptop, a $5 VPS, or any container
host. Nothing here depends on AWS or any internal Amazon system.*

The code lives in `code/`. All three options serve the same
`orbit.api` HTTP service and persist to a JSON file (swap for PostgreSQL via
`code/migrations/0001_init.sql` when you outgrow single-file storage).

---

## Prerequisites (all options)
- The `code/` directory (the `orbit` package + `pyproject.toml`).
- Option A needs only **Python 3.10+**. Options B and C need **Docker**.
- No API keys, no cloud account, no external services required to run.

---

## Way 1 — Run it directly with Python (simplest; laptop or any VPS)

Zero installs. Good for local use, demos, or a small single-city club on a
plain Linux box.

```bash
cd code

# Start the API (serves on 127.0.0.1:8080, stores in ./orbit.json)
python -m orbit.api

# Or bind publicly on a VPS and choose a data path:
ORBIT_HOST=0.0.0.0 ORBIT_PORT=8080 ORBIT_DB=/var/lib/orbit/orbit.json python -m orbit.api
```

Smoke test:
```bash
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/clubs \
     -H 'Content-Type: application/json' \
     -d '{"name":"My Club","city":"Austin","min_density":6}'
```

**Keep it running** on a VPS with a systemd unit (`/etc/systemd/system/orbit.service`):
```ini
[Unit]
Description=Orbit API
After=network.target

[Service]
WorkingDirectory=/opt/orbit/code
Environment=ORBIT_HOST=0.0.0.0
Environment=ORBIT_PORT=8080
Environment=ORBIT_DB=/var/lib/orbit/orbit.json
ExecStart=/usr/bin/python3 -m orbit.api
Restart=always
User=orbit

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now orbit
```
Put **Caddy or nginx** in front for TLS if you expose it to the internet.

- **Pros:** dead simple, no Docker, no deps.
- **Cons:** you manage the process/OS yourself; single node.

---

## Way 2 — Docker on any host (portable; self-hosted single node)

Runs identically on your machine or any VPS/cloud VM. The JSON store lives in
a named volume so data survives restarts and redeploys.

```bash
cd code

# Build + run with compose (recommended)
docker compose up -d --build

# ...or plain docker
docker build -t orbit-api .
docker run -d --name orbit-api -p 8080:8080 -v orbit-data:/data orbit-api
```

Smoke test: `curl http://localhost:8080/health`

The included `Dockerfile`:
- uses `python:3.12-slim`, installs **nothing** (no deps),
- runs as a **non-root** user,
- exposes `/data` as a volume for the JSON store,
- has a built-in `HEALTHCHECK` hitting `/health`.

- **Pros:** portable, reproducible, easy to move between hosts/clouds.
- **Cons:** still a single node unless you add an external DB + load balancer.

---

## Way 3 — Managed container platform (no servers to manage)

Deploy the same Docker image to any managed container/PaaS host that is **not
Amazon** — e.g. **Fly.io, Render, Railway, Google Cloud Run, Azure Container
Apps, or DigitalOcean App Platform**. They build from the `Dockerfile` and run
it for you.

Because these platforms have **ephemeral local disk**, the JSON file will not
persist across redeploys/instances. Two clean choices:

**3a. Attach a persistent volume** (Fly.io volumes, Render disks):
- Mount it at `/data` and set `ORBIT_DB=/data/orbit.json`. Single instance.

**3b. Switch to PostgreSQL** (recommended for real multi-instance hosting):
- Provision a managed Postgres (Neon, Supabase, Render/Railway Postgres, etc.).
- Apply the schema: `psql "$DATABASE_URL" -f code/migrations/0001_init.sql`.
- Implement a `PostgresRepository` with the **same method names** as
  `JsonFileRepository` (see `code/README.md` → "growing into the full stack").
  No service or engine code changes.

Example — **Fly.io**:
```bash
cd code
fly launch --no-deploy          # detects the Dockerfile, creates fly.toml
fly volumes create orbit_data --size 1
# set the mount in fly.toml:  [mounts] source="orbit_data" destination="/data"
fly secrets set ORBIT_DB=/data/orbit.json
fly deploy
```

Example — **Google Cloud Run** (use 3b, Postgres, since Cloud Run disk is ephemeral):
```bash
cd code
gcloud run deploy orbit-api --source . --port 8080 --allow-unauthenticated
# set DATABASE_URL as a Cloud Run env var / secret and use the Postgres repo
```

- **Pros:** no server management, scales, HTTPS included.
- **Cons:** ephemeral disk means you should use Postgres (3b) for anything real.

---

## Choosing

| Need | Use |
|------|-----|
| Try it now / demo / smallest footprint | **Way 1** (Python direct) |
| Portable, reproducible, one box you control | **Way 2** (Docker / compose) |
| Hands-off hosting, HTTPS, room to scale | **Way 3** (managed + Postgres 3b) |

## Data & migration path
- Start on the **JSON file** (Ways 1–2, or 3a with a volume).
- Move to **PostgreSQL** (Way 3b) when you need multiple instances, real
  concurrency, or analytics. The schema is ready in
  `code/migrations/0001_init.sql`; the repository interface stays identical.

## Security notes for public hosting
- Put TLS in front (Caddy/nginx for Ways 1–2; managed platforms include it).
- The stdlib server is fine for small scale; for higher traffic, front it with
  a reverse proxy or move to the Postgres-backed setup behind a WSGI/ASGI
  server as described in `../09_File_Manifest.md`.
- Add authentication before exposing write endpoints publicly (the buildable
  core ships without auth — see FR-01/NFR-05 in `../05_Requirements.md`).

---

*Everything above is provider-neutral and runs entirely outside Amazon. No AWS,
no internal tooling, no vendor lock-in.*

---

## The web UI and auth (applies to all 3 ways)

- The API serves a **single-file web UI at `GET /`** (from `code/orbit/web/index.html`).
  Just open the server's root URL in a browser — no separate build or host needed.
  You can also host the HTML file anywhere static and point its **API base** field
  at your server.
- Set **`ORBIT_TOKEN`** to require a token on write endpoints (reads stay open).
  The UI sends it as the `X-Orbit-Token` header; enter it in the UI's **Token** field.
- **`DATABASE_URL`** switches storage from the local JSON file to PostgreSQL
  (apply `code/migrations/0001_init.sql` first and `pip install "psycopg[binary]"`).
  This is the recommended path for Way 3 (managed hosts with ephemeral disk).
