"""How many different players a team (or the league) started / rostered.

`Number of players started` = distinct Player IDs with at least one starter
row in player_week over the period; `Number of players rostered` = distinct
Player IDs with any row (starter or bench). Year and all-time sheets only.

The total is counted from Player ID alone, never by adding the
`Number of QB/WR/RB/TE started` columns: a player who shows up under two
positions would count once in each position column, but he is one player, so
he counts once here. A player whose position is missing counts here too.

A period with no player_week rows gets no row, so the caller's left merge
leaves it to its own fill rule.
"""
from __future__ import annotations

from typing import Sequence

import pandas as pd

STARTED = "Number of players started"
ROSTERED = "Number of players rostered"
COLUMNS = [STARTED, ROSTERED]


def unique_player_counts(pw: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """One row per `keys` group (keys=[] → one row for everything) with the
    distinct started / rostered player counts."""
    keys = list(keys)
    need = keys + ["Player ID", "Starter/Bench"]
    if pw.empty or not set(need).issubset(pw.columns):
        return pd.DataFrame(columns=keys + COLUMNS)
    df = pw[need].dropna(subset=keys + ["Player ID"]).copy()
    if df.empty:
        return pd.DataFrame(columns=keys + COLUMNS)
    df["Player ID"] = df["Player ID"].astype(str)
    df["_k"] = 0
    gkeys = keys or ["_k"]
    starter = df["Starter/Bench"].astype(str).str.strip().str.lower().eq("starter")
    rostered = df.groupby(gkeys)["Player ID"].nunique()
    started = df[starter].groupby(gkeys)["Player ID"].nunique().reindex(rostered.index).fillna(0)
    out = pd.DataFrame({STARTED: started.astype(int), ROSTERED: rostered.astype(int)}).reset_index()
    return out[keys + COLUMNS]
