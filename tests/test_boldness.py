"""Guards for `lotg_support.boldness` — how far a lineup call went against
what the manager could see before kickoff.

The stat has no published twin (the build's 5-game start/sit column picks its
reference by hindsight), so the guards tie each half to something the build
did publish: the re-scored game log to `player_week["Points"]`, the lineup
search (`best_lineup_value`) to `team_week["Max PF"]`. The rest pins the arithmetic and the
lineup-legality check with synthetic fixtures, and checks that expected points
mean something (the calibration slope).

Data-dependent checks skip when `exports/`, the snapshot or the nflverse cache
are absent, and assert only against completed seasons. They run with
`promote=False` so CI does not pay for calibrating beta over seven seasons.

Run: python tests/test_boldness.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import boldness as B  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()
_FAST = B.Params(promote=False)


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _have_cache(season: int) -> bool:
    c = _ROOT / ".cache"
    return all((c / f"nflverse_{k}_{y}.csv").exists()
               for k in ("stats_player_week", "snap_counts", "weekly_rosters")
               for y in (season - 2, season - 1, season))


def _season():
    ok = [y for y in Q.completed_seasons() if _have_cache(y)] if _HAVE_EXPORTS else []
    return ok[-1] if ok else None


_ROWS = {}


def _rows(season):
    if season not in _ROWS:
        _ROWS[season] = B.boldness(season, params=_FAST, include_live=False)
    return _ROWS[season]


# --------------------------------------------------------------------------- #
# no data needed
# --------------------------------------------------------------------------- #
def test_draft_rounds_bucket_as_documented():
    assert B._bucket(1) == "R1" and B._bucket("2.0") == "R2" and B._bucket(3) == "R3"
    assert B._bucket(4) == "R4-7" and B._bucket(7) == "R4-7"
    assert B._bucket(None) == "UDFA" and B._bucket(float("nan")) == "UDFA" and B._bucket(12) == "UDFA"


def test_lineup_fits_allows_a_reshuffle_but_not_an_illegal_lineup():
    slots = [("QB",), ("RB",), ("WR",), ("RB", "WR", "TE"), ("QB", "RB", "WR", "TE")]
    e = {"q1": frozenset({"QB"}), "q2": frozenset({"QB"}), "q3": frozenset({"QB"}),
         "r1": frozenset({"RB"}), "r2": frozenset({"RB"}), "w1": frozenset({"WR"}),
         "t1": frozenset({"TE"})}
    # a bench RB coming in for the flex TE is legal (he takes the flex)
    assert B.lineup_fits(["q1", "r1", "w1", "r2", "q2"], slots, e)
    # a bench QB coming in for a superflex RB is legal too — the reshuffle
    # case a same-slot swap would miss when the starter was in a strict slot
    assert B.lineup_fits(["q1", "r2", "w1", "t1", "q2"], slots, e)
    # a third QB cannot start: only QB + superflex take quarterbacks
    assert not B.lineup_fits(["q1", "r1", "w1", "q3", "q2"], slots, e)
    # removing the only WR leaves the strict WR slot unfillable
    assert not B.lineup_fits(["q1", "r1", "r2", "t1", "q2"], slots, e)
    # an unknown player is eligible nowhere
    assert not B.lineup_fits(["zz"], slots, e)
    assert B.lineup_fits([], slots, e)


def test_the_best_lineup_uses_each_players_eligibility_not_one_position():
    # Cordarrelle Patterson, 2021: an RB today, WR-eligible that season. With a
    # single position he could not take the WR slot and the "best" lineup came
    # out below the one actually set (stevenb123, 2021 wk9).
    slots = [("QB",), ("RB",), ("WR",), ("RB", "WR", "TE")]
    e = {"q": frozenset({"QB"}), "r": frozenset({"RB"}), "r2": frozenset({"RB"}),
         "cp": frozenset({"RB", "WR"}), "w": frozenset({"WR"})}
    vals = {"q": 20.0, "r": 15.0, "r2": 14.0, "cp": 13.0, "w": 5.0}
    assert B.best_lineup_value(vals, slots, e) == 20 + 15 + 14 + 13
    # best-first is exact on this structure, never worse than any legal lineup
    assert B.best_lineup_value(vals, slots, e) >= 20 + 15 + 13 + 5
    # a slot nobody can fill counts 0, and a negative expectation is never forced in
    assert B.best_lineup_value({"q": 20.0, "w": -1.0}, slots, e) == 20.0
    assert B.best_lineup_value({}, slots, e) == 0.0


def test_lineup_boldness_covers_every_single_start():
    # Swapping in one start's reference is itself a legal lineup, so a lineup's
    # boldness is never below its boldest start (and no starter is unresolved).
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    b = _rows(y)
    filled = b[b["Starter ID"].notna()]
    assert not (filled["Starter source"] == "unresolved").any(), \
        filled.loc[filled["Starter source"] == "unresolved", ["Week", "Team", "Starter"]].head()
    mx = filled.groupby(["Week", "Team"])["Boldness"].max().fillna(0.0)
    tb = B.team_boldness(y, params=_FAST, include_live=False).set_index(["Week", "Team"])["Team boldness"]
    j = mx.to_frame("start").join(tb.rename("lineup"), how="inner")
    assert len(j) and (j["lineup"] >= j["start"] - 0.011).all(), j[j["lineup"] < j["start"] - 0.011]


def test_filled_slots_drops_empty_markers_and_an_unlisted_tail():
    slots = [("QB",), ("RB",), ("WR",), ("RB", "WR", "TE")]
    # Sleeper marks an empty slot with "0"
    assert B.filled_slots(["q", Q.EMPTY_SLOT, "w", "f"], slots) == (["q", "w", "f"], [("QB",), ("WR",), ("RB", "WR", "TE")], 1)
    # a 2020 ESPN lineup simply lists fewer starters: the tail is empty
    assert B.filled_slots(["q", "r"], slots) == (["q", "r"], [("QB",), ("RB",)], 2)
    assert B.filled_slots([], slots) == ([], [], 4)
    # an empty slot is not boldness: the best lineup fills only the filled slots
    e = {"q": frozenset({"QB"}), "r": frozenset({"RB"}), "w": frozenset({"WR"}), "w2": frozenset({"WR"})}
    _, sl, _ = B.filled_slots(["q", Q.EMPTY_SLOT, "w", Q.EMPTY_SLOT], slots)
    assert B.best_lineup_value({"q": 20.0, "w": 10.0, "r": 15.0, "w2": 12.0}, sl, e) == 20.0 + 12.0


def test_empty_slots_carry_no_boldness_and_are_counted():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    b = _rows(y)
    empty = b[b["Starter"] == "Empty slot"]
    assert empty["Boldness"].isna().all()
    tb = B.team_boldness(y, params=_FAST, include_live=False)
    slots = B.season_slots(y)
    for _, r in tb.iterrows():
        wr = {B.season_teams(y).get(rid): w for rid, w in B.week_rows(y, int(r["Week"])).items()}[r["Team"]]
        listed = list(wr.starters)[:len(slots)]
        assert r["Empty slots"] == len(slots) - sum(p != Q.EMPTY_SLOT for p in listed)


def test_a_dead_start_is_judged_like_an_empty_slot():
    # a starter ruled out who scored 0 carries no Boldness, and the lineup is
    # judged on the other slots only — never bolder than its live starts
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    b = _rows(y)
    dead = b[b["Dead start?"]]
    assert len(dead) and dead["Boldness"].isna().all()
    assert (pd.to_numeric(dead["Starter points"]) == 0).all() and dead["Starter unavailable?"].all()
    # a flagged starter who DID score is an ordinary start
    scored = b[b["Starter unavailable?"] & ~b["Dead start?"]]
    assert scored["Boldness"].notna().all() or scored.empty


def test_the_rookie_slot_prior_fades_out():
    # after rookie_prior_weeks the slot has no say: a rookie's E is his own
    # games shrunk toward the ordinary positional prior, as for anyone
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    e = B._base_expectations(y, [1, 8], _FAST)
    rk = e[e["rookie"]]
    assert (rk.loc[rk["week"] == 8, "source"] == "history").all()
    assert rk.loc[rk["week"] == 1, "source"].str.startswith("rookie").all()


def test_every_debatable_choice_is_a_parameter():
    p = B.Params()
    for name in ("prior_season_weight", "recency_half_life", "team_change_weight", "shrink_games",
                 "rookie_shrink_games", "rookie_prior_weeks", "promotion_lookback", "promote",
                 "preseason_grace_weeks", "beta"):
        assert hasattr(p, name), name
    assert 0 < p.prior_season_weight < 1


# --------------------------------------------------------------------------- #
# against the data
# --------------------------------------------------------------------------- #
def test_rescored_log_reproduces_the_builds_points():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    assert B.check_points_reconcile(y) == []


def test_team_boldness_is_never_negative_and_the_lineup_search_matches_max_pf():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    assert B.check_team_boldness_bounds(y, params=_FAST) == []


def test_boldness_is_the_positive_part_of_edge():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    df = _rows(y).dropna(subset=["Edge"])
    # empty slots and dead starts keep their Edge but are not boldness
    judged = df[(df["Starter"] != "Empty slot") & ~df["Dead start?"]]
    assert len(judged) > 500
    assert ((judged["Boldness"] - judged["Edge"].clip(lower=0)).abs() <= 0.011).all()
    assert df.loc[df.index.difference(judged.index), "Boldness"].isna().all()


def test_the_reference_could_legally_have_started():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    df = _rows(y).dropna(subset=["Reference ID"])
    slots = B.season_slots(y)
    elig = B.season_eligibility(y)
    unavail = Q.unavailable(y)
    lineups = {(wk, rid): w for wk in sorted(set(df["Week"])) for rid, w in B.week_rows(y, int(wk)).items()}
    teams = {v: k for k, v in B.season_teams(y).items()}
    bad = []
    for r in df.to_dict("records"):
        ref = str(r["Reference ID"])
        wr = lineups[(r["Week"], teams[r["Team"]])]
        others = [p for p in wr.starters[:len(slots)] if p != Q.EMPTY_SLOT and p != r["Starter ID"]]
        # taxi players count as bench by design, so they are legal references
        if (ref in wr.starters or (ref, int(r["Week"])) in unavail
                or not B.lineup_fits(others + [ref], slots, elig)):
            bad.append((r["Week"], r["Team"], r["Starter"], r["Reference"]))
    assert not bad, bad[:5]


def test_rookie_slot_prior_learns_only_from_earlier_drafts():
    # every training row must predate the season it prices, and only real
    # rookies (rookie season == draft year) are priced by slot
    if not _HAVE_EXPORTS:
        return _skip("no exports/")
    ids = B._player_ids()
    for y, g, overall, pos in B._rookie_draft_rows():
        assert int(ids.at[g, "rookie_season"]) == y
        assert pos in B.POSITIONS and overall >= 1
    first = min(y for y, *_ in B._rookie_draft_rows())
    assert B.rookie_slot_priors(first) == {}      # nothing earlier to learn from


def test_2020_runs_from_the_espn_backfill():
    # 2020 has no snapshot; its lineups come from the ESPN emit and its points
    # are ESPN-scored, which the re-scored log must still reproduce
    if not _HAVE_EXPORTS or not _have_cache(2020):
        return _skip("no exports/ or nflverse cache for 2018-2020")
    assert B.played_weeks(2020) and len(B.season_slots(2020)) == 9
    assert B.check_points_reconcile(2020) == []
    df = B.boldness(2020, weeks=[1], params=_FAST)
    assert len(df) == 8 * 9 and df["E starter"].notna().all()


def test_the_build_path_matches_the_inquiry_path():
    # Inside the build the module is fed the build's own matchups, flags, picks,
    # scorer and bridge (build_inputs). Fed the same data the inquiry path reads,
    # it must return the same Boldness for every start and the same Lineup
    # Boldness for every lineup — one stat, two doors.
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    import json
    from lotg_support import scoring_events as SE
    plain = B.boldness(y, params=_FAST, include_live=False)
    lineups = B.team_boldness(y, params=_FAST, include_live=False)
    weeks = B.played_weeks(y)
    matchups = {y: {w: [dict(roster_id=rid, matchup_id=r.matchup_id, points=r.points,
                             starters=list(r.starters), players=list(r.players),
                             players_points=dict(r.players_points))
                        for rid, r in B.week_rows(y, w).items()] for w in weeks}}
    league = json.loads((_ROOT / "exports" / "snapshot" / f"season_{y}" / "league.json").read_text())
    score, score_map = B._build_scorer()
    with B.build_inputs(matchups=matchups, roster_positions={y: league["roster_positions"]},
                        teams={y: B.season_teams(y)}, unavailable={y: Q.unavailable(y)},
                        rookie_picks=Q.load_sheet("rookie_picks"),
                        scoring={y: dict(B.scoring_table(y))}, score=score, score_map=score_map,
                        bridge=SE.gsis_bridge()):
        starts, built_lineups = B.build_columns(_FAST)
    key = ["Year", "Week", "Team", "Player ID"]
    want = plain[plain["Starter ID"].notna()].rename(columns={"Starter ID": "Player ID"})
    want = want.assign(Boldness=want["Boldness"].where(
        want["Boldness"].notna() | want["E starter"].isna() | want["Dead start?"], 0.0))
    m = want[key + ["Boldness"]].merge(starts, on=key, suffixes=("_plain", "_built"))
    assert len(m) == len(want) == len(starts)
    assert ((m["Boldness_plain"].fillna(-1) - m["Boldness_built"].fillna(-1)).abs() < 1e-9).all()
    lm = lineups.merge(built_lineups, on=["Year", "Week", "Team"])
    assert len(lm) == len(lineups) and (lm["Team boldness"] - lm["Lineup Boldness"]).abs().max() < 1e-9
    assert (lm["Empty slots_x"] == lm["Empty slots_y"]).all()


def test_beta_is_an_nfl_fit_the_league_rosters_cannot_move():
    # beta is calibrated on NFL next-man-up events; it once picked up the
    # league's rosters (the no-history fallback) and so differed between the
    # build's inputs and the snapshot's — the inquiry path drifted from the
    # exported column by up to 0.08. Empty rosters must give the same beta.
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    seasons = (y - 1, y)
    plain = B.calibrate_beta(seasons=seasons)
    score, score_map = B._build_scorer()
    B._clear_caches()
    try:
        with B.build_inputs(matchups={s: {} for s in seasons}, roster_positions={},
                            teams={}, unavailable={}, rookie_picks=Q.load_sheet("rookie_picks"),
                            scoring={s: dict(B.scoring_table(s)) for s in seasons},
                            score=score, score_map=score_map, bridge={}):
            no_league = B.calibrate_beta(seasons=seasons)
    finally:
        B._clear_caches()
    assert plain and plain == no_league, (plain, no_league)


def test_the_inquiry_path_never_scores_a_week_the_build_has_not_finalized():
    # "any points" also catches the week in progress (Thursday night is
    # enough); the inquiry path stops where the committed build did.
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    tw = Q.load_sheet("team_week")
    for y in sorted(set(Q.numeric(tw, "Year").dropna().astype(int))):
        played, live = B.season_weeks(y)
        last = int(Q.numeric(tw[Q.numeric(tw, "Year") == y], "Week").max())
        assert not played or max(played) <= last, (y, played, last)
        assert live is None or live == last + 1, (y, live, last)


def test_expected_points_mean_something():
    # If E is unbiased, a start with Edge B loses to its reference by about B:
    # the slope of Result on Edge sits near -1. One season is noisier than the
    # pooled history (-0.74 across 2021-2025), hence the wider band.
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    c = B.calibration(_rows(y))
    assert "slope" in c and -1.5 <= c["slope"] <= -0.4, c


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
