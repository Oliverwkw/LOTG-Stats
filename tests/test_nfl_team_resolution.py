"""Regression tests for deterministic NFL-team resolution in the LOTG build.

A player who wasn't rostered in a given NFL season (free agent / unsigned)
used to resolve their per-week "NFL team" from the live Sleeper snapshot, which
flips between builds. Odell Beckham 2022 (a free agent all season, recovering
from a torn ACL, on no NFL roster) flipped between MIA and NYG, and because Luck
is z-scored within each (Year, Week) across all teams, that single flip churned
~50 cells across 8 sheets between otherwise-identical builds.

`_resolve_historical_nfl_team` makes the fallback deterministic: the team from
the most recent season ON OR BEFORE the target year that the player actually
appeared in nflverse weekly stats, or None when no such season exists.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from lotg import _resolve_historical_nfl_team  # noqa: E402


def test_obj_2022_resolves_to_stable_single_value():
    # OBJ: NYG (2014-2018), LA Rams (2021, won SB), free agent all of 2022.
    history = {2014: "NYG", 2015: "NYG", 2018: "NYG", 2021: "LA"}
    # 'LA' normalizes to 'LAR' — the most recent season on/before 2022.
    results = {_resolve_historical_nfl_team(history, 2022) for _ in range(10)}
    assert results == {"LAR"}, results


def test_no_prior_season_leaves_team_blank():
    # Player whose only nflverse season is in the future relative to the target:
    # leave NFL team blank rather than guessing.
    assert _resolve_historical_nfl_team({2023: "BAL"}, 2022) is None
    assert _resolve_historical_nfl_team({}, 2022) is None


def test_exact_season_takes_priority_over_earlier():
    history = {2020: "CLE", 2021: "LA", 2022: "BAL"}
    assert _resolve_historical_nfl_team(history, 2022) == "BAL"


def test_picks_most_recent_prior_when_target_absent():
    # Gap year 2022: most recent prior season is 2021.
    history = {2019: "CLE", 2021: "LA", 2024: "MIA"}
    assert _resolve_historical_nfl_team(history, 2022) == "LAR"


if __name__ == "__main__":
    test_obj_2022_resolves_to_stable_single_value()
    test_no_prior_season_leaves_team_blank()
    test_exact_season_takes_priority_over_earlier()
    test_picks_most_recent_prior_when_target_absent()
    print("all NFL-team resolution regression tests passed")
