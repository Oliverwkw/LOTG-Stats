from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import pandas as pd
import requests

@dataclass
class ExternalConfig:
    cache_dir: Path
    timeout_seconds: int = 60

def _download(url: str, out: Path, timeout: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    r = session.get(url, timeout=timeout, proxies={"http": None, "https": None})
    r.raise_for_status()
    out.write_bytes(r.content)


def _download_best_effort(urls: list[str], out: Path, timeout: int) -> None:
    """Try multiple URLs (mirrors/case variants). Raises only if all fail."""
    last_err: Optional[Exception] = None
    for url in urls:
        try:
            _download(url, out, timeout)
            return
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    if last_err is not None:
        raise last_err

def load_dynastyprocess_playerids(cfg: ExternalConfig) -> pd.DataFrame:
    # Official DynastyProcess data repo includes player id mappings (incl sleeper_id)
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/files/playerids.csv",
        "https://raw.githubusercontent.com/DynastyProcess/data/master/files/playerids.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_playerids.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    return pd.read_csv(path)

def load_dynastyprocess_values_players(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values-players.csv",
        "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values-players.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_values_players.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    return pd.read_csv(path)

def load_dynastyprocess_values_picks(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values-picks.csv",
        "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values-picks.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_values_picks.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    return pd.read_csv(path)

def load_nflverse_injuries(cfg: ExternalConfig, season: int) -> pd.DataFrame:
    # nflverse makes weekly injury report data available via its releases; easiest stable source is nflreadr's hosted files.
    # This URL pattern is stable in practice; if it ever changes, update here.
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/injuries/injuries_{season}.csv",
    ]
    path = cfg.cache_dir / f"nflverse_injuries_{season}.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    return pd.read_csv(path)


def load_nflverse_player_ids(cfg: ExternalConfig) -> pd.DataFrame:
    """Load nflverse player_ids mapping (includes sleeper_id and gsis_id)."""
    urls = [
        "https://github.com/nflverse/nflverse-data/releases/download/player_ids/player_ids.csv",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_ids/player_ids.csv",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_ids.csv",
    ]
    path = cfg.cache_dir / "nflverse_player_ids.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    return pd.read_csv(path)

def load_nflverse_games(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://github.com/nflverse/nflverse-data/releases/download/games/games.csv.gz",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/games/games.csv.gz",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/games.csv.gz",
    ]
    path = cfg.cache_dir / "nflverse_games.csv.gz"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.read_csv(path, compression="gzip")

def load_nflverse_snap_counts(cfg: ExternalConfig, season: int) -> pd.DataFrame:
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv.gz",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/snap_counts/snap_counts_{season}.csv",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/snap_counts/snap_counts_{season}.csv.gz",
    ]
    path = cfg.cache_dir / f"nflverse_snap_counts_{season}.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.read_csv(path, compression="gzip")

def load_nflverse_transactions(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://github.com/nflverse/nflverse-data/releases/download/transactions/transactions.csv.gz",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/transactions/transactions.csv.gz",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/transactions.csv.gz",
    ]
    path = cfg.cache_dir / "nflverse_transactions.csv.gz"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.read_csv(path, compression="gzip")

def load_nflverse_stats_player_week(cfg: ExternalConfig, season: int) -> pd.DataFrame:
    """Load nflverse weekly player stats; used for team-by-week and played detection."""
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_{season}.csv.gz",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_stats/stats_player_week_{season}.csv",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_stats/stats_player_week_{season}.csv.gz",
    ]
    path = cfg.cache_dir / f"nflverse_stats_player_week_{season}.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    # handle possible gz without relying on pandas compression inference
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.read_csv(path, compression='gzip')
