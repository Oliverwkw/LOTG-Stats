#!/usr/bin/env python3
"""Sleeper injury snapshot (PR E fix B) — the gameday sweep and the final capture.

Pulls Sleeper's current injury_status/status for every rostered player in the
league — plus Sleeper's live participation index for the week — into
data/injury_tracker.csv, which the main build reads as its primary
injury/suspension source. Run by two workflows, one per mode below:
sweep_injuries.yml (daily 16:00 UTC) and capture_injuries.yml (Tue 05:00 UTC).

TWO MODES
  --mode final  (default)  the post-week capture, Tuesday 05:00 UTC. It is the
      one that carries participation: Sleeper's weekly stats are complete by
      then, and `played` is what stops a man who was hurt DURING a game from
      being recorded as having missed it.
  --mode sweep             a gameday capture, taken while the designations are
      still the ones the teams played under. Runs daily and exits in seconds
      unless the schedule says there is a game today, so it needs no cron
      edits for the Wednesday opener, the Black Friday game or a rescheduled
      Tuesday one. It files under the week whose games are being played.

Sweeps and the final capture MERGE into one row per player-week (see
injury_tracker.merge_capture): the strongest designation any of them saw, with
participation from the final one. That is the point of sweeping — a designation
the team clears on Monday is still in the sheet, and one added on Monday still
cannot flag a game the player appeared in.

Three things it will REFUSE to do, because each writes a block that is worse
than the gap it fills:
  * capture a season before injury_tracker.TRACKER_FIRST_SEASON — those seasons
    were built by the nflverse/meta process and keep its flags;
  * re-run the FINAL capture on a week that already has one (the cron keeps
    firing every January Tuesday after week 18, and the schedule keeps
    resolving to 18). Gameday sweeps always merge — that is what they are for;
  * write anything at all under --dry-run.
Both re-capture refusals are lifted by --force, which writes TODAY's statuses
over that week's real ones.

Uses an UNCACHED Sleeper client so it always reads live data.

WHICH WEEK A CAPTURE IS FILED UNDER comes from the FIXED NFL SCHEDULE, never
from Sleeper's /state/nfl — the most recently started week for a final capture,
the week whose games are being played today for a sweep. /state/nfl rolls its
`week` on Sleeper's own clock: trusted blindly it would file a capture one week
off if it rolled early, and — because the cron fires on every Tuesday in
September — would file the PRESEASON injury picture as week 1 on the Tuesdays
before kickoff. Sleeper's state is still read, as a cross-check that shouts when
the two disagree by more than the ordinary Tuesday roll-forward. `--week`
overrides both (testing/backfill).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from lotg_support.utils import HttpConfig  # noqa: E402
from lotg_support.sleeper import SleeperClient  # noqa: E402
from lotg_support.injury_tracker import (  # noqa: E402
    TRACKER_FIRST_SEASON, capture_rows, gameday, gameday_week, merge_capture,
    sweep_counts,
    merge_into_csv, missing_weeks, played_index, season_from_date, state_info,
    state_week_drift, weeks_finalized, week_from_schedule,
)


def resolve_week(sc, season: int, args) -> tuple:
    """(week, notes) — the week to file this capture under, or (None, notes)."""
    notes = []
    st = state_info(sc)

    if getattr(args, "mode", "final") == "sweep":
        if args.week is not None:
            notes.append(f"Using --week {args.week} (explicit override).")
            return int(args.week), notes
        wk = gameday_week(season)
        if wk is None:
            notes.append(f"No NFL game on {gameday()} — nothing to sweep.")
            return None, notes
        notes.append(f"Sweeping {season} week {wk}: the schedule has a game today "
                     f"({gameday()}).")
        return int(wk), notes

    sched_week = week_from_schedule(season)
    if st["week"] is not None:
        notes.append(f"Sleeper /state/nfl: season={st['season']} week={st['week']} "
                     f"season_type={st['season_type']}")

    if args.week is not None:
        notes.append(f"Using --week {args.week} (explicit override).")
        return int(args.week), notes

    if sched_week is not None:
        notes.append(f"Schedule says the most recently started week is {sched_week}.")
        # Only a REAL disagreement is escalated to a GitHub annotation (so it
        # lands in the run summary rather than scrolling past in the log). The
        # Tuesday roll-forward is not one — see state_week_drift().
        drift = state_week_drift(st["week"], sched_week)
        if drift == "agree":
            notes.append("Sleeper's state agrees with the schedule.")
        elif drift == "rolled":
            notes.append(
                f"Sleeper's state has already rolled to week {st['week']} "
                f"(the ordinary Tuesday picture); filing under {sched_week}.")
        elif drift == "drift":
            notes.append(
                f"::warning::Sleeper's state week ({st['week']}) is "
                f"{int(st['week']) - int(sched_week):+d} weeks from the schedule "
                f"({sched_week}) — neither agreement nor the usual Tuesday "
                f"roll-forward. Filing under {sched_week}, because the schedule is "
                f"fixed and Sleeper's state rolls on its own clock, but check that "
                f"block.")
        if st["season_type"] not in (None, "regular"):
            notes.append(
                f"::warning::Sleeper says season_type={st['season_type']} while the "
                f"schedule says regular-season week {sched_week} has started. "
                f"Filing under {sched_week}.")
        return int(sched_week), notes

    # No schedule (fetch failed, or the season has not kicked off yet).
    if st["season_type"] == "regular" and st["week"]:
        notes.append("WARNING: schedule unavailable; falling back to Sleeper's "
                     f"state week ({st['week']}). Verify this block's week.")
        return int(st["week"]), notes

    notes.append(f"No regular-season week has started yet (season_type="
                 f"{st['season_type']}). Nothing to capture.")
    return None, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="Replace an existing block for this (season, week). "
                         "Required for an explicit --week that already has one: "
                         "a re-capture writes TODAY's statuses, which for a past "
                         "week is worse than the gap it fills.")
    ap.add_argument("--mode", choices=("final", "sweep"), default="final",
                    help="'final' (default) is the post-week capture that carries "
                         "participation; 'sweep' is a gameday capture of the "
                         "designations the teams played under, and exits cleanly "
                         "on a day with no game.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and summarise, but do not write the CSV.")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "league.yaml").read_text())
    http = HttpConfig(timeout_seconds=30, max_retries=10, backoff_base_seconds=0.7)
    # cache_dir=None -> never cache; the snapshot must be live.
    sc = SleeperClient(str(cfg["league_id"]), http, cache_dir=None)

    season = args.season
    if season is None:
        season = state_info(sc)["season"] or season_from_date()

    week, notes = resolve_week(sc, int(season), args)
    for n in notes:
        print(n)
    if not week or int(week) < 1:
        return 0

    season, week = int(season), int(week)
    if season < TRACKER_FIRST_SEASON:
        print(f"REFUSING: {season} is before the tracker's first season "
              f"({TRACKER_FIRST_SEASON}). Seasons up to {TRACKER_FIRST_SEASON - 1} "
              f"were built by the nflverse/meta process and keep its flags; "
              f"load_status_index() drops rows before {TRACKER_FIRST_SEASON}, so "
              f"capturing one would write a block nothing ever reads.")
        return 1

    final = args.mode == "final"
    if final and week in weeks_finalized(ROOT, season) and not args.force:
        if args.week is not None:
            print(f"REFUSING: {season} week {week} has already been finalized and "
                  f"--week was given explicitly. A re-capture writes TODAY's "
                  f"statuses over that week's real ones. Pass --force if that is "
                  f"genuinely what you want.")
            return 1
        # The routine case, and the reason this is a skip rather than an
        # overwrite: once the regular season is over the schedule keeps
        # resolving to week 18, so every remaining January Tuesday would
        # otherwise re-finalize week 18 with a mid-playoffs snapshot.
        print(f"Nothing to do: {season} week {week} has already been finalized, "
              f"and the schedule has not moved on to a new week. (Pass --force to "
              f"re-capture it with TODAY's statuses.)")
        return 0
    if args.force:
        print(f"Note: --force given — REPLACING the {season} week {week} block, "
              f"discarding whatever earlier captures of it recorded.")

    played = played_index(sc, season, week)
    if not played and final:
        # Only the final capture is expected to have it; a sweep runs before or
        # during the games, so an empty index there is the normal case.
        print("WARNING: Sleeper returned no participation data for this week — "
              "'played' will be blank and the build falls back to nflverse "
              "(which lags ~2-3 days) to tell a played week from a missed one.")
    rows = capture_rows(sc, season, week, played=played)
    if not rows:
        print(f"No rostered players found for {season} week {week}; nothing written.")
        return 0

    flagged = sum(1 for r in rows if r["injury_status"])
    on_bye = sum(1 for r in rows if r["on_bye"] == "true")
    did_play = sum(1 for r in rows if r["played"] == "true")
    summary = (f"{len(rows)} rostered players ({flagged} with an injury_status, "
               f"{did_play} confirmed to have played, {on_bye} on a bye) "
               f"for {season} week {week}")
    if args.dry_run:
        print(f"[dry run] Would {args.mode}-capture {summary}; CSV not written.")
        return 0

    if args.force:
        path = merge_into_csv(ROOT, rows)
    else:
        path = merge_capture(ROOT, rows, final=final)
    print(f"{args.mode.capitalize()} capture: {summary} -> {path}")

    if not final:
        # A sweep files a week that is still being played; the gap report is the
        # final capture's job, and would otherwise flag this very week.
        return 0

    swept = max(sweep_counts(ROOT, season, week), default=1) > 1
    if not swept:
        print(f"::warning::{season} week {week} was finalized with no gameday "
              f"sweep behind it, so its designations are only what Sleeper was "
              f"showing on Tuesday. A tag the team cleared on Monday is not in "
              f"this week.")

    gaps = missing_weeks(ROOT, season, week)
    if gaps:
        print(f"WARNING: {season} has no captured block for week(s) "
              f"{', '.join(str(g) for g in gaps)}. Sleeper keeps no injury "
              f"history, so those gaps are permanent — the build falls back to "
              f"nflverse for them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
