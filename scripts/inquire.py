"""Ask the built league data a question, without writing a script first.

A thin command line over `lotg_support.inquiry`. It changes nothing: every
subcommand opens committed files under `exports/` and prints. Nothing in the
build imports it and no workflow runs it.

The point is the first ten minutes of an inquiry. Most of that time normally
goes on "which of the twelve sheets has this, and what is the column called?"
(there are ~1,000 of them), on re-reading the snapshot layout, and on
rediscovering the same handful of traps. All of that is one command here.

    # where does a concept live?
    python scripts/inquire.py columns 'efficien|max pf'
    python scripts/inquire.py describe team_week Efficiency

    # leaderboards and filtered rows
    python scripts/inquire.py top player_year Points -n 10 --where Year=2025
    python scripts/inquire.py rows team_week --where Year=2025 --where 'Margin<1' \
        --select Team,Week,Opponent,Margin

    # judgement questions: position groups, lineup composition, scarcity, spend
    python scripts/inquire.py group WR --season 2025
    python scripts/inquire.py stacks --compare 'Max PF' --condition 'stack_WR>=2'
    python scripts/inquire.py scarcity --season 2025
    python scripts/inquire.py spend --team Oliverwkw

    # over-inclusive: rank on EVERY column, don't curate which stats to check
    python scripts/inquire.py sweep team_year --where Team=shmuel256 --where Year=2025 \
        --within Year=2025 --window 2
    python scripts/inquire.py extremes league_year

    # one entity, everything about it
    python scripts/inquire.py player 'Lamar Jackson'
    python scripts/inquire.py team shmuel256
    python scripts/inquire.py season 2025

    # the raw snapshot (what counterfactuals start from)
    python scripts/inquire.py trades --player 'Justin Herbert'
    python scripts/inquire.py roster 2025 6 --team shmuel256

    # are the replay primitives still sound?
    python scripts/inquire.py validate --season 2025

Add `--csv` to a table command to get parseable output instead of a grid.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import inquiry as Q  # noqa: E402

_POSITIONS = ("QB", "RB", "WR", "TE")


# ---------------------------------------------------------------------------
def _emit(df: pd.DataFrame, as_csv: bool, limit: int = 0) -> None:
    if limit:
        df = df.head(limit)
    if as_csv:
        print(df.to_csv(index=False).rstrip())
        return
    if df.empty:
        print("(no rows)")
        return
    with pd.option_context("display.max_columns", None, "display.width", 250,
                           "display.max_colwidth", 40):
        print(df.to_string(index=False))
    print(f"\n{len(df)} row(s)")


def _select(df: pd.DataFrame, select: str) -> pd.DataFrame:
    if not select:
        return df
    wanted = [c.strip() for c in select.split(",") if c.strip()]
    missing = [c for c in wanted if c not in df.columns]
    if missing:
        near = {m: [c for c in df.columns if m.lower() in c.lower()][:4] for m in missing}
        raise SystemExit(f"unknown column(s) {missing}; close matches: {near}")
    return df[wanted]


# ---------------------------------------------------------------------------
def cmd_sheets(args) -> None:
    for name, df in Q.all_sheets().items():
        print(f"{name:<18} {len(df):>6} rows  {len(df.columns):>4} columns   "
              f"key: {Q.ENTITY_COL.get(name) or '(single row)'}")
    print("\nseasons in exports:", Q.export_seasons())
    print("seasons with a Sleeper snapshot (replayable):", Q.snapshot_seasons())


def cmd_columns(args) -> None:
    hits = Q.find_columns(args.pattern, sheets=args.sheet or None,
                          search_notes=not args.names_only)
    if not hits:
        print(f"no column matches {args.pattern!r}")
        return
    for hit in hits:
        line = f"{hit.sheet:<18} {hit.column}"
        if hit.notes and not args.names_only:
            line += f"\n{'':<19}note: {hit.notes}"
        print(line)
    print(f"\n{len(hits)} match(es)")


def cmd_describe(args) -> None:
    info = Q.describe_column(args.sheet, args.column)
    width = max(len(k) for k in info)
    for key, val in info.items():
        print(f"{key:<{width}} : {val}")


def cmd_rows(args) -> None:
    df = _select(Q.rows(args.sheet, *args.where), args.select)
    _emit(df, args.csv, args.limit)


def cmd_top(args) -> None:
    df = Q.top(args.sheet, args.column, *args.where, n=args.limit or 10,
               ascending=args.asc,
               columns=[c.strip() for c in args.select.split(",")] if args.select else None)
    _emit(df, args.csv)


def _emit_hits(hits, as_csv: bool, title: str) -> None:
    if as_csv:
        print("label,column,value,rank,end,out_of,volatile")
        for h in hits:
            print(f"\"{h.label}\",\"{h.column}\",{h.value},{h.rank},{h.end},{h.out_of},{h.volatile}")
        return
    print(title)
    if not hits:
        print("  (nothing within the window)")
        return
    for h in hits:
        print(f"  {h.describe()}")
    flagged = sum(1 for h in hits if h.volatile)
    print(f"\n{len(hits)} item(s)"
          + (f"; {flagged} on build-volatile columns — classify, don't drop" if flagged else ""))


def cmd_sweep(args) -> None:
    hits = Q.sweep(args.sheet, *args.where, window=args.window, within=args.within,
                   include_volatile=not args.no_volatile)
    _emit_hits(hits, args.csv,
               f"every {args.sheet} column where this lands in the top/bottom {args.window}:")


def cmd_extremes(args) -> None:
    hits = Q.extremes(args.sheet, *args.within, n=args.top,
                      include_volatile=not args.no_volatile)
    _emit_hits(hits, args.csv, f"both ends of every rankable {args.sheet} column:")


def cmd_group(args) -> None:
    from lotg_support import analysis as A

    df = A.position_group(args.position, season=args.season, team=args.team,
                          min_share=args.min_share)
    cols = ["Team", "Year", "players", "starter_weeks", "points", "ppg", "contributors",
            "effective_players", "top1_share", "top3_share", "best_player", "share_of_team"]
    _emit(df[[c for c in cols if c in df.columns]], args.csv, args.limit)
    if not args.csv and not df.empty:
        print("effective_players = 1/Σ(share²): 1.0 means one player did everything.")


def cmd_stacks(args) -> None:
    from lotg_support import analysis as A

    df = A.lineup_stacks(season=args.season)
    if args.compare:
        print(A.compare(df, args.condition, args.compare, by="Year",
                        permutations=args.permutations).describe())
        return
    _emit(df, args.csv, args.limit or 20)


def cmd_compare(args) -> None:
    from lotg_support import analysis as A

    frame = A.lineup_stacks(season=args.season) if args.sheet == "stacks" \
        else Q.rows(args.sheet, *args.where)
    print(A.compare(frame, args.condition, args.metric, by=args.by,
                    permutations=args.permutations).describe())


_SWEEP_CAVEAT = (
    "\nRead `q` (Benjamini-Hochberg false-discovery rate) before believing a row: "
    "with {tests} tests,\nabout {expected:.1f} would clear p<0.05 by chance alone. "
    "Columns that are definitionally part of\nthe condition or target will top the "
    "list — recognise those, don't report them as findings."
)


def _frame_for(args):
    from lotg_support import analysis as A

    if args.sheet == "stacks":
        return A.lineup_stacks(season=getattr(args, "season", None))
    if args.sheet == "group":
        return A.position_group(getattr(args, "position", "WR"),
                                season=getattr(args, "season", None))
    return Q.rows(args.sheet, *getattr(args, "where", []))


def cmd_compare_all(args) -> None:
    from lotg_support import analysis as A

    df = A.compare_all(_frame_for(args), args.condition, permutations=args.permutations,
                       min_n=args.min_n)
    _emit(df, args.csv, args.limit)
    if not args.csv and not df.empty:
        print(_SWEEP_CAVEAT.format(tests=int(df["tests"].iloc[0]),
                                   expected=int(df["tests"].iloc[0]) * 0.05))


def cmd_correlate(args) -> None:
    from lotg_support import analysis as A

    df = A.correlate_all(_frame_for(args), args.target, method=args.method,
                         min_n=args.min_n)
    _emit(df, args.csv, args.limit)
    if not args.csv and not df.empty:
        print(_SWEEP_CAVEAT.format(tests=int(df["tests"].iloc[0]),
                                   expected=int(df["tests"].iloc[0]) * 0.05))
        print("Correlation is not causation, and these columns are not independent "
              "of each other.")


def cmd_stretch(args) -> None:
    from lotg_support import analysis as A

    frame = _frame_for(args)
    order = [c for c in args.order.split(",") if c.strip()]
    df = A.best_stretch(frame, args.metric, args.length,
                        entity_columns=[c for c in args.entity.split(",") if c.strip()],
                        order_columns=order, n=args.limit or 10)
    _emit(df, args.csv)
    if not args.csv and not df.empty:
        print("Contiguity is by row order within the entity — check `span` for a run "
              "that jumped a gap.")


def cmd_timeline(args) -> None:
    from lotg_support import analysis as A

    df = A.timeline(player=args.player, team=args.team, season=args.season)
    _emit(df.drop(columns=["undated"], errors="ignore"), args.csv, args.limit)


def cmd_scarcity(args) -> None:
    from lotg_support import analysis as A

    seasons = [args.season] if args.season else Q.export_seasons()
    for year in seasons:
        rows = A.scarcity(year, demand_multiple=args.demand_multiple)
        if not rows:
            continue
        print(f"\n{year}  (replacement rank = starters actually fielded per week"
              f"{f' x {args.demand_multiple}' if args.demand_multiple != 1.0 else ''})")
        for s in rows:
            print(f"  {s.describe()}")


def cmd_spend(args) -> None:
    from lotg_support import analysis as A

    df = A.spend_by_position(team=args.team, season=args.season)
    _emit(df, args.csv, args.limit)
    if not args.csv:
        print("\nTrades are NOT priced here (trades.csv stores assets as text) — "
              "say so in any write-up that uses this table.")


def cmd_player(args) -> None:
    dossier = Q.player_dossier(args.name)
    print(f"=== {dossier['player']} ===")
    for section in ("all_time", "by_year", "drafted", "added", "dropped"):
        df = dossier[section]
        if df.empty:
            continue
        print(f"\n--- {section} ---")
        cols = {
            "by_year": ["Player", "Year", "Top Team", "Points", "Avg points"],
            "added": ["Team", "Player Added", "type of transaction (waiver/free agency)", "Date", "Faab"],
            "dropped": ["Team", "Player Dropped", "Date", "Season"],
            "drafted": ["Year", "Number", "Player Picked", "Team"],
        }.get(section)
        _emit(_select(df, ",".join(c for c in (cols or []) if c in df.columns)) if cols else df,
              args.csv, 0 if section != "all_time" else 1)
    weeks = dossier["by_week"]
    if not weeks.empty and "Points" in weeks.columns:
        best = Q.numeric(weeks, "Points").idxmax()
        row = weeks.loc[best]
        print(f"\nbest week: {row['Points']} in {row['Year']} {row['Week Name']} "
              f"({row['Team']}, {row['Starter/Bench']})")
    try:
        deals = Q.trades(player=args.name)
    except (KeyError, FileNotFoundError) as exc:
        deals = []
        print(f"\n(trade lookup skipped: {exc})")
    if deals:
        print("\n--- trades ---")
        for trade in deals:
            print(f"  {trade.season}  {trade.describe()}")


def cmd_team(args) -> None:
    dossier = Q.team_dossier(Q.canonical_team(args.name))
    print(f"=== {dossier['team']} ===")
    for section in ("all_time", "by_year"):
        df = dossier[section]
        if df.empty:
            continue
        print(f"\n--- {section} ---")
        cols = ["Team", "Year", "Result", "Record", "Win %", "Differential"] if section == "by_year" else None
        _emit(_select(df, ",".join(c for c in (cols or []) if c in df.columns)) if cols else df,
              args.csv)


def cmd_season(args) -> None:
    dossier = Q.season_dossier(args.year)
    meta = dossier["meta"]
    print(f"=== {args.year} ===")
    print(f"playoffs start week {meta.playoff_week_start} "
          f"({meta.regular_season_weeks}-week regular season, {meta.playoff_teams} teams), "
          f"lineup: {[ '/'.join(s) for s in meta.starting_slots ]}")
    print(f"snapshot available (replayable): {meta.has_snapshot}")
    for section in ("teams", "bracket"):
        df = dossier[section]
        if df.empty:
            continue
        print(f"\n--- {section} ---")
        cols = {
            "teams": ["Team", "Year", "Result", "Record", "Win %"],
            "bracket": ["Week Name", "Team", "PF", "Opponent", "Points against", "Win?"],
        }[section]
        _emit(_select(df, ",".join(c for c in cols if c in df.columns)), args.csv)


def cmd_trades(args) -> None:
    deals = Q.trades(season=args.season, player=args.player, date=args.date)
    for trade in deals:
        print(f"{trade.season}  {trade.describe()}")
        print(f"{'':<6}id={trade.transaction_id}")
    print(f"\n{len(deals)} trade(s)")


def cmd_roster(args) -> None:
    year, wk = args.year, args.week
    table, pl = Q.teams(year), Q.players()
    slots = Q.season_meta(year).starting_slots
    for rid, row in sorted(Q.week(year, wk).items()):
        if args.team and Q.canonical_team(args.team).lower() != table.get(rid, "").lower():
            continue
        print(f"\n{table.get(rid, rid)} — {row.points:.2f} (raw Sleeper points)")
        for idx, pid in enumerate(row.starters):
            slot = "/".join(slots[idx]) if idx < len(slots) else "?"
            label = "(empty)" if pid == Q.EMPTY_SLOT else f"{pl.name(pid)} [{pl.position(pid)}]"
            print(f"  {slot:<12} {label:<28} {row.players_points.get(pid, 0.0):>7.2f}")
        if args.bench:
            print("  bench:")
            for pid in row.bench:
                print(f"  {'':<12} {pl.name(pid):<28} {row.players_points.get(pid, 0.0):>7.2f}")


def cmd_validate(args) -> None:
    from lotg_support import replay as R  # imported lazily: only this command needs it

    seasons = ([args.season] if args.season
               else [s for s in Q.completed_seasons() if Q.played_weeks(s)])
    failed = False
    for year in seasons:
        problems = R.validate(year)
        print(f"{year}: {'OK' if not problems else f'{len(problems)} PROBLEM(S)'}")
        for line in problems[:20]:
            print(f"   {line}")
        failed |= bool(problems)
    raise SystemExit(1 if failed else 0)


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def table_args(p):
        p.add_argument("--where", action="append", default=[],
                       metavar="EXPR", help="filter, e.g. Year=2025 or 'Points>200' "
                                            "or 'Player~mahomes' (regex). Repeatable.")
        p.add_argument("--select", default="", help="comma-separated columns to show")
        p.add_argument("-n", "--limit", type=int, default=0, help="max rows")
        p.add_argument("--csv", action="store_true", help="CSV instead of a grid")

    p = sub.add_parser("sheets", help="list the export sheets and their shape")
    p.set_defaults(func=cmd_sheets)

    p = sub.add_parser("columns", help="find which sheet/column holds a concept")
    p.add_argument("pattern", help="case-insensitive regex")
    p.add_argument("--sheet", action="append", default=[], help="restrict to a sheet (repeatable)")
    p.add_argument("--names-only", action="store_true", help="match column names, not notes")
    p.set_defaults(func=cmd_columns)

    p = sub.add_parser("describe", help="shape, range and formula of one column")
    p.add_argument("sheet")
    p.add_argument("column")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("rows", help="filtered rows of a sheet")
    p.add_argument("sheet")
    table_args(p)
    p.set_defaults(func=cmd_rows)

    p = sub.add_parser("top", help="leaderboard for one column")
    p.add_argument("sheet")
    p.add_argument("column")
    p.add_argument("--asc", action="store_true", help="smallest first")
    table_args(p)
    p.set_defaults(func=cmd_top)

    p = sub.add_parser("sweep", help="rank a row on EVERY column of a sheet, not a curated few")
    p.add_argument("sheet")
    p.add_argument("--where", action="append", default=[], metavar="EXPR",
                   help="picks the row(s) being asked about (repeatable)")
    p.add_argument("--within", action="append", default=[], metavar="EXPR",
                   help="narrows the board it is ranked against, e.g. Year=2025")
    p.add_argument("--window", type=int, default=5, help="report top/bottom N (default 5)")
    p.add_argument("--no-volatile", action="store_true",
                   help="drop build-volatile columns (default: keep and flag them)")
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("extremes", help="both ends of every rankable column of a sheet")
    p.add_argument("sheet")
    p.add_argument("--within", action="append", default=[], metavar="EXPR",
                   help="restrict the board, e.g. Year=2025")
    p.add_argument("--top", type=int, default=1, help="how many from each end (default 1)")
    p.add_argument("--no-volatile", action="store_true")
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_extremes)

    p = sub.add_parser("group", help="a position group per team-season, with depth measures")
    p.add_argument("position", nargs="?", default="WR", choices=list(_POSITIONS))
    p.add_argument("--season", type=int)
    p.add_argument("--team")
    p.add_argument("--min-share", type=float, default=0.05,
                   help="share of group points that counts as a contributor (default 0.05)")
    p.add_argument("-n", "--limit", type=int, default=0)
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_group)

    p = sub.add_parser("stacks", help="lineup composition by NFL team, with PF / Max PF joined")
    p.add_argument("--season", type=int)
    p.add_argument("--compare", metavar="METRIC",
                   help="compare this metric across the condition instead of listing rows")
    p.add_argument("--condition", default="stack_WR>=2",
                   help="cohort split for --compare (default stack_WR>=2)")
    p.add_argument("--permutations", type=int, default=2000)
    p.add_argument("-n", "--limit", type=int, default=0)
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_stacks)

    p = sub.add_parser("compare", help="split any sheet on a condition and compare a metric")
    p.add_argument("sheet", help="an export sheet, or 'stacks' for the lineup-composition frame")
    p.add_argument("condition", help="e.g. 'stack_WR>=2' or 'Rookie?=true'")
    p.add_argument("metric", help="numeric column to compare")
    p.add_argument("--where", action="append", default=[], metavar="EXPR")
    p.add_argument("--season", type=int, help="only with sheet=stacks")
    p.add_argument("--by", default="Year", help="breakdown column (default Year; '' to skip)")
    p.add_argument("--permutations", type=int, default=2000)
    p.set_defaults(func=cmd_compare)

    def frame_args(p):
        p.add_argument("sheet", help="an export sheet, 'stacks' (lineup composition) "
                                     "or 'group' (a position group per team-season)")
        p.add_argument("--where", action="append", default=[], metavar="EXPR")
        p.add_argument("--season", type=int, help="for sheet=stacks/group")
        p.add_argument("--position", default="WR", help="for sheet=group")
        p.add_argument("-n", "--limit", type=int, default=0)
        p.add_argument("--csv", action="store_true")

    p = sub.add_parser("compare-all",
                       help="cohort test on EVERY numeric column, with FDR control")
    frame_args(p)
    p.add_argument("--condition", required=True, help="e.g. 'stack_WR>=2'")
    p.add_argument("--permutations", type=int, default=500)
    p.add_argument("--min-n", type=int, default=5, help="skip columns with a tiny cohort")
    p.set_defaults(func=cmd_compare_all)

    p = sub.add_parser("correlate",
                       help="correlate EVERY numeric column against one target, with FDR control")
    frame_args(p)
    p.add_argument("--target", required=True, help="the column everything is correlated against")
    p.add_argument("--method", default="pearson", choices=["pearson", "spearman", "kendall"])
    p.add_argument("--min-n", type=int, default=10)
    p.set_defaults(func=cmd_correlate)

    p = sub.add_parser("stretch", help="best contiguous run of N rows per entity")
    frame_args(p)
    p.add_argument("--metric", required=True, help="column to total over the window")
    p.add_argument("--length", type=int, default=3, help="rows per window (default 3)")
    p.add_argument("--entity", default="Team", help="comma-separated entity key (default Team)")
    p.add_argument("--order", default="Year,Week",
                   help="comma-separated ordering columns; absent ones are ignored")
    p.set_defaults(func=cmd_stretch)

    p = sub.add_parser("timeline", help="every recorded event for a player or team, in order")
    p.add_argument("--player")
    p.add_argument("--team")
    p.add_argument("--season", type=int)
    p.add_argument("-n", "--limit", type=int, default=0)
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_timeline)

    p = sub.add_parser("scarcity", help="surplus of the best player over replacement, by position")
    p.add_argument("--season", type=int)
    p.add_argument("--demand-multiple", type=float, default=1.0,
                   help="scale replacement rank (1.0 = exactly what the league starts)")
    p.set_defaults(func=cmd_scarcity)

    p = sub.add_parser("spend", help="draft capital + FAAB per position, against points returned")
    p.add_argument("--team")
    p.add_argument("--season", type=int)
    p.add_argument("-n", "--limit", type=int, default=0)
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_spend)

    p = sub.add_parser("player", help="everything the exports know about a player")
    p.add_argument("name")
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_player)

    p = sub.add_parser("team", help="everything the exports know about a team")
    p.add_argument("name")
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_team)

    p = sub.add_parser("season", help="one season: shape, standings, bracket")
    p.add_argument("year", type=int)
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_season)

    p = sub.add_parser("trades", help="completed trades, both sides resolved to names")
    p.add_argument("--season", type=int)
    p.add_argument("--player")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.set_defaults(func=cmd_trades)

    p = sub.add_parser("roster", help="a week's lineup from the snapshot, slot by slot")
    p.add_argument("year", type=int)
    p.add_argument("week", type=int)
    p.add_argument("--team")
    p.add_argument("--bench", action="store_true")
    p.set_defaults(func=cmd_roster)

    p = sub.add_parser("validate", help="run the replay guards against the committed data")
    p.add_argument("--season", type=int)
    p.set_defaults(func=cmd_validate)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (KeyError, LookupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # `... | head` closed the pipe. Not an error; keep the shell quiet.
        try:
            sys.stdout.close()
        finally:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
