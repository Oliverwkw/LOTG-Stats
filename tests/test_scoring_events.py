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

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

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


# --------------------------------------------------------------------------- #
# careers
# --------------------------------------------------------------------------- #
def _seasonal_file(season: int):
    return _ROOT / ".cache" / SE.SEASONAL_DIR / SE.SEASONAL_FILE.format(season=season)


#: One finished season, fetched if it is not cached (~400KB), so the structural
#: career checks are real in CI rather than permanently skipped. The guards that
#: need the whole 1999-> history stay skip-if-absent, like test_contracts.py.
_PROBE_SEASON = 2015


def _have_seasonal() -> int:
    """A cached seasonal season to test against, fetching the probe if needed."""
    for season in range(2015, 2025):
        if _seasonal_file(season).exists() and _seasonal_file(season).stat().st_size > 0:
            return season
    try:
        if SE._seasonal(_PROBE_SEASON, str(_ROOT)) is not None:
            return _PROBE_SEASON
    except Exception:
        pass
    return 0


def _have_full_seasonal_history() -> bool:
    """Every season a career can span is cached — the whole-history guards."""
    return all((_seasonal_file(y).exists() and _seasonal_file(y).stat().st_size > 0)
               for y in range(SE.FIRST_NFLVERSE_SEASON, 2025))


def test_basis_measure_and_years_rule_reject_junk():
    for call in (lambda: SE.career_totals(basis="everything"),
                 lambda: SE.lowest_careers(measure="whatever"),
                 lambda: SE.lowest_careers(years_rule="vibes")):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("an unknown option should raise, not be guessed at")


def test_the_default_tenure_rule_follows_the_career_measure():
    # A career-to-date question is about the tenure he HAD at that start; a
    # lifetime question is about the career he ended up with. Getting this
    # backwards silently changes who qualifies.
    assert SE.DEFAULT_YEARS_RULE["career_to_date"] == "at_start"
    assert SE.DEFAULT_YEARS_RULE["career_total"] == "roster"
    assert set(SE.DEFAULT_YEARS_RULE) == {"career_total", "career_to_date"}


def test_a_seasonal_file_carries_reg_post_rows_and_they_are_never_summed():
    season = _have_seasonal()
    if not season:
        return _skip("no cached nflverse seasonal file")
    frame = SE._seasonal(season, str(_ROOT))
    assert frame is not None
    kinds = set(frame["season_type"])
    assert "REG+POST" in kinds, kinds     # the trap this guards
    assert SE._basis_types("reg") == ("REG",)
    assert SE._basis_types("reg_post") == ("REG", "POST")
    assert "REG+POST" not in SE._basis_types("reg_post")


def test_career_totals_equal_the_rows_the_basis_names():
    season = _have_seasonal()
    if not season or not _have_cache(2020):
        return _skip("no cached seasonal file")
    frame = SE._seasonal(season, str(_ROOT))
    reg = frame[frame["season_type"] == "REG"]
    # rebuild one season's contribution independently and require the module's
    # per-season table to match it exactly
    want = {}
    for pid, value in zip(reg["player_id"].astype(str),
                          pd.to_numeric(reg["rushing_yards"], errors="coerce").fillna(0.0)):
        want[pid] = want.get(pid, 0.0) + float(value)
    got, _ = SE._season_values_cached("rushing_yards", "reg", season, str(_ROOT))
    for pid, value in want.items():
        assert abs(got.get((pid, season), 0.0) - value) < 0.001, (pid, season, value)
    # and the postseason basis must be at least as large in aggregate
    assert (sum(SE.career_totals("rushing_yards", basis="reg_post").values())
            >= sum(SE.career_totals("rushing_yards", basis="reg").values()))


def test_career_to_date_never_exceeds_the_lifetime_total():
    # Only true for a stat that cannot go backwards — rushing YARDS can (that is
    # the whole reason the negative-career answers exist), touchdowns cannot.
    if not _seasons():
        return _skip("no completed season with a cached nflverse file")
    frame = SE.starter_careers(stat="rushing_tds")
    if frame.empty:
        return _skip("no starter rows")
    bad = frame[frame["career_to_date"] > frame["career_total"] + 0.001]
    assert bad.empty, bad.head().to_string()
    assert (frame["career_to_date"] >= -0.001).all()


def test_lowest_careers_is_sorted_and_keeps_ties_at_the_cutoff():
    if not _seasons():
        return _skip("no completed season with a cached nflverse file")
    rows = SE.lowest_careers(measure="career_to_date", n=5)
    if rows.empty:
        return _skip("no qualifying players")
    values = list(rows["career_to_date"])
    assert values == sorted(values), values
    assert len(rows) >= 5
    # anything beyond the fifth row is there only because it ties the fifth
    for extra in values[5:]:
        assert extra == values[4], (extra, values)


def test_lowest_careers_reports_the_earliest_of_equal_starts():
    if not _seasons():
        return _skip("no completed season with a cached nflverse file")
    rows = SE.lowest_careers(measure="career_to_date", n=8)
    frame = SE.starter_careers()
    for row in rows.itertuples(index=False):
        mine = frame[(frame["Player"] == row.Player)
                     & (frame["years_at_start"].fillna(0) >= 3)
                     & (frame["career_to_date"] == row.career_to_date)]
        first = mine.sort_values(["Year", "Week"]).iloc[0]
        assert (int(first["Year"]), int(first["Week"])) == (int(row.Year), int(row.Week)), \
            (row.Player, row.Year, row.Week, first["Year"], first["Week"])


def test_the_career_guards_pass_on_real_data():
    if not _seasons() or not _have_full_seasonal_history():
        return _skip("seasonal history not fully cached")
    assert SE.check_career_window_covers_starters() == []
    assert SE.check_career_sources_agree() == []
    assert SE.check_career_to_date_arithmetic() == []


def test_the_season_cache_stays_out_of_the_builds_freshness_gate():
    """`.cache/*.csv` is the build's baseline and every file there must be
    stamped in `_fetch_log.json` — `test_refresh_external` asserts exactly that.
    These files are fetched by a path that does not stamp, so they live in a
    subdirectory. Writing them beside the build's own broke that guard once.
    """
    season = _have_seasonal()
    if not season:
        return _skip("no cached nflverse seasonal file")
    assert _seasonal_file(season).parent.name == SE.SEASONAL_DIR
    loose = [p.name for p in (_ROOT / ".cache").glob("*.csv")
             if p.name.startswith("nflverse_stats_player_season_")]
    assert loose == [], loose
    log = _ROOT / ".cache" / "_fetch_log.json"
    if log.exists():
        stamped = set(json.loads(log.read_text()))
        unstamped = sorted({p.name for p in (_ROOT / ".cache").glob("*.csv")} - stamped)
        assert unstamped == [], unstamped


def test_the_seam_guard_can_fail():
    # A guard that cannot fail is decoration: at a zero tolerance the known
    # upstream drift must surface.
    if not _seasons() or not _have_full_seasonal_history():
        return _skip("seasonal history not fully cached")
    assert SE.check_career_to_date_arithmetic(max_player_rate=0.0) != []


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
        test_basis_measure_and_years_rule_reject_junk,
        test_the_default_tenure_rule_follows_the_career_measure,
        test_a_seasonal_file_carries_reg_post_rows_and_they_are_never_summed,
        test_career_totals_equal_the_rows_the_basis_names,
        test_career_to_date_never_exceeds_the_lifetime_total,
        test_lowest_careers_is_sorted_and_keeps_ties_at_the_cutoff,
        test_lowest_careers_reports_the_earliest_of_equal_starts,
        test_the_season_cache_stays_out_of_the_builds_freshness_gate,
        test_the_career_guards_pass_on_real_data,
        test_the_seam_guard_can_fail,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all scoring-event checks passed")
