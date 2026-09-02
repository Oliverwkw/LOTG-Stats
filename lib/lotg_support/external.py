from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Cache freshness
# ---------------------------------------------------------------------------
# Every loader below used to download only when its file was ABSENT or EMPTY.
# Combined with `force_refresh` being set for the in-progress season alone, that
# meant a completed season's file, once present, was never fetched again — and
# the committed `.cache` is only rewritten by hand, so the shipped exports sat on
# a 2026-06-29 vintage of NFLverse for 65 days while upstream back-corrected
# 25,045 values underneath them. The player-id bridge and the bye schedule were
# worse: no `force_refresh` parameter at all, so nothing in the repo could
# refresh them.
#
# So freshness is now the loaders' own job, and it applies to EVERY file: past
# the age below, the next build re-downloads. The Tuesday build therefore keeps
# the whole cache under a week old on its own, with no workflow step to forget
# and no cache key to bust.
#
# Age is read from a sidecar log, not from mtime: `actions/checkout` stamps every
# file with the checkout time (git stores no mtimes), so an mtime test would call
# a two-month-old committed file "fetched seconds ago" on exactly the runs that
# matter. The log records when each file was last successfully DOWNLOADED,
# travels with the cache (it lives inside `cache_dir`), and is committed
# alongside `.cache` so a cold checkout knows how old its files really are. An
# unlisted file is treated as infinitely stale, which is the safe direction.
CACHE_MAX_AGE_DAYS = 6.0
FETCH_LOG_NAME = "_fetch_log.json"


def cache_max_age_days() -> float:
    """Staleness horizon in days. `LOTG_CACHE_MAX_AGE_DAYS` overrides; <= 0
    forces every file to re-download."""
    raw = str(os.environ.get("LOTG_CACHE_MAX_AGE_DAYS", "")).strip()
    if not raw:
        return CACHE_MAX_AGE_DAYS
    try:
        return float(raw)
    except ValueError:
        return CACHE_MAX_AGE_DAYS


def _fetch_log_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / FETCH_LOG_NAME


def read_fetch_log(cache_dir: Path) -> Dict[str, str]:
    """{filename: ISO-8601 timestamp of last successful download}."""
    try:
        blob = json.loads(_fetch_log_path(cache_dir).read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in blob.items()} if isinstance(blob, dict) else {}


def record_fetch(path: Path, when: Optional[datetime] = None) -> None:
    """Stamp `path` as downloaded now. Best-effort: a read-only cache dir must
    not fail a build, it just means the file reads stale again next time."""
    path = Path(path)
    log = read_fetch_log(path.parent)
    log[path.name] = (when or datetime.now(timezone.utc)).isoformat()
    try:
        _fetch_log_path(path.parent).write_text(json.dumps(log, indent=1, sort_keys=True))
    except OSError:
        pass


def cache_is_stale(path: Path, max_age_days: Optional[float] = None) -> bool:
    """True when `path` should be re-downloaded: missing, empty, never recorded
    as fetched, or fetched longer ago than the horizon."""
    path = Path(path)
    if (not path.exists()) or path.stat().st_size == 0:
        return True
    age = cache_max_age_days() if max_age_days is None else max_age_days
    if age <= 0:
        return True
    stamp = read_fetch_log(path.parent).get(path.name)
    if not stamp:
        return True                      # unknown vintage -> assume stale
    try:
        fetched = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched) > timedelta(days=age)


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
            # Write beside the target and rename over it. Now that a refresh
            # overwrites files that are ALREADY GOOD, a half-written body would
            # destroy the very copy the fallback below depends on; os.replace is
            # atomic within a filesystem, so the cached file is either the old
            # one or the whole new one.
            tmp = out.with_name(out.name + ".part")
            try:
                tmp.write_bytes(r.content)
                os.replace(tmp, out)
            finally:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
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


def _ensure(cfg: "ExternalConfig", path: Path, urls: list[str],
            force_refresh: bool = False) -> None:
    """Download `path` if it is missing, empty, stale, or forced.

    A source that is down or rate-limiting must never cost us a file we already
    have: on failure with a usable copy on disk we keep it and say nothing, and
    deliberately do NOT stamp the fetch log — so the file stays stale and the
    next build tries again rather than waiting out another whole horizon.
    """
    have = path.exists() and path.stat().st_size > 0
    if not (force_refresh or cache_is_stale(path)):
        return
    try:
        _download_best_effort(urls, path, cfg.timeout_seconds)
    except Exception:
        if not have:
            raise
        return
    record_fetch(path)

# ---------------------------------------------------------------------------
# Fantasy-position pins
# ---------------------------------------------------------------------------
# NFLverse labels a player by the position he PLAYS. For a two-way player that
# is a defensible label upstream and a broken one here: our league rosters and
# scores him at ONE fantasy position, and every league-relative stat we compute
# pools him with whoever shares that label — the weekly positional scoring
# percentile, the `_pos_factor` "adjusted by position" scaling, Starter PAR's
# replacement level (the bottom third of that year/week/position's started
# scores) and the "Number of X started" counts.
#
# Travis Hunter is the case this exists for. He is drafted, rostered and started
# in this league as a WR. In August 2026 NFLverse relabelled his 2025 weeks 1-7
# from WR/WR to CB/DB, which put him in a 2025 "CB" pool whose only member was
# himself: his weekly percentiles collapsed to 0.0 or 100.0 ranked against his
# own seven games (week 5, 9.4 pts -> 100.0; week 3, 3.1 pts -> 0.0), where the
# WR pool had them at 32.4 and 6.6. Weeks 8-17 have no NFLverse row at all and
# fall back to Sleeper's dictionary, so they stayed WR — splitting one player
# across two position pools inside a single season.
#
# Keyed by gsis_id, never by name: names collide and upstream re-spells them.
# Applied on READ rather than to the cached file, so `.cache` stays a faithful
# copy of what NFLverse published and the weekly audit's drift diff still sees
# the relabel for what it is.
#
# This is a pin, not a mapping table to grow by default: add a player only when
# his fantasy position here is genuinely unambiguous and upstream disagrees.
FANTASY_POSITION_PINS: dict[str, str] = {
    "00-0040718": "WR",   # Travis Hunter (JAX) — two-way WR/CB, rostered as a WR
}

# The columns that carry a position label in the NFLverse files we read, and the
# columns those files use for the GSIS player id.
_POSITION_COLS = ("position", "position_group", "depth_chart_position", "ngs_position")
_GSIS_COLS = ("player_id", "gsis_id")


def apply_position_pins(df: pd.DataFrame) -> pd.DataFrame:
    """Overwrite the position labels of pinned players. Returns `df` (mutated).

    A no-op for every file that carries neither a GSIS id column nor a position
    column, and for every frame that names none of the pinned players.
    """
    if df is None or df.empty or not FANTASY_POSITION_PINS:
        return df
    id_col = next((c for c in _GSIS_COLS if c in df.columns), None)
    if id_col is None:
        return df
    pos_cols = [c for c in _POSITION_COLS if c in df.columns]
    if not pos_cols:
        return df
    # A position column that arrived ALL-EMPTY — e.g. a preseason weekly-roster
    # file published before the season starts, where nflverse hasn't populated
    # positions yet — is typed float64 by the CSV reader. Writing a string label
    # ('WR') into a float64 column raises TypeError under pandas' strict dtype
    # assignment, which aborted the whole 2026 weekly-roster load. Cast the
    # columns we're about to overwrite to object first (a no-op for a normal
    # string position column).
    for col in pos_cols:
        if df[col].dtype != object:
            df[col] = df[col].astype(object)
    ids = df[id_col].astype(str)
    for pid, pos in FANTASY_POSITION_PINS.items():
        hit = ids == pid
        if hit.any():
            for col in pos_cols:
                df.loc[hit, col] = pos
    return df


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
    _ensure(cfg, path, urls)
    return pd.read_csv(path)

def load_dynastyprocess_values_players(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values-players.csv",
        "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values-players.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_values_players.csv"
    _ensure(cfg, path, urls)
    return pd.read_csv(path)

def load_dynastyprocess_values_picks(cfg: ExternalConfig) -> pd.DataFrame:
    urls = [
        "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values-picks.csv",
        "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values-picks.csv",
    ]
    path = cfg.cache_dir / "dynastyprocess_values_picks.csv"
    _ensure(cfg, path, urls)
    return pd.read_csv(path)

def load_nflverse_injuries(cfg: ExternalConfig, season: int, force_refresh: bool = False) -> pd.DataFrame:
    # nflverse makes weekly injury report data available via its releases; easiest stable source is nflreadr's hosted files.
    # This URL pattern is stable in practice; if it ever changes, update here.
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/injuries/injuries_{season}.csv",
    ]
    path = cfg.cache_dir / f"nflverse_injuries_{season}.csv"
    _ensure(cfg, path, urls, force_refresh=force_refresh)
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
    _ensure(cfg, path, urls)
    return apply_position_pins(pd.read_csv(path))

def load_nflverse_stats_player_week(cfg: ExternalConfig, season: int, force_refresh: bool = False) -> pd.DataFrame:
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
    _ensure(cfg, path, urls, force_refresh=force_refresh)
    # handle possible gz without relying on pandas compression inference
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        df = pd.read_csv(path, compression='gzip', low_memory=False)
    return apply_position_pins(df)


def load_nflverse_weekly_rosters(cfg: ExternalConfig, season: int, force_refresh: bool = False) -> pd.DataFrame:
    """Load nflverse WEEKLY rosters for a season (every player on a team that
    week, including IR / suspended / PUP — players who never accumulate stats).
    Used to give those players their real NFL team instead of the 'NFL'
    free-agent sentinel. Columns of interest: season, week, team, gsis_id."""
    urls = [
        f"https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv.gz",
        f"https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/weekly_rosters/roster_weekly_{season}.csv",
    ]
    path = cfg.cache_dir / f"nflverse_weekly_rosters_{season}.csv"
    _ensure(cfg, path, urls, force_refresh=force_refresh)
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        df = pd.read_csv(path, compression='gzip', low_memory=False)
    return apply_position_pins(df)
