"""The tenure ledger's clock — an open tenure must not be measured to "right now".

"Top team" (player_year, player_all_time) is an argmax over how long each team
held the player. A tenure that has not ended has no end date, so it is measured
to a clock; when that clock was `datetime.now()`, the ANSWER depended on the
minute the build ran. Two teams within a few hours of each other in a season's
ownership race simply traded places between one build and the next, with no new
data in between.

That is the whole of the 2026-09-16 dataset-health email — "1 breakage, 2 changed
rows, all of it one column, Top Team":

  * Ray Davis  — shmuel256 -> plehv79    (crossed 09:01:52 UTC)
  * Tre Tucker — shmuel256 -> AceMatthew (crossed 10:16:10 UTC)

both inside the 17 hours between the Tuesday build that committed the exports
(run 511, 2026-09-16 01:38 UTC) and the Wednesday rebuild that audits them
(health run 9, 18:35 UTC). Neither player changed hands; the clock moved.

`_tenure_as_of` replaces the wall clock with one that advances with the DATA —
the most recent fantasy week whose games are final, or the latest tenure event
when that is later (the offseason) — so a rebuild that learns nothing new
reproduces the same ranking.

Pure helpers only; no exports needed.

Run: python tests/test_tenure_as_of_clock.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

from lotg import (  # noqa: E402
    _last_final_week_cutoff,
    _tenure_as_of,
    _week_complete_cutoff,
)

UTC = timezone.utc

# The two real build instants the health email compared.
_BUILD = datetime(2026, 9, 16, 1, 38, tzinfo=UTC)     # CI build run 511
_REBUILD = datetime(2026, 9, 16, 18, 35, tzinfo=UTC)  # health-email run 9
# The latest transaction either of them could see (2026-09-15 14:23:21 UTC),
# straight off the committed snapshot.
_LAST_TX = datetime(2026, 9, 15, 14, 23, 21, tzinfo=UTC)
# 2026 week 1's Monday night game is Sept 14; the week is final at Tue 08:00 UTC.
_WEEK1_FINAL = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The week clock
# ---------------------------------------------------------------------------
def test_the_last_final_week_is_the_one_whose_games_are_over():
    assert _week_complete_cutoff(2026, 1) == _WEEK1_FINAL
    # Anywhere inside week 2 — before week 2's own cutoff — week 1 is the last
    # one that is final.
    for now in (_BUILD, _REBUILD, datetime(2026, 9, 20, 23, 59, tzinfo=UTC)):
        assert _last_final_week_cutoff(now, 2020) == _WEEK1_FINAL, now
    # And it does advance: past week 2's cutoff, week 2 is.
    assert (_last_final_week_cutoff(datetime(2026, 9, 23, tzinfo=UTC), 2020)
            == _week_complete_cutoff(2026, 2))


def test_no_week_is_final_before_the_first_season_kicks_off():
    assert _last_final_week_cutoff(datetime(2020, 1, 1, tzinfo=UTC), 2020) is None


def test_the_week_clock_never_runs_ahead_of_now():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    cut = _last_final_week_cutoff(now, 2020)
    assert cut is not None and cut <= now


# ---------------------------------------------------------------------------
# The as-of clock
# ---------------------------------------------------------------------------
def test_a_rebuild_with_no_new_data_gets_the_same_clock():
    """The regression itself: 17 hours apart, same data, same answer."""
    assert (_tenure_as_of(_BUILD, _LAST_TX, 2020)
            == _tenure_as_of(_REBUILD, _LAST_TX, 2020))
    # Every hour in between, too — the flips were at 09:01:52 and 10:16:10 UTC.
    seen = {_tenure_as_of(_BUILD + timedelta(hours=h), _LAST_TX, 2020)
            for h in range(0, 17)}
    assert len(seen) == 1, seen


def test_the_latest_event_wins_when_it_is_the_newer_fact():
    # In-season: the last transaction (Sept 15 14:23) is newer than week 1
    # going final (Sept 15 08:00), so ownership keeps accruing to it.
    assert _tenure_as_of(_BUILD, _LAST_TX, 2020) == _LAST_TX
    # Offseason: no week has been final since January, so the league's own
    # moves are the only clock there is.
    july = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    july_tx = datetime(2026, 7, 15, 7, 42, 48, tzinfo=UTC)
    assert _tenure_as_of(july, july_tx, 2020) == july_tx


def test_a_quiet_week_still_advances_with_the_football():
    """The week clock is what stops a quiet league freezing the ledger."""
    stale_tx = datetime(2026, 9, 2, tzinfo=UTC)          # before week 1
    assert _tenure_as_of(_BUILD, stale_tx, 2020) == _WEEK1_FINAL
    later = _tenure_as_of(datetime(2026, 9, 23, tzinfo=UTC), stale_tx, 2020)
    assert later == _week_complete_cutoff(2026, 2) > _WEEK1_FINAL


def test_the_clock_is_never_in_the_future_and_falls_back_to_now():
    for now, ev in ((_BUILD, _LAST_TX),
                    (_BUILD, datetime(2027, 1, 1, tzinfo=UTC)),   # bad future date
                    (datetime(2026, 7, 1, tzinfo=UTC), None)):
        assert _tenure_as_of(now, ev, 2020) <= now, (now, ev)
    # Nothing known at all -> the wall clock, i.e. the old behaviour.
    nothing = datetime(2019, 1, 1, tzinfo=UTC)
    assert _tenure_as_of(nothing, None, 2020) == nothing


# ---------------------------------------------------------------------------
# The ranking that moved
# ---------------------------------------------------------------------------
_SEASON_OPEN = datetime(2026, 9, 1, tzinfo=UTC)   # FY2026's in-season window opens


def _leader(spells, now):
    """The build's Top-team rule, reduced to its essentials: seconds per team
    inside the in-season window, open tenure clipped at `now`, argmax."""
    secs = {}
    for team, start, end in spells:
        stop = min(end or now, now)
        if stop > start:
            secs[team] = secs.get(team, 0.0) + (stop - start).total_seconds()
    return max(secs.items(), key=lambda kv: kv[1])[0] if secs else None


# Both spells, FY2026, straight off the committed snapshot's transaction feed:
# shmuel256 held each player from the window opening until he dropped them on
# 2026-09-07, and the waiver run of 2026-09-09 gave them to their current team.
_RAY_DAVIS = (
    ("shmuel256", _SEASON_OPEN, datetime(2026, 9, 7, 13, 43, 9, 175000, tzinfo=UTC)),
    ("plehv79", datetime(2026, 9, 9, 19, 18, 43, 17000, tzinfo=UTC), None),
)
_TRE_TUCKER = (
    ("shmuel256", _SEASON_OPEN, datetime(2026, 9, 7, 13, 44, 56, 799000, tzinfo=UTC)),
    ("AceMatthew", datetime(2026, 9, 9, 20, 31, 13, 2000, tzinfo=UTC), None),
)


def test_the_wall_clock_really_did_flip_the_ranking():
    """Guard that the failure mode is real, not hypothetical."""
    assert _leader(_RAY_DAVIS, _BUILD) == "shmuel256"
    assert _leader(_RAY_DAVIS, _REBUILD) == "plehv79"
    assert _leader(_TRE_TUCKER, _BUILD) == "shmuel256"
    assert _leader(_TRE_TUCKER, _REBUILD) == "AceMatthew"


def test_the_as_of_clock_holds_it_still():
    for spells in (_RAY_DAVIS, _TRE_TUCKER):
        at_build = _leader(spells, _tenure_as_of(_BUILD, _LAST_TX, 2020))
        at_rebuild = _leader(spells, _tenure_as_of(_REBUILD, _LAST_TX, 2020))
        # shmuel256 is what both sheets actually ship for 2026.
        assert at_build == at_rebuild == "shmuel256", spells


def test_the_ranking_is_not_frozen_forever():
    """Still moves — just on the football calendar rather than the build clock."""
    week3 = datetime(2026, 9, 30, tzinfo=UTC)
    assert _leader(_RAY_DAVIS, _tenure_as_of(week3, _LAST_TX, 2020)) == "plehv79"


if __name__ == "__main__":
    for fn in (
        test_the_last_final_week_is_the_one_whose_games_are_over,
        test_no_week_is_final_before_the_first_season_kicks_off,
        test_the_week_clock_never_runs_ahead_of_now,
        test_a_rebuild_with_no_new_data_gets_the_same_clock,
        test_the_latest_event_wins_when_it_is_the_newer_fact,
        test_a_quiet_week_still_advances_with_the_football,
        test_the_clock_is_never_in_the_future_and_falls_back_to_now,
        test_the_wall_clock_really_did_flip_the_ranking,
        test_the_as_of_clock_holds_it_still,
        test_the_ranking_is_not_frozen_forever,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all tenure as-of clock checks passed")
