"""FAAB-unit values (`lotg_support.faab_value`) and rating-page votes (`lotg_support.faab_votes`).

- every rule's bounds and fitted strength respect its sign lock (an injury can only lower a value, ...);
- the committed params reproduce the board they were fitted on (top of the 2026-10-24 board) and beat the
  rules-off baseline on BOTH the league's trades and its cuts — the system has to explain history, not
  just the calls;
- the league calls still mostly pass (a regression floor, not a target);
- every trade/cut in evidence.json resolves to an inputs row;
- votes are a capped signal: one answer per team per question, own players halved, non-members quartered,
  one team's share capped, the term's weight grows with answers and teams and never passes VOTE_MAX;
- the page's board.json / questions.json are in sync with the committed inputs and params.

No network. Run: python tests/test_faab_value.py
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import faab_calls as LC  # noqa: E402
from lotg_support import faab_value as F  # noqa: E402
from lotg_support import faab_votes as FV  # noqa: E402

REF = F.DATA / f"reviewed_board_{LC.CALLS_DATE}.csv"


def test_sign_locks_hold_for_bounds_and_params():
    p = F.load_params()
    for k in F.RAISE_ONLY:
        assert F.BOUNDS[k][0] >= 0 and p[k] >= 0, k
    for k in F.LOWER_ONLY:
        assert F.BOUNDS[k][1] <= 0 and p[k] <= 0, k
    for k, (lo, hi) in F.BOUNDS.items():
        assert lo - 1e-9 <= p[k] <= hi + 1e-9, (k, p[k], lo, hi)


def test_board_reproduces_and_beats_rules_off_on_trades_and_cuts():
    R = F.load_inputs(); p = F.load_params()
    T = F.board(R, p, as_of=LC.CALLS_DATE).set_index("name").V
    # 704 = the reviewed board; the weekly rebuild can qualify more players as of
    # the calls date (2026-10-28: 706, Darius Cooper + Ryan Flournoy) but never drop one
    assert T.index.is_unique and len(T) >= 704, len(T)
    # the weekly rebuild rewrites inputs.csv, so no exact dollars: the top 3 stay these three, inside the top-3 call's band
    top3 = set(T.sort_values(ascending=False).index[:3])
    assert top3 == {"Jahmyr Gibbs", "Bijan Robinson", "Josh Allen"}, top3
    for n in top3:
        assert 3700 <= T[n] <= 4300, (n, T[n])
    ev = F.Evidence.load()
    fitted, off = F.apply_rules(ev.E, p), F.apply_rules(ev.E, dict(F.P0))
    assert F.trade_err(fitted, ev.trades)[0] < F.trade_err(off, ev.trades)[0]
    assert F.cut_err(fitted, ev.cuts) < F.cut_err(off, ev.cuts)
    assert len(ev.trades) >= 200 and len(ev.cuts) >= 1000
    # the summer unsigned flag marks only players off the Week-1 roster, not everyone between June 1 and kickoff
    summer = R[R.e_x_offseason > 0]
    assert len(summer) >= 100 and (summer.e_x_unsigned > 0).mean() < 0.15, (summer.e_x_unsigned > 0).mean()


def test_calls_regression_floor():
    ev = F.Evidence.load(); T = ev.Ts[ev.call_boards[LC.CALL_DATES[0]]]
    t = LC.calls(F.call_values(ev, F.load_params()), pd.read_csv(REF).set_index("name").V, set(T.name[T.pos == "QB"]))
    assert sum(x == 0 for _, x in t) >= 85, [n for n, x in t if x > 0]


def test_evidence_resolves_to_inputs():
    R = F.load_inputs(); ev = json.load(open(F.DATA / "evidence.json"))
    keys = set(zip(R.sid, R.date))
    missing = [k for k in ev["cuts"] if tuple(k) not in keys] + [k for t in ev["trades"] for s in t["sides"] for k in s["players"] if tuple(k) not in keys]
    assert not missing, missing[:5]
    assert (R.date == ev["as_of"]).sum() > 600


def _votes(rows):
    buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n")
    w.writerow(FV.FIELDS); w.writerows([[r.get(f, "") for f in FV.FIELDS] for r in rows])
    return FV.read_responses(buf.getvalue())


def _pair(team, q, ans, own="", t="10/27/2026 10:00:00"):
    return dict(timestamp=t, team=team, question_id=q, kind="pair", board_date="2026-10-24", player_a="A1", player_b="B1",
                shown_a=500, shown_b=500, answer=ans, own=own)


def test_votes_dedupe_own_guest_and_team_cap():
    df = FV.weighted(_votes([_pair("Oliverwkw", "q1", "B", t="10/27/2026 09:00:00"), _pair("Oliverwkw", "q1", "A"),
                             _pair("plehv79", "q1", "A", own="A"), _pair(FV.GUEST, "q1", "A"), _pair("Nobody", "q1", "A")]))
    assert len(df) == 3                                              # latest per team, unknown team dropped
    w = df.set_index("team").w
    assert w["plehv79"] < w["Oliverwkw"] and w[FV.GUEST] < w["plehv79"]
    many = FV.weighted(_votes([_pair("Oliverwkw", f"q{i}", "A") for i in range(50)] + [_pair(t, "q0", "A") for t in FV.TEAMS[:3]]))
    share = many.groupby("team").w.sum() / many.w.sum()
    assert share.max() <= FV.TEAM_CAP + 1e-4


def test_vote_strength_grows_needs_teams_and_is_capped():
    one = FV.weighted(_votes([_pair("Oliverwkw", f"q{i}", "A") for i in range(2000)]))
    eight = FV.weighted(_votes([_pair(t, f"q{i}", "A") for t in FV.TEAMS for i in range(400)]))
    few = FV.weighted(_votes([_pair(t, f"q{i}", "A") for t in FV.TEAMS for i in range(3)]))
    assert FV.strength(one) <= FV.VOTE_MAX / FV.FULL_TEAMS + 1e-9      # one team alone: a quarter of the cap at most
    assert FV.strength(few) < FV.strength(eight) < FV.VOTE_MAX
    assert FV.VOTE_MAX < F.W_TRADES and FV.VOTE_MAX < F.W_CUTS


def test_vote_loss_direction():
    C = FV.consensus(FV.weighted(_votes([_pair(t, "q1", "A") for t in FV.TEAMS])))
    c = C.iloc[0].to_dict()
    assert FV.q_loss(c, pd.Series({"A1": 600.0, "B1": 400.0})) == 0
    assert FV.q_loss(c, pd.Series({"A1": 400.0, "B1": 600.0})) > 0
    rows = [dict(timestamp="10/27/2026 10:00:00", team=t, question_id="p1", kind="pair", board_date="2026-10-24", player_a="A1",
                 player_b="B1", shown_a=1000, shown_b=900, verdict_a="lower", amount_a=500, verdict_b="higher") for t in FV.TEAMS]
    sig = FV.signals(_votes(rows))
    assert set(sig.question_id) == {"p1:a", "p1:b"}                  # no pick made -> two price checks, no pair signal
    pr = FV.consensus(FV.weighted(sig)).set_index("question_id")
    assert abs(pr.loc["p1:a", "target"] - 500) < 1 and abs(pr.loc["p1:b", "target"] - 1200) < 1


def test_price_verdicts_are_directions_amounts_are_targets():
    """'too low' / 'too high' say only that the shown value is not right in that direction (no cap, no minimum);
    a typed amount is a target (+-15%); 'about right' is +-15% of the value shown"""
    def check(verdict, amount=""):
        r = dict(timestamp="10/27/2026 10:00:00", team="Oliverwkw", question_id="v1", kind="pair", board_date="2026-10-24",
                 player_a="A1", player_b="B1", shown_a=300, shown_b=300, verdict_a=verdict, amount_a=amount)
        c = FV.consensus(FV.weighted(FV.signals(_votes([r])))).set_index("question_id").loc["v1:a"].to_dict()
        return lambda v: FV.q_loss(c, pd.Series({"A1": float(v)}))
    low = check("higher")
    assert low(301) == 0 and low(1000) == 0 and low(5000) == 0 and low(250) > 0
    high = check("lower")
    assert high(299) == 0 and high(50) == 0 and high(400) > 0
    right = check("right")
    assert right(320) == 0 and right(280) == 0 and right(400) > 0 and right(200) > 0
    typed = check("higher", "2000")
    assert typed(2100) == 0 and typed(1000) > 0 and typed(3000) > 0


def test_qb_rules_reach_only_their_players():
    """QB rules move only QBs; the IR healthy-role blend moves only players on IR/PUP; a QB opening needs a QB who
    has played well (a backup behind the same aging starter gets nothing)"""
    R = F.load_inputs(); p = F.load_params(); T = R[R.date == R.date.max()].reset_index(drop=True)
    X = F.characteristics(T, p["youth_age"]); qb = T.pos.values == "QB"
    for k in ("qb_pedigree", "qb_starter", "qb_played"):
        assert (X[k][~qb] == 0).all(), k
    for k in ("qb_pedigree", "qb_starter", "qb_opening"):
        assert k in F.RAISE_ONLY and F.BOUNDS[k][0] >= 0
    v1, v0 = F.apply_rules(T, p), F.apply_rules(T, dict(p, ir_no_double=0.0))
    moved = np.abs(v1 / np.maximum(v0, 1e-9) - 1) > 1e-9
    assert not moved[X["ir"] == 0].any()
    o = X["qb_played"] * X["opening"]
    assert ((o > 0) <= ((X["qb_played"] > 0) & (X["opening"] > 0))).all()
    # the QB opening fades out with experience: nothing from a QB's fifth season (exp 4) on
    assert (X["qb_early"][T.exp.fillna(0).values >= 4] == 0).all() and (X["qb_early"][T.exp.fillna(0).values <= 1] == 1).all()
    vq, vq0 = F.apply_rules(T, p), F.apply_rules(T, dict(p, qb_opening=0.0))
    assert not (np.abs(vq / np.maximum(vq0, 1e-9) - 1) > 1e-9)[(X["qb_early"] == 0) | ~qb].any()


def test_trade_note_rules_reach_only_their_players():
    """TE line: veteran TEs only; regression: only players past the age start; the replacement line spares 25-and-under (but not a WR who has had no starter's role);
    'no NFL team' never charges a player on a roster"""
    R = F.load_inputs(); p = F.load_params(); T = R.reset_index(drop=True)
    X = F.characteristics(T, p["youth_age"]); age = T.age.values; exp_ = T.exp.fillna(0).values; pos = T.pos.values
    assert np.isnan(X["te_x"][(pos != "TE") | (exp_ < 3)]).all()
    a0 = np.where(pos == "RB", 26.0, 28.0)
    assert (X["regress"][np.nan_to_num(age, nan=0) <= a0] == 0).all() and (X["regress"] >= 0).all() and (X["regress"] <= 1).all()
    assert "te_line" in F.LOWER_ONLY and F.BOUNDS["te_line"][1] <= 0 and 0 <= F.BOUNDS["regress"][0]
    # dud games: receivers only; peak share: young receivers only; slump: non-QBs in their first four seasons
    assert (X["duds"][~np.isin(pos, ["WR", "TE"])] == 0).all() and (X["peak_share"][~np.isin(pos, ["WR", "TE"]) | (np.nan_to_num(age, nan=99) >= 25)] == 0).all()
    assert (X["slump"][(pos == "QB") | (exp_ > 3)] == 0).all()
    assert "duds" in F.LOWER_ONLY and "slump" in F.LOWER_ONLY and "peak_share" in F.RAISE_ONLY
    _, terms, _ = F.apply_rules(T, p, explain=True)
    assert (terms["replacement line"][(np.nan_to_num(age, nan=99) <= 25) & (X["wr_no_role"] == 0)] == 0).all()   # a WR without a starter's role is not spared
    assert (terms["no NFL team"][X["rostered"] > 0] == 0).all()
    assert (terms["te_line"][np.isnan(X["te_x"])] == 0).all()
    # the old-player decline (old_cliff, rec_age) never reaches a QB or a player whose usage did not drop
    assert (X["old_cliff"][pos == "QB"] == 0).all() and (X["rec_age"][pos == "QB"] == 0).all()
    assert "old_cliff" in F.LOWER_ONLY and F.BOUNDS["rec_age"][0] >= 0
    # the boom-week boost reaches only TEs under 29; the WR no-role flag only WRs
    assert (X["boom_week"][(pos != "TE") | (np.nan_to_num(age, nan=99) >= 29)] == 0).all() and "boom_week" in F.RAISE_ONLY
    assert (X["wr_no_role"][pos != "WR"] == 0).all()
    # a fresh start (followed his coach) is offseason-only, non-QB, under 28
    assert (X["fresh"][(pos == "QB") | (np.nan_to_num(age, nan=99) >= 28) | (T.e_x_moved_off.fillna(0).values == 0)] == 0).all() and "fresh_start" in F.RAISE_ONLY
    # ... and only for a player who would otherwise be under FRESH_MAX
    T2 = T[X["fresh"] > 0].reset_index(drop=True)
    if len(T2):
        v_no, t_no, _ = F.apply_rules(T2, dict(p, fresh_start=0.0), explain=True)
        _, t2, _ = F.apply_rules(T2, p, explain=True)
        assert ((t2["fresh_start"] > 0) <= (v_no < F.FRESH_MAX)).all()
    assert (terms["boom_week"][X["boom_week"] == 0] == 0).all()


def test_rookie_backup_reaches_vet_rbs_and_follows_the_workload():
    """non-rookie RBs with a paid same-team rookie only; an early workload drop raises it, a kept workload late fades it,
    a rookie's low usage never matters (the rule reads the vet's own usage)"""
    R = F.load_inputs(); p = F.load_params(); T = R.reset_index(drop=True)
    X = F.characteristics(T, p["youth_age"]); pos = T.pos.values; exp_ = T.exp.fillna(0).values
    assert (X["rookie_backup"][~np.isin(pos, F.BACKUP_POS) | (exp_ < 1) | (T.e_x_rookie_backup.fillna(0).values == 0)] == 0).all()
    assert "rookie_backup" in F.LOWER_ONLY and F.BOUNDS["rookie_backup"][1] <= 0
    base = dict(pos="RB", exp=3.0, age=26.0, injury="", e_x_rookie_backup=250.0)
    rows = [dict(base, e_x_cur_games=np.nan, e_x_rookie_backup_held=np.nan),     # preseason: spend only
            dict(base, e_x_cur_games=2.0, e_x_rookie_backup_held=0.55),          # early, big drop: up to 1.5x
            dict(base, e_x_cur_games=2.0, e_x_rookie_backup_held=1.2),           # early, held: no change
            dict(base, e_x_cur_games=10.0, e_x_rookie_backup_held=1.0),          # late, held: faded out
            dict(base, e_x_cur_games=10.0, e_x_rookie_backup_held=0.6),          # late, lost the job: full
            dict(base, exp=0.0, e_x_cur_games=np.nan, e_x_rookie_backup_held=np.nan),   # a rookie himself: never
            dict(base, pos="WR", e_x_cur_games=np.nan, e_x_rookie_backup_held=np.nan)]
    x = F.characteristics(pd.DataFrame(rows))["rookie_backup"]
    assert np.allclose(x, [1.0, 1.5, 1.0, 0.0, 1.0, 0.0, 0.0])


def test_draft_comp_reaches_mid_priced_players_from_their_third_season():
    base = dict(pos="WR", age=24.0, injury="", e_x_draft_comp=1.0)
    x = F.characteristics(pd.DataFrame([dict(base, exp=e) for e in (0.0, 1.0, 2.0)] + [dict(base, exp=4.0, e_x_draft_comp=2.0)]))["draft_comp"]
    assert np.allclose(x, [0.0, 0.0, 1.0, 1.5])
    assert "draft_comp" in F.LOWER_ONLY and F.BOUNDS["draft_comp"][1] <= 0
    R = F.load_inputs(); p = F.load_params(); _, terms, st = F.apply_rules(R, p, explain=True)
    assert (terms["draft_comp"][(st["base"] <= 150) | (st["base"] >= 800)] == 0).all()   # gated to base $150-800


def test_cheap_deal_reaches_moved_vets_on_cheap_new_deals():
    """a veteran who moved on a cheap deal signed this season (Ekeler 2024: 1.7% of the cap) is docked; a big deal, a QB,
    a player who did not move, or no deal this season is not"""
    base = dict(pos="RB", age=29.0, exp=7.0, injury="", e_x_moved_off=1.0, e_x_vet_deal_cap=0.015)
    rows = [base, dict(base, e_x_vet_deal_cap=0.0225), dict(base, e_x_vet_deal_cap=0.05), dict(base, pos="QB"),
            dict(base, e_x_moved_off=0.0), dict(base, e_x_vet_deal_cap=np.nan), dict(base, pos="WR", e_x_vet_deal_cap=0.015)]
    x = F.characteristics(pd.DataFrame(rows))["cheap_deal"]
    assert np.allclose(x, [1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 1.0])
    assert "cheap_deal" in F.LOWER_ONLY and F.BOUNDS["cheap_deal"][1] <= 0
    R = F.load_inputs(); p = F.load_params(); _, terms, st = F.apply_rules(R, p, explain=True)
    assert (terms["cheap_deal"][st["base"] <= 300] == 0).all()        # a cheap player's cheap deal is no news


def test_older_wr_team_share_is_capped():
    """a WR's share_talent multiplier is capped at share_old_cap from share_old_age (fading in over the 2 years before)"""
    p = F.load_params(); cap = np.log(p["share_old_cap"]); a = p["share_old_age"]
    R = pd.DataFrame([dict(pos=q, age=x, exp=8.0, injury="", V_raw=1500.0, e_x_l0_xfp_share=0.30, e_x_l1_xfp_share=0.30)
                      for q, x in (("WR", a - 3), ("WR", a - 1), ("WR", a + 1), ("RB", a + 1))])
    st = F.apply_rules(R, p, explain=True)[1]["share_talent"]
    assert st[0] > cap and cap < st[1] < st[0] and np.isclose(st[2], cap) and st[3] > cap


def test_undrafted_rookie_fades_out_as_he_plays():
    base = dict(pos="WR", age=22.0, exp=0.0, injury="", e_x_league_undrafted=1.0)
    rows = [dict(base, e_x_cur_games=g) for g in (0.0, 2.0, 4.0)] + [dict(base, exp=1.0), dict(base, e_x_league_undrafted=0.0)]
    x = F.characteristics(pd.DataFrame(rows))["undrafted"]
    assert np.allclose(x, [1.0, 0.5, 0.0, 0.0, 0.0])
    assert "undrafted" in F.LOWER_ONLY and F.BOUNDS["undrafted"][1] <= 0


def test_te_one_off_needs_a_move_and_fades_as_he_plays():
    base = dict(pos="TE", age=30.0, exp=8.0, injury="", e_x_te_one_off=1.0, e_x_moved_off=1.0)
    rows = [base, dict(base, e_x_moved_off=0.0), dict(base, e_x_moved_off=0.0, e_x_new_team=1.0, e_x_cur_games=2.0), dict(base, pos="WR")]
    assert np.allclose(F.characteristics(pd.DataFrame(rows))["te_one_off"], [1.0, 0.0, 0.5, 0.0])
    assert "te_one_off" in F.LOWER_ONLY


def test_team_q_lo_only_lowers_cheap_players_on_bad_teams():
    p = F.load_params(); R = F.load_inputs(); _, terms, st = F.apply_rules(R, p, explain=True)
    t = terms["team_q_lo"]
    assert (t <= 0).all() and (t[st["base"] >= 150] == 0).all() and (t < 0).any()
    assert "team_q_lo" in F.REG_KEYS and F.BOUNDS["team_q_lo"][0] >= 0


def test_qb_paid_is_a_moved_qb_on_a_big_new_deal_until_he_plays():
    base = dict(pos="QB", age=32.0, exp=9.0, injury="", e_x_moved_off=1.0, e_x_vet_deal_cap=0.167)
    rows = [base, dict(base, e_x_vet_deal_cap=0.115), dict(base, e_x_vet_deal_cap=0.05), dict(base, e_x_moved_off=0.0),
            dict(base, e_x_moved_off=0.0, e_x_new_team=1.0, e_x_cur_games=2.0), dict(base, pos="WR")]
    assert np.allclose(F.characteristics(pd.DataFrame(rows))["qb_paid"], [1.0, 0.5, 0.0, 0.0, 0.5, 0.0])
    assert "qb_paid" in F.RAISE_ONLY


def test_young_players_availability_drop_is_floored():
    p = F.load_params(); fl = np.log(p["avail_young_floor"]); a = p["avail_young_age"]
    base = dict(pos="RB", exp=2.0, injury="", V_raw=500.0, e_x_l0_games=2.0, e_x_l1_games=3.0)
    R = pd.DataFrame([dict(base, age=x) for x in (a - 1, a + 1, a + 3)])
    av = F.apply_rules(R, p, explain=True)[1]["availability"]
    assert np.isclose(av[0], fl) and fl > av[1] > av[2] and av[2] < fl


def test_ypc_bad_starts_in_the_third_season():
    base = dict(pos="RB", age=25.0, injury="", e_x_ypc_2y=3.7)
    x = F.characteristics(pd.DataFrame([dict(base, exp=e) for e in (1.0, 2.0, 3.0)]))["ypc_bad"]
    assert np.allclose(x, [0.0, 1.0, 1.0])


def test_current_usage_fades_in_over_four_games():
    """a TE's usage for the TE line moves from last season's to this season's a quarter per game, not all at once at 4"""
    base = dict(pos="TE", exp=5.0, age=28.0, e_x_l0_xfp_pg=8.0, e_x_l1_xfp_pg=8.0, e_x_cur_xfp_pg=14.0, injury="")
    T = pd.DataFrame([dict(base, e_x_cur_games=g) for g in (0, 1, 2, 4, 6)])
    T.loc[0, "e_x_cur_xfp_pg"] = np.nan
    tx = F.characteristics(T)["te_x"]
    assert tx[0] == 8.0 and tx[3] == 14.0 and tx[4] == 14.0
    assert tx[0] < tx[1] < tx[2] < tx[3]


def test_page_files_in_sync_with_inputs_and_params():
    R = F.load_inputs(); p = F.load_params(); T = F.board(R, p)
    b = json.load(open(_ROOT / "docs" / "rate" / "board.json"))
    q = json.load(open(_ROOT / "docs" / "rate" / "questions.json"))
    assert b["as_of"] == q["as_of"] == T.date.iloc[0]
    page = {x["sid"]: x["value"] for x in b["players"]}
    assert all(abs(page[s] - v) <= 1 for s, v in zip(T.sid, T.V)), "run: python scripts/faab_value.py publish"
    _, _, stages = F.apply_rules(T, p, explain=True)
    assert [x["id"] for x in FV.questions(T, stages, T.date.iloc[0])] == [x["id"] for x in q["questions"]]
    ids = [x["id"] for x in q["questions"]]
    assert len(ids) == len(set(ids)) and all(x["kind"] == "pair" and x["a"] in page and x["b"] in page for x in q["questions"])
    slots = [p["value"] for p in b["picks"]]
    assert b["picks"][0]["slot"] == "1.01" and slots == sorted(slots, reverse=True)


def test_one_submission_gives_pair_and_two_price_signals():
    r = dict(_pair("Oliverwkw", "q9", "B", own="A"), verdict_a="right", verdict_b="", amount_b="$1,200", why="younger")
    sig = FV.signals(_votes([r])).set_index("question_id")
    assert list(sig.index) == ["q9", "q9:a", "q9:b"]
    assert sig.loc["q9:a", "own"] == "A" and sig.loc["q9:b", "own"] == "" and sig.loc["q9:b", "player_a"] == "B1"
    c = FV.consensus(FV.weighted(sig.reset_index())).set_index("question_id")
    assert abs(c.loc["q9:b", "target"] - 1200) < 1


def test_normalise_reads_form_headers():
    text = "Timestamp,Team,Question ID,Kind,Board date,Answer\n10/27/2026 10:00:00,Oliverwkw,abc,pair,2026-10-24,A\n"
    df = FV.read_responses(FV.normalise(text))
    assert df.loc[0, "team"] == "Oliverwkw" and df.loc[0, "question_id"] == "abc" and list(df.columns) == FV.FIELDS


def test_match_names_finds_near_misses():
    # fixed names, no data: the lookup must not depend on the weekly rebuild
    names = ["Kenneth Walker III", "P.J. Walker", "A.J. Brown", "Ja'Marr Chase", "Jaxson Dart", "Travis Etienne Jr.", "Trevor Etienne"]
    assert F.match_names(names, "a.j. brown") == ["A.J. Brown"]
    assert F.match_names(names, "aj brown") == ["A.J. Brown"]                   # punctuation ignored
    assert F.match_names(names, "Jamarr Chase") == ["Ja'Marr Chase"]
    assert F.match_names(names, "Kenneth Walker") == ["Kenneth Walker III"]     # substring before fuzzy
    assert F.match_names(names, "etienne") == ["Travis Etienne Jr.", "Trevor Etienne"]
    assert F.match_names(names, "Jaxon Dart")[0] == "Jaxson Dart"               # typo, best first
    names += ["Christian McCaffrey", "Luke McCaffrey", "Jaxon Smith-Njigba", "Brian Thomas Jr.", "De'Von Achane"]
    assert F.match_names(names, "CMC") == ["Christian McCaffrey"]               # initials, last word may run longer
    assert F.match_names(names, "jsn") == ["Jaxon Smith-Njigba"] and F.match_names(names, "BTJ") == ["Brian Thomas Jr."]
    assert F.match_names(names, "Deven Achaine")[0] == "De'Von Achane"
    assert F.match_names(names, "xqz") == [] and F.match_names(names, "") == []


TESTS = [test_sign_locks_hold_for_bounds_and_params, test_board_reproduces_and_beats_rules_off_on_trades_and_cuts,
         test_calls_regression_floor, test_evidence_resolves_to_inputs, test_votes_dedupe_own_guest_and_team_cap,
         test_vote_strength_grows_needs_teams_and_is_capped, test_vote_loss_direction, test_page_files_in_sync_with_inputs_and_params,
         test_one_submission_gives_pair_and_two_price_signals,
         test_normalise_reads_form_headers, test_match_names_finds_near_misses]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall faab value checks passed")


def test_each_call_group_is_judged_on_the_board_of_its_day():
    ev = F.Evidence.load()
    assert set(ev.call_boards) == set(LC.CALL_DATES) and all(gd <= d for d, gd in ev.call_boards.items())
    v = F.call_values(ev, F.load_params())[LC.CALL_DATES[0]]
    lo, hi = v.copy(), v.copy(); lo["Michael Wilson"], hi["Michael Wilson"] = 300.0, 500.0
    miss = lambda b: dict(LC.calls(b))["Michael Wilson up (>= $400)"]       # a second-review call (2026-10-25)
    assert miss(lo) > 0 and miss(hi) == 0
    # the 2026-10-25 call reads the 10-25 board, not the 10-24 one, and not a later one
    assert miss({"2026-10-24": lo, "2026-10-25": hi, "2026-10-26": lo}) == 0
    assert miss({"2026-10-24": hi, "2026-10-25": lo, "2026-10-26": hi}) > 0
    # no board for its day: the latest earlier one stands in
    assert miss({"2026-10-24": hi, "2026-10-28": lo}) == 0


def test_overtaken_reaches_aging_players_and_fades_as_he_plays():
    base = dict(pos="WR", age=31.0, exp=8.0, injury="", e_x_overtaken=1.0)
    rows = [base, dict(base, age=28.0), dict(base, age=26.0), dict(base, e_x_cur_games=4.0), dict(base, e_x_overtaken=0.0)]
    assert np.allclose(F.characteristics(pd.DataFrame(rows))["overtaken"], [1.0, 0.5, 0.0, 0.5, 0.0])
    assert "overtaken" in F.LOWER_ONLY and F.load_params()["overtaken"] < 0


def test_post_rules_dock_the_lesser_of_two_big_wrs_and_cap_fast_risers():
    R = pd.DataFrame(dict(sid=["a", "b", "c", "a"], date=["2024-05-07", "2024-05-07", "2024-05-07", "2024-04-02"], pos=["WR", "WR", "RB", "WR"],
                          e_x_cur_games=[0.0] * 4, e_x_l0_tgt_share=[0.30, 0.20, 0.10, 0.30], wr_mate=["b", "a", "", ""]))
    mate, lag = F.links(R)
    assert list(mate) == [1, 0, -1, -1] and list(lag) == [3, -1, -1, -1]
    V = np.array([3600.0, 2200.0, 1000.0, 1000.0])
    out = F.post_rules(V, R, dict(wr_pair=-2.0), mate, lag)
    assert np.allclose(out, [3600.0, 2200.0 * np.exp(-2.0 * 0.30), 1000.0, 1000.0])      # the lesser WR, by the other's share
    out = F.post_rules(V, R, dict(lag_cap=2.5, lag_floor=100.0), mate, lag)
    assert np.allclose(out, [2500.0, 2200.0, 1000.0, 1000.0])                             # a's row 4 weeks earlier was $1,000
    assert "wr_pair" in F.LOWER_ONLY and F.load_params()["lag_cap"] >= 50          # the cap stays off until Oliver says


def test_wr_talent_is_receivers_only_and_young_qbs_rbs_have_their_own_upside_rule():
    R = F.load_inputs(); X = F.characteristics(R)
    assert (X["wr_talent"][~R.pos.isin(["WR", "TE"]).values] == 0).all()
    yu = X["young_upside"]
    assert (yu[~R.pos.isin(["QB", "RB"]).values] == 0).all() and (yu[R.exp.values > F.UPSIDE_EXP] == 0).all() and (yu > 0).any()
    assert "young_upside" in F.RAISE_ONLY


def test_young_elite_is_rbs_wrs_under_24_with_elite_production():
    base = dict(pos="WR", age=23.0, exp=2.0, injury="", e_x_gp_cur=6.0, e_x_ppg_cur=22.0, e_x_ppg_l0=15.0)
    rows = [base, dict(base, age=24.5), dict(base, age=25.5), dict(base, pos="QB"), dict(base, e_x_ppg_cur=16.0)]
    X = F.characteristics(pd.DataFrame(rows))["young_elite"]
    assert X[0] == 1.0 and 0 < X[1] < 1 and X[2] == 0 and X[3] == 0 and X[4] == 0, X
    assert "young_elite" in F.RAISE_ONLY


def test_te_top3_eases_the_te_line():
    R = F.load_inputs(); p = F.load_params()
    _, t1, _ = F.apply_rules(R, p, explain=True); _, t0, _ = F.apply_rules(R, dict(p, te_top3=0.0), explain=True)
    hit = np.nan_to_num(F.col(R, "e_x_te_top3")) > 0
    assert (t1["te_line"] >= t0["te_line"] - 1e-12).all() and (t1["te_line"][~hit] == t0["te_line"][~hit]).all()


def test_rookie_r1_is_a_late_round_rb_behind_a_first_round_rookie():
    base = dict(pos="RB", age=23.0, exp=1.0, injury="", e_x_draft_comp_r1=1.0, e_x_draft_pick=np.nan)
    rows = [base, dict(base, e_x_draft_pick=20.0), dict(base, exp=0.0), dict(base, pos="WR"), dict(base, e_x_draft_comp_r1=0.0)]
    assert np.allclose(F.characteristics(pd.DataFrame(rows))["rookie_r1"], [1, 0, 0, 0, 0])
    assert "rookie_r1" in F.LOWER_ONLY and F.load_params()["rookie_r1"] < 0


def test_r1_wr_is_a_veteran_wr_whose_team_took_a_first_round_wr():
    base = dict(pos="WR", age=28.0, exp=5.0, injury="", e_x_draft_comp_r1=1.0)
    rows = [base, dict(base, exp=1.0), dict(base, pos="TE"), dict(base, e_x_draft_comp_r1=0.0)]
    assert np.allclose(F.characteristics(pd.DataFrame(rows))["r1_wr"], [1, 0, 0, 0])
    assert "r1_wr" in F.LOWER_ONLY and F.load_params()["r1_wr"] < 0


def test_a_second_year_rbs_rookie_year_is_a_lighter_usage_prior():
    base = dict(pos="RB", age=23.0, exp=1.0, injury="", e_x_cur_games=4.0, e_x_cur_xfp_pg=19.5, e_x_l0_xfp_pg=4.2)
    rows = [base, dict(base, exp=2.0), dict(base, pos="WR")]
    u = F.characteristics(pd.DataFrame(rows))["usage"]
    assert u[0] > u[1] and u[2] < u[0] and F.ROOKIE_PRIOR["RB"] < 1.0
