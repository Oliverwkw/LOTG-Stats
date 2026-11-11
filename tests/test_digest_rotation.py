"""The Tuesday digest rotation must land on main, or the catch-up re-sends it.

Run 835 (Tue 2026-11-10) mailed the league, then lost its rotation: a FAAB
rebuild pushed to main mid-build, the exports commit's reconcile ran
`git reset --hard origin/main`, which put data/digest/ranks_snapshot.json back
to last week's copy, and the rotation step found nothing to commit. The 17:47
catch-up's guard read the stale stamp, ran, and mailed the same digest again
(run 836).

These tests run the REAL rotation step script from build.yml in a scratch git
repo, under that exact race: the working copy holds the stale snapshot (as the
reset leaves it) and origin/main has moved since the checkout.

Run: python tests/test_digest_rotation.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
BUILD = _ROOT / ".github" / "workflows" / "build.yml"
TEMP_NAME = "rotated_ranks_snapshot.json"


def _steps() -> dict:
    doc = yaml.safe_load(BUILD.read_text())
    return {s.get("name", ""): s for s in doc["jobs"]["build"]["steps"]}


def _step(prefix: str) -> dict:
    hits = [s for n, s in _steps().items() if n.startswith(prefix)]
    assert len(hits) == 1, f"expected one step named {prefix!r}*, found {len(hits)}"
    return hits[0]


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True,
                          capture_output=True)


def _snapshot(stamp: str) -> str:
    return json.dumps({"meta": {"captured_at": stamp}}) + "\n"


def test_digest_step_saves_the_rotated_snapshot_outside_the_checkout():
    run = _step("Build weekly digest")["run"]
    assert f"${{RUNNER_TEMP}}/{TEMP_NAME}" in run, (
        "the digest step must copy the rotated snapshot to $RUNNER_TEMP, where a "
        "reconcile `git reset --hard` in the exports commit cannot reach it")
    assert 'exit "${status}"' in run, (
        "the digest step must still exit with build_digest.py's status")


def test_rotation_reads_the_same_temp_copy():
    run = _step("Rotate digest snapshot")["run"]
    assert f"${{RUNNER_TEMP}}/{TEMP_NAME}" in run


def _run_rotation(work: Path, temp: Path) -> subprocess.CompletedProcess:
    script = _step("Rotate digest snapshot")["run"]
    script = re.sub(r"\$\{\{\s*github\.run_number\s*\}\}", "999", script)
    assert "${{" not in script, "unsubstituted expression left in the rotation script"
    env = dict(os.environ, RUNNER_TEMP=str(temp),
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    return subprocess.run(["bash", "-e", "-c", script], cwd=work, env=env,
                          text=True, capture_output=True)


def _race(with_temp_copy: bool):
    """origin/main moved mid-build and the working copy's snapshot is stale."""
    root = Path(tempfile.mkdtemp())
    remote, work, other, temp = (root / n for n in ("remote.git", "work", "other", "temp"))
    temp.mkdir()
    _git(root, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(root, "clone", "-q", str(remote), str(other))
    for k, v in {"user.name": "t", "user.email": "t@example.com"}.items():
        _git(other, "config", k, v)
    (other / "data" / "digest").mkdir(parents=True)
    (other / "data" / "digest" / "ranks_snapshot.json").write_text(_snapshot("2026-11-03T20:33:25+00:00"))
    (other / "data" / "digest" / "last_digest.html").write_text("<p>last week</p>\n")
    (other / "data" / "faab_value").mkdir(parents=True)
    (other / "data" / "faab_value" / "params.json").write_text("{}\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "base")
    _git(other, "push", "-q", "origin", "main")
    _git(root, "clone", "-q", str(remote), str(work))

    # Something else (the FAAB rebuild) pushes to main after the build checked out.
    (other / "data" / "faab_value" / "params.json").write_text('{"x": 1}\n')
    _git(other, "commit", "-q", "-am", "FAAB values: weekly rebuild [skip ci]")
    _git(other, "push", "-q", "origin", "main")

    fresh = _snapshot("2026-11-10T20:48:20+00:00")
    if with_temp_copy:
        (temp / TEMP_NAME).write_text(fresh)
    # The working copy keeps the stale snapshot, as the reconcile reset leaves it.
    return root, remote, work, temp, fresh


def _remote_snapshot(root: Path, remote: Path) -> str:
    check = root / "check"
    _git(root, "clone", "-q", str(remote), str(check))
    return (check / "data" / "digest" / "ranks_snapshot.json").read_text()


def test_rotation_lands_despite_a_reset_and_a_moved_main():
    if not shutil.which("git"):
        print("SKIP  git not available")
        return
    root, remote, work, temp, fresh = _race(with_temp_copy=True)
    try:
        res = _run_rotation(work, temp)
        assert res.returncode == 0, f"rotation failed:\n{res.stdout}\n{res.stderr}"
        assert _remote_snapshot(root, remote) == fresh, (
            "origin/main does not hold the rotated snapshot; the catch-up cron "
            "would re-send this week's digest")
        check = root / "check"
        log = _git(check, "log", "--format=%s").stdout
        assert "FAAB values: weekly rebuild" in log, "the concurrent push was lost"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_without_the_temp_copy_the_old_behaviour_is_kept():
    """No rotated copy (digest step failed): commit whatever is in the checkout."""
    if not shutil.which("git"):
        print("SKIP  git not available")
        return
    root, remote, work, temp, _fresh = _race(with_temp_copy=False)
    try:
        res = _run_rotation(work, temp)
        assert res.returncode == 0, f"rotation failed:\n{res.stdout}\n{res.stderr}"
        assert "nothing to commit" in res.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [test_digest_step_saves_the_rotated_snapshot_outside_the_checkout,
         test_rotation_reads_the_same_temp_copy,
         test_rotation_lands_despite_a_reset_and_a_moved_main,
         test_without_the_temp_copy_the_old_behaviour_is_kept]

if __name__ == "__main__":
    bad = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            bad += 1
            print(f"FAIL  {t.__name__}: {e}")
    sys.exit(1 if bad else 0)
