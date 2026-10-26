"""Bench points vs Points left on bench (lotg_support.bench_points).

"Bench points" = every point the bench scored (non-starter player_week rows,
taxi and IR included); "Points left on bench" = Max PF − the starters' points,
so the +5 semifinal bonus never shows up in it. Both sit on team_week, add up
across a game in the combined block, and sum (with a per-team-week average)
onto team_year / team_all_time / league_week / league_year / league_all_time.

Checks:
* the helper's sums, averages, N/A for an all-blank group and int keys;
* a pre-split digest snapshot's "Combined bench points" boards move to
  "Combined points left on bench" once, and new snapshots are stamped;
* on the committed exports (skips until a build carries the columns): every
  team_week matches a recount from player_week, the bonus games read
  Max PF − starters, the award flags the week's max, the combined columns add
  the two teams, and each rollup sheet is the sum / mean of team_week.

Run: python tests/test_bench_points.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import bench_points as B  # noqa: E402
from lotg_support import digest as D  # noqa: E402
from lotg_support import matchup as M  # noqa: E402

_EXPORTS = _ROOT / "exports"


def _pw():
    return pd.DataFrame({
        "Team": ["A", "A", "A", "A", "B", "B"],
        "Year": [2025, 2025, 2025, 2025, 2025, 2025],
        "Week": [1, 1, 1, 2, 1, 1],
        "Starter/Bench": ["Starter", "Bench", "Bench", "Starter", "Starter", "Starter"],
        "Points": [20.0, 7.5, None, 10.0, 15.0, 3.0],
    })


def test_bench_points_sum_non_starters_and_zero_without_a_bench():
    out = B.bench_points_by_team_week(_pw()).set_index(["Year", "Week", "Team"])[B.BENCH]
    assert out[(2025, 1, "A")] == 7.5          # the blank-points bench row counts 0
    assert out[(2025, 2, "A")] == 0.0
    assert out[(2025, 1, "B")] == 0.0


def test_points_left_on_bench_is_max_pf_minus_starters():
    assert B.points_left_on_bench(160.98, 121.30) == 39.68
    assert B.points_left_on_bench(None, 100.0) is None


def test_rollup_sums_averages_and_blank_groups():
    tw = pd.DataFrame({"Team": ["A", "A", "B"], "Year": ["2025", "2025", "2025"],
                       "Week": [1, 2, 1], B.BENCH: [80.0, 100.0, None],
                       B.LEFT: [10.0, 30.0, None]})
    ty = B.rollup(tw, ["Team", "Year"]).set_index("Team")
    assert ty.at["A", B.BENCH] == 180.0 and ty.at["A", "Avg bench points"] == 90.0
    assert ty.at["A", B.LEFT] == 40.0 and ty.at["A", "Avg points left on bench"] == 20.0
    assert ty.at["B", B.BENCH] is None or pd.isna(ty.at["B", B.BENCH])
    assert isinstance(ty.at["A", "Year"], (int,)) or str(ty["Year"].dtype).startswith("int")
    lw = B.rollup(tw, ["Year", "Week"], averages=False)
    assert list(lw.columns) == ["Year", "Week", B.BENCH, B.LEFT]
    assert lw.set_index("Week").at[1, B.BENCH] == 80.0
    la = B.rollup(tw, [])
    assert la.at[0, B.BENCH] == 180.0 and la.at[0, "Avg points left on bench"] == 20.0


def test_combined_block_carries_both_columns():
    names = [c for c, _b, _h in M.COMBINED_COLUMNS]
    assert names.index("Combined points left on bench") == names.index("Combined bench points") + 1
    assert M.base_column("Combined bench points") == B.BENCH
    assert M.base_column("Combined points left on bench") == B.LEFT


def _place(column, rank, key, value):
    return {"sheet": "team_week", "column": column, "end": "high", "rank": rank,
            "key": key, "label": key, "value": value}


def test_pre_split_snapshot_boards_move_once():
    old = {"meta": {"captured_at": "2026-10-20T18:21:55+00:00"}, "event_board": [
        _place("Combined bench points", 1, "team_week|shmuel256|2022|16", 167.96),
        _place("Combined Max PF", 1, "team_week|shmuel256|2022|16", 400.0)]}
    m = D.migrate_snapshot_bench_split(copy.deepcopy(old))
    cols = [e["column"] for e in m["event_board"]]
    assert cols == ["Combined points left on bench", "Combined Max PF"], cols
    assert m["meta"]["bench_points_split"] == "2026-10-25"
    # A stamped snapshot's "Combined bench points" is the new column: left alone.
    m["event_board"].append(_place("Combined bench points", 1, "team_week|A|2026|8", 250.0))
    assert D.migrate_snapshot_bench_split(copy.deepcopy(m)) == m


def test_new_snapshots_are_stamped():
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026], "PF": [100.0]})
    snap = D.build_snapshot(pd.DataFrame({"Player": ["p"], "Points": [1.0]}),
                            pd.DataFrame({"Team": ["A"], "PF": [100.0]}), ty,
                            pd.DataFrame({"Year": [2026], "Week": [1], "Team": ["A"]}))
    assert snap["meta"].get("bench_points_split") == "2026-10-25", snap["meta"]


def test_league_milestones_classify_the_new_columns():
    for c in (B.BENCH, B.LEFT):
        assert c in D.MAJOR_LEAGUE_STATS, c
    for c in ("Avg bench points", "Avg points left on bench"):
        assert D.NON_COUNTING_LEAGUE_STATS.get(c) == "average", c


def test_a_new_column_is_baselined_off_the_on_pace_list():
    prior = {"pace": {"teams": {"PF": {"A": "high:1"}}},
             "event_board": [_place("Combined bench points", 1, "team_week|A|2022|16", 160.0),
                             _place("Avg max PF", 1, "team_year|A|2022", 150.0)]}
    projs = [D.Projection("teams", "A", "PF", "high", 2, 8, 100.0),
             D.Projection("teams", "B", B.BENCH, "low", 1, 8, 50.0),
             D.Projection("league", "League", B.LEFT, "high", 2, 6, 30.0),
             # known column new to the on-pace list (a gate opening): still told
             D.Projection("teams", "C", "Avg max PF", "high", 1, 8, 150.0)]
    known = D.snapshot_columns(prior)
    changed = D.diff_pace(prior["pace"], projs, known)
    assert [(p.entity, p.column) for p in changed] == [("A", "PF"), ("C", "Avg max PF")], changed
    assert len(D.diff_pace(prior["pace"], projs)) == 4     # without known_columns: as before


# --- committed exports (skip until a build carries the columns) -------------

def _load(name):
    p = _EXPORTS / f"{name}.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _skip(reason: str) -> bool:
    print(f"  (skip: {reason})")
    return True


def _built_team_week():
    tw = _load("team_week")
    if tw is None or B.BENCH not in tw.columns or B.LEFT not in tw.columns:
        _skip("exports/team_week.csv has no bench columns yet")
        return None
    return tw


def test_team_week_matches_player_week_recount():
    tw, pw = _built_team_week(), _load("player_week")
    if tw is None or pw is None:
        return
    pw["Points"] = _num(pw["Points"]).fillna(0.0)
    keys = ["Team", "Year", "Week"]
    bench = pw[pw["Starter/Bench"] != "Starter"].groupby(keys)["Points"].sum()
    start = pw[pw["Starter/Bench"] == "Starter"].groupby(keys)["Points"].sum()
    t = tw.set_index(keys)
    bp, left, mx = _num(t[B.BENCH]), _num(t[B.LEFT]), _num(t["Max PF"])
    assert ((bp - bench.reindex(t.index).fillna(0.0)).abs() < 0.011).all()
    assert ((left - (mx - start.reindex(t.index).fillna(0.0))).abs() < 0.011).all()
    assert (left >= -0.005).all(), left.min()
    # The 12 bonus games: PF − starters = 5, and left on bench ignores it.
    gap = (_num(t["PF"]) - start.reindex(t.index)).round(2)
    bonus = gap == 5.0
    assert bonus.sum() >= 12, bonus.sum()
    assert ((left[bonus] - (mx[bonus] - _num(t["PF"])[bonus] + 5)).abs() < 0.011).all()


def test_most_bench_points_flags_the_weeks_max():
    tw = _built_team_week()
    if tw is None:
        return
    tw = tw.copy()
    tw["_b"] = _num(tw[B.BENCH])
    top = tw.groupby(["Year", "Week"])["_b"].transform("max")
    flag = tw["Most bench points?"].astype(str).str.lower().isin(["1", "true", "1.0"])
    assert (flag == ((tw["_b"] == top) & (top > 0))).all()


def test_combined_columns_add_the_two_teams():
    tw = _built_team_week()
    if tw is None:
        return
    idx = tw.set_index(["Team", "Year", "Week"])
    for comb, base in (("Combined bench points", B.BENCH), ("Combined points left on bench", B.LEFT)):
        win = tw[_num(tw[comb]).notna()]
        assert len(win) > 0, comb
        for _, r in win.iterrows():
            o = idx.loc[(r["Opponent"], r["Year"], r["Week"])]
            assert abs(float(r[comb]) - (float(r[base]) + float(o[base]))) < 0.011, (comb, r["Team"], r["Year"], r["Week"])


def test_rollups_equal_team_week_sums():
    tw = _built_team_week()
    if tw is None:
        return
    tw = pd.DataFrame({k: tw[k] for k in ("Team", "Year", "Week")}).assign(
        **{B.BENCH: _num(tw[B.BENCH]), B.LEFT: _num(tw[B.LEFT])})
    for sheet, keys in (("team_year", ["Team", "Year"]), ("team_all_time", ["Team"]),
                        ("league_week", ["Year", "Week"]), ("league_year", ["Year"])):
        df = _load(sheet)
        assert df is not None and B.BENCH in df.columns, sheet
        want = tw.groupby(keys)[[B.BENCH, B.LEFT]].agg(["sum", "mean"])
        got = df.set_index(keys)
        for k in want.index:
            g = got.loc[k]
            if str(g[B.BENCH]) == "N/A":
                continue                           # pre-season row
            for c in (B.BENCH, B.LEFT):
                assert abs(float(g[c]) - want.at[k, (c, "sum")]) < 0.011, (sheet, k, c)
                if sheet != "league_week":
                    assert abs(float(g[B.AVG_OF[c]]) - want.at[k, (c, "mean")]) < 0.011, (sheet, k, c)
    la = _load("league_all_time")
    assert abs(float(la.at[0, B.BENCH]) - tw[B.BENCH].sum()) < 0.05
    assert abs(float(la.at[0, "Avg points left on bench"]) - tw[B.LEFT].mean()) < 0.011


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
