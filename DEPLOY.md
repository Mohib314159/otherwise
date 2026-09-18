# DEPLOY.md — putting Otherwise on a public URL

Written for a first deployment ever. Two routes; both are free and both deploy
automatically when you push to `main` on GitHub. Nothing here costs money, but
both need an account that only you can create.

## What gets deployed

One container (see `Dockerfile`) that runs the FastAPI backend and serves the
static frontend from `web/`. Showcase verdicts in `showcase/` are committed to
the repo, so the landing page never waits on a satellite read. Live runs read
Sentinel data from Microsoft Planetary Computer at request time.

There are no secrets: Planetary Computer, ESA WorldCover and the Copernicus DEM
are all anonymous. Never commit a `.env`.

## Route A (recommended): Hugging Face Spaces

Why: the free tier gives 2 vCPU and 16 GB RAM, enough for live runs. The Space
sleeps after 48 hours without visitors and wakes on the next visit (about a
minute).

1. Create a free account at https://huggingface.co/join.
2. Create a Space: https://huggingface.co/new-space. Name it `otherwise`,
   SDK = **Docker**, hardware = **CPU basic (free)**, visibility = public.
   Leave it empty.
3. Make a write token: Settings → Access Tokens → New token (type **Write**).
   Copy it once; it is only shown once.
4. In the GitHub repo: Settings → Secrets and variables → Actions → New
   repository secret, twice:
   - `HF_TOKEN` = the token from step 3
   - `HF_SPACE` = `your-hf-username/otherwise`
5. Push to `main` (or run the "Sync to Hugging Face Space" workflow from the
   Actions tab). The Space builds the Dockerfile (5-10 minutes the first time)
   and comes up at `https://your-hf-username-otherwise.hf.space`.
6. Open it. The showcase should load instantly; draw an area to test a live run.

The Space's disk is not persistent: live-run results survive until the Space
restarts. Showcase results are in the image, so they always survive.

## Route B: Render

Why: simplest "connect GitHub, click deploy". The free plan has 512 MB RAM and
a small CPU share, so live runs take longer (10+ minutes) and the service
spins down after 15 idle minutes (first visit afterwards takes ~1 minute).

1. Create a free account at https://render.com (sign in with GitHub).
2. New → **Blueprint**, pick this repo. Render reads `render.yaml`.
3. Click Apply. The service builds from the Dockerfile and gets a URL like
   `https://otherwise.onrender.com`.
4. If live runs time out on the free plan, set the environment variable
   `APP_LIVE_RUNS=0` in the Render dashboard: the site keeps working with the
   showcase examples and tells visitors that live runs are off.

## Running it on your own machine

```bash
pip install -r requirements.txt
uvicorn src.app.server:app --reload --port 8000
# open http://127.0.0.1:8000
```

## Adding a showcase example

1. Add the site to `SITES` in `scripts/run_sites.py` (a bbox or GeoJSON,
   the event date, the change type, the months to look after, the documented
   source and a one-line blurb). `expected` must come from the source; leave
   it blank if there is none.
2. Run `python -m scripts.run_sites <key>`. It writes `showcase/<id>.json`,
   the before/after thumbnails and updates `showcase/index.json`.
3. Commit `showcase/` and push. The landing page reads `index.json` in order.

## Adding a site to the track record

`python -m scripts.track_record` rebuilds `showcase/track_record.json` from
every entry in `showcase/index.json` that has an `expected` value, and never
counts a site without a source. Commit the result.
