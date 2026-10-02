"""Guards for `lotg_support.boldness` — how far a lineup call went against
what the manager could see before kickoff.

The stat has no published twin (the build's 5-game start/sit column picks its
reference by hindsight), so the guards tie each half to something the build
did publish: the re-scored game log to `player_week["Points"]`, the lineup
optimiser to `team_week["Max PF"]`. The rest pins the arithmetic and the
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


def test_team_boldness_is_never_negative_and_the_optimiser_matches_max_pf():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    assert B.check_team_boldness_bounds(y, params=_FAST) == []


def test_boldness_is_the_positive_part_of_edge():
    y = _season()
    if y is None:
        return _skip("no completed season with exports and the nflverse cache")
    df = _rows(y).dropna(subset=["Edge"])
    assert len(df) > 500
    assert ((df["Boldness"] - df["Edge"].clip(lower=0)).abs() <= 0.011).all()


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
