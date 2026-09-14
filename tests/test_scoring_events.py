"""Guards for `lotg_support.scoring_events` — the nflverse touchdown join.

No sheet in this repo carries a touchdown, so there is no count to reconcile
against. What these hold is the JOIN and the arithmetic around it: a stat line
attached to a starter must be that starter's own (checked by re-scoring it into
the league's settings and matching the points the build already has), a
touchdown total must be the sum of the kinds it claims to add up, and a starter
with no stat line must be reported rather than counted as a confident zero.

Data-dependent checks skip when `exports/`, the snapshot or the nflverse cache
are absent, and assert only against completed seasons.

Run: python tests/test_scoring_events.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import scoring_events as SE  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _have_cache(season: int) -> bool:
    return (_ROOT / ".cache" / f"nflverse_stats_player_week_{season}.csv").exists()


def _seasons():
    return [y for y in Q.completed_seasons() if _have_cache(y)]


# --------------------------------------------------------------------------- #
# no data needed
# --------------------------------------------------------------------------- #
def test_a_passing_touchdown_is_not_a_scored_one():
    assert SE.PASSING_KIND not in SE.TD_KINDS
    assert set(SE.TD_KINDS) == {"rushing_tds", "receiving_tds",
                                "special_teams_tds", "fumble_recovery_tds"}


def test_qb_rule_rejects_junk_rather_than_guessing():
    try:
        SE.lineups_without_touchdowns(seasons=[], qb_rule="whatever")
    except ValueError as e:
        assert "qb_rule" in str(e)
    else:
        raise AssertionError("an unknown qb_rule should raise, not default")


def test_slot_names_follow_the_snapshots_own_pools():
    assert SE._slot_name(("QB",)) == "QB"
    assert SE._slot_name(("RB", "WR", "TE")) == "FLEX"
    assert SE._slot_name(("QB", "RB", "WR", "TE")) == "SUPER_FLEX"


# --------------------------------------------------------------------------- #
# the stat side
# --------------------------------------------------------------------------- #
def test_weekly_stats_are_regular_season_only():
    # Fantasy weeks 15-17 are NFL weeks 15-17: the REG rows. nflverse's POST
    # rows are the NFL playoffs, which no fantasy week covers.
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    weekly = SE.weekly_stats(seasons[-1])
    assert set(weekly["season_type"].astype(str).str.upper()) == {"REG"}
    assert int(weekly["week"].max()) <= 18


def test_touchdown_total_is_the_sum_of_its_kinds():
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    frame = SE.touchdowns(seasons[-1])
    parts = frame[list(SE.TD_KINDS)].sum(axis=1)
    assert (parts - frame["touchdowns"]).abs().max() < 1e-9
    assert frame["touchdowns"].sum() > 0
    # one row per player and week, so a starter joins exactly one stat line
    assert not frame.duplicated(["player_id", "week"]).any()


# --------------------------------------------------------------------------- #
# the join
# --------------------------------------------------------------------------- #
def test_the_join_reproduces_the_builds_own_starter_points():
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    problems = []
    for season in seasons:
        problems += SE.check_touchdown_join(season)
    assert problems == [], problems


def test_every_lineup_slot_gets_a_starter_row():
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    season = seasons[-1]
    rows = SE.starter_touchdowns(season)
    size = Q.season_meta(season).lineup_size
    counts = rows.groupby(["Week", "Team"]).size()
    assert set(counts.unique()) == {size}, counts.value_counts().to_dict()


def test_a_starter_with_no_stat_line_is_reported_not_counted_as_zero():
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    rows = SE.starter_touchdowns(seasons[-1])
    unresolved = rows[~rows["resolved"] & ~rows["empty_slot"]]
    # they still carry 0.0 so sums work, but they are flagged
    assert (unresolved["touchdowns"] == 0).all()
    scan = SE.lineups_without_touchdowns(seasons=[seasons[-1]])
    assert "unresolved" in scan.columns


def test_the_slot_rule_is_stricter_than_the_position_rule():
    # Every starter the position rule counts, the slot rule counts too (the QB
    # slot holds a quarterback), so a lineup with no touchdown outside the QB
    # slot has none outside quarterbacks either — never the other way round.
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    by_slot = SE.lineups_without_touchdowns(seasons=seasons, qb_rule="slot")
    by_pos = SE.lineups_without_touchdowns(seasons=seasons, qb_rule="position")
    keys = lambda f: {(int(r.Year), int(r.Week), r.Team) for r in f.itertuples()}
    assert keys(by_slot) <= keys(by_pos), keys(by_slot) - keys(by_pos)


def test_the_scan_finds_only_lineups_that_really_scored_nothing():
    seasons = _seasons()
    if not seasons:
        return _skip("no completed season with a cached nflverse file")
    scan = SE.lineups_without_touchdowns(seasons=seasons)
    assert (scan["touchdowns"] == 0).all()
    assert (scan["starters_counted"] > 0).all()
    rows = {}
    for season in seasons:
        rows[season] = SE.starter_touchdowns(season)
    for row in scan.itertuples():
        frame = rows[int(row.Year)]
        lineup = frame[(frame["Week"] == int(row.Week)) & (frame["Team"] == row.Team)]
        counted = lineup[lineup["Position"].astype(str).str.upper() != "QB"]
        assert counted["touchdowns"].sum() == 0, (row.Year, row.Week, row.Team)


# --------------------------------------------------------------------------- #
# 2020, the season with exports and no snapshot
# --------------------------------------------------------------------------- #
def test_every_2020_starter_name_reaches_a_gsis_id():
    if not _HAVE_EXPORTS or not _have_cache(2020):
        return _skip("no exports/ or no cached nflverse 2020")
    if 2020 not in Q.export_seasons():
        return _skip("no 2020 rows in player_week")
    assert SE.check_2020_coverage() == []


def test_2020_rows_come_from_the_sheet_and_snapshot_seasons_do_not():
    if not _HAVE_EXPORTS or not _have_cache(2020):
        return _skip("no exports/ or no cached nflverse 2020")
    assert set(SE.starter_touchdowns(2020)["source"]) == {"exports"}
    seasons = _seasons()
    if seasons:
        assert set(SE.starter_touchdowns(seasons[-1])["source"]) == {"snapshot"}


if __name__ == "__main__":
    for fn in (
        test_a_passing_touchdown_is_not_a_scored_one,
        test_qb_rule_rejects_junk_rather_than_guessing,
        test_slot_names_follow_the_snapshots_own_pools,
        test_weekly_stats_are_regular_season_only,
        test_touchdown_total_is_the_sum_of_its_kinds,
        test_the_join_reproduces_the_builds_own_starter_points,
        test_every_lineup_slot_gets_a_starter_row,
        test_a_starter_with_no_stat_line_is_reported_not_counted_as_zero,
        test_the_slot_rule_is_stricter_than_the_position_rule,
        test_the_scan_finds_only_lineups_that_really_scored_nothing,
        test_every_2020_starter_name_reaches_a_gsis_id,
        test_2020_rows_come_from_the_sheet_and_snapshot_seasons_do_not,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all scoring-event checks passed")
