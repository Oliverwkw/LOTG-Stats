from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import requests


@dataclass
class ExternalConfig:
    cache_dir: Path
    timeout_seconds: int = 60


def _try_download(urls: list[str], out: Path, timeout: int) -> bool:
    """
    Try a list of URLs until one succeeds. Returns True if downloaded.
    """
    out.parent.mkdir(parents=True, exist_ok=True)

    last_err = None
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200 and r.content:
                out.write_bytes(r.content)
                return True
            last_err = f"{r.status_code} for {url}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e} for {url}"

    # Keep failure info in a tiny text file for debugging (doesn't crash build)
    try:
        (out.parent / (out.name + ".error.txt")).write_text(str(last_err))
    except Exception:
        pass
    return False


def _read_csv_or_empty(path: Path) -> pd.DataFrame:
    try:
        if path.exists() and path.stat().st_size > 0:
            return pd.read_csv(path)
    except Exception:
        pass
    return pd.DataFrame()


def load_dynastyprocess_playerids(cfg: ExternalConfig) -> pd.DataFrame:
    """
    DynastyProcess player id mapping.
    This has historically lived at db_playerids.csv, but branches/paths can vary.
    We try several stable patterns and fall back to empty (build continues).
    """
    urls = [
        # raw.githubusercontent.com (master/main)
        "https://raw.githubusercontent.com/dynastyprocess/data/master/db_playerids.csv",
        "https://raw.githubusercontent.com/dynastyprocess/data/main/db_playerids.csv",
        # github.com raw endpoint variants
        "https://github.com/dynastyprocess/data/raw/master/db_playerids.csv",
        "https://github.com/dynastyprocess/data/raw/main/db_playerids.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_db_playerids.csv"
    if not path.exists():
        _try_download(urls, path, cfg.timeout_seconds)
    return _read_csv_or_empty(path)


def load_dynastyprocess_values_players(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/values-players.csv",
        "https://raw.githubusercontent.com/dynastyprocess/data/main/values-players.csv",
        "https://github.com/dynastyprocess/data/raw/master/values-players.csv",
        "https://github.com/dynastyprocess/data/raw/main/values-players.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_values_players.csv"
    if not path.exists():
        _try_download(urls, path, cfg.timeout_seconds)
    return _read_csv_or_empty(path)


def load_dynastyprocess_values_picks(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/values-picks.csv",
        "https://raw.githubusercontent.com/dynastyprocess/data/main/values-picks.csv",
        "https://github.com/dynastyprocess/data/raw/master/values-picks.csv",
        "https://github.com/dynastyprocess/data/raw/main/values-picks.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_values_picks.csv"
    if not path.exists():
        _try_download(urls, path, cfg.timeout_seconds)
    return _read_csv_or_empty(path)


def load_nflverse_injuries(cfg: ExternalConfig, season: int) -> pd.DataFrame:
    """
    nflverse injuries release. If a season file doesn't exist, return empty.
    """
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv",
    ]
    path = cfg.cache_dir / f"nflverse_injuries_{season}.csv"
    if not path.exists():
        _try_download(urls, path, cfg.timeout_seconds)
    return _read_csv_or_empty(path)
