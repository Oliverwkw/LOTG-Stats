from __future__ import annotations

from typing import List, Optional
import glob
import os

import numpy as np
import pandas as pd

from .config import AppConfig


def _read_any(path: str, sheet_name: Optional[str]) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name)
    raise ValueError(f"Unsupported file type: {ext}")


def load_games(cfg: AppConfig) -> pd.DataFrame:
    paths: List[str] = []
    for pattern in cfg.inputs.patterns:
        paths.extend(glob.glob(os.path.join(cfg.inputs.data_dir, pattern)))
    if not paths:
        raise FileNotFoundError(
            f"No input files matched in {cfg.inputs.data_dir} with {cfg.inputs.patterns}"
        )

    frames = []
    for path in sorted(paths):
        try:
            df = _read_any(path, cfg.inputs.sheet_name)
            df["__source_file"] = os.path.basename(path)
            frames.append(df)
        except Exception as exc:
            print(f"[WARN] Skipping {path}: {exc}")

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalize_games(raw: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    c = cfg.columns
    needed = [c.date, c.home_team, c.away_team, c.home_score, c.away_score]
    for col in needed:
        if col is None or col not in raw.columns:
            raise KeyError(f"Missing required column in inputs: {col}")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[c.date], errors="coerce"),
            "home_team": raw[c.home_team].astype(str),
            "away_team": raw[c.away_team].astype(str),
            "home_score": pd.to_numeric(raw[c.home_score], errors="coerce")
            .fillna(0)
            .astype(int),
            "away_score": pd.to_numeric(raw[c.away_score], errors="coerce")
            .fillna(0)
            .astype(int),
        }
    )

    if c.season and c.season in raw.columns:
        df["season"] = raw[c.season].astype(str)
    else:
        df["season"] = None

    if c.venue and c.venue in raw.columns:
        df["venue"] = raw[c.venue].astype(str)
    else:
        df["venue"] = None

    if c.player and c.player in raw.columns:
        df["player"] = raw[c.player].astype(str)
    if c.player_team and c.player_team in raw.columns:
        df["player_team"] = raw[c.player_team].astype(str)

    for fld, name in [
        (c.minutes, "minutes"),
        (c.points, "points"),
        (c.rebounds, "rebounds"),
        (c.assists, "assists"),
    ]:
        if fld and fld in raw.columns:
            df[name] = pd.to_numeric(raw[fld], errors="coerce")

    return df


def infer_season(df: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    if df["season"].notna().any() or not cfg.seasons.infer_by_year_boundary:
        return df

    start_month = cfg.seasons.year_start_month
    year = df["date"].dt.year
    season_year = np.where(df["date"].dt.month >= start_month, year, year - 1)
    df["season"] = season_year.astype("Int64").astype(str)
    return df
