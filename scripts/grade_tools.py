"""Grade the advice tools by walk-forward replay. Read-only.

    python scripts/grade_tools.py startsit                 # every team-week since 2021: rec lineup vs set lineup
    python scripts/grade_tools.py startsit --by Team       # per manager (--by Year: per season)
    python scripts/grade_tools.py waivers [-N 4]           # tool's top free agent vs the add actually made
    python scripts/grade_tools.py trades [--sims 2000]     # trade.py odds deltas vs what the trade did (~4 s/trade, cached)
    python scripts/grade_tools.py all --save               # all three; --save writes the track-record lines
    python scripts/grade_tools.py startsit --year 2025 :: waivers --year 2025   # chain with ::

advise.py / trade.py print one track-record line from the last `--save` run
(`.cache/grade/track_record.json`). Method, caveats and findings:
plan/notes/ADVICE_TOOLS_GRADE.md. Nothing here writes to exports/.
"""
from __future__ import annotations

import argparse
import signal
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
warnings.simplefilter("ignore")

import pandas as pd  # noqa: E402

from lotg_support import grade as G  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

CAVEATS = [
    "# point in time: each week reads only earlier weeks' stats, that week's Sleeper projection, the roster as it"
    " stood and byes; never the week's results, Injury? flags or the build's projection columns",
    "# 2021 on (2020 has no snapshot); 8 teams, so per-manager rows are ~100 weeks each — read the ±se",
    "# positions = Sleeper's current dictionary; taxi approximated (season-end taxi not yet started = unstartable)",
    "# 'out' on the PPG bases = no Sleeper projection row or one under 0.5, or a bye (live: the injury feed)",
]
RECORD = {}


def _years(s):
    return [int(x) for x in s.split(",")] if s else None


def cmd_startsit(a):
    df = G.replay_startsit(_years(a.year))
    print(f"START/SIT replay — {len(df)} team-weeks, {df['Year'].min()}-{df['Year'].max()} "
          f"(through {df['Year'].max()} week {df[df['Year'] == df['Year'].max()]['Week'].max()})")
    print("vs set pts/wk = the recommended lineup's actual points minus the set lineup's; wins = regular-season"
          " results flipped against the opponent's actual score; set == rec % = weeks the manager set exactly it")
    print(G.summarize_startsit(df).to_string(index=False))
    if a.by:
        print(f"\nby {a.by}:")
        s = G.summarize_startsit(df, by=a.by, bases=G.BASES)
        print(s[s["basis"].isin(["proj", "hindsight best"])].to_string(index=False) if a.by == "Team" else s.to_string(index=False))
    print("\nper season (vs set pts/wk):")
    print(G.by_season_startsit(df).to_string())
    print("\npaired (a − b per team-week):")
    for x, y in (("proj", "season"), ("proj", "recent"), ("blend", "proj"), ("blend3", "proj")):
        print(f"  {x} − {y}: {G.paired_test(df, x, y)}")
    ref = G.reference_startsit(df)
    if ref:
        print("\nreference: " + ref)
    p = G.summarize_startsit(df, bases=("proj",)).iloc[0]
    RECORD["startsit"] = (f"track record: following the projection lineup vs the set one, {p['vs set pts/wk']:+.1f}"
                          f" ± {p['±se']:.1f} pts/wk, net {int(p['net wins']):+d} wins over {int(p['weeks'])}"
                          f" team-weeks {df['Year'].min()}-{df['Year'].max()}; season/L3 lineups LOSE"
                          f" {-(df['season'] - df['actual']).mean():.1f}/{-(df['recent'] - df['actual']).mean():.1f}"
                          " pts/wk to the set one")
    print("\n" + "\n".join(CAVEATS))


def cmd_waivers(a):
    df = G.replay_waivers(_years(a.year), horizon=a.N)
    print(f"WAIVERS replay — {len(df)} adds (leg 2+), next {a.N} weeks; lineup gain = points added to the team's"
          " hindsight-best lineup over its pre-add roster")
    print(G.summarize_waivers(df).to_string(index=False))
    print(f"\nthe added player's place in the tool's list: median {df['tool rank'].median():.0f} of a median pool of "
          f"{df['pool'].median():.0f}; top-1 {100 * (df['tool rank'] == 1).mean():.0f}%, top-5 "
          f"{100 * (df['tool rank'] <= 5).mean():.0f}%, top-15 {100 * (df['tool rank'] <= 15).mean():.0f}%")
    print("\nby kind:")
    print(df.groupby("kind").apply(lambda g: pd.Series({
        "adds": len(g), "added gain": round(g["added gain"].mean(), 2), "top gain": round(g["top gain"].mean(), 2),
        "same-pos top gain": round(g["same gain"].mean(), 2)})).to_string())
    print("\nby season:")
    print(df.groupby("Year")[["added gain", "top gain", "same gain"] + [f"{b} top gain" for b in G.RANKINGS]]
          .mean().round(2).to_string())
    print("\npaired, ranking a's top pick minus ranking b's (lineup gain per add):")
    for x in ("proj", "recent", "blend"):
        print(f"  +{x} − +season: {G.paired_test(df.rename(columns={'leg': 'Week'}), f'{x} top gain', 'season top gain')}")
    if a.show:
        print(df.sort_values("top gain", ascending=False).head(a.show).to_string(index=False))
    s = G.summarize_waivers(df)
    t = s.iloc[0]
    sp = s.iloc[2]
    RECORD["waivers"] = (f"track record: the tool's top add vs the add made, next {a.N} wks, {t['mean diff']:+.1f}"
                         f" ± {t['±se']:.1f} lineup pts (ahead {t['tool ahead %']:.0f}%, tied {t['tied %']:.0f}%);"
                         f" at the same position {sp['mean diff']:+.1f} ± {sp['±se']:.1f}; {len(df)} adds")
    print("\n" + "\n".join(CAVEATS))
    print("# the top free agent was not always gettable (another team's bid / priority): this is an upper bound")


def cmd_trades(a):
    def prog(i, n):
        print(f"  ... {i}/{n}", file=sys.stderr, flush=True)
    df = G.replay_trades(_years(a.year), sims=a.sims, progress=prog if not a.quiet else None)
    print(f"TRADES replay — {df['tid'].nunique()} two-team in-season trades, {len(df)} sides, "
          f"{df['Year'].min()}-{df['Year'].max()}; forecast rewound to the week before the trade"
          " (leave-season-out calibration, backtest availability)")
    print("realized = Δ in the side's hindsight-best lineup pts/wk over the rest of the regular season, trade undone")
    print(G.summarize_trades(df).to_string(index=False))
    both = (df["fc pts/wk"].abs() >= 0.5) & (df["fc title %"].abs() >= 0.5)
    hit = (df.loc[both, "fc title %"].apply(lambda v: v > 0) == df.loc[both, "real pts/wk"].apply(lambda v: v > 0))
    print(f"\ntitle % sign where the pts/wk delta is also 0.5+: {100 * hit.mean():.0f}% of {int(both.sum())}"
          " — a title-odds move with a pts/wk move under 0.5 is mostly Monte Carlo noise")
    if a.show:
        print(df.sort_values("real pts/wk").to_string(index=False))
    s = G.summarize_trades(df).set_index("prediction")
    f, n = s.loc["fc pts/wk"], s.loc["naive pts/wk"]
    RECORD["trade"] = (f"track record: the forecast's pts/wk delta had the right sign on {f['hit %']:.0f}%"
                       f" ({f['95% CI']}) of {int(f['sides'])} past trade sides (naive season-PPG lineup:"
                       f" {n['hit %']:.0f}%); title-odds sign {s.loc['fc title %', 'hit %']:.0f}% (noise when pts/wk moves < 0.5)")
    print("\n" + "\n".join(CAVEATS))


def cmd_all(a):
    cmd_startsit(a)
    print()
    cmd_waivers(a)
    print()
    cmd_trades(a)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("startsit", "waivers", "trades", "all"):
        s = sub.add_parser(name)
        s.add_argument("--year", help="comma list of seasons (default: all)")
        s.add_argument("--by", choices=["Team", "Year"], help="startsit: split by manager or season")
        s.add_argument("-N", type=int, default=4, help="waivers: weeks after the add (default 4)")
        s.add_argument("--sims", type=int, default=2000, help="trades: sims per forecast")
        s.add_argument("--show", type=int, default=0, help="print the first N rows")
        s.add_argument("--quiet", action="store_true")
        s.add_argument("--save", action="store_true", help="write the track-record lines advise/trade print")
    chunks, cur = [], []
    for x in argv:
        if x == "::":
            chunks.append(cur)
            cur = []
        else:
            cur.append(x)
    chunks.append(cur)
    save = False
    for c in chunks:
        a = p.parse_args(c)
        save |= a.save
        {"startsit": cmd_startsit, "waivers": cmd_waivers, "trades": cmd_trades, "all": cmd_all}[a.cmd](a)
        print()
    if save and RECORD:
        print(f"track record written: {G.save_track_record(RECORD)}")


if __name__ == "__main__":
    main(sys.argv[1:])
