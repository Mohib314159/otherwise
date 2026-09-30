"""The web process must stay import-light.

On the 512 MB host the web parent and a live-run child share the memory budget,
so `import src.app.server` must not drag in the analysis stack; that is loaded
only inside the spawned job child (src/app/jobrunner.py). Checked in a fresh
interpreter, since this test process has long since imported everything.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEAVY = ("rasterio", "scipy", "pandas", "pystac", "pystac_client", "odc", "xarray",
         "planetary_computer", "src.app.run", "src.app.fetch", "src.app.estimator",
         "src.app.air.run", "src.app.air.analysis", "src.app.air.providers")


def _loaded_after(code: str) -> list[str]:
    probe = code + f"\nimport json, sys\nprint(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))\n"
    env = {**os.environ, "PYTHONPATH": ROOT, "OPENBLAS_NUM_THREADS": "1"}
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_importing_the_server_does_not_load_the_pipeline():
    assert _loaded_after("import src.app.server") == []


def test_serving_pages_and_saved_runs_does_not_load_the_pipeline():
    code = """
import json, os
from fastapi.testclient import TestClient
import src.app.server as server
c = TestClient(server.app)
ids = [e["id"] for e in json.load(open(os.path.join(server.SHOWCASE_DIR, "index.json")))]
for url in ("/", "/track-record", "/api/track-record", "/api/showcase", "/api/health",
            f"/v/{ids[0]}", f"/api/runs/{ids[0]}", f"/api/runs/{ids[0]}/report.md"):
    assert c.get(url).status_code == 200, url
"""
    assert _loaded_after(code) == []
