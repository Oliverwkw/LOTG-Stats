#!/usr/bin/env python3
"""Weekly Sleeper injury snapshot (PR E fix B).

Run by .github/workflows/capture_injuries.yml every Monday night during the
NFL season. Pulls Sleeper's current injury_status/status for every rostered
player in the league and appends a (season, week) block to
data/injury_tracker.csv, which the main build reads as its primary
injury/suspension source.

Uses an UNCACHED Sleeper client so it always reads live data. Season/week come
from Sleeper's /state/nfl; pass --season/--week to override (testing/backfill).
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
    capture_rows, current_state, merge_into_csv,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "league.yaml").read_text())
    http = HttpConfig(timeout_seconds=30, max_retries=10, backoff_base_seconds=0.7)
    # cache_dir=None -> never cache; the snapshot must be live.
    sc = SleeperClient(str(cfg["league_id"]), http, cache_dir=None)

    season, week = args.season, args.week
    if season is None or week is None:
        s2, w2 = current_state(sc)
        season = season if season is not None else s2
        week = week if week is not None else w2

    if not season or not week or int(week) < 1:
        print(f"No active NFL scoring week (season={season}, week={week}); nothing to capture.")
        return 0

    rows = capture_rows(sc, int(season), int(week))
    if not rows:
        print(f"No rostered players found for {season} week {week}; nothing written.")
        return 0
    path = merge_into_csv(ROOT, rows)
    flagged = sum(1 for r in rows if r["injury_status"])
    print(f"Captured {len(rows)} rostered players ({flagged} with an injury_status) "
          f"for {season} week {week} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
