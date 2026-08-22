"""Which season a dated roster move belongs to.

A season runs from kickoff week 1 to the end of its championship game, and
everything after that championship belongs to the NEXT season — its offseason —
through to that season's kickoff. The whole rule is one comparison:

    a move belongs to the first season whose championship has not happened yet.

That settles both edges at once, and both edges really occur here, because the
championship date moves: 2020's final was Dec 28 and 2021's ran to Jan 3. So a
move in January *before* the final is still the old season (it is still being
played), and a move in late December *after* the final is already the new one
(even though the calendar has not turned). A listed year can therefore differ
from its date in either direction, and the league calendar decides which — not
the month.

The old behaviour was **not** calendar year, though it looks like it from
outside: the season came from Sleeper's league rollover, which lands on a
different date each year. It happened to agree with the real league calendar
almost everywhere, which is why so few rows move.

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
def test_the_season_is_the_first_championship_not_yet_played():
    for iso, want, why in (
        ("2020-09-09T21:45:18+00:00", 2020, "preseason 2020"),
        ("2020-12-16T16:43:22+00:00", 2020, "in-season 2020"),
        ("2020-12-31T18:00:00+00:00", 2021, "AFTER 2020's Dec 28 final -> next season"),
        ("2022-01-02T18:00:00+00:00", 2021, "2021 championship Sunday, still 2021"),
        ("2022-01-03T18:00:00+00:00", 2021, "2021 championship Monday, inclusive"),
        ("2022-01-04T18:00:00+00:00", 2022, "the day after -> 2022"),
        ("2022-03-09T21:05:26+00:00", 2022, "2022 offseason"),
        ("2023-01-01T18:00:00+00:00", 2022, "2022's final ran to Jan 2"),
        ("2023-01-10T18:00:00+00:00", 2023, "past it -> 2023"),
        ("2024-01-13T18:00:00+00:00", 2024, "2023 ended Jan 1"),
        ("2025-01-01T18:00:00+00:00", 2025, "2024 ended Dec 30 — already 2025"),
        ("2025-12-31T18:00:00+00:00", 2026, "AFTER 2025's Dec 29 final -> 2026"),
        ("2026-01-01T18:00:00+00:00", 2026, "2026 offseason"),
    ):
        assert lotg._move_season(_utc(iso), 9999, _ENDS) == want, (iso, why)


def test_a_december_championship_pushes_the_rest_of_december_forward():
    # The half of the rule a month-based reading gets wrong. 2020's final was
    # Dec 28 and 2025's Dec 29, so the last days of those calendar years are
    # already the NEXT season's offseason.
    assert lotg._move_season(_utc("2020-12-29T18:00:00+00:00"), 9999, _ENDS) == 2021
    assert lotg._move_season(_utc("2025-12-30T18:00:00+00:00"), 9999, _ENDS) == 2026
    # while a final that runs into January holds its own season there
    assert lotg._move_season(_utc("2022-01-01T18:00:00+00:00"), 9999, _ENDS) == 2021


def test_past_every_known_championship_it_falls_forward_not_back():
    # A season whose playoff start we have not learned has no end, so it cannot
    # be matched; the move belongs to the season after the last finished one.
    assert lotg._move_season(_utc("2026-12-31T18:00:00+00:00"), 9999,
                             {2025: date(2025, 12, 29)}) == 2026
    assert lotg._move_season(_utc("2027-06-01T18:00:00+00:00"), 9999,
                             {2025: date(2025, 12, 29)}) == 2027
    # and with nothing to go on at all it takes the date's own year
    assert lotg._move_season(_utc("2027-01-02T18:00:00+00:00"), 9999, {}) == 2027


def test_it_reads_the_league_clock_not_utc():
    # 2021-01-01 00:00 UTC is 2020-12-31 19:00 in New York: December there, so
    # the season that just ended. This is the boundary the 14 synthesized
    # ESPN->Sleeper migration drops sit on.
    assert lotg._move_season(_utc("2021-01-01T00:00:00+00:00"), 9999, _ENDS) == 2021
    # 2022-01-04 00:00 UTC is 2022-01-03 19:00 in New York — championship
    # Monday, so it is still 2021 where the UTC date would say 2022.
    assert lotg._move_season(_utc("2022-01-04T00:00:00+00:00"), 9999, _ENDS) == 2021


def test_a_naive_timestamp_is_read_as_utc_not_rejected():
    naive = datetime(2021, 1, 1, 0, 0)
    assert lotg._move_season(naive, 9999, _ENDS) == 2021


def test_no_timestamp_falls_back_rather_than_guessing():
    assert lotg._move_season(None, 2024, _ENDS) == 2024


# --------------------------------------------------------------------------- #
# the sheets (needs a build carrying this rule)
# --------------------------------------------------------------------------- #
def _expected(displayed_date: str) -> int:
    when = date.fromisoformat(displayed_date)
    for season in sorted(_ENDS):
        if when <= _ENDS[season]:
            return season
    return max(max(_ENDS) + 1, when.year)


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


def test_every_year_mismatch_straddles_a_championship():
    """A listed year that differs from the date is fine — but only at the seam.

    Both directions are legal and both occur: a January move before its
    season's final keeps the old year, a late-December move after its season's
    final takes the new one. What is NOT legal is a mismatch away from that
    boundary, so each one is checked against the championship it straddles.
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
        where = (name, team, str(when), season)
        if season == when.year - 1:
            # labelled with the season that was still being played
            end = _ENDS.get(season)
            assert end is not None and when <= end, (*where, f"past its final {end}")
        elif season == when.year + 1:
            # labelled with the season whose offseason had already begun
            end = _ENDS.get(when.year)
            assert end is not None and when > end, (*where, f"not yet past {end}")
        else:
            raise AssertionError((*where, "off by more than one season"))


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


# --------------------------------------------------------------------------- #
# the counters that follow the season, not the league week
# --------------------------------------------------------------------------- #
def _num(v):
    t = str(v).strip()
    return None if t in ("", "nan", "None", "N/A") else float(t)


def test_team_year_equals_the_weeks_except_where_a_move_has_no_week():
    """`team_year` is season-scoped; `team_week` can only hold in-season moves.

    A move made after a championship belongs to the next season's OFFSEASON,
    which has no week to sit in — so it counts in `team_year` and in no week at
    all. Every team-season where the two differ must therefore hold enough
    offseason moves to account for the gap. Anything else is a defect.

    'Number of transactions' counts trades as well as adds/drops (a trade
    credits both it and 'Number of trades'), so the explanation has to be
    looked for in `trades.csv` as well as `transactions.csv` — reading only the
    latter reports a season whose offseason was all trades as unexplained.
    """
    if not _HAVE or not (_EXPORTS / "team_year.csv").exists():
        return _skip("no exports/")
    from collections import defaultdict
    weeks = defaultdict(int)
    played = set()
    for r in _rows("team_week.csv"):
        played.add(int(r["Year"]))
        v = _num(r.get("Number of transactions"))
        if v is not None:
            weeks[(r["Team"], int(r["Year"]))] += int(v)
    offseason = defaultdict(list)
    every = defaultdict(list)
    for sheet in ("transactions.csv", "trades.csv"):
        for r in _rows(sheet):
            season = int(r["Season"])
            when = date.fromisoformat(str(r["Date"])[:10])
            every[(r["Team"], season)].append((sheet, str(when)))
            if when < lotg._nfl_kickoff_thursday(season):
                offseason[(r["Team"], season)].append((sheet, str(when)))
    checked = differed = 0
    for r in _rows("team_year.csv"):
        v = _num(r.get("Number of transactions"))
        if v is None:
            continue
        key = (r["Team"], int(r["Year"]))
        checked += 1
        if int(key[1]) not in played:
            # A season with no played weeks has no week for ANY of its moves, so
            # its season total is knowable exactly rather than as a bound.
            assert int(v) == len(every[key]), (
                key, int(v), len(every[key]), "unplayed season disagrees with its own moves")
            if int(v):
                differed += 1
            continue
        if int(v) == weeks[key]:
            continue
        differed += 1
        assert int(v) > weeks[key], (key, weeks[key], int(v), "season total below the weeks")
        assert offseason[key], (key, weeks[key], int(v),
                                "differs but has no offseason move to explain it")
        assert int(v) - weeks[key] <= len(offseason[key]), (
            key, weeks[key], int(v), len(offseason[key]),
            "differs by more than its offseason moves can account for")
    assert checked > 40, checked
    assert differed, "no team-season differs — the guard would be vacuous"


def test_league_year_ties_to_the_team_year_rows_it_rolls_up():
    if not _HAVE or not (_EXPORTS / "league_year.csv").exists():
        return _skip("no exports/")
    from collections import defaultdict
    per = defaultdict(int)
    for r in _rows("team_year.csv"):
        v = _num(r.get("Number of transactions"))
        if v is not None:
            per[int(r["Year"])] += int(v)
    seen = 0
    for r in _rows("league_year.csv"):
        v = _num(r.get("Number of transactions"))
        if v is None:
            continue
        seen += 1
        assert int(v) == per[int(r["Year"])], (r["Year"], int(v), per[int(r["Year"])])
    assert seen, "no league_year rows checked"


def test_the_all_time_sheets_roll_up_the_same_team_year_rows():
    """`league_all_time` and `team_all_time` must roll up the same seasons.

    Both are all-time totals of the same activity, so they have to agree with
    each other and with `team_year`. `league_all_time` used to sum `team_week`,
    which drops offseason moves AND the whole in-progress season (it has no
    played weeks), leaving it short of `team_all_time` by that season's total.
    """
    if not _HAVE or not (_EXPORTS / "league_all_time.csv").exists():
        return _skip("no exports/")
    # The sheets carry "Offseason / Inseason / Total trades", not a bare
    # "Number of trades" — that one is internal and never rendered, so there is
    # nothing to reconcile here. test_season_window covers the trade split.
    ty_tx = 0
    ty_faab = 0.0
    for r in _rows("team_year.csv"):
        ty_tx += int(_num(r.get("Number of transactions")) or 0)
        ty_faab += _num(r.get("Amount of FAAB spent")) or 0.0
    assert ty_tx, "no team_year transactions — the guard would be vacuous"
    la = _rows("league_all_time.csv")
    assert len(la) == 1, len(la)
    assert int(_num(la[0].get("Number of transactions")) or 0) == ty_tx, (
        int(_num(la[0].get("Number of transactions")) or 0), ty_tx)
    assert abs((_num(la[0].get("Amount of FAAB spent")) or 0.0) - ty_faab) < 0.51, (
        la[0].get("Amount of FAAB spent"), ty_faab)
    if not (_EXPORTS / "team_all_time.csv").exists():
        return
    # team_all_time tops itself up from any season that produced no team_year
    # row at all; while every season has one, the two must land on the number.
    ty_years = {int(r["Year"]) for r in _rows("team_year.csv")}
    detail_years = {int(r["Season"]) for sheet in ("transactions.csv", "trades.csv")
                    for r in _rows(sheet)}
    if not detail_years <= ty_years:
        return _skip(f"seasons with no team_year row: {sorted(detail_years - ty_years)}")
    ta_tx = sum(int(_num(r.get("Number of transactions")) or 0)
                for r in _rows("team_all_time.csv"))
    assert ta_tx == ty_tx, (ta_tx, ty_tx)


def test_a_post_championship_move_is_in_no_week_of_the_season_it_left():
    """The concrete case, named so a regression does not read as arithmetic.

    A transaction dated after its league season's championship must not be
    counted in that season's week 17 — it is the next season's offseason.
    """
    if not _HAVE:
        return _skip("no exports/")
    from collections import defaultdict
    # rows whose Season is NOT the calendar year they fall in, forward direction
    forward = [r for r in _rows("transactions.csv")
               if int(r["Season"]) == date.fromisoformat(str(r["Date"])[:10]).year + 1]
    assert forward, "no post-championship moves found — guard would be vacuous"
    for r in forward:
        prev = int(r["Season"]) - 1
        end = _ENDS.get(prev)
        assert end is not None and date.fromisoformat(str(r["Date"])[:10]) > end, (
            r["Team"], r["Date"], r["Season"], f"not actually past {prev}'s final")


if __name__ == "__main__":
    for fn in (
        test_the_season_is_the_first_championship_not_yet_played,
        test_a_december_championship_pushes_the_rest_of_december_forward,
        test_past_every_known_championship_it_falls_forward_not_back,
        test_it_reads_the_league_clock_not_utc,
        test_a_naive_timestamp_is_read_as_utc_not_rejected,
        test_no_timestamp_falls_back_rather_than_guessing,
        test_every_dated_move_agrees_with_its_own_date,
        test_every_year_mismatch_straddles_a_championship,
        test_player_year_transaction_counts_follow_the_same_seasons,
        test_the_trade_split_still_reconciles,
        test_team_year_equals_the_weeks_except_where_a_move_has_no_week,
        test_league_year_ties_to_the_team_year_rows_it_rolls_up,
        test_the_all_time_sheets_roll_up_the_same_team_year_rows,
        test_a_post_championship_move_is_in_no_week_of_the_season_it_left,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all move-season checks passed")
