from __future__ import annotations

import argparse
import os

import pandas as pd

from .compute import (
    build_team_game_table,
    home_away_splits,
    league_standings,
    players_summary,
    vs_team_matrix,
)
from .config import load_config
from .excel import write_workbook
from .io import infer_season, load_games, normalize_games


def main() -> None:
    parser = argparse.ArgumentParser(description="LOTG Stats Workbook Generator")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    raw = load_games(cfg)
    df = normalize_games(raw, cfg)
    df = infer_season(df, cfg)

    team_games = build_team_game_table(df)

    tables = {
        "League_Standings": league_standings(team_games),
        "Team_Game_Log": team_games,
    }

    if cfg.options.include_vs_team:
        tables["Vs_Team"] = vs_team_matrix(team_games)

    if cfg.options.include_home_away_splits:
        tables["Home_Away_Splits"] = home_away_splits(team_games)

    players = players_summary(df)
    if not players.empty and cfg.options.include_players:
        tables["Players"] = players

    cfg_summary = pd.DataFrame(
        {
            "Key": [
                "Input Files",
                "Rows (raw)",
                "Rows (normalized)",
                "Seasons (unique)",
            ],
            "Value": [
                len(raw.get("__source_file", pd.Series(dtype=object)).unique())
                if "__source_file" in raw
                else "n/a",
                len(raw),
                len(df),
                ", ".join(sorted(set(df["season"].astype(str))))
                if "season" in df
                else "n/a",
            ],
        }
    )
    tables["Config_Summary"] = cfg_summary

    out_path = os.path.join(cfg.output.dir, cfg.output.file)
    write_workbook(tables, out_path)
    print(f"✅ Wrote {out_path}")


if __name__ == "__main__":
    main()
