"""The two bench totals and their season / all-time / league rollups.

Two different questions, two columns [per user, 2026-10-25]:
  * "Bench points"          — every point the team's bench scored that week:
                              the sum of `Points` over its non-starter
                              player_week rows (taxi and IR included, as on
                              "Most bench points?", which flags the week's max).
  * "Points left on bench"  — Max PF − the starters' own points: what a better
                              lineup would have added. The starter total, not
                              PF, so the +5 semifinal home-field bonus (no
                              player's points; Max PF does not carry it) never
                              reads as 5 points fewer left on the bench.

team_week carries both per team; its combined-matchup block adds the two teams
(`lotg_support.matchup`). Everything here sums team_week rows: team_year /
team_all_time / league_week / league_year / league_all_time get the total, and
the year / all-time sheets also the average per team-week ("Avg …", as
"Avg max PF" sits beside "Max PF").
"""
from __future__ import annotations

from typing import List, Sequence

import pandas as pd

BENCH = "Bench points"
LEFT = "Points left on bench"
WEEK_COLUMNS = (BENCH, LEFT)
AVG_OF = {BENCH: "Avg bench points", LEFT: "Avg points left on bench"}
# Sheet order on the year / all-time sheets.
PERIOD_COLUMNS = (BENCH, AVG_OF[BENCH], LEFT, AVG_OF[LEFT])


def bench_points_by_team_week(pw: pd.DataFrame) -> pd.DataFrame:
    """(Year, Week, Team, "Bench points") for every team-week player_week has:
    the non-starters' points summed, 0.0 for a week with no bench rows."""
    keys = ["Year", "Week", "Team"]
    if pw is None or pw.empty or not set(keys + ["Starter/Bench", "Points"]) <= set(pw.columns):
        return pd.DataFrame(columns=keys + [BENCH])
    p = pw[keys].copy()
    p["Year"] = pd.to_numeric(p["Year"], errors="coerce")
    p["Week"] = pd.to_numeric(p["Week"], errors="coerce")
    p["Team"] = p["Team"].astype(str)
    pts = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)
    p[BENCH] = pts.where(pw["Starter/Bench"] != "Starter", 0.0)
    out = p.dropna(subset=["Year", "Week"]).groupby(keys, as_index=False)[BENCH].sum()
    out[BENCH] = out[BENCH].round(2)
    return out


def points_left_on_bench(max_pf, starter_points):
    """Max PF − the starters' points (None when Max PF is missing)."""
    if max_pf is None or starter_points is None:
        return None
    return round(float(max_pf) - float(starter_points), 2)


def rollup(tw: pd.DataFrame, keys: Sequence[str], averages: bool = True) -> pd.DataFrame:
    """team_week's two bench columns summed over `keys` (empty = one all-time
    row), plus the per-team-week averages when `averages`. A group whose rows
    are all blank reads None, not 0."""
    keys = list(keys)
    cols: List[str] = list(PERIOD_COLUMNS) if averages else list(WEEK_COLUMNS)
    if tw is None or tw.empty or not set(keys + list(WEEK_COLUMNS)) <= set(tw.columns):
        return pd.DataFrame(columns=keys + cols)
    f = tw[keys].copy() if keys else pd.DataFrame(index=tw.index)
    for k in keys:
        if k in ("Year", "Week"):
            f[k] = pd.to_numeric(f[k], errors="coerce")
    for c in WEEK_COLUMNS:
        f[c] = pd.to_numeric(tw[c], errors="coerce")
    groups = f.groupby(keys) if keys else [((), f)]
    rows = []
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        row = {k: (int(v) if k in ("Year", "Week") else v) for k, v in zip(keys, key)}
        for c in WEEK_COLUMNS:
            s = g[c].dropna()
            row[c] = round(float(s.sum()), 2) if not s.empty else None
            if averages:
                row[AVG_OF[c]] = round(float(s.mean()), 2) if not s.empty else None
        rows.append(row)
    return pd.DataFrame(rows, columns=keys + cols)
