from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import requests


@dataclass
class ExternalConfig:
    cache_dir: Path
    timeout_seconds: int = 60


def _download(url: str, out: Path, timeout: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    out.write_bytes(r.content)


def load_dynastyprocess_playerids(cfg: ExternalConfig) -> pd.DataFrame:
    # DynastyProcess open-data repo (player id mapping)
    # Main file is db_playerids.csv at repo root (not /files/playerids.csv)
    url = "https://raw.githubusercontent.com/DynastyProcess/data/master/db_playerids.csv"
    path = cfg.cache_dir / "dynastyprocess_db_playerids.csv"
    if not path.exists():
        _download(url, path, cfg.timeout_seconds)
    return pd.read_csv(path)


def load_dynastyprocess_values_players(cfg: ExternalConfig) -> pd.DataFrame:
    # Trade values (players) — at repo root
    url = "https://raw.githubusercontent.com/DynastyProcess/data/master/values-players.csv"
    path = cfg.cache_dir / "dynastyprocess_values_players.csv"
    if not path.exists():
        _download(url, path, cfg.timeout_seconds)
    return pd.read_csv(path)


def load_dynastyprocess_values_picks(cfg: ExternalConfig) -> pd.DataFrame:
    # Trade values (picks) — at repo root
    url = "https://raw.githubusercontent.com/DynastyProcess/data/master/values-picks.csv"
    path = cfg.cache_dir / "dynastyprocess_values_picks.csv"
    if not path.exists():
        _download(url, path, cfg.timeout_seconds)
    return pd.read_csv(path)


def load_nflverse_injuries(cfg: ExternalConfig, season: int) -> pd.DataFrame:
    # nflverse injuries release
    url = f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
    path = cfg.cache_dir / f"nflverse_injuries_{season}.csv"
    if not path.exists():
        _download(url, path, cfg.timeout_seconds)
    return pd.read_csv(path)
