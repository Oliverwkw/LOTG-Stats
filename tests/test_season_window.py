"""When a season starts and ends — the in-season / offseason boundary.

The Offseason / Inseason trade split used to anchor on a fixed **Sept 7**, which
is wrong at both ends and by a moving amount:

  * **Kickoff moves.** NFL week 1 is the Thursday after Labor Day, which has
    ranged from Sept 4 (2025) to Sept 10 (2020 and 2026). A fixed Sept 7 read
    everything in the Sept 7-10 gap as in-season, which is what filed the 2020
    startup slot swap — struck the evening before the draft finished — as an
    in-season trade.
  * **And week 1 does not always open on that Thursday.** 2026 opened on
    WEDNESDAY Sept 9 (NE at SEA, 20:20 ET), a day ahead of its computed
    Thursday, so the Thursday anchor reads Sept 9 2026 as offseason while week 1
    is being played. The boundary is now the schedule's own week-1 opener
    (`_season_opener`), with the Thursday as the fallback when the schedule
    cannot say. In 2020-2025 the two are identical, so no shipped row moves.
  * **The far end was missing entirely.** A season ends at its championship, not
    at New Year, so a deal made after the title game counted as in-season until
    the calendar rolled over.

The window is now (week-1 Thursday .. championship Monday), both derived per
season. On the data as it stands only the slot swap actually moves — no other
trade sits in a kickoff gap or after a championship — so the second half is a
guard against a case that has not happened yet rather than a restatement.

The kickoff checks need nothing but `src/lotg.py`. The rest read `exports/` and
skip when it is absent; they need a build carrying this fix.

Run: python tests/test_season_window.py
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

# Real NFL week-1 Thursdays. The spread across these seven seasons is what makes
# a fixed anchor wrong: six days between the earliest and the latest.
_KICKOFFS = {
    2020: date(2020, 9, 10),
    2021: date(2021, 9, 9),
    2022: date(2022, 9, 8),
    2023: date(2023, 9, 7),
    2024: date(2024, 9, 5),
    2025: date(2025, 9, 4),
    2026: date(2026, 9, 10),
}

# The swap, and the two managers in it.
_SWAP_DATE = date(2020, 9, 9)
_SWAP_TEAMS = {"LWebs53", "AceMatthew"}


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _rows(name: str):
    with (_EXPORTS / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(v):
    s = str(v).strip()
    if s in ("", "nan", "None", "N/A"):
        return None
    return float(s)


# --------------------------------------------------------------------------- #
# kickoff (no data needed)
# --------------------------------------------------------------------------- #
def test_kickoff_matches_the_real_nfl_week_one():
    for season, expected in _KICKOFFS.items():
        assert lotg._nfl_kickoff_thursday(season) == expected, season


def test_a_fantasy_week_runs_tuesday_to_monday():
    """The league's week runs Tuesday-Monday: 2026 week 2 begins Tuesday Sept 15,
    the day after week 1's Monday night game, so a Tuesday or Wednesday waiver
    belongs to the week being set up. The build used to count from the Thursday
    kickoff and filed those moves a week early."""
    wk, td = lotg._season_week_of, lotg.timedelta
    assert wk(date(2026, 9, 8), 2026) == 1       # week 1's Tuesday
    assert wk(date(2026, 9, 14), 2026) == 1      # Monday night: still week 1
    assert wk(date(2026, 9, 15), 2026) == 2      # Tuesday: week 2
    assert wk(date(2026, 9, 16), 2026) == 2      # Wednesday waivers: week 2
    assert wk(date(2024, 10, 21), 2024) == 7     # a Monday
    assert wk(date(2024, 10, 22), 2024) == 8     # the Tuesday after it
    assert wk(date(2022, 12, 7), 2022) == 14     # the Wednesday after week 13's MNF
    # The deep-offseason rule is unchanged: week 1 only within 7 days of kickoff.
    assert wk(date(2026, 9, 3), 2026) == 1
    assert wk(date(2026, 9, 2), 2026) == 0
    for season in range(2020, 2027):
        first = lotg._week_tuesday(season, 1)
        assert first.weekday() == 1, (season, first)
        assert first == lotg._nfl_kickoff_thursday(season) - td(days=2), season
        for w in (2, 9, 17):
            start = lotg._week_tuesday(season, w)
            assert wk(start, season) == w, (season, w)
            assert wk(start - td(days=1), season) == w - 1, (season, w)
            assert wk(start + td(days=6), season) == w, (season, w)


def test_the_2020_backfill_counts_weeks_the_same_way():
    """espn_2020.py cannot import lotg, so it keeps its own copy of the week rule."""
    src = (_ROOT / "src" / "espn_2020.py").read_text()
    assert "week1_tuesday = ss - _dt.timedelta(days=2)" in src
    assert "(d - week1_tuesday).days // 7 + 1" in src


def test_kickoff_actually_moves():
    days = {d.day for d in _KICKOFFS.values()}
    assert len(days) > 1, "a fixed anchor would be fine if kickoff never moved"
    assert min(days) <= 5 and max(days) >= 10, sorted(days)


def _schedule_openers():
    """{season: date of the first REG week-1 game}, from whichever copy of
    nflverse's games.csv this checkout has. None when neither exists."""
    for cand in (_ROOT / ".cache" / "nfldata_games.csv",
                 _ROOT / "exports" / "snapshot" / "nfldata_games.csv"):
        if not cand.exists():
            continue
        out = {}
        with cand.open(newline="") as f:
            for r in csv.DictReader(f):
                if r.get("game_type") != "REG" or r.get("week") != "1":
                    continue
                try:
                    season = int(r["season"])
                except (KeyError, TypeError, ValueError):
                    continue
                day = str(r.get("gameday") or "")[:10]
                if len(day) == 10 and (season not in out or day < out[season]):
                    out[season] = day
        return out
    return None


def test_the_opener_lookup_reads_week_one_and_nothing_else():
    """Pure, no schedule needed: week 1 only, and no invented boundary."""
    m = {(2026, 1): "2026-09-09", (2026, 2): "2026-09-17",
         (2025, 1): "2025-09-04T20:20"}
    assert lotg._season_opener(m, 2026) == date(2026, 9, 9)
    assert lotg._season_opener(m, "2026") == date(2026, 9, 9)
    assert lotg._season_opener(m, 2025) == date(2025, 9, 4)   # timestamp tolerated
    # Nothing to say is None, never a guess — the caller keeps the Thursday.
    assert lotg._season_opener(m, 2024) is None
    assert lotg._season_opener({}, 2026) is None
    assert lotg._season_opener(m, None) is None
    assert lotg._season_opener({(2026, 1): "not-a-date"}, 2026) is None


def test_the_opener_only_moves_the_season_that_opened_early():
    """The safety property: 2020-2025 are untouched, 2026 moves by one day.

    If this ever fails for a completed season, the change stopped being
    additive — that season's Offseason/Inseason split would move in the
    shipped sheets."""
    openers = _schedule_openers()
    if not openers:
        return _skip("no nflverse games.csv in this checkout")
    for season in range(2020, 2026):
        if season not in openers:
            continue
        assert date.fromisoformat(openers[season]) == lotg._nfl_kickoff_thursday(season), (
            f"{season} opened {openers[season]}, not its computed Thursday "
            f"{lotg._nfl_kickoff_thursday(season)} — the anchor change is no "
            "longer a no-op for a completed season")
    if 2026 in openers:
        assert date.fromisoformat(openers[2026]) == date(2026, 9, 9)
        assert lotg._nfl_kickoff_thursday(2026) == date(2026, 9, 10)


def test_the_2026_opener_is_the_boundary_the_build_uses():
    """A move made on Sept 9 2026 must not read as offseason.

    Nothing is misfiled today — the one Sept 9 trade was struck 17:23 ET and
    the waivers processed 18:04 ET, all before the 20:20 kickoff — so this
    guards the case rather than restating a correction."""
    openers = _schedule_openers()
    if not openers or 2026 not in openers:
        return _skip("no 2026 schedule in this checkout")
    opener = lotg._season_opener({(2026, 1): openers[2026]}, 2026)
    assert opener == date(2026, 9, 9)
    # The build's rule is `d < kick` -> offseason. Under the Thursday anchor a
    # Sept 9 move is offseason; under the opener it is not.
    assert date(2026, 9, 9) < lotg._nfl_kickoff_thursday(2026)
    assert not (date(2026, 9, 9) < opener)


def test_the_swap_predates_its_seasons_kickoff():
    # The whole point: Sept 9 2020 is before kickoff (Sept 10) but after the old
    # fixed Sept 7 anchor, so the two rules disagree on exactly this trade.
    assert _SWAP_DATE < lotg._nfl_kickoff_thursday(2020)
    assert _SWAP_DATE >= date(2020, 9, 7)


# --------------------------------------------------------------------------- #
# the split as built
# --------------------------------------------------------------------------- #
def test_offseason_plus_inseason_equals_total():
    if not _HAVE:
        return _skip("no exports/")
    for sheet in ("team_year.csv", "league_year.csv"):
        seen = 0
        for r in _rows(sheet):
            off, ins, tot = (_num(r.get("Offseason trades")),
                             _num(r.get("Inseason trades")),
                             _num(r.get("Total trades")))
            if tot is None:
                continue
            assert off is not None, (sheet, r.get("Year"), "Offseason trades is N/A")
            assert ins is not None, (sheet, r.get("Year"), "Inseason trades is N/A")
            assert off + ins == tot, (sheet, r.get("Year"), off, ins, tot)
            seen += 1
        assert seen, sheet


def test_the_first_season_counts_its_offseason_trade():
    # 2020's offseason ROSTER turnover is legitimately N/A (no prior season to
    # diff against), but its offseason TRADE count is not — the slot swap is one,
    # and blanking it broke the identity above.
    if not _HAVE:
        return _skip("no exports/")
    rows = [r for r in _rows("team_year.csv") if str(r.get("Year")) == "2020"]
    assert len(rows) == 8, len(rows)
    got = {r["Team"]: _num(r["Offseason trades"]) for r in rows}
    for team, n in got.items():
        assert n == (1.0 if team in _SWAP_TEAMS else 0.0), (team, n)
    league = [r for r in _rows("league_year.csv") if str(r.get("Year")) == "2020"]
    assert _num(league[0]["Offseason trades"]) == 1.0, league[0]["Offseason trades"]


def test_first_season_roster_turnover_is_still_na():
    # The carve-out must not have swept the turnover columns along with it.
    if not _HAVE:
        return _skip("no exports/")
    for r in _rows("team_year.csv"):
        if str(r.get("Year")) != "2020":
            continue
        for col in ("Offseason starter turnover", "Offseason roster turnover"):
            assert _num(r.get(col)) is None, (r["Team"], col, r.get(col))


def test_no_trade_is_filed_against_the_wrong_side_of_a_boundary():
    # Recompute the split independently from each trade's own date and the
    # season window, and require it to match what the sheets report.
    if not _HAVE or not (_EXPORTS / "trades.csv").exists():
        return _skip("no exports/trades.csv")
    from collections import defaultdict
    finals_week = {2020: 16, 2021: 17, 2022: 17, 2023: 17, 2024: 17, 2025: 17, 2026: 17}
    # The near edge is the schedule's week-1 opener, the Thursday only when the
    # schedule cannot say — the same rule as the build's _season_window. Reading
    # the Thursday alone here filed the 2026-09-09 BROsenzweig/JacobRosenzweig
    # trade (2026 opened Wednesday Sept 9) as offseason and failed run
    # 34873813049 against a build that was right. The far edge still counts
    # from the Thursday: the finals Monday does not move with the opener.
    #
    # COMPLETED seasons only, like every data-dependent guard here. The
    # in-progress season's split depends on which build wrote the exports: the
    # committed ones predating the opener change file that same trade the other
    # way, so asserting 2026 fails on one vintage or the other. The 2026
    # boundary itself is held by test_the_2026_opener_is_the_boundary_the_build_uses.
    openers = _schedule_openers() or {}
    counts = defaultdict(lambda: {"off": set(), "in": set()})
    for r in _rows("trades.csv"):
        season = int(r["Season"])
        if not lotg._season_is_complete(season):
            continue
        when = date.fromisoformat(str(r["Date"])[:10])
        thursday = lotg._nfl_kickoff_thursday(season)
        kick = date.fromisoformat(openers[season]) if season in openers else thursday
        end = thursday + __import__("datetime").timedelta(days=4 + 7 * (finals_week[season] - 1))
        bucket = "off" if (when < kick or when > end) else "in"
        counts[(r["Team"], season)][bucket].add(str(r["Date"]))
    for row in _rows("team_year.csv"):
        key = (row["Team"], int(row["Year"]))
        if not lotg._season_is_complete(key[1]):
            continue
        off, ins = _num(row["Offseason trades"]), _num(row["Inseason trades"])
        if off is None or ins is None:
            continue
        assert off == len(counts[key]["off"]), (key, off, sorted(counts[key]["off"]))
        assert ins == len(counts[key]["in"]), (key, ins, len(counts[key]["in"]))


if __name__ == "__main__":
    for fn in (
        test_kickoff_matches_the_real_nfl_week_one,
        test_kickoff_actually_moves,
        test_the_swap_predates_its_seasons_kickoff,
        test_offseason_plus_inseason_equals_total,
        test_the_first_season_counts_its_offseason_trade,
        test_first_season_roster_turnover_is_still_na,
        test_no_trade_is_filed_against_the_wrong_side_of_a_boundary,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all season-window checks passed")
