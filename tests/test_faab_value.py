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
    R = F.load_inputs(); T = F.board(R, F.load_params(), as_of=LC.CALLS_DATE)
    t = LC.calls(T.set_index("name").V, pd.read_csv(REF).set_index("name").V, set(T.name[T.pos == "QB"]))
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
