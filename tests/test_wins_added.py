"""Wins added (trades + add_drops): the rule, on synthetic weeks and on the data.

The synthetic cases pin each part of the rule in `lotg_support.wins_added`:

  * the lineup rule — an arrival may displace a starter and players move
    between slots to fit him (an RB leaves the RB slot for the flex so a WR can
    come in); a bench player only fills a slot a departed starter left open;
    nobody started anywhere counts for at most 1.5 x his last-3-game average;
  * the per-week result flip against the real opponent, ±1;
  * the opponent losing a given-up player he started (and the mirror row);
  * lineage through a later trade at its KTC share, read as a probability;
  * a given-up player later re-acquired counts as a different player.

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


def _league(weeks, pts_by_week, nfl=None):
    """weeks: {key: [(team, starters, bench, opp)]}; pts_by_week: {key: {pid: pts}}."""
    built = {k: {t: _tw(t, s, b, pts_by_week[k], o) for t, s, b, o in rows} for k, rows in weeks.items()}
    elig = {SEASON: {p: frozenset({pos}) for p, pos in POS.items()}}
    days = {k: f"{k[0]}-10-{k[1]:02d}" for k in weeks}
    rostered = {k: {p: v for p, v in pts_by_week[k].items()
                    if any(p in tw.players for tw in built[k].values())} for k in weeks}
    nfl = dict(nfl or {})
    for k, pts in pts_by_week.items():          # unrostered players score from "nflverse"
        for p, v in pts.items():
            if p not in rostered[k]:
                nfl.setdefault(p, {})[k] = v
    return W.League(built, rostered, {SEASON: SLOTS}, elig, POS, nfl, days)


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


def test_reacquired_player_counts_as_a_different_player():
    # A dropped d, later picked him back up (m2) and started him. While he is
    # really on A, the drop adds nothing that week; the re-add owns the week.
    pts = {"r1": 5, "w1": 10, "d": 30, "b1": 2, "o1": 20, "o2": 10, "o3": 10}
    lg = _league({K1: [("A", ["r1", "w1", "d"], ["b1"], "B"), ("B", ["o1", "o2", "o3"], [], "A")]}, {K1: pts})
    m1 = _move("A", f"{SEASON}-08-01", sent=["d"], kind="add_drop", stamp=f"{SEASON}-08-01 12:00:00")
    m2 = _move("A", f"{SEASON}-08-20", received=["d"], kind="add_drop", stamp=f"{SEASON}-08-20 12:00:00")
    assert W.wins_added_for(m1, [m2], lg) == 0.0
    assert W.wins_added_for(m2, [], lg) == 1.0


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
    print(f"  {len(picked)} rows recompute exactly")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
