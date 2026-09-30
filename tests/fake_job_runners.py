"""Fake live-run functions for the job-process tests.

They run inside the spawned child, so they cannot touch the test's objects;
they report back through the return value, files, or how the process ends.
Signature matches jobrunner.run_live_job: fn(req, progress, *, runs_dir, profile).
"""
import os
import signal
import time


def succeed(req, progress, *, runs_dir, profile):
    progress("sentinel-2", 1, 2)
    with open(os.path.join(runs_dir, "fake-ok.json"), "w") as f:
        f.write("{}")
    return f"fake-ok-{os.getpid()}"


def echo_request(req, progress, *, runs_dir, profile):
    """Return what reached the child, so the parent can check the request path."""
    return f"{req.get('domain')}|{req.get('case_id')}|{req.get('post_months')}|{profile}"


def raise_error(req, progress, *, runs_dir, profile):
    raise ValueError("fake pipeline failure")


def hang(req, progress, *, runs_dir, profile):
    """Wedged without reaching another checkpoint: only a hard kill stops it."""
    progress("sentinel-2", 0, 1)
    time.sleep(120)
    return "should-not-finish"


def sigkill_self(req, progress, *, runs_dir, profile):
    """What the kernel OOM killer does to a process."""
    progress("sentinel-2", 0, 1)
    os.kill(os.getpid(), getattr(signal, "SIGKILL", 9))
    time.sleep(30)


def exit_3(req, progress, *, runs_dir, profile):
    os._exit(3)


def checkpoint_forever(req, progress, *, runs_dir, profile):
    """Keeps reporting progress; counts checkpoints reached in a file."""
    counter = os.environ["FAKE_JOB_COUNTER"]
    for i in range(100):
        with open(counter, "a") as f:
            f.write("x")
        progress("sentinel-2", i, 100)
    raise AssertionError("should have been cancelled")
