"""Get back the exports of any past build — one command (lotg_support.reproduce).

  python scripts/reproduce_exports.py --run 41658606539 -o /tmp/r   # a CI run's artifact, byte for byte
  python scripts/reproduce_exports.py --commit 5528392 -o /tmp/r    # exports + inputs committed at/before it
  python scripts/reproduce_exports.py --date 2026-10-06 -o /tmp/r   # the last export commit on main that day
  python scripts/reproduce_exports.py --commit 5528392 --rebuild -o /tmp/r   # re-run that code offline (2020-25 smoke)
  python scripts/reproduce_exports.py --manifest                    # this checkout's inputs manifest (JSON)
  python scripts/reproduce_exports.py --diff A.json B.json          # which inputs two builds read differently

A build fetches live data, so old code re-run today gives today's numbers; what a
build SHIPPED is what comes back exactly (artifact, or the export commit in git).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from lotg_support import reproduce as R  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="CI run id: download its LOTG_outputs artifact")
    g.add_argument("--commit", help="git ref: the newest export commit at or before it")
    g.add_argument("--date", help="YYYY-MM-DD: the newest export commit on origin/main by that day's end")
    g.add_argument("--manifest", action="store_true", help="print this checkout's inputs manifest")
    g.add_argument("--diff", nargs=2, metavar=("OLD", "NEW"), help="compare two inputs_manifest.json files")
    ap.add_argument("--rebuild", action="store_true", help="with --commit/--date: re-run its code offline")
    ap.add_argument("-o", "--out", type=Path, help="output directory")
    a = ap.parse_args(argv)

    if a.manifest:
        print(json.dumps(R.inputs_manifest(), indent=1))
        return 0
    if a.diff:
        d = R.diff_manifests(*(json.loads(Path(p).read_text()) for p in a.diff))
        for k, v in d.items():
            print(f"{k}: {len(v)}")
            for x in v:
                print(f"  {x}")
        return 0
    if not a.out:
        ap.error("-o/--out is required")
    if a.run:
        R.download_run(a.run, a.out)
        print(f"run {a.run}'s LOTG_outputs -> {a.out}")
        return 0
    sha = R.export_commit(a.commit or "origin/main", date=a.date)
    if a.rebuild:
        R.rebuild(sha, a.out)
        print(f"offline rebuild of {sha[:10]} (2020-25 scope) -> {a.out}")
        return 0
    have = R.extract_commit(sha, a.out)
    print(f"export commit {sha[:10]}: {', '.join(have)} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
