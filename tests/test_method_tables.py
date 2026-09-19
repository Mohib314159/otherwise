"""docs/METHOD.md must agree with the runs committed in showcase/.

CRITIQUE.md issue 10: METHOD.md section 10, showcase/track_record.json and
showcase/validation.md disagreed on Rhodes' verdict and on Grunheide's interval,
because the doc was hand-written and the runs moved underneath it. These tests
make that drift a test failure rather than something a reviewer finds.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_known_answer_table_in_method_md_is_up_to_date():
    r = subprocess.run([sys.executable, "-m", "scripts.method_tables", "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, (
        "docs/METHOD.md no longer matches showcase/*.json.\n"
        "Run `python -m scripts.method_tables` and commit the result.\n" + r.stderr)


def test_track_record_summary_agrees_with_the_committed_runs():
    """The same arithmetic, computed two ways, must land in the same place."""
    with open(os.path.join(ROOT, "showcase", "index.json")) as f:
        index = json.load(f)
    n = hits = cant = misses = false_alarms = 0
    for e in index:
        p = os.path.join(ROOT, "showcase", f"{e['id']}.json")
        if not os.path.exists(p) or not e.get("expected"):
            continue
        with open(p) as f:
            got = json.load(f)["verdict"]["status"]
        n += 1
        if got == "CANT_TELL":
            cant += 1
        elif got == e["expected"]:
            hits += 1
        elif e["expected"] == "NOT_REAL":
            false_alarms += 1
        else:
            misses += 1

    tp = os.path.join(ROOT, "showcase", "track_record.json")
    if not os.path.exists(tp):
        pytest.skip("no track_record.json committed")
    with open(tp) as f:
        summary = json.load(f).get("summary") or {}
    assert summary.get("n") == n
    assert summary.get("hits") == hits
    assert summary.get("misses") == misses
    assert summary.get("false_alarms") == false_alarms
    assert summary.get("cant_tell") == cant


def test_method_md_does_not_contradict_the_committed_rhodes_verdict():
    """Rhodes was re-run in wide mode and is REAL; the doc used to say CAN'T TELL."""
    with open(os.path.join(ROOT, "showcase", "index.json")) as f:
        index = json.load(f)
    entry = next((e for e in index if e["key"] == "rhodes"), None)
    if entry is None:
        pytest.skip("rhodes not in the showcase")
    with open(os.path.join(ROOT, "showcase", f"{entry['id']}.json")) as f:
        run = json.load(f)
    with open(os.path.join(ROOT, "docs", "METHOD.md")) as f:
        doc = f.read()
    if run["verdict"]["status"] == "REAL":
        # the old wording claimed the opposite, with "controls burnt too" as the reason
        assert "| Rhodes 2023 | burn | REAL | CAN'T TELL |" not in doc
