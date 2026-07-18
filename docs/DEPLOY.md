# Deploying to Vercel

**What deploys:** the dashboard is a self-contained static site
(`dashboards/html/`), so it hosts perfectly on Vercel's static/edge network.

**What does *not* run on Vercel:** the always-on refresh server (`src/serve.py`)
and its `/api/refresh` · `/api/report.pdf` endpoints. Vercel is serverless — no
long-running process, no background loop, an ephemeral read-only filesystem — so
the live "Refresh now" button and on-demand PDF generation can't run there. The
dashboard detects this automatically: on a static host it switches to **snapshot
mode** (hides the refresh button, shows a "Snapshot · <date>" pill) and the
**⬇ PDF** button serves the pre-built `amex_executive_report.pdf` that ships
alongside the page.

Freshness is handled instead by a **GitHub Action** (`.github/workflows/refresh.yml`)
that regenerates the data on a schedule and pushes — Vercel redeploys on every
push, so the deployed snapshot stays current without a live backend.

---

## 1. One-time setup

Make sure these committed files exist in `dashboards/html/` (the pipeline
generates them): `index.html`, `data.json`, `data.js`, `version.json`,
`amex_executive_report.pdf`, `amex_dashboard_standalone.html`. If not:

```bash
python -m src.pipeline          # builds data.json / data.js
python -m src.report && cp reports/amex_executive_report.pdf dashboards/html/
python scripts/build_standalone.py
```

`vercel.json` (already in the repo root) points Vercel at `dashboards/html`:

```json
{ "outputDirectory": "dashboards/html", "cleanUrls": true }
```

## 2. Deploy

**Option A — Vercel dashboard (no CLI):**
1. Push the repo to GitHub (see the repo README).
2. Go to <https://vercel.com/new> → **Import** `code-shm/AMEX-MIS-App`.
3. Framework preset: **Other**. Leave build command empty; Output Directory is
   read from `vercel.json` (`dashboards/html`).
4. **Deploy.** You get a `https://<project>.vercel.app` URL.

**Option B — Vercel CLI:**
```bash
npm i -g vercel
vercel            # first run links/creates the project (accept defaults)
vercel --prod     # promote to production
```

## 3. Keep it fresh (auto-update)

The included workflow refreshes daily and on demand:

- **Enable it:** it runs automatically once the repo is on GitHub. Trigger a test
  run from **Actions → "Refresh dashboard data" → Run workflow**.
- Each run re-pulls the CFPB Amex feed, re-scores, rebuilds `data.json` + the
  PDF, and commits them. Vercel auto-redeploys on the push.
- Change the cadence by editing the `cron` in `.github/workflows/refresh.yml`.

> The industry-benchmark panel relies on the two small precomputed MIS parquet
> files (kept in the repo via `.gitignore` exceptions). The 17M-row MIS pass is
> **not** re-run in CI — regenerate it locally with `python -m src.mis_aggregate`
> and commit the refreshed `data/outputs/mis_*.parquet` when you want it updated.

---

## Want the *live* server (real-time Refresh button + dynamic PDF)?

`src/serve.py` is cloud-ready — it reads `$PORT` and binds `0.0.0.0`
automatically when a host injects it. Deploy to any host that allows a
long-running process:

**Render (blueprint included):** push to GitHub → Render → **New → Blueprint** →
pick the repo. `render.yaml` sets it up (`pip install -r requirements.txt`, start
`python -m src.serve`, health check `/api/status`).

**Railway / Heroku:** the included `Procfile` (`web: python -m src.serve`) is
detected automatically — just create a service from the repo.

**Fly.io / any VM:** `pip install -r requirements.txt` then
`python -m src.serve --host 0.0.0.0 --port 8080`.

On these hosts the deployed dashboard shows the live pill, a working **Refresh
now** button, and server-generated PDFs — the full agentic experience. (Free
tiers sleep when idle; the first visit wakes the dyno and a visitor can refresh
on demand.)

> Vercel remains the best home for the fast, free **static** dashboard; use a
> long-running host only if you specifically want the live Refresh button online.
