from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import yaml


@dataclass
class InputConfig:
    data_dir: str
    patterns: list[str]
    sheet_name: Optional[str]


@dataclass
class ColumnMap:
    date: str
    season: Optional[str]
    home_team: str
    away_team: str
    home_score: str
    away_score: str
    team: Optional[str]
    opponent: Optional[str]
    venue: Optional[str]
    player: Optional[str]
    player_team: Optional[str]
    minutes: Optional[str]
    points: Optional[str]
    rebounds: Optional[str]
    assists: Optional[str]


@dataclass
class SeasonCfg:
    infer_by_year_boundary: bool
    year_start_month: int


@dataclass
class OutputCfg:
    dir: str
    file: str


@dataclass
class OptionsCfg:
    include_players: bool
    include_vs_team: bool
    include_home_away_splits: bool


@dataclass
class AppConfig:
    inputs: InputConfig
    columns: ColumnMap
    seasons: SeasonCfg
    output: OutputCfg
    options: OptionsCfg


def _get(d: Dict[str, Any], key: str, default=None):
    return d.get(key, default)


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    inputs = cfg.get("inputs", {})
    cols = cfg.get("columns", {})
    seasons = cfg.get("seasons", {})
    output = cfg.get("output", {})
    options = cfg.get("options", {})

    return AppConfig(
        inputs=InputConfig(
            data_dir=inputs.get("data_dir", "./data"),
            patterns=inputs.get("patterns", ["*.csv"]),
            sheet_name=inputs.get("sheet_name"),
        ),
        columns=ColumnMap(
            date=cols.get("date", "Date"),
            season=cols.get("season"),
            home_team=cols.get("home_team", "HomeTeam"),
            away_team=cols.get("away_team", "AwayTeam"),
            home_score=cols.get("home_score", "HomeScore"),
            away_score=cols.get("away_score", "AwayScore"),
            team=cols.get("team"),
            opponent=cols.get("opponent"),
            venue=cols.get("venue"),
            player=cols.get("player"),
            player_team=cols.get("player_team"),
            minutes=cols.get("minutes"),
            points=cols.get("points"),
            rebounds=cols.get("rebounds"),
            assists=cols.get("assists"),
        ),
        seasons=SeasonCfg(
            infer_by_year_boundary=seasons.get("infer_by_year_boundary", True),
            year_start_month=seasons.get("year_start_month", 1),
        ),
        output=OutputCfg(
            dir=output.get("dir", "./LOTG_outputs"),
            file=output.get("file", "LOTG_Stats.xlsx"),
        ),
        options=OptionsCfg(
            include_players=options.get("include_players", True),
            include_vs_team=options.get("include_vs_team", True),
            include_home_away_splits=options.get("include_home_away_splits", True),
        ),
    )
