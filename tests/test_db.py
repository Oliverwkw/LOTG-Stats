"""The DuckDB query layer (`lotg_support.db`, `scripts/sql.py`, `fast.py sql`).

A SQL answer is only worth having if it is the `fast.py q` answer, so:

- every export sheet in the database holds `fast.typed_sheet`'s values —
  same columns, same blanks, same booleans and text — and its numbers are the
  exact parse of the CSV text (`float(text)`; typed_sheet's pd.to_numeric may
  sit one ulp away, so the comparison with it allows 1e-12 relative);
- `pw` is `fast.player_weeks()` value for value, `ts` is `fast.team_seasons()`
  (all-play within 1e-12);
- `Year` / `Week` are INTEGER, `Win?` BOOLEAN, dates DATE / TIMESTAMP, and
  the natural keys are unique;
- the raw snapshot tables reconcile with the build: raw matchup points + the
  semifinal +5 = team_week PF, starters' points sum to the matchup points;
- a column the build adds shows up typed with no code change, and an input
  change makes the database stale;
- the footer prints the caveats a query touches; the CLIs run; a snapshot
  week attached as "live" gives `lpw` = `fast.player_weeks(live)`.

Builds once into a temp directory (never `.cache/`). Only completed seasons
are asserted against. Skips cleanly without `exports/` or without duckdb.

Run: python tests/test_db.py
"""
from __future__ import annotations

import io
import math
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import fast, inquiry as Q  # noqa: E402

try:
    import duckdb  # noqa: F401
    _HAVE_DUCKDB = True
except ImportError:
    _HAVE_DUCKDB = False

_HAVE_EXPORTS = (_ROOT / "exports" / "team_week.csv").exists()
_HAVE_SNAPSHOT = (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()
_TMP = Path(tempfile.mkdtemp(prefix="lotg_db_test_"))
_DB = _TMP / "lotg.duckdb"


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _ready() -> bool:
    if not _HAVE_DUCKDB:
        return not _skip("duckdb not installed (pip install duckdb)")
    if not _HAVE_EXPORTS:
        return not _skip("no exports/")
    return True


def _con():
    from lotg_support import db
    if not _DB.exists():
        db.build(_DB, quiet=True)
    return db.connect(_DB, rebuild="never")


def _same_numbers(a: pd.Series, b: pd.Series) -> bool:
    x = pd.to_numeric(a).astype(float).to_numpy()
    y = pd.to_numeric(b).astype(float).to_numpy()
    nan = np.isnan(x)
    return bool((nan == np.isnan(y)).all() and np.allclose(x[~nan], y[~nan], rtol=1e-12, atol=0))


def _text(s: pd.Series) -> list:
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or v == "" else str(v)
            for v in s.astype(object)]


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_normalize_types_frames_for_sql():
    from lotg_support import db
    df = pd.DataFrame({"Year": pd.array([2024, None], dtype="Int64"), "flag": [True, None],
                       "n": [1, None], "mix": ["a", 3], "s": ["x", ""]}, dtype=object)
    df["Year"] = df["Year"].astype("Int64")
    out, casts, text = db.normalize(df)
    assert casts == {"Year": "INTEGER"}
    assert str(out["flag"].dtype) == "boolean"
    assert pd.api.types.is_numeric_dtype(out["n"])
    assert out["mix"].tolist() == ["a", "3"] and set(text) == {"mix", "s"}


def test_sql_typing_follows_typed_sheet_rules():
    if not _HAVE_DUCKDB and _skip("duckdb not installed"):
        return
    from lotg_support import db
    import duckdb
    con = duckdb.connect()
    raw = pd.DataFrame({"Year": ["2024", "2025", ""], "num": ["1.5", "N/A", "nan"], "b": ["Yes", "no", ""],
                        "d": ["2024-09-01", "", "2024-10-01"], "t": ["2024-09-01 10:00:00", "", "2024-09-02"],
                        "s": ["3-1", "", "In Progress"], "streak": ["4", "In Progress", ""],
                        "Player ID": ["4034", "7564.0", ""], "Player IDs received": ["1, 2", "", "3"]})
    con.register("_frame", raw.assign(_row=range(1, 4)))
    db._create_typed(con, "x", [f"{e} AS {db._qi(c)}" for c, e in db._typed_exprs(con, "_frame", list(raw.columns)).items()])
    types = dict(con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'x'").fetchall())
    assert types == {"Year": "INTEGER", "num": "DOUBLE", "b": "BOOLEAN", "d": "DATE", "t": "TIMESTAMP",
                     "s": "VARCHAR", "streak": "VARCHAR", "Player ID": "VARCHAR",
                     "Player IDs received": "VARCHAR", "_row": "BIGINT"}, types
    rows = con.execute("SELECT * FROM x ORDER BY _row").fetchall()
    assert rows[1][1] is None and rows[2][1] is None          # N/A and nan are blank, never NaN
    assert rows[0][2] is True and rows[1][2] is False and rows[2][2] is None
    assert rows[1][5] is None and rows[2][6] is None           # blank text -> NULL
    assert [r[7] for r in rows] == ["4034", "7564", None]       # ids are labels, as player_ids.clean_id


# ---------------------------------------------------------------------------
# Against the committed data
# ---------------------------------------------------------------------------
def test_every_sheet_holds_typed_sheets_values():
    if not _ready():
        return
    con = _con()
    checked = 0
    for sheet in Q.SHEETS:
        try:
            a = fast.typed_sheet(sheet)
        except FileNotFoundError:
            continue
        raw = Q.load_sheet(sheet)
        b = con.execute(f'SELECT * EXCLUDE (_row) FROM "{sheet}" ORDER BY _row').df()
        assert list(a.columns) == list(b.columns), sheet
        assert len(a) == len(b), sheet
        for c in a.columns:
            x, y = a[c], b[c]
            if pd.api.types.is_bool_dtype(y) or str(y.dtype) == "boolean" or (
                    y.dtype == object and pd.api.types.infer_dtype(y.dropna()) == "boolean"):
                assert _text(x) == _text(y), (sheet, c)
            elif pd.api.types.is_numeric_dtype(y):
                assert pd.api.types.is_numeric_dtype(x), (sheet, c, "numeric only in the db")
                assert _same_numbers(x, y), (sheet, c)
                # exact: the db holds float(text) of the CSV cell
                txt = raw[c].astype(str).str.strip()
                keep = ~txt.isin(["", "nan", "None", "N/A", "NA", "-"])
                want = np.array([float(v) for v in txt[keep]])
                got = pd.to_numeric(y[keep.to_numpy()]).astype(float).to_numpy()
                assert np.array_equal(want, got), (sheet, c)
            elif pd.api.types.is_datetime64_any_dtype(y) or (len(y.dropna()) and hasattr(y.dropna().iloc[0], "year")):
                want = pd.to_datetime(raw[c].where(raw[c].str.strip() != ""), errors="coerce")
                got = pd.to_datetime(y)
                assert ((want == got) | (want.isna() & got.isna())).all(), (sheet, c)
            else:
                assert _text(x) == _text(y), (sheet, c)
            checked += 1
    assert checked > 1500, checked


def test_pw_is_fast_player_weeks_and_ts_is_team_seasons():
    if not _ready():
        return
    con = _con()
    a = fast.player_weeks()
    b = con.execute("SELECT * EXCLUDE (_row) FROM pw ORDER BY _row").df()
    assert list(a.columns) == list(b.columns) and len(a) == len(b)
    for c in a.columns:
        if pd.api.types.is_numeric_dtype(b[c]) and not pd.api.types.is_bool_dtype(b[c]):
            x = pd.to_numeric(a[c]).astype(float).to_numpy()
            y = pd.to_numeric(b[c]).astype(float).to_numpy()
            assert np.array_equal(x, y, equal_nan=True), c          # bit for bit
        elif c == "Acquired":
            got = pd.to_datetime(b[c])
            want = pd.to_datetime(a[c])
            assert ((want == got) | (want.isna() & got.isna())).all()
        else:
            assert _text(a[c]) == _text(b[c]), c
    ts = fast.team_seasons()
    t = con.execute("SELECT * FROM ts").df().set_index(["Team", "Year"])
    col = "Regular season all-play win %"
    m = ts[[col]].join(t[[col]], rsuffix="_db")
    assert len(m) == len(t) == len(ts)
    assert _same_numbers(m[col], m[col + "_db"])
    assert _same_numbers(ts["Tanking"], t.loc[ts.index, "Tanking"])


def test_types_and_keys():
    if not _ready():
        return
    con = _con()
    types = {(t, c): d for t, c, d in con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns").fetchall()}
    for t in ("player_week", "team_week", "team_year", "pw", "ts", "player_year", "league_week"):
        assert types[(t, "Year")] == "INTEGER", t
    assert types[("team_week", "Win?")] == "BOOLEAN"
    assert types[("pw", "Win?")] == "BOOLEAN"
    assert types[("team_week", "PF")] == "DOUBLE"
    assert types[("add_drops", "Date")] == "TIMESTAMP"
    assert types[("player_additions", "Date")] == "DATE"
    assert types[("pw", "Acquired")] == "DATE"
    keys = dict(con.execute("SELECT \"table\", key FROM _tables").fetchall())
    for t in ("player_week", "team_week", "team_year", "pw", "ts", "sleeper_players"):
        assert keys.get(t, "_row") != "_row", (t, keys.get(t))
    # a natural key that is not unique is reported, never enforced
    for t, k in keys.items():
        if k != "_row":
            cols = ", ".join(f'"{c.strip()}"' for c in k.split(","))
            dup = con.execute(f'SELECT count(*) FROM (SELECT {cols} FROM "{t}" GROUP BY ALL HAVING count(*) > 1)').fetchone()[0]
            assert dup == 0, (t, k)


def test_snapshot_tables_reconcile_with_the_build():
    if not _ready() or (not _HAVE_SNAPSHOT and _skip("no snapshot")):
        return
    con = _con()
    done = ", ".join(str(y) for y in Q.completed_seasons())
    if not done and _skip("no completed snapshot season"):
        return
    off = con.execute(f"""
        SELECT t.Team, t.Year, t.Week, t.PF, m.Points
        FROM team_week t JOIN sleeper_matchups m USING (Team, Year, Week)
        WHERE t.Year IN ({done}) AND abs(t.PF - m.Points) > 0.011""").df()
    semi = {(y, Q.season_meta(y).semifinal_week) for y in Q.completed_seasons()}
    assert len(off), "the semifinal +5 should show"
    for r in off.itertuples():
        assert (r.Year, r.Week) in semi and abs(r.PF - r.Points - 5) < 0.011, r
    n = con.execute(f"SELECT count(*) FROM team_week WHERE Year IN ({done})").fetchone()[0]
    joined = con.execute(f"SELECT count(*) FROM team_week JOIN sleeper_matchups USING (Team, Year, Week) "
                         f"WHERE Year IN ({done})").fetchone()[0]
    assert joined == n, (joined, n)
    bad = con.execute(f"""
        SELECT m.Year, m.Week, m.Team, m.Points, s.p FROM sleeper_matchups m JOIN (
          SELECT Year, Week, roster_id, sum(coalesce(Points, 0)) AS p FROM sleeper_lineups WHERE Starter GROUP BY ALL) s
        USING (Year, Week, roster_id) WHERE m.Year IN ({done}) AND abs(m.Points - s.p) > 0.011""").df()
    assert bad.empty, bad.head()
    failed = con.execute("SELECT count(*) FROM sleeper_moves WHERE status = 'failed' AND \"Waiver bid\" IS NOT NULL").fetchone()[0]
    assert failed > 0
    assert con.execute("SELECT min(Year) FROM sleeper_matchups").fetchone()[0] == min(Q.snapshot_seasons())


def test_new_columns_are_picked_up_and_inputs_make_it_stale():
    if not _ready():
        return
    from lotg_support import db
    root = _TMP / "root"
    (root / "exports").mkdir(parents=True)
    for f in (_ROOT / "exports").glob("*.csv"):
        shutil.copy(f, root / "exports" / f.name)
    tw = pd.read_csv(root / "exports" / "team_week.csv", dtype=str, keep_default_na=False)
    tw["A brand new column"] = ["1.5" if i % 2 else "" for i in range(len(tw))]
    tw.to_csv(root / "exports" / "team_week.csv", index=False)
    path = root / "x.duckdb"
    Q.set_root(root)
    try:
        assert not db.is_fresh(path)
        db.build(path, quiet=True)
        assert db.is_fresh(path)
        con = db.connect(path, rebuild="never")
        t = con.execute("SELECT data_type FROM information_schema.columns WHERE table_name = 'team_week' "
                        "AND column_name = 'A brand new column'").fetchone()
        assert t == ("DOUBLE",), t
        assert con.execute('SELECT sum("A brand new column") FROM tw').fetchone()[0] == 1.5 * (len(tw) // 2)
        con.close()
        (root / "exports" / "team_week.csv").write_text((root / "exports" / "team_week.csv").read_text() + "\n")
        assert not db.is_fresh(path)
    finally:
        Q.set_root(None)


def test_footer_prints_the_caveats_a_query_touches():
    if not _ready():
        return
    from lotg_support import db
    con = _con()
    f = " | ".join(db.footer("SELECT Team, max(PF) FROM team_week GROUP BY Team", con))
    assert "semifinal +5" in f and "finalized through" in f and "lineup by season" in f
    assert "strict" not in f
    f = " | ".join(db.footer("SELECT count(*) FROM starters WHERE Points > 40", con))
    assert "strict `> N`" in f and "lineup by season" in f
    f = " | ".join(db.footer("SELECT * FROM bench WHERE Points >= 20", con))
    assert "taxi and IR" in f
    f = " | ".join(db.footer("SELECT * FROM sleeper_moves WHERE status = 'failed'", con))
    assert "2020 was played on ESPN" in f and "100 budget" in f
    f = " | ".join(db.footer("SELECT 'team_week > 5' AS x", con))     # literals select nothing
    assert "semifinal" not in f and "strict" not in f


def test_clis_run():
    if not _ready():
        return
    _con().close()
    old = os.environ.get("LOTG_DB")
    os.environ["LOTG_DB"] = str(_DB)
    try:
        import runpy
        sql = runpy.run_path(str(_ROOT / "scripts" / "sql.py"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            sql["main"](["SELECT Team, count(*) AS n FROM tw GROUP BY Team ORDER BY Team", "::",
                         "SELECT count(*) AS n FROM pw WHERE Points > 40"])
        out = buf.getvalue()
        assert "===== sql" in out and "Oliverwkw" in out and "# exports finalized through" in out, out
        buf = io.StringIO()
        with redirect_stdout(buf):
            sql["main"](["--tables"])
        assert "sleeper_lineups" in buf.getvalue() and "pw_full" in buf.getvalue()
        cli = runpy.run_path(str(_ROOT / "scripts" / "fast.py"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli["main"](["sql", "SELECT count(*) AS n FROM starters", "::", "q", "len(pw)"])
        out = buf.getvalue()
        n = int(fast.player_weeks()["Starter/Bench"].eq("Starter").sum())
        assert f"{n}" in out and "===== fast.py q" in out, out
    finally:
        if old is None:
            os.environ.pop("LOTG_DB", None)
        else:
            os.environ["LOTG_DB"] = old


def test_a_snapshot_week_attached_as_live():
    if not _ready() or (not _HAVE_SNAPSHOT and _skip("no snapshot")):
        return
    from lotg_support import db, live
    season = max(Q.completed_seasons())
    lw = live.fetch(season, 5, source="snapshot")
    con = _con()
    db.attach_live(con, lw)
    want = fast.player_weeks(lw)
    assert con.execute("SELECT count(*) FROM lpw").fetchone()[0] == len(want)
    assert con.execute("SELECT count(*) FROM lpw WHERE Live").fetchone()[0] == int(want["Live"].sum())
    assert con.execute("SELECT count(*) FROM live_tw").fetchone()[0] == len(lw.team_week)
    f = " | ".join(db.footer("SELECT * FROM lpw WHERE Live", con))
    assert "leading now" in f


TESTS = [
    test_normalize_types_frames_for_sql,
    test_sql_typing_follows_typed_sheet_rules,
    test_every_sheet_holds_typed_sheets_values,
    test_pw_is_fast_player_weeks_and_ts_is_team_seasons,
    test_types_and_keys,
    test_snapshot_tables_reconcile_with_the_build,
    test_new_columns_are_picked_up_and_inputs_make_it_stale,
    test_footer_prints_the_caveats_a_query_touches,
    test_clis_run,
    test_a_snapshot_week_attached_as_live,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall db checks passed")
