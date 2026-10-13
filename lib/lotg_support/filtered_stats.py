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


def _is(df: pd.DataFrame, column: str, value: str) -> pd.Series:
    """Rows whose `column` reads `value` (case-insensitive; "True" for a flag)."""
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.strip().str.lower() == value.lower()


def _team_lost(df: pd.DataFrame, frames: dict) -> pd.Series:
    """player_week rows whose team lost that week: its own `Win?` column, or
    (exports built before it existed) team_week's by (Team, Year, Week)."""
    if "Win?" in df.columns:
        return _result_is(df, False)
    tw = frames.get("team_week")
    keys = ["Team", "Year", "Week"]
    if tw is None or tw.empty or any(k not in df.columns or k not in tw.columns for k in keys):
        return pd.Series(False, index=df.index)
    lost = tw.loc[_result_is(tw, False), keys].drop_duplicates()
    lost = set(map(tuple, lost.astype(str).values))
    return pd.Series([tuple(r) in lost for r in df[keys].astype(str).values], index=df.index)


@dataclass(frozen=True)
class FilteredStat:
    sheet: str                                   # the sheet it is ranked on
    column: str                                  # its name in the email
    base: str                                    # the column it filters
    keep: Callable[[pd.DataFrame, dict], pd.Series]   # rows that count (sheet, all frames)
    end: str                                     # "high" | "low": the end ranked
    description: str


def _team(column, base, won, end, description):
    return FilteredStat("team_week", column, base, lambda df, fr: _result_is(df, won),
                        end, description)


_POSITIONS = ("QB", "RB", "WR", "TE")


def _player_week_stats():
    """Points by role and position. Position is Sleeper's current one (the
    playbook's position-drift trap applies)."""
    starter = lambda df: _is(df, "Starter/Bench", "Starter")      # noqa: E731
    bench = lambda df: _is(df, "Starter/Bench", "Bench")          # noqa: E731
    out = [
        FilteredStat("player_week", "Points as starter", "Points",
                     lambda df, fr: starter(df), "high", "Most points by a starter."),
        FilteredStat("player_week", "Points on bench", "Points",
                     lambda df, fr: bench(df), "high", "Most points left on a bench."),
    ]
    for pos in _POSITIONS:
        out += [
            FilteredStat("player_week", f"{pos} points", "Points",
                         lambda df, fr, pos=pos: _is(df, "Position", pos),
                         "high", f"Most points by a {pos}, started or not."),
            FilteredStat("player_week", f"{pos} points as starter", "Points",
                         lambda df, fr, pos=pos: starter(df) & _is(df, "Position", pos),
                         "high", f"Most points by a starting {pos}."),
            FilteredStat("player_week", f"{pos} points on bench", "Points",
                         lambda df, fr, pos=pos: bench(df) & _is(df, "Position", pos),
                         "high", f"Most points by a benched {pos}."),
        ]
    out += [
        FilteredStat("player_week", "Points by a rookie starter", "Points",
                     lambda df, fr: starter(df) & _is(df, "Rookie?", "True"),
                     "high", "Most points by a starting rookie."),
        FilteredStat("player_week", "Points by a starter in a loss", "Points",
                     lambda df, fr: starter(df) & _team_lost(df, fr),
                     "high", "Most points by a starter whose team lost."),
        FilteredStat("player_week", "Points on bench in a loss", "Points",
                     lambda df, fr: bench(df) & _team_lost(df, fr),
                     "high", "Most points left on the bench of a team that lost."),
    ]
    return out


FILTERED_STATS = (
    _team("PF in a loss", "PF", False, "high", "Most points scored in a losing week."),
    _team("PF in a win", "PF", True, "low", "Fewest points scored in a winning week."),
    _team("Max PF in a loss", "Max PF", False, "high",
          "Highest optimal-lineup score in a losing week."),
    _team("Max PF in a win", "Max PF", True, "low",
          "Lowest optimal-lineup score in a winning week."),
    _team("Efficiency in a loss", "Efficiency", False, "high",
          "Best lineup efficiency (PF / Max PF) in a losing week."),
    _team("Efficiency in a win", "Efficiency", True, "low",
          "Worst lineup efficiency (PF / Max PF) in a winning week."),
    *(_team(f"Points from {p}s in a loss", f"Points from {p}s", False, "high",
            f"Most points from {p}s in a losing week.") for p in _POSITIONS),
    *(x for proj in ("Sleeper", "Claude", "Enhanced") for x in (
        _team(f"Points above {proj} Projection in a loss", f"Points above {proj} Projection",
              False, "high", f"Most points above the {proj} projection in a losing week."),
        _team(f"Points above {proj} Projection in a win", f"Points above {proj} Projection",
              True, "low", f"Furthest below the {proj} projection in a winning week."))),
    _team("Lineup Boldness in a win", "Lineup Boldness", True, "high",
          "Boldest lineup that won."),
    _team("Lineup Boldness in a loss", "Lineup Boldness", False, "high",
          "Boldest lineup that lost."),
    _team("Players under 10 pts (starters) in a win", "Players under 10 pts (starters)", True,
          "high", "Most starters under 10 points in a winning week."),
    _team("Players over 30 pts (starters) in a loss", "Players over 30 pts (starters)", False,
          "high", "Most 30-point starters in a losing week."),
    _team("Number of rookies started in a win", "Number of rookies started", True, "high",
          "Most rookies started in a winning week."),
    *_player_week_stats(),
    FilteredStat("player_year", "Avg points by a rookie", "Avg points",
                 lambda df, fr: _is(df, "Rookie?", "True"), "high",
                 "Best points per game in a rookie season."),
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
        df[f.column] = base.where(f.keep(df, frames).astype(bool))
        added.append(f.column)
    return added
