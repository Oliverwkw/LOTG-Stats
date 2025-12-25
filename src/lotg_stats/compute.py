from __future__ import annotations

import numpy as np
import pandas as pd


def build_team_game_table(games: pd.DataFrame) -> pd.DataFrame:
    home = games.assign(
        team=games["home_team"],
        opponent=games["away_team"],
        points_for=games["home_score"],
        points_against=games["away_score"],
        is_home=True,
    )
    away = games.assign(
        team=games["away_team"],
        opponent=games["home_team"],
        points_for=games["away_score"],
        points_against=games["home_score"],
        is_home=False,
    )
    team_games = pd.concat([home, away], ignore_index=True)
    team_games["is_win"] = team_games["points_for"] > team_games["points_against"]
    team_games["margin"] = team_games["points_for"] - team_games["points_against"]
    return team_games[
        [
            "season",
            "date",
            "team",
            "opponent",
            "points_for",
            "points_against",
            "margin",
            "is_win",
            "is_home",
        ]
    ].sort_values(["season", "date", "team"])


def league_standings(team_games: pd.DataFrame) -> pd.DataFrame:
    grouped = team_games.groupby(["season", "team"], as_index=False).agg(
        GP=("team", "count"),
        W=("is_win", "sum"),
        L=("is_win", lambda s: (~s).sum()),
        PF=("points_for", "sum"),
        PA=("points_against", "sum"),
        PlusMinus=("margin", "sum"),
    )
    grouped["WinPct"] = (grouped["W"] / grouped["GP"]).round(3).fillna(0.0)
    grouped = grouped.sort_values(
        ["season", "WinPct", "PlusMinus", "PF"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    return grouped


def home_away_splits(team_games: pd.DataFrame) -> pd.DataFrame:
    grouped = team_games.groupby(["season", "team", "is_home"], as_index=False).agg(
        GP=("team", "count"),
        W=("is_win", "sum"),
        L=("is_win", lambda s: (~s).sum()),
        PF=("points_for", "sum"),
        PA=("points_against", "sum"),
        PlusMinus=("margin", "sum"),
    )
    grouped["WinPct"] = (grouped["W"] / grouped["GP"]).round(3).fillna(0.0)
    grouped["Split"] = np.where(grouped["is_home"], "Home", "Away")
    grouped = grouped.drop(columns=["is_home"])
    return grouped[
        ["season", "team", "Split", "GP", "W", "L", "WinPct", "PF", "PA", "PlusMinus"]
    ]


def vs_team_matrix(team_games: pd.DataFrame) -> pd.DataFrame:
    grouped = team_games.groupby(["season", "team", "opponent"], as_index=False).agg(
        GP=("team", "count"),
        W=("is_win", "sum"),
        L=("is_win", lambda s: (~s).sum()),
        PF=("points_for", "sum"),
        PA=("points_against", "sum"),
        PlusMinus=("margin", "sum"),
    )
    grouped["WinPct"] = (grouped["W"] / grouped["GP"]).round(3).fillna(0.0)
    grouped = grouped.sort_values(
        ["season", "team", "WinPct", "GP"],
        ascending=[True, True, False, False],
    )
    grouped = grouped[grouped["team"] != grouped["opponent"]]
    return grouped[
        ["season", "team", "opponent", "GP", "W", "L", "WinPct", "PF", "PA", "PlusMinus"]
    ]


def players_summary(df: pd.DataFrame) -> pd.DataFrame:
    required = {"player", "player_team"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    grouped = df.groupby(["season", "player_team", "player"], as_index=False).agg(
        GP=("player", "count"),
        MIN=("minutes", "sum"),
        PTS=("points", "sum"),
        REB=("rebounds", "sum"),
        AST=("assists", "sum"),
    )
    for col in ["MIN", "PTS", "REB", "AST"]:
        if col in grouped.columns:
            grouped[f"{col}_Avg"] = (grouped[col] / grouped["GP"]).round(2)
    grouped = grouped.sort_values(
        ["season", "player_team", "PTS"], ascending=[True, True, False]
    )
    return grouped
