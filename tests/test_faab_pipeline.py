"""FAAB value pipeline pieces (`lotg_support.faab_pipeline` / `faab_inputs` / `faab_votes` vote dates).

- the replacement line by season (184 / 208 / 200 roster spots league-wide);
- the excused-absence fallback lifts an exempt player to his preseason value and never lowers anyone;
- votes map to the grid date of the board they were shown on (never a later one), and a vote on an unknown
  player or a date before the grid is skipped, not misplaced;
- trades.csv parses into two-team sides, players resolved to their player_additions row;
- a pick's price falls with each further draft out and a late slot never prices above an early one;
- the summer flags: only a player off the Week-1 roster is 'unsigned'; the offseason window is everyone's;
- a player on a roster (IR, suspended) is never 'no NFL team'.

None of these need scikit-learn (the models import it lazily), so they run in the build's CI. No network. Run: python tests/test_faab_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import faab_inputs as I  # noqa: E402
from lotg_support import faab_pipeline as P  # noqa: E402
from lotg_support import faab_features as X  # noqa: E402


def test_replacement_line_by_season():
    assert list(P.line_n(pd.to_datetime(["2023-10-01", "2024-02-01", "2024-10-01", "2025-03-01", "2026-10-24"]))) == [184, 184, 208, 200, 200]


def test_excused_fallback_lifts_to_preseason_only():
    R = pd.DataFrame({"sid": ["a", "a", "b", "b"], "date": pd.to_datetime(["2025-08-20", "2025-10-21", "2025-08-20", "2025-10-21"]),
                      "V_raw": np.array([900, 100, 300, 500], "float32"), "e_x_cur_exempt": [0, 3, 0, 3]})
    out = P.excused_fallback(R.copy()).V_raw.values
    assert out[1] == 900 and out[3] == 500 and out[0] == 900 and out[2] == 300


def test_votes_map_to_their_own_board_date():
    R = pd.DataFrame({"sid": ["1", "2", "1", "2"], "date": pd.to_datetime(["2026-10-20", "2026-10-20", "2026-10-27", "2026-10-27"])})
    csv = ("timestamp,team,question_id,kind,board_date,player_a,player_b\n"
           "10/25/2026 10:00:00,Oliverwkw,q1,pair,2026-10-24,1,2\n"
           "10/25/2026 10:00:00,Oliverwkw,q2,pair,2020-01-01,1,2\n"
           "10/25/2026 10:00:00,Oliverwkw,q3,pair,2026-10-24,1,999\n")
    idx, vd = P.vote_rows(R, csv)
    assert vd == {"2026-10-24": "2026-10-20"}                         # the board shown on the 24th = the 20th's rows
    assert sorted(R.iloc[idx].index.tolist()) == [0, 1]              # unknown player 999 and the pre-grid vote skipped


def test_trades_parse_into_two_sides():
    if not (_ROOT / "exports" / "trades.csv").exists():
        print("  [SKIP] exports absent"); return
    pa = I.player_additions_sid()
    TR = I.trades(pa)
    assert len(TR) >= 200
    two = [s for s in TR.values() if len(s) == 2]
    assert len(two) / len(TR) > 0.95
    kinds = {k for s in TR.values() for side in s.values() for k, _, _ in side}
    assert kinds <= {"faab", "pick", "player", "startup", "unknown"}
    pl = [(x, a) for s in TR.values() for side in s.values() for k, x, a in side if k == "player"]
    assert all(pa.loc[x, "Player"] == a for x, a in pl[:300])


def test_pick_prices_fall_with_distance_and_slot():
    if not (_ROOT / "exports" / "rookie_picks.csv").exists():
        print("  [SKIP] exports absent"); return
    pk = I.Picks(I.player_additions_sid())
    d = pd.Timestamp("2026-03-01")
    assert pk.value("2026 1", d) > pk.value("2027 1", d) > pk.value("2028 1", d)
    assert pk.value("2026 1", d) > pk.value("2026 2", d) > pk.value("2026 3", d)
    assert pk.value("2026 5", d) == 20.0


def test_unsigned_only_off_the_week1_roster_offseason_for_everyone():
    # one summer date and one in-season date for: a Week-1 player, a Week-4 signing, a never-signed player, a retired one
    d = pd.to_datetime(["2025-08-05"] * 4 + ["2025-10-01"] * 4).values
    fw = np.array([1, 4, np.nan, np.nan] * 2, dtype=float)
    ko = np.array([X.KO[2025]] * 8, dtype="datetime64[ns]"); jun1 = pd.to_datetime(["2025-06-01"] * 8).values
    over = np.array([0, 0, 0, 1] * 2)
    un, off = X.offseason_flags(d, fw, ko, jun1, over)
    assert list(un) == [0, 1, 1, 0, 0, 0, 1, 0], un      # Lamar-style Week-1 starter is signed all summer
    assert list(off) == [1, 1, 1, 1, 0, 0, 0, 0], off    # the summer window is everyone's, the season no one's
    # the Week-4 signing is unsigned until 3 days before his first week, then signed
    un2, _ = X.offseason_flags(pd.to_datetime(["2025-09-21", "2025-09-22"]).values, np.array([4.0, 4.0]),
                               np.array([X.KO[2025]] * 2, dtype="datetime64[ns]"), pd.to_datetime(["2025-06-01"] * 2).values, np.zeros(2))
    assert list(un2) == [1, 0], un2


def test_rostered_players_have_a_team():
    # offseason: on a roster last season (a year on IR or suspended) counts; in season only this season's roster does
    d = pd.to_datetime(["2023-03-21", "2023-03-21", "2023-10-01", "2023-10-01", "2023-09-08"]).values
    fw_l0 = np.array([9.0, np.nan, 1.0, 1.0, np.nan]); fw_cur = np.array([1.0, np.nan, np.nan, 3.0, 1.0])
    ko = np.array([X.KO[2022], X.KO[2022], X.KO[2023], X.KO[2023], X.KO[2023]], dtype="datetime64[ns]")
    ins = np.array([False, False, True, True, True])
    assert list(X.rostered_recent(d, fw_l0, fw_cur, ko, ins)) == [1, 0, 0, 1, 1]


TESTS = [test_replacement_line_by_season, test_excused_fallback_lifts_to_preseason_only, test_votes_map_to_their_own_board_date,
         test_trades_parse_into_two_sides, test_pick_prices_fall_with_distance_and_slot,
         test_unsigned_only_off_the_week1_roster_offseason_for_everyone, test_rostered_players_have_a_team]

def test_lag_rows_find_the_row_four_weeks_earlier():
    d = pd.to_datetime(["2025-09-02", "2025-09-30", "2025-10-01", "2025-10-28", "2025-09-01", "2025-10-28"])
    R = pd.DataFrame(dict(sid=["a", "a", "a", "a", "b", "b"], date=d))
    # a on 10-28 -> 09-30 (the latest at least 28 days earlier); a on 10-01 -> 09-02 (29 days); b on 10-28 -> none
    # (09-01 is 57 days back, past the 7-day slack); a on 09-02 -> none
    assert list(P.lag_rows(R, np.array([3, 2, 5, 0]))) == [0, 1]



def test_game_form_counts_full_role_duds_and_crosses_seasons():
    # 2024: 4 full-role games (2 under 5 PPR) and a cameo under 5 (not a dud); 2025: 16 full games, 10 PPR then 20
    rows = [("a", 2024, w, p_, s_) for w, p_, s_ in [(1, 3, .8), (2, 4, .9), (3, 15, .9), (4, 20, .7), (5, 1, .2)]]
    rows += [("a", 2025, w, 10.0 if w <= 10 else 20.0, .9) for w in range(1, 17)]
    gl = pd.DataFrame(rows, columns=["gsis", "season", "week", "ppr", "off_pct"])
    gl["known"] = pd.to_datetime(gl.season.map(X.KO)) + pd.to_timedelta(7 * (gl.week - 1) + 5, unit="D")
    d = pd.to_datetime(["2026-03-01", "2026-03-01", "2025-09-20"]).values
    o = X.game_form(gl, ["a", "b", "a"], d, [2025, 2025, 2024])
    assert o["duds_2y"][0] == 2 and o["full_2y"][0] == 20 and o["duds_2y"][1] == 0 and np.isnan(o["form_last"][1])
    assert abs(o["form_last"][0] - 16.0) < 1e-9          # 2025 weeks 7-16: four 10s, six 20s
    assert abs(o["form_prev"][0] - 10.0) < 1e-9          # 2024 weeks 2-5 (4 + 15 + 20 + 1) + 2025 weeks 1-6 (six 10s): crosses seasons
    assert np.isnan(o["form_last"][2]) and o["duds_2y"][2] == 2          # by 2025-09-20 only 7 games are known


def test_coach_follow_needs_a_move_and_the_same_head_coach():
    gt = pd.DataFrame({"team": ["BAL", "BAL", "NYG", "NYG", "MIA"], "season": [2025, 2025, 2026, 2026, 2026], "game_type": "REG",
                       "gameday": pd.to_datetime(["2025-09-07", "2026-01-04", "2026-09-13", "2026-09-20", "2026-09-13"]),
                       "coach": ["John Harbaugh", "John Harbaugh", "John Harbaugh", "John Harbaugh", "Jeff Hafley"]})
    o = X.coach_follow([2026, 2026, 2026], ["NYG", "MIA", "BAL"], ["BAL", "BAL", "BAL"], gt)
    assert list(o) == [1.0, 0.0, 0.0]                  # followed Harbaugh; new coach; did not move
    assert list(X.coach_follow([2026], ["NYG"], ["BAL"], gt.drop(columns="coach"))) == [0.0]   # no coach data: never


def test_rookie_backup_spend_counts_same_team_same_position_rookies():
    roster = pd.DataFrame({"gsis": ["v", "v", "r", "r", "q", "w"], "season": 2024, "week": [1, 2, 1, 2, 1, 1], "team": ["TB", "TB", "TB", "TB", "TB", "NYG"]})
    info = pd.DataFrame({"sid": ["R", "Q", "W", "V"], "gsis": ["r", "q", "w", "v"], "pos": ["RB", "QB", "RB", "RB"], "dyear": [2024, 2024, 2024, 2022]})
    adds = pd.DataFrame({"sid": ["R", "R", "Q", "W", "V"], "date": pd.to_datetime(["2024-05-10", "2024-09-03", "2024-05-10", "2024-05-10", "2022-05-10"]),
                         "type": ["Draft", "Waiver", "Draft", "Draft", "Draft"], "price": [50.0, 61.0, 900.0, 700.0, 500.0]})
    rows = pd.DataFrame({"sid": ["V", "V", "V", "R"], "gsis": ["v", "v", "v", "r"], "date": pd.to_datetime(["2024-05-01", "2024-08-01", "2024-09-21", "2024-09-21"]), "pos": "RB"})
    gl = pd.DataFrame({"gsis": "v", "season": [2023, 2023, 2024, 2024], "known": pd.to_datetime(["2023-09-15", "2023-09-22", "2024-09-14", "2024-09-21"]),
                       "rush_car": [20.0, 20.0, 10.0, 10.0], "gl_tgt": [4.0, 4.0, 4.0, 4.0], "off_pct": [0.8, 0.8, 0.6, 0.6]})
    sp, held = X.rookie_backup_spend(rows, adds, info, roster, gl)
    # before the rookie was added: 0; drafted at $50; the Week-1 bid x4 = $244 is his largest price; the QB and the
    # other team's RB never count; the rookie's own row is 0
    assert list(sp) == [0.0, 50.0, 244.0, 0.0]
    assert np.isnan(held[0]) and np.isnan(held[1]) and abs(held[2] - (0.5 + 1.0 + 0.75) / 3) < 1e-9


def test_nfl_draft_comp_counts_early_round_rookies_from_draft_day():
    roster = pd.DataFrame({"gsis": ["v", "h", "k", "o"], "season": 2025, "week": 1, "team": ["LAC", "LAC", "LAC", "NYG"],
                           "draft_club": [None, "LAC", "LAC", "NYG"]})
    dp = pd.DataFrame({"gsis_id": ["h", "k", "o"], "position": "WR", "draft_year": 2025, "draft_round": [2, 5, 1]})
    rows = pd.DataFrame({"sid": "V", "gsis": "v", "pos": "WR", "date": pd.to_datetime(["2025-04-20", "2025-04-29", "2025-10-01", "2026-03-10"])})
    # before the draft: 0; round 2 same team counts, round 5 and another team's do not; a new season (March on) resets it
    assert list(X.nfl_draft_comp(rows, dp, roster)) == [0.0, 1.0, 1.0, 0.0]
    assert list(X.nfl_draft_comp(rows.assign(pos="RB"), dp, roster)) == [0.0] * 4


def test_departed_starter_means_the_rookie_replaced_him():
    roster = pd.DataFrame({"gsis": ["a", "a", "b", "b", "h"], "season": [2025, 2026, 2025, 2026, 2026], "week": 1,
                           "team": ["PHI", "NE", "PHI", "PHI", "PHI"], "draft_club": [None, None, None, None, "PHI"]})
    dp = pd.DataFrame({"gsis_id": ["a", "b", "h"], "position": "WR", "draft_year": [2018, 2020, 2026], "draft_round": [2, 1, 1]})
    gl = pd.DataFrame({"gsis": ["a"] * 8 + ["b"] * 8, "season": 2025, "ppr": [15.0] * 8 + [12.0] * 8})
    gone = X.departed(dp, roster, gl)
    assert gone == {("PHI", "WR", 2026)}                 # a (15 PPR/g) left; b stayed; nothing for a season without rosters
    rows = pd.DataFrame({"sid": "B", "gsis": "b", "pos": "WR", "date": pd.to_datetime(["2026-10-01"])})
    assert list(X.nfl_draft_comp(rows, dp, roster)) == [1.0] and list(X.nfl_draft_comp(rows, dp, roster, gone=gone)) == [0.0]


def test_game_form_counts_15_point_games_and_best_game():
    gl = pd.DataFrame({"gsis": "a", "season": [2023, 2024, 2024, 2025, 2026], "week": 1, "known": pd.to_datetime(["2023-09-15", "2024-09-15", "2024-09-22", "2025-09-15", "2026-09-15"]),
                       "ppr": [20.0, 16.0, 45.0, 3.0, 12.0], "off_pct": 0.8})
    f = X.game_form(gl, ["a"], pd.to_datetime(["2026-06-09"]).values, [2025])
    assert f["g15_3y"][0] == 3.0 and f["max_2y"][0] == 45.0         # 2023-25: 20, 16, 45; best of 2024-25 (+2026, none yet)


def test_offseason_move_from_free_agency_to_kickoff():
    d = pd.to_datetime(["2025-03-01", "2025-04-08", "2025-04-08", "2025-09-20"]).values
    o = X.offseason_move(d, [2025, 2025, 2025, 2025], ["LA", "LA", "TB", "LA"], ["NYJ", "NYJ", "TB", "NYJ"])
    assert list(o) == [0.0, 1.0, 0.0, 0.0]            # before March 15; moved; same team; in season (e_x_new_team's job)
    # after kickoff, until his first game is in the stats (no e_x_new_team yet), up to 5 weeks
    d2 = pd.to_datetime(["2025-09-07", "2025-09-07", "2025-10-20"]).values
    o2 = X.offseason_move(d2, [2025] * 3, ["PIT", "PIT", "PIT"], ["MIA", "MIA", "MIA"], [True, False, True])
    assert list(o2) == [1.0, 0.0, 0.0]


def test_vet_deal_cap_reads_this_seasons_veteran_deal():
    """the cap share of a veteran deal signed in the row's season (March-based); rookie deals and other seasons don't count"""
    c = pd.DataFrame(dict(gsis_id=["a", "a", "a", "b"], year_signed=[2017, 2020, 2024, 2024], draft_year=[2017, 2017, 2017, 2024],
                          apy_cap_pct=[0.003, 0.031, 0.017, 0.008]))
    rows = pd.DataFrame(dict(gsis=["a", "a", "a", "b", "a"], date=pd.to_datetime(["2024-07-09", "2025-02-01", "2025-03-02", "2024-07-09", "2017-08-01"])))
    v = X.vet_deal_cap(rows, c)
    assert np.allclose(v[:2], [0.017, 0.017]) and np.isnan(v[2]) and np.isnan(v[3]) and np.isnan(v[4])


def test_league_undrafted_credits_top_week1_adds():
    """not taken in the league's rookie draft = 1, less credit for a pre-Week-1 bid against the season's 5th-largest"""
    d0 = "2024-07-13"
    adds = pd.DataFrame(dict(sid=["d", "w1", "w2", "w3", "w4", "w5", "luke"], type=["Draft"] + ["Waiver"] * 6,
                             date=pd.to_datetime([d0] + ["2024-09-03"] * 6), price=[0, 80, 60, 40, 35, 30, 15]))
    rows = pd.DataFrame(dict(sid=["d", "luke", "luke", "w1", "x", "x"],
                             date=pd.to_datetime(["2024-08-01", "2024-08-01", "2024-09-04", "2024-09-04", "2024-09-04", "2024-07-01"])))
    v = X.league_undrafted(rows, adds)
    assert np.allclose(v[:5], [0.0, 1.0, 0.5, 0.0, 1.0]) and np.isnan(v[5])




def test_te_one_off_is_one_big_year_on_a_new_team_after_mid_seasons():
    gl = pd.DataFrame([dict(gsis=g, season=y, ppr=p) for g, seas in (("j", {2019: 8, 2020: 7, 2021: 4, 2022: 4, 2023: 7, 2024: 13}),
                                                                     ("k", {2022: 12, 2023: 7, 2024: 13}), ("m", {2021: 4, 2022: 4, 2023: 7, 2024: 13}))
                       for y, p in seas.items() for _ in range(10)])
    ro = pd.DataFrame([dict(gsis=g, season=y, week=1, team=("MIA" if y == 2024 else "ATL") if g != "m" else "MIA") for g in "jkm" for y in range(2019, 2026)])
    rows = pd.DataFrame(dict(gsis=["j", "k", "m", "j"], date=pd.to_datetime(["2025-09-07"] * 3 + ["2024-09-01"]), pos=["TE"] * 4))
    assert np.allclose(X.te_one_off(rows, gl, ro), [1.0, 0.0, 0.0, 0.0])    # k: one mid season only; m: big year on the same team


def test_ypc_with_current_adds_this_seasons_known_games():
    gl = pd.DataFrame(dict(gsis="m", season=[2019, 2020, 2021, 2021], week=[1, 1, 1, 10], rush_car=[100, 50, 100, 100], rush_yds=[400, 180, 450, 500],
                           known=pd.to_datetime(["2019-09-10", "2020-09-15", "2021-09-14", "2021-11-16"])))
    rows = pd.DataFrame(dict(gsis=["m", "m"], date=pd.to_datetime(["2021-10-01", "2021-12-01"])))
    v = X.ypc_with_current(rows, gl)
    assert np.isclose(v[0], (400 + 180 + 450) / 250) and np.isclose(v[1], (400 + 180 + 450 + 500) / 350)



def test_overtaken_by_a_same_team_rookie_last_season():
    gl = pd.DataFrame([dict(gsis=g, season=2023, ppr=p) for g, p in (("v", 13.0), ("r", 17.0), ("o", 12.0), ("w", 10.0)) for _ in range(10)])
    ro = pd.DataFrame([dict(gsis=g, season=2023, week=1, team=t) for g, t in (("v", "LA"), ("r", "LA"), ("o", "SF"), ("w", "LA"))])
    dp = pd.DataFrame(dict(gsis_id=["v", "r", "o", "w"], position=["WR", "WR", "WR", "RB"], draft_year=[2017, 2023, 2016, 2019]))
    rows = pd.DataFrame(dict(gsis=["v", "o", "r", "v", "w"], date=pd.to_datetime(["2024-04-30", "2024-04-30", "2024-04-30", "2023-04-30", "2024-04-30"]),
                             pos=["WR", "WR", "WR", "WR", "RB"]))
    # v: the LA rookie r outscored him by 4 a game -> 1; o: other team; r: the rookie himself; v a season earlier; w: other position
    assert np.allclose(X.overtaken_by_rookie(rows, gl, ro, dp), [1.0, 0.0, 0.0, 0.0, 0.0])


def test_wr_mates_pair_each_wr_with_his_teams_top_other_wr():
    R = pd.DataFrame(dict(sid=list("abcd"), gsis=list("abcd"), date=pd.to_datetime(["2024-05-07"] * 4), pos=["WR", "WR", "WR", "WR"],
                          V_raw=[3000.0, 2000.0, 500.0, 900.0]))
    ro = pd.DataFrame(dict(gsis=list("abcd"), season=2024, week=1, team=["MIA", "MIA", "MIA", "BUF"]))
    old = getattr(X, "RW", None); X.RW = ro
    try:
        m = P.wr_mates(R, np.arange(4))
    finally:
        X.RW = old
    assert m == {0: 1, 1: 0, 2: 0}          # the top WR gets the second; the rest the top; alone on his team: none


def test_te_top3_reads_last_two_seasons_top_three_tes():
    gl = pd.DataFrame([dict(gsis=g, season=y, ppr=p) for g, y, p in (("a", 2021, 200), ("b", 2021, 190), ("c", 2021, 180), ("d", 2021, 170),
                                                                      ("d", 2020, 300), ("w", 2021, 400))])
    pos = pd.Series(dict(a="TE", b="TE", c="TE", d="TE", w="WR"))
    rows = pd.DataFrame(dict(gsis=["c", "d", "d", "a"], date=pd.to_datetime(["2022-11-30", "2022-11-30", "2021-11-30", "2022-11-30"]), pos=["TE", "TE", "TE", "WR"]))
    # c: TE3 in 2021 (the WR doesn't count); d: TE4 in 2021, TE1 in 2020 (two back = 0.5); d a season earlier: TE1 last season; a WR row: 0
    assert np.allclose(X.te_top3(rows, gl, pos=pos), [1.0, 0.5, 1.0, 0.0])


def test_board_day_is_the_trade_day_unless_a_same_day_event_could_follow_it():
    dd = {pd.Timestamp("2025-05-03")}                                  # a league rookie-draft day
    assert P.board_day("2025-07-14 13:20:37", dd) == pd.Timestamp("2025-07-14")          # an ordinary day: its own board
    assert P.board_day("2025-05-03 21:00:00", dd) == pd.Timestamp("2025-05-02")          # league draft day: the day before
    assert P.board_day("2025-04-24 19:59:00", dd) == pd.Timestamp("2025-04-23")          # NFL draft Thursday, before round 1
    assert P.board_day("2025-04-24 20:30:00", dd) == pd.Timestamp("2025-04-24")          # ... after it started
    assert P.board_day("2025-04-25 18:00:00", dd) == pd.Timestamp("2025-04-24")          # Friday before rounds 2-3
    assert P.board_day("2025-04-26 11:00:00", dd) == pd.Timestamp("2025-04-25")          # Saturday before rounds 4-7
    assert P.board_day("2025-04-26", dd) == pd.Timestamp("2025-04-25")                   # a cut (no time) on a draft day
    assert P.board_day("2025-04-27 09:00:00", dd) == pd.Timestamp("2025-04-27")          # the day after the draft


def test_evidence_rows_use_the_trade_days_board_and_fall_back_a_week():
    R = pd.DataFrame({"sid": ["1", "2", "1", "2", "1"],
                      "date": pd.to_datetime(["2025-07-08", "2025-07-08", "2025-07-14", "2025-07-14", "2025-07-15"])})
    pa = pd.DataFrame({"sid": ["1", "2"], "Addition type": ["Trade", "Trade"], "Date": ["2025-07-14", "2025-07-14"]})
    TR = {"2025-07-14 13:20:37": {"a": [("player", 0, "x")], "b": [("faab", 50.0, None)]},
          "2025-07-15 10:00:00": {"a": [("player", 1, "y")], "b": [("faab", 20.0, None)]}}     # 2 has no 07-15 row
    drops = pd.DataFrame({"sid": ["1"], "date": pd.to_datetime(["2025-07-16"])})
    tr, cut = P.evidence_rows(R, TR, pa, None, drops, draft_days=set())
    assert tr[0][1][0][1] == [2]                    # player 1 on the trade day's own board (07-14), not 07-08
    assert tr[1][1][0][1] == [3]                    # player 2 missing on 07-15: the latest board before it (07-14)
    assert list(cut) == [4]                         # the cut on 07-16 reads the latest board on or before it (07-15)


def test_evidence_dates_add_offseason_trade_days_only_once():
    pa = pd.DataFrame({"sid": ["1"], "Addition type": ["Draft"], "Date": ["2025-05-03"]})
    TR = {"2025-07-17 10:00:00": {"a": [], "b": []}, "2025-07-17 15:00:00": {"a": [], "b": []},
          "2025-05-03 12:00:00": {"a": [], "b": []}, "2025-06-01 12:00:00": {"a": []}}
    assert P.evidence_dates(TR, pa) == [pd.Timestamp("2025-05-02"), pd.Timestamp("2025-07-17")]


def test_cached_block_rereads_stats_and_carries_the_model_to_new_rows():
    b = pd.DataFrame({"sid": ["1", "1", "2"], "date": pd.to_datetime(["2025-07-08", "2025-07-15", "2025-07-08"]),
                      "L": [5.0, 6.0, 3.0], "S": [1.0, 2.0, 0.5], "pos": ["WR", "WR", "RB"], "e_x_old": [1.0, 1.0, 1.0]})
    F = pd.DataFrame({"sid": ["1", "1", "1", "2", "2", "3"],
                      "date": pd.to_datetime(["2025-07-08", "2025-07-15", "2025-07-17", "2025-07-08", "2025-07-17", "2025-07-17"]),
                      "pos": ["WR", "WR", "WR", "RB", "RB", "TE"], "e_x_old": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0], "e_x_new": [7.0, 8.0, 9.0, 4.0, 5.0, 1.0]})
    out, k = P.refresh_block(b, F, pd.Timestamp("2025-07-01"), pd.Timestamp("2025-10-01"))
    o = out.set_index(["sid", "date"])
    assert k == 2                                                            # 1 and 2 on 07-17; 3 has no earlier row: left out
    assert o.loc[("1", pd.Timestamp("2025-07-15")), "e_x_new"] == 8.0         # a column added since the block was fit
    assert (o.e_x_old == 2.0).all()                                          # every stat re-read from today's frame
    assert o.loc[("1", pd.Timestamp("2025-07-17")), "L"] == 6.0               # the model's output from his latest earlier row
    assert o.loc[("2", pd.Timestamp("2025-07-17")), "S"] == 0.5 and o.loc[("2", pd.Timestamp("2025-07-17")), "e_x_new"] == 5.0
    assert ("3", pd.Timestamp("2025-07-17")) not in o.index


def test_since_injury_counts_games_after_the_last_week_out():
    ko = pd.Timestamp("2025-09-04"); kn = lambda w: ko + pd.Timedelta(days=7 * (w - 1) + 5)
    gl = pd.DataFrame([("a", 2025, w, kn(w), p_) for w, p_ in [(1, 10.0), (2, 12.0), (4, 30.0), (5, 20.0), (6, 25.0)]] + [("b", 2025, 1, kn(1), 9.0)],
                      columns=["gsis", "season", "week", "known", "ppr"])
    iw = pd.DataFrame([("a", 2025, 3, kn(3)), ("a", 2024, 9, kn(9) - pd.Timedelta(days=365))], columns=["gsis", "season", "week", "known"])
    ppg, gp = X.since_injury(gl, iw, ["a", "a", "a", "b"], [kn(6), kn(4), kn(2), kn(6)])
    assert gp[0] == 3 and abs(ppg[0] - 25.0) < 1e-9        # weeks 4-6 after the week-3 absence
    assert gp[1] == 1 and ppg[1] == 30.0                    # only what was known by then
    assert gp[2] == 2 and abs(ppg[2] - 11.0) < 1e-9         # before week 3: since last season's absence
    assert np.isnan(ppg[3]) and np.isnan(gp[3])            # no absence on record


def _gl(rows):
    ko = pd.Timestamp("2025-09-04")
    d = pd.DataFrame(rows, columns=["gsis", "season", "week", "team", "gl_tgt", "ppr", "off_pct", "rush_car", "rec", "pass_yds"])
    d["known"] = ko + pd.to_timedelta(7 * (d.week - 1) + 5, unit="D") + pd.to_timedelta(365 * (d.season - 2025), unit="D")
    return d


def test_rb_room_ranks_last_season_and_counts_added_competition():
    # 2024: a (team T), b (team S), k (team W) and v (team U, 15 PPR a game) are RBs; in 2025 v joins T and W drafts rookie n in round 1
    gl = pd.DataFrame([(g, 2024, w, ppr) for g, ppr in (("a", 18.0), ("b", 16.0), ("k", 14.0), ("v", 15.0)) for w in range(1, 9)],
                      columns=["gsis", "season", "week", "ppr"])
    ro = pd.DataFrame([(g, y, 1, t, None) for g, y, t in (("a", 2024, "T"), ("b", 2024, "S"), ("k", 2024, "W"), ("v", 2024, "U"),
                                                          ("a", 2025, "T"), ("b", 2025, "S"), ("k", 2025, "W"), ("v", 2025, "T"))]
                      + [("n", 2025, 1, "W", "W")], columns=["gsis", "season", "week", "team", "draft_club"])
    dp = pd.DataFrame(dict(gsis_id=["n"], position=["RB"], draft_year=[2025], draft_round=[1]))
    pos_of = pd.Series({g: "RB" for g in ("a", "b", "k", "v", "n")})
    rows = pd.DataFrame(dict(gsis=["a", "b", "k", "v"], date=[pd.Timestamp("2025-08-01")] * 4, pos=["RB"] * 4))
    rk, cp = X.rb_room(rows, gl, ro, dp, pos_of)
    assert list(rk) == [1, 2, 4, 3]
    assert list(cp) == [1, 0, 1, 0]          # a: v joined T; b: nobody; k: W's first-round rookie; v himself is not his own competition


def test_catch_rate_reads_two_seasons_and_this_one_by_the_date():
    gl = _gl([("a", 2023, 1, "T", 40, 10, 0.8, 0, 40, 0), ("a", 2024, 1, "T", 40, 10, 0.8, 0, 24, 0), ("a", 2025, 1, "T", 20, 10, 0.8, 0, 16, 0),
              ("a", 2025, 2, "T", 20, 10, 0.8, 0, 0, 0), ("b", 2025, 1, "T", 10, 10, 0.8, 0, 9, 0)])
    when = lambda s, w: gl.known[(gl.season == s) & (gl.week == w)].iloc[0]
    rows = pd.DataFrame(dict(gsis=["a", "a", "b"], date=[when(2025, 1), when(2025, 2), when(2025, 2)]))
    c = X.catch_rate(rows, gl)
    assert abs(c[0] - 80 / 100) < 1e-9 and abs(c[1] - 80 / 120) < 1e-9 and np.isnan(c[2])   # 2023 counts (two complete seasons back); b: under 30 targets


def test_league_draft_done_is_the_day_after_the_draft():
    adds = pd.DataFrame(dict(type=["Draft", "Draft", "Waiver"], date=pd.to_datetime(["2025-07-20", "2025-07-20", "2025-08-01"])))
    rows = pd.DataFrame(dict(date=pd.to_datetime(["2025-07-19", "2025-07-20", "2025-07-21", "2024-07-30"])))
    d = X.league_draft_done(rows, adds)
    assert list(d[:3]) == [0, 0, 1] and np.isnan(d[3])        # no 2024 draft rows: unknown


def test_target_lead_fades_over_17_games_after_the_lead_is_lost():
    # a leads team T in targets weeks 1-5 (4+ games in), b takes over from week 6
    gl = _gl([("a", 2025, w, "T", 9 if w <= 5 else 1, 10, 0.8, 0, 5, 0) for w in range(1, 11)] +
             [("b", 2025, w, "T", 2 if w <= 5 else 12, 8, 0.8, 0, 5, 0) for w in range(1, 11)] +
             [("c", 2025, w, "T", 3, 5, 0.5, 0, 2, 0) for w in range(1, 11)])
    when = lambda w: gl.known[gl.week == w].iloc[0]
    rows = pd.DataFrame(dict(gsis=["a", "a", "a", "c"], date=[when(5), when(10), when(3), when(10)]))
    w, sh = X.target_lead(rows, gl)
    assert w[0] == 1.0 and abs(w[1] - (1 - 2 / 17)) < 1e-9        # season-to-date: he still leads through week 8 (48 v 46)
    assert w[2] == 0.0                                              # week 3: not 4 games into the season yet
    assert w[3] == 0.0 and np.isnan(sh[3])                          # never led


def test_recent_max_touch_games_big_games():
    gl = _gl([("a", 2025, 1, "T", 5, 33.8, 0.84, 1, 6, 0), ("a", 2025, 2, "T", 5, 14.6, 0.76, 2, 5, 0), ("a", 2025, 3, "T", 4, 3.8, 0.36, 0, 2, 0),
              ("a", 2025, 6, "T", 9, 15.7, 0.75, 18, 4, 0), ("a", 2025, 7, "T", 4, 1.9, 0.66, 20, 3, 0)])
    when = lambda w: gl.known[gl.week == w].iloc[0]
    rows = pd.DataFrame(dict(gsis=["a", "a"], date=[when(6), when(7)]))
    m = X.recent_max(rows, gl)
    assert m[0] == 33.8 and m[1] == 15.7                            # the 36%-snap week 3 is not a healthy game
    assert list(X.touch_games(rows, gl)) == [1, 2]                  # 22 and 23 touches: over 20
    assert list(X.big_games(rows, gl)) == [3, 4]                    # games on half the snaps


def test_te_slide_qb_streak_draft_price_and_pass_ypg():
    pos_of = {f"t{i}": "TE" for i in range(30)} | {"q": "QB", "q2": "QB"}
    r = []
    for s in (2023, 2024, 2025):
        for i in range(30):
            pts = 30 - i
            if i == 0: pts = {2023: 40, 2024: 22, 2025: 5}[s]   # t0: TE1, then 9th, then outside the top 20
            r += [(f"t{i}", s, w, "T", 5, pts, 0.8, 0, 4, 0) for w in range(1, 7)]
    for s, n, pts in [(2023, 17, 25), (2024, 5, 20), (2025, 17, 26)]:   # q: top, hurt (5 games), top
        r += [("q", s, w, "Q", 0, pts, 1.0, 3, 0, 250) for w in range(1, n + 1)]
    for s in (2023, 2024, 2025): r += [("q2", s, w, "Q", 0, 30, 1.0, 3, 0, 300) for w in range(1, 18)]   # top every year
    gl = _gl(r)
    d = pd.Timestamp("2026-07-01"); rows = pd.DataFrame(dict(gsis=["t0", "t5", "q", "q2"], date=[d] * 4, pos=["TE", "TE", "QB", "QB"], sid=["1", "2", "3", "4"]))
    sl, rec, was = X.te_slide(rows, gl, pos_of, [2025] * 4)
    assert sl[0] == 2 and was[0] == 1 and sl[1] == 0                # t0: 9th then 30th, after a TE1 year; t5 is 6th
    st = X.qb_hurt_or_top(rows, gl, pos_of, [2025] * 4)
    assert st[2] == 3 and st[3] == 0                                # hurt-or-top for 3 years; top every year is not the rule
    adds = pd.DataFrame(dict(sid=["3", "3"], date=pd.to_datetime(["2023-05-01", "2025-05-01"]), type=["Draft", "Trade"], price=[1234.7, 500]))
    assert X.league_draft_price(rows, adds)[2] == 1234.7 and np.isnan(X.league_draft_price(rows, adds)[0])
    cur_s, ins, l0 = X.season_keys(rows.date)
    assert X.pass_ypg(rows, gl, cur_s, l0, ins)[2] == 250 and np.isnan(X.pass_ypg(rows, gl, cur_s, l0, ins)[0])


def test_qb_base_is_the_teams_best_qb_that_day():
    d = pd.Timestamp("2025-10-01")
    R = pd.DataFrame(dict(sid=["1", "2", "3", "4", "5"], gsis=["w", "q1", "q2", "t", "x"], date=[d] * 5, pos=["WR", "QB", "QB", "TE", "WR"],
                          V_raw=[300.0, 629.0, 200.0, 500.0, 100.0]))
    rw = pd.DataFrame(dict(gsis=["w", "q1", "q2", "t", "x"], season=2025, week=1, team=["LAC", "LAC", "LAC", "GB", None]))
    old = getattr(X, "RW", None); X.RW = rw
    try: q = P.qb_base(R, np.arange(5))
    finally: X.RW = old
    assert q[0] == 629.0 and np.isnan(q[1]) and np.isnan(q[3]) and np.isnan(q[4])   # GB has no QB here; x has no team


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall faab pipeline checks passed")
