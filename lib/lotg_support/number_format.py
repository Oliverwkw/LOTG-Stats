"""The workbook's number format per column, shared by the build (`src/lotg.py`,
which applies it to every exported sheet) and the weekly digest (which prints
each number to the same decimal places, so a stat reads the same in the email
as in the spreadsheet)."""
from __future__ import annotations

import re
from typing import Optional

from lotg_support import matchup

# Whole-number columns beyond the "number of " / "weeks " / ... prefixes.
EXTRA_COUNT_PREFIXES = ("healthy weeks ", "healthy bench weeks ", "bench weeks ", "injured weeks ",
                         # the donut / points-threshold counts on the team and
                         # league sheets: "Donuts (roster)", "Players over 30 pts (starters)"
                         "donuts (", "players under ", "players over ",
                         # player_all_time's playoff split start counts
                         "regular-season games started", "playoff games started")


def col_number_format(col: str) -> Optional[str]:
    """Excel number format for a column (Phase 11E): uniform 2 decimals, NO
    thousands commas, on all value/stat/percent columns. Counts, streaks and
    Year/Week/Season stay whole numbers; text/date columns are left General."""
    # A combined-matchup column is formatted like the per-team stat it combines
    # ("Combined efficiency" as a percent, "Combined donuts" as a count).
    _base = matchup.base_column(col)
    if _base:
        return col_number_format(_base)
    n = re.sub(r"\s+", " ", str(col).strip().lower())
    # Identity / labels / dates / pick-number -> leave alone.
    if n in ("year", "week", "season", "number") or "date" in n:
        return None
    # Whole-number columns: counts, aggregates, streaks.
    if (n.startswith("number of ") or n.startswith("times ") or n.startswith("times as ")
            or n.startswith("most number of ") or n.startswith("weeks ")
            or n.startswith(EXTRA_COUNT_PREFIXES)
            or n.endswith("streak") or n == "championships" or n == "upst"
            or "number of teams" in n
            or n.startswith("total weeks as team starter")
            or n.startswith("total weeks on bench")
            or n.startswith("total times highest starter on team")
            or n.startswith("total times lowest starter on team")):
        return "0"
    # Percent columns that are stored 0-100 (NOT fractions) -> show with a "%"
    # literal and no x100. (boom/bust % are computed as *100 in the player sheets;
    # without this the generic "ends in %" rule below applies Excel's percent format
    # and multiplies again, so 9.4 rendered as 940.00%.)
    _tier_words = ("boom", "bust", "lower quartile", "middle 50%", "upper quartile")
    if (n in ("faab premium %",)
            or (n.endswith(" %") and (n.startswith("starter ") or n.startswith("rostered "))
                and any(_w in n for _w in _tier_words))
            or n.startswith("% of starters ")):
        return '0.00"%"'
    # App-style win % columns (lotg_support.gametime): whole percents [per user].
    if n.startswith(("pre-week win %", "difference in pre-week win %", "largest win % overcome",
                     "win % overcome", "avg pre-week win %")):
        return "0%"
    # Percent columns stored 0-1 -> Excel percent (x100).
    if (n.endswith("%") or n.startswith("win % vs ") or "win %" in n or n == "efficiency"
            or "% of points" in n or "% of team points" in n or "% of league points" in n
            or "% of starts" in n
            # team_week comeback shares (lotg_support.gametime.PERCENT_COLUMNS)
            or n.startswith("% of own points scored ") or n.startswith("% of opponent's ")
            or "all-play win" in n
            or n in ("highest win % vs a team", "lowest win % vs a team")):
        return "0.00%"
    # Tanking is a tiny marginal delta — 2 decimals collapse most values to 0.00
    # in the workbook. Show 4 (the CSV already carries 4).
    if n == "tanking":
        return "0.0000"
    # Everything else numeric (PPG, points, PF, PAR, KTC, addition value, Luck,
    # skill, O-Score, …) -> 2 decimals, no commas. (Harmless on text cells.)
    return "0.00"


def decimals(fmt: Optional[str]) -> Optional[int]:
    """Decimal places an Excel number format shows ("0.00" -> 2, "0" -> 0,
    '0.00"%"' -> 2, "0.00%" -> 2); None for General (no format)."""
    if not fmt:
        return None
    m = re.match(r'0(?:\.(0+))?', fmt)
    return len(m.group(1) or "") if m else None
