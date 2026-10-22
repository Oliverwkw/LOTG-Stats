"""How many different players a team / the league started and rostered
(lotg_support.unique_players).

`Number of players started` / `Number of players rostered` on team_year /
team_all_time / league_year / league_all_time: distinct Player IDs over the
period, counted directly — never the sum of the QB/WR/RB/TE columns — so a
player listed at two positions counts once.

Run: python tests/test_unique_players.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import unique_players as U  # noqa: E402

_EXPORTS = _ROOT / "exports"
_POS = ("QB", "WR", "RB", "TE")


def _row(team, year, pid, pos, starter=True):
    return {"Team": team, "Year": year, "Player ID": pid, "Position": pos,
            "Starter/Bench": "Starter" if starter else "Bench"}


def _pw():
    return pd.DataFrame([
        _row("A", 2024, "1", "QB"), _row("A", 2024, "1", "QB"),       # same QB, two weeks
        _row("A", 2024, "2", "TE"), _row("A", 2024, "2", "QB"),       # one player, two positions
        _row("A", 2024, "3", "WR", starter=False),                    # bench only
        _row("A", 2024, "4", None),                                   # position missing
        _row("A", 2025, "1", "QB", starter=False),
        _row("B", 2024, "1", "QB"),                                   # same player, other team
        _row("B", 2024, None, "RB"),                                  # no Player ID: not a player
    ])


def test_team_year_counts_each_player_once():
    out = U.unique_player_counts(_pw(), ["Team", "Year"]).set_index(["Team", "Year"])
    a = out.loc[("A", 2024)]
    assert (a[U.STARTED], a[U.ROSTERED]) == (3, 4), a.to_dict()
    # a season with only bench rows → 0 started (a row, not missing)
    assert (out.loc[("A", 2025), U.STARTED], out.loc[("A", 2025), U.ROSTERED]) == (0, 1)
    assert (out.loc[("B", 2024), U.STARTED], out.loc[("B", 2024), U.ROSTERED]) == (1, 1)


def test_two_positions_is_one_player_not_two():
    pw = _pw()
    a = pw[(pw["Team"] == "A") & (pw["Year"] == 2024) & pw["Position"].notna()]
    by_pos = a[a["Starter/Bench"] == "Starter"].groupby("Position")["Player ID"].nunique().sum()
    got = U.unique_player_counts(a, ["Team", "Year"]).iloc[0][U.STARTED]
    assert (by_pos, got) == (3, 2), (by_pos, got)


def test_all_time_and_league_keys():
    t = U.unique_player_counts(_pw(), ["Team"]).set_index("Team")
    assert (t.loc["A", U.STARTED], t.loc["A", U.ROSTERED]) == (3, 4)
    y = U.unique_player_counts(_pw(), ["Year"]).set_index("Year")
    assert (y.loc[2024, U.STARTED], y.loc[2024, U.ROSTERED]) == (3, 4)
    assert (y.loc[2025, U.STARTED], y.loc[2025, U.ROSTERED]) == (0, 1)
    every = U.unique_player_counts(_pw(), [])
    assert len(every) == 1 and (every.at[0, U.STARTED], every.at[0, U.ROSTERED]) == (3, 4)


def test_empty_input():
    for keys in (["Team", "Year"], []):
        out = U.unique_player_counts(pd.DataFrame(), keys)
        assert out.empty and list(out.columns) == keys + U.COLUMNS


def test_tenure_rows_add_only_missing_tenures():
    pw = _pw()
    tenures = [("A", 2024, "1"),     # already in player_week → no row
               ("A", 2024, "9"),     # picked up and dropped between lineups
               ("A", 2024, "9"),     # second stint, same season → still one row
               ("A", 2025, "3"),     # rostered 2024 only; held 2025 off-snapshot
               ("B", 2024, None),    # no Player ID → skipped
               ("A", None, "8")]     # no season → skipped
    ex = U.tenure_rows(pw, tenures, {"9": "RB"}.get, lambda p, y: p == "9")
    got = sorted(zip(ex["Team"], ex["Year"], ex["Player ID"], ex["Position"], ex["Rookie?"]),
                 key=str)
    # player 3's position comes from his player_week row, not the fallback
    assert got == sorted([("A", 2024, "9", "RB", 1), ("A", 2025, "3", "WR", 0)], key=str), got
    assert (ex["Starter/Bench"] == "Bench").all()


def test_rostered_counts_include_tenures_started_does_not():
    pw = _pw().assign(**{"Rookie?": 0})
    ex = U.tenure_rows(pw, [("A", 2024, "9")], {"9": "RB"}.get, lambda p, y: True)
    rows = pd.concat([pw[list(ex.columns)], ex], ignore_index=True)
    c = U.rostered_counts(rows, ["Team", "Year"]).set_index(["Team", "Year"]).loc[("A", 2024)]
    assert c[U.ROSTERED] == 5 and c["Number of RB rostered"] == 1, c.to_dict()
    assert c["Number of rookies rostered"] == 1 and c["Number of QB rostered"] == 2, c.to_dict()
    # started is untouched by tenure rows
    s = U.unique_player_counts(rows, ["Team", "Year"]).set_index(["Team", "Year"]).loc[("A", 2024)]
    assert s[U.STARTED] == 3
    every = U.rostered_counts(rows, [])
    assert len(every) == 1 and every.at[0, U.ROSTERED] == 5


def test_rostered_counts_without_tenures_match_unique_counts():
    pw = _pw()
    for keys in (["Team", "Year"], ["Team"], ["Year"], []):
        a = U.rostered_counts(pw, keys)[keys + [U.ROSTERED]]
        b = U.unique_player_counts(pw, keys)[keys + [U.ROSTERED]]
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True), check_dtype=False)


def test_started_share():
    got = U.started_share(pd.Series([3, 0, 2]), pd.Series([4, 0, 2])).tolist()
    assert got[0] == 0.75 and pd.isna(got[1]) and got[2] == 1.0, got


def _sheet(name):
    p = _EXPORTS / f"{name}.csv"
    return pd.read_csv(p) if p.exists() else None


def test_committed_sheets_bound_by_position_columns():
    """Where the committed sheets carry the columns (completed seasons only):
    the total is at least the largest position count and at most their sum
    (equal to the sum unless a player is listed at two positions), and never
    more rostered than started."""
    checked = 0
    for name, year_keyed in (("team_year", True), ("team_all_time", False),
                             ("league_year", True), ("league_all_time", False)):
        df = _sheet(name)
        if df is None or not set(U.COLUMNS).issubset(df.columns):
            print(f"{name}: columns not in committed exports — not run")
            continue
        if year_keyed:
            yr = pd.to_numeric(df["Year"], errors="coerce")
            df = df[yr < yr.max()]
        for kind, col in (("started", U.STARTED), ("rostered", U.ROSTERED)):
            per = df[[f"Number of {p} {kind}" for p in _POS]].apply(pd.to_numeric, errors="coerce")
            tot = pd.to_numeric(df[col], errors="coerce")
            assert (tot <= per.sum(axis=1)).all(), (name, kind)
            assert (tot >= per.max(axis=1)).all(), (name, kind)
        assert (pd.to_numeric(df[U.STARTED]) <= pd.to_numeric(df[U.ROSTERED])).all(), name
        if U.PCT in df.columns:
            pct = pd.to_numeric(df[U.PCT], errors="coerce")
            want = (pd.to_numeric(df[U.STARTED]) / pd.to_numeric(df[U.ROSTERED])).round(4)
            assert ((pct - want).abs() < 1e-9).all(), name
        checked += 1
    if not checked:
        print("exports/ predate the unique-player columns — reconciliation not run")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
