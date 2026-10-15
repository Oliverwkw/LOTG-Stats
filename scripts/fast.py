"""Stat checks in one command — the live week included. Read-only.

A thin command line over `lotg_support.fast` and `lotg_support.live`. Built so
the common inquiry ("most starters over 18 in a loss", "is X close to it before
the late window", "where does 44.2 rank", "when did I last have a 40") is ONE
command whose output already carries its caveats.

    # the live week: every matchup, every starter, slot, kickoff status
    python scripts/fast.py live
    python scripts/fast.py live --team Oliverwkw

    # per-team-week counts of players over a line, ranked, live week placed in
    python scripts/fast.py count 18 --loss --live
    python scripts/fast.py count 18 --loss --entering late --live --team Oliverwkw
    python scripts/fast.py count 20 --bench --no-qb
    python scripts/fast.py count 18 --pos WR,TE --ge
    python scripts/fast.py count all --slot MNF --live      # most starters playing Monday night

    # which sheet has a column? (team_week alone has ~300)
    python scripts/fast.py cols "margin entering|choke"

    # where a number would rank in any export column (filters as inquire.py)
    python scripts/fast.py rank player_week Points 44.2 --where Starter/Bench=Starter
    python scripts/fast.py rank team_week PF 199.48 --where 'Win?=False'

    # several parts of one question: chain with `::` (one process, one tool call)
    python scripts/fast.py count 20 --bench :: count 20 --bench --no-qb

    # anything else: one pandas expression over preloaded frames
    #   pw   = typed player_week + team result (fast.player_weeks)
    #   lpw  = pw with the live week appended (fetches Sleeper)
    #   live = the LiveWeek;  tw, ty, py, pa, ... = any export sheet (text)
    #   num(df, col) = numeric column;  twt, tyt, pyt, ... / T("sheet") = typed sheet
    #   statements are allowed; the last expression is printed
    python scripts/fast.py q "pw[(pw.Team=='Oliverwkw')&(pw.Points>=40)].sort_values(['Year','Week']).tail(3)"

`--snapshot` on `live` / `--live` reads the committed snapshot's copy of the
week instead of Sleeper (no network; as old as the snapshot).
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import fast, inquiry as Q  # noqa: E402

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 140)


_LIVE = {}


def _live(args):
    """The live week, fetched once per process (a `::` batch shares it)."""
    from lotg_support import live
    key = (getattr(args, "snapshot", False), args.season, args.week)
    if key not in _LIVE:
        if key[0]:
            if not (args.season and args.week):
                sys.exit("--snapshot needs --season and --week")
            _LIVE[key] = live.fetch(args.season, args.week, source="snapshot")
        else:
            _LIVE[key] = live.fetch(args.season, args.week)
    return _LIVE[key]


def _notes(lines):
    for line in lines:
        print(f"# {line}")


def cmd_live(args) -> None:
    lw = _live(args)
    _notes(lw.caveats())
    tw = lw.team_week.sort_values("PF", ascending=False)
    print(tw.drop(columns=["Year", "Week"]).to_string(index=False))
    pw = lw.player_week
    teams = [Q.canonical_team(args.team)] if args.team else list(tw["Team"])
    for t in teams:
        st = pw[(pw["Team"] == t) & (pw["Starter/Bench"] == "Starter")]
        row = tw[tw["Team"] == t].iloc[0]
        print(f"\n{t} {row.PF:g} vs {row.Opponent} {row['Points against']:g}")
        for r in st.sort_values("Points", ascending=False).to_dict("records"):
            k = r["Kickoff"]
            kick = k.strftime("%a %H:%M") if k is not None and pd.notna(k) else "-"
            print(f"  {r['Player']:<24} {r['Position']:<3} {r['NFL team']:<4} {r['Points']:>6.2f}  "
                  f"{r['Game slot']:<14} {kick:<9} {r['Game status']}")
        if args.bench:
            b = pw[(pw["Team"] == t) & (pw["Starter/Bench"] == "Bench")].sort_values("Points", ascending=False)
            print("  bench: " + ", ".join(f"{r.Player} {r.Points:g}" for r in b.itertuples()))


def _slots(args):
    return [x.strip() for x in args.slot.split(",")] if getattr(args, "slot", None) else None


def cmd_count(args) -> None:
    lw = _live(args) if args.live else None
    role = "bench" if args.bench else ("any" if args.any else "starter")
    exclude = ["QB"] if args.no_qb else None
    pos = [p.strip().upper() for p in args.pos.split(",")] if args.pos else None
    years = [int(y) for y in args.year.split(",")] if args.year else None
    c = fast.count_over(args.threshold, role=role, strict=not args.ge, positions=pos, exclude=exclude,
                        result=("loss" if args.loss else "win" if args.win else None),
                        entering=args.entering, years=years, live=lw, slots=_slots(args))
    if lw is not None:
        _notes(lw.caveats())
    _notes(fast.caveats(c))
    hist = c[~c["Live"]]
    print("distribution (team-weeks, finished): " + str(hist["n"].value_counts().sort_index().to_dict()))
    cols = ["Team", "Year", "Week", "Week Name", "Opponent", "Margin", "PF", "starters", "n", "at_threshold", "who"]

    def show(view, label):
        if not len(view):
            print(f"{label}: none")
            return
        cut = view["n"].iloc[min(args.n, len(view)) - 1]
        top = view[view["n"] >= max(cut, 1)]          # every tie at the cut line
        print(f"{label}:")
        print(top[cols].to_string(index=False) if len(top) else "  (no team-week above 0)")

    show(hist, "league, most first")
    # pre-counted so an answer never has to count printed rows
    for v in sorted(hist.loc[hist["n"] > 0, "n"].unique(), reverse=True)[:3]:
        at = hist[hist["n"] == v]
        by = at["Team"].value_counts()
        print(f"  exactly {v}: {len(at)} team-week(s) — " + ", ".join(f"{k} {c}" for k, c in by.items()))
    if args.team:
        t = Q.canonical_team(args.team)
        mine = hist[hist["Team"].str.lower() == t.lower()]
        best = int(mine["n"].max()) if len(mine) else 0
        print(f"\n{t}: best {best}, done {int((mine['n'] == best).sum())} time(s); "
              f"league record {int(hist['n'].max()) if len(hist) else 0}")
        show(mine.head(max(args.n, 5)), f"{t}, most first")
    if lw is not None:
        # every live team, whether or not it meets --loss/--win right now
        full = fast.count_over(args.threshold, role=role, strict=not args.ge, positions=pos, exclude=exclude,
                               entering=args.entering, live=lw, slots=_slots(args))
        lv = full[full["Live"]]
        if args.team:
            lv = lv[lv["Team"].str.lower() == Q.canonical_team(args.team).lower()]
        record = int(hist["n"].max()) if len(hist) else 0
        when = f"entering {fast.stage_name(args.entering)}" if args.entering else "now"
        print(f"\nlive week ({when}; record above = {record}):")
        for r in lv.sort_values("n", ascending=False).rename(columns={"Stage kickoff": "Stage_kickoff"}).itertuples():
            rk, tie, of = fast.place(hist["n"], r.n)
            state = "behind" if r.Margin < 0 else ("ahead" if r.Margin > 0 else "level")
            ok = (not args.loss or r.Margin < 0) and (not args.win or r.Margin > 0)
            print(f"  {r.Team:<16} n={r.n} ({state} {r.Margin:+.2f}) -> would be {'tied ' if tie else ''}{fast.ordinal(rk)} of {of}"
                  f"{f' (with {tie})' if tie else ''}{'' if ok else ' [does not qualify right now]'}"
                  f"{'; ' + r.who if r.who else ''}")
            st = lw.player_week[(lw.player_week["Team"] == r.Team) & (lw.player_week["Starter/Bench"] == "Starter")]
            if args.entering and getattr(r, "Stage_kickoff", None) is not None:
                st = st[st["Kickoff"].notna() & (st["Kickoff"] < r.Stage_kickoff)]
            if pos:
                st = st[st["Position"].isin(pos)]
            if _slots(args):
                st = st[st["Game slot"].isin([fast.slot_name(x) for x in _slots(args)])]
            if exclude:
                st = st[~st["Position"].isin(exclude)]
            pending = st[st["Game status"] != "final?"]
            if len(pending):
                print("      still to finish" + (f" before {fast.stage_name(args.entering)}" if args.entering else "")
                      + ": " + ", ".join(f"{x['Player']} {x['Points']:g} ({x['Game slot']}, {x['Game status']})"
                                         for x in pending.to_dict("records")))


def cmd_rank(args) -> None:
    df = Q.filter_rows(Q.load_sheet(args.sheet), *args.where)
    col = Q.numeric(df, args.column)
    rk, tie, of = fast.place(col, args.value, higher_is_better=not args.low)
    print(f"{args.value:g} would be {'tied ' if tie else ''}{fast.ordinal(rk)} of {of} in {args.sheet}.{args.column}"
          f"{' (low end)' if args.low else ''}{f' (with {tie})' if tie else ''}"
          f"{' — filters: ' + ' & '.join(args.where) if args.where else ''}")
    show = df.assign(_v=col).dropna(subset=["_v"]).sort_values("_v", ascending=args.low).head(args.n)
    keys = [k for k in ("Player", "Team", "Year", "Week", "Week Name", "Opponent") if k in show.columns]
    print(show[keys + [args.column]].to_string(index=False))


class _Lazy(dict):
    def __init__(self, args):
        super().__init__()
        self.args = args

    def __missing__(self, key):
        if key == "pw":
            v = fast.player_weeks()
        elif key == "live":
            v = _live(self.args)
        elif key == "lpw":
            v = fast.player_weeks(self["live"])
        elif key == "num":
            v = Q.numeric
        elif key == "T":
            v = fast.typed_sheet
        elif key == "cols":
            v = fast.find_columns
        elif key in ("twt", "tyt", "pyt", "lwt", "lyt"):
            v = fast.typed_sheet({"twt": "team_week", "tyt": "team_year", "pyt": "player_year",
                                  "lwt": "league_week", "lyt": "league_year"}[key])
        elif key in ("pd", "fast", "Q"):
            v = {"pd": pd, "fast": fast, "Q": Q}[key]
        else:
            alias = {"tw": "team_week", "ty": "team_year", "ta": "team_all_time", "py": "player_year",
                     "pa": "player_all_time", "lw": "league_week", "ly": "league_year"}.get(key, key)
            try:
                v = Q.load_sheet(alias)
            except KeyError:
                raise KeyError(key)
        self[key] = v
        return v


def cmd_q(args) -> None:
    import ast
    env = _Lazy(args)
    g = {"__builtins__": __builtins__}
    tree = ast.parse(args.expr.strip())
    last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    if tree.body:   # statements first (assignments, imports); the last expression is printed
        exec(compile(tree, "<q>", "exec"), g, env)   # noqa: S102 - local CLI
    if last is None:
        return
    out = eval(compile(ast.Expression(last.value), "<q>", "eval"), g, env)   # noqa: S307 - local CLI
    print(out.to_string() if hasattr(out, "to_string") else out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def live_opts(p):
        p.add_argument("--season", type=int)
        p.add_argument("--week", type=int)
        p.add_argument("--snapshot", action="store_true", help="committed snapshot instead of Sleeper")

    p = sub.add_parser("live", help="the live week: scores, starters, slots")
    p.add_argument("--team")
    p.add_argument("--bench", action="store_true")
    live_opts(p)
    p.set_defaults(fn=cmd_live)

    p = sub.add_parser("count", help="per team-week count of players over a line")
    p.add_argument("threshold", type=lambda x: float("-inf") if x.lower() in ("all", "any") else float(x),
                   help="a number, or `all` to count every player")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--bench", action="store_true")
    g.add_argument("--any", action="store_true", help="starters and bench")
    p.add_argument("--pos", help="only these positions, e.g. WR,TE")
    p.add_argument("--no-qb", action="store_true")
    p.add_argument("--ge", action="store_true", help=">= instead of >")
    r = p.add_mutually_exclusive_group()
    r.add_argument("--loss", action="store_true")
    r.add_argument("--win", action="store_true")
    p.add_argument("--entering", help="stage: late / early / SNF / Monday / any game slot")
    p.add_argument("--slot", help="only players whose game is in these slots, e.g. MNF or SNF,MNF")
    p.add_argument("--team")
    p.add_argument("--year", help="comma list")
    p.add_argument("--live", action="store_true", help="place the live week against history")
    p.add_argument("-n", type=int, default=10)
    live_opts(p)
    p.set_defaults(fn=cmd_count)

    p = sub.add_parser("cols", help="find a column across every export sheet")
    p.add_argument("regex")
    p.set_defaults(fn=lambda a: print(fast.find_columns(a.regex).to_string(index=False)))

    p = sub.add_parser("rank", help="where a value would rank in an export column")
    p.add_argument("sheet")
    p.add_argument("column")
    p.add_argument("value", type=float)
    p.add_argument("--where", action="append", default=[])
    p.add_argument("--low", action="store_true", help="lower is better")
    p.add_argument("-n", type=int, default=5)
    p.set_defaults(fn=cmd_rank)

    p = sub.add_parser("q", help="evaluate one pandas expression over preloaded frames")
    p.add_argument("expr")
    live_opts(p)
    p.set_defaults(fn=cmd_q)

    if hasattr(signal, "SIGPIPE"):          # `| head` closes the pipe: exit quietly
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    argv = list(sys.argv[1:] if argv is None else argv)
    # `a :: b :: c` runs several subcommands in ONE process: one load, one
    # Sleeper fetch, one tool call for a question with several parts.
    parts, cur = [], []
    for tok in argv:
        if tok == "::":
            parts.append(cur)
            cur = []
        else:
            cur.append(tok)
    parts.append(cur)
    parts = [p for p in parts if p]
    for i, part in enumerate(parts):
        if len(parts) > 1:
            print(f"{'' if i == 0 else chr(10)}===== fast.py {' '.join(part)}")
        args = ap.parse_args(part)
        args.fn(args)


if __name__ == "__main__":
    main()
