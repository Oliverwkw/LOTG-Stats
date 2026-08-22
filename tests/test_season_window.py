"""When a season starts and ends — the in-season / offseason boundary.

The Offseason / Inseason trade split used to anchor on a fixed **Sept 7**, which
is wrong at both ends and by a moving amount:

  * **Kickoff moves.** NFL week 1 is the Thursday after Labor Day, which has
    ranged from Sept 4 (2025) to Sept 10 (2020 and 2026). A fixed Sept 7 read
    everything in the Sept 7-10 gap as in-season, which is what filed the 2020
    startup slot swap — struck the evening before the draft finished — as an
    in-season trade.
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


def test_kickoff_actually_moves():
    days = {d.day for d in _KICKOFFS.values()}
    assert len(days) > 1, "a fixed anchor would be fine if kickoff never moved"
    assert min(days) <= 5 and max(days) >= 10, sorted(days)


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
    counts = defaultdict(lambda: {"off": set(), "in": set()})
    for r in _rows("trades.csv"):
        season = int(r["Season"])
        when = date.fromisoformat(str(r["Date"])[:10])
        kick = lotg._nfl_kickoff_thursday(season)
        end = kick + __import__("datetime").timedelta(days=4 + 7 * (finals_week[season] - 1))
        bucket = "off" if (when < kick or when > end) else "in"
        counts[(r["Team"], season)][bucket].add(str(r["Date"]))
    for row in _rows("team_year.csv"):
        key = (row["Team"], int(row["Year"]))
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
