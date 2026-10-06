"""NFL games nflverse struck from its data that this league played anyway.

One so far: the 2022 week 17 Bills at Bengals Monday night game (Jan 2 2023,
Damar Hamlin's cardiac arrest), suspended in the 1st quarter and declared a
no-contest. The NFL voided it, so nflverse dropped it from the schedule, the
weekly stats, the season totals and the snap counts. Sleeper scored the 1st
quarter, and so did the league.

User rule [2026-10-05]: it is a normal game with a short stat pool — "same
thing as if all the players got injured midgame" — and it should be in the
data as such. So:

- the schedule row goes back wherever the schedule is read
  (`restore_struck_games`), so byes, game days and game slots see the game;
- the players' real stat lines from that quarter (Sleeper's stats API —
  `scripts/struck_game_stats.py` writes `data/struck_game_stats.csv` in
  nflverse's `stats_player_week` schema) go back into the weekly stats
  (`add_struck_stat_rows`) and the season totals (`add_struck_season_totals`);
- players who dressed and recorded nothing are marked active in
  `data/game_day_status.csv` (their snaps were voided with the rest).

Snap counts are not rebuilt; the game-day status rows cover what they decide.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
STATS_CSV = _ROOT / "data" / "struck_game_stats.csv"

STRUCK_GAMES = (
    {"game_id": "2022_17_BUF_CIN", "season": 2022, "game_type": "REG", "week": 17,
     "gameday": "2023-01-02", "weekday": "Monday", "gametime": "20:30",
     "away_team": "BUF", "home_team": "CIN"},
)
STRUCK_GAME_IDS = frozenset(g["game_id"] for g in STRUCK_GAMES)


def restore_struck_games(games: pd.DataFrame) -> pd.DataFrame:
    """`games` (the nfldata schedule) with STRUCK_GAMES put back where missing."""
    if games is None or games.empty or not {"season", "week", "home_team", "away_team"}.issubset(games.columns):
        return games
    have = {(int(s), int(w), str(h)) for s, w, h in
            games[["season", "week", "home_team"]].dropna().itertuples(index=False)}
    add = [g for g in STRUCK_GAMES if (g["season"], g["week"], g["home_team"]) not in have]
    if not add:
        return games
    extra = pd.DataFrame([{c: g.get(c) for c in games.columns} for g in add])
    for c in ("season", "week"):
        if c in extra.columns:
            extra[c] = extra[c].astype(games[c].dtype)
    return pd.concat([games, extra], ignore_index=True)


@functools.lru_cache(maxsize=1)
def struck_stat_rows() -> pd.DataFrame:
    """The struck games' stat lines (nflverse weekly schema), or an empty frame."""
    if not STATS_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(STATS_CSV, low_memory=False)


def add_struck_stat_rows(weekly: pd.DataFrame, season: int) -> pd.DataFrame:
    """nflverse weekly stats for `season` with the struck games' rows added —
    only where that game is absent, so a future nflverse that restores it wins."""
    rows = struck_stat_rows()
    if weekly is None or rows.empty:
        return weekly
    rows = rows[rows["season"] == int(season)]
    if rows.empty:
        return weekly
    if "game_id" in weekly.columns:
        rows = rows[~rows["game_id"].isin(set(weekly["game_id"].astype(str)))]
    if rows.empty:
        return weekly
    rows = rows.reindex(columns=weekly.columns)
    # nflverse writes 0 for a stat a player did not record, never NaN — a NaN
    # here poisons every sum it reaches (career totals went to 0, the trade
    # composite blank). Rates/shares stay NaN, as nflverse leaves them.
    for c in rows.columns:
        if c not in _KEYS and c not in _RATES and pd.api.types.is_numeric_dtype(weekly[c]):
            rows[c] = pd.to_numeric(rows[c], errors="coerce").fillna(0)
    return pd.concat([weekly, rows], ignore_index=True)


def add_struck_season_totals(seasonal: Optional[pd.DataFrame], season: int) -> Optional[pd.DataFrame]:
    """nflverse season totals with the struck games' stats added to each player's
    REG and REG+POST rows (a new row when he has none). Numeric columns that are
    counts are summed; rates and shares are left as published."""
    rows = struck_stat_rows()
    if seasonal is None or rows.empty:
        return seasonal
    rows = rows[rows["season"] == int(season)]
    if rows.empty:
        return seasonal
    count_cols = [c for c in rows.columns
                  if c in seasonal.columns and c not in _KEYS and c not in _RATES
                  and pd.api.types.is_numeric_dtype(rows[c])]
    out = seasonal.copy()
    for col in count_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for _, r in rows.iterrows():
        pid = str(r["player_id"])
        for st in ("REG", "REG+POST"):
            m = (out["player_id"].astype(str) == pid) & (out["season_type"].astype(str).str.upper() == st)
            if m.any():
                for col in count_cols:
                    out.loc[m, col] = out.loc[m, col].fillna(0) + (r[col] if pd.notna(r[col]) else 0)
                if "games" in out.columns:
                    out.loc[m, "games"] = pd.to_numeric(out.loc[m, "games"], errors="coerce").fillna(0) + 1
            else:
                new = {c: r[c] for c in rows.columns if c in out.columns}
                new.update(season_type=st)
                if "games" in out.columns:
                    new["games"] = 1
                out = pd.concat([out, pd.DataFrame([new])], ignore_index=True)
    return out


_KEYS = {"player_id", "player_name", "player_display_name", "position", "position_group",
         "headshot_url", "season", "week", "season_type", "game_id", "team", "opponent_team",
         "recent_team", "games"}
_RATES = {"passing_cpoe", "pacr", "racr", "fg_pct",
          "pat_pct", "fg_long", "passing_epa", "rushing_epa", "receiving_epa"}
