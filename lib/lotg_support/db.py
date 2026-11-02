"""A typed DuckDB database over the committed exports and the raw snapshot, so
any question is one SQL call. `scripts/sql.py` and `fast.py sql` are the
command lines over it. Read-only with respect to the repo: it never writes
`exports/`, `data/` or anything tracked.

    from lotg_support import db
    db.query('SELECT Team, max(PF) FROM team_week GROUP BY Team')     # a DataFrame
    con = db.connect()                                                # duckdb connection

Built on demand from the committed CSVs into `.cache/lotg.duckdb` (gitignored;
`$LOTG_DB` moves it) in a few seconds, and rebuilt automatically whenever an
input changes (`fingerprint`: size + mtime of every input file and of the code
that types them). Nothing binary is committed; CI publishes a copy in the run
artifact.

Typing is `fast.typed_sheet`'s — the same rules `twt` / `tyt` / ... use, so a
SQL answer and a `q` answer agree — plus three things SQL needs:

- Yes/No and True/False columns are BOOLEAN with NULL for blanks;
- ISO timestamp columns are TIMESTAMP, ISO date-only columns DATE;
- blank text cells are NULL (`IS NULL`, not `= ''`); `N/A` stays text in a
  text column and is NULL in a numeric one, exactly as in `twt`.

Numbers are DuckDB's parse of the CSV text, which is exact (= Python's
`float(text)`); `pd.to_numeric`, behind `typed_sheet`, can land one ulp away
(25.0325 for "25.032500000000002"), so a SQL value and a `twt` value may
differ in the 16th digit. `pw` is fast.py's own frame, bit for bit.

`Year` and `Week` are INTEGER. Text columns that are numbers with a sentinel
("In Progress" in the streak columns, "2027 1.??" picks) stay VARCHAR:
`TRY_CAST(col AS DOUBLE)` gives the numbers.

Tables (every one has `_row`, the 1-based row of its source, unique):

- the fourteen export sheets by name (`player_week`, `team_week`, ...) plus
  `picks` (both pick sheets, `inquiry.load_sheet('picks')`); new columns the
  build adds are picked up by the next rebuild, nothing lists them here;
- `pw` = `fast.player_weeks()`: one row per player-week, typed, the team's
  result joined and the acquisition columns (`Acquired via`, `Season source`,
  `In-season pickup`, ...) — identical to the `pw` of `fast.py q`;
- `ts` = `fast.team_seasons()` recomputed in SQL: typed team_year plus
  `Regular season all-play win %` (keys Team, Year);
- `sleeper_*`: the raw Sleeper snapshot keyed by `Player ID` (2021 on; 2020 is
  ESPN, no snapshot): `sleeper_matchups` (team-week raw points, opponent),
  `sleeper_lineups` (every player in every matchup: points, starter, slot),
  `sleeper_transactions` / `sleeper_moves` (every add, drop and trade leg,
  FAILED waiver claims and their bids included) / `sleeper_trade_picks`,
  `sleeper_players` (the current player dictionary, every scalar field),
  `sleeper_leagues` (one row per season's settings), `sleeper_scoring`;
- `id_bridge` (DynastyProcess ids: sleeper_id <-> gsis_id ...) and
  `nfl_schedule` (nflverse games, struck game restored) when on disk.

Views: `tw`, `ty`, `ta`, `py`, `pa`, `lw`, `ly`, `la` and the typed aliases
`twt`, `tyt`, `pyt`, `lwt`, `lyt` (the same sheets — every table here is typed),
`starters` / `bench` (pw by role), `pw_full` (every player_week column + the
team result), `player_positions` (Player, Year -> Position, the build's own
per-season position, `analysis.positions_by_season`), `tw_regular` (regular
season team-weeks), `catalog_columns` (every column and its type; the SQL
`cols`), `caveats`. With `live=` (CLI `--live`) the connection also has
`lpw` (pw + the live week, `fast.player_weeks(live)`), `live_pw`, `live_tw`.

Caveats live in the database (`caveats`, and COMMENT ON every table) and
`footer(sql)` prints the ones a query touches — the same ones `fast.py`
prints: PF's semifinal +5, strict `>` vs `>=`, lineup size by season, every
week type counted, bench = every non-starter, the as-of week, live = raw
Sleeper / leading now, FAAB on a 100 scale.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from lotg_support import inquiry as Q

SCHEMA_VERSION = 1
DB_NAME = "lotg.duckdb"

# Natural keys, checked unique at build time and indexed (a key that is not
# unique on the data is reported, not enforced). The first candidate whose
# columns all exist wins, so `Player ID` becomes the key the day the build
# adds it.
KEYS: Dict[str, Sequence[Sequence[str]]] = {
    "player_week": (("Player ID", "Team", "Year", "Week"), ("Player", "Team", "Year", "Week")),
    "player_year": (("Player ID", "Year"), ("Player", "Year")),
    "player_all_time": (("Player ID",), ("Player",)),
    "team_week": (("Team", "Year", "Week"),),
    "team_year": (("Team", "Year"),),
    "team_all_time": (("Team",),),
    "league_week": (("Year", "Week"),),
    "league_year": (("Year",),),
    "trades": (("Date", "Team"),),
    "non_rookie_picks": (("Year", "Number"),),
    "formulas": (("Sheet", "Stat"),),
    "pw": (("Player ID", "Team", "Year", "Week"), ("Player", "Team", "Year", "Week")),
    "ts": (("Team", "Year"),),
    "sleeper_matchups": (("Year", "Week", "roster_id"),),
    "sleeper_transactions": (("transaction_id",),),
    "sleeper_players": (("Player ID",),),
    "sleeper_leagues": (("Year",),),
}

ALIASES = {"tw": "team_week", "ty": "team_year", "ta": "team_all_time", "py": "player_year",
           "pa": "player_all_time", "lw": "league_week", "ly": "league_year", "la": "league_all_time",
           "twt": "team_week", "tyt": "team_year", "pyt": "player_year", "lwt": "league_week",
           "lyt": "league_year"}

_BLANKS = ("", "nan", "None", "N/A", "NA", "-")


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:      # optional dependency: the fast path never needs it
        raise SystemExit("the SQL layer needs duckdb: pip install duckdb==1.4.5") from exc
    return duckdb


# ---------------------------------------------------------------------------
# Where the database lives and when it is stale
# ---------------------------------------------------------------------------
def default_path() -> Path:
    env = os.environ.get("LOTG_DB")
    return Path(env).resolve() if env else Q.repo_root() / ".cache" / DB_NAME


def _inputs() -> List[Path]:
    root = Q.repo_root()
    ex = root / "exports"
    files = sorted(ex.glob("*.csv"))
    files += [ex / "raw" / "pick_ref_index.csv", root / ".cache" / "nfldata_games.csv"]
    snap = ex / "snapshot"
    if snap.exists():
        files += sorted(p for p in snap.rglob("*") if p.is_file() and p.suffix in (".json", ".csv"))
    lib = Path(__file__).resolve().parent
    files += [lib / "db.py", lib / "fast.py", lib / "inquiry.py"]
    return [f for f in files if f.exists()]


def fingerprint() -> str:
    """What the database was built from: size + mtime of every input (the CSVs,
    the snapshot, the schedule, and the code that types them). A checkout or a
    new build changes it, and the next `connect()` rebuilds."""
    h = hashlib.sha1(f"v{SCHEMA_VERSION}".encode())
    root = Q.repo_root()
    for f in _inputs():
        st = f.stat()
        h.update(f"{os.path.relpath(f, root)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def _stored_fingerprint(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        con = _duckdb().connect(str(path), read_only=True)
        try:
            row = con.execute("SELECT value FROM _meta WHERE key = 'fingerprint'").fetchone()
        finally:
            con.close()
        return row[0] if row else None
    except Exception:       # noqa: BLE001 - a half-written or old file is just stale
        return None


def is_fresh(path: Optional[os.PathLike] = None) -> bool:
    p = Path(path) if path else default_path()
    return _stored_fingerprint(p) == fingerprint()


# ---------------------------------------------------------------------------
# Frames -> typed tables
# ---------------------------------------------------------------------------
def _is_text(col: pd.Series) -> bool:
    return col.dtype == object or pd.api.types.is_string_dtype(col)


def normalize(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str], List[str]]:
    """Prepare an already-typed frame (pw, ts, the snapshot) for DuckDB:
    bool-ish object columns -> nullable boolean, a text column holding a
    stray number -> all text. Returns the frame, {column: SQL cast} (Year /
    Week -> INTEGER) and the text columns, which `_typed_exprs` scans for ISO
    dates and blanks in SQL."""
    out = df.copy()
    casts: Dict[str, str] = {}
    text: List[str] = []
    for c in out.columns:
        col = out[c]
        if c in ("Year", "Week") and pd.api.types.is_numeric_dtype(col):
            casts[c] = "INTEGER"
            continue
        if col.dtype == bool or not _is_text(col):
            continue
        kind = pd.api.types.infer_dtype(col, skipna=True)
        if kind == "boolean":
            out[c] = col.astype("boolean")
        elif kind in ("string", "empty"):
            text.append(c)
        elif kind in ("integer", "floating", "mixed-integer-float"):     # numbers with None
            out[c] = pd.to_numeric(col)
        elif kind in ("mixed", "mixed-integer"):                        # a stray number in text: all text
            out[c] = col.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
            text.append(c)
    return out, casts, text


def _typed_exprs(con, src: str, columns: Sequence[str], numbers: bool = True) -> Dict[str, str]:
    """{column: SQL expression} typing text columns of a registered frame, by
    `fast.typed_sheet`'s rules (blank = '', nan, None, N/A, NA, - after
    stripping; all non-blank numeric -> DOUBLE, Year/Week INTEGER; all
    true/false/yes/no -> BOOLEAN) plus ISO dates -> DATE / TIMESTAMP and
    blank text -> NULL. `numbers=False` (an already-typed frame, whose text
    columns are ids and names): dates and blanks only. Two aggregate passes
    decide every column's type; tests/test_db.py checks it against typed_sheet."""
    blanks = ", ".join(_ql(b) for b in _BLANKS)

    # A long scan (column, value) and a GROUP BY — hundreds of FILTER
    # aggregates in one SELECT make DuckDB's planner superlinear — in two
    # passes, so the date regexes only see the columns that are neither
    # numbers nor booleans.
    def scan(cols, aggs):
        on = ", ".join(f"CAST({_qi(c)} AS VARCHAR) AS {_qi(c)}" for c in cols)
        return con.execute(f"""
            SELECT col, {aggs}
            FROM (SELECT col, trim(v) AS v FROM (UNPIVOT (SELECT {on} FROM {src}) ON COLUMNS(*) INTO NAME col VALUE v))
            WHERE v NOT IN ({blanks})
            GROUP BY col""").fetchall()

    if not columns:
        return {}
    if numbers:
        first = {r[0]: r[1:] for r in scan(columns, """count(*),
            count(*) FILTER (TRY_CAST(v AS DOUBLE) IS NULL),
            count(*) FILTER (lower(v) NOT IN ('true', 'false', 'yes', 'no'))""")}
    else:
        first = {r[0]: (r[1], 1, 1) for r in scan(columns, "count(*)")}
    rest = [c for c, (p, n, b) in first.items() if n and b]
    second = {r[0]: r[1:] for r in scan(rest, """
        count(*) FILTER (NOT regexp_full_match(v, '\\d{4}-\\d{2}-\\d{2}')),
        count(*) FILTER (NOT regexp_full_match(v,
            '\\d{4}-\\d{2}-\\d{2}([ T]\\d{2}:\\d{2}(:\\d{2}(\\.\\d+)?)?)?'))""")} if rest else {}
    out = {}
    for c in columns:
        p, n, b = first.get(c, (0, 0, 0))
        d, t = second.get(c, (1, 1))
        raw = f"CAST({_qi(c)} AS VARCHAR)"     # an all-None column arrives as Arrow null
        v = f"trim({raw})"
        # every non-blank value is known to cast (the stats above), so TRY_CAST
        # only has the blanks left to turn into NULL — except 'nan', which
        # DOUBLE reads as NaN and typed_sheet reads as blank
        if p and not n:
            typ = "INTEGER" if c in ("Year", "Week") else "DOUBLE"
            expr = f"CASE WHEN lower({v}) = 'nan' THEN NULL ELSE TRY_CAST({v} AS {typ}) END"
        elif p and not b:
            expr = (f"CASE lower({v}) WHEN 'true' THEN true WHEN 'yes' THEN true "
                    "WHEN 'false' THEN false WHEN 'no' THEN false END")
        elif p and not d:
            expr = f"TRY_CAST({v} AS DATE)"
        elif p and not t:
            expr = f"TRY_CAST({v} AS TIMESTAMP)"
        else:
            expr = f"NULLIF({raw}, '')"
        out[c] = expr
    return out


_CHUNK = 25


def _create_typed(con, name: str, exprs: Sequence[str], src: str = "_frame") -> None:
    """CREATE TABLE name AS SELECT exprs..., _row FROM src. Planned in chunks
    of _CHUNK columns joined back by position: one SELECT with a few hundred
    CASE expressions makes DuckDB's optimizer superlinear (100 columns took
    3 s, team_year's 196 ran out of memory)."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE _raw AS SELECT * FROM {src} ORDER BY _row")
    parts = []
    for i in range(0, len(exprs), _CHUNK):
        con.execute(f"CREATE OR REPLACE TEMP TABLE _c{i} AS SELECT {', '.join(exprs[i:i + _CHUNK])} "
                    "FROM _raw ORDER BY _row")
        parts.append(f"_c{i}")
    con.execute("CREATE OR REPLACE TEMP TABLE _crow AS SELECT _row FROM _raw ORDER BY _row")
    body = " POSITIONAL JOIN ".join(parts + ["_crow"])
    con.execute(f"CREATE TABLE {_qi(name)} AS SELECT * FROM {body}")
    for t in parts + ["_crow", "_raw"]:
        con.execute(f"DROP TABLE {t}")


def _dedupe_columns(df: pd.DataFrame, notes: List[str], table: str) -> pd.DataFrame:
    """DuckDB identifiers are case-insensitive: 'PF' and 'pf' cannot both be
    columns. Suffix the later one and say so (no sheet has a clash today)."""
    seen: Dict[str, int] = {}
    cols = []
    for c in df.columns:
        k = str(c).lower()
        if k in seen:
            seen[k] += 1
            new = f"{c} ({seen[k]})"
            notes.append(f"{table}: column {c!r} clashes case-insensitively; stored as {new!r}")
            cols.append(new)
        else:
            seen[k] = 1
            cols.append(c)
    df = df.copy()
    df.columns = cols
    return df


def _arrow(df: pd.DataFrame):
    """Register frames as Arrow: DuckDB scans pandas object columns one Python
    object at a time (seconds for team_week), Arrow in milliseconds."""
    import pyarrow as pa
    return pa.Table.from_pandas(df, preserve_index=False)


def _qi(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _ql(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _store(con, name: str, df: pd.DataFrame, notes: List[str], source: str, text: bool = False) -> None:
    """One frame -> one table. `text=True`: an all-text export sheet, every
    column typed by `_typed_exprs`; otherwise an already-typed frame
    (`normalize`), whose text columns only get dates and NULLs."""
    df = _dedupe_columns(df.reset_index(drop=True), notes, name)
    cols = list(df.columns)
    if text:
        casts, txt = {}, cols
    else:
        df, casts, txt = normalize(df)
    df["_row"] = np.arange(1, len(df) + 1, dtype="int64")
    con.register("_frame", _arrow(df))
    try:
        typed = _typed_exprs(con, "_frame", txt, numbers=text)
        exprs = [f"{typed[c]} AS {_qi(c)}" if c in typed else
                 f"CAST({_qi(c)} AS {casts[c]}) AS {_qi(c)}" if c in casts else _qi(c) for c in cols]
        _create_typed(con, name, exprs)
    finally:
        con.unregister("_frame")
    key = ""
    for cand in KEYS.get(name, ()):
        if all(c in df.columns for c in cand):
            cols = ", ".join(_qi(c) for c in cand)
            dup = con.execute(f"SELECT count(*) FROM (SELECT {cols} FROM {_qi(name)} GROUP BY ALL HAVING count(*) > 1)").fetchone()[0]
            if dup:
                notes.append(f"{name}: key ({', '.join(cand)}) is not unique ({dup} duplicated) — not enforced; use _row")
            else:
                con.execute(f"CREATE UNIQUE INDEX {_qi('ux_' + name)} ON {_qi(name)} ({cols})")
                key = ", ".join(cand)
            break
    _TABLES.append({"table": name, "kind": source, "rows": len(df), "key": key or "_row"})


_TABLES: List[dict] = []


# ---------------------------------------------------------------------------
# The raw snapshot as tables
# ---------------------------------------------------------------------------
def _snap_json(rel: str):
    p = Q.snapshot_dir() / rel
    return json.loads(p.read_text()) if p.exists() else None


def _et(ms) -> Optional[pd.Timestamp]:
    if ms is None:
        return None
    return (pd.Timestamp(int(ms), unit="ms", tz="UTC").tz_convert("America/New_York").tz_localize(None))


def snapshot_frames() -> Dict[str, pd.DataFrame]:
    """The parts of `exports/snapshot` worth querying, keyed by Sleeper ids."""
    try:        # inquiry's cached parse: Q.players() reads the same 18 MB file
        players = Q._snap("sleeper_players_nfl.json")
    except FileNotFoundError:
        players = {}
    names = Q.players().names() if players else {}
    out: Dict[str, List[dict]] = {k: [] for k in ("sleeper_matchups", "sleeper_lineups", "sleeper_transactions",
                                                  "sleeper_moves", "sleeper_trade_picks", "sleeper_leagues",
                                                  "sleeper_scoring")}
    for year in Q.snapshot_seasons():
        league = _snap_json(f"season_{year}/league.json") or {}
        settings = league.get("settings") or {}
        positions = list(league.get("roster_positions") or [])
        slots = [p for p in positions if p not in ("BN", "IR", "TAXI")]
        teams = Q.teams(year)
        out["sleeper_leagues"].append({
            "Year": year, "league_id": league.get("league_id"), "name": league.get("name"),
            "status": league.get("status"), "lineup_size": len(slots), "roster_size": len(positions),
            "starting_slots": ",".join(slots), "roster_positions": ",".join(positions),
            **{k: v for k, v in settings.items() if isinstance(v, (int, float, str, bool)) or v is None}})
        for stat, pts in (league.get("scoring_settings") or {}).items():
            out["sleeper_scoring"].append({"Year": year, "stat": stat, "points": float(pts)})
        wdir = Q.snapshot_dir() / f"season_{year}" / "weeks"
        for wpath in sorted(wdir.glob("week_*")):
            week = int(wpath.name.split("_")[1])
            ms = _snap_json(f"season_{year}/weeks/{wpath.name}/matchups.json") or []
            by_mid: Dict[object, List[int]] = {}
            for m in ms:
                by_mid.setdefault(m.get("matchup_id"), []).append(m["roster_id"])
            pts_by_rid = {m["roster_id"]: m.get("points") for m in ms}
            for m in ms:
                rid = m["roster_id"]
                mid = m.get("matchup_id")
                opp = [r for r in by_mid.get(mid, []) if r != rid] if mid is not None else []
                out["sleeper_matchups"].append({
                    "Year": year, "Week": week, "Team": teams.get(rid), "roster_id": rid, "matchup_id": mid,
                    "Points": m.get("points"), "Opponent": teams.get(opp[0]) if opp else None,
                    "Points against": pts_by_rid.get(opp[0]) if opp else None})
                starters = list(m.get("starters") or [])
                pp = m.get("players_points") or {}
                for i, pid in enumerate(starters):
                    empty = str(pid) == Q.EMPTY_SLOT
                    out["sleeper_lineups"].append({
                        "Year": year, "Week": week, "Team": teams.get(rid), "roster_id": rid,
                        "Player ID": None if empty else str(pid), "Player": None if empty else names.get(str(pid), str(pid)),
                        "Starter": True, "Slot": slots[i] if i < len(slots) else None, "Slot index": i,
                        "Points": None if empty else pp.get(str(pid)), "Empty slot": empty})
                for pid in m.get("players") or []:
                    if pid in starters:
                        continue
                    out["sleeper_lineups"].append({
                        "Year": year, "Week": week, "Team": teams.get(rid), "roster_id": rid,
                        "Player ID": str(pid), "Player": names.get(str(pid), str(pid)), "Starter": False,
                        "Slot": "BN", "Slot index": None, "Points": pp.get(str(pid)), "Empty slot": False})
            tx = _snap_json(f"season_{year}/weeks/{wpath.name}/transactions.json") or []
            for t in tx:
                tid = str(t.get("transaction_id"))
                bid = (t.get("settings") or {}).get("waiver_bid")
                base = {"transaction_id": tid, "Year": year, "Week": week, "type": t.get("type"),
                        "status": t.get("status"), "Created (ET)": _et(t.get("created")),
                        "Status updated (ET)": _et(t.get("status_updated"))}
                rids = list(t.get("roster_ids") or [])
                out["sleeper_transactions"].append({
                    **base, "Teams": ", ".join(str(teams.get(r, r)) for r in rids), "roster_ids": ",".join(map(str, rids)),
                    "Waiver bid": bid, "adds": len(t.get("adds") or {}), "drops": len(t.get("drops") or {}),
                    "picks": len(t.get("draft_picks") or []), "notes": (t.get("metadata") or {}).get("notes")})
                for move, mapping in (("add", t.get("adds") or {}), ("drop", t.get("drops") or {})):
                    for pid, rid in mapping.items():
                        out["sleeper_moves"].append({
                            **base, "Team": teams.get(rid), "roster_id": rid, "Move": move,
                            "Player ID": str(pid), "Player": names.get(str(pid), str(pid)),
                            "Waiver bid": bid if move == "add" else None})
                for pk in t.get("draft_picks") or []:
                    out["sleeper_trade_picks"].append({
                        **base, "Pick season": pk.get("season"), "Round": pk.get("round"),
                        "Original team": teams.get(pk.get("roster_id")), "To": teams.get(pk.get("owner_id")),
                        "From": teams.get(pk.get("previous_owner_id"))})
    frames = {k: pd.DataFrame(v) for k, v in out.items() if v}
    if players:
        scalar = set()
        for rec in players.values():
            scalar.update(k for k, v in rec.items() if isinstance(v, (str, int, float, bool)) or v is None)
        rows = []
        for pid, rec in players.items():
            r = {k: rec.get(k) for k in scalar if not isinstance(rec.get(k), (dict, list))}
            r["fantasy_positions"] = ",".join(rec.get("fantasy_positions") or [])
            r["Player ID"] = str(pid)
            r["Player"] = names.get(str(pid), str(pid))
            rows.append(r)
        p = pd.DataFrame(rows)
        p = p.drop(columns=[c for c in ("player_id",) if c in p.columns])
        lead = ["Player ID", "Player", "position", "team", "age", "birth_date", "years_exp", "status",
                "injury_status", "gsis_id"]
        lead = [c for c in lead if c in p.columns]
        p = p[lead + sorted(c for c in p.columns if c not in lead)]
        if "gsis_id" in p.columns:
            p["gsis_id"] = p["gsis_id"].map(lambda v: v.strip() if isinstance(v, str) else v)
        frames["sleeper_players"] = p
    return frames


# ---------------------------------------------------------------------------
# Caveats: stored in the database, printed under every query that touches them
# ---------------------------------------------------------------------------
_PW_LIKE = r"pw|lpw|pw_full|starters|bench|player_week|live_pw|player_year|py|pyt|player_all_time|pa"
_TW_LIKE = r"tw|twt|team_week|tw_regular|ts|team_year|ty|tyt|team_all_time|ta|league_week|lw|lwt|league_year|ly|lyt|league_all_time|la"


def _caveat_rows(meta: Dict[str, str]) -> List[Tuple[str, str, str, str]]:
    """(topic, tables regex, SQL-text regex, text): a caveat is printed when
    the query names a table matching the first, or its text matches the
    second ('' = never)."""
    return [
        ("as of", ".*", "", f"exports finalized through {meta.get('exports_through', '?')}; snapshot captured "
                            f"{meta.get('snapshot_captured_at', '?')}; database built {meta.get('built_at', '?')}"),
        ("semifinal +5", rf"{_TW_LIKE}|pw|lpw|pw_full|starters|bench", r"\bpf\b",
         f"team PF (and Margin, Points against, PF-derived columns) includes the semifinal +5 "
         f"({meta.get('semifinal_rows', '?')} team-weeks: {meta.get('semifinal_weeks', '?')}); player Points, "
         "sleeper_* points and live points do not"),
        ("over N", "", r"(?<![<>!=])(>=?|<=?)(?!=)\s*-?\d",
         "'over N' in fast.py is strict `> N`; a `>=` reading adds the rows at exactly N — check both "
         "when a row sits on the line"),
        ("lineup size", rf"{_PW_LIKE}|{_TW_LIKE}|sleeper_lineups", "",
         f"starters per lineup by season: {meta.get('lineup_sizes', '?')} — a count record is not lineup-size neutral"),
        ("week types", rf"{_PW_LIKE}|{_TW_LIKE}|sleeper_matchups|sleeper_lineups", "",
         "every export week counts (regular season, playoffs, consolation, toilet bowl); filter on "
         "`Week Name` (tw_regular = Week N rows only)"),
        ("bench", "bench", r"\bbench\b",
         "bench = every non-starter row, taxi and IR included (no weekly taxi flag exists)"),
        ("2020", r"sleeper_\w+", "",
         "sleeper_* tables start in 2021: 2020 was played on ESPN and has no snapshot (it is in the export sheets)"),
        ("FAAB", "sleeper_transactions|sleeper_moves|add_drops", r"faab|waiver bid",
         "FAAB is a 100 budget under house rules, not Sleeper's 10000 setting; `Waiver bid` is already in "
         "those units (it equals add_drops `Faab` on matched 2022-26 claims). sleeper_moves includes FAILED claims"),
        ("player dictionary", "sleeper_players", "",
         "sleeper_players is Sleeper's CURRENT dictionary (position, team, status today); per-season "
         "position is player_positions / player_week `Position`"),
        ("live", "lpw|live_pw|live_tw", "",
         "live rows (`Live` = true) are raw Sleeper points (no +5); `Win?` = leading now; game status is a "
         "kickoff-clock guess"),
        ("acquisition", "", r"acquired|season source|in-season pickup",
         "`Acquired via` = how the player's CURRENT stint on that team began; `Season source` = Week-1 roster "
         "or Acquired via; `In-season pickup` = Season source Waiver / Free agency"),
    ]


def _meta(con, fp: str, built_s: float) -> Dict[str, str]:
    meta = {"schema_version": str(SCHEMA_VERSION), "fingerprint": fp,
            "built_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
            "build_seconds": f"{built_s:.1f}"}
    cur = max(Q.export_seasons() or [0])
    if cur:
        meta["exports_through"] = f"{cur} week {Q.finalized_week(cur)}"
    sm = _snap_json("_snapshot_meta.json") or {}
    meta["snapshot_captured_at"] = str(sm.get("captured_at", "?"))[:16].replace("T", " ") + " UTC"
    sizes = con.execute("""
        SELECT Year, mode(n) AS n FROM (
          SELECT Year, Team, Week, count(*) AS n FROM pw WHERE "Starter/Bench" = 'Starter' GROUP BY ALL)
        GROUP BY Year ORDER BY Year""").fetchall()
    runs: List[List[int]] = []
    for y, n in sizes:
        if runs and runs[-1][2] == n:
            runs[-1][1] = y
        else:
            runs.append([y, y, n])
    meta["lineup_sizes"] = ", ".join(f"{a}-{b}: {n}" if a != b else f"{a}: {n}" for a, b, n in runs)
    semi = con.execute("""
        SELECT t.Year, t.Week FROM team_week t JOIN (
          SELECT Team, Year, Week, sum(Points) AS s FROM pw WHERE "Starter/Bench" = 'Starter' GROUP BY ALL) p
        USING (Team, Year, Week) WHERE abs(t.PF - p.s - 5) < 0.005 ORDER BY 1, 2""").fetchall()
    meta["semifinal_rows"] = str(len(semi))
    weeks: Dict[int, int] = {}
    for y, w in semi:
        weeks[y] = w
    meta["semifinal_weeks"] = ", ".join(f"{y} wk{w}" for y, w in weeks.items())
    return meta


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
_VIEWS = {
    "starters": "SELECT * FROM pw WHERE \"Starter/Bench\" = 'Starter'",
    "bench": "SELECT * FROM pw WHERE \"Starter/Bench\" <> 'Starter'",
    "tw_regular": "SELECT * FROM team_week WHERE \"Week Name\" LIKE 'Week %'",
    "player_positions": ("SELECT Player, Year, arg_max(Position, _row) AS Position FROM player_week "
                         "WHERE Position IS NOT NULL GROUP BY Player, Year"),
    "catalog_columns": ("SELECT table_name AS \"table\", column_name AS \"column\", data_type AS type, "
                        "ordinal_position AS position FROM information_schema.columns "
                        "WHERE table_schema = 'main' AND table_name NOT LIKE '\\_%' ESCAPE '\\' ORDER BY 1, 4"),
}


def _pw_full_sql(con) -> str:
    have = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'player_week'").fetchall()}
    add = [c for c in ("Opponent", "Win?", "Margin", "PF", "Points against") if c not in have]
    cols = "".join(f", t.{_qi(c)}" for c in add)
    return (f"SELECT p.*{cols} FROM player_week p LEFT JOIN team_week t "
            "ON t.Team = p.Team AND t.Year = p.Year AND t.Week = p.Week")


def _create_ts(con) -> None:
    """`ts` = `fast.team_seasons()` in SQL: typed team_year plus `Regular
    season all-play win %` — each regular week, the share of the other teams
    outscored, ties half (pandas' average rank: (rank - 1) / (n - 1))."""
    con.execute("""
        CREATE TABLE ts AS
        WITH r AS (
          SELECT Team, Year,
                 (rank() OVER w - 1 + (count(*) OVER (PARTITION BY Year, Week, PF) - 1) / 2.0)
                   / (count(*) OVER (PARTITION BY Year, Week) - 1) AS ap
          FROM team_week WHERE "Week Name" LIKE 'Week%'
          WINDOW w AS (PARTITION BY Year, Week ORDER BY PF))
        SELECT y.* EXCLUDE (_row), a."Regular season all-play win %", y._row
        FROM team_year y LEFT JOIN (
          SELECT Team, Year, avg(ap) AS "Regular season all-play win %" FROM r GROUP BY Team, Year) a
        USING (Team, Year) ORDER BY y._row""")
    con.execute('CREATE UNIQUE INDEX ux_ts ON ts (Team, Year)')
    n = con.execute("SELECT count(*) FROM ts").fetchone()[0]
    _TABLES.append({"table": "ts", "kind": "fast.team_seasons() (SQL)", "rows": n, "key": "Team, Year"})


def build(path: Optional[os.PathLike] = None, quiet: bool = False) -> Path:
    """Build the database from the committed exports + snapshot (seconds).
    Written to a temp file and moved into place, so a reader never sees half."""
    from lotg_support import fast
    duckdb = _duckdb()
    target = Path(path) if path else default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp{os.getpid()}")
    for p in (tmp, Path(str(tmp) + ".wal")):
        if p.exists():
            p.unlink()
    t0 = time.time()
    fp = fingerprint()
    notes: List[str] = []
    _TABLES.clear()
    con = duckdb.connect(str(tmp))
    con.execute("SET enable_progress_bar = false")
    try:
        for sheet in Q.SHEETS:
            try:
                df = Q.load_sheet(sheet)
            except FileNotFoundError:
                continue
            _store(con, sheet, df, notes, "export sheet", text=True)
        _store(con, "pw", fast.player_weeks(), notes, "fast.player_weeks()")
        _create_ts(con)
        for name, df in snapshot_frames().items():
            _store(con, name, df, notes, "snapshot")
        bridge = Q.snapshot_dir() / "dynastyprocess_playerids.csv"
        if bridge.exists():
            _store(con, "id_bridge", pd.read_csv(bridge, low_memory=False), notes, "snapshot")
        sched = Q.schedule()
        if not sched.empty:
            _store(con, "nfl_schedule", sched, notes, ".cache/nfldata_games.csv")
        tables = {t["table"] for t in _TABLES}
        for alias, sheet in ALIASES.items():
            if sheet in tables:
                con.execute(f"CREATE VIEW {alias} AS SELECT * FROM {_qi(sheet)}")
        for name, sql in _VIEWS.items():
            con.execute(f"CREATE VIEW {_qi(name)} AS {sql}")
        if "player_week" in tables and "team_week" in tables:
            con.execute(f"CREATE VIEW pw_full AS {_pw_full_sql(con)}")
        meta = _meta(con, fp, time.time() - t0)
        meta["notes"] = " | ".join(notes)
        rows = _caveat_rows(meta)
        con.execute("CREATE TABLE _caveats (topic VARCHAR, tables VARCHAR, sql_text VARCHAR, text VARCHAR)")
        con.executemany("INSERT INTO _caveats VALUES (?, ?, ?, ?)", rows)
        con.execute("CREATE VIEW caveats AS SELECT * FROM _caveats")
        con.register("_frame_tables", pd.DataFrame(_TABLES))
        con.execute("CREATE TABLE _tables AS SELECT * FROM _frame_tables")
        con.unregister("_frame_tables")
        for t in _TABLES:
            mine = [txt for topic, rx, _, txt in rows if rx and topic != "as of" and re.fullmatch(rx, t["table"])]
            text = f"{t['kind']}; key {t['key']}. " + " ".join(mine)
            con.execute(f"COMMENT ON TABLE {_qi(t['table'])} IS {_ql(text.strip())}")
        for tbl in ("team_week", "pw", "ts", "team_year"):
            if tbl in tables:
                cols = {r[0] for r in con.execute(f"SELECT column_name FROM information_schema.columns "
                                                  f"WHERE table_name = {_ql(tbl)}").fetchall()}
                if "PF" in cols:
                    con.execute(f"COMMENT ON COLUMN {_qi(tbl)}.PF IS 'includes the semifinal +5'")
        meta["build_seconds"] = f"{time.time() - t0:.1f}"
        con.execute("CREATE TABLE _meta (key VARCHAR, value VARCHAR)")
        con.executemany("INSERT INTO _meta VALUES (?, ?)", list(meta.items()))
        con.execute("CHECKPOINT")
    finally:
        con.close()
    os.replace(tmp, target)
    if not quiet:
        size = target.stat().st_size / 1e6
        print(f"# built {target} in {time.time() - t0:.1f}s ({size:.1f} MB, {len(_TABLES)} tables)")
        for n in notes:
            print(f"# note: {n}")
    return target


def connect(path: Optional[os.PathLike] = None, rebuild: str = "auto", live=None, quiet: bool = False):
    """A read-only connection, (re)building first when the inputs moved
    (`rebuild`: 'auto' | 'always' | 'never'). `live` (a `live.LiveWeek`) adds
    `lpw`, `live_pw`, `live_tw` to this connection only."""
    duckdb = _duckdb()
    target = Path(path) if path else default_path()
    if rebuild == "always" or (rebuild == "auto" and not is_fresh(target)):
        build(target, quiet=quiet)
    con = duckdb.connect(str(target), read_only=True)
    if live is not None:
        attach_live(con, live)
    return con


def attach_live(con, live) -> None:
    """Register the live week on a connection: `lpw` = `fast.player_weeks(live)`
    (history + live rows, `Live` true), `live_pw` / `live_tw` = the live week alone."""
    from lotg_support import fast
    for name, df in (("lpw", fast.player_weeks(live)), ("live_pw", live.player_week),
                     ("live_tw", live.team_week)):
        frame, casts, txt = normalize(df.reset_index(drop=True))
        con.register(f"_{name}", _arrow(frame))
        typed = _typed_exprs(con, f"_{name}", txt, numbers=False)
        sel = ", ".join(f"{typed[c]} AS {_qi(c)}" if c in typed else
                        f"CAST({_qi(c)} AS {casts[c]}) AS {_qi(c)}" if c in casts else _qi(c)
                        for c in frame.columns)
        con.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS SELECT {sel} FROM _{name}")
    con.execute(f"CREATE OR REPLACE TEMP VIEW _live_meta AS SELECT {_ql(' / '.join(live.caveats()))} AS text")


def query(sql: str, con=None, **kw) -> pd.DataFrame:
    """Run one SQL statement and return a DataFrame."""
    own = con is None
    con = con or connect(**kw)
    try:
        return con.execute(sql).df()
    finally:
        if own:
            con.close()


def _relations(con) -> List[str]:
    return [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name NOT LIKE '\\_%' ESCAPE '\\'").fetchall()]


def footer(sql: str, con) -> List[str]:
    """The caveats this query touches (by the tables it names, or its text)."""
    text = re.sub(r"'[^']*'", "''", sql)              # literals never select a caveat
    low = text.lower()
    named = {t for t in _relations(con) if re.search(rf"(?<![\w\"]){re.escape(t.lower())}(?![\w\"])", low)}
    out = []
    for topic, rx, srx, txt in con.execute("SELECT * FROM _caveats").fetchall():
        hit = (topic == "as of" or (rx and any(re.fullmatch(rx, t) for t in named))
               or (srx and re.search(srx, low)))
        if hit:
            out.append(txt)
    if any(t in named for t in ("lpw", "live_pw", "live_tw")):
        try:
            out.insert(0, con.execute("SELECT text FROM _live_meta").fetchone()[0])
        except Exception:   # noqa: BLE001 - not attached
            pass
    return out


def describe(con, table: Optional[str] = None) -> pd.DataFrame:
    """Every table and view (rows, key, comment), or one table's columns."""
    if table:
        return con.execute(f"DESCRIBE {_qi(table)}").df()[["column_name", "column_type", "null"]]
    t = con.execute("SELECT * FROM _tables").df()
    c = con.execute("SELECT table_name AS \"table\", comment FROM duckdb_tables() "
                    "UNION ALL SELECT view_name, comment FROM duckdb_views() WHERE NOT internal").df()
    out = c.merge(t, on="table", how="left")
    out["kind"] = out["kind"].fillna("view")
    out = out[~out["table"].str.startswith("_")]
    return out[["table", "kind", "rows", "key", "comment"]].sort_values(["kind", "table"])


def export_parquet(out_dir: os.PathLike, con=None) -> Path:
    """Every table as Parquet (one file each, plus schema.sql) — for readers
    without DuckDB (a static site, pyarrow, polars)."""
    own = con is None
    con = con or connect()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        con.execute(f"EXPORT DATABASE {_ql(str(out))} (FORMAT PARQUET)")
    finally:
        if own:
            con.close()
    return out


# ---------------------------------------------------------------------------
# Command line (scripts/sql.py and `fast.py sql`)
# ---------------------------------------------------------------------------
def print_result(df: pd.DataFrame, max_rows: int = 200, fmt: str = "table") -> None:
    if fmt == "csv":
        print(df.to_csv(index=False), end="")
        return
    if fmt == "json":
        print(df.to_json(orient="records", date_format="iso"))
        return
    shown = df if not max_rows or len(df) <= max_rows else df.head(max_rows)
    print(shown.to_string(index=False) if len(shown.columns) else "(no columns)")
    if len(shown) < len(df):
        print(f"... {len(df)} rows, first {max_rows} shown (-n 0 for all, or add LIMIT)")
    elif len(df) == 0:
        print("(0 rows)")


def run(sql: str, con, max_rows: int = 200, fmt: str = "table", notes: bool = True) -> pd.DataFrame:
    """Run one statement, print the result and (as '# ' lines) its caveats."""
    df = con.execute(sql).df()
    print_result(df, max_rows=max_rows, fmt=fmt)
    if notes and fmt == "table":
        for line in footer(sql, con):
            print(f"# {line}")
    return df
