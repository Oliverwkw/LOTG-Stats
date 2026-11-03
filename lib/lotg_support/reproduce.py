"""Get back the exports of any past build, and say what that build read.

A build is not a pure function of its commit: it fetches live Sleeper, nflverse
and KTC data, so re-running old code today gives today's data (memory
cache-non-hermetic-historical). What CAN be reproduced exactly is what a build
shipped, from one of two places:

  * a CI run's `LOTG_outputs` artifact (`--run ID`): every CSV, the workbook, the
    zip and raw/, byte for byte. main runs keep it 90 days, branch runs 14.
  * git (`--commit REF` / `--date YYYY-MM-DD`): each export commit holds the CSVs,
    raw/, the Sleeper snapshot and (on the Tuesday runs) `.cache`, i.e. the exports
    AND the inputs they came from. Kept forever.

`raw/inputs_manifest.json` (written by every build since this module landed)
records a sha256 for every input file the build had on disk when it finished:
`.cache`, the snapshot, the KTC histories, the installed packages. Two builds
with equal manifests read the same bytes; `diff_manifests` names the inputs that
moved, which separates "upstream revised a file" from "the code changed".

`rebuild` re-runs a commit's own code against that commit's committed snapshot
and `.cache` with the network off (scripts/offline_build.py). It is a smoke test
with the harness's scope: seasons 2020-2025, no KTC (N/A) and no live 2026 league;
see that script's docstring. It never reproduces a CI build's numbers exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "inputs_manifest.json"
MANIFEST_VERSION = 1

# What a build reads from disk. `.cache` subtrees the build never opens (inquiry
# downloads, the FAAB pipeline, the DuckDB copy) are left out so the manifest
# answers "what did the BUILD read".
_INPUT_TREES = (".cache", "exports/snapshot", "data/ktc_cache")
_NOT_BUILD_INPUTS = (
    ".cache/seasons/", ".cache/faab/", ".cache/ktc_proxy/", ".cache/grade/",
    ".cache/lotg.duckdb", ".cache/trade_calibration_", ".cache/nflverse_historical_contracts",
)
# Hashed as one digest per directory (thousands of small files): a change shows
# as "this tree changed", with its file count.
_ROLLUP_DIRS = (".cache/sleeper", "data/ktc_cache/players", "data/ktc_cache/backfill")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rollup_of(rel: str) -> Optional[str]:
    return next((d for d in _ROLLUP_DIRS if rel == d or rel.startswith(d + "/")), None)


def inputs_manifest(root: Path = ROOT, packages: Optional[Dict[str, str]] = None) -> dict:
    """sha256 + size of every build input under `root`, rolled up per big directory."""
    files: Dict[str, dict] = {}
    rollups: Dict[str, hashlib._Hash] = {}
    counts: Dict[str, int] = {}
    for tree in _INPUT_TREES:
        base = root / tree
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if any(rel.startswith(x) for x in _NOT_BUILD_INPUTS):
                continue
            digest = _sha256(p)
            group = _rollup_of(rel)
            if group:
                rollups.setdefault(group, hashlib.sha256()).update(f"{rel}\0{digest}\n".encode())
                counts[group] = counts.get(group, 0) + 1
            else:
                files[rel] = {"sha256": digest, "bytes": p.stat().st_size}
    for group, h in rollups.items():
        files[group + "/"] = {"sha256": h.hexdigest(), "files": counts[group]}
    if packages is None:
        try:
            from importlib import metadata
            packages = {d.metadata["Name"].lower(): d.version for d in metadata.distributions()}
        except Exception:
            packages = {}
    fetch_log = {}
    try:
        fetch_log = json.loads((root / ".cache" / "_fetch_log.json").read_text())
    except Exception:
        pass
    return {
        "version": MANIFEST_VERSION,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA") or _git(["rev-parse", "HEAD"], root) or None,
        "python": sys.version.split()[0],
        "packages": dict(sorted(packages.items())),
        "fetched_at": fetch_log,
        "files": dict(sorted(files.items())),
    }


def diff_manifests(old: dict, new: dict) -> Dict[str, List[str]]:
    """Inputs added / removed / changed between two manifests, and package moves."""
    a, b = old.get("files", {}), new.get("files", {})
    pa, pb = old.get("packages", {}), new.get("packages", {})
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(k for k in set(a) & set(b) if a[k].get("sha256") != b[k].get("sha256")),
        "packages": sorted(f"{k} {pa.get(k)} -> {pb.get(k)}" for k in set(pa) | set(pb) if pa.get(k) != pb.get(k)),
    }


def _git(args: List[str], root: Path = ROOT) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return ""


def export_commit(ref: str = "HEAD", date: Optional[str] = None, root: Path = ROOT) -> str:
    """The newest commit at or before `ref` (or before the end of `date`) that wrote exports.

    Export commits are the ones that touched `exports/snapshot/_snapshot_meta.json`
    (every build stamps it, so a commit that shipped exports changed it)."""
    args = ["log", "-1", "--format=%H"]
    if date:
        args.append(f"--before={date} 23:59:59")
    args += [ref, "--", "exports/snapshot/_snapshot_meta.json"]
    sha = _git(args, root)
    if not sha:
        raise SystemExit(f"no export commit at or before {ref}{' on ' + date if date else ''}")
    return sha


def extract_commit(sha: str, out: Path, paths: Iterable[str] = ("exports", ".cache"),
                   root: Path = ROOT) -> List[str]:
    """Write `paths` as they were at `sha` into `out`; returns the paths that existed."""
    out.mkdir(parents=True, exist_ok=True)
    have = [p for p in paths if _git(["cat-file", "-t", f"{sha}:{p}"], root) == "tree"]
    if not have:
        raise SystemExit(f"{sha[:10]} has none of {list(paths)}")
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "x.tar"
        subprocess.run(["git", "archive", "--format=tar", "-o", str(tar), sha, *have], cwd=root, check=True)
        with tarfile.open(tar) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(out, filter="data")
            else:
                t.extractall(out)
    return have


def download_run(run_id: str, out: Path, artifact: str = "LOTG_outputs") -> Path:
    """A CI run's artifact, exactly as uploaded (needs `gh`, signed in)."""
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "run", "download", str(run_id), "-n", artifact, "-D", str(out)], check=True)
    return out


def rebuild(sha: str, out: Path, root: Path = ROOT) -> Path:
    """Run `sha`'s own offline harness against its committed inputs, in a temp worktree.

    Scope is scripts/offline_build.py's (2020-2025, no KTC, no live league): a smoke
    test of old code, not a copy of what CI shipped. Needs the build's packages
    (`pip install -r requirements.txt -c requirements.lock`, python 3.11)."""
    wt = Path(tempfile.mkdtemp(prefix="lotg_rebuild_"))
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), sha], cwd=root, check=True)
    try:
        if not (wt / "scripts" / "offline_build.py").exists():
            raise SystemExit(f"{sha[:10]} predates scripts/offline_build.py; use --commit or --run")
        env = dict(os.environ, PYTHONPATH=f"{wt / 'src'}{os.pathsep}{wt / 'lib'}")
        subprocess.run([sys.executable, "scripts/offline_build.py"], cwd=wt, env=env, check=True)
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-R", str(wt / "exports") + "/.", str(out)], check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=root, check=False)
    return out
