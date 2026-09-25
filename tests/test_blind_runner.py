"""The blind-validation scheduler times each item from when it starts, not from
when it was queued, and terminates only items that genuinely overrun."""
import time

from scripts.blind_validation import run_bounded


def quick(args, q):
    time.sleep(0.6)
    q.put({"id": args["item"]["id"], "run_id": None, "seconds": 0.6, "error": None})


def stuck(args, q):
    time.sleep(0.6 if args["item"]["id"] != "slow" else 60)
    q.put({"id": args["item"]["id"], "run_id": None, "seconds": 0.6, "error": None})


def test_queued_items_are_not_timed_out_before_they_start(tmp_path):
    # 4 items, one at a time, 0.6 s each = 2.4 s in total; a 1.5 s timeout measured
    # from submission (the old bug) would have recorded the last items as timeouts.
    items = [{"id": f"i{k}"} for k in range(4)]
    out = list(run_bounded(items, str(tmp_path), parallel=1, timeout=1.5, worker=quick))
    assert [it["id"] for it, _ in out] == ["i0", "i1", "i2", "i3"]
    assert all(res["error"] is None for _, res in out)


def test_an_item_that_overruns_is_terminated_and_recorded(tmp_path):
    items = [{"id": "slow"}, {"id": "ok"}]
    t0 = time.time()
    out = dict((it["id"], res) for it, res in run_bounded(items, str(tmp_path), parallel=2, timeout=2.0, worker=stuck))
    assert out["ok"]["error"] is None
    assert out["slow"]["error"].startswith("timeout after 2 s (terminated)")
    assert time.time() - t0 < 20          # the stuck process did not run its full 60 s
