"""Guards for `lotg_support.projections` — the Sleeper / Claude / Enhanced
Projection columns [per user, 2026-10-07].

The synthetic checks pin the rules: league scoring of projected stats, a
Sleeper row with no projected points is NO projection (never 0), a known-out
player projects 0 under all three, Sleeper falls back to the weakened model then
Claude, the team projection carries the semifinal bonus, one player award a week
with an alphabetical tie-break (team ties all win), and the rollups. The data
checks run over the committed exports once a build has written the columns:
completed seasons only.

Run: python tests/test_projections.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from lotg_support import projections as P  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def test_column_names():
    assert P.WEEK_COLUMNS[:6] == ("Sleeper Projection", "Points above Sleeper Projection",
                                  "Overachiever (Sleeper Projection)", "Underachiever (Sleeper Projection)",
                                  "Overachiever (Sleeper Projection) streak",
                                  "Underachiever (Sleeper Projection) streak")
    assert len(P.WEEK_COLUMNS) == 18 and len(P.LEAGUE_WEEK_COLUMNS) == 6
    assert "Times as Overachiever (Enhanced Projection)" in P.rollup_columns("Times as ")
    assert "Avg Points above Claude Projection" in P.rollup_columns(None)
    assert not any("achiever" in c for c in P.rollup_columns(None))     # league: totals only


def test_ids_match_however_the_table_was_loaded():
    # The build reads the DynastyProcess id table with numeric dtypes: 4837248
    # comes back as "4837248.0". Unnormalised, ESPN / FantasyPros never matched
    # a player (branch run 683: outside-source coverage 77% instead of 99%, and
    # the model fit on near-duplicate columns blew up — Justin Fields 2024 wk 12
    # projected 23.9 as a backup).
    num = pd.Series([4837248.0, np.nan, 28013.0])
    assert P._id_str(num).tolist()[0] == "4837248" and pd.isna(P._id_str(num).tolist()[1])
    assert P._id_str(num.astype(str)).fillna("-").tolist() == P._id_str(num).fillna("-").tolist()


def test_scoring_uses_the_league_table():
    stats = pd.DataFrame([{"pass_yd": 250, "pass_td": 2, "rec": 5, "rec_yd": 60, "kr_yd": 99}])
    table = {"pass_yd": 0.04, "pass_td": 4, "rec": 1, "rec_yd": 0.1}
    assert abs(P.score_stats(stats, table).iloc[0] - (10 + 8 + 5 + 6)) < 1e-9


def _frame(rows):
    return pd.DataFrame(rows, columns=["Year", "Week", "Team", "Player", "Starter/Bench", "Points",
                                       "Sleeper Projection", "Claude Projection", "Enhanced Projection"])


def test_player_awards_one_winner_alphabetical():
    pw = _frame([(2025, 1, "A", "Zed", "Starter", 30.0, 10.0, 10.0, 10.0),   # +20
                 (2025, 1, "B", "Amy", "Starter", 25.0, 5.0, 5.0, 5.0),      # +20 (tie, alphabetical wins)
                 (2025, 1, "B", "Bob", "Starter", 2.0, 15.0, 15.0, 15.0),    # −13
                 (2025, 1, "B", "Out", "Starter", 0.0, 0.0, 0.0, 0.0),       # known out: never Underachiever
                 (2025, 1, "A", "Ben", "Bench", 40.0, 5.0, 5.0, 5.0)])       # bench: not eligible
    out = pd.Series([False, False, False, True, False])
    aw = P.player_week_awards(pw, out)
    for x in P.NAMES:
        assert aw[P.over_col(x)].tolist() == [0, 1, 0, 0, 0]
        assert aw[P.under_col(x)].tolist() == [0, 0, 1, 0, 0]


def test_team_projection_carries_the_semifinal_bonus():
    pw = _frame([(2025, 15, "A", "p1", "Starter", 20.0, 15.0, 12.0, 14.0),
                 (2025, 15, "A", "p2", "Starter", 10.0, 10.0, 10.0, 10.0),
                 (2025, 15, "A", "p3", "Bench", 30.0, 9.0, 9.0, 9.0)])
    tw = pd.DataFrame([{"Team": "A", "Year": 2025, "Week": 15, "PF": 35.0}])   # 30 + the +5 bonus
    t = P.team_week_projection(tw, pw)
    assert t.loc[0, "Enhanced Projection"] == 24.0 + 5.0          # starters + bonus, bench ignored
    assert t.loc[0, "Points above Enhanced Projection"] == 6.0     # the bonus is never "above"
    tie = pd.DataFrame({"Team": ["A", "B", "C"], "Year": 2025, "Week": 1,
                        **{P.above_col(x): [5.0, 5.0, -3.0] for x in P.NAMES}})
    aw = P.team_week_awards(tie)
    assert aw[P.over_col("Enhanced")].tolist() == [1, 1, 0] and aw[P.under_col("Enhanced")].tolist() == [0, 0, 1]


def test_rollup_sums_averages_and_counts():
    f = pd.DataFrame({"Team": ["A", "A"], "Year": [2025, 2025],
                      **{P.proj_col(x): [10.0, 20.0] for x in P.NAMES},
                      **{P.above_col(x): [5.0, -1.0] for x in P.NAMES},
                      **{P.over_col(x): [1, 0] for x in P.NAMES}, **{P.under_col(x): [0, 1] for x in P.NAMES}})
    r = P.rollup(f, ["Team", "Year"], "Times ").iloc[0]
    assert r["Enhanced Projection"] == 30.0 and r["Avg Enhanced Projection"] == 15.0
    assert r["Points above Sleeper Projection"] == 4.0 and r["Avg Points above Sleeper Projection"] == 2.0
    assert r["Times Overachiever (Claude Projection)"] == 1 and r["Times Underachiever (Claude Projection)"] == 1


def test_upset_and_opponent_gap():
    tw = pd.DataFrame({"Team": ["A", "B", "C", "D"], "Opponent": ["B", "A", "D", "C"], "Year": 2025, "Week": 1,
                       "Win?": [True, False, True, False],
                       **{P.proj_col(x): [100.0, 110.0, 100.0, 108.0] for x in P.NAMES}})
    g = P.opponent_gaps(tw)
    assert g[P.opp_gap_col("Enhanced")].tolist() == [-10.0, 10.0, -8.0, 8.0]
    # A won 10 behind (an upset); C won only 8 behind (under the 9-point bar)
    assert g["UPST"].tolist() == [1.0, 0.0, 0.0, 0.0]


def test_startsit_miss_uses_the_same_reference():
    pw = pd.DataFrame({"Player ID": ["s", "b"], "Year": 2025, "Week": 3, "Position": ["WR", "WR"],
                       "Starter/Bench": ["Starter", "Bench"], "Reference player ID": ["b", "s"],
                       **{P.proj_col(x): [12.0, 15.0] for x in P.NAMES}})
    m = P.startsit_miss(pw, lambda y, p: 1.0)
    # the starter's best bench option was projected 3 more; the bench player 3 more than his starter
    assert m[P.startsit_col("Enhanced")].tolist() == [3.0, 3.0]
    assert m[P.startsit_col("Claude", True)].tolist() == [3.0, 3.0]


# --------------------------------------------------------------------------- #
def _data():
    pw = Q.load_sheet("player_week")
    if "Enhanced Projection" not in pw.columns:
        return None
    done = set(Q.completed_seasons())
    return pw[Q.numeric(pw, "Year").isin(done)]


def test_exports_projection_accuracy():
    # Enhanced is the best broad-use projection: on completed seasons' starters it
    # must beat the Claude projection on RMSE and stay unbiased (2020-25 at build
    # time: Enhanced 8.01 / 0.00, Claude 8.29 / −1.27).
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    pw = _data()
    if pw is None:
        return _skip("exports predate the projection columns")
    st = pw[pw["Starter/Bench"].astype(str) == "Starter"]
    pts = Q.numeric(st, "Points")
    rmse = {x: float(np.sqrt(((Q.numeric(st, P.proj_col(x)) - pts) ** 2).mean())) for x in P.NAMES}
    bias = float((Q.numeric(st, P.proj_col("Enhanced")) - pts).mean())
    print(f"  starters RMSE {({k: round(v, 3) for k, v in rmse.items()})}, Enhanced bias {bias:+.2f}")
    assert rmse["Enhanced"] < rmse["Claude"] and rmse["Enhanced"] < 8.2
    # and it must clearly beat Sleeper alone (8.006 v 8.103 when every source
    # joins; a broken source join left only 8.058 v 8.103)
    assert rmse["Sleeper"] - rmse["Enhanced"] > 0.06, rmse
    assert abs(bias) < 0.3


def test_exports_rules_hold():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    pw = _data()
    if pw is None:
        return _skip("exports predate the projection columns")
    flag = pd.Series(False, index=pw.index)
    for c in ("Bye?", "Injury?", "Suspension?"):
        if c in pw.columns:
            flag = flag | pw[c].astype(str).str.lower().isin(("true", "1", "1.0"))
    out = flag & (Q.numeric(pw, "Points").fillna(0) == 0)
    for x in P.NAMES:
        v = Q.numeric(pw, P.proj_col(x))
        assert (v[out] == 0).all(), (x, "a known-out week must project 0")
        assert v.notna().mean() > 0.99, (x, "coverage")
        diff = Q.numeric(pw, "Points") - v
        assert ((Q.numeric(pw, P.above_col(x)) - diff).abs().fillna(0) < 0.011).all()
        # exactly one Overachiever per week among starters
        n = pw.assign(a=Q.numeric(pw, P.over_col(x)).fillna(0)).groupby(["Year", "Week"]).a.sum()
        assert (n == 1).all(), (x, n[n != 1].head())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
