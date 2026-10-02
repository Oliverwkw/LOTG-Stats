"""How bold was that lineup call?

A thin command line over `lotg_support.boldness`. For every start (2020 on) it
compares the starter's pre-kickoff expected points with the best startable bench
player's (taxi counts as bench), and prints. It changes nothing — no export, no
workflow, no build output; the only thing it writes is the nflverse download
cache under `.cache/`.

    # one team-week, start by start (the in-progress week works too)
    python scripts/boldness.py week --season 2026 --week 4 --team BROsenzweig

    # the boldest starts ever (games that mattered; --all keeps tank weeks)
    python scripts/boldness.py top -n 20
    python scripts/boldness.py top --position QB
    python scripts/boldness.py top --all

    # managers, seasons, positions; team-weeks by ex-ante Max PF minus expected PF
    python scripts/boldness.py managers
    python scripts/boldness.py teams -n 10

    # the guards
    python scripts/boldness.py validate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support import boldness as B  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_COLS = ["Year", "Week", "Team", "Slot", "Starter", "E starter", "Starter source",
         "Reference", "E reference", "Boldness", "Bust odds", "Starter points",
         "Reference points", "Starter promoted over", "Low stakes"]


def _history(args) -> pd.DataFrame:
    h = B.with_bust_odds(B.history())
    h = h[~h["Starter unavailable?"] & h["Boldness"].notna()]
    if not getattr(args, "all", False):
        h = h[h["Low stakes"].isna()]
    return h


def cmd_week(args) -> None:
    coef = B.fit_bust_odds(B.history(include_live=False))
    df = B.with_bust_odds(B.boldness(args.season, weeks=[args.week]), coef)
    df = df[df["Team"].str.lower() == args.team.lower()]
    print(df[_COLS[3:13]].to_string(index=False))
    tb = B.team_boldness(args.season, weeks=[args.week])
    print(tb[tb["Team"].str.lower() == args.team.lower()].to_string(index=False))


def cmd_top(args) -> None:
    h = _history(args)
    if args.position:
        h = h[h["Starter position"] == args.position.upper()]
    done = h[~h["Live week?"]]
    print(f"{len(done)} completed starts ranked"
          f"{'' if args.all else ' (low-stakes weeks excluded; --all keeps them)'}")
    print(h.sort_values("Boldness", ascending=False).head(args.n)[_COLS].to_string(index=False))


def cmd_managers(args) -> None:
    h = _history(args)
    h = h[~h["Live week?"]].assign(Team=lambda d: d["Team"].str.lower())
    g = h.groupby("Team")
    out = pd.DataFrame({
        "starts": g.size(),
        "mean boldness": g["Boldness"].mean(),
        "% of starts bold": g["Boldness"].apply(lambda s: (s > 0).mean() * 100),
        "bold>=3": g["Boldness"].apply(lambda s: (s >= 3).sum()),
        "bold>=3 beat reference %": g.apply(lambda d: (d.loc[d["Boldness"] >= 3, "Result"] > 0).mean() * 100),
    }).sort_values("mean boldness", ascending=False)
    print(out.round(2).to_string())


def cmd_teams(args) -> None:
    seasons = sorted(set(Q.export_seasons()) | set(Q.snapshot_seasons()))
    tb = pd.concat([B.team_boldness(s) for s in seasons], ignore_index=True)
    print(tb.sort_values("Team boldness", ascending=False).head(args.n).to_string(index=False))


def cmd_validate(args) -> None:
    problems = []
    for y in sorted(set(Q.completed_seasons()) | {2020}):
        problems += B.check_points_reconcile(y)
        problems += B.check_team_boldness_bounds(y)
    problems += B.check_calibration(B.history(include_live=False))
    print("\n".join(problems) if problems else "all boldness guards pass")
    sys.exit(1 if problems else 0)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("week")
    w.add_argument("--season", type=int, required=True)
    w.add_argument("--week", type=int, required=True)
    w.add_argument("--team", required=True)
    w.set_defaults(fn=cmd_week)
    t = sub.add_parser("top")
    t.add_argument("-n", type=int, default=20)
    t.add_argument("--position")
    t.add_argument("--all", action="store_true")
    t.set_defaults(fn=cmd_top)
    m = sub.add_parser("managers")
    m.add_argument("--all", action="store_true")
    m.set_defaults(fn=cmd_managers)
    te = sub.add_parser("teams")
    te.add_argument("-n", type=int, default=10)
    te.set_defaults(fn=cmd_teams)
    v = sub.add_parser("validate")
    v.set_defaults(fn=cmd_validate)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
