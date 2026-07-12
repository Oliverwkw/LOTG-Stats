from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

import pandas as pd

from .utils import HttpConfig, fetch_json
from .sleeper import SleeperClient
from .external import ExternalConfig, load_dynastyprocess_playerids, load_nflverse_injuries

SLEEPER_BASE = "https://api.sleeper.app/v1"

# Records when snapshot_all last captured live data, so a build can tell whether
# the committed snapshot is fresh enough to build on (see snapshot_age_days).
SNAPSHOT_META_NAME = "_snapshot_meta.json"


def snapshot_captured_at(repo_root: Path) -> Optional[datetime]:
    """UTC time the committed snapshot was last captured, or None if unknown."""
    meta = repo_root / "exports" / "snapshot" / SNAPSHOT_META_NAME
    try:
        stamp = json.loads(meta.read_text()).get("captured_at")
        dt = datetime.fromisoformat(stamp)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def snapshot_age_days(repo_root: Path, now: Optional[datetime] = None) -> Optional[float]:
    """Age of the committed snapshot in days, or None if it has no capture stamp."""
    captured = snapshot_captured_at(repo_root)
    if captured is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - captured).total_seconds() / 86400.0


def snapshot_is_stale(repo_root: Path, max_age_days: float,
                      now: Optional[datetime] = None) -> bool:
    """True if the snapshot is missing/undated or older than max_age_days."""
    age = snapshot_age_days(repo_root, now=now)
    return age is None or age > max_age_days


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


def refresh_current_season(
    repo_root: Path,
    league_id: str,
    http_cfg: Optional[HttpConfig] = None,
    client: Optional[Any] = None,
) -> bool:
    """Re-fetch ONLY the live current league (league/users/rosters/traded_picks/drafts)
    and overwrite that season's snapshot files.

    This is the cheap, always-on complement to the age-gated full ``snapshot_all``:
    the current roster is the one thing that changes constantly (trades/adds), so we
    refresh it every run instead of waiting for the staleness window. A dedicated
    ``SleeperClient`` with no ``cache_dir`` is used, so the request bypasses the
    on-disk cache and always hits the live API.

    Safe by construction: if the live fetch comes back empty (e.g. no network), the
    existing committed snapshot is left untouched rather than clobbered with blanks.
    Returns True only when fresh rosters were written. ``client`` is injectable for
    tests.
    """
    sc = client or SleeperClient(
        str(league_id),
        http_cfg or HttpConfig(timeout_seconds=30, max_retries=6, backoff_base_seconds=0.7),
    )
    try:
        lg = sc.league(str(league_id))
        rosters = sc.rosters(str(league_id))
    except Exception:
        return False
    if not isinstance(lg, dict) or not lg.get("season") or not rosters:
        # Missing league metadata or an empty roster list ⇒ treat as a failed fetch
        # and keep the last-good committed snapshot.
        return False

    season = int(lg["season"])
    season_dir = repo_root / "exports" / "snapshot" / f"season_{season}"
    _safe_write_json(season_dir / "league.json", lg)
    _safe_write_json(season_dir / "rosters.json", rosters)
    try:
        _safe_write_json(season_dir / "users.json", sc.users(str(league_id)) or [])
    except Exception:
        pass
    for name, getter in (("traded_picks", sc.traded_picks), ("drafts", getattr(sc, "drafts", None))):
        if getter is None:
            continue
        try:
            data = getter(str(league_id))
            if data:
                _safe_write_json(season_dir / f"{name}.json", data)
        except Exception:
            pass
    return True


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

    # Stamp the capture time last, so a partially-written snapshot isn't dated fresh.
    _safe_write_json(
        snapshot_dir / SNAPSHOT_META_NAME,
        {"captured_at": datetime.now(timezone.utc).isoformat(), "league_id": str(league_id)},
    )

    return snapshot_dir
