"""Phase 14 CLI — build the in-season weekly digest from the latest build.

Reads the built `exports/` CSVs and the prior ranks snapshot, computes this
week's rankings, diffs them for all-time leaderboard crossings, projects the
in-progress season's on-pace ranks (from week 3), and writes:

  * `data/digest/ranks_snapshot.json`  — this week's all-time rankings (committed
    so next week diffs against it).
  * `exports/raw/weekly_digest.html`   — the rendered digest body.

In-season gate: with no completed weeks (offseason) the digest is skipped and
the snapshot is NOT rotated, so the first in-season run keeps a real baseline.
`--force` builds regardless. `--phrasing-csv PATH` writes the "how every stat is
phrased" catalog and exits.

Delivery is separate — see `scripts/send_digest.py`. This CLI only renders.

Usage:
  PYTHONPATH=src:lib python scripts/build_digest.py [--exports DIR]
       [--snapshot PATH] [--out PATH] [--force] [--phrasing-csv PATH]
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
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the LOTG weekly digest.")
    ap.add_argument("--exports", default=str(_ROOT / "exports"))
    ap.add_argument("--snapshot", default=str(_ROOT / "data" / "digest" / "ranks_snapshot.json"))
    ap.add_argument("--out", default=None,
                    help="digest HTML (default: <exports>/raw/weekly_digest.html)")
    ap.add_argument("--force", action="store_true",
                    help="build even in the offseason (no completed weeks)")
    ap.add_argument("--phrasing-csv", default=None,
                    help="write the stat-phrasing catalog CSV and exit")
    ap.add_argument("--replica", default=None,
                    help="write the 'most recent digest' replica (latest completed "
                         "season's post-championship wrap) to this path and exit")
    args = ap.parse_args(argv)

    exports = Path(args.exports)
    frames = {n: _read(exports, n) for n in (
        "player_all_time", "team_all_time", "player_year", "team_year",
        "league_year", "league_all_time", "team_week", "player_week", "league_week",
        "picks", "trades", "transactions",
    )}
    required = ("player_all_time", "team_all_time", "team_year")
    if any(frames[n].empty for n in required):
        print(f"[digest] no build found under {exports} — nothing to do.")
        return 0

    # Phrasing catalog: standalone, no snapshot / gate needed.
    if args.phrasing_csv:
        rows = D.phrasing_catalog(
            frames["player_all_time"], frames["team_all_time"],
            frames["player_year"], frames["team_year"], frames["league_year"],
            frames["league_all_time"],
            frames["player_week"], frames["team_week"], frames["league_week"],
            frames["picks"], frames["trades"], frames["transactions"],
        )
        D.write_phrasing_csv(Path(args.phrasing_csv), rows)
        print(f"[digest] phrasing catalog ({len(rows)} stats) -> {args.phrasing_csv}")
        return 0

    # Replica: the most-recent-digest stand-in (offseason = post-championship).
    if args.replica:
        html = D.build_replica_html(frames)
        if not html:
            print("[digest] no completed week on record — no replica written.")
            return 0
        Path(args.replica).parent.mkdir(parents=True, exist_ok=True)
        Path(args.replica).write_text(html)
        print(f"[digest] replica digest -> {args.replica}")
        return 0

    snap_path = Path(args.snapshot)
    out_path = Path(args.out) if args.out else exports / "raw" / "weekly_digest.html"

    current = D.build_snapshot(
        frames["player_all_time"], frames["team_all_time"],
        frames["team_year"], frames["team_week"],
        league_all_time=frames["league_all_time"],
        captured_at=datetime.now(timezone.utc),
    )
    meta = current["meta"]
    print(f"[digest] season={meta['season']} weeks_completed={meta['weeks_completed']}")

    if not D.is_in_season(current) and not args.force:
        print("[digest] offseason — skipping digest, snapshot left unrotated.")
        return 0

    projections = D.project_on_pace(
        frames["player_year"], frames["team_year"],
        frames["league_year"], frames["team_week"],
    )
    current["pace"] = D.pace_rank_map(projections)
    records = D.yearly_records(
        frames["player_year"], frames["team_year"],
        frames["league_year"], frames["team_week"],
    )
    current["yearly_records"] = D.record_value_map(records)
    highlights = D.weekly_highlights(
        frames["player_week"], frames["team_week"],
        frames["league_week"], frames["team_year"],
    )
    events = D.season_event_highlights(frames, meta["season"]) if meta["season"] else []
    current["event_keys"] = D.event_key_map(events)
    # Two-sided (zero-centered) extremes: matchup margins this week + trade
    # differentials this season, ranked by |value| with both sides named.
    week_no = D.latest_completed_week(frames["team_week"], meta["season"]) if meta["season"] else None
    paired = []
    if meta["season"] and week_no:
        paired += D.matchup_highlights(frames["team_week"], meta["season"], week_no)
        paired += D.season_paired_highlights(frames, meta["season"])
    current["paired_keys"] = D.paired_key_map(paired)

    prior = D.load_snapshot(snap_path)
    if prior is None:
        print("[digest] no prior snapshot — baselining this week (no diff yet).")
        crossings, proj_changes, milestones, record_changes, event_changes = [], [], [], [], []
        paired_changes = []
    else:
        crossings = D.diff_snapshots(prior, current)
        milestones = D.milestone_crossings(
            prior.get("league_milestones", {}), current["league_milestones"])
        prior_pace = prior.get("pace")
        if prior_pace is None:
            # First week the season carries on-pace data — baseline it silently
            # so we don't dump every standing; report only changes from here on.
            print("[digest] baselining on-pace standings this week (no diff yet).")
            proj_changes = []
        else:
            proj_changes = D.diff_pace(prior_pace, projections)
        prior_records = prior.get("yearly_records")
        if prior_records is None:
            print("[digest] baselining yearly records this week (no diff yet).")
            record_changes = []
        else:
            record_changes = D.diff_records(prior_records, records)
        prior_events = prior.get("event_keys")
        if prior_events is None:
            print("[digest] baselining event highlights this week (no diff yet).")
            event_changes = []
        else:
            event_changes = D.diff_events(prior_events, events)
        prior_paired = prior.get("paired_keys")
        if prior_paired is None:
            print("[digest] baselining two-sided extremes this week (no diff yet).")
            paired_changes = []
        else:
            paired_changes = D.diff_paired(prior_paired, paired)

    html = D.render_digest_html(crossings, proj_changes, meta, milestones,
                                record_changes, highlights, events=event_changes,
                                paired=paired_changes)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"[digest] {len(highlights)} single-week highlight(s), {len(crossings)} crossing(s), "
          f"{len(record_changes)} record(s), {len(event_changes)} event(s), "
          f"{len(paired_changes)} two-sided extreme(s), "
          f"{len(milestones)} milestone(s), {len(proj_changes)} on-pace change(s) -> {out_path}")

    D.save_snapshot(snap_path, current)
    print(f"[digest] snapshot saved -> {snap_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
