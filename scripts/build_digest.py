"""Phase 14 CLI — build the weekly digest from the latest build.

Reads the built `exports/` CSVs and the prior ranks snapshot, computes this
week's rankings, diffs them for all-time leaderboard crossings, projects the
in-progress season's on-pace ranks (from week 3), and writes:

  * `data/digest/ranks_snapshot.json`  — this week's rankings (committed so next
    week diffs against it).
  * `exports/raw/weekly_digest.html`   — the rendered digest body.

Runs YEAR-ROUND: the identical diff pipeline in-season and off. Offseason weeks
still move the all-time leaderboards (KTC / age drift) and add picks / trades /
transactions, so the snapshot rotates and diffs every week; the in-season-only
pieces (on-pace, records, single-week highlights) self-gate to empty when there
is no in-progress week. A digest with no movement is suppressed at SEND time
(`send_digest.py --skip-empty`), so a quiet week sends no email — the same rule
in-season and off. `--phrasing-csv PATH` writes the "how every stat is phrased"
catalog and exits.

The email opens with a short lede — up to five sentences, fewer on a quiet week —
saying what actually happened, because the list under it runs to dozens of
one-line facts. It is computed, not written: every move is scored on place,
prominence and surprise, and the winner leads. See `lotg_support/email_summary`
(and `plan/notes/ai-email-lede.md` for the shelved model-written version).

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
from lotg_support import email_summary as DS

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
                    help="(retained for compatibility; the digest now builds "
                         "year-round, so this is a no-op)")
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
        "picks", "trades", "add_drops", "player_additions",
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
            frames["picks"], frames["trades"], frames["add_drops"],
            frames["player_additions"],
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

    # The digest runs YEAR-ROUND — the exact same diff pipeline in-season and off.
    # Offseason weeks legitimately still move the all-time leaderboards (KTC / age
    # drift) and add picks / trades / transactions, so the snapshot rotates and
    # diffs every week regardless of season. The in-season-only pieces (on-pace,
    # single-season records, single-week highlights) self-gate to empty when there
    # is no in-progress week, so the offseason digest is just the subset that has
    # movement. An empty digest (no movement) is suppressed at send time
    # (`send_digest.py --skip-empty`), so a quiet week sends no email.

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
    # The boards cover EVERY numeric column of EVERY row-level sheet, over every
    # row ever — a season, a week, a pick, a trade, a transaction. A recompute
    # that re-values history reshuffles an all-time top/bottom 5, and that
    # reshuffle is the thing to report, whichever sheet it lands on.
    events = D.all_board_highlights(frames)
    current["event_board"] = D.event_board(events)

    prior = D.load_snapshot(snap_path)
    if prior is None:
        print("[digest] no prior snapshot — baselining this week (no diff yet).")
        crossings, proj_changes, milestones, record_changes, event_changes = [], [], [], [], []
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
        # A snapshot from before the all-seasons board (it carried `event_keys`,
        # current-season only) has no `event_board`, so the first run after the
        # change re-baselines silently rather than emailing the whole board.
        prior_events = prior.get("event_board")
        if prior_events is None:
            print("[digest] baselining event boards this week (no diff yet).")
            event_changes = []
        else:
            event_changes = D.diff_events(prior_events, events)

    # The lede: up to five sentences above the list saying what actually
    # happened, because 65 one-line facts is a wall nobody reads. Computed, not
    # written — every move is scored on place, prominence and surprise, and the
    # winner leads. Cannot fail the build; build_intro never raises. See
    # lotg_support/email_summary.
    sections = D.digest_sections(crossings, proj_changes, milestones,
                                 record_changes, highlights, event_changes)
    intro = DS.build_intro(sections, D.digest_title(meta))
    if intro:
        print(f"[digest] lede: {intro}")

    html = D.render_digest_html(crossings, proj_changes, meta, milestones,
                                record_changes, highlights, intro=intro,
                                events=event_changes)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"[digest] {len(highlights)} single-week highlight(s), {len(crossings)} crossing(s), "
          f"{len(record_changes)} record(s), {len(event_changes)} board move(s), "
          f"{len(milestones)} milestone(s), {len(proj_changes)} on-pace change(s) -> {out_path}")

    D.save_snapshot(snap_path, current)
    print(f"[digest] snapshot saved -> {snap_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
