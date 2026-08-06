"""Counterfactual replay: guards, and the case the engine was generalised from.

The load-bearing test is `test_no_move_replay_reproduces_every_season`: replay
each season changing nothing, and require the result to match the build's own
`team_week.PF` (including the +5 semifinal home-field bonus) and `team_year`
champion. That exercises scoring, seeding, the bracket and the bonus against an
independent source, so a counterfactual run on top of it differs from reality
only where the moves actually bite.

Also pins the 2025 Herbert-for-Jackson answer documented in
`plan/notes/WHATIF_HERBERT_TRADE_2025.md`, under all three lineup models.

Everything SKIPs cleanly without the committed snapshot/exports.

Run: python tests/test_replay.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import replay as R  # noqa: E402

_HAVE_DATA = ((_ROOT / "exports" / "team_week.csv").exists()
              and (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists())


def _seasons():
    # Completed seasons only: an in-progress season has snapshot weeks the build
    # has not exported yet, so a comparison against exports/ would be partial.
    return [y for y in Q.completed_seasons() if Q.played_weeks(y)]


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_is_legal_respects_slots_and_the_empty_sentinel():
    slots = (("QB",), ("RB",), ("RB", "WR", "TE"))
    elig = {"qb1": frozenset({"QB"}), "rb1": frozenset({"RB"}),
            "wr1": frozenset({"WR"}), "qb2": frozenset({"QB"})}
    assert R.is_legal(["qb1", "rb1", "wr1"], elig, slots)
    assert R.is_legal(["wr1", "rb1", "qb1"], elig, slots)       # order must not matter
    assert not R.is_legal(["qb1", "qb2", "wr1"], elig, slots)   # no second RB
    assert not R.is_legal(["qb1", "rb1"], elig, slots)          # wrong size
    # Sleeper's "0" empty-slot sentinel is a wildcard, not an illegal lineup.
    assert R.is_legal(["qb1", "rb1", Q.EMPTY_SLOT], elig, slots)
    # Dual eligibility (the position-drift case) satisfies either slot.
    both = dict(elig, cp=frozenset({"RB", "WR"}))
    assert R.is_legal(["qb1", "cp", "wr1"], both, slots)


def test_standings_order_matches_the_build_rule():
    teams = {1: "a", 2: "b", 3: "c", 4: "d"}
    meta = Q.SeasonMeta(year=2099, has_snapshot=True, playoff_week_start=3)
    scores = {1: {1: 100.0, 2: 90.0, 3: 80.0, 4: 70.0},
              2: {1: 50.0, 2: 60.0, 3: 200.0, 4: 10.0}}
    pairs = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)]}
    table = R._standings(scores, pairs, teams, meta)
    # c wins both; a and b both go 1-1 on equal PF (150 each) so the name
    # breaks the tie; d loses both.
    assert [s.team for s in table] == ["c", "a", "b", "d"]
    assert [s.record for s in table] == ["2-0", "1-1", "1-1", "0-2"]
    assert (table[1].points_for, table[2].points_for) == (150.0, 150.0)
    # Only regular-season weeks (1..playoff_week_start-1) count toward seeding.
    assert table[0].points_for == 280.0


def test_ties_count_as_half_a_win():
    teams = {1: "a", 2: "b"}
    meta = Q.SeasonMeta(year=2099, has_snapshot=True, playoff_week_start=2)
    table = R._standings({1: {1: 100.0, 2: 100.0}}, {1: [(1, 2)]}, teams, meta)
    assert [s.ties for s in table] == [1, 1]
    assert table[0].sort_key[0] == 0.5
    assert table[0].record == "0-0-1"


def test_unknown_model_is_refused():
    try:
        R.replay(R.Scenario(season=2025, moves=(), model="hindsight"))
    except ValueError as exc:
        assert "unknown model" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("bad model should raise")


# ---------------------------------------------------------------------------
# Guards against the committed data
# ---------------------------------------------------------------------------
def test_every_real_lineup_is_legal():
    if not _HAVE_DATA:
        return _skip("no committed data")
    for year in _seasons():
        problems = R.check_lineup_template(year)
        assert not problems, problems[:3]


def test_ceiling_model_reproduces_the_built_max_pf():
    if not _HAVE_DATA:
        return _skip("no committed data")
    for year in _seasons():
        problems = R.check_max_pf(year)
        assert not problems, problems[:3]


def test_no_move_replay_reproduces_every_season():
    if not _HAVE_DATA:
        return _skip("no committed data")
    for year in _seasons():
        problems = R.check_identity(year)
        assert not problems, problems[:5]


def test_2020_cannot_be_replayed_and_says_so():
    if not _HAVE_DATA:
        return _skip("no committed data")
    try:
        R.no_op(2020)
    except LookupError as exc:
        assert "no Sleeper snapshot" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("2020 has no snapshot and must refuse to replay")


def test_bracket_applies_the_home_field_bonus_to_the_higher_seed_only():
    if not _HAVE_DATA:
        return _skip("no committed data")
    result = R.no_op(2025)
    meta = Q.season_meta(2025)
    seeds = [s.roster_id for s in result.standings[:meta.playoff_teams]]
    raw = Q.week(2025, meta.semifinal_week)
    for team, points, _, _ in result.bracket.semifinals:
        rid = next(i for i, t in result.teams.items() if t == team)
        assert rid in (seeds[0], seeds[1]), "the first name in a semifinal is the higher seed"
        assert abs(points - (raw[rid].points + Q.SEMIFINAL_HOME_BONUS)) < 0.02
    for _, _, team, points in result.bracket.semifinals:
        rid = next(i for i, t in result.teams.items() if t == team)
        assert abs(points - raw[rid].points) < 0.02, "the lower seed gets no bonus"


# ---------------------------------------------------------------------------
# The inquiry this engine was generalised from
# ---------------------------------------------------------------------------
def test_undo_trade_finds_the_2025_herbert_deal():
    if not _HAVE_DATA:
        return _skip("no committed data")
    scenario = R.undo_trade(2025, player="Justin Herbert")
    moved = {Q.players().name(m.player_id) for m in scenario.moves}
    assert moved == {"Justin Herbert", "Tre' Harris", "Lamar Jackson", "Chris Godwin"}
    # Each player goes back to the roster that gave him up.
    by_name = {Q.players().name(m.player_id): m for m in scenario.moves}
    herbert, lamar = by_name["Justin Herbert"], by_name["Lamar Jackson"]
    assert herbert.to_roster == lamar.from_roster
    assert herbert.from_roster == lamar.to_roster


def test_herbert_counterfactual_matches_the_documented_answer():
    if not _HAVE_DATA:
        return _skip("no committed data")
    scenario = R.undo_trade(2025, player="Justin Herbert")
    for model in R.MODELS:
        result = R.replay(scenario.with_model(model))
        shmuel = next(s for s in result.standings if s.team == "shmuel256")
        was = next(s for s in result.real_standings if s.team == "shmuel256")
        assert (was.record, shmuel.record) == ("12-3", "13-2"), (model, was.record, shmuel.record)
        assert {f.week for f in result.flips} == {6, 8}, (model, result.flips)
        assert result.bracket.champion == "shmuel256", model
        assert result.real_bracket.champion == "shmuel256", model
        assert not result.warnings, result.warnings


def test_a_no_op_scenario_changes_nothing_anywhere():
    if not _HAVE_DATA:
        return _skip("no committed data")
    result = R.no_op(2025)
    assert result.moved_weeks() == []
    assert result.flips == []
    assert result.changed is False
    assert [s.team for s in result.standings] == [s.team for s in result.real_standings]


def test_render_reports_the_change():
    if not _HAVE_DATA:
        return _skip("no committed data")
    text = R.render(R.replay(R.undo_trade(2025, player="Justin Herbert")), weekly=True)
    assert "head-to-head results that change: 2" in text
    assert "champion: shmuel256 -> shmuel256  (unchanged)" in text
    assert "shmuel256: 12-3 -> 13-2" in text


TESTS = [
    test_is_legal_respects_slots_and_the_empty_sentinel,
    test_standings_order_matches_the_build_rule,
    test_ties_count_as_half_a_win,
    test_unknown_model_is_refused,
    test_every_real_lineup_is_legal,
    test_ceiling_model_reproduces_the_built_max_pf,
    test_no_move_replay_reproduces_every_season,
    test_2020_cannot_be_replayed_and_says_so,
    test_bracket_applies_the_home_field_bonus_to_the_higher_seed_only,
    test_undo_trade_finds_the_2025_herbert_deal,
    test_herbert_counterfactual_matches_the_documented_answer,
    test_a_no_op_scenario_changes_nothing_anywhere,
    test_render_reports_the_change,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall replay checks passed")
