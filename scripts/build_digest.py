"""Phase 14 CLI — build the in-season weekly digest from the latest build.

Reads the built `exports/` CSVs and the prior ranks snapshot, computes this
week's rankings, diffs them for leaderboard crossings, projects the in-progress
season's pace, and writes:

  * `data/digest/ranks_snapshot.json`  — this week's rankings (committed so next
    week diffs against it).
  * `exports/raw/weekly_digest.html`   — the rendered digest body.

In-season gate: if the current season has no completed weeks (offseason), the
digest is skipped and the snapshot is NOT rotated, so the first in-season run
still has a meaningful baseline. Pass `--force` to build regardless.

DELIVERY IS INTENTIONALLY NOT WIRED HERE. The Phase 14 plan records
"Delivery / recipients: TBD (user will specify before phase starts)". Once the
recipient list + provider are decided, a thin send step reads
`exports/raw/weekly_digest.html` and mails it — no change to this module.

Usage:
  PYTHONPATH=src:lib python scripts/build_digest.py [--exports exports]
                                                    [--snapshot PATH]
                                                    [--out PATH] [--force]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from lotg_support import digest as D

_ROOT = Path(__file__).resolve().parent.parent


def _read(exports: Path, name: str) -> pd.DataFrame:
    p = exports / f"{name}.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, low_memory=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the LOTG weekly digest.")
    ap.add_argument("--exports", default=str(_ROOT / "exports"),
                    help="directory holding the built CSVs")
    ap.add_argument("--snapshot", default=str(_ROOT / "data" / "digest" / "ranks_snapshot.json"),
                    help="prior/next ranks snapshot JSON")
    ap.add_argument("--out", default=None,
                    help="digest HTML output (default: <exports>/raw/weekly_digest.html)")
    ap.add_argument("--force", action="store_true",
                    help="build even in the offseason (no completed weeks)")
    args = ap.parse_args(argv)

    exports = Path(args.exports)
    snap_path = Path(args.snapshot)
    out_path = Path(args.out) if args.out else exports / "raw" / "weekly_digest.html"

    need = ["player_all_time", "team_all_time", "team_year", "team_week"]
    frames = {n: _read(exports, n) for n in need}
    if any(frames[n].empty for n in ("player_all_time", "team_all_time", "team_year")):
        print(f"[digest] no build found under {exports} — nothing to do.")
        return 0

    current = D.build_snapshot(
        frames["player_all_time"], frames["team_all_time"],
        frames["team_year"], frames["team_week"],
        captured_at=datetime.now(timezone.utc),
    )
    meta = current["meta"]
    print(f"[digest] season={meta['season']} weeks_completed={meta['weeks_completed']}")

    if not D.is_in_season(current) and not args.force:
        print("[digest] offseason (no completed weeks) — skipping digest, "
              "snapshot left unrotated.")
        return 0

    prior = D.load_snapshot(snap_path)
    if prior is None:
        print("[digest] no prior snapshot — baselining this week (no diff yet).")
        crossings = []
    else:
        crossings = D.diff_snapshots(prior, current)

    projections = D.project_end_of_season(frames["team_year"], frames["team_week"])

    html = D.render_digest_html(crossings, projections, meta)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"[digest] {len(crossings)} crossing(s), {len(projections)} projection(s) "
          f"-> {out_path}")

    # Rotate the snapshot forward so next week diffs against this week.
    D.save_snapshot(snap_path, current)
    print(f"[digest] snapshot saved -> {snap_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
