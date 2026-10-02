"""Wins added (trades + add_drops): the rule, on synthetic weeks and on the data.

The synthetic cases pin each part of the rule in `lotg_support.wins_added`:

  * the lineup rule — an arrival may displace a starter and players move
    between slots to fit him (an RB leaves the RB slot for the flex so a WR can
    come in); a bench player only fills a slot a departed starter left open;
    nobody started anywhere counts for at most 1.5 x his last-3-game average;
    every substitution must be plausible (incoming 3-game average >= outgoing
    minus 5); a player with fewer than 3 prior games moves in only if he
    really started that week, and can always be moved out; every cleared slot
    is filled before points are counted; no real starter sits while a real
    bench player starts;
  * the per-week result flip against the real opponent, ±1;
  * the opponent losing a given-up player he started (and the mirror row);
  * lineage through a later trade at its KTC share, read as a probability;
  * the given-up count stops once the league lets him go (4 straight weeks
    on no roster) or the team re-acquires him.

The data guards: every real lineup 2020-today is legal under its season's
template and every PF is its starters' points (+5 in a semifinal) — the two
facts the counterfactual search stands on — and, once the column is in the
committed exports, a recompute of a sample of rows matches it. The sample is
restricted to rows whose value is settled by completed seasons and whose
lineage never passes through a later trade (so KTC cannot move it).

Run: python tests/test_wins_added.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import wins_added as W  # noqa: E402

SEASON = 2023
SLOTS = (("RB",), ("WR",), ("RB", "WR", "TE"))
POS = {"r1": "RB", "r2": "RB", "w1": "WR", "w2": "WR", "w3": "WR", "b1": "RB", "b2": "WR",
       "o1": "RB", "o2": "WR", "o3": "RB", "ob": "RB", "s": "RB", "d": "WR",
       "x": "WR", "y": "RB", "z": "RB", "c1": "RB", "c2": "WR", "c3": "WR"}


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _tw(team, starters, bench, pts, opp):
    pf = round(sum(pts.get(p, 0.0) for p in starters), 2)
    return W.TeamWeek(team=team, starters=tuple(starters), players=frozenset(starters) | frozenset(bench),
                      pf=pf, offset=0.0, opponent=opp)


def _league(weeks, pts_by_week, nfl=None, unproven=(), slots=SLOTS, pos=None):
    """weeks: {key: [(team, starters, bench, opp)]}; pts_by_week: {key: {pid: pts}}."""
    built = {k: {t: _tw(t, s, b, pts_by_week[k], o) for t, s, b, o in rows} for k, rows in weeks.items()}
    pos = {**POS, **(pos or {})}
    elig = {SEASON: {p: frozenset({ps}) for p, ps in pos.items()}}
    days = {k: f"{k[0]}-10-{k[1]:02d}" for k in weeks}
    rostered = {k: {p: v for p, v in pts_by_week[k].items()
                    if any(p in tw.players for tw in built[k].values())} for k in weeks}
    nfl = {p: dict(g) for p, g in (nfl or {}).items()}
    for p in pos:                               # a proven 10-a-game history unless given one
        if p not in nfl:
            nfl[p] = {(SEASON - 1, 15): 10.0, (SEASON - 1, 16): 10.0, (SEASON - 1, 17): 10.0}
    for p in unproven:
        nfl.pop(p, None)
    for k, pts in pts_by_week.items():          # unrostered players score from "nflverse"
        for p, v in pts.items():
            if p not in rostered[k]:
                nfl.setdefault(p, {})[k] = v
    return W.League(built, rostered, {SEASON: slots}, elig, pos, nfl, days)


K1 = (SEASON, 1)


def test_arrival_displaces_and_players_change_slots():
    # r1 in the RB slot (5), w1 WR (10), r2 in the flex (12). A WR arrival who
    # really started elsewhere (20) can only get in if r2 slides to the RB slot
    # and r1 sits: 10 + 12 + 20.
    pts = {"r1": 5, "w1": 10, "r2": 12, "w2": 20, "c1": 1, "c2": 1, "c3": 1}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], [], "C"), ("C", ["c1", "c2", "w2"], [], "A")]}, {K1: pts})
    got = W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w2"])
    assert got == 42.0, got


def test_bench_only_fills_open_slots_and_is_capped():
    # b1 booms for 30 on the bench, averaging 8 over his last 3 games -> cap 12.
    pts = {"r1": 5, "w1": 10, "r2": 12, "b1": 30}
    hist = {"b1": {(SEASON - 1, 15): 8.0, (SEASON - 1, 16): 8.0, (SEASON - 1, 17): 8.0}}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], ["b1"], None)]}, {K1: pts}, hist)
    tw = lg.team_week(K1, "A")
    assert W.cf_lineup_points(lg, K1, tw, set(), []) == 27.0, "a bench player must not displace a starter"
    assert W.cf_lineup_points(lg, K1, tw, {"r2"}, []) == 5 + 10 + 12.0, "forced fill, capped at 1.5 x 8"


def test_arrival_cap_depends_on_whether_anyone_started_him():
    hist = {"w3": {(SEASON - 1, 15): 6.0, (SEASON - 1, 16): 6.0, (SEASON - 1, 17): 6.0}}
    pts = {"r1": 5, "w1": 10, "r2": 12, "w3": 25, "c1": 1, "c2": 1, "c3": 1}
    # On waivers (nobody started him): capped at 9, so he replaces r1 for +4.
    lg = _league({K1: [("A", ["r1", "w1", "r2"], [], None)]}, {K1: pts}, hist)
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w3"]) == 31.0
    # Started by another team that week: full points.
    lg = _league({K1: [("A", ["r1", "w1", "r2"], [], None), ("C", ["c1", "c2", "w3"], [], None)]}, {K1: pts}, hist)
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w3"]) == 47.0


def test_implausible_substitution_is_not_made():
    # w3 scored 30 but averages 3; the weakest starter he could replace (r1)
    # averages 15. Nobody would have started him over r1: no change.
    hist = {"w3": {(SEASON - 1, 15): 3.0, (SEASON - 1, 16): 3.0, (SEASON - 1, 17): 3.0},
            "r1": {(SEASON - 1, 15): 15.0, (SEASON - 1, 16): 15.0, (SEASON - 1, 17): 15.0},
            "w1": {(SEASON - 1, 15): 15.0, (SEASON - 1, 16): 15.0, (SEASON - 1, 17): 15.0},
            "r2": {(SEASON - 1, 15): 15.0, (SEASON - 1, 16): 15.0, (SEASON - 1, 17): 15.0}}
    pts = {"r1": 5, "w1": 10, "r2": 12, "w3": 30, "c1": 1, "c2": 1, "c3": 1}
    weeks = {K1: [("A", ["r1", "w1", "r2"], [], None), ("C", ["c1", "c2", "w3"], [], None)]}
    lg = _league(weeks, {K1: pts}, hist)
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w3"]) == 27.0
    # Averaging 11 (within 5 of 15) he is a reasonable start: in for r1.
    hist["w3"] = {(SEASON - 1, 15): 11.0, (SEASON - 1, 16): 11.0, (SEASON - 1, 17): 11.0}
    lg = _league(weeks, {K1: pts}, hist)
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w3"]) == 52.0


def test_unproven_players_move_in_only_if_they_really_started():
    pts = {"r1": 5, "w1": 10, "r2": 12, "w2": 20, "w3": 22, "b1": 9, "c1": 1, "c2": 1, "c3": 1}
    weeks = {K1: [("A", ["r1", "w1", "r2"], ["b1"], None), ("C", ["c1", "c2", "w2"], [], None)]}
    # A rookie (fewer than 3 prior games) who really started that week may move in [per user]...
    lg = _league(weeks, {K1: pts}, unproven=["w2"])
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w2"]) == 42.0
    # ...one who did not (on waivers, w3) may not...
    lg = _league(weeks, {K1: pts}, pos={"w3": "WR"}, unproven=["w3"])
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w3"]) == 27.0
    # ...nor a rookie on the bench as a forced fill: r2's slot stays empty.
    lg = _league(weeks, {K1: pts}, unproven=["b1"])
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), {"r2"}, []) == 15.0
    # A rookie STARTER can be displaced by any proven arrival.
    lg = _league(weeks, {K1: pts}, unproven=["r1"])
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), set(), ["w2"]) == 42.0


def test_two_open_slots_are_judged_against_the_two_best_options():
    # r2 (RB, flex) and w1 (WR) both leave. Fillers: b1 (RB, avg 18) and b2
    # (WR, avg 9). Judged against the single best (18) b2 fails and the WR
    # slot stays empty; with two holes the bar is the 2nd-best (9 - 5).
    hist = {p: {(SEASON - 1, 15): a, (SEASON - 1, 16): a, (SEASON - 1, 17): a}
            for p, a in (("b1", 18.0), ("b2", 9.0), ("r1", 10.0), ("w1", 10.0), ("r2", 10.0))}
    pts = {"r1": 5, "w1": 10, "r2": 12, "b1": 14, "b2": 8}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], ["b1", "b2"], None)]}, {K1: pts}, hist)
    assert W.cf_lineup_points(lg, K1, lg.team_week(K1, "A"), {"w1", "r2"}, []) == 5 + 14 + 8.0


def _h(a):
    return {(SEASON - 1, 15): a, (SEASON - 1, 16): a, (SEASON - 1, 17): a}


SF = (("QB",), ("WR",), ("QB", "RB", "WR", "TE"))   # QB, WR, superflex


def test_a_bench_player_never_replaces_a_starter_by_reshuffling():
    # w1 (WR) leaves. Arrival a (WR, 20) can fill the WR slot. Bench QB q2 (30)
    # could only get in by benching the real QB q1 — the old count-based rule
    # allowed it (a "displaces" q1 while q3 slides to QB and q2 takes the
    # superflex): 60. Slot-aware, a bench player only fills a cleared slot,
    # and q2 cannot play WR: q1 + a + q3 = 35.
    pos = {"q1": "QB", "q2": "QB", "q3": "QB", "a": "WR", "c1": "QB", "c2": "WR", "c3": "WR"}
    hist = {"q1": _h(15.0), "q3": _h(10.0), "q2": _h(20.0), "a": _h(15.0), "w1": _h(10.0)}
    pts = {"q1": 5, "w1": 10, "q3": 10, "q2": 30, "a": 20, "c1": 1, "c2": 1, "c3": 1}
    lg = _league({K1: [("A", ["q1", "w1", "q3"], ["q2"], None), ("C", ["c1", "c2", "a"], [], None)]},
                 {K1: pts}, hist, slots=SF, pos=pos)
    pts_cf, lineup = W.cf_lineup(lg, K1, lg.team_week(K1, "A"), {"w1"}, ["a"])
    assert (pts_cf, sorted(lineup)) == (35.0, ["a", "q1", "q3"]), (pts_cf, lineup)


def test_a_real_starter_never_sits_behind_a_real_bench_player():
    # LWebs53 2022 wk 5's shape: WR w1 (the return) leaves; given-up WR a could
    # fill his slot or displace RB r2 in the flex; bench WR b scored more than
    # r2. "a into the flex, b into w1's slot" would sit real starter r2 behind
    # real bench player b — not allowed [per user]: a takes w1's slot, r2 stays.
    pts = {"r1": 5, "w1": 10, "r2": 6, "a": 20, "b": 15, "c1": 1, "c2": 1, "c3": 1}
    pos = {"b": "WR", "a": "WR"}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], ["b"], None), ("C", ["c1", "c2", "a"], [], None)]},
                 {K1: pts}, pos=pos)
    pts_cf, lineup = W.cf_lineup(lg, K1, lg.team_week(K1, "A"), {"w1"}, ["a"])
    assert (pts_cf, sorted(lineup)) == (31.0, ["a", "r1", "r2"]), (pts_cf, lineup)


def test_every_cleared_slot_is_filled_even_by_a_zero():
    # w1 leaves; the only WR on the bench scored 0. The slot is still filled.
    pts = {"r1": 5, "w1": 10, "r2": 12, "w2": 0}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], ["w2"], None)]}, {K1: pts})
    pts_cf, lineup = W.cf_lineup(lg, K1, lg.team_week(K1, "A"), {"w1"}, [])
    assert (pts_cf, sorted(lineup)) == (17.0, ["r1", "r2", "w2"]), (pts_cf, lineup)


def test_four_for_one_fills_every_cleared_slot_with_a_different_player():
    # The shape of shmuel256's 2022 Jefferson trade: four received starters
    # out in one week, Jefferson (j) back, bench covers the rest — four
    # cleared slots, four different players.
    slots = (("QB",), ("RB",), ("WR",), ("WR",), ("QB", "RB", "WR", "TE"))
    pos = {"q1": "QB", "r1": "RB", "w1": "WR", "w2": "WR", "s1": "QB", "j": "WR",
           "bq": "QB", "br": "RB", "bw": "WR", "c1": "QB", "c2": "WR", "c3": "WR", "c4": "WR", "c5": "RB"}
    pts = {"q1": 20, "r1": 15, "w1": 14, "w2": 13, "s1": 18, "j": 25, "bq": 12, "br": 9, "bw": 8,
           "c1": 1, "c2": 1, "c3": 1, "c4": 1, "c5": 1}
    weeks = {K1: [("A", ["q1", "r1", "w1", "w2", "s1"], ["bq", "br", "bw"], None),
                  ("C", ["c1", "c5", "c2", "j", "c3"], ["c4"], None)]}
    lg = _league(weeks, {K1: pts}, slots=slots, pos=pos)
    pts_cf, lineup = W.cf_lineup(lg, K1, lg.team_week(K1, "A"), {"q1", "r1", "w1", "w2"}, ["j"])
    assert sorted(lineup) == ["bq", "br", "bw", "j", "s1"], lineup
    assert pts_cf == 18 + 25 + 12 + 9 + 8


def _move(team, day, received=(), sent=(), kind="trade", senders=None, stamp=None):
    return W.Move(sheet="trades" if kind == "trade" else "add_drops", index=0, team=team,
                  stamp=stamp or f"{day} 12:00:00", day=day, kind=kind,
                  received=[W.Asset(label=p, pid=p) for p in received],
                  sent=[W.Asset(label=p, pid=p) for p in sent], senders=dict(senders or {}))


def test_dropping_a_player_who_would_have_won_the_game_is_minus_one():
    # A dropped d before week 1; d (on waivers, 3-game average 25) scores 30.
    # A really lost 27-40; with d in r1's place (5) A scores 52 and wins.
    hist = {"d": {(SEASON - 1, 15): 25.0, (SEASON - 1, 16): 25.0, (SEASON - 1, 17): 25.0}}
    pts = {"r1": 5, "w1": 10, "r2": 12, "d": 30, "o1": 20, "o2": 10, "o3": 10}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], [], "B"), ("B", ["o1", "o2", "o3"], [], "A")]}, {K1: pts}, hist)
    drop = _move("A", f"{SEASON}-09-01", sent=["d"], kind="add_drop")
    assert W.wins_added_for(drop, [], lg) == -1.0


def test_opponent_loses_the_player_and_the_mirror_row_agrees():
    # A traded s to B; B started s (25) and beat A 40-27. Undo it: A plays s
    # over r1 (+20 -> 47) and B fills s's slot from its bench (ob, 3 -> 18).
    pts = {"r1": 5, "w1": 10, "r2": 12, "s": 25, "o2": 10, "o3": 5, "ob": 3}
    lg = _league({K1: [("A", ["r1", "w1", "r2"], [], "B"), ("B", ["s", "o2", "o3"], ["ob"], "A")]}, {K1: pts})
    a_side = _move("A", f"{SEASON}-09-01", sent=["s"])
    b_side = _move("B", f"{SEASON}-09-01", received=["s"], senders={"s": "A"})
    assert W.wins_added_for(a_side, [], lg) == -1.0
    assert W.wins_added_for(b_side, [], lg) == 1.0


def test_lineage_through_a_later_trade_earns_its_ktc_share():
    # m1: A gets x. m2: A sends x (KTC 100) + y (300) for z. z starts in week 1
    # and is why A wins 37-35; without z, r2's slot goes to the bench (b1, 2)
    # and A loses. m1 is owed 100/400 of z: 0.25 of that win. m2 owns all of it.
    pts = {"r1": 5, "w1": 10, "z": 22, "b1": 2, "x": 0, "y": 0, "o1": 15, "o2": 10, "o3": 10}
    lg = _league({K1: [("A", ["r1", "w1", "z"], ["b1"], "B"), ("B", ["o1", "o2", "o3"], [], "A")]}, {K1: pts})
    m1 = _move("A", f"{SEASON}-08-01", received=["x"], stamp=f"{SEASON}-08-01 12:00:00")
    m2 = _move("A", f"{SEASON}-08-15", received=["z"], sent=["x", "y"], stamp=f"{SEASON}-08-15 12:00:00")
    ktc = {"x": 100.0, "y": 300.0}
    value = lambda a, day: ktc.get(a.pid)
    items = W.lineage(m1, [m2], value)
    assert [(i.pid, round(i.share, 2)) for i in items] == [("x", 1.0), ("z", 0.25)]
    assert W.wins_added_for(m1, [m2], lg, value) == 0.25
    assert W.wins_added_for(m2, [], lg, value) == 1.0


def test_dropping_ends_the_lineage():
    m1 = _move("A", f"{SEASON}-08-01", received=["x"], stamp=f"{SEASON}-08-01 12:00:00")
    m2 = _move("A", f"{SEASON}-08-15", received=["z"], sent=["x"], kind="add_drop",
               stamp=f"{SEASON}-08-15 12:00:00")
    items = W.lineage(m1, [m2], None)
    assert [(i.pid, i.ended) for i in items] == [("x", f"{SEASON}-08-15")], "an add/drop does not pass lineage on"


def test_a_reacquired_player_belongs_to_the_reacquiring_move():
    # A dropped d, later picked him back up (m2) and started him. While he is
    # really on A, the drop adds nothing that week; the re-add owns the week.
    pts = {"r1": 5, "w1": 10, "d": 30, "b1": 2, "o1": 20, "o2": 10, "o3": 10}
    lg = _league({K1: [("A", ["r1", "w1", "d"], ["b1"], "B"), ("B", ["o1", "o2", "o3"], [], "A")]}, {K1: pts})
    m1 = _move("A", f"{SEASON}-08-01", sent=["d"], kind="add_drop", stamp=f"{SEASON}-08-01 12:00:00")
    m2 = _move("A", f"{SEASON}-08-20", received=["d"], kind="add_drop", stamp=f"{SEASON}-08-20 12:00:00")
    assert W.wins_added_for(m1, [m2], lg) == 0.0
    assert W.wins_added_for(m2, [], lg) == 1.0


def _weeks(n, a_starters, a_bench=(), b_starters=("o1", "o2", "o3")):
    return {(SEASON, w): [("A", list(a_starters), list(a_bench), "B"), ("B", list(b_starters), [], "A")]
            for w in range(1, n + 1)}


def test_the_count_stops_once_the_league_lets_him_go():
    # d dropped before week 1 and nobody rosters him for weeks 1-4. In week 5
    # he scores 40 and would win A the game — but by then the league has let
    # him go for 4 straight weeks, so the drop no longer owns him.
    hist = {"d": {(SEASON - 1, 15): 30.0, (SEASON - 1, 16): 30.0, (SEASON - 1, 17): 30.0}}
    # d plays no NFL game in weeks 1-4 (no stat line), so his 3-game cap still
    # reads last season's 30.
    pts = {k: {"r1": 5, "w1": 10, "r2": 12, "o1": 20, "o2": 10, "o3": 10} for k in _weeks(5, [])}
    pts[(SEASON, 5)]["d"] = 40
    lg = _league(_weeks(5, ["r1", "w1", "r2"]), pts, hist)
    drop = _move("A", f"{SEASON}-09-01", sent=["d"], kind="add_drop")
    assert W._given_up(drop, lg) == [("d", (SEASON, 1), (SEASON, 4))]
    assert W.wins_added_for(drop, [], lg) == 0.0
    # Rostered somewhere in week 3, the run restarts and week 5 still counts.
    weeks = _weeks(5, ["r1", "w1", "r2"])
    weeks[(SEASON, 3)].append(("C", ["c1", "c2", "c3"], ["d"], None))
    pts[(SEASON, 3)].update({"c1": 1, "c2": 1, "c3": 1})
    lg = _league(weeks, pts, hist)
    assert W.wins_added_for(drop, [], lg) == -1.0


def test_reacquiring_a_player_ends_the_earlier_moves_count():
    # A drops d (m1), picks him back up in week 2 (m2), drops him again in
    # week 3 (m3). From the re-add on, m1 never owns d again — week 5 is m3's.
    hist = {"d": {(SEASON - 1, 15): 30.0, (SEASON - 1, 16): 30.0, (SEASON - 1, 17): 30.0}}
    weeks = _weeks(5, ["r1", "w1", "r2"])
    for w in range(1, 6):                       # d stays rostered by C throughout
        weeks[(SEASON, w)].append(("C", ["c1", "c2", "c3"], ["d"], None))
    pts = {k: {"r1": 5, "w1": 10, "r2": 12, "d": 0, "o1": 20, "o2": 10, "o3": 10,
               "c1": 1, "c2": 1, "c3": 1} for k in weeks}
    pts[(SEASON, 5)]["d"] = 40
    lg = _league(weeks, pts, hist)
    m1 = _move("A", f"{SEASON}-09-01", sent=["d"], kind="add_drop", stamp=f"{SEASON}-09-01 12:00:00")
    m2 = _move("A", f"{SEASON}-10-02", received=["d"], kind="add_drop", stamp=f"{SEASON}-10-02 12:00:00")
    m3 = _move("A", f"{SEASON}-10-03", sent=["d"], kind="add_drop", stamp=f"{SEASON}-10-03 12:00:00")
    assert W._given_up(m1, lg, [m2, m3]) == [("d", (SEASON, 1), (SEASON, 1))]
    assert W.wins_added_for(m1, [m2, m3], lg) == 0.0
    assert W.wins_added_for(m3, [], lg) == -1.0


def test_per_season_rate_is_wins_times_17_over_games_since_the_move():
    assert W.per_season(-1.0, 1) == -17.0, "a loss the week after the move reads -17"
    assert W.per_season(-1.0, 2) == -8.5
    assert W.per_season(3.0, 51) == 1.0
    assert W.per_season(0.0, 0) is None, "N/A before the move's first game"
    lg = _league(_weeks(4, ["r1", "w1", "r2"]),
                 {k: {"r1": 5, "w1": 10, "r2": 12, "o1": 1, "o2": 1, "o3": 1} for k in _weeks(4, [])})
    assert W.games_elapsed(_move("A", f"{SEASON}-10-02"), lg) == 3   # weeks 2-4


def test_the_rate_waits_five_weeks_on_the_email_boards():
    # The weekly email keeps a move off a RATE board until 5 NFL weeks have
    # been played since it (digest.BoardGate, EVENT_MIN_WEEKS) — the same hold
    # every other rate on the move sheets gets. Wins added itself is a count.
    from lotg_support import digest as D
    assert D.is_rate_stat(W.RATE_COLUMN) and not D.is_counting_stat(W.RATE_COLUMN)
    assert D.is_counting_stat(W.COLUMN)
    assert D.EVENT_MIN_WEEKS == 5


# ---------------------------------------------------------------------------
# Data guards
# ---------------------------------------------------------------------------
def _have_data() -> bool:
    return (_ROOT / "exports" / "team_week.csv").exists() and (_ROOT / "exports" / "snapshot").exists()


def test_real_lineups_are_legal_and_pf_is_starters_plus_bonus():
    if not _have_data():
        return _skip("exports/ or exports/snapshot absent")
    from lotg_support import inquiry as Q
    lg = W.load_league(Q.load_sheet("team_week"), {})
    done = set(Q.completed_seasons()) | {2020}
    weeks = [k for k in lg.order if k[0] in done]
    assert len(weeks) >= 16 + 17 * 4, f"only {len(weeks)} completed weeks loaded"
    bad = [m for m in W.check_offsets(lg) + W.check_real_lineups_legal(lg) if int(m[1:5]) in done]
    assert not bad, f"{len(bad)} team-weeks break the counterfactual's footing: {bad[:5]}"
    print(f"  {len(weeks)} completed weeks: every lineup legal, every PF = starters (+5)")


def test_counterfactual_lineups_keep_the_rules_on_real_moves():
    """Every counterfactual lineup, week by week, for both sides of the
    2022-09-27 Jefferson 4-for-1 and a spread of other moves:
      * drawn only from the week's real roster minus the move's return, plus
        what it gave up;
      * no real starter (still on the roster) sits while a real bench player
        starts [per user];
      * no cleared slot left empty while an eligible proven player could fill it;
      * nobody unproven (fewer than 3 prior NFL games) moved in unless he
        really started that week.
    Needs no Wins added column — it checks the lineups, not the totals."""
    if not _have_data():
        return _skip("exports/ or exports/snapshot absent")
    if not list((_ROOT / ".cache").glob("nflverse_stats_player_week_*.csv")):
        return _skip("no nflverse cache for the 3-game averages")
    from lotg_support import inquiry as Q
    from lotg_support.replay import is_legal
    lg = W.load_league(Q.load_sheet("team_week"), W.nflverse_points_from_cache())
    trades, adds = Q.load_sheet("trades"), Q.load_sheet("add_drops")
    moves = W.moves_from_sheets(trades, adds, lg, [Q.load_sheet("rookie_picks"), Q.load_sheet("non_rookie_picks")])
    later = W.later_moves(moves)
    jj = set(trades.index[trades["Date"].astype(str).str.startswith("2022-09-27 02:10:12")])
    sample = [m for m in moves if (m.sheet == "trades" and (m.index in jj or m.index % 15 == 0))
              or (m.sheet == "add_drops" and m.index % 60 == 0)]
    assert any(m.index in jj for m in sample if m.sheet == "trades"), "Jefferson trade not found"
    bad, checked = [], 0
    for mv in sample:
        eff = lg.week_of(mv.day)
        if eff is None:
            continue
        items = W.lineage(mv, later[id(mv)], None)
        given = W._given_up(mv, lg, later[id(mv)])
        for key in lg.keys_from(eff):
            tw = lg.team_week(key, mv.team)
            if tw is None:
                continue
            out = {it.pid for it in W._present(items, lg, key, tw)}
            arr = [p for p, st, en in given if st <= key <= en and (p not in tw.players or p in out)]
            if not (out & set(tw.starters)) and not arr:
                continue
            checked += 1
            _, lineup = W.cf_lineup(lg, key, tw, out, arr)
            pool = (set(tw.players) - out) | set(arr)
            real_bench = set(tw.players) - set(tw.starters) - out
            kept = [p for p in tw.starters if p not in out]
            slots, elig = lg.slots[key[0]], lg.eligibility[key[0]]
            where = f"{mv.sheet}[{mv.index}] {mv.team} {key}"
            if not set(lineup) <= pool:
                bad.append(f"{where}: off-pool {sorted(set(lineup) - pool)}")
            if set(lineup) & real_bench and not set(kept) <= set(lineup):
                bad.append(f"{where}: starter {sorted(set(kept) - set(lineup))} sits while bench "
                           f"{sorted(set(lineup) & real_bench)} starts")
            entrants = [p for p in lineup if p not in tw.starters]
            if any(lg.recent_avg(p, key) is None and p not in lg.started[key] for p in entrants):
                bad.append(f"{where}: unproven entrant who did not really start")
            if len(lineup) < len(tw.starters):
                spare = [p for p in pool - set(lineup)
                         if lg.recent_avg(p, key) is not None or p in lg.started[key]]
                pad = len(slots) - len(lineup) - 1
                if any(is_legal(lineup + [p] + [W.EMPTY] * pad, elig, slots) for p in spare):
                    bad.append(f"{where}: a cleared slot left empty ({len(lineup)}/{len(tw.starters)})")
    assert checked >= 200, f"only {checked} counterfactual weeks checked"
    assert not bad, f"{len(bad)} lineups break the rules: {bad[:6]}"
    print(f"  {checked} counterfactual lineups keep every rule")


def test_sample_recomputes_to_the_exported_column():
    if not _have_data():
        return _skip("exports/ or exports/snapshot absent")
    from lotg_support import inquiry as Q
    trades, adds = Q.load_sheet("trades"), Q.load_sheet("add_drops")
    if W.COLUMN not in trades.columns or W.COLUMN not in adds.columns:
        return _skip("exports predate the Wins added column (pre-merge exports)")
    if not list((_ROOT / ".cache").glob("nflverse_stats_player_week_*.csv")):
        return _skip("no nflverse cache to score off-roster players")
    lg = W.load_league(Q.load_sheet("team_week"), W.nflverse_points_from_cache())
    done = [k for k in lg.order if k[0] in set(Q.completed_seasons())]
    if not done:
        return _skip("no completed season loaded")
    last_done = max(done)
    moves = W.moves_from_sheets(trades, adds, lg, [Q.load_sheet("rookie_picks"), Q.load_sheet("non_rookie_picks")])
    later = W.later_moves(moves)
    frames = {"trades": trades, "add_drops": adds}
    picked = []
    for sheet in ("trades", "add_drops"):
        df = frames[sheet]
        mv_of = {mv.index: mv for mv in moves if mv.sheet == sheet}
        order = pd.to_numeric(df[W.COLUMN], errors="coerce").abs().sort_values(ascending=False).index
        n = 0
        for idx in order:
            mv = mv_of[idx]
            if any(it.share < 1.0 for it in W.lineage(mv, later[id(mv)], None)):
                continue                     # KTC-shared: not reproducible without the index
            full = round(W.wins_added_for(mv, later[id(mv)], lg), 2)
            if round(W.wins_added_for(mv, later[id(mv)], lg, through=last_done), 2) != full:
                continue                     # the season in progress still moves it
            picked.append((sheet, idx, full, float(df.at[idx, W.COLUMN])))
            n += 1
            if n == 12:
                break
    assert len(picked) >= 12, f"only {len(picked)} rows qualified for the recompute"
    bad = [p for p in picked if abs(p[2] - p[3]) > 0.011]
    assert not bad, f"recompute disagrees with the export (sheet, row, recomputed, exported): {bad}"
    # The rate is the total × 17 / games since the move, on every row.
    for sheet, df in frames.items():
        mv_of = {mv.index: mv for mv in moves if mv.sheet == sheet}
        if W.RATE_COLUMN not in df.columns:
            continue
        rate = pd.to_numeric(df[W.RATE_COLUMN], errors="coerce")
        tot = pd.to_numeric(df[W.COLUMN], errors="coerce")
        none_yet = [i for i in df.index if W.games_elapsed(mv_of[i], lg) == 0 and not pd.isna(rate[i])]
        assert not none_yet, f"{sheet}: {len(none_yet)} rows with no game yet carry a rate instead of N/A: {none_yet[:5]}"

        def _ok(i):
            want = W.per_season(tot[i], W.games_elapsed(mv_of[i], lg))
            return pd.isna(rate[i]) if want is None else abs(want - rate[i]) <= 0.011
        off = [i for i in df.index if not _ok(i)]
        assert not off, f"{sheet}: {len(off)} rows whose rate is not Wins added x 17 / games: {off[:5]}"
    print(f"  {len(picked)} rows recompute exactly")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
