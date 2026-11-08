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

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall faab pipeline checks passed")


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

