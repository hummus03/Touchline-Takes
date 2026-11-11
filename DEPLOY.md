# Deploying Touchline Takes to touchlinetakes.com

This guide takes the newsroom from your laptop to the public site. The app is built so
that it **refuses to start in production** until the settings are safe and the data is
real. `python -m touchline_takes.preflight` tells you what's missing.

## 1. Before you deploy

These need you, a machine with normal internet access, or both:

- [ ] **Real results data.** Football-Data.co.uk CSVs. The container can download them on
      first start (`RESULTS_SEASONS`).
- [ ] **A football-data.org API key** (`FOOTBALL_DATA_API_KEY`, free tier) for real
      fixtures, predictions and previews. Without it the site simply has no previews.
- [ ] **An LLM key** (`ANTHROPIC_API_KEY`, or an OpenAI-compatible endpoint). The template
      writer works without one, but reads robotically.
- [ ] **Feed terms.** Check the terms of each RSS feed you use before publishing summaries
      of it on a commercial site.
- [ ] **Legal pages.** Privacy notice and terms of use aren't built yet. The site sets no
      tracking cookies (only the admin session cookie), but you still need a privacy notice
      in most jurisdictions.
- [ ] **Photo tagger.** Keep `PHOTO_TAGGER=false` until it's retrained on real photos (it
      was trained on synthetic scenes).
- [ ] **DNS.** Control of the `touchlinetakes.com` DNS records.

## 2. What's in the box

| File | Purpose |
|---|---|
| `Dockerfile` | One image for the site and the scheduler. Python 3.13, non-root user, one persistent volume at `/data`, healthcheck on `/healthz`. |
| `docker/entrypoint.sh` | Modes: `web` (gunicorn), `scheduler` (pipeline every `SCHEDULE_MINUTES`), `all` (both, for hosts with one container per disk). Any other argument runs as a command. |
| `docker-compose.yml` + `deploy/Caddyfile` | Single-VPS setup: web, scheduler and Caddy, which provides automatic HTTPS. |
| `deploy/production.env.example` | Every production setting, documented. Copy it to `.env.production` (git-ignored). |
| `touchline_takes/preflight.py` | The production checks. They run at startup and on demand. |

**Everything persistent lives in `/data`:**
- the SQLite database (WAL mode, shared safely by web and scheduler)
- LangGraph checkpoints, which hold runs paused for review
- the Chroma index
- trained models
- downloaded results CSVs
- the Keras weights cache

**What production mode (`TOUCHLINE_ENV=production`, the image default) changes:**

- **Preflight blocks startup** on any of these:
  - a weak or missing `SECRET_KEY` or `ADMIN_PASSWORD`
  - a non-HTTPS `SITE_URL`
  - offline mode
  - synthetic or missing results data
  - a database that contains sample stories
  - `ALLOW_SAMPLE_DATA=true`
- **It never falls back to sample data.** If every feed fails, nothing is published. If
  the fixtures API fails, there are no fixtures.
- **Hardening:**
  - security headers, including a strict CSP (the site uses no JavaScript)
  - HSTS
  - secure session cookies
  - `robots.txt`, which keeps crawlers out of `/admin`
  - branded 404 and 500 pages
- **Rate limits:** `/ask` and failed admin logins are rate-limited per client IP.
- **Runs come from the scheduler only.** The admin page can't trigger them, which avoids
  long web requests.
- **The web process never writes to the Chroma index.** `/ask` uses an in-memory index
  synced from the database.

Generate secrets with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Option A (recommended): one VPS with Docker Compose

A small VPS is enough: 2 vCPU, 4 GB RAM, about 10 GB disk. The image is about 1.9 GB,
mostly ChromaDB's ONNX runtime, JAX, SciPy and pandas. This is the setup I tested end to
end in the build sandbox: Compose with Caddy on HTTPS, with the scheduler publishing a
story that the web container then served.

Install Docker on the server, then:

```bash
git clone https://github.com/hummus03/Touchline-Takes.git && cd Touchline-Takes
```

```bash
cp deploy/production.env.example .env.production
```

Fill in `.env.production`: `SECRET_KEY`, `ADMIN_PASSWORD`, `FOOTBALL_DATA_API_KEY`,
`ANTHROPIC_API_KEY`, `RESULTS_SEASONS`. Then check it before starting anything:

```bash
docker compose build
```

```bash
docker compose run --rm web python -m touchline_takes.preflight
```

The only remaining error should be the results data, which is downloaded on first start
when `RESULTS_SEASONS` is set. To fetch it now instead:

```bash
docker compose run --rm web python scripts/download_football_data.py --league E0 --seasons 2425 2526 2627
```

Point DNS at the server: an `A` record (and `AAAA` if you have IPv6) for
`touchlinetakes.com` and `www.touchlinetakes.com`. Then start everything:

```bash
docker compose up -d
```

Caddy gets a Let's Encrypt certificate automatically once DNS resolves to the server.
`www` redirects to the bare domain. Check it:

```bash
docker compose ps
```

```bash
docker compose logs -f scheduler
```

```bash
curl https://touchlinetakes.com/healthz
```

**Reviewing drafts:** `AUTO_PUBLISH=false` is the default. Each scheduler run pauses at
human review. Approve or reject drafts at `https://touchlinetakes.com/admin` (user `admin`,
your `ADMIN_PASSWORD`), or from the server:

```bash
docker compose exec web python -m touchline_takes.review list
```

## 4. Option B: a platform with one container and one disk (Fly.io, Render)

These platforms attach a disk to **one** machine, so web and scheduler must share a
container. Use the image's default `all` mode, and **scale to exactly one instance**:
SQLite doesn't support multiple hosts. Set `PROXY_HOPS=1` because the platform's proxy
sits in front.

> I couldn't test these two from the build sandbox (no accounts). The settings below
> follow each platform's documented Docker and volume setup; check them against the
> current docs when you deploy.

**Fly.io**, `fly.toml`:

```toml
app = "touchline-takes"
primary_region = "lhr"

[env]
  SITE_URL = "https://touchlinetakes.com"
  PROXY_HOPS = "1"
  RESULTS_SEASONS = "2425 2526 2627"
  PHOTO_TAGGER = "false"

[[mounts]]
  source = "touchline_data"
  destination = "/data"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "off"   # the scheduler must keep running
  min_machines_running = 1

  [[http_service.checks]]
    method = "GET"
    path = "/healthz"
    interval = "30s"
    timeout = "5s"
    grace_period = "60s"
```

```bash
fly launch --no-deploy
```

```bash
fly volumes create touchline_data --size 5
```

```bash
fly secrets set SECRET_KEY=... ADMIN_PASSWORD=... FOOTBALL_DATA_API_KEY=... LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...
```

```bash
fly deploy
```

```bash
fly certs add touchlinetakes.com
```

**Render:** create a *Web Service* from the repo with runtime *Docker*, **1 instance**, a
*Disk* mounted at `/data`, health check path `/healthz`, and the variables from
`deploy/production.env.example` plus `PROXY_HOPS=1`. Then add the custom domain in
Render's settings.

## 5. Running it

- **Logs:** gunicorn access logs and the scheduler's per-agent log go to stdout. The
  admin page also shows the agent log, rejections and recent runs.
- **Monitoring:** point an uptime monitor at `/healthz`. It returns 200 when the app and
  the database answer.
- **Backups:** everything lives in `/data`. Take a consistent SQLite copy while running:

  ```bash
  docker compose exec web python -c "import sqlite3; s=sqlite3.connect('/data/touchline_takes.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
  ```

  Then copy `/data/backup.db` and `/data/checkpoints.db` off the server.
- **Updates:** run the following. Running containers receive SIGTERM; the scheduler
  finishes its current run, then exits cleanly.

  ```bash
  git pull && docker compose up -d --build
  ```

- **Costs:** `LLM_MAX_CALLS_PER_RUN` caps uncached LLM calls per run. Responses are cached
  in the database.

## 6. Known limits

- **Rate limits are per worker process.** With `WEB_CONCURRENCY=2` the effective `/ask`
  limit is up to twice the setting. Fine for a small site; use a CDN or WAF limit if
  traffic grows.
- **Brute-force lockout catches the right password too.** After too many failed admin
  logins (`ADMIN_AUTH_RATE_LIMIT`), that IP is locked out for the window even with the
  correct password.
- **Single host only.** Scaling beyond one host means moving from SQLite to Postgres and
  from the in-process scheduler to a job queue.
- **Some features are still missing:** legal pages, an email alert when drafts await
  review, and a sitemap beyond the RSS feed.
