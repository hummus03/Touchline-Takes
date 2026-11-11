# Deploying Touchline Takes to touchlinetakes.com

There are two ways to run the site:

- **[Part 1: free](#part-1-free-github-actions--github-pages).** GitHub Actions runs the
  newsroom on a schedule, drafts arrive as pull requests for you to review, and GitHub
  Pages serves the site. No server, no cost beyond the domain. The trade-off: no live
  `/ask` page and no web admin page (you review on GitHub instead).
- **[Part 2: your own server](#part-2-your-own-server-docker).** The full Flask app with
  `/ask` and the admin page, in Docker. Needs a paid VPS or platform.

# Part 1: free (GitHub Actions + GitHub Pages)

## How it works

```
every 3 hours  ┌──────────────────── Newsroom workflow ────────────────────┐
               │ restore state → download results → run the newsroom → open │
               │ one pull request per approved draft → save state           │
               └───────────────────────────────────────────────────────────┘
you            merge a pull request to publish it, close it to reject it
on merge       ┌──────────────────── Deploy site workflow ─────────────────┐
               │ validate every article (no claim without a source) →       │
               │ build static pages → publish to GitHub Pages               │
               └───────────────────────────────────────────────────────────┘
```

- **Published articles** are files in `content/articles/*.json` on `main`. A review PR adds
  one file, so you can edit the wording in the PR before merging.
- **The deploy re-validates everything.** If a file has an unsourced claim, a non-http(s)
  link or a bad name, the build stops and the live site stays as it was. A separate check
  also runs on any pull request that edits an article.
- **The newsroom's memory** (its database and results data) is stored on the
  `newsroom-state` branch as a single commit that's replaced on every run, so it doesn't
  grow. Your repository is public, so that branch is public too: it holds drafts, rejected
  drafts and run logs, all built from public news.
- **There's an off switch.** Nothing runs until you set the repository variable
  `TOUCHLINE_LIVE` to `true`.

What I verified in the build sandbox: the full flow with a local stand-in for GitHub.
- Runs restored and saved the state branch.
- One review branch and PR was opened per draft, and nothing was sent twice, even after
  the state was wiped.
- Merging and then building produced a site with no broken links.
- Tampered article files were refused.
- `AUTO_PUBLISH` committed straight to `main`.
- `actionlint` reports no problems in the workflows.

What I could not do from the sandbox: run it on GitHub itself. Your first run (step 6
below) is the real test.

## Step by step

### 1. Make `main` the default branch

My work is on the branch `claude/touchline-takes-newsroom-bqvz5d`, which GitHub made the
default. The workflows expect `main`.

On GitHub, open your repository, go to **Settings → General → Default branch**, click the
✏️ next to the branch name, rename it to **`main`** and confirm.

### 2. Let Actions write to the repository and open pull requests

In **Settings → Actions → General → Workflow permissions**:
1. Select **Read and write permissions**.
2. Tick **Allow GitHub Actions to create and approve pull requests**.
3. Click **Save**.

### 3. Turn on GitHub Pages

In **Settings → Pages → Build and deployment → Source**, choose **GitHub Actions**.

### 4. Add your settings

In **Settings → Secrets and variables → Actions**:

**Variables tab:**

| Name | Value | |
|---|---|---|
| `TOUCHLINE_LIVE` | `true` | the on switch |
| `LLM_PROVIDER` | `offline` | free template writer (default). `anthropic` needs the secret below and costs money per article. |
| `LLM_MODEL` | `claude-haiku-5-5` | default in the workflow: roughly $2 a month at one run every 3 hours. `claude-sonnet-5-5` or `claude-opus-5-5` write better and cost about 15-40x more. Set a monthly spend limit in the Claude Console either way. |
| `AUTO_PUBLISH` | `false` | `true` skips your review and commits articles straight to `main` |
| `RESULTS_SEASONS` | `2425 2526 2627` | optional, this is the default |
| `RSS_FEEDS` | comma-separated feed URLs | optional, default is BBC Sport, The Guardian and Sky Sports football. Check each feed's terms. |

**Secrets tab:**

| Name | |
|---|---|
| `FOOTBALL_DATA_API_KEY` | free key from football-data.org, for fixtures, predictions and previews. Optional but recommended. |
| `ANTHROPIC_API_KEY` | only if `LLM_PROVIDER=anthropic` |

### 5. Point the domain at GitHub Pages (GoDaddy → DNS → DNS Records)

**Edit** the `A` record with name `@` (currently "Parked") so its value is
`185.199.108.153`. Then **add** three more `A` records, all with name `@`:

| Type | Name | Value |
|---|---|---|
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |

**Edit** the `CNAME` record named `www` so its value is **`hummus03.github.io`** (it currently
says `touchlinetakes.com`).

Optional, for IPv6: add `AAAA` records with name `@` and values `2606:50c0:8000::153`,
`2606:50c0:8001::153`, `2606:50c0:8002::153` and `2606:50c0:8003::153`.

Leave `NS`, `SOA`, `_domainconnect` and `_dmarc` alone, and don't use GoDaddy's "Connect
Domain" button.

Then, on GitHub, go to **Settings → Pages → Custom domain**, enter `touchlinetakes.com`
and click **Save**. Once the DNS check passes (minutes to a few hours), tick **Enforce
HTTPS**.

It's also worth verifying the domain, which stops anyone else from claiming it on GitHub
Pages. Go to your GitHub profile's **Settings → Pages → Add a domain** and add the `TXT`
record it shows you at GoDaddy.

### 6. First run

1. Go to the **Actions** tab, choose **Newsroom** and click **Run workflow** (on `main`).
   It takes about 3 minutes.
2. In the run log, check the "Run the newsroom" step: it should show stories stored from
   your feeds.
3. Open the **Pull requests** tab. Each draft is a PR labelled `newsroom-review`, with the
   article, its sources, what the Fact-checker and Editor sent back, and how to review.
4. **Merge** the ones you want published and **close** the rest.

Each merge triggers **Deploy site**, and the article is live a minute or two later. After
that, the newsroom runs by itself every 3 hours.

### Day to day

- **Review:** you'll get GitHub notifications for new review PRs. Merge to publish, close
  to reject. To change wording, edit the article file in the PR ("Files changed" → ⋯ →
  Edit file), then merge.
- **Pause it:** set `TOUCHLINE_LIVE` to `false`.
- **Problems:** a red ❌ in the Actions tab tells you which step failed. The most common
  causes are a missing permission (step 2) or Pages not set to GitHub Actions (step 3).
- **If `main` is protected** by a branch rule that requires pull requests,
  `AUTO_PUBLISH=true` can't push to it. Keep review mode in that case.

# Part 2: your own server (Docker)

## 1. Before you deploy (server)

These need you, a machine with normal internet access, or both:

- [ ] **Real results data.** Football-Data.co.uk CSVs. The container can download them on
      first start (`RESULTS_SEASONS`).
- [ ] **A football-data.org API key** (`FOOTBALL_DATA_API_KEY`, free tier) for real
      fixtures, predictions and previews. Without it the site simply has no previews.
- [ ] **An LLM key** (`ANTHROPIC_API_KEY`, or an OpenAI-compatible endpoint). The template
      writer works without one, but reads robotically.
- [ ] **Feed terms.** Check the terms of each RSS feed you use before publishing summaries
      of it on a commercial site. The defaults are BBC Sport, The Guardian and Sky Sports.
      Their RSS is offered for personal, non-commercial use, and articles here only link
      back and quote short facts, but read each outlet's current terms yourself. Drop any
      feed from `RSS_FEEDS` (the repository variable in static mode) to stop using it.
- [ ] **Legal pages.** Privacy notice and terms of use aren't built yet. The site sets no
      tracking cookies (only the admin session cookie), but you still need a privacy notice
      in most jurisdictions.
- [ ] **Photo tagger.** Keep `PHOTO_TAGGER=false` until it's retrained on real photos (it
      was trained on synthetic scenes).
- [ ] **DNS.** Control of the `touchlinetakes.com` DNS records.

## 2. What's in the box (server)

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
