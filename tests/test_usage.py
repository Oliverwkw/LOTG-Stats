"""Usage / opportunity and xFP (lotg_support.usage).

Checks:
* xFP is rebuilt from ffopportunity's expected components with the league's
  own scoring table: with PPR settings it reproduces ffopportunity's own total,
  the TE premium lands on TEs only, and a scoring key with no expectation
  (fumbles) is left out;
* red-zone opportunities count targets + carries inside the 20 and nothing
  else (no two-point tries, no penalty-nullified plays, no sacks, no playoffs);
* the per-season usage frame bridges snap counts PFR -> GSIS, drops
  ffopportunity's postseason weeks, and reads a played week with no target
  row as a 0 share;
* attach() blanks a week he did not play, gives 0 xFP to a snaps-only week,
  and reports an unbridged player as "no gsis"; the player / team rollups sum
  and average over the weeks with data and leave unbridged starters out;
* the tool table and its flags (advise.py / trade.py);
* on the committed cache (skips without it): every completed-season
  ffopportunity row's league-scored xFP is within rounding of its own total,
  and the actual components + lost fumbles reproduce its actual points;
* on the committed exports (skips until a build carries the columns): Points
  minus xFP = Points − xFP, team_week's Starters' xFP is the starters' sum,
  the year sheets add up to player_week / team_week, and at least 97% of the
  2021+ player-weeks that scored have an xFP (every miss listed).

Run: python tests/test_usage.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

from lotg_support import usage as U  # noqa: E402

_EXPORTS = _ROOT / "exports"
_CACHE = _ROOT / ".cache"

PPR = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "pass_2pt": 2.0, "rush_yd": 0.1, "rush_td": 6.0,
       "rush_2pt": 2.0, "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rec_2pt": 2.0, "fum": -1.0, "fum_lost": -1.0}


def _skip(reason: str) -> bool:
    print(f"  (skip: {reason})")
    return True


def _ffo_row(**kw):
    base = {c: 0.0 for c in U.XFP_SCORE_MAP.values()}
    base.update({c: 0.0 for c in U.ACTUAL_SCORE_MAP.values()})
    base.update(season=2025, week=1, player_id="00-0037744", position="TE", rec_fumble_lost=0, rush_fumble_lost=0)
    base.update(kw)
    return base


# --------------------------------------------------------------------------- synthetic
def test_xfp_is_league_scoring_of_the_expected_components():
    # Trey McBride 2025 wk1 as ffopportunity publishes it (total_fantasy_points_exp 15.43).
    f = pd.DataFrame([_ffo_row(receptions_exp=7.09, rec_yards_gained_exp=66.39, rec_touchdown_exp=0.28)])
    assert abs(U.component_points(f, PPR).iat[0] - 15.43) < 0.03
    half = dict(PPR, rec=0.5)
    assert abs(U.component_points(f, half).iat[0] - (15.409 - 3.545)) < 1e-6
    # first downs score when a season scores them; fumbles never enter xFP
    f2 = pd.DataFrame([_ffo_row(rush_first_down_exp=2.0)])
    assert U.component_points(f2, dict(PPR, rush_fd=0.5)).iat[0] == 1.0
    assert U.component_points(f2, {"fum": -2.0, "fum_lost": -2.0}).iat[0] == 0.0
    assert set(U.NOT_MODELLED) & set(U.XFP_SCORE_MAP) == set()


def test_red_zone_counts_only_red_zone_targets_and_carries():
    pbp = pd.DataFrame([
        # season_type, week, yl, play_type, 2pt, rush, pass, sack, rusher, receiver
        ("REG", 1, 15, "pass", 0, 0, 1, 0, None, "R1"),     # target
        ("REG", 1, 20, "run", 0, 1, 0, 0, "B1", None),      # carry (at the 20)
        ("REG", 1, 21, "run", 0, 1, 0, 0, "B1", None),      # outside
        ("REG", 1, 2, "pass", 1, 0, 1, 0, None, "R1"),      # two-point try
        ("REG", 1, 5, "no_play", 0, 0, 1, 0, None, "R1"),   # penalty
        ("REG", 1, 8, "pass", 0, 0, 1, 1, None, None),      # sack
        ("REG", 1, 3, "run", 0, 1, 0, 0, "Q1", None),       # scramble / QB run counts
        ("POST", 19, 3, "pass", 0, 0, 1, 0, None, "R1"),    # playoffs
    ], columns=U._PBP_COLS)
    rz = U.red_zone_from_pbp(pbp).set_index("gsis_id")
    assert rz.at["R1", "rz_targets"] == 1 and rz.at["R1", "rz_carries"] == 0
    assert rz.at["B1", "rz_carries"] == 1
    assert rz.at["Q1", "rz_carries"] == 1
    assert set(rz.index) == {"R1", "B1", "Q1"} and set(rz["week"]) == {1}


def _season():
    stats = pd.DataFrame({"player_id": ["G1", "G2", "G1"], "season_type": ["REG", "REG", "POST"],
                          "week": [1, 1, 19], "targets": [8, 0, 5], "carries": [1, 14, 0],
                          "receiving_air_yards": [90, -3, 10], "target_share": [0.3, None, 0.2]})
    snaps = pd.DataFrame({"pfr_player_id": ["P1", "P2", "P3", "P4"], "game_type": ["REG"] * 4,
                          "week": [1, 1, 2, 1], "offense_snaps": [50, 40, 10, 0],
                          "defense_snaps": [0, 0, 0, 0], "st_snaps": [0, 0, 2, 0],
                          "offense_pct": [0.8, 0.6, 0.15, 0.0]})
    bridge = {"P1": "G1", "P2": "G2", "P3": "G3", "P4": "G4"}
    ffo = pd.DataFrame([_ffo_row(player_id="G1", week=1, receptions_exp=5.0, rec_yards_gained_exp=60.0),
                        _ffo_row(player_id="G2", week=1, rush_yards_gained_exp=70.0, rush_touchdown_exp=0.5),
                        _ffo_row(player_id="G1", week=19, receptions_exp=9.0)])
    rz = pd.DataFrame({"gsis_id": ["G2"], "week": [1], "rz_targets": [0], "rz_carries": [3]})
    return U.season_usage(2025, stats, snaps, ffo, rz, bridge, PPR)


def test_season_usage_bridges_snaps_and_drops_the_postseason():
    u = _season().set_index(["gsis_id", "week"])
    assert (("G1", 19) not in u.index)                        # ffopportunity's playoff week
    assert u.at[("G1", 1), U.SNAP] == 0.8 and u.at[("G1", 1), U.TARGETS] == 8
    assert u.at[("G2", 1), U.TSHARE] == 0.0                   # played, no target row -> 0
    assert u.at[("G2", 1), U.RZ] == 3
    assert abs(u.at[("G2", 1), "_xfp_base"] - 10.0) < 1e-9
    assert u.at[("G3", 2), "_xfp_base"] == 0.0                # special-teams snaps only
    assert ("G4", 1) not in u.index                           # 0 snaps is not an appearance


def _pw():
    return pd.DataFrame({
        "Player ID": ["s1", "s2", "s3", "s1", "s4"],
        "Player": ["A", "B", "C", "A", "D"],
        "Team": ["T", "T", "T", "T", "T"],
        "Year": [2025, 2025, 2025, 2025, 2025],
        "Week": [1, 1, 2, 2, 1],
        "Starter/Bench": ["Starter", "Starter", "Starter", "Starter", "Starter"],
        "Position": ["TE", "RB", "WR", "TE", "WR"],
        "Points": [12.0, 15.0, 0.0, 0.0, 9.0],
    })


def test_attach_blanks_did_not_play_and_reports_unbridged():
    bridge = {"s1": "G1", "s2": "G2", "s3": "G3"}           # s4 has no gsis
    pw, rep = U.attach(_pw(), _season(), bridge, {2025: dict(PPR, bonus_rec_te=0.5)})
    r = pw.set_index(["Player ID", "Week"])
    assert abs(r.at[("s1", 1), U.XFP] - (5 + 6 + 2.5)) < 1e-9          # TE premium on expected catches
    assert abs(r.at[("s2", 1), U.XFP] - 10.0) < 1e-9                    # no premium for an RB
    assert abs(r.at[("s1", 1), U.DIFF] - (12.0 - 13.5)) < 1e-9
    assert pd.isna(r.at[("s1", 2), U.XFP])                              # no game that week
    assert r.at[("s3", 2), U.XFP] == 0.0                                # snaps only
    st = rep.set_index(["Player ID", "Week"])["status"]
    assert st[("s4", 1)] == "no gsis" and st[("s1", 2)] == "did not play" and st[("s1", 1)] == "matched"
    un = U.unmatched_players(rep)
    assert list(un["Player ID"]) == ["s4"] and un.at[0, "Player-weeks"] == 1
    summ = U.match_summary(rep).iloc[0]
    assert summ["rows"] == 5 and summ["no gsis"] == 1


def test_rollups_sum_over_weeks_with_data():
    pw, _ = U.attach(_pw(), _season(), {"s1": "G1", "s2": "G2", "s3": "G3"}, {2025: PPR})
    py = U.player_rollup(pw, ["Player ID", "Year"]).set_index("Player ID")
    assert py.at["s1", U.WEEKS] == 1 and py.at["s1", U.XFP] == 11.0 and py.at["s1", U.AVG_XFP] == 11.0
    assert py.at["s4", U.WEEKS] == 0 and pd.isna(py.at["s4", U.XFP])
    assert py.at["s2", U.CARRIES] == 14 and py.at["s2", U.RZ] == 3
    tw = U.team_week_rollup(pw).set_index("Week")
    assert tw.at[1, U.ST_XFP] == 21.0                                   # s4 (unbridged) left out
    assert tw.at[1, U.ST_DIFF] == round((12 - 11) + (15 - 10), 2)
    assert tw.at[2, U.ST_XFP] == 0.0                                    # s3 played for nothing
    ty = U.team_rollup(tw.reset_index(), ["Team", "Year"]).iloc[0]
    assert ty[U.ST_XFP] == 21.0 and ty[U.AVG_ST_XFP] == 10.5


def test_tool_table_and_flags():
    t = pd.DataFrame({"G": [6, 6], "Snap%": [0.5, 0.9], "Snap% L3": [0.8, 0.9], "Tgt/G": [3, 8], "Car/G": [9, 0],
                      "RZ/G": [1, 1], "xFP/G": [10.0, 15.0], "xFP L3": [16.0, 15.5],
                      "Pts-xFP/G": [0.0, 5.0], "Pts-xFP L3": [0.5, 6.0]}, index=["a", "b"])
    flags = U.usage_flags(t, {"a": "Rising Back", "b": "Hot Receiver"})
    assert any("Rising Back" in f and "UP" in f for f in flags)
    assert any("Hot Receiver" in f and "above" in f for f in flags)
    assert not any("Hot Receiver" in f and ("UP" in f or "DOWN" in f) for f in flags)
    dp = pd.DataFrame({"sleeper_id": ["1", "2"], "gsis_id": ["00-0000001", "00-0000002"]})
    m = U.sleeper_to_gsis({"1": {"gsis_id": " 00-0000009 "}}, dp)
    assert m == {"1": "00-0000009", "2": "00-0000002"}


def test_topic_and_number_formats():
    import lotg
    from lotg_support.number_format import col_number_format as fmt
    assert {lotg._col_topic(c) for c in U.ALL_COLUMNS} == {"Usage"}
    assert "Usage" in lotg._TOPIC_FILL
    assert {fmt(c) for c in U.COUNT_COLUMNS} == {"0"}
    assert {fmt(c) for c in U.FRACTION_COLUMNS} == {"0.00%"}
    assert fmt(U.XFP) == fmt(U.DIFF) == "0.00"


# --------------------------------------------------------------------------- committed cache
def test_cached_ffopportunity_reconciles_with_its_own_totals():
    files = sorted(_CACHE.glob("ffopportunity_ep_weekly_*.csv.gz"))
    snap = _EXPORTS / "snapshot"
    done = [f for f in files if int(f.name[-11:-7]) < 2026 and (snap / f"season_{f.name[-11:-7]}" / "league.json").exists()]
    if not done and _skip("no completed-season ffopportunity file in .cache"):
        return
    for f in done:
        y = int(f.name[-11:-7])
        sc = json.loads((snap / f"season_{y}" / "league.json").read_text())["scoring_settings"]
        d = pd.read_csv(f, compression="gzip", low_memory=False)
        x = U.component_points(d, sc)
        assert (x - d["total_fantasy_points_exp"]).abs().max() < 0.6, y      # rounded components (max 0.51, 2022)
        a = U.component_points(d, sc, U.ACTUAL_SCORE_MAP) - 2 * (d["rec_fumble_lost"].fillna(0) + d["rush_fumble_lost"].fillna(0))
        assert (a - d["total_fantasy_points"]).abs().max() < 0.01, y


# --------------------------------------------------------------------------- committed exports
def _load(name):
    p = _EXPORTS / f"{name}.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _built():
    pw = _load("player_week")
    if pw is None or U.XFP not in pw.columns:
        _skip("exports/player_week.csv has no usage columns yet")
        return None
    return pw


def test_player_week_difference_and_match_rate():
    pw = _built()
    if pw is None:
        return
    x, d, pts = _num(pw[U.XFP]), _num(pw[U.DIFF]), _num(pw["Points"])
    has = x.notna()
    assert ((pts[has] - x[has] - d[has]).abs() < 0.011).all()
    assert (x[has] >= -6).all()                                  # INT expectation can go a little negative
    yr = _num(pw["Year"])
    scored = (yr >= 2021) & (yr < yr.max()) & (pts.fillna(0) != 0)
    rate = has[scored].mean()
    miss = pw.loc[scored & ~has, ["Player", "Team", "Year", "Week", "Points"]]
    print(f"  xFP coverage of scoring 2021+ completed-season player-weeks: {rate:.4f}; misses: {len(miss)}")
    print(miss.groupby("Player").size().sort_values(ascending=False).head(25).to_string())
    assert rate >= 0.97, rate


def test_team_week_and_year_sheets_add_up():
    pw = _built()
    if pw is None:
        return
    tw, ty, py = _load("team_week"), _load("team_year"), _load("player_year")
    keys = ["Team", "Year", "Week"]
    st = pw[pw["Starter/Bench"] == "Starter"].assign(_x=_num(pw[U.XFP]))
    want = st.groupby(keys)["_x"].sum(min_count=1)
    got = tw.set_index(keys)[U.ST_XFP].pipe(_num)
    both = pd.concat([want.rename("w"), got.rename("g")], axis=1).dropna()
    assert len(both) > 0 and ((both["w"] - both["g"]).abs() < 0.05).all()
    yw = _num(tw[U.ST_XFP]).groupby([tw["Team"], tw["Year"]]).sum(min_count=1)
    yg = ty.set_index(["Team", "Year"])[U.ST_XFP].pipe(_num)
    yb = pd.concat([yw.rename("w"), yg.rename("g")], axis=1).dropna()
    assert ((yb["w"] - yb["g"]).abs() < 0.1).all()
    for c in (U.TARGETS, U.CARRIES, U.RZ):
        a = _num(pw[c]).groupby(_num(pw["Year"])).sum()
        b = _num(py[c]).groupby(_num(py["Year"])).sum()
        for y in a.index:
            if a[y] > 0:
                assert abs(a[y] - b.get(y, 0)) < 0.5, (c, y, a[y], b.get(y))


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
