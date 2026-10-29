"""Start/sit, add/drop and strategy data in one command. Read-only.

    python scripts/advise.py startsit Oliverwkw          # set lineup vs best on 3 bases, injuries, byes, matchups
    python scripts/advise.py waivers Oliverwkw [--pos RB,WR] [-n 15]   # FAs by what they add to YOUR lineup + drop candidates
    python scripts/advise.py strategy Oliverwkw          # window: standings, odds, positional ranks, ages, picks
    python scripts/advise.py roster Oliverwkw            # every player with all the columns
    # startsit / waivers also print usage + xFP (snap %, targets, carries, red-zone looks,
    # expected points, points minus xFP; season vs last 3) for the rows shown
    python scripts/advise.py startsit Oliverwkw :: waivers Oliverwkw --pos RB   # chain with ::
    # ends with the strategy-guide files for each subcommand, read live from project memory
    # (lotg_support.guide); --no-guide leaves them out

It prints data and caveats, not a verdict: the answer still needs the news
(injury reports, role changes), the matchup read, and the league's strategy
guide in project memory. Points are this league's scoring of Sleeper's stats
(free agents included); reconciled with Sleeper's matchup points in
tests/test_advise.py.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

import pandas as pd  # noqa: E402

from lotg_support import advise as A, inquiry as Q  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

_STATE = {}


def _ctx():
    if "lg" not in _STATE:
        lg = A.league_now()
        _STATE["lg"], _STATE["b"] = lg, A.board(lg)
    return _STATE["lg"], _STATE["b"]


def _team(name: str) -> str:
    return Q.canonical_team(name)


def _head(lg, what):
    print(f"{what} — {lg.year} week {lg.week} (results final through week {lg.done}); "
          f"Sleeper as of {lg.fetched}")


def _usage(lg, b, index):
    """The usage / xFP table for these board rows, then its data flags."""
    try:
        u, flags = A.usage(b, lg, index)
    except Exception as exc:  # noqa: BLE001 - usage is extra; never lose the rest
        print(f"\n(usage / xFP unavailable: {exc})")
        return
    print(f"\nusage + xFP (nflverse / ffopportunity, {lg.year} weeks 1-{lg.done}; L3 = last 3 NFL weeks; "
          "xFP = expected points of his targets/carries in league scoring):")
    print(u.fillna("").to_string(index=False))
    for f in flags:
        print(f"# usage: {f}")
    print("# usage: points above xFP with flat xFP/snaps = efficiency/TDs (rarely sticky); xFP or snap% rising = a "
          "role change (sticky while it lasts). nflverse lags Sleeper by a day or two after games")


def _common_caveats(lg):
    print(f"# points = this league's scoring of Sleeper's NFL stats; G/PPG count games played (gp>0); "
          f"L3 = last 3 played weeks; proj = Sleeper's week-{lg.week} projection, league-scored")
    print("# injury / depth chart = Sleeper's player feed now (not the NFL report itself — check the report and news)")
    print("# strategy: read the league strategy guide before a verdict - the files MEMORY.md's 'Strategy guide' line"
          " lists (dynasty-strategy, dynasty-picks-trades, weekly-lineup-strategy, waivers-streaming, league-settings,"
          " ...); cite the rule used, add any new lesson there. Not readable? say no guide rule was applied")


def cmd_startsit(args):
    lg, b = _ctx()
    team = _team(args.team)
    _head(lg, f"START/SIT {team}")
    t, totals = A.start_sit(b, lg, team)
    print(t.fillna("").to_string(index=False))
    print("\nbest-lineup totals (weekly pts): " + ", ".join(f"{k} {v}" for k, v in totals.items()))
    _usage(lg, b, t.index)
    if args.dvp:
        d = A.dvp(lg)
        opp = {r["Player"]: r["opp"].split()[-1] for _, r in t.iterrows() if r["opp"] not in ("", "BYE")}
        rows = []
        for p, o in opp.items():
            pos = t.loc[t["Player"] == p, "Pos"].iloc[0]
            m = d[(d["defense"] == o) & (d["Pos"] == pos)]
            if len(m):
                rows.append({"Player": p, "Pos": pos, "opp": o, "allowed/gm": round(m["allowed"].iloc[0], 1),
                             "rank (1=most)": int(m["rank"].iloc[0])})
        print("\nmatchups: points the opponent allows to the position (top-2 scorers per game, this season;"
              " players mapped by their CURRENT NFL team, so a mid-season move blurs it):")
        print(pd.DataFrame(rows).to_string(index=False))
    _common_caveats(lg)
    print("# best:<basis> = the slot that player fills in the best lineup on that basis; flag start?/sit? where "
          "the set lineup differs from the projection's best. Taxi/IR cannot start.")
    miss = t[(t["set"] == "START") & (t[f"proj wk{lg.week}"].isna())]
    for p in miss["Player"]:
        print(f"# {p}: in the set lineup with NO Sleeper projection (usually ruled out / doubtful) — check news")


def cmd_waivers(args):
    lg, b = _ctx()
    team = _team(args.team)
    _head(lg, f"WAIVERS {team} (FAAB left {lg.budget_left.get(team, '?')} of 100)")
    pos = [p.strip() for p in args.pos.split(",")] if args.pos else None
    top, drops = A.waivers(b, lg, team, args.n, pos)
    print("free agents, by weekly points they add to your best lineup:")
    print(top.fillna("").to_string(index=False))
    print("\ndrop candidates (least lineup value lost on season PPG; taxi/IR excluded):")
    print(drops.fillna("").to_string(index=False))
    _usage(lg, b, list(top.index) + list(drops.index))
    left = sorted(lg.budget_left.items(), key=lambda kv: -kv[1])
    print("\nFAAB left (of a 100 budget): " + ", ".join(f"{t} {v}" for t, v in left))
    _common_caveats(lg)
    print("# drop cost is THIS season's weekly lineup value only — dynasty value (age, role, KTC, superflex QB scarcity)"
          " is not in it; never call a drop from this column alone")
    print("# FAAB: the league plays a 100 budget with house rules (Oliver, 2026-10-15); Sleeper's setting says 10000, so"
          " 'left' = 10000 minus Sleeper's used count, which lands on the 100 scale (every team 0-100 since 2024)."
          " House rules are not modelled: never quote a bid against 10000, and check the rules before advising a bid")
    print("# season basis averages players with <3 games with last season / the projection (small samples)")
    print("# +lineup = best-lineup points with him added minus without (0 = he would not start for you); "
          "a bench-depth / handcuff / bye-cover add can still be right at 0 — say so")


def cmd_strategy(args):
    lg, b = _ctx()
    team = _team(args.team)
    _head(lg, f"STRATEGY {team}")
    from lotg_support import fast
    from lotg_support import forecast as F, trade as T
    st = T.standings(lg.year)
    fc = F.forecast(lg.year, sims=args.sims, calibration=T._calibration())
    odds = pd.DataFrame([{"team": o.team, "pts/wk": round(o.projection, 1), "title %": o.champion,
                          "finals %": o.finals, "playoffs %": o.playoffs, "exp wins": round(o.expected_wins, 1)}
                         for o in fc.odds]).set_index("team")
    print("standings + forecast:")
    print(st.join(odds).sort_values("title %", ascending=False).to_string())
    ps = A.position_strength(b, lg)
    print("\npositional strength (sum of top-k season PPG: QB2 RB3 WR4 TE1; rank 1 = best):")
    print(ps.to_string())
    print("\naverage age by position (rostered):")
    print(A.age_profile(b).to_string())
    try:
        print("\nfuture rookie picks held (rounds; Sleeper traded_picks in the snapshot):")
        print(A.picks_owned(lg.year, lg).fillna("").to_string())
    except Exception as exc:   # noqa: BLE001
        print(f"\n(picks unavailable: {exc})")
    try:
        from lotg_support import draft_capital as D
        mx = D.built_max_pf(lg.year, regular_season_only=True)
        rule = D.order_rule(lg.year + 1)
        print(f"\nnext draft ({lg.year + 1}) orders the bottom four by "
              f"{'ascending Max PF (lowest ceiling picks 1.01), NOT record' if rule == 'max_pf' else 'reverse placement'}"
              f" - Max PF to date (weeks 1-{lg.done}): "
              + ", ".join(f"{t} {v:.0f}" for t, v in sorted(mx.items(), key=lambda kv: kv[1])))
    except Exception as exc:   # noqa: BLE001
        print(f"\n(draft-order rule unavailable: {exc})")
    meta = Q.season_meta(lg.year)
    print(f"\n# playoffs: {getattr(meta, 'playoff_teams', '?')} teams from week "
          f"{getattr(meta, 'playoff_week_start', '?')}; regular season {meta.regular_season_weeks} weeks")
    print(f"# forecast: {fc.sims} sims; rates as trade.py states them (run trade.py for a deal's effect)")
    _common_caveats(lg)


def cmd_roster(args):
    lg, b = _ctx()
    team = _team(args.team)
    _head(lg, f"ROSTER {team}")
    t = b[b["Owner"] == team].sort_values(["Pos", "PPG"], ascending=[True, False])
    print(t.drop(columns=["pid", "Owner"]).fillna("").to_string(index=False))
    _common_caveats(lg)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("startsit"); p.add_argument("team"); p.add_argument("--no-dvp", dest="dvp", action="store_false")
    p.set_defaults(fn=cmd_startsit)
    p = sub.add_parser("waivers"); p.add_argument("team"); p.add_argument("--pos"); p.add_argument("-n", type=int, default=15)
    p.set_defaults(fn=cmd_waivers)
    p = sub.add_parser("strategy"); p.add_argument("team"); p.add_argument("--sims", type=int, default=5000)
    p.set_defaults(fn=cmd_strategy)
    p = sub.add_parser("roster"); p.add_argument("team"); p.set_defaults(fn=cmd_roster)
    argv = list(sys.argv[1:] if argv is None else argv)
    show_guide = "--no-guide" not in argv
    argv = [a for a in argv if a != "--no-guide"]
    parts, cur = [], []
    for tok in argv:
        if tok == "::":
            parts.append(cur); cur = []
        else:
            cur.append(tok)
    parts.append(cur)
    for i, part in enumerate(p for p in parts if p):
        if i:
            print("\n" + "=" * 100)
        args = ap.parse_args(part)
        args.fn(args)
    if show_guide:
        from lotg_support import guide
        topics = []
        for part in parts:
            if part and part[0] not in topics:
                topics.append(part[0])
        print("\n" + "=" * 100 + "\n" + guide.render(topics))


if __name__ == "__main__":
    main()
