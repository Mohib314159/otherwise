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

## Route A: Hugging Face Spaces — needs a PRO subscription ($9/month)

**Corrected 2026-09-19. This route is no longer free, and this guide used to say
it was.** Hugging Face now requires a paid plan to create a Space that runs on
compute. From their own documentation
(https://huggingface.co/docs/hub/spaces-overview, read 2026-09-19):

> Static Spaces are free for everyone. Gradio and Docker Spaces run on compute
> and require a paid plan to create: PRO for personal accounts, Team or
> Enterprise for organizations.

This app needs a **Docker** Space, so it needs PRO, listed at "$9 /month" on
https://huggingface.co/pricing (read 2026-09-19). The hardware itself (CPU
Basic: 2 vCPU, 16 GB RAM) still has no hourly cost — it is the account plan that
costs money. The `hf-sync` workflow in this repo is still correct; only the price
changed.

Worth knowing before you decide: 16 GB of RAM is enough to run the **full**
profile, which would remove the accuracy caveat that live runs on a 512 MB box
currently carry (see `docs/LIVE_RUNS_DESIGN.md` and `DECISIONS.md`). That is the
real argument for paying here, rather than convenience.

Steps, if you choose this route:

1. Create an account at https://huggingface.co/join and subscribe to PRO.
2. Create a Space: https://huggingface.co/new-space. Name it `otherwise`,
   SDK = **Docker**, hardware = **CPU basic**, visibility = public.
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

## Route B (free, and what is deployed today): Render

Why: simplest "connect GitHub, click deploy", and the only genuinely free route
of the two. The free plan has 512 MB RAM and 0.1 CPU, and spins down after 15
idle minutes.

**What that means for live runs, measured rather than guessed.** A cold live run
on a 27 ha area took **25 minutes** on a machine with about two usable cores; a
wide-control run took **2.8 hours**. Render's free tier has 0.1 CPU, so expect
substantially longer, and the instance sleeps after 15 idle minutes. Memory now
fits (peak about 340 MB resident, 471 MB counted by the container limit), but
CPU does not really. `docs/LIVE_RUNS_DESIGN.md` works through the options; the
short version is that the showcase and permalinks are what the free tier is good
at, and live runs on demand are the part that wants either a paid instance or a
different home.

The rest of the Render setup (first visit afterwards takes ~1 minute).

1. Create a free account at https://render.com (sign in with GitHub).
2. New → **Blueprint**, pick this repo. Render reads `render.yaml`.
3. Click Apply. The service builds from the Dockerfile and gets a URL. Render
   adds a random suffix when the plain name is taken; this project's live
   service is **https://otherwise-r1vd.onrender.com**. Every push to `main`
   redeploys it automatically.
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

## Air / ULEZ runtime notes

Air is **off** unless the environment variable `APP_AIR_ENABLED=1` is set;
`render.yaml` pins it to `0` for the public site. While off, the Land/Air tab is
hidden and `/api/air/*` returns 404. Keep it off until air has its own
known-answer set and false-alarm test (see `DECISIONS.md`).

The ground-NO₂ path makes outbound HTTPS requests to the public LAQN/Imperial ERG, DEFRA UK-AIR AURN, Open-Meteo ERA5 archive and GLA/TfL ArcGIS services. No API secret is required for the registered ULEZ cases.

Set `APP_AIR_CACHE_DIR` to a writable location. The Docker/Render configuration uses `/data/air_cache`; `data/air_cache/` is ignored locally. The cache is an optimisation/provenance copy, not part of the estimator state.

Run IDs include the air protocol version, so upgrading the method does not reuse an older permalink. A host without persistent storage may lose locally generated run JSON after restart; attach persistent storage if durable production permalinks are required beyond the committed showcase artefacts.
