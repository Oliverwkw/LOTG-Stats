"""Who actually reached the end zone under a fantasy lineup.

A thin command line over `lotg_support.scoring_events`. It joins nflverse's
weekly stat lines onto this league's starters — nothing in `exports/` or the
snapshot records a touchdown — prints, and changes nothing: no export, no
workflow, no build output. The only thing it writes is the nflverse download
cache under `.cache/`.

    # the scan: team-weeks where no non-QB starter scored
    python scripts/touchdowns.py drought
    python scripts/touchdowns.py drought --qb-rule slot     # superflex QB counts too
    python scripts/touchdowns.py drought --season 2025

    # one lineup, player by player
    python scripts/touchdowns.py lineup --season 2025 --week 12 --team Oliverwkw

    # a season's scorers, most touchdowns first
    python scripts/touchdowns.py scorers --season 2025

    # the guards that tie the join to numbers the build already published
    python scripts/touchdowns.py validate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import scoring_events as SE  # noqa: E402

_SHOW = ["Year", "Week", "Team", "Player", "Position", "slot", "Points",
         "touchdowns", "passing_touchdowns", "resolved"]


def _seasons(args):
    return [int(args.season)] if args.season else None


def cmd_drought(args):
    """Team-weeks in which no non-quarterback starter scored a touchdown."""
    scan = SE.lineups_without_touchdowns(seasons=_seasons(args), qb_rule=args.qb_rule)
    if scan.empty:
        print("no such team-week")
        return
    print(scan.to_string(index=False))
    flagged = int((scan["unresolved"] > 0).sum())
    print(f"\n{len(scan)} team-week(s), qb_rule={args.qb_rule}. "
          f"{flagged} carry a starter with no stat line — read those as candidates.")


def cmd_lineup(args):
    """One team's week, starter by starter."""
    rows = SE.starter_touchdowns(int(args.season), weeks=[int(args.week)])
    rows = rows[rows["Team"] == args.team] if args.team else rows
    print(rows[_SHOW].to_string(index=False))


def cmd_scorers(args):
    """A season's starters ranked by touchdowns scored while started."""
    rows = SE.starter_touchdowns(int(args.season))
    ranked = (rows.groupby(["Player", "Position"], as_index=False)
              .agg(touchdowns=("touchdowns", "sum"), starts=("Player", "count"),
                   points=("Points", "sum"))
              .sort_values("touchdowns", ascending=False))
    print(ranked.head(args.n).to_string(index=False))


def cmd_validate(args):
    """Run the module's guards."""
    problems = []
    seasons = _seasons(args) or [y for y in Q.export_seasons()
                                 if not Q.season_meta(y).has_snapshot
                                 or y in Q.completed_seasons()]
    for season in seasons:
        problems += SE.check_touchdown_join(season)
    problems += SE.check_2020_coverage()
    for line in problems:
        print(f"FAIL {line}")
    print("all checks passed" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv=None):
    # The flags hang off a shared parent so they are accepted AFTER the
    # subcommand, which is where anyone reading the examples above will type them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--season", type=int, help="restrict to one season")
    common.add_argument("--week", type=int, help="lineup: which week")
    common.add_argument("--team", help="lineup: which team")
    common.add_argument("--qb-rule", choices=SE.QB_RULES, default="position",
                        help="drought: what counts as a quarterback (default: position)")
    common.add_argument("-n", type=int, default=25, help="scorers: how many rows")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("drought", cmd_drought), ("lineup", cmd_lineup),
                     ("scorers", cmd_scorers), ("validate", cmd_validate)):
        sub.add_parser(name, help=fn.__doc__, parents=[common]).set_defaults(func=fn)
    args = parser.parse_args(argv)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 400)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
