from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

import pandas as pd

from .utils import HttpConfig, fetch_json
from .sleeper import SleeperClient
from .external import ExternalConfig, load_dynastyprocess_playerids, load_nflverse_injuries

SLEEPER_BASE = "https://api.sleeper.app/v1"


def _safe_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(obj, indent=2))
    except Exception:
        path.write_text(json.dumps(str(obj)))


def _safe_write_df(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_csv(path, index=False)
    except Exception:
        path.write_text("")


def _download_stats_week(cfg: HttpConfig, season: int, week: int) -> List[Dict[str, Any]]:
    """Sleeper weekly NFL stats endpoint (fallback for player-week points)."""
    url = f"{SLEEPER_BASE}/stats/nfl/regular/{season}/{week}"
    try:
        data = fetch_json(url, cfg)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def snapshot_all(
    repo_root: Path,
    league_id: str,
    min_season: Optional[int],
    max_season: Optional[int],
) -> Path:
    """
    Step 1: Create an organized snapshot of Sleeper + external data.

    Output folder: exports/snapshot/

    The build step should be able to run using ONLY these files (plus plan/catalog/config).
    """
    snapshot_dir = repo_root / "exports" / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    http = HttpConfig(timeout_seconds=30, max_retries=10, backoff_base_seconds=0.7)
    sc = SleeperClient(league_id, http)

    cache_dir = repo_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    ext = ExternalConfig(cache_dir=cache_dir, timeout_seconds=120)

    # Sleeper NFL players (giant dictionary)
    try:
        players_nfl = sc.players_nfl()
    except Exception:
        players_nfl = {}
    _safe_write_json(snapshot_dir / "sleeper_players_nfl.json", players_nfl)

    # DynastyProcess ids (for gsis_id joins)
    try:
        dp_ids = load_dynastyprocess_playerids(ext)
    except Exception:
        dp_ids = pd.DataFrame()
    _safe_write_df(snapshot_dir / "dynastyprocess_playerids.csv", dp_ids)

    # League chain
    chain: List[Dict[str, Any]] = []
    lid = str(league_id)
    seen = set()

    while lid and lid not in seen:
        seen.add(lid)
        try:
            lg = sc.league(lid)
        except Exception:
            break
        if not isinstance(lg, dict):
            break

        season = int(lg.get("season") or 0)
        if min_season is not None and season < int(min_season):
            break

        chain.append(lg)
        prev = lg.get("previous_league_id")
        lid = str(prev) if prev else ""
        if lid == "None":
            lid = ""

    chain = sorted(chain, key=lambda x: int(x.get("season") or 0))
    if max_season is not None:
        chain = [x for x in chain if int(x.get("season") or 0) <= int(max_season)]

    _safe_write_json(snapshot_dir / "league_chain.json", chain)

    for lg in chain:
        season = int(lg.get("season") or 0)
        lid = str(lg.get("league_id") or "")
        season_dir = snapshot_dir / f"season_{season}"
        season_dir.mkdir(parents=True, exist_ok=True)

        _safe_write_json(season_dir / "league.json", lg)

        try:
            users = sc.users(lid)
        except Exception:
            users = []
        try:
            rosters = sc.rosters(lid)
        except Exception:
            rosters = []

        _safe_write_json(season_dir / "users.json", users)
        _safe_write_json(season_dir / "rosters.json", rosters)

        # nflverse injuries for season (best-effort)
        try:
            inj = load_nflverse_injuries(ext, season)
        except Exception:
            inj = pd.DataFrame()
        _safe_write_df(season_dir / "nflverse_injuries.csv", inj)

        # Weekly data
        week = 1
        while True:
            try:
                matchups = sc.matchups(week, lid)
            except Exception:
                matchups = []
            if not matchups:
                break

            wk_dir = season_dir / "weeks" / f"week_{week:02d}"
            _safe_write_json(wk_dir / "matchups.json", matchups)

            try:
                txs = sc.transactions(week, lid)
            except Exception:
                txs = []
            _safe_write_json(wk_dir / "transactions.json", txs)

            stats = _download_stats_week(http, season, week)
            _safe_write_json(wk_dir / "stats_nfl.json", stats)

            week += 1

    return snapshot_dir
