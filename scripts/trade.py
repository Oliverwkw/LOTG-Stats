"""Trade check in one command. Read-only.

    python scripts/trade.py shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard"
    python scripts/trade.py shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard" \\
        --give-pick "2029 3rd" --rate "Chuba Hubbard=16" --healthy "A.J. Brown"
    # several scenarios in one call: chain with `::` (calibration is shared)
    python scripts/trade.py shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard" \\
        :: shmuel256 --give "Christian McCaffrey" --get "A.J. Brown,Chuba Hubbard" --rate "Chuba Hubbard=16"

Prints, for the side named first and its partner (found from the rosters):
the moving players (this season vs the last two, and what the forecast assumes
for each: rate, availability, IR / designation), both teams' record, position
depth before and after, then title / finals / playoff odds and projected
weekly points before and after for every team — plus the caveats that apply.
`--rate NAME=PPG` and `--healthy NAME` apply to both runs, so the change shown
is the trade's alone under those assumptions. `--no-forecast` skips the odds.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

import pandas as pd  # noqa: E402

from lotg_support import fast, trade as T  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def _split(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def one(args, pw) -> None:
    tr = T.resolve(args.team, _split(args.give), _split(args.get), args.year,
                   _split(args.give_pick), _split(args.get_pick))
    rate = {}
    for item in args.rate:
        name, _, v = item.rpartition("=")
        rate[T.Q.players().name(T._find(name, T._rosters(tr.year, tr.week))[0])] = float(v)
    healthy = _split(",".join(args.healthy))
    print(f"TRADE {tr.year} (rosters wk {tr.week}): {tr.team} gives {', '.join(tr.give.values())}"
          f"{' + ' + ', '.join(tr.picks_give) if tr.picks_give else ''} | gets "
          f"{', '.join(tr.get.values())}{' + ' + ', '.join(tr.picks_get) if tr.picks_get else ''}"
          f" | partner {tr.partner}")
    table = T.player_table(tr, pw)
    print("\nplayers (G / PPG = weeks with non-zero points; fcst = forecast's rate and weekly availability):")
    print(table.to_string(index=False))
    if not args.no_ktc:
        kt, note = T.ktc_values(tr)
        print(f"\n{note} — one small input:")
        if len(kt):
            print(kt.fillna("").to_string(index=False))
    st = T.standings(tr.year)
    print(f"\nstandings {tr.year}:")
    print(st.to_string())
    for team in (tr.team, tr.partner):
        b, a = T.depth(tr, team, False, pw, args.depth), T.depth(tr, team, True, pw, args.depth)
        print(f"\n{team} depth, before | after (* = moving):")
        w = max(len(b), len(a))
        both = pd.concat([b.reindex(range(w)).add_suffix(" (before)"), a.reindex(range(w)).add_suffix(" (after)")], axis=1)
        print(both.fillna("").to_string(index=False))
    run_ = None
    if not args.no_forecast:
        run_ = T.run(tr, sims=args.sims, rate=rate, healthy=healthy)
        print("\nforecast (projection = expected weekly points with injuries; depth_cost = healthy minus that;"
              " champion/finals/playoffs in %):")
        print(run_.delta().to_string())
    print()
    for c in T.caveats(tr, run_, table):
        print(f"# {c}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("team", help="the side you are advising")
    ap.add_argument("--give", required=True, help="comma list of players that team sends")
    ap.add_argument("--get", required=True, help="comma list of players it receives")
    ap.add_argument("--give-pick", help="comma list, noted (not modelled)")
    ap.add_argument("--get-pick", help="comma list, noted (not modelled)")
    ap.add_argument("--rate", action="append", default=[], help='"Name=PPG" override, repeatable')
    ap.add_argument("--healthy", action="append", default=[], help="drop IR / Out caps for this player")
    ap.add_argument("--year", type=int)
    ap.add_argument("--sims", type=int, default=5000)
    ap.add_argument("--depth", type=int, default=5, help="players shown per position")
    ap.add_argument("--no-forecast", action="store_true")
    ap.add_argument("--no-ktc", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    parts, cur = [], []
    for tok in argv:
        if tok == "::":
            parts.append(cur); cur = []
        else:
            cur.append(tok)
    parts.append(cur)
    pw = fast.player_weeks()
    for i, part in enumerate(p for p in parts if p):
        if i:
            print("\n" + "=" * 100)
        one(ap.parse_args(part), pw)


if __name__ == "__main__":
    main()
