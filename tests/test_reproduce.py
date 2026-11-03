"""lotg_support.reproduce: inputs manifest, manifest diff, export-commit lookup."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import reproduce as R  # noqa: E402


def _tree(root: Path):
    for rel, body in {
        ".cache/nflverse_stats_player_week_2025.csv": "a,b\n1,2\n",
        ".cache/sleeper/abc.json": "{}",
        ".cache/sleeper/def.json": "[]",
        ".cache/faab/big.parquet": "not a build input",
        ".cache/lotg.duckdb": "binary",
        ".cache/_fetch_log.json": json.dumps({"nflverse_stats_player_week_2025.csv": "2026-11-03T00:00:00+00:00"}),
        "exports/snapshot/league_chain.json": "[]",
        "data/ktc_cache/players/x.json": "{}",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


def test_manifest_hashes_build_inputs_and_rolls_up_big_trees():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _tree(root)
        m = R.inputs_manifest(root, packages={"pandas": "3.0.6"})
        f = m["files"]
        assert ".cache/nflverse_stats_player_week_2025.csv" in f
        assert f[".cache/sleeper/"]["files"] == 2 and ".cache/sleeper/abc.json" not in f
        assert f["data/ktc_cache/players/"]["files"] == 1
        assert not any(k.startswith((".cache/faab", ".cache/lotg.duckdb")) for k in f)
        assert m["packages"] == {"pandas": "3.0.6"}
        assert m["fetched_at"]["nflverse_stats_player_week_2025.csv"].startswith("2026-11-03")
        # Deterministic apart from the clock: the same tree hashes the same.
        m2 = R.inputs_manifest(root, packages={"pandas": "3.0.6"})
        assert m2["files"] == f


def test_diff_names_what_moved():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _tree(root)
        a = R.inputs_manifest(root, packages={"pandas": "3.0.6"})
        (root / ".cache/sleeper/abc.json").write_text('{"x": 1}')
        (root / "exports/snapshot/new.json").write_text("{}")
        (root / "exports/snapshot/league_chain.json").unlink()
        b = R.inputs_manifest(root, packages={"pandas": "3.0.7"})
        dd = R.diff_manifests(a, b)
        assert dd["changed"] == [".cache/sleeper/"]
        assert dd["added"] == ["exports/snapshot/new.json"]
        assert dd["removed"] == ["exports/snapshot/league_chain.json"]
        assert dd["packages"] == ["pandas 3.0.6 -> 3.0.7"]


def _git_ok() -> bool:
    try:
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=_ROOT, check=True, capture_output=True)
        return (_ROOT / "exports" / "snapshot" / "_snapshot_meta.json").exists()
    except Exception:
        return False


def test_export_commit_holds_a_snapshot_stamp():
    if not _git_ok():
        return
    try:
        sha = R.export_commit("HEAD")
    except SystemExit:
        return      # a shallow CI clone may not reach an export commit
    blob = subprocess.run(["git", "show", f"{sha}:exports/snapshot/_snapshot_meta.json"], cwd=_ROOT,
                          capture_output=True, text=True, check=True).stdout
    assert json.loads(blob).get("captured_at")


def test_extract_commit_writes_that_commits_files():
    if not _git_ok():
        return
    with tempfile.TemporaryDirectory() as d:
        have = R.extract_commit("HEAD", Path(d), paths=("config", "no_such_dir"))
        assert have == ["config"]
        assert (Path(d) / "config" / "league.yaml").read_bytes() == (_ROOT / "config" / "league.yaml").read_bytes()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
