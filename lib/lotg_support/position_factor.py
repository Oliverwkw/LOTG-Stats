"""The per-season position factor every "adjusted by position" number uses.

    factor(season, position) = league starter avg / position starter avg

both over that season's STARTED player_week rows. Each season stands on its own
baseline — pooling seasons let one scoring era shift another's numbers — with
one exception: a season that has played fewer than `MIN_WEEKS` weeks (the season
in progress, weeks 1-4, and any move filed under it before kickoff) borrows the
previous season's baseline (user rule 2026-09-26). Every build recomputes, so the
switch to its own baseline at week 5 is retroactive. A season past every one on
record (a move filed under a season that has not kicked off) uses the latest.

`MIN_WEEKS` equals `digest.MIN_YEARLY_WEEK`, the week the email starts showing a
season's averages, so the numbers settle the week they are first reported
(tests/test_position_factor.py keeps the two in step).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

MIN_WEEKS = 5

Baselines = Tuple[Dict[int, float], Dict[int, Dict[str, float]], Dict[int, int]]


def season_baselines(starters: pd.DataFrame, min_weeks: int = MIN_WEEKS) -> Baselines:
    """({season: league starter avg}, {season: {POS: starter avg}},
    {season: the season whose baseline it uses}) from STARTED player_week rows
    (columns Year, Week, Position, Points)."""
    league: Dict[int, float] = {}
    by_pos: Dict[int, Dict[str, float]] = {}
    source: Dict[int, int] = {}
    if starters is None or starters.empty:
        return league, by_pos, source
    df = starters.assign(
        _Y=pd.to_numeric(starters["Year"], errors="coerce"),
        _W=pd.to_numeric(starters["Week"], errors="coerce"),
        _P=pd.to_numeric(starters["Points"], errors="coerce"),
        _POS=starters["Position"].astype(str).str.upper(),
    ).dropna(subset=["_Y"])
    weeks = df.groupby("_Y")["_W"].nunique()
    for yr, g in df.groupby("_Y"):
        y = int(yr)
        league[y] = float(g["_P"].mean() or 0.0)
        by_pos[y] = {str(p): float(gg["_P"].mean() or 0.0) for p, gg in g.groupby("_POS")}
        source[y] = y
    for y in sorted(league):
        if int(weeks.get(y, 0)) < min_weeks and (y - 1) in league:
            # (y - 1) is already resolved, so a chain of short seasons resolves too.
            league[y] = league[y - 1]
            by_pos[y] = dict(by_pos[y - 1])
            source[y] = source[y - 1]
    return league, by_pos, source


def factor(baselines: Baselines, season: Any, pos: Optional[str]) -> float:
    """The position factor for `season` (1.0 without a baseline for it or the
    position)."""
    league, by_pos, _src = baselines
    try:
        y = int(season)
    except (TypeError, ValueError):
        return 1.0
    if league and y not in league and y > max(league):
        y = max(league)
    la = league.get(y, 0.0)
    pa = (by_pos.get(y) or {}).get(str(pos or "").upper(), 0.0)
    return (la / pa) if (la and pa) else 1.0
