"""Guards for `lotg_support.boldness` — how far a lineup call went against
what the manager could see before kickoff.

The stat has no published twin (the build's 5-game start/sit column picks its
reference by hindsight), so the guards tie each half to something the build
did publish: the re-scored game log to `player_week["Points"]`, the lineup
optimiser to `team_week["Max PF"]`. The rest pins the arithmetic and the
seed-lock enumeration with synthetic fixtures, and checks that expected points
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


def test_seed_lock_needs_every_outcome_to_agree():
    # a is two clear of everyone: locked. b and c can swap: neither locked.
    # d trails c by a win with a PF gap wider than any week can close: d can
    # only tie c on wins and lose the tiebreak, so d is locked 4th.
    wins = {"a": 10, "b": 8, "c": 8, "d": 7}
    pf = {"a": 2000, "b": 1900, "c": 1950, "d": 1500}
    games = [("a", "d"), ("b", "c")]
    assert B.locked_seeds(wins, pf, games, spread=170) == ["a", "d"]
    # shrink the gap below one week's spread and d's tie becomes movable
    pf["d"] = 1900
    assert B.locked_seeds(wins, pf, games, spread=170) == ["a"]


def test_seed_lock_with_no_games_locks_nothing():
    assert B.locked_seeds({"a": 3}, {"a": 1.0}, [], spread=100) == []


def test_every_debatable_choice_is_a_parameter():
    p = B.Params()
    for name in ("prior_season_weight", "team_change_weight", "shrink_games",
                 "rookie_shrink_games", "promotion_lookback", "promote",
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
    elig = Q.season_eligibility(y)
    taxi = B._taxi(y)
    unavail = Q.unavailable(y)
    bad = []
    for r in df.to_dict("records"):
        slot = set(str(r["Slot"]).split("/"))
        ref = str(r["Reference ID"])
        if not (elig.get(ref, frozenset()) & slot) or ref in taxi or (ref, int(r["Week"])) in unavail:
            bad.append((r["Week"], r["Team"], r["Starter"], r["Reference"]))
    assert not bad, bad[:5]


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
