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


def _dnp_case():
    """A small player_week, its gsis ids, an appearance log and a schedule:
    BUF / CIN 2022 wk 17 is the struck Hamlin game, LV 2026 wk 4 played,
    NYJ 2026 wk 4 on a bye, MIA 2026 wk 4 played but its stats not in yet."""
    pw = pd.DataFrame([
        (2026, 4, "LV", 0.0),    # 0 Mendoza: no stat line, no snap, LV played  -> True
        (2026, 4, "LV", 0.0),    # 1 Cousins: appeared                          -> False
        (2026, 4, "LV", 6.4),    # 2 scored points (a stat line the log missed) -> False
        (2026, 4, "NYJ", 0.0),   # 3 bye                                        -> False
        (2026, 4, "MIA", 0.0),   # 4 MIA's stats have not landed                -> False
        (2022, 17, "CIN", 0.0),  # 5 Ja'Marr Chase, the struck game [per user] -> False
        (2026, 4, "LV", 0.0),    # 6 no gsis id                                 -> False
        (2026, 4, "", 0.0),      # 7 no NFL team (free agent)                   -> False
    ], columns=["Year", "Week", "NFL team", "Points"])
    gsis = pd.Series(["00-M", "00-C", "00-X", "00-J", "00-T", "00-JC", None, "00-F"])
    log = pd.DataFrame([("00-C", 2026, 4, "LV"), ("00-O", 2026, 4, "LV"),
                        ("00-B", 2022, 17, "BUF"), ("00-H", 2022, 17, "CIN")],
                       columns=["gsis_id", "season", "week", "team"])
    games = pd.DataFrame([
        ("2026_04_KC_LV", 2026, "REG", 4, "KC", "LV", np.nan, np.nan),   # score not in the cached schedule yet
        ("2026_04_MIA_BUF", 2026, "REG", 4, "MIA", "BUF", 20.0, 27.0),
        ("2022_17_BUF_CIN", 2022, "REG", 17, "BUF", "CIN", np.nan, np.nan),
    ], columns=["game_id", "season", "game_type", "week", "away_team", "home_team", "away_score", "home_score"])
    return pw, gsis, log, games


def test_did_not_play_rule():
    # [per user, 2026-10-07] no stat line and no offensive snap in a game the
    # team played projects 0 — but never the voided Hamlin game.
    pw, gsis, log, games = _dnp_case()
    assert P.did_not_play(pw, gsis, log, games).tolist() == [True, False, False, False, False, False, False, False]
    # nothing to judge against -> nothing flagged
    assert not P.did_not_play(pw, gsis, log.iloc[0:0], games).any()
    assert not P.did_not_play(pw, gsis, log, games.iloc[0:0]).any()
    # an LV game nflverse already marks as struck would not count either
    struck = games.assign(game_id=games["game_id"].where(games["game_id"] != "2026_04_KC_LV", "2022_17_BUF_CIN"))
    assert not P.did_not_play(pw, gsis, log, struck).any()


def test_qb_cameo_rule():
    # [per user, 2026-10-10] a QB with <= 10% of the snaps and under 1 point did
    # not really play — unless he was his team's QB going in (an early injury
    # is a bust). QBs only; a team's first game reads his last game of last season.
    pw = pd.DataFrame([
        (2024, 8, "CIN", "QB", 0.0),     # 0 Browning: 3 kneels, Burrow had wk 7       -> True
        (2022, 14, "ARI", "QB", 0.66),   # 1 Murray: hurt on the first drive, QB in wk 12 -> False
        (2024, 8, "CIN", "QB", 2.6),     # 2 a cameo that scored                        -> False
        (2024, 8, "CIN", "RB", 0.0),     # 3 not a QB                                   -> False
        (2024, 8, "CIN", "QB", 0.0),     # 4 15% of the snaps: not a cameo              -> False
        (2023, 1, "NYJ", "QB", 0.0),     # 5 Rodgers: team's first game, 100% last year -> False
        (2025, 1, "NYG", "QB", 0.1),     # 6 a rookie with no history                   -> True
    ], columns=["Year", "Week", "NFL team", "Position", "Points"])
    gsis = pd.Series(["B", "M", "X", "R", "Y", "A", "K"])
    snaps = pd.DataFrame([
        ("Q", 2024, 7, "CIN", 1.00), ("B", 2024, 8, "CIN", 0.05), ("Q", 2024, 8, "CIN", 0.95),
        ("X", 2024, 8, "CIN", 0.08), ("R", 2024, 8, "CIN", 0.03), ("Y", 2024, 8, "CIN", 0.15),
        ("M", 2022, 12, "ARI", 1.00), ("M", 2022, 14, "ARI", 0.04),
        ("A", 2022, 18, "GB", 1.00), ("A", 2023, 1, "NYJ", 0.07),
        ("K", 2025, 1, "NYG", 0.02),
    ], columns=["gsis_id", "season", "week", "team", "offense_pct"])
    log = snaps.rename(columns={"offense_pct": "_"})[["gsis_id", "season", "week", "team"]]
    games = pd.DataFrame([
        ("2024_08_PHI_CIN", 2024, "REG", 8, "PHI", "CIN"), ("2022_14_ARI_NE", 2022, "REG", 14, "NE", "ARI"),
        ("2023_01_BUF_NYJ", 2023, "REG", 1, "BUF", "NYJ"), ("2025_01_WAS_NYG", 2025, "REG", 1, "NYG", "WAS"),
    ], columns=["game_id", "season", "game_type", "week", "away_team", "home_team"])
    got = P.did_not_play(pw, gsis, log, games, snaps=snaps).tolist()
    assert got == [True, False, False, False, False, False, True], got
    # without snap shares only the no-appearance half runs: nothing here
    assert not P.did_not_play(pw, gsis, log, games).any()


def test_exports_did_not_play_projects_zero():
    # On a build with the rule (its log line says so): Desmond Ridder's 2022
    # weeks 1-13 (no snap behind Mariota) and Jake Browning's 2024 weeks 1-8
    # (wk 8: a 3-kneel QB cameo) project 0 under all three; Kyler Murray's 2022
    # wk 14 (hurt on the first drive) does not, nor does Ja'Marr Chase's start in
    # the voided 2022 wk 17 game [per user].
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    log = _ROOT / "exports" / "raw" / "build_debug.log"
    if not log.exists() or "did-not-play weeks zeroed" not in log.read_text(errors="ignore"):
        return _skip("exports predate the did-not-play rule")
    pw = _data()
    if pw is None:
        return _skip("exports predate the projection columns")
    yr, wk = Q.numeric(pw, "Year"), Q.numeric(pw, "Week")
    row = lambda n, y: (pw["Player"] == n) & (yr == y)
    for x in P.NAMES:
        v = Q.numeric(pw, P.proj_col(x))
        assert (v[row("Desmond Ridder", 2022) & wk.between(1, 13)] == 0).all(), x
        assert (v[row("Jake Browning", 2024) & wk.between(1, 8)] == 0).all(), x
        assert (v[row("Kyler Murray", 2022) & (wk == 14)] > 0).all(), x
        assert (v[row("Ja'Marr Chase", 2022) & (wk == 17)] > 0).all(), x


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


def test_exports_sleeper_boldness():
    # Boldness judged on the Sleeper Projection [per user, 2026-10-07]: never
    # negative, starters only, and the lineup version never negative.
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    pw = Q.load_sheet("player_week")
    if "Sleeper Boldness" not in pw.columns:
        return _skip("exports predate Sleeper Boldness")
    v = Q.numeric(pw, "Sleeper Boldness")
    bench = pw["Starter/Bench"].astype(str) != "Starter"
    assert (v.dropna() >= 0).all() and v[bench].isna().all()
    tw = Q.load_sheet("team_week")
    # the Combined projection columns keep the matchup convention: the loser's row
    # points at the winner's ("winner"), never blank (branch run 689 blanked it)
    cmb = tw["Combined Enhanced Projection"].astype(str)
    assert (cmb.isin(["winner"]) | Q.numeric(tw, "Combined Enhanced Projection").notna()).mean() > 0.99
    lb = Q.numeric(tw, "Sleeper Lineup Boldness")
    assert (lb.dropna() >= 0).all() and lb.notna().mean() > 0.9


def test_exports_claude_hardship():
    # Hardship (Claude Projections) [per user, 2026-10-07]: never negative, the
    # starter-adjusted one never above it, a loss flip only on a loss and a win
    # flip only on a win — and it is NOT zero wherever Hardship is not (the
    # out-week trap: a projection read after the known-out zeroing is 0).
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    tw = Q.load_sheet("team_week")
    cp = " (Claude Projections)"
    if "Hardship" + cp not in tw.columns:
        return _skip("exports predate Hardship (Claude Projections)")
    h, sa = Q.numeric(tw, "Hardship" + cp), Q.numeric(tw, "Starter-adjusted Hardship" + cp)
    assert (h >= 0).all() and (sa <= h + 0.01).all()
    old = Q.numeric(tw, "Hardship")
    assert ((old > 5) & (h == 0)).mean() < 0.02, "Claude hardship reads 0 where Hardship is not"
    won = tw["Win?"].astype(str).str.lower().isin(("true", "1", "1.0"))
    flag = lambda c: tw[c + cp].astype(str).str.lower().isin(("true", "1", "1.0"))
    assert not (flag("Loss from hardship?") & won).any()
    assert not (flag("Win from hardship (2-sided)?") & ~won).any()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
