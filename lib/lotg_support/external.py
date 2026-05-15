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

    # Try direct first, then allow env-proxy settings if direct egress is blocked.
    last_err: Optional[Exception] = None
    for trust_env in (False, True):
        try:
            session = requests.Session()
            session.trust_env = trust_env
            kwargs = {"timeout": timeout}
            if not trust_env:
                kwargs["proxies"] = {"http": None, "https": None}
            r = session.get(url, **kwargs)
            r.raise_for_status()
            out.write_bytes(r.content)
            return
        except Exception as e:
            last_err = e
            continue

    if last_err is not None:
        raise last_err


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
    # Official DynastyProcess data repo includes player id mappings (incl sleeper_id).
    # File was renamed from playerids.csv to db_playerids.csv; keep legacy as fallback.
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv",
        "https://raw.githubusercontent.com/DynastyProcess/data/master/files/db_playerids.csv",
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
    """Load nflverse player metadata (rookie_season, birth_date, position, etc.).

    Note: the nflverse 'player_ids' release was renamed to 'players' and the new
    'players.csv' does NOT carry sleeper_id. The sleeper_id<->gsis_id mapping is
    sourced from DynastyProcess (load_dynastyprocess_playerids) and from Sleeper's
    own /players/nfl feed (which already exposes gsis_id per player).
    """
    urls = [
        "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv",
        "https://github.com/nflverse/nflverse-data/releases/download/player_ids/player_ids.csv",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_ids/player_ids.csv",
        "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_ids.csv",
    ]
    path = cfg.cache_dir / "nflverse_player_ids.csv"
    if (not path.exists()) or path.stat().st_size == 0:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    return pd.read_csv(path)

def load_nflverse_stats_player_week(cfg: ExternalConfig, season: int) -> pd.DataFrame:
    """Load nflverse weekly player stats; used for team-by-week and played detection.

    nflverse maintains two release tags carrying the same per-week stats file:
    'player_stats' (legacy, older seasons) and 'stats_player' (newer seasons,
    e.g. 2025+). We try both so historical and current seasons both resolve.
    """
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv.gz",
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
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.read_csv(path, compression='gzip', low_memory=False)
