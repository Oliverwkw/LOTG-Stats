"""Team score swings and lineup correlation (lotg_support.team_variance).

Lineup swing / riskiness / stacking / matchup swing, the stack and same-game
pair counts and boom / bust weeks on team_week; their rollups and the underdog
split on team_year / team_all_time / league_year / league_all_time; plus the
league data the fixed constants came from and AceMatthew's two league-chat
charts ("scoring level vs consistency"), which the year columns reproduce.

Run: python tests/test_team_variance.py
"""
from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import team_variance as TV  # noqa: E402

_EXPORTS = _ROOT / "exports"
_GAMES = _ROOT / ".cache" / "nfldata_games.csv"


def _games():
    return pd.DataFrame([
        {"season": 2024, "week": 1, "game_type": "REG", "home_team": "KC", "away_team": "BAL"},
        {"season": 2024, "week": 1, "game_type": "REG", "home_team": "BUF", "away_team": "MIA"},
        {"season": 2024, "week": 1, "game_type": "POST", "home_team": "KC", "away_team": "BUF"},
    ])


def _row(team, week, player, pos, nfl, pts, starter=True, year=2024, **kw):
    return {"Team": team, "Year": year, "Week": week, "Player": player, "Position": pos,
            "NFL team": nfl, "Points": pts, "Starter/Bench": "Starter" if starter else "Bench",
            "Bye?": kw.get("bye", False), "Injury?": kw.get("inj", False)}


def _two_team_week():
    pw = pd.DataFrame([
        _row("A", 1, "qb", "QB", "KC", 25.0), _row("A", 1, "wr", "WR", "KC", 20.0),
        _row("A", 1, "te", "TE", "KC", 10.0), _row("A", 1, "rb", "RB", "MIA", 12.0),
        _row("A", 1, "bench", "WR", "KC", 3.0, starter=False),
        _row("B", 1, "qb2", "QB", "BAL", 18.0), _row("B", 1, "wr2", "WR", "BUF", 9.0),
        _row("B", 1, "rb2", "RB", "NYJ", 7.0),
    ])
    tw = pd.DataFrame([
        {"Team": "A", "Year": 2024, "Week": 1, "Opponent": "B", "Enhanced Projection": 70.0,
         "Pre-week Win % (Enhanced Projection)": 0.62, "Win?": True},
        {"Team": "B", "Year": 2024, "Week": 1, "Opponent": "A", "Enhanced Projection": 40.0,
         "Pre-week Win % (Enhanced Projection)": 0.38, "Win?": False},
    ])
    return pw, tw


def test_relation_and_rho():
    assert TV.relation("KC", "KC", "BAL") == "same"
    assert TV.relation("KC", "BAL", "BAL") == "opp"
    assert TV.relation("KC", "BUF", "BAL") is None
    assert TV.relation("", "KC", None) is None
    assert TV.pair_rho("same", "WR", "QB") == TV.PAIR_RHO[("same", "QB", "WR")]   # order-free
    assert TV.pair_rho(None, "QB", "WR") == 0.0
    assert TV.pair_rho("opp", "QB", "QB") == 0.18


def test_nfl_opponents_regular_season_only():
    o = TV.nfl_opponents(_games())
    assert o[(2024, 1, "KC")] == "BAL" and o[(2024, 1, "BAL")] == "KC"
    assert o[(2024, 1, "BUF")] == "MIA"           # the POST row did not overwrite it


def test_player_sd_is_point_in_time_and_shrunk():
    """Week 3's spread reads weeks 1-2 only; a bye / injured week is not a
    played week; no history = the position's spread."""
    pw = pd.DataFrame([
        _row("A", 1, "x", "WR", "KC", 10.0), _row("A", 2, "x", "WR", "KC", 30.0),
        _row("A", 3, "x", "WR", "KC", 99.0), _row("A", 4, "x", "WR", "KC", 0.0, bye=True),
        _row("A", 5, "x", "WR", "KC", 20.0),
    ])
    sd = TV.player_sd(pw)
    assert abs(sd.iloc[0] - TV.POS_SD["WR"]) < 1e-9          # week 1: no history
    assert abs(sd.iloc[1] - TV.POS_SD["WR"]) < 1e-9          # one played week: no SD yet
    s2 = np.var([10.0, 30.0], ddof=1)
    want3 = math.sqrt((2 * s2 + TV.SHRINK * TV.POS_SD["WR"] ** 2) / (2 + TV.SHRINK))
    assert abs(sd.iloc[2] - want3) < 1e-9                    # the 99 is not seen yet
    s3 = np.var([10.0, 30.0, 99.0], ddof=1)
    want4 = math.sqrt((3 * s3 + TV.SHRINK * TV.POS_SD["WR"] ** 2) / (3 + TV.SHRINK))
    assert abs(sd.iloc[3] - want4) < 1e-9
    assert abs(sd.iloc[4] - want4) < 1e-9                    # the bye added nothing


def test_week_columns_by_hand():
    pw, tw = _two_team_week()
    wc = TV.week_columns(pw, tw, _games()).set_index("Team")
    sd = {r: TV.POS_SD[p] for r, p in (("qb", "QB"), ("wr", "WR"), ("te", "TE"), ("rb", "RB"))}
    ind = sum(v * v for v in sd.values())
    cov = (TV.PAIR_RHO[("same", "QB", "WR")] * sd["qb"] * sd["wr"]
           + TV.PAIR_RHO[("same", "QB", "TE")] * sd["qb"] * sd["te"]
           + TV.PAIR_RHO[("same", "TE", "WR")] * sd["wr"] * sd["te"])   # rb (MIA) pairs with none
    a = wc.loc["A"]
    assert abs(a["Lineup swing"] - round(math.sqrt(ind + 2 * cov), 2)) < 1e-9
    assert abs(a["Swing added by stacking"] - round(math.sqrt(ind + 2 * cov) - math.sqrt(ind), 2)) < 0.011
    assert a["QB-receiver stacks"] == 2                      # WR + TE, the RB elsewhere
    assert a["Starter pairs in the same NFL game"] == 3      # qb-wr, qb-te, wr-te
    # A's KC trio against B's BAL QB (KC v BAL) and A's MIA RB against B's BUF WR
    assert a["Pairs sharing an NFL game with opponent"] == 4
    assert wc.loc["B", "Pairs sharing an NFL game with opponent"] == 4
    assert wc.loc["B", "QB-receiver stacks"] == 0
    assert abs(wc.loc["A", "Matchup swing"] - wc.loc["B", "Matchup swing"]) < 1e-9
    # vs league: the two ratios average 1
    assert abs(wc["Lineup swing vs league"].mean() - 1) < 1e-3
    # riskiness: the two log-deviations of swing net of 0.5 x projection cancel
    lr = np.log(wc["Lineup riskiness"].astype(float))
    assert abs(lr.sum()) < 1e-3


def test_boom_bust_vs_week_median():
    rows = [_row(t, 1, f"p{t}", "WR", "KC", pts) for t, pts in
            (("A", 140.0), ("B", 100.0), ("C", 79.0), ("D", 121.0))]
    pw = pd.DataFrame(rows)
    tw = pd.DataFrame([{"Team": t, "Year": 2024, "Week": 1, "Opponent": o} for t, o in
                       (("A", "B"), ("B", "A"), ("C", "D"), ("D", "C"))])
    wc = TV.week_columns(pw, tw, None).set_index("Team")       # median 110.5: boom >= 132.6, bust <= 88.4
    assert wc.loc["A", "Boom week?"] == True and wc.loc["D", "Boom week?"] == False   # noqa: E712
    assert wc.loc["C", "Bust week?"] == True and wc.loc["B", "Bust week?"] == False   # noqa: E712


def test_rollup_underdog_split_and_first_weeks():
    """Underdog = pre-week Win % under 50%; risky = riskiness >= 1."""
    wc = pd.DataFrame({
        "Team": ["A"] * 8, "Year": [2024] * 8, "Week": list(range(1, 9)),
        "Lineup swing": [24.0] * 8, "Lineup swing vs league": [1.0] * 8,
        "Lineup riskiness": [1.1, 1.1, 0.9, 0.9, 1.2, 0.8, 1.0, 1.0],
        "Swing added by stacking": [0.5] * 8, "Matchup swing": [34.0] * 8,
        "QB-receiver stacks": [1] * 8, "Starter pairs in the same NFL game": [2] * 8,
        "Pairs sharing an NFL game with opponent": [3] * 8,
        "Boom week?": [True, False, False, False, False, False, False, True],
        "Bust week?": [False] * 7 + [True],
        "_pts": [100.0, 120.0, 140.0, 160.0, 130.0, 150.0, 90.0, 200.0],
    })
    tw = pd.DataFrame({"Team": ["A"] * 8, "Year": ["2024"] * 8, "Week": [str(w) for w in range(1, 9)],
                       "Pre-week Win % (Enhanced Projection)": [0.4, 0.3, 0.45, 0.2, 0.6, 0.7, None, 0.5],
                       "Win?": [True, False, True, False, True, False, True, True]})
    r = TV.rollup(wc, tw, ["Team", "Year"], TV.TEAM_YEAR_COLUMNS).iloc[0]
    assert r[TV.HV_WIN] == 0.5          # weeks 1 (W) and 2 (L)
    assert r[TV.LV_WIN] == 0.5          # weeks 3 (W) and 4 (L)
    assert abs(r["Avg lineup riskiness as underdog"] - 1.0) < 1e-9
    assert abs(r["Avg lineup riskiness as favorite"] - 1.0) < 1e-9   # weeks 5, 6, 8 (0.5 = favorite)
    assert r["Boom week %"] == 0.25 and r["Bust week %"] == 0.125
    first = [100.0, 120.0, 140.0, 160.0, 130.0, 150.0]
    assert r["Avg weekly score (first 6 weeks)"] == round(np.mean(first), 2)
    assert r["Weekly score swing (first 6 weeks)"] == round(np.std(first, ddof=1), 2)
    # to this point = weeks 1..8 (the latest season's last week) = the whole season here
    assert r["Weekly score swing % (to this point)"] == r["Weekly score swing %"]
    assert r["Scoring style (to this point)"] is not None
    assert r["Weekly score swing % (first 6 weeks)"] == round(np.std(first, ddof=1) / np.mean(first), 4)
    allp = wc["_pts"]
    assert r["Weekly score swing %"] == round(allp.std(ddof=1) / allp.mean(), 4)
    assert r["QB-receiver stacks"] == 8
    lg = TV.rollup(wc, tw, [], TV.LEAGUE_COLUMNS).iloc[0]
    assert lg[TV.HV_N] == 2 and lg[TV.LV_N] == 2
    # Under six weeks: the first-6 pair is N/A, not a 5-week figure
    short = TV.rollup(wc[wc["Week"] <= 5], tw, ["Team", "Year"], TV.TEAM_YEAR_COLUMNS).iloc[0]
    assert pd.isna(short["Avg weekly score (first 6 weeks)"])


def test_attach_is_dtype_blind_and_leaves_na():
    frame = pd.DataFrame({"Team": ["A", "B"], "Year": ["2024", "2024"], "Week": ["1", "1"]})
    cols = pd.DataFrame({"Team": ["A"], "Year": [2024], "Week": [1.0], "Lineup swing": [24.5],
                         "Boom week?": [True]})
    out = TV.attach(frame, cols, ["Team", "Year", "Week"], ["Lineup swing", "Boom week?"])
    assert out.loc[0, "Lineup swing"] == 24.5 and out.loc[0, "Boom week?"] is True
    assert pd.isna(out.loc[1, "Lineup swing"]) and out.loc[1, "Boom week?"] is None
    one = TV.attach(pd.DataFrame({"x": [1, 2]}), pd.DataFrame({"Underdog weeks (risky lineup)": [5]}), [],
                    ["Underdog weeks (risky lineup)"])
    assert list(one["Underdog weeks (risky lineup)"]) == [5, 5]


def test_names_are_one_topic_block():
    import importlib
    sys.path.insert(0, str(_ROOT / "src"))
    lotg = importlib.import_module("lotg")
    for c in TV.ALL_COLUMNS:
        assert lotg._col_topic(c) == "Variance", c
        assert lotg._preserve_na(c), c
    from lotg_support.number_format import col_number_format as fmt
    assert fmt("QB-receiver stacks") == "0" and fmt("Underdog weeks (safe lineup)") == "0"
    assert fmt("Boom week %") == "0.00%" and fmt("Weekly score swing % (first 6 weeks)") == "0.00%"
    assert fmt("Underdog win % (risky lineup)") == "0.00%"


# ---------------------------------------------------------------------------
# Committed data (skips cleanly without exports/; completed seasons only)
# ---------------------------------------------------------------------------
def _exports():
    if not (_EXPORTS / "player_week.csv").exists() or not (_EXPORTS / "team_week.csv").exists():
        return None, None
    pw = pd.read_csv(_EXPORTS / "player_week.csv", low_memory=False)
    tw = pd.read_csv(_EXPORTS / "team_week.csv", low_memory=False)
    return pw, tw


def test_pair_rho_still_fits_the_league():
    """Refit every PAIR_RHO entry with 1,000+ pairs from completed seasons."""
    pw, _ = _exports()
    if pw is None or not _GAMES.exists():
        print("exports/ or the schedule cache absent — data checks not run")
        return
    opp = TV.nfl_opponents(pd.read_csv(_GAMES))
    p = pw[(pw["Year"] < pw["Year"].max()) & pw["Points"].notna()].copy()
    for c in ("Bye?", "Injury?"):
        p = p[~p[c].map(TV._flag)]
    g = p.groupby(["Player", "Year"])["Points"]
    p = p.assign(r=p["Points"] - g.transform("mean"), n=g.transform("size"))
    p = p[p["n"] >= 6]
    p["t"] = p["NFL team"].map(TV._team)
    pairs = {}
    for (y, w), d in p.groupby(["Year", "Week"]):
        recs = list(zip(d["Position"], d["t"], d["r"]))
        for (pa, ta, ra), (pb, tb, rb) in itertools.combinations(recs, 2):
            rel = TV.relation(ta, tb, opp.get((int(y), int(w), ta)))
            if rel:
                key = (rel,) + tuple(sorted((pa, pb)))
                pairs.setdefault(key, []).append((ra, rb))
    checked = 0
    for key, v in pairs.items():
        if len(v) < 1000:
            continue
        a = np.array(v)
        rho = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
        assert abs(rho - TV.PAIR_RHO.get(key, 0.0)) <= 0.08, (key, round(rho, 3), TV.PAIR_RHO.get(key))
        checked += 1
    assert checked >= 10, checked


def test_reproduces_acematthews_charts():
    """The full-season chart (completed seasons): median swing 17.0%, the
    average-vs-swing correlation -0.41; the first-6-games chart (every
    team-season with 6 weeks, 2026 included): median 15.6%, r = -0.22, and his
    labelled points. Assert only seasons completed when the charts were drawn."""
    pw, tw = _exports()
    if pw is None:
        print("exports/ absent — data checks not run")
        return
    wc = TV.week_columns(pw, tw, pd.read_csv(_GAMES) if _GAMES.exists() else None)
    ty = TV.rollup(wc, tw, ["Team", "Year"], TV.TEAM_YEAR_COLUMNS).set_index(["Team", "Year"])
    done = ty[ty.index.get_level_values("Year") <= 2025]
    mean = wc.groupby(["Team", "Year"])["_pts"].mean().reindex(done.index)
    assert abs(100 * done["Weekly score swing %"].median() - 17.0) < 0.15
    assert abs(np.corrcoef(mean, done["Weekly score swing %"])[0, 1] - (-0.41)) < 0.01
    six = ty[ty.index.get_level_values("Year") <= 2026].dropna(subset=["Avg weekly score (first 6 weeks)"])
    assert len(six) >= 56
    assert abs(six["Avg weekly score (first 6 weeks)"].median() - 143.9) < 0.15
    assert abs(100 * six["Weekly score swing % (first 6 weeks)"].median() - 15.6) < 0.15
    for (team, year), (avg, pct) in {("AceMatthew", 2021): (131.8, 30.0), ("stevenb123", 2023): (114.5, 4.8),
                                     ("JacobRosenzweig", 2022): (133.8, 7.5)}.items():
        r = ty.loc[(team, year)]
        assert abs(r["Avg weekly score (first 6 weeks)"] - avg) < 0.6, (team, year)
        assert abs(100 * r["Weekly score swing % (first 6 weeks)"] - pct) < 0.25, (team, year)
    assert abs(100 * ty.loc[("BROsenzweig", 2021), "Weekly score swing %"] - 31.7) < 0.1
    assert ty.loc[("BROsenzweig", 2021), "Scoring style"] == "Low-scoring, up-and-down"
    assert ty.loc[("shmuel256", 2026), "Scoring style (to this point)"] == "High-scoring, steady"


def test_committed_sheets_match_recompute():
    """Where the committed sheets carry the columns, they reproduce from
    player_week (completed seasons)."""
    pw, tw = _exports()
    if pw is None or "Lineup swing" not in tw.columns:
        print("committed exports predate the team-variance columns — check not run")
        return
    wc = TV.week_columns(pw, tw, pd.read_csv(_GAMES) if _GAMES.exists() else None)
    done = wc[wc["Year"] < wc["Year"].max()]
    m = done.merge(tw, on=["Team", "Year", "Week"], suffixes=("", "_sheet"))
    assert len(m) == len(done)
    for c in ("Lineup swing", "Matchup swing", "QB-receiver stacks", "Pairs sharing an NFL game with opponent"):
        a, b = pd.to_numeric(m[c], errors="coerce"), pd.to_numeric(m[f"{c}_sheet"], errors="coerce")
        assert ((a - b).abs() < 0.011).mean() > 0.99, c


def test_fast_swing_table():
    if not (_EXPORTS / "player_week.csv").exists():
        print("exports/ absent — check not run")
        return
    from lotg_support import fast
    t, notes = fast.swing_table(6)
    assert {"Avg score", "Weekly score swing %", "Quadrant"}.issubset(t.columns)
    assert any("r = -0.2" in n for n in notes), notes
    full, notes = fast.swing_table()
    assert any("r = -0.4" in n for n in notes), notes


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
