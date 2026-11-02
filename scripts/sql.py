"""Any question as ONE SQL call over the typed exports + raw snapshot. Read-only.

A thin command line over `lotg_support.db` (DuckDB). The database is built on
demand from the committed CSVs into `.cache/lotg.duckdb` (a few seconds, only
when an input changed) — nothing to set up beyond `pip install duckdb`.

    python scripts/sql.py "SELECT Team, Year, Week, PF FROM team_week ORDER BY PF DESC LIMIT 5"
    python scripts/sql.py "SELECT Team, count(*) FROM starters WHERE Points > 40 GROUP BY Team ORDER BY 2 DESC"
    python scripts/sql.py "SELECT * FROM catalog_columns WHERE \"column\" ILIKE '%margin entering%'"
    python scripts/sql.py --live "SELECT Team, Player, Points FROM lpw WHERE Live ORDER BY Points DESC LIMIT 10"
    python scripts/sql.py "SELECT ..." :: "SELECT ..."      # several statements, one process
    python scripts/sql.py --tables                         # every table / view, rows, key, caveats
    python scripts/sql.py --describe team_week             # one table's columns and types
    python scripts/sql.py --rebuild                        # force a rebuild (prints size and time)
    python scripts/sql.py --parquet /tmp/lotg_parquet      # every table as Parquet + schema.sql

Tables: the export sheets by name (player_week, team_week, ...; aliases tw, ty,
py, pa, lw, ly, twt, ...), `pw` and `ts` exactly as `fast.py q` has them,
`starters` / `bench` / `pw_full` / `player_positions` / `tw_regular`, and the
raw Sleeper snapshot (`sleeper_matchups`, `sleeper_lineups`,
`sleeper_transactions`, `sleeper_moves` — failed waiver bids included —,
`sleeper_trade_picks`, `sleeper_players`, `sleeper_leagues`, `sleeper_scoring`),
`id_bridge`, `nfl_schedule`. Quote column names with spaces or `?`:
"Win?", "Starter/Bench", "Margin entering Monday".

Every result is followed by `# ` caveat lines for the tables it touched
(semifinal +5 in PF, strict > vs >=, lineup size by season, the as-of week ...).
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import db  # noqa: E402

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 140)


def _live(args):
    from lotg_support import live
    if args.snapshot:
        if not (args.season and args.week):
            sys.exit("--snapshot needs --season and --week")
        return live.fetch(args.season, args.week, source="snapshot")
    return live.fetch(args.season, args.week)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="*", help="statements; separate several with ::")
    ap.add_argument("--tables", action="store_true", help="list every table and view")
    ap.add_argument("--describe", metavar="TABLE", help="one table's columns and types")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the database first")
    ap.add_argument("--db", help="database path (default .cache/lotg.duckdb or $LOTG_DB)")
    ap.add_argument("--parquet", metavar="DIR", help="export every table as Parquet into DIR")
    ap.add_argument("-n", type=int, default=200, help="rows to print (0 = all)")
    ap.add_argument("--format", choices=("table", "csv", "json"), default="table")
    ap.add_argument("--no-caveats", action="store_true")
    ap.add_argument("--live", action="store_true", help="add lpw / live_pw / live_tw (fetches Sleeper)")
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--snapshot", action="store_true", help="live week from the committed snapshot")
    args = ap.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    con = db.connect(args.db, rebuild="always" if args.rebuild else "auto",
                     live=_live(args) if args.live else None)
    try:
        if args.parquet:
            print(f"# wrote {db.export_parquet(args.parquet, con)}")
        if args.tables:
            db.print_result(db.describe(con), max_rows=0)
        if args.describe:
            db.print_result(db.describe(con, args.describe), max_rows=0)
        parts, cur = [], []
        for tok in args.sql:
            if tok == "::":
                parts.append(" ".join(cur))
                cur = []
            else:
                cur.append(tok)
        parts.append(" ".join(cur))
        parts = [p for p in parts if p.strip()]
        for i, sql in enumerate(parts):
            if len(parts) > 1:
                print(f"{'' if i == 0 else chr(10)}===== sql {sql}")
            db.run(sql, con, max_rows=args.n, fmt=args.format, notes=not args.no_caveats)
    finally:
        con.close()


if __name__ == "__main__":
    main()
