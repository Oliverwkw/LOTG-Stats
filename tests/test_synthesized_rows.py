"""Synthesized transaction rows must count exactly like real ones.

The build synthesizes lineage-closing transactions — the 2020->2021 platform
transfer releases, terminal dead-end cuts, and arrivals with no recorded add —
so a player's ownership history has no holes in it. Those rows are appended to
`transactions_rows` **after** the weekly loop has finished, so the scattered
per-event counters never saw them: they were rendered into `add_drops.csv`
and counted in no team's season total. 28 of 56 completed team-seasons were
short, by 85 moves in total; `JacobRosenzweig 2021` read **2** transactions
against **13** rows in its own detail sheets.

The team counters are now rebuilt from the final rows — the same fix, and for
the same reason, as the `player_year` / `player_all_time` rebuild that already
sat directly above them in the build. A synthesized row that falls in-season
also gets its `team_week` bucket, derived from its own date on the league clock
(it has no Sleeper leg to read — it never existed on the platform).

These read `exports/` and skip when it is absent; they need a build carrying
this fix, and they assert only against completed seasons.

Run: python tests/test_synthesized_rows.py
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

import lotg  # noqa: E402

_EXPORTS = _ROOT / "exports"
_HAVE = (_EXPORTS / "team_year.csv").exists()

# The worst case before the fix, and a legible one: nearly its whole 2021 was
# lineage rows, so the sheet said 2 where the detail tables said 13.
_NAMED = ("JacobRosenzweig", 2021)


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _rows(name: str):
    with (_EXPORTS / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(v):
    s = str(v).strip()
    return None if s in ("", "nan", "None", "N/A") else float(s)


def _detail_counts():
    """(team, season) -> number of rows across add_drops.csv + trades.csv."""
    from collections import defaultdict
    n = defaultdict(int)
    for sheet in ("add_drops.csv", "trades.csv"):
        for r in _rows(sheet):
            n[(r["Team"], int(r["Season"]))] += 1
    return n


def test_team_year_counts_every_row_of_its_detail_sheets():
    """The whole point: a row in the sheet is a row in the count.

    'Total transactions' counts trades too (Number of Add/Drops + trades), so
    the two detail sheets together are the population.
    """
    if not _HAVE:
        return _skip("no exports/")
    n = _detail_counts()
    checked = 0
    for r in _rows("team_year.csv"):
        v = _num(r.get("Total transactions"))
        if v is None:
            continue
        key = (r["Team"], int(r["Year"]))
        assert int(v) == n[key], (key, int(v), n[key],
                                  "season total disagrees with its own detail rows")
        checked += 1
    assert checked > 40, checked


def test_the_named_case_is_counted_in_full():
    if not _HAVE:
        return _skip("no exports/")
    n = _detail_counts()
    got = [r for r in _rows("team_year.csv")
           if (r["Team"], int(r["Year"])) == _NAMED]
    assert len(got) == 1, len(got)
    assert int(_num(got[0]["Total transactions"]) or 0) == n[_NAMED] > 10, (
        got[0]["Total transactions"], n[_NAMED])


def test_the_lineage_rows_are_really_there_to_be_counted():
    """Guards the guard: if the synthesized rows ever stop being emitted, the
    checks above go quietly vacuous rather than failing."""
    if not _HAVE:
        return _skip("no exports/")
    lineage = [r for r in _rows("add_drops.csv")
               if (r["Team"], int(r["Season"])) == _NAMED
               and not (r.get("Player Added") or "").strip()
               and _num(r.get("Faab")) is None]
    assert len(lineage) >= 8, len(lineage)


def test_an_in_season_synthesized_row_lands_in_a_week():
    """A synthesized row made during the season has a week, so it must not widen
    the team_year / team_week gap. Only the rows with no week may — and the
    build's rule for that is a date more than 7 days before kickoff."""
    if not _HAVE or not (_EXPORTS / "team_week.csv").exists():
        return _skip("no exports/")
    from collections import defaultdict
    weeks = defaultdict(int)
    played = set()
    for r in _rows("team_week.csv"):
        played.add(int(r["Year"]))
        v = _num(r.get("Total transactions"))
        if v is not None:
            weeks[(r["Team"], int(r["Year"]))] += int(v)
    weekless = defaultdict(int)
    for sheet in ("add_drops.csv", "trades.csv"):
        for r in _rows(sheet):
            season = int(r["Season"])
            when = date.fromisoformat(str(r["Date"])[:10])
            if not lotg._season_week_of(when, season):
                weekless[(r["Team"], season)] += 1
    n = _detail_counts()
    checked = 0
    for key, total in n.items():
        if key[1] not in played:
            continue
        checked += 1
        assert total - weeks[key] <= weekless[key], (
            key, total, weeks[key], weekless[key],
            "more moves missing from the weeks than have no week to sit in")
    assert checked > 40, checked


if __name__ == "__main__":
    for fn in (
        test_team_year_counts_every_row_of_its_detail_sheets,
        test_the_named_case_is_counted_in_full,
        test_the_lineage_rows_are_really_there_to_be_counted,
        test_an_in_season_synthesized_row_lands_in_a_week,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all synthesized-row checks passed")
