"""Filtered stats: digest-only columns that are an existing column with a row filter.

Some records are already in the workbook, just not as their own column — "most
points in a loss" is the `PF` column of `team_week` filtered to `Win?` = False.
Giving each one a real export column would bloat the sheets with a column that
repeats another one; leaving them out means the weekly email never says when
one is broken. So they are listed here instead, and `add_filtered_stats` adds
them to the digest's frames as if they were columns like any other: they get
all-time boards, records, single-week highlights and drop-offs through exactly
the same code as every exported column. They never reach `exports/`.

Each stat is ranked at ONE end only (`end`). The other end is just the base
column's own board over a subset — the lowest PF in a loss is the lowest PF —
so ranking it would report the same game twice.

[per user, 2026-10-13: "a new list of stats like this that can be found by
filtering columns and so don't get their own column, but which should appear in
the weekly email ... as if they are columns like any other"]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd


def _result_is(df: pd.DataFrame, won: bool) -> pd.Series:
    """Rows whose `Win?` reads `won`. Anything else (a tie, an unplayed week's
    blank) is in neither filter."""
    if "Win?" not in df.columns:
        return pd.Series(False, index=df.index)
    s = df["Win?"].astype(str).str.strip().str.lower()
    return s.isin(("true", "1", "1.0") if won else ("false", "0", "0.0"))


@dataclass(frozen=True)
class FilteredStat:
    sheet: str                                   # the sheet it is ranked on
    column: str                                  # its name in the email
    base: str                                    # the column it filters
    keep: Callable[[pd.DataFrame], pd.Series]    # rows that count
    end: str                                     # "high" | "low": the end ranked
    description: str


FILTERED_STATS = (
    FilteredStat("team_week", "PF in a loss", "PF", lambda df: _result_is(df, False),
                 "high", "Most points scored in a losing week."),
    FilteredStat("team_week", "PF in a win", "PF", lambda df: _result_is(df, True),
                 "low", "Fewest points scored in a winning week."),
    FilteredStat("team_week", "Max PF in a loss", "Max PF", lambda df: _result_is(df, False),
                 "high", "Highest optimal-lineup score in a losing week."),
    FilteredStat("team_week", "Max PF in a win", "Max PF", lambda df: _result_is(df, True),
                 "low", "Lowest optimal-lineup score in a winning week."),
    FilteredStat("team_week", "Efficiency in a loss", "Efficiency",
                 lambda df: _result_is(df, False),
                 "high", "Best lineup efficiency (PF / Max PF) in a losing week."),
    FilteredStat("team_week", "Efficiency in a win", "Efficiency",
                 lambda df: _result_is(df, True),
                 "low", "Worst lineup efficiency (PF / Max PF) in a winning week."),
)

_BY_KEY: Dict[tuple, FilteredStat] = {(f.sheet, f.column): f for f in FILTERED_STATS}
_BASE: Dict[str, str] = {f.column: f.base for f in FILTERED_STATS}


def ranked_end(sheet: str, column: str) -> Optional[str]:
    """The one end a filtered stat is ranked at; None for every other column."""
    f = _BY_KEY.get((sheet, column))
    return f.end if f else None


def base_column(column: str) -> Optional[str]:
    """The exported column a filtered stat filters, so the email prints it the
    way the workbook prints that column (Efficiency as a percent); None for
    every other column. Filtered-stat names are unique across sheets."""
    return _BASE.get(column)


def add_filtered_stats(frames: dict) -> List[str]:
    """Add every filtered stat to its sheet in `frames` (in place): the base
    column's value on the rows it keeps, blank elsewhere. Returns the names
    added; a stat whose sheet or base column is missing is skipped."""
    added = []
    for f in FILTERED_STATS:
        df = frames.get(f.sheet)
        if df is None or df.empty or f.base not in df.columns:
            continue
        base = pd.to_numeric(df[f.base], errors="coerce")
        df[f.column] = base.where(f.keep(df).astype(bool))
        added.append(f.column)
    return added
