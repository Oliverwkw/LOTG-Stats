"""A skipped weekly run must not silently delete that week from the record.

GitHub drops scheduled events outright (2026-07-07), so a week with no digest run
is reachable, not hypothetical. Most of the digest survives it: crossings,
records, pace and event moves all diff STATE against the prior snapshot — an
entity's previous value against its current one — so a two-week gap simply
reports the two-week move whole.

Single-week records are the exception, and that asymmetry is the whole point of
this file. A single-week performance is not a state; it belongs to its week, and
the section only ever asked for latest_completed_week(). Skip week 6's run and
week 6's records are never mentioned again — silently, with nothing in the email
to say so.

Run: PYTHONPATH=src:lib python tests/test_digest_missed_week.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "lib", _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_digest as B  # noqa: E402
from lotg_support import digest as D  # noqa: E402


def _tw(weeks, season=2026):
    """team_week with one row per (week, team)."""
    return pd.DataFrame([{"Year": season, "Week": w, "Team": t, "PF": 100 + w + t}
                         for w in weeks for t in range(1, 9)])


def _meta(season=2026, weeks=0):
    return {"season": season, "weeks_completed": weeks}


def _snap(season=2026, weeks=0):
    return {"meta": {"season": season, "weeks_completed": weeks}}


def test_the_ordinary_week_is_untouched():
    """gap == 1 must behave exactly as the section always has: latest week only."""
    tw = _tw(range(1, 8))
    covered, note = B._weeks_to_cover(_snap(weeks=6), _meta(weeks=7), tw)
    assert covered == [D.latest_completed_week(tw, 2026)] == [7], covered
    assert note is None


def test_a_missed_week_is_made_up():
    tw = _tw(range(1, 8))
    # last successful digest saw 5 weeks; we are now at 7 -> week 6 was skipped
    covered, note = B._weeks_to_cover(_snap(weeks=5), _meta(weeks=7), tw)
    assert covered == [6, 7], covered
    assert "1 weekly run(s) never happened" in note
    assert "::warning::" in note


def test_the_backfill_is_capped_and_says_what_it_dropped():
    tw = _tw(range(1, 12))
    covered, note = B._weeks_to_cover(_snap(weeks=3), _meta(weeks=11), tw)
    assert covered == [8, 9, 10, 11], covered
    assert "NOT covered" in note and "4, 5, 6, 7" in note, note


def test_a_new_season_does_not_backfill_the_old_one():
    tw = _tw([1], season=2027)
    covered, note = B._weeks_to_cover(_snap(season=2026, weeks=17),
                                      _meta(season=2027, weeks=1), tw)
    assert covered == [1] and note is None


def test_a_baseline_run_covers_only_the_latest_week():
    tw = _tw(range(1, 4))
    assert B._weeks_to_cover(None, _meta(weeks=3), tw) == ([3], None)


def test_the_offseason_covers_nothing():
    assert B._weeks_to_cover(_snap(weeks=0), _meta(weeks=0), _tw([])) == ([], None)


def test_the_anchor_is_the_max_week_not_the_count():
    """weeks_completed is a COUNT, latest_completed_week is a MAX.

    They diverge the moment a week is missing from team_week, and anchoring the
    section on the count would put the ordinary digest on the wrong week.
    """
    tw = _tw([1, 2, 4])                      # week 3 absent: count 3, max 4
    assert D.weeks_completed(tw, 2026) == 3
    assert D.latest_completed_week(tw, 2026) == 4
    covered, _ = B._weeks_to_cover(_snap(weeks=2), _meta(weeks=3), tw)
    assert covered == [4], covered


def test_the_week_is_named_only_when_more_than_one_is_covered():
    one = D.WeeklyHighlight("players", "X", "PF", "high", 1, 9.9, week=7)
    assert "[week 7]" not in one.detail()
    one.show_week = True
    assert "[week 7]" in one.detail()


def test_the_section_title_names_the_span_it_covers():
    hs = [D.WeeklyHighlight("players", "X", "PF", "high", 1, 9.9, week=w)
          for w in (6, 7)]
    titles = [t for t, _, _ in D.digest_sections(highlights=hs)]
    assert any("weeks 6-7" in t for t in titles), titles
    solo = [D.WeeklyHighlight("players", "X", "PF", "high", 1, 9.9, week=7)]
    titles = [t for t, _, _ in D.digest_sections(highlights=solo)]
    assert any("(this week)" in t for t in titles), titles


def test_a_real_missed_week_is_recovered_from_the_committed_exports():
    """End to end on real data: week N's records reappear in an N+1 digest."""
    ex = _ROOT / "exports"
    if not (ex / "team_week.csv").exists():
        print("SKIP  exports/ absent")
        return
    tw = pd.read_csv(ex / "team_week.csv", low_memory=False)
    pw = pd.read_csv(ex / "player_week.csv", low_memory=False)
    lw = pd.read_csv(ex / "league_week.csv", low_memory=False)
    ty = pd.read_csv(ex / "team_year.csv", low_memory=False)
    season = 2025
    solo = D.weekly_highlights(pw, tw, lw, ty, season=season, week=6)
    assert solo, "fixture week has no highlights; pick another"
    both = (D.weekly_highlights(pw, tw, lw, ty, season=season, week=6)
            + D.weekly_highlights(pw, tw, lw, ty, season=season, week=7))
    assert len(both) > len(solo)
    assert {h.week for h in both} == {6, 7}
    print(f"      week 6 alone: {len(solo)} records; weeks 6+7 recovered: {len(both)}")


TESTS = [test_the_ordinary_week_is_untouched,
         test_a_missed_week_is_made_up,
         test_the_backfill_is_capped_and_says_what_it_dropped,
         test_a_new_season_does_not_backfill_the_old_one,
         test_a_baseline_run_covers_only_the_latest_week,
         test_the_offseason_covers_nothing,
         test_the_anchor_is_the_max_week_not_the_count,
         test_the_week_is_named_only_when_more_than_one_is_covered,
         test_the_section_title_names_the_span_it_covers,
         test_a_real_missed_week_is_recovered_from_the_committed_exports]

if __name__ == "__main__":
    bad = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            bad += 1; print(f"FAIL  {t.__name__}: {e}")
    sys.exit(1 if bad else 0)
