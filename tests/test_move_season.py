"""Which season a dated roster move belongs to.

The trade deadline passes but adds and drops keep going, so the tail of a season
spills past New Year — those moves are that season's business, not the next
one's. `_move_season` rolls January back a year and leaves every other month
alone, which reproduces the label the build already gave all but 84 of its 2096
moves.

Two things about the old behaviour are worth pinning, because both surprised the
investigation that produced this:

  * It was **not** calendar year, though it looks like it from outside. It was
    Sleeper's own league rollover, which lands on a different date each year —
    so 3 of the 7 January groups were already right and 4 were not.
  * It broke at **both** ends. January moves filed under the season about to
    start, and 15 rows dated December 31 filed under the season after — fourteen
    of them the synthesized 2020-12-31 ESPN->Sleeper migration drops.

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
from datetime import datetime, timezone
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


def _rows(name: str):
    with (_EXPORTS / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# the rule itself
# --------------------------------------------------------------------------- #
def test_january_rolls_back_and_nothing_else_does():
    for iso, want in (
        ("2022-01-05T12:00:00+00:00", 2021),
        ("2023-01-10T18:00:00+00:00", 2022),
        ("2026-01-04T15:00:00+00:00", 2025),
        ("2022-02-09T12:00:00+00:00", 2022),   # February keeps its own year
        ("2022-03-09T21:05:26+00:00", 2022),
        ("2020-09-09T21:45:18+00:00", 2020),
        ("2020-12-16T16:43:22+00:00", 2020),
    ):
        assert lotg._move_season(_utc(iso), 9999) == want, iso


def test_it_reads_the_league_clock_not_utc():
    # 2021-01-01 00:00 UTC is 2020-12-31 19:00 in New York: December there, so
    # the season that just ended. This is the boundary the 14 synthesized
    # ESPN->Sleeper migration drops sit on.
    assert lotg._move_season(_utc("2021-01-01T00:00:00+00:00"), 9999) == 2020
    # And the mirror: late on Jan 31 in New York is February in UTC.
    assert lotg._move_season(_utc("2022-02-01T04:00:00+00:00"), 9999) == 2021


def test_a_naive_timestamp_is_read_as_utc_not_rejected():
    naive = datetime(2021, 1, 1, 0, 0)
    assert lotg._move_season(naive, 9999) == 2020


def test_no_timestamp_falls_back_rather_than_guessing():
    assert lotg._move_season(None, 2024) == 2024


# --------------------------------------------------------------------------- #
# the sheets (needs a build carrying this rule)
# --------------------------------------------------------------------------- #
def _expected(displayed_date: str) -> int:
    year, month = int(displayed_date[:4]), int(displayed_date[5:7])
    return year - 1 if month == 1 else year


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


def test_january_moves_land_in_the_season_that_just_ended():
    # The concrete case, so a regression names itself rather than showing up as
    # an arithmetic mismatch.
    if not _HAVE:
        return _skip("no exports/")
    jan = [r for r in _rows("transactions.csv") if str(r["Date"])[5:7] == "01"]
    assert jan, "no January transactions — guard would be vacuous"
    for r in jan:
        assert int(r["Season"]) == int(str(r["Date"])[:4]) - 1, (r["Team"], r["Date"], r["Season"])


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
        test_january_rolls_back_and_nothing_else_does,
        test_it_reads_the_league_clock_not_utc,
        test_a_naive_timestamp_is_read_as_utc_not_rejected,
        test_no_timestamp_falls_back_rather_than_guessing,
        test_every_dated_move_agrees_with_its_own_date,
        test_january_moves_land_in_the_season_that_just_ended,
        test_player_year_transaction_counts_follow_the_same_seasons,
        test_the_trade_split_still_reconciles,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all move-season checks passed")
