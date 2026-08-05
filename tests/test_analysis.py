"""Analysis primitives: position joins, lineup composition, cohorts, scarcity.

Two of the guards tie this layer to numbers the build computed independently,
which is what makes it safe to answer a judgement question from:

  * the starter points reconstructed from `player_week` must equal `team_week.PF`
    (allowing exactly the +5 semifinal home-field bonus);
  * `max_same_nfl_team` must equal the build's own
    "Most number of players started from same NFL team" column, every lineup.

The rest pin behaviour that a wrong answer would depend on: depth measures that
distinguish one star from a real corps, a cohort comparison that reports both
sides and a per-season breakdown, and replacement level derived from what the
league actually starts rather than assumed.

Run: python tests/test_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import analysis as A  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _seasons():
    return [y for y in Q.completed_seasons() if Q.played_weeks(y)]


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_placeholders_are_recognised():
    for value in ("", "  ", "Unknown", "unknown", "N/A", "-", "none"):
        assert A.is_placeholder(value), value
    for value in ("Josh Allen", "Unknown Soldier", "0"):
        assert not A.is_placeholder(value), value


def test_compare_reports_both_sides_and_the_breakdown():
    df = pd.DataFrame({
        "flag": [2, 2, 2, 0, 0, 0, 2, 0],
        "value": [10.0, 12.0, 11.0, 20.0, 22.0, 21.0, 11.0, 19.0],
        "Year": [2024, 2024, 2024, 2024, 2025, 2025, 2025, 2025],
    })
    out = A.compare(df, "flag>=2", "value", by="Year", permutations=200)
    assert (out.n_with, out.n_without) == (4, 4)
    assert out.mean_with == 11.0 and out.mean_without == 20.5
    assert out.difference == -9.5
    assert out.effect_size < -3      # a large, obvious separation
    assert out.p_value < 0.1
    # The per-season breakdown must be present and cover both seasons.
    assert {label for label, *_ in out.by_group} == {"2024", "2025"}
    text = out.describe()
    assert "with:" in text and "without:" in text and "per group" in text


def test_compare_refuses_columns_it_cannot_see():
    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    for bad in (("missing>=1", "b"), ("a>=1", "missing")):
        try:
            A.compare(df, bad[0], bad[1], by=None, permutations=10)
        except KeyError:
            continue
        raise AssertionError(f"{bad} should raise")


def test_permutation_p_is_deterministic():
    df = pd.DataFrame({"flag": [1, 1, 0, 0, 1, 0], "value": [5.0, 6.0, 9.0, 8.0, 5.5, 9.5]})
    first = A.compare(df, "flag>=1", "value", by=None, permutations=500, seed=7)
    again = A.compare(df, "flag>=1", "value", by=None, permutations=500, seed=7)
    assert first.p_value == again.p_value


# ---------------------------------------------------------------------------
# Guards against the committed data
# ---------------------------------------------------------------------------
def test_starter_points_reconcile_with_the_built_pf():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    for year in _seasons():
        problems = A.check_starter_points_reconcile(year)
        assert not problems, problems[:3]


def test_stack_counts_match_the_build():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    for year in _seasons():
        problems = A.check_stack_counts_match_build(year)
        assert not problems, problems[:3]


def test_every_named_player_gets_a_position():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    assert not A.check_positions_are_placed()
    picks = A.placement_report("picks", "Player Picked", "Year")
    # Unexercised future picks are written "Unknown" — excluded, and counted.
    assert picks["placeholders"] > 0
    assert picks["rate"] >= 0.99


def test_positions_are_per_season_from_the_build():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    table = A.positions_by_season()
    assert table[("Josh Allen", 2025)] == "QB"
    assert A.position_of("Josh Allen", 2025) == "QB"
    assert A.position_of("Josh Allen") == "QB"
    assert A.position_of("nobody at all") is None
    # The join reaches sheets that carry no position column of their own.
    picks = A.with_position(Q.rows("picks", "Year=2025"), "Player Picked", "Year")
    assert "Position" in picks.columns
    assert set(picks["Position"]) & {"QB", "RB", "WR", "TE"}


def test_position_group_measures_depth_not_just_total():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    df = A.position_group("WR", season=2025)
    assert not df.empty and set(df["Position"]) == {"WR"}
    assert (df["points"].diff().dropna() <= 0).all(), "should be ordered by points"
    for row in df.itertuples():
        assert 1.0 <= row.effective_players <= row.players + 1e-9
        assert 0.0 < row.top1_share <= row.top3_share <= 1.0 + 1e-9
        assert row.contributors <= row.players
    # A team whose group is more concentrated must score lower on effective_players.
    top_heavy = df.loc[df["top1_share"].idxmax()]
    spread = df.loc[df["top1_share"].idxmin()]
    assert top_heavy["effective_players"] < spread["effective_players"]


def test_lineup_stacks_carry_the_ceiling_columns():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    df = A.lineup_stacks(season=2025)
    assert not df.empty
    for col in ("max_same_nfl_team", "stack_WR", "PF", "Max PF", "Efficiency"):
        assert col in df.columns, col
    assert (df["max_same_nfl_team"] >= df["stack_WR"]).all(), \
        "a within-position stack cannot exceed the whole-lineup stack"
    # A lineup can field fewer than the template's slots when a manager left one
    # empty — Sleeper's "0" sentinel, which produces no player_week row. Every
    # shortfall must be explained by exactly that, never by a lost row.
    size = Q.season_meta(2025).lineup_size
    assert (df["starters"] <= size).all()
    for row in df[df["starters"] < size].itertuples():
        rid = next(i for i, t in Q.teams(2025).items() if t == row.Team)
        empty = sum(1 for p in Q.week(2025, int(row.Week)).get(rid).starters
                    if p == Q.EMPTY_SLOT)
        assert size - row.starters == empty, (row.Team, row.Week, empty)
    # PF joined from team_week must match the starter points this layer sums,
    # outside the semifinal week where the build adds its +5.
    regular = df[df["Week"] != Q.season_meta(2025).semifinal_week]
    assert (regular["PF"] - regular["starter_points"]).abs().max() < 0.02


def test_replacement_level_comes_from_what_the_league_starts():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    demand = A.observed_demand(2025)
    # Superflex: more QBs started per week than a single-QB league would field,
    # and WR is the deepest requirement. Measured, not assumed.
    assert demand["QB"] > 8, demand
    assert demand["WR"] > demand["RB"] > demand["TE"], demand

    rows = {s.position: s for s in A.scarcity(2025)}
    assert set(rows) == set(A.POSITIONS)
    for pos, s in rows.items():
        assert s.replacement_rank == max(1, round(demand[pos])), (pos, s.replacement_rank)
        assert s.best >= s.replacement
        assert s.surplus == round(s.best - s.replacement, 2)
    # A stricter definition of replacement can only lower the bar, never raise it.
    strict = {s.position: s for s in A.scarcity(2025, demand_multiple=2.0)}
    for pos in rows:
        assert strict[pos].replacement <= rows[pos].replacement + 1e-9


def test_value_curve_ranks_within_position():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    curve = A.value_curve(season=2025)
    for pos in A.POSITIONS:
        sub = curve[curve["Position"] == pos].sort_values("rank")
        assert list(sub["rank"]) == list(range(1, len(sub) + 1)), pos
        assert (sub["value"].diff().dropna() <= 1e-9).all(), pos


def test_spend_by_position_covers_every_team_and_flags_its_gap():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    df = A.spend_by_position()
    assert set(df["Position"]) == set(A.POSITIONS)
    assert len(set(df["Team"])) == 8
    for team, sub in df.groupby("Team"):
        assert abs(sub["points_share"].sum() - 1.0) < 0.05, team
        if sub["picks"].sum():
            # Shares are rounded to 4dp, so allow the rounding drift.
            assert abs(sub["pick_share"].sum() - 1.0) < 1e-3, team
    # Trades are deliberately unpriced; the docstring must keep saying so, since
    # a write-up that forgets it would overstate its coverage.
    assert "Trades are not priced here" in A.spend_by_position.__doc__


def test_reads_are_pure():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    before = {p: p.stat().st_mtime for p in (_ROOT / "exports").glob("*.csv")}
    A.lineup_stacks(season=2025)
    A.spend_by_position(season=2025)
    A.scarcity(2025)
    after = {p: p.stat().st_mtime for p in (_ROOT / "exports").glob("*.csv")}
    assert before == after, "analysis must never write to exports/"


TESTS = [
    test_placeholders_are_recognised,
    test_compare_reports_both_sides_and_the_breakdown,
    test_compare_refuses_columns_it_cannot_see,
    test_permutation_p_is_deterministic,
    test_starter_points_reconcile_with_the_built_pf,
    test_stack_counts_match_the_build,
    test_every_named_player_gets_a_position,
    test_positions_are_per_season_from_the_build,
    test_position_group_measures_depth_not_just_total,
    test_lineup_stacks_carry_the_ceiling_columns,
    test_replacement_level_comes_from_what_the_league_starts,
    test_value_curve_ranks_within_position,
    test_spend_by_position_covers_every_team_and_flags_its_gap,
    test_reads_are_pure,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall analysis checks passed")
