"""Child-process side of a live run.

The web process used to execute each live run as a thread inside itself, so a
run that exhausted memory got the whole server OOM-killed (showcase and every
permalink with it), and a wedged run could only be stopped cooperatively.
Now `server._worker` spawns one child process per job and runs `child_main`
in it. The child reports progress and a single terminal message over a
multiprocessing queue; the parent enforces the hard time limit by killing the
child, and reads a SIGKILL exit (the kernel OOM killer's signal) as "ran out of
memory". Only the job dies; the web process keeps serving.

This module is imported fresh in every spawned child, so it keeps its own
top-level imports light: the pipeline is imported inside the default runner.

Message protocol (child -> parent), plain tuples so nothing unpicklable crosses:
    ("progress", stage, done, total)
    ("done", run_id)
    ("error", message)
"""
from __future__ import annotations

import importlib
import os
import time
import traceback

DEFAULT_RUNNER = "src.app.jobrunner:run_live_job"

OOM_MESSAGE = ("This run ran out of memory on the server and was stopped. Try a smaller "
               "area or a shorter window; the showcase examples still work.")


class JobTimeout(RuntimeError):
    """A live run exceeded APP_JOB_TIMEOUT_S (checkpoint or hard kill)."""


def timeout_message(timeout_s: float) -> str:
    limit = (f"{timeout_s / 60:.0f}-minute" if timeout_s >= 60 else f"{timeout_s:g}-second")
    return (f"This run passed the {limit} limit and was stopped so other runs can start. "
            f"Try a smaller area or a shorter window.")


def resolve_runner(spec: str):
    """'package.module:function' -> the function."""
    mod, _, name = spec.partition(":")
    return getattr(importlib.import_module(mod), name)


def run_live_job(req: dict, progress, *, runs_dir: str, profile: str) -> str:
    """The real live run (land or air). Returns the saved run's id.

    Writes the same outputs the in-process worker used to: the run JSON (via
    run_verdict / run_air_verdict with save=True) and, for land runs, the
    before/after thumbnails plus their metadata JSON, all under `runs_dir`.
    """
    label = (req.get("label") or "")[:120]
    if req.get("domain") == "air":
        from .air import run_air_verdict
        out = run_air_verdict(req.get("case_id") or "", req.get("post_months"), label=label,
                              progress=progress, runs_dir=runs_dir)
        return out["id"]
    from .run import run_verdict
    out = run_verdict(req["geojson"], req["event_date"], req.get("change_type") or "other",
                      int(req.get("post_months") or 12), label=label, progress=progress,
                      profile=profile, runs_dir=runs_dir)
    try:
        import json
        from .imagery import make_thumbnails
        progress("imagery", 0, 1)
        info = make_thumbnails(req["geojson"], req["event_date"], runs_dir, out["id"])
        for tag, meta in info.items():
            with open(os.path.join(runs_dir, f"{out['id']}_{tag}.json"), "w") as f:
                json.dump(meta, f)
    except JobTimeout:
        raise
    except Exception:
        traceback.print_exc()          # thumbnails are optional; the verdict stands
    return out["id"]


def _volunteer_for_oom_killer():
    """Make the kernel pick this child, not the web process, when memory runs out.

    Raising one's own oom_score_adj needs no privilege. Linux only; elsewhere a no-op.
    """
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass


def execute(req: dict, emit, *, runner: str, runs_dir: str, profile: str, timeout_s: float) -> None:
    """Run one job and emit exactly one terminal message. Usable in-process for tests."""
    deadline = time.monotonic() + timeout_s

    def progress(stage, done, total):
        # Cooperative checkpoint: a run that keeps reporting progress stops cleanly
        # here; the parent's hard kill is the backstop for one that does not.
        if time.monotonic() >= deadline:
            raise JobTimeout(timeout_message(timeout_s))
        emit(("progress", stage, done, total))

    try:
        fn = resolve_runner(runner)
        rid = fn(req, progress, runs_dir=runs_dir, profile=profile)
        emit(("done", rid))
    except JobTimeout as e:
        emit(("error", str(e)[:300]))
    except MemoryError:
        emit(("error", OOM_MESSAGE))
    except Exception as e:
        # MemoryBudgetError (a deliberate, explained refusal) lands here too; its
        # message is written for the user.
        traceback.print_exc()
        emit(("error", (str(e) or type(e).__name__)[:300]))


def child_main(payload: dict, queue) -> None:
    """Entry point of the spawned child process."""
    _volunteer_for_oom_killer()
    execute(payload["req"], queue.put, runner=payload["runner"], runs_dir=payload["runs_dir"],
            profile=payload["profile"], timeout_s=payload["timeout_s"])
