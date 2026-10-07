"""team_week's combined-matchup block: one game's two teams, taken together.

Each column pairs a team_week row with its opponent's row of the same (Year,
Week) and combines one per-team stat across the two. The value is written ONCE
per game, in the WINNER's row; the loser's row holds the text `WINNER_TEXT`,
which the workbook turns into a link to the winner's cell (so a sort or a board
over the column counts each game once, and the loser row still points at it).

How each stat combines (`COMBINED_COLUMNS`):
  * "sum"   — the two teams' values added (points, counts, hardship).
  * "mean"  — the average of the two teams' own values (efficiency, boom/bust
              %): each team is judged against its OWN lineup, then averaged.
  * "bench" — combined Max PF − combined PF (points left on both benches).
  * "per_started" — combined position points ÷ combined starters at that
              position (pooled over the game's starters, so the count behind
              the points is taken out; `POSITIONS` pairs the two columns).

PF carries the league's +5 semifinal home-field bonus and so does everything
built on it here (combined points, and — since Max PF does not carry it —
combined bench points reads 5 lower in a bonus game). By design, per user.

The winner is the row whose `Win?` is true against an opponent's false — the
sheet's own result, so the 2026+ two-week final follows its combined-round
result. If `Win?` does not separate the two (a tie), the higher PF wins; an
exact tie on PF puts the value in BOTH rows.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

WINNER_TEXT = "winner"

# team_week's positional starter split: (position, points column, starters
# column). Shared by the combined per-starter columns and the league sheets'
# "Points per X started" (`points_per_started`).
POSITIONS: Tuple[Tuple[str, str, str], ...] = (
    ("QB", "Points from QBs", "Number of QB started"),
    ("WR", "Points from WRs", "Number of WR started"),
    ("RB", "Points from RBs", "Number of RB started"),
    ("TE", "Points from TEs", "Number of TE started"),
)
_STARTERS_OF: Dict[str, str] = {pts: n for _p, pts, n in POSITIONS}

# (column, team_week base column, how). Order is the sheet order.
COMBINED_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("Combined points", "PF", "sum"),
    ("Combined Max PF", "Max PF", "sum"),
    ("Combined efficiency", "Efficiency", "mean"),
    ("Combined bench points", "Max PF", "bench"),
    ("Combined points from QBs", "Points from QBs", "sum"),
    ("Combined points from WRs", "Points from WRs", "sum"),
    ("Combined points from RBs", "Points from RBs", "sum"),
    ("Combined points from TEs", "Points from TEs", "sum"),
    ("Combined QBs started", "Number of QB started", "sum"),
    ("Combined WRs started", "Number of WR started", "sum"),
    ("Combined RBs started", "Number of RB started", "sum"),
    ("Combined TEs started", "Number of TE started", "sum"),
    ("Combined points per QB started", "Points from QBs", "per_started"),
    ("Combined points per WR started", "Points from WRs", "per_started"),
    ("Combined points per RB started", "Points from RBs", "per_started"),
    ("Combined points per TE started", "Points from TEs", "per_started"),
    ("Combined donuts (starters)", "Donuts (starters)", "sum"),
    ("Combined players under 10 pts (starters)", "Players under 10 pts (starters)", "sum"),
    ("Combined players over 20 pts (starters)", "Players over 20 pts (starters)", "sum"),
    ("Combined players over 30 pts (starters)", "Players over 30 pts (starters)", "sum"),
    ("Combined players over 40 pts (starters)", "Players over 40 pts (starters)", "sum"),
    ("Combined players over 50 pts (starters)", "Players over 50 pts (starters)", "sum"),
    ("Combined % of starters boom", "% of starters boom", "mean"),
    ("Combined % of starters bust", "% of starters bust", "mean"),
    ("Combined starter injuries", "Number of starter injuries", "sum"),
    ("Combined players on bye", "Number of players on bye", "sum"),
    ("Combined starter-adjusted Hardship", "Starter-adjusted Hardship", "sum"),
    ("Combined rookies started", "Number of rookies started", "sum"),
    ("Combined starter turnover from previous week", "Starter turnover from previous week", "sum"),
    # the three projections and points above them [per user, 2026-10-07]
    ("Combined Sleeper Projection", "Sleeper Projection", "sum"),
    ("Combined Points above Sleeper Projection", "Points above Sleeper Projection", "sum"),
    ("Combined Claude Projection", "Claude Projection", "sum"),
    ("Combined Points above Claude Projection", "Points above Claude Projection", "sum"),
    ("Combined Enhanced Projection", "Enhanced Projection", "sum"),
    ("Combined Points above Enhanced Projection", "Points above Enhanced Projection", "sum"),
)

COMBINED_NAMES: Tuple[str, ...] = tuple(c for c, _, _ in COMBINED_COLUMNS)
_BASE_OF: Dict[str, str] = {c: b for c, b, _ in COMBINED_COLUMNS}


def base_column(col: str) -> Optional[str]:
    """The per-team team_week column a combined column is built from (its
    number format and meaning follow it), or None for any other column."""
    return _BASE_OF.get(str(col).strip())


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _truthy(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "1.0", "yes"):
        return True
    if s in ("false", "0", "0.0", "no"):
        return False
    return None


def _whole_number_column(base: Optional[pd.Series]) -> bool:
    if base is None:
        return False
    vals = pd.to_numeric(base, errors="coerce").dropna()
    return not vals.empty and bool(vals.mod(1).eq(0).all())


def _render(value: float, whole: bool) -> object:
    """Whole numbers stay ints on a whole-number base column, so '3' not '3.0';
    everything else is rounded to the 4 decimals the export carries."""
    if whole and float(value).is_integer():
        return int(value)
    return round(float(value), 4)


def winner_side(row: dict, opp: dict) -> str:
    """"self" / "opp" / "both": whose row carries the combined value."""
    w, ow = _truthy(row.get("Win?")), _truthy(opp.get("Win?"))
    if w is True and ow is False:
        return "self"
    if w is False and ow is True:
        return "opp"
    pf, opf = _num(row.get("PF")), _num(opp.get("PF"))
    if pf is not None and opf is not None and pf != opf:
        return "self" if pf > opf else "opp"
    return "both"


def combine(a: dict, b: dict, base: str, how: str) -> Optional[float]:
    """One game's combined value from the two rows (None if either side lacks it)."""
    if how == "bench":
        m1, m2 = _num(a.get("Max PF")), _num(b.get("Max PF"))
        p1, p2 = _num(a.get("PF")), _num(b.get("PF"))
        if None in (m1, m2, p1, p2):
            return None
        return (m1 + m2) - (p1 + p2)
    x, y = _num(a.get(base)), _num(b.get(base))
    if x is None or y is None:
        return None
    if how == "per_started":
        n = _STARTERS_OF[base]
        na, nb = _num(a.get(n)), _num(b.get(n))
        if na is None or nb is None or na + nb <= 0:
            return None
        return (x + y) / (na + nb)
    return (x + y) / 2.0 if how == "mean" else x + y


def add_combined_columns(tw: pd.DataFrame) -> pd.DataFrame:
    """A copy of team_week with the `COMBINED_COLUMNS` block appended.

    Rows with no opponent row that week, or a game missing the base stat on
    either side, get a blank. The winner's row holds the number; the loser's
    holds `WINNER_TEXT`."""
    if tw is None or tw.empty or not {"Team", "Opponent", "Year", "Week"} <= set(tw.columns):
        return tw
    out = tw.copy()
    records = out.to_dict("records")
    idx_of: Dict[Tuple[str, int, int], int] = {}
    keys: List[Optional[Tuple[str, int, int]]] = []
    for i, r in enumerate(records):
        y, w = _num(r.get("Year")), _num(r.get("Week"))
        if y is None or w is None:
            keys.append(None)
            continue
        k = (str(r.get("Team")).strip(), int(y), int(w))
        keys.append(k)
        idx_of[k] = i
    cols: Dict[str, List[object]] = {c: [None] * len(records) for c in COMBINED_NAMES}
    whole = {name: how == "sum" and _whole_number_column(out.get(base))
             for name, base, how in COMBINED_COLUMNS}
    for i, r in enumerate(records):
        k = keys[i]
        opp_name = str(r.get("Opponent") or "").strip()
        if k is None or not opp_name or opp_name.lower() in ("nan", "n/a"):
            continue
        j = idx_of.get((opp_name, k[1], k[2]))
        if j is None or j == i:
            continue
        o = records[j]
        side = winner_side(r, o)
        for name, base, how in COMBINED_COLUMNS:
            v = combine(r, o, base, how)
            if v is None:
                continue  # blank on both rows: no winner cell to point at
            cols[name][i] = WINNER_TEXT if side == "opp" else _render(v, whole[name])
    for name in COMBINED_NAMES:
        out[name] = pd.Series(cols[name], index=out.index, dtype=object)
    return out


def points_per_started(frame: pd.DataFrame) -> Dict[str, Optional[float]]:
    """League "Points per X started" over a set of team_week rows (a week, a
    season, all time): the position's total starter points ÷ its total
    player-starts. Summed from the WEEKLY starts, not the league year / all-time
    "Number of X started" columns, which count distinct players. None when the
    position has no starts in the frame."""
    out: Dict[str, Optional[float]] = {}
    for pos, pts_col, n_col in POSITIONS:
        name = f"Points per {pos} started"
        if frame is None or frame.empty or pts_col not in frame.columns or n_col not in frame.columns:
            out[name] = None
            continue
        pts = pd.to_numeric(frame[pts_col], errors="coerce").fillna(0.0).sum()
        n = pd.to_numeric(frame[n_col], errors="coerce").fillna(0.0).sum()
        out[name] = round(float(pts) / float(n), 4) if n > 0 else None
    return out


LEAGUE_PER_STARTED_COLUMNS: Tuple[str, ...] = tuple(f"Points per {p} started" for p, _a, _b in POSITIONS)
