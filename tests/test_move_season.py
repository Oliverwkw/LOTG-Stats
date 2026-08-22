"""Which season a dated roster move belongs to.

A season is kickoff week 1 through the end of the championship game, and a move
carries the label of the season whose in-season or offseason it is part of. In
practice that makes the label the move's own calendar year — with exactly one
exception, which is the whole reason the helper exists:

    A move made between January 1 and that season's **championship Monday**
    happened while the season was still being PLAYED, and belongs to it, even
    though the calendar has ticked over.

Those are the only rows whose listed year differs from their date; there are two
of them in the whole dataset. Once championship Monday is past the offseason has
begun, and every move takes its own calendar year through to the next kickoff.

Two things about the old behaviour are worth pinning, because both surprised the
investigation that produced this:

  * It was **not** calendar year, though it looks like it from outside. It was
    Sleeper's own league rollover, which lands on a different date each year —
    so some January moves were already right and others were not.
  * It broke at **both** ends. Some January moves were filed under the season
    about to start, and 15 rows dated December 31 under the season after —
    fourteen of them the synthesized 2020-12-31 ESPN->Sleeper migration drops.

The rule reads the **league** clock. Timestamps are UTC internally and the Date
column is rendered America/New_York at write time, so 2021-01-01 00:00 UTC
displays as 2020-12-31 19:00. Deriving the season from the UTC month would label
a row from a date that appears nowhere on the sheet — which is the same
representation mismatch that produced the startup-draft bug. The export guard
below is written against the DISPLAYED date for exactly that reason: it is the
one a reader can check.

Run: python tests/test_move_season.py
"""
from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

import lotg  # noqa: E402

_EXPORTS = _ROOT / "exports"
_HAVE = (_EXPORTS / "transactions.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


# Championship Monday per season — the far edge of "in-season".
_ENDS = {
    2020: date(2020, 12, 28),
    2021: date(2022, 1, 3),
    2022: date(2023, 1, 2),
    2023: date(2024, 1, 1),
    2024: date(2024, 12, 30),
    2025: date(2025, 12, 29),
    2026: date(2027, 1, 4),
}


def _rows(name: str):
    with (_EXPORTS / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# the rule itself
# --------------------------------------------------------------------------- #
def test_only_up_to_championship_monday_rolls_back():
    for iso, want, why in (
        ("2022-01-02T18:00:00+00:00", 2021, "2021 championship Sunday"),
        ("2022-01-03T18:00:00+00:00", 2021, "2021 championship Monday, inclusive"),
        ("2022-01-04T18:00:00+00:00", 2022, "the day after — offseason has begun"),
        ("2023-01-01T18:00:00+00:00", 2022, "2022's final ran to Jan 2"),
        ("2023-01-10T18:00:00+00:00", 2023, "well past it"),
        ("2024-01-13T18:00:00+00:00", 2024, "2023 ended Jan 1"),
        ("2025-01-01T18:00:00+00:00", 2025, "2024 ended Dec 30 — already offseason"),
        ("2026-01-01T18:00:00+00:00", 2026, "2025 ended Dec 29"),
        ("2020-12-31T18:00:00+00:00", 2020, "after its own championship, own year"),
        ("2022-02-09T12:00:00+00:00", 2022, "offseason keeps its own year"),
        ("2022-03-09T21:05:26+00:00", 2022, "offseason keeps its own year"),
        ("2020-09-09T21:45:18+00:00", 2020, "preseason keeps its own year"),
    ):
        assert lotg._move_season(_utc(iso), 9999, _ENDS) == want, (iso, why)


def test_a_season_with_no_known_end_never_rolls_a_move_back():
    # An in-progress season has no championship Monday yet; guessing one would
    # relabel live moves, so nothing rolls back into it.
    assert lotg._move_season(_utc("2027-01-02T18:00:00+00:00"), 9999, {2026: None}) == 2027
    assert lotg._move_season(_utc("2027-01-02T18:00:00+00:00"), 9999, {}) == 2027


def test_it_reads_the_league_clock_not_utc():
    # 2021-01-01 00:00 UTC is 2020-12-31 19:00 in New York: December there, so
    # the season that just ended. This is the boundary the 14 synthesized
    # ESPN->Sleeper migration drops sit on.
    assert lotg._move_season(_utc("2021-01-01T00:00:00+00:00"), 9999, _ENDS) == 2020
    # And the mirror: 2022-01-04 00:00 UTC is 2022-01-03 19:00 in New York —
    # championship Monday, so it rolls back where the UTC date would not.
    assert lotg._move_season(_utc("2022-01-04T00:00:00+00:00"), 9999, _ENDS) == 2021


def test_a_naive_timestamp_is_read_as_utc_not_rejected():
    naive = datetime(2021, 1, 1, 0, 0)
    assert lotg._move_season(naive, 9999, _ENDS) == 2020


def test_no_timestamp_falls_back_rather_than_guessing():
    assert lotg._move_season(None, 2024, _ENDS) == 2024


# --------------------------------------------------------------------------- #
# the sheets (needs a build carrying this rule)
# --------------------------------------------------------------------------- #
def _expected(displayed_date: str) -> int:
    when = date.fromisoformat(displayed_date)
    prev_end = _ENDS.get(when.year - 1)
    return when.year - 1 if (prev_end is not None and when <= prev_end) else when.year


def test_every_dated_move_agrees_with_its_own_date():
    """Season and Date must be answerable against each other on the sheet.

    Checked against the DISPLAYED date, not the internal UTC one — a reader with
    the CSV open can run this check by eye, which is the point.
    """
    if not _HAVE:
        return _skip("no exports/")
    problems = []
    checked = 0
    for name in ("trades.csv", "transactions.csv"):
        for r in _rows(name):
            when = str(r["Date"])[:10]
            if len(when) < 10:
                continue
            checked += 1
            got, want = int(r["Season"]), _expected(when)
            if got != want:
                problems.append(f"{name} {r['Team']} {when}: Season {got}, expected {want}")
    assert checked > 1500, checked
    assert not problems, problems[:10]


def test_the_only_year_mismatches_are_played_in_january():
    """A listed year that differs from the date is the exception, so name it.

    Every such row must be a move made in January, on or before the championship
    Monday of the season it is labelled with — i.e. while that season's final
    was still to be played. Anything else is a defect.
    """
    if not _HAVE:
        return _skip("no exports/")
    odd = []
    for name in ("trades.csv", "transactions.csv"):
        for r in _rows(name):
            when = date.fromisoformat(str(r["Date"])[:10])
            if int(r["Season"]) != when.year:
                odd.append((name, r["Team"], when, int(r["Season"])))
    assert odd, "no year mismatches at all — the guard would be vacuous"
    for name, team, when, season in odd:
        assert when.month == 1, (name, team, str(when), season, "not January")
        end = _ENDS.get(season)
        assert end is not None and when <= end, (
            name, team, str(when), season, f"past championship Monday {end}")


def test_player_year_transaction_counts_follow_the_same_seasons():
    """The per-season player counts must agree with the rows they come from.

    This is the reconciliation the change could most easily have broken: the
    Season on the record moved, so anything bucketing by season had to move with
    it or the sheets would quietly disagree.
    """
    if not _HAVE or not (_EXPORTS / "player_year.csv").exists():
        return _skip("no exports/")
    from collections import Counter, defaultdict
    per = defaultdict(Counter)
    for r in _rows("transactions.csv"):
        season = int(r["Season"])
        if r["Player Added"]:
            per[season][r["Player Added"]] += 1
        if r["Player Dropped"]:
            per[season][r["Player Dropped"]] += 1
    bad, checked = [], 0
    for r in _rows("player_year.csv"):
        raw = str(r.get("Number of transactions", "")).strip()
        if raw in ("", "nan", "N/A"):
            continue
        checked += 1
        got = int(float(raw))
        want = per[int(r["Year"])][r["Player"]]
        if got != want:
            bad.append(f"{r['Player']} {r['Year']}: player_year {got}, transactions.csv {want}")
    assert checked > 1000, checked
    assert not bad, bad[:10]


def test_the_trade_split_still_reconciles():
    if not _HAVE:
        return _skip("no exports/")
    for name in ("team_year.csv", "league_year.csv"):
        seen = 0
        for r in _rows(name):
            tot = str(r.get("Total trades", "")).strip()
            if tot in ("", "nan", "N/A"):
                continue
            off = int(float(r["Offseason trades"]))
            ins = int(float(r["Inseason trades"]))
            assert off + ins == int(float(tot)), (name, r.get("Year"), off, ins, tot)
            seen += 1
        assert seen, name


if __name__ == "__main__":
    for fn in (
        test_only_up_to_championship_monday_rolls_back,
        test_a_season_with_no_known_end_never_rolls_a_move_back,
        test_it_reads_the_league_clock_not_utc,
        test_a_naive_timestamp_is_read_as_utc_not_rejected,
        test_no_timestamp_falls_back_rather_than_guessing,
        test_every_dated_move_agrees_with_its_own_date,
        test_the_only_year_mismatches_are_played_in_january,
        test_player_year_transaction_counts_follow_the_same_seasons,
        test_the_trade_split_still_reconciles,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all move-season checks passed")
