"""How many different players a team (or the league) started / rostered.

`Number of players started` = distinct Player IDs with at least one starter
row in player_week over the period; `Number of players rostered` = distinct
Player IDs with any row (starter or bench). Year and all-time sheets only.

Rostered also counts every player_additions tenure (`tenure_rows`): a player
added and dropped between two lineup snapshots — picked up Wednesday, cut
Thursday — has no player_week row but was still on the roster that season.
The same rows feed `Number of QB/WR/RB/TE rostered` and `Number of rookies
rostered` (`rostered_counts`). Started is unchanged: a start needs a week.

`% of rostered players started` = started / rostered (N/A with none rostered).

The total is counted from Player ID alone, never by adding the
`Number of QB/WR/RB/TE started` columns: a player who shows up under two
positions would count once in each position column, but he is one player, so
he counts once here. A player whose position is missing counts here too.

A period with no player_week rows gets no row, so the caller's left merge
leaves it to its own fill rule.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, Sequence, Tuple

import pandas as pd

STARTED = "Number of players started"
ROSTERED = "Number of players rostered"
COLUMNS = [STARTED, ROSTERED]
PCT = "% of rostered players started"
POSITIONS = ("QB", "WR", "RB", "TE")
ROOKIES = "Number of rookies rostered"
ROSTERED_COLUMNS = [ROSTERED, *(f"Number of {p} rostered" for p in POSITIONS), ROOKIES]


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


def tenure_rows(pw: pd.DataFrame, tenures: Iterable[Tuple[Any, Any, Any]],
                position_of: Callable[[str], Optional[str]],
                is_rookie: Callable[[str, int], bool]) -> pd.DataFrame:
    """Bench rows for the (team, season, player id) tenures that have no
    player_week row for that team and season, shaped like player_week's
    Team / Year / Player ID / Position / Rookie? / Starter/Bench. Position is
    the player's player_week position where he has one, else `position_of`."""
    cols = ["Team", "Year", "Player ID", "Position", "Rookie?", "Starter/Bench"]
    seen, pos = set(), {}
    if not pw.empty and {"Team", "Year", "Player ID"}.issubset(pw.columns):
        yrs = pd.to_numeric(pw["Year"], errors="coerce")
        seen = {(str(t), int(y), str(p)) for t, y, p in zip(pw["Team"], yrs, pw["Player ID"])
                if pd.notna(y) and pd.notna(p)}
        if "Position" in pw.columns:
            pos = {str(p): v for p, v in zip(pw["Player ID"], pw["Position"]) if pd.notna(p) and pd.notna(v)}
    rows = []
    for team, season, pid in tenures:
        if team is None or pid is None or season is None or pd.isna(season):
            continue
        k = (str(team), int(season), str(pid))
        if k in seen:
            continue
        seen.add(k)
        rows.append({"Team": k[0], "Year": k[1], "Player ID": k[2],
                     "Position": pos.get(k[2]) or position_of(k[2]),
                     "Rookie?": 1 if is_rookie(k[2], k[1]) else 0, "Starter/Bench": "Bench"})
    return pd.DataFrame(rows, columns=cols)


def rostered_counts(rows: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """One row per `keys` group with the distinct-player rostered counts:
    total, per position and rookies. `rows` is player_week plus `tenure_rows`."""
    keys = list(keys)
    if rows.empty or not set(keys + ["Player ID"]).issubset(rows.columns):
        return pd.DataFrame(columns=keys + ROSTERED_COLUMNS)
    df = rows.dropna(subset=keys + ["Player ID"]).copy()
    df["Player ID"] = df["Player ID"].astype(str)
    df["_pos"] = df.get("Position", pd.Series(index=df.index, dtype=object)).astype(str).str.upper().str.strip()
    df["_rookie"] = (pd.to_numeric(df["Rookie?"], errors="coerce").fillna(0).astype(int).eq(1)
                     if "Rookie?" in df.columns else False)
    df["_k"] = 0
    gkeys = keys or ["_k"]
    out = pd.DataFrame({ROSTERED: df.groupby(gkeys)["Player ID"].nunique()})
    for p in POSITIONS:
        out[f"Number of {p} rostered"] = df[df["_pos"] == p].groupby(gkeys)["Player ID"].nunique()
    out[ROOKIES] = df[df["_rookie"]].groupby(gkeys)["Player ID"].nunique()
    out = out.fillna(0).astype(int).reset_index()
    return out[keys + ROSTERED_COLUMNS]


def started_share(started: pd.Series, rostered: pd.Series) -> pd.Series:
    """`% of rostered players started`, 4 places; N/A where none rostered."""
    s = pd.to_numeric(started, errors="coerce")
    r = pd.to_numeric(rostered, errors="coerce")
    return (s / r.where(r > 0)).round(4)
