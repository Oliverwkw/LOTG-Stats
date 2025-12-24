
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta, date
from collections import Counter, deque, defaultdict
import json
import math
import traceback
import logging
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays")

LOG = logging.getLogger("lotg")
if not LOG.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


import pandas as pd

# ----------------------------
# DataFrame safety helpers
# ----------------------------
def ensure_cols(df: pd.DataFrame, cols, default=None):
    """Ensure columns exist; if missing, create with default."""
    for c in cols:
        if c not in df.columns:
            df[c] = default
    return df

def to_num_series(s, default=0.0):
    """Robust numeric coercion for series/array-like; returns float series."""
    if s is None:
        return pd.Series([], dtype='float64')
    out = pd.to_numeric(s, errors='coerce')
    if isinstance(out, pd.Series):
        return out.fillna(default)
    # scalar
    return pd.Series([out if pd.notna(out) else default], dtype='float64')

def safe_to_numeric(df: pd.DataFrame, col: str, default=0.0):
    """Convert df[col] to numeric if present; otherwise create with default."""
    if col not in df.columns:
        df[col] = default
    else:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(default)
    return df

def as_bool(df: pd.DataFrame, col: str, default=False):
    """Ensure a boolean column exists, with pandas BooleanDtype."""
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default).astype('boolean')
    return df

def log_df(df: pd.DataFrame, name: str, sample_cols=None, n=3):
    """Log basic df shape and missingness for debugging."""
    try:
        LOG.info('%s: shape=%s', name, df.shape)
        if sample_cols:
            miss = {c: int(df[c].isna().sum()) for c in sample_cols if c in df.columns}
            LOG.info('%s: missing=%s', name, miss)
    except Exception as e:
        LOG.warning('log_df failed for %s: %s', name, e)
    return df


def log_missing_cols(df: pd.DataFrame, name: str, required: list[str]) -> None:
    """Log missing required columns; helps catch silent schema drift."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        LOG.warning("%s: missing expected columns: %s", name, missing)


import yaml
from dateutil import parser as dateparser

from .utils import HttpConfig, safe_div, clean_name
from .sleeper import SleeperClient
from .external import (
    ExternalConfig,
    load_dynastyprocess_playerids,
    load_dynastyprocess_values_players,
    load_dynastyprocess_values_picks,
    load_nflverse_injuries,
)
from .lineup import compute_optimal_lineup
from .plan import load_plan_catalog, require_columns


# ============================================================
# Build philosophy (two-step internally):
#  1) Pull & cache ALL Sleeper + supporting NFL data we need.
#  2) Compute every sheet deterministically from those caches.
# ============================================================


@dataclass
class RunConfig:
    league_id: str
    min_season: int | None
    max_season: int | None
    season_type: str = "regular"


# --------------------------
# Logging helpers
# --------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _log(path: Path, msg: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.read_text() + msg + "\n" if path.exists() else msg + "\n")
    except Exception:
        pass

def _log_exc(path: Path, where: str, e: Exception) -> None:
    _log(path, f"[{_now_iso()}] ERROR at {where}: {type(e).__name__}: {e}\n{traceback.format_exc()}")

def _to_int(x: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return default

def _to_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return default

def _safe_df(obj: Any) -> pd.DataFrame:
    return obj if isinstance(obj, pd.DataFrame) else pd.DataFrame()

def _first_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _epoch_ms_to_dt(ms: Any) -> Optional[datetime]:
    try:
        ms_i = int(ms)
        if ms_i <= 0:
            return None
        return datetime.fromtimestamp(ms_i / 1000, tz=timezone.utc)
    except Exception:
        return None

def _epoch_ms_to_date(ms: Any) -> Optional[date]:
    dt = _epoch_ms_to_dt(ms)
    return dt.date() if dt else None

def _calc_age(birth_date_str: Optional[str], on_date: date) -> Optional[float]:
    if not birth_date_str:
        return None
    try:
        bd = dateparser.parse(str(birth_date_str)).date()
        return round((on_date - bd).days / 365.25, 2)
    except Exception:
        return None


# --------------------------
# Team handle mapping (HANDLE, not franchise name)
# --------------------------

def _team_handle_map(users: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for u in users or []:
        uid = str(u.get("user_id"))
        handle = u.get("display_name") or u.get("username")
        if not handle:
            meta = u.get("metadata") or {}
            handle = meta.get("team_name") or uid
        out[uid] = str(handle)
    return out


# --------------------------
# NFL team normalization + bye schedule support
# --------------------------

_TEAM_NORMALIZE = {
    "LA": "LAR", "STL": "LAR",
    "SD": "LAC",
    "WSH": "WAS",
    "ARZ": "ARI", "AZ": "ARI",
    "NWE": "NE",
    "KCC": "KC",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "GNB": "GB",
    "LVR": "LV",
    # already-normalized common codes:
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BUF": "BUF", "CAR": "CAR",
    "CHI": "CHI", "CIN": "CIN", "CLE": "CLE", "DAL": "DAL", "DEN": "DEN",
    "DET": "DET", "GB": "GB", "HOU": "HOU", "IND": "IND", "JAX": "JAX",
    "KC": "KC", "LAC": "LAC", "LAR": "LAR", "LV": "LV", "MIA": "MIA",
    "MIN": "MIN", "NE": "NE", "NO": "NO", "NYG": "NYG", "NYJ": "NYJ",
    "PHI": "PHI", "PIT": "PIT", "SEA": "SEA", "SF": "SF", "TB": "TB",
    "TEN": "TEN", "WAS": "WAS",
}

def _norm_team(t: Any) -> Optional[str]:
    if not t:
        return None
    s = str(t).strip().upper()
    return _TEAM_NORMALIZE.get(s, s)

def _download_csv_best_effort(urls: List[str], path: Path, timeout: int = 120, debug: Optional[Path]=None) -> pd.DataFrame:
    import requests
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        try:
            return pd.read_csv(path)
        except Exception:
            pass
    last_err = None
    session = requests.Session()
    session.trust_env = False
    for url in urls:
        try:
            r = session.get(url, timeout=timeout, proxies={"http": None, "https": None})
            if r.status_code == 200 and r.content:
                path.write_bytes(r.content)
                try:
                    return pd.read_csv(path)
                except Exception:
                    return pd.DataFrame()
            last_err = f"{r.status_code} {url}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e} {url}"
    if debug:
        _log(debug, f"[{_now_iso()}] WARN csv download failed: {last_err}")
    return pd.DataFrame()

def _played_teams_by_week(games: pd.DataFrame, season: int) -> Dict[int, set]:
    games = _safe_df(games)
    out: Dict[int, set] = {}
    if games.empty:
        return out
    if not {"season", "week", "home_team", "away_team"}.issubset(set(games.columns)):
        return out
    sub = games.copy()
    try:
        sub["season"] = pd.to_numeric(sub["season"], errors="coerce").astype("Int64")
        sub["week"] = pd.to_numeric(sub["week"], errors="coerce").astype("Int64")
    except Exception:
        return out
    sub = sub[sub["season"] == season]
    if sub.empty:
        return out
    for wk, g in sub.groupby("week"):
        if pd.isna(wk):
            continue
        home = g["home_team"].dropna().astype(str).map(_norm_team).tolist()
        away = g["away_team"].dropna().astype(str).map(_norm_team).tolist()
        out[int(wk)] = set([t for t in (home + away) if t])
    return out


# --------------------------
# Injury/Suspension flags (platform designation at that week)
# --------------------------

def _infer_flags_from_sleeper_player_meta(meta: Dict[str, Any]) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Uses Sleeper platform designations from /players/nfl (status/injury_status).
    Conservative: only True when it's clearly OUT/IR/PUP/NFI or SUSP.
    """
    if not isinstance(meta, dict):
        return (None, None)

    status = str(meta.get("status") or "").lower()
    injury_status = str(meta.get("injury_status") or "").lower()

    # suspension
    if "susp" in status or "susp" in injury_status:
        return (False, True)

    healthy_markers = {"active", "", "healthy", "none", "null"}
    if (status in healthy_markers) and (injury_status in healthy_markers):
        return (False, False)

    # Out/IR style
    injury_markers = ["ir", "out", "inactive", "pup", "nfi", "injured", "covid"]
    if any(k == status for k in injury_markers) or any(k in injury_status for k in injury_markers):
        return (True, False)

    # questionable/doubtful can still play -> do not mark True
    if ("question" in status) or ("question" in injury_status) or ("doubt" in injury_status):
        return (False, False)

    return (None, None)

def _infer_flags_from_nflverse(injuries: pd.DataFrame, gsis_id: Optional[str], season: int, week: int) -> Tuple[Optional[bool], Optional[bool]]:
    injuries = _safe_df(injuries)
    if injuries.empty or not gsis_id:
        return (None, None)
    if "gsis_id" not in injuries.columns:
        return (None, None)

    try:
        sub = injuries.copy()
        if "season" in sub.columns:
            sub["season"] = pd.to_numeric(sub["season"], errors="coerce").astype("Int64")
            sub = sub[sub["season"] == season]
        if "week" in sub.columns:
            sub["week"] = pd.to_numeric(sub["week"], errors="coerce").astype("Int64")
            sub = sub[sub["week"] == week]
        sub = sub[sub["gsis_id"].astype(str) == str(gsis_id)]
    except Exception:
        return (None, None)

    if sub.empty:
        return (None, None)

    status_col = _first_col(sub, ["report_status", "status", "game_status", "injury_status", "practice_status"])
    if not status_col:
        return (None, None)

    s = str(sub.iloc[0].get(status_col) or "").lower()
    if not s:
        return (None, None)

    suspension = ("susp" in s) or ("sspd" in s)
    injury = (("out" in s) or ("ir" in s) or ("inactive" in s) or ("pup" in s)) and not suspension
    return (injury, suspension)

def _merge_flags(primary: Tuple[Optional[bool], Optional[bool]], secondary: Tuple[Optional[bool], Optional[bool]]) -> Tuple[Optional[bool], Optional[bool]]:
    inj1, sus1 = primary
    inj2, sus2 = secondary
    if sus1 is True or sus2 is True:
        return (False, True)
    if inj1 is True or inj2 is True:
        return (True, False)
    if (inj1 is False and sus1 is False) or (inj2 is False and sus2 is False):
        return (False, False)
    return (None, None)


# --------------------------
# League chain
# --------------------------

def _walk_league_chain(sc: SleeperClient, start_league_id: str, min_season: int | None, max_season: int | None) -> List[Dict[str, Any]]:
    chain: List[Dict[str, Any]] = []
    lid = str(start_league_id)
    seen = set()
    while lid and lid not in seen:
        seen.add(lid)
        try:
            lg = sc.league(lid)
        except Exception:
            break
        if not isinstance(lg, dict):
            break
        season = _to_int(lg.get("season"), None)
        if season is not None and min_season is not None and season < min_season:
            break
        chain.append(lg)
        prev = lg.get("previous_league_id")
        lid = str(prev) if prev else ""
        if lid == "None":
            lid = ""
    chain = sorted(chain, key=lambda x: _to_int(x.get("season"), 0) or 0)
    if max_season is not None:
        chain = [x for x in chain if (_to_int(x.get("season"), 0) or 0) <= max_season]
    return chain


# --------------------------
# Plan column enforcement
# --------------------------

def _ensure_plan_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    df = _safe_df(df).copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def _is_text_column(col: str) -> bool:
    col_l = col.lower()
    text_markers = [
        "team",
        "player",
        "opponent",
        "record",
        "result",
        "link",
        "assets",
        "type of transaction",
        "date",
        "trade",
        "etc",
        "original",
        "number",
        "pick",
        "position",
        "starter/bench",
        "nfl team",
    ]
    numeric_markers = [
        "number of ",
        "points",
        "pf",
        "avg",
        "max",
        "min",
        "range",
        "margin",
        "win %",
        "win?",
        "loss",
        "efficiency",
        "hardship",
        "luck",
        "tanking",
        "difference",
        "change",
        "weeks",
        "week",
        "year",
        "age",
        "ppg",
        "faab",
        "value",
        "streak",
        "score",
    ]
    if any(m in col_l for m in numeric_markers):
        return False
    return any(m in col_l for m in text_markers)


def _fill_empty_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            continue
        if df[col].isna().all():
            df[col] = "N/A"
    return df


def _fill_missing_values(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            continue
        df[col] = df[col].astype(object).replace("", "N/A").fillna("N/A")
    return df


# --------------------------
# Matchup naming for playoffs/toilet
# --------------------------

def _matchup_stage(week: int, playoff_start: Optional[int]) -> Optional[str]:
    if not playoff_start:
        return None
    if week < playoff_start:
        return None
    if week == playoff_start:
        return "SEMIS"
    if week == playoff_start + 1:
        return "FINALS"
    return None


# --------------------------
# Main build
# --------------------------

def build_all(repo_root: Path) -> None:
    debug = repo_root / "exports" / "raw" / "build_debug.log"
    _log(debug, f"\n[{_now_iso()}] ===== Build start =====")

    plan_csv = repo_root / "plan" / "LOTG Plan - Sheet1.csv"
    catalog = load_plan_catalog(plan_csv)

    cfg = yaml.safe_load((repo_root / "config/league.yaml").read_text())
    run_cfg = RunConfig(
        league_id=str(cfg["league_id"]),
        min_season=cfg.get("min_season"),
        max_season=cfg.get("max_season"),
        season_type=str(cfg.get("season_type", "regular")).lower(),
    )

    http = HttpConfig(timeout_seconds=30, max_retries=10, backoff_base_seconds=0.7)
    sc = SleeperClient(run_cfg.league_id, http)

    cache_dir = repo_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    ext = ExternalConfig(cache_dir=cache_dir, timeout_seconds=120)

    # ------------- External data -------------
    try:
        dp_ids = _safe_df(load_dynastyprocess_playerids(ext))
    except Exception as e:
        dp_ids = pd.DataFrame()
        _log_exc(debug, "load_dynastyprocess_playerids", e)

    for c in ["sleeper_id", "gsis_id", "name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    # nflverse games for byes
    games = _download_csv_best_effort(
        urls=[
            "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
            "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
        ],
        path=cache_dir / "nfldata_games.csv",
        timeout=120,
        debug=debug,
    )
    played_by_week_by_season: Dict[int, Dict[int, set]] = {}
    if not games.empty:
        try:
            games["season"] = pd.to_numeric(games["season"], errors="coerce").astype("Int64")
        except Exception:
            pass

    # Sleeper NFL players (meta)
    try:
        players_nfl = sc.players_nfl()
    except Exception as e:
        players_nfl = {}
        _log_exc(debug, "players_nfl", e)

    pid_meta: Dict[str, Dict[str, Any]] = {}
    pid_pos: Dict[str, str] = {}
    for pid, meta in (players_nfl or {}).items():
        if not isinstance(meta, dict):
            continue
        pid = str(pid)
        full = meta.get("full_name") or (f"{meta.get('first_name','')} {meta.get('last_name','')}".strip())
        pid_meta[pid] = {
            "full_name": full or pid,
            "pos": (meta.get("position") or ""),
            "team": _norm_team(meta.get("team")),
            "birth_date": meta.get("birth_date") or meta.get("birthdate"),
            "years_exp": meta.get("years_exp"),
            "status": meta.get("status"),
            "injury_status": meta.get("injury_status"),
        }
        pid_pos[pid] = (pid_meta[pid]["pos"] or "").upper()

    # ------------- League chain -------------
    leagues = _walk_league_chain(sc, run_cfg.league_id, run_cfg.min_season, run_cfg.max_season)
    raw_dir = repo_root / "exports" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    def write_outputs(tables: List[Tuple[str, pd.DataFrame, str]]) -> None:
        out_dir = repo_root / "exports"
        out_dir.mkdir(exist_ok=True)
        for fname, frame, plan_key in tables:
            cols = catalog.get(plan_key, [])
            frame = _safe_df(frame)
            out = _ensure_plan_columns(frame, cols)
            out = _fill_empty_columns(out, cols)
            out = _fill_missing_values(out, cols)
            try:
                require_columns(out, cols, fname.replace(".csv", ""))
            except Exception as e:
                _log_exc(debug, f"require_columns_{fname}", e)
            out.to_csv(out_dir / fname, index=False)

        try:
            from openpyxl import Workbook
            from openpyxl.utils import get_column_letter

            wb = Workbook()
            wb.remove(wb.active)

            for csvf in sorted(out_dir.glob("*.csv")):
                sheet_name = csvf.stem[:31]
                ws = wb.create_sheet(title=sheet_name)

                try:
                    d = pd.read_csv(csvf)
                except Exception:
                    d = pd.DataFrame()

                ws.append(list(d.columns))
                for row in d.itertuples(index=False, name=None):
                    ws.append(list(row))
                ws.freeze_panes = "A2"

                if ws.max_column >= 1:
                    ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{max(1, ws.max_row)}"

                try:
                    for j, col in enumerate(d.columns, 1):
                        max_len = max([len(str(col))] + [len(str(x)) for x in d[col].head(200).fillna("").astype(str).tolist()])
                        ws.column_dimensions[get_column_letter(j)].width = min(60, max(10, max_len + 2))
                except Exception:
                    pass

            wb.save(out_dir / "LOTG_Stats.xlsx")
        except Exception as e:
            _log_exc(debug, "excel_write", e)

        try:
            import zipfile
            with zipfile.ZipFile(out_dir / "LOTG_Exports.zip", "w", zipfile.ZIP_DEFLATED) as z:
                for f in out_dir.glob("*.csv"):
                    z.write(f, arcname=f.name)
                if (out_dir / "LOTG_Stats.xlsx").exists():
                    z.write(out_dir / "LOTG_Stats.xlsx", arcname="LOTG_Stats.xlsx")
                for f in (out_dir / "raw").glob("*"):
                    if f.is_file():
                        z.write(f, arcname=f"raw/{f.name}")
        except Exception as e:
            _log_exc(debug, "zip_exports", e)

        _log(debug, f"[{_now_iso()}] ===== Build end =====")

    if not leagues:
        fallback_dir = repo_root / "data"
        fallback_tables = []
        for fname, plan_key in [
            ("player_week.csv", "Player-Week"),
            ("player_year.csv", "Player-year"),
            ("player_all_time.csv", "Player-all-time"),
            ("team_week.csv", "team-week"),
            ("team_year.csv", "team-year"),
            ("team_all_time.csv", "team-all-time"),
            ("league_week.csv", "league-week"),
            ("league_year.csv", "league-year"),
            ("league_all_time.csv", "league-all-time"),
            ("transactions.csv", "transactions"),
            ("trades.csv", "trades"),
            ("pick_history.csv", "Pick History"),
        ]:
            src = fallback_dir / fname
            if src.exists():
                try:
                    fallback_tables.append((fname, pd.read_csv(src), plan_key))
                except Exception:
                    fallback_tables.append((fname, pd.DataFrame(), plan_key))
            else:
                fallback_tables.append((fname, pd.DataFrame(), plan_key))
        _log(debug, f"[{_now_iso()}] WARN no leagues found; using fallback data/ outputs")
        write_outputs(fallback_tables)
        return

    # ------------- Output rows -------------
    player_week_rows: List[Dict[str, Any]] = []
    team_week_rows: List[Dict[str, Any]] = []
    transactions_rows: List[Dict[str, Any]] = []
    trades_rows: List[Dict[str, Any]] = []
    pick_rows: List[Dict[str, Any]] = []

    # Internal ledger helpers
    # key: (season, week, roster_id) -> opponent roster_id + opponent points
    opp_rid_map: Dict[Tuple[int, int, int], Optional[int]] = {}
    opp_pf_map: Dict[Tuple[int, int, int], Optional[float]] = {}
    stage_label_map: Dict[Tuple[int, int, int], Optional[str]] = {}

    # Determine last completed week per league (robust, per Apps Script)
    def last_completed_week(league_id: str, season: int, max_weeks: int = 30) -> int:
        """Last week with any non-zero team points, excluding the fantasy-championship week.

        Sleeper leagues often expose an extra 'final' week that we intentionally exclude from all tables:
        - week 18 for seasons 2021+
        - week 17 for seasons <= 2020 (kept for future ESPN backfill)
        """
        excluded = 18 if int(season) >= 2021 else 17
        last = 0
        for wk in range(1, max_weeks + 1):
            if wk == excluded:
                continue
            try:
                mu = sc.matchups(wk, league_id)
            except Exception:
                mu = None
            if not mu:
                continue
            has_real = any((_to_float(m.get("points"), 0.0) or 0.0) > 0.0 for m in mu)
            if has_real:
                last = wk
        return last


    # ------------- Build each season -------------
    for lg in leagues:
        league_id = str(lg.get("league_id"))
        season = _to_int(lg.get("season"), 0) or 0

        # playoff start week (Sleeper setting)
        settings = lg.get("settings") or {}
        playoff_start = _to_int(settings.get("playoff_week_start"), None)

        # cache played_by_week
        if season not in played_by_week_by_season:
            played_by_week_by_season[season] = _played_teams_by_week(games, season) if not games.empty else {}
        played_by_week = played_by_week_by_season.get(season, {})

        # nflverse injuries (optional; used as secondary signal)
        try:
            injuries = _safe_df(load_nflverse_injuries(ext, season))
        except Exception as e:
            injuries = pd.DataFrame()
            _log_exc(debug, f"load_nflverse_injuries_{season}", e)

        # users/rosters
        try:
            users = sc.users(league_id)
        except Exception as e:
            users = []
            _log_exc(debug, f"users_{season}", e)
        try:
            rosters = sc.rosters(league_id)
        except Exception as e:
            rosters = []
            _log_exc(debug, f"rosters_{season}", e)

        user_handle = _team_handle_map(users)

        roster_owner: Dict[int, str] = {}
        roster_to_team: Dict[int, str] = {}
        for r in rosters or []:
            rid = _to_int(r.get("roster_id"), None)
            if rid is None:
                continue
            roster_owner[rid] = str(r.get("owner_id") or "")
            roster_to_team[rid] = user_handle.get(roster_owner[rid], f"Roster {rid}")

        # raw snapshots
        try:
            (raw_dir / f"league_{season}.json").write_text(json.dumps(lg, indent=2))
            (raw_dir / f"users_{season}.json").write_text(json.dumps(users, indent=2))
            (raw_dir / f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))
        except Exception:
            pass

        # draft picks history (rookie + startup as available in Sleeper; still partial)
        try:
            drafts = sc.drafts(league_id)
        except Exception as e:
            drafts = []
            _log_exc(debug, f"drafts_{season}", e)
        draft_picks_all: List[Dict[str, Any]] = []
        for d in drafts or []:
            did = str(d.get("draft_id") or "")
            if not did:
                continue
            try:
                picks = sc.draft_picks(did)
            except Exception as e:
                picks = []
                _log_exc(debug, f"draft_picks_{season}_{did}", e)
            for p in picks or []:
                p["draft_id"] = did
                p["draft_season"] = season
            draft_picks_all.extend(picks or [])

        for p in draft_picks_all:
            rnd = p.get("round")
            pick_no = p.get("pick_no")
            roster_id = p.get("roster_id")
            player = p.get("player_id")
            team = roster_to_team.get(_to_int(roster_id, -1), f"Roster {roster_id}") if roster_id is not None else None
            pick_rows.append({
                "Year": season,
                "Original Team": team,
                "Number": f"R{rnd}.{pick_no}",
                "Player Picked": pid_meta.get(str(player), {}).get("full_name") if player else None,
                "Trade 1": None, "Trade 2": None, "Trade 3": None, "Trade 4": None, "Trade 5": None,
                "Trade 6": None, "Trade 7": None, "Trade 8": None, "Trade 9": None, "Trade 10": None,
                "etc": None,
            })

        # robust last completed week
        try:
            last_week = last_completed_week(league_id, season)
        except Exception as e:
            last_week = 0
            _log_exc(debug, f"last_completed_week_{season}", e)

        if last_week <= 0:
            _log(debug, f"[{_now_iso()}] INFO season {season}: no completed weeks, skipping")
            continue

        # Exclude week 18 always; if season < 2021 exclude week 17 (kept for future ESPN import)
        def week_allowed(wk: int) -> bool:
            if wk == 18:
                return False
            if season < 2021 and wk == 17:
                return False
            return True

        # storage for week/team scoring for expected win, etc.
        team_pf_by_week: Dict[int, Dict[str, float]] = defaultdict(dict)

        # ------------- Pre-fetch all weekly matchups & transactions -------------
        matchups_by_week: Dict[int, List[Dict[str, Any]]] = {}
        tx_by_week: Dict[int, List[Dict[str, Any]]] = {}

        for wk in range(1, min(last_week, 30) + 1):
            if not week_allowed(wk):
                continue
            try:
                mu = sc.matchups(wk, league_id) or []
                matchups_by_week[wk] = mu
                for m in mu:
                    rid = _to_int(m.get("roster_id"), None)
                    if rid is None:
                        continue
                    tm = roster_to_team.get(rid, f"Roster {rid}")
                    team_pf_by_week[wk][tm] = float(_to_float(m.get("points"), 0.0) or 0.0)
            except Exception as e:
                _log_exc(debug, f"matchups_{season}_wk{wk}", e)

            try:
                tx_by_week[wk] = sc.transactions(wk, league_id) or []
            except Exception as e:
                tx_by_week[wk] = []
                _log_exc(debug, f"transactions_{season}_wk{wk}", e)

        # ------------- Build opponent roster mapping + playoff labels -------------
        for wk, mu in matchups_by_week.items():
            mdf = _safe_df(pd.DataFrame(mu))
            if mdf.empty:
                continue
            if "matchup_id" not in mdf.columns:
                continue
            # ensure numeric
            try:
                mdf["roster_id"] = pd.to_numeric(mdf["roster_id"], errors="coerce").astype("Int64")
                mdf["points"] = pd.to_numeric(mdf["points"], errors="coerce").fillna(0.0)
            except Exception:
                pass

            stage = _matchup_stage(wk, playoff_start)

            for mid, g in mdf.groupby("matchup_id"):
                rids = [int(x) for x in g["roster_id"].dropna().astype(int).tolist()]
                if len(rids) != 2:
                    continue
                a, b = rids
                pa = float(g.loc[g["roster_id"] == a, "points"].iloc[0])
                pb = float(g.loc[g["roster_id"] == b, "points"].iloc[0])

                opp_rid_map[(season, wk, a)] = b
                opp_rid_map[(season, wk, b)] = a
                opp_pf_map[(season, wk, a)] = pb
                opp_pf_map[(season, wk, b)] = pa

            # playoff/toilet naming per your rules:
            if stage:
                # Determine top4 by regular season W-L then PF tiebreaker, using weeks < playoff_start.
                try:
                    if playoff_start and wk == playoff_start:
                        reg = []
                        for rr in rosters or []:
                            rid = _to_int(rr.get("roster_id"), None)
                            if rid is None:
                                continue
                            tm = roster_to_team.get(rid, f"Roster {rid}")
                            # compute record up to reg season
                            wins = losses = ties = 0
                            pf_sum = 0.0
                            for w2 in range(1, playoff_start):
                                if not week_allowed(w2):
                                    continue
                                pf2 = team_pf_by_week.get(w2, {}).get(tm)
                                if pf2 is None:
                                    continue
                                pf_sum += float(pf2)
                                opp_pf2 = opp_pf_map.get((season, w2, rid))
                                if opp_pf2 is None:
                                    continue
                                if pf2 > opp_pf2:
                                    wins += 1
                                elif pf2 < opp_pf2:
                                    losses += 1
                                else:
                                    ties += 1
                            reg.append((tm, rid, wins, losses, ties, pf_sum))
                        reg.sort(key=lambda x: (x[2] + 0.5 * x[4], x[5]), reverse=True)
                        top4 = set([rid for _, rid, *_ in reg[:4]])
                        bottom4 = set([rid for _, rid, *_ in reg[4:]])
                        # annotate this week (semis) and next week (finals)
                        for rid in top4:
                            stage_label_map[(season, playoff_start, rid)] = "Semifinal"
                        for rid in bottom4:
                            stage_label_map[(season, playoff_start, rid)] = "Toilet Semis"
                        # next week labels depend on semis results
                        finals_week = playoff_start + 1
                        if week_allowed(finals_week) and finals_week in matchups_by_week:
                            # Determine winners/losers within those brackets
                            for rid in top4:
                                opp = opp_rid_map.get((season, playoff_start, rid))
                                if opp is None:
                                    continue
                                if rid < opp:  # handle each pair once
                                    pf_a = team_pf_by_week[playoff_start].get(roster_to_team[rid], 0.0)
                                    pf_b = team_pf_by_week[playoff_start].get(roster_to_team[opp], 0.0)
                                    win_a = (pf_a > pf_b)
                                    winner = rid if win_a else opp
                                    loser = opp if win_a else rid
                                    stage_label_map[(season, finals_week, winner)] = "Final"
                                    stage_label_map[(season, finals_week, loser)] = "3rd Place"
                            for rid in bottom4:
                                opp = opp_rid_map.get((season, playoff_start, rid))
                                if opp is None:
                                    continue
                                if rid < opp:
                                    pf_a = team_pf_by_week[playoff_start].get(roster_to_team[rid], 0.0)
                                    pf_b = team_pf_by_week[playoff_start].get(roster_to_team[opp], 0.0)
                                    win_a = (pf_a > pf_b)
                                    winner = rid if win_a else opp
                                    loser = opp if win_a else rid
                                    stage_label_map[(season, finals_week, winner)] = "Toilet Final"
                                    stage_label_map[(season, finals_week, loser)] = "Toilet Trash"
                except Exception as e:
                    _log_exc(debug, f"playoff_labeling_{season}_wk{wk}", e)

        # ------------- Weekly loop to build team_week & player_week -------------
        prev_starters_by_team: Dict[str, set] = {}
        player_last5_healthy: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5))  # for hardship later
        # for player awards
        awards_weekly = defaultdict(list)  # (season,wk) -> list of (pid, team, pts, started, pos)

        for wk, mu in matchups_by_week.items():
            stage = _matchup_stage(wk, playoff_start)
            # tx summaries
            faab_spent: Dict[str, float] = defaultdict(float)
            trade_count: Dict[str, int] = defaultdict(int)
            tx_count: Dict[str, int] = defaultdict(int)

            for t in tx_by_week.get(wk, []):
                try:
                    creator = str(t.get("creator") or "")
                    team = user_handle.get(creator) if creator else None
                    if team:
                        tx_count[team] += 1
                        if t.get("type") == "trade":
                            trade_count[team] += 1
                        meta = t.get("metadata") or {}
                        if isinstance(meta, dict):
                            bid = _to_float(meta.get("waiver_bid") or meta.get("faab") or 0.0, 0.0) or 0.0
                            faab_spent[team] += float(bid)
                except Exception as e:
                    _log_exc(debug, f"tx_summary_{season}_wk{wk}", e)

            # build team rows
            for m in mu:
                try:
                    rid = _to_int(m.get("roster_id"), None)
                    if rid is None:
                        continue
                    team = roster_to_team.get(rid, f"Roster {rid}")
                    pf = float(_to_float(m.get("points"), 0.0) or 0.0)

                    opp_rid = opp_rid_map.get((season, wk, rid))
                    opp_team = roster_to_team.get(opp_rid, f"Roster {opp_rid}") if opp_rid is not None else None
                    opp_points = opp_pf_map.get((season, wk, rid))
                    margin = (pf - opp_points) if opp_points is not None else None
                    win = None
                    if margin is not None:
                        win = 1 if margin > 0 else 0 if margin < 0 else 0.5

                    starters = [str(x) for x in (m.get("starters") or []) if x]
                    players = [str(x) for x in (m.get("players") or []) if x]
                    ppts_raw = m.get("players_points") or {}
                    ppts: Dict[str, float] = {}
                    if isinstance(ppts_raw, dict):
                        for k, v in ppts_raw.items():
                            try:
                                ppts[str(k)] = float(v)
                            except Exception:
                                pass

                    # Max PF: use proven algorithm (Apps Script parity)
                    max_pf = compute_optimal_lineup(ppts, pid_pos, season)
                    # Sanity check: if a team scored points, Max PF must be > 0 (otherwise per-player points were lost).
                    if (pf or 0.0) > 0.0 and (max_pf or 0.0) <= 0.0:
                        _log(
                            debug,
                            "ERROR: Max PF computed as 0 despite PF>0. league=%s season=%s week=%s roster_id=%s "
                            "pf=%s players_points_type=%s players_points_len=%s"
                            % (
                                league_id,
                                season,
                                wk,
                                rid,
                                pf,
                                type(ppts_raw).__name__,
                                (len(ppts) if isinstance(ppts, dict) else "NA"),
                            ),
                        )
                        LOG.warning(
                            "Max PF sanity: PF>0 but Max PF==0 for %s %s wk=%s roster=%s; leaving Max PF blank. Check raw exports.",
                            season,
                            league_id,
                            wk,
                            rid,
                        )
                    eff = safe_div(pf, max_pf, default=0.0)

                    # expected win percentile vs league that week
                    scores = list(team_pf_by_week.get(wk, {}).values())
                    expected = None
                    luck_raw = None
                    if scores and len(scores) > 1:
                        expected = sum(1 for s in scores if pf > s) / max(1, (len(scores) - 1))
                        if win is not None:
                            luck_raw = (win - expected)

                    prev = prev_starters_by_team.get(team, set())
                    turnover = len(set(starters).symmetric_difference(prev)) if prev else None
                    prev_starters_by_team[team] = set(starters)

                    starter_points = [ppts.get(pid, 0.0) for pid in starters]
                    donuts = sum(1 for x in starter_points if float(x) == 0.0)
                    under10 = sum(1 for x in starter_points if float(x) < 10.0)
                    over20 = sum(1 for x in starter_points if float(x) > 20.0)
                    over30 = sum(1 for x in starter_points if float(x) > 30.0)
                    over40 = sum(1 for x in starter_points if float(x) > 40.0)
                    over50 = sum(1 for x in starter_points if float(x) > 50.0)
                    diff_hi_lo = (max(starter_points) - min(starter_points)) if starter_points else None

                    def count_pos(pids, pos):
                        return sum(1 for pid in pids if (pid_pos.get(pid) or "") == pos)

                    qb_s, rb_s, wr_s, te_s = count_pos(starters, "QB"), count_pos(starters, "RB"), count_pos(starters, "WR"), count_pos(starters, "TE")
                    qb_r, rb_r, wr_r, te_r = count_pos(players, "QB"), count_pos(players, "RB"), count_pos(players, "WR"), count_pos(players, "TE")

                    rook_s = sum(1 for pid in starters if str(pid_meta.get(pid, {}).get("years_exp")) in ("0", "0.0"))
                    rook_r = sum(1 for pid in players if str(pid_meta.get(pid, {}).get("years_exp")) in ("0", "0.0"))

                    approx_date = date(season, 9, 1) + timedelta(days=7 * (wk - 1))
                    ages = [a for a in (_calc_age(pid_meta.get(pid, {}).get("birth_date"), approx_date) for pid in players) if a is not None]
                    avg_age = round(sum(ages) / len(ages), 2) if ages else None

                    roster_nfl_teams = [pid_meta.get(pid, {}).get("team") for pid in players if pid_meta.get(pid, {}).get("team")]
                    start_nfl_teams = [pid_meta.get(pid, {}).get("team") for pid in starters if pid_meta.get(pid, {}).get("team")]
                    most_start_same = max(Counter(start_nfl_teams).values()) if start_nfl_teams else None
                    most_roster_same = max(Counter(roster_nfl_teams).values()) if roster_nfl_teams else None
                    most_start_team = Counter(start_nfl_teams).most_common(1)[0][0] if start_nfl_teams else None
                    most_roster_team = Counter(roster_nfl_teams).most_common(1)[0][0] if roster_nfl_teams else None

                    def max_same_team_by_pos(pids, pos):
                        teams = [
                            pid_meta.get(pid, {}).get("team")
                            for pid in pids
                            if (pid_pos.get(pid) or "").upper() == pos and pid_meta.get(pid, {}).get("team")
                        ]
                        return max(Counter(teams).values()) if teams else None

                    # Opponent label per playoffs spec
                    opp_label = opp_team
                    label = stage_label_map.get((season, wk, rid))
                    if label:
                        opp_label = label

                    team_week_rows.append({
                        "Team": team,
                        "Week": wk,
                        "Year": season,
                        "PF": round(pf, 2),
                        "Win?": win,
                        "Opponent": opp_label,
                        "Points against": round(float(opp_points), 2) if opp_points is not None else None,
                        "Margin": round(float(margin), 2) if margin is not None else None,
                        "Max PF": round(max_pf, 2) if max_pf is not None else None,
                        "Efficiency": round(eff, 4) if eff is not None else None,
                        "Number of Injuries": None,         # computed later from player_week
                        "Number of suspensions": None,      # computed later from player_week
                        "Number of players on bye": None,   # computed later from player_week
                        "Largest deficit overcome (if win)": None,
                        "Starter turnover from previous week": turnover,
                        "Difference in pregame avg max PF from opponent": None,  # computed later
                        "UPST": None,                      # computed later
                        "Hardship": None,                  # computed later
                        "Tanking": None,                   # computed later (needs pick ledger; best effort later)
                        "Luck": round(luck_raw, 4) if luck_raw is not None else None,
                        "Brosenzweig": None,
                        "Sisenzweig": None,
                        "Number of donuts": donuts,
                        "Number of players under 10": under10,
                        "Number of players over 20": over20,
                        "Number of players over 30": over30,
                        "Number of players over 40": over40,
                        "Number of players over 50": over50,
                        "Number of QB started": qb_s,
                        "Number of WR started": wr_s,
                        "Number of RB started": rb_s,
                        "Number of TE started": te_s,
                        "Number of QB rostered": qb_r,
                        "Number of WR rostered": wr_r,
                        "Number of RB rostered": rb_r,
                        "Number of TE rostered": te_r,
                        "Number of transactions": int(tx_count.get(team, 0)),
                        "Number of trades": int(trade_count.get(team, 0)),
                        "Amount of FAAB spent": round(float(faab_spent.get(team, 0.0)), 2),
                        "Most number of players started from same NFL team": most_start_same,
                        "Most number of players started from same NFL team (team)": most_start_team,
                        "Most number of players rostered from same NFL team": most_roster_same,
                        "Most number of players rostered from same NFL team (team)": most_roster_team,
                        "Most number of QBs started from same NFL team": max_same_team_by_pos(starters, "QB"),
                        "Most number of QBs rostered from same NFL team": max_same_team_by_pos(players, "QB"),
                        "Most number of RBs started from same NFL team": max_same_team_by_pos(starters, "RB"),
                        "Most number of RBs rostered from same NFL team": max_same_team_by_pos(players, "RB"),
                        "Most number of WR started from same NFL team": max_same_team_by_pos(starters, "WR"),
                        "Most number of WR rostered from same NFL team": max_same_team_by_pos(players, "WR"),
                        "Most number of TE started from same NFL team": max_same_team_by_pos(starters, "TE"),
                        "Most number of TE rostered from same NFL team": max_same_team_by_pos(players, "TE"),
                        "Number of NFL teams among starting players": len(set(start_nfl_teams)) if start_nfl_teams else None,
                        "Number of NFL teams amoung rostered players": len(set(roster_nfl_teams)) if roster_nfl_teams else None,
                        "Number of rookies started": rook_s,
                        "Number of rookies rostered": rook_r,
                        "Player average age": avg_age,
                        "Difference between highest and lowest starters": round(diff_hi_lo, 2) if diff_hi_lo is not None else None,
                        "Combined matchup score": round(pf + opp_points, 2) if opp_points is not None else None,
                        "Win streak": None,
                        "Loss streak": None,
                        "Win streak counting previous season": None,
                        "Loss streak counting previous season": None,
                        "Top half of league?": None,
                        "Highest score?": None,
                        "Lowest score?": None,
                        "Narrowest victory?": None,
                        "Largest blowout?": None,
                        "Most efficient?": None,
                        "Least efficient?": None,
                        "Increase in points from previous week": None,
                        "Number of cuffs rostered": None,
                        "Number of cuffs started": None,
                        "Future draft capital": None,
                        "Startup draft players remaining": None,
                        # leave remaining plan columns to enforcement step
                    })

                    # starter slot labels are not provided reliably by Sleeper; we approximate by roster order
                    starter_slot = {}
                    # League has fixed slots; for this build we only need "Position started in" for analysis,
                    # so we store the player's NFL position as a stable proxy.
                    for pid in starters:
                        starter_slot[pid] = pid_pos.get(pid)

                    played_set = played_by_week.get(wk, set())

                    bench = [pid for pid in players if pid not in starters]
                    best_bench_pid = None
                    best_bench_pts = None
                    if bench:
                        best_bench_pid = max(bench, key=lambda pid: ppts.get(pid, 0.0))
                        best_bench_pts = float(ppts.get(best_bench_pid, 0.0))

                    worst_starter_pid = None
                    worst_starter_pts = None
                    if starters:
                        worst_starter_pid = min(starters, key=lambda pid: ppts.get(pid, 0.0))
                        worst_starter_pts = float(ppts.get(worst_starter_pid, 0.0))

                    for pid in players:
                        meta = pid_meta.get(pid, {})
                        full_name = meta.get("full_name") or pid
                        nfl_team = meta.get("team")
                        pts = float(ppts.get(pid, 0.0))
                        started = pid in starters
                        slot = starter_slot.get(pid) if started else (pid_pos.get(pid) or None)

                        # gsis id lookup for nflverse
                        gsis = None
                        if not dp_ids.empty and "sleeper_id" in dp_ids.columns and "gsis_id" in dp_ids.columns:
                            try:
                                match = dp_ids.loc[dp_ids["sleeper_id"].astype(str) == pid]
                                if not match.empty:
                                    gsis = str(match["gsis_id"].iloc[0])
                            except Exception:
                                gsis = None

                        # Flags (platform primary, nflverse secondary)
                        f1 = _infer_flags_from_sleeper_player_meta(meta)
                        f2 = _infer_flags_from_nflverse(injuries, gsis, season, wk)
                        inj, susp = _merge_flags(f1, f2)

                        # Bye is schedule-based. If player scored >0 -> not a bye.
                        bye = None
                        if nfl_team and played_set:
                            bye = (_norm_team(nfl_team) not in played_set)
                        if pts > 0:
                            bye = False
                            inj = False
                            susp = False

                        if inj is None:
                            inj = False
                        if susp is None:
                            susp = False
                        if bye is None:
                            bye = False

                        rookie = str(meta.get("years_exp")) in ("0", "0.0")
                        age = _calc_age(meta.get("birth_date"), approx_date)

                        diff_best_bench = (pts - best_bench_pts) if (started and best_bench_pts is not None) else None
                        diff_worst_starter = (pts - worst_starter_pts) if ((not started) and worst_starter_pts is not None) else None
                        ref_player = None
                        if started and best_bench_pid:
                            ref_player = pid_meta.get(best_bench_pid, {}).get("full_name") or best_bench_pid
                        elif (not started) and worst_starter_pid:
                            ref_player = pid_meta.get(worst_starter_pid, {}).get("full_name") or worst_starter_pid

                        rookie = str(meta.get("years_exp")) in ("0", "0.0")
                        age = _calc_age(meta.get("birth_date"), approx_date)

                        diff_best_bench = (pts - best_bench_pts) if (started and best_bench_pts is not None) else None
                        diff_worst_starter = (pts - worst_starter_pts) if ((not started) and worst_starter_pts is not None) else None
                        ref_player = None
                        if started and best_bench_pid:
                            ref_player = pid_meta.get(best_bench_pid, {}).get("full_name") or best_bench_pid
                        elif (not started) and worst_starter_pid:
                            ref_player = pid_meta.get(worst_starter_pid, {}).get("full_name") or worst_starter_pid

                        player_week_rows.append({
                            "Player": full_name,
                            "Team": team,
                            "Week": wk,
                            "Year": season,
                            "Points": round(pts, 2),
                            "Injury?": bool(inj),
                            "Suspension?": bool(susp),
                            "Bye?": bool(bye),
                            "Starter/Bench": "Starter" if started else "Bench",
                            "% of points (if starter)": round(pts / pf, 4) if started and pf else None,
                            "Position started in (if starter)": slot,
                            "Change from previous week": None,
                            "Change from previous 5 weeks avg": None,
                            "Change from career average to that point": None,
                            "Change from overall career average": None,
                            "Number of weeks on team": None,
                            "Number of consecutive weeks on bench before start (if starter)": None,
                            "Number of consecutive weeks on bench before start excluding injury/bye (if starter)": None,
                            "Total weeks as team starter to that point": None,
                            "Total weeks on bench to that point": None,
                            "Total weeks as team starter on that team this season": None,
                            "Total weeks on bench on that team this season": None,
                            "- Activated Cuff? (Was a player of the same nfl team/position & who averages >10 PPG more over last 5 played games injured? Only for players with avg <10 PPG)": 0,
                            "Difference from best startable bench (if starter)": round(diff_best_bench, 2) if diff_best_bench is not None else None,
                            "Difference from worst benchable starter (if bench)": round(diff_worst_starter, 2) if diff_worst_starter is not None else None,
                            "Reference player name": ref_player,
                            "Difference in averages of best/worst startables over previous 5 games": None,
                            "Cuff adjusted difference": None,
                            "Rookie?": 1 if rookie else 0,
                            "Age": age,
                            "NFL team": nfl_team,
                            # award flags (filled later)
                            "Player of the week?": None,
                            "QB of the week?": None,
                            "RB of the week?": None,
                            "WR of the week?": None,
                            "TE of the week?": None,
                            "Benchwarmer of the week?": None,
                            "Bench QB of the week?": None,
                            "Bench RB of the week?": None,
                            "Bench WR of the week?": None,
                            "Bench TE of the week?": None,
                            "Highest starter on team?": None,
                            "Lowest starter on team?": None,
                        })

                        # store for awards later
                        awards_weekly[(season, wk)].append((pid, team, pts, started, pid_pos.get(pid) or ""))

                except Exception as e:
                    _log_exc(debug, f"team_player_rows_{season}_wk{wk}", e)

            # Transactions rows (non-trade) + trades ledger
            for t in tx_by_week.get(wk, []):
                try:
                    ttype = t.get("type")
                    created_date = _epoch_ms_to_date(t.get("created"))
                    created_dt = _epoch_ms_to_dt(t.get("created"))
                    creator = str(t.get("creator") or "")
                    team = user_handle.get(creator) if creator else None

                    # Trades ledger (one row per involved team)
                    if ttype == "trade":
                        roster_ids = t.get("roster_ids") or []
                        if not isinstance(roster_ids, list):
                            roster_ids = []
                        roster_ids_int = [int(x) for x in roster_ids if _to_int(x, None) is not None]
                        adds = t.get("adds") or {}
                        if not isinstance(adds, dict):
                            adds = {}
                        draft_picks = t.get("draft_picks") or []
                        if not isinstance(draft_picks, list):
                            draft_picks = []

                        # received assets by team
                        recv_players: Dict[int, List[str]] = defaultdict(list)
                        for pid, rrid in adds.items():
                            rr = _to_int(rrid, None)
                            if rr is None:
                                continue
                            recv_players[rr].append(pid_meta.get(str(pid), {}).get("full_name") or str(pid))

                        recv_picks: Dict[int, List[str]] = defaultdict(list)
                        for dp in draft_picks:
                            if not isinstance(dp, dict):
                                continue
                            owner_id = _to_int(dp.get("owner_id"), None)
                            if owner_id is None:
                                continue
                            recv_picks[owner_id].append(f"{dp.get('season')} R{dp.get('round')}")

                        # Build row per roster in roster_ids_int
                        for rid in roster_ids_int:
                            tm = roster_to_team.get(rid, f"Roster {rid}")
                            others = [roster_to_team.get(o, f"Roster {o}") for o in roster_ids_int if o != rid]
                            received = []
                            received.extend(recv_players.get(rid, []))
                            received.extend(recv_picks.get(rid, []))
                            dropped = []
                            for o in roster_ids_int:
                                if o == rid:
                                    continue
                                dropped.extend(recv_players.get(o, []))
                                dropped.extend(recv_picks.get(o, []))
                            trades_rows.append({
                                "Team": tm,
                                "Team's traded with": "; ".join(sorted(set([x for x in others if x]))),
                                "Assets recieved": "; ".join(received) if received else None,
                                "Assets dropped": "; ".join(dropped) if dropped else None,
                                "Date": created_dt.isoformat() if created_dt else (str(created_date) if created_date else None),
                                # KTC/Oliver columns stay blank by design for now
                                "KTC value difference at deal time": None,
                                "KTC value difference at end of season": None,
                                "KTC value difference 1 year later": None,
                                "KTC value difference 2 years later": None,
                                "Oliver value difference at deal time": None,
                                "Oliver value difference at end of season": None,
                                "Oliver value difference 1 year later": None,
                                "Oliver value difference 2 years later": None,
                                "Pick value recieved": None,
                                "Change in pick value at draft time": None,
                                "Assets retained now": None,
                                "Assets traded away": None,
                                "Return from trades": None,
                                "Additional assets traded away in those deals": None,
                                "Return from trades of trades...of trades. Keep going until present day": None,
                                "Asset difference in average age": None,
                                "Tanking before": None,
                                "Tanking after": None,
                                "Link to next transaction": None,
                                "Link to previous transaction": None,
                            })

                        continue  # don't add to transactions.csv

                    # Non-trade transactions
                    if ttype not in ("waiver", "free_agent", "commissioner"):
                        # keep but label if unknown
                        pass

                    adds = t.get("adds") or {}
                    drops = t.get("drops") or {}
                    meta = t.get("metadata") or {}
                    faab = meta.get("waiver_bid") if isinstance(meta, dict) else None
                    num_bids = meta.get("num_bids") if isinstance(meta, dict) else None

                    if not isinstance(adds, dict):
                        adds = {}
                    if not isinstance(drops, dict):
                        drops = {}

                    for pid, rrid in adds.items():
                        pid = str(pid)
                        dropped = None
                        for dp, drid in drops.items():
                            if str(drid) == str(rrid):
                                dropped = str(dp)
                                break

                        transactions_rows.append({
                            "Team": team,
                            "Player Added": pid_meta.get(pid, {}).get("full_name") or pid,
                            "Player Dropped": pid_meta.get(dropped, {}).get("full_name") if dropped else None,
                            "type of transaction (waiver/free agency)": ttype,
                            "Faab": faab,
                            "Date": created_dt.isoformat() if created_dt else (str(created_date) if created_date else None),
                            "Number of bids": num_bids,
                            "Link to next transaction": None,
                            "Link to previous transaction": None,
                            "Average PPG on team": None,
                            "Average PPG of dropped player over same time": None,
                            "Difference of averages": None,
                            "Difference of averages adjusted by position": None,
                            "Age difference": None,
                            "Player addition value": None,
                            "Cuff at time of pickup?": None,
                            "Weeks between pickup and start": None,
                            "Number of starts before next drop": None,
                            "% of starts made while rostered": None,
                            "Injury adjusted % of starts made while rostered": None,
                            "Date dropped/traded": None,
                            "Tanking before": None,
                            "Tanking after": None,
                            "Number of times picked up by this team": None,
                        })
                except Exception as e:
                    _log_exc(debug, f"transactions_trades_rows_{season}_wk{wk}", e)

    # --------------------------
    # Convert to DataFrames
    # --------------------------
    pw = pd.DataFrame(player_week_rows)
    log_df(pw, 'player_week', sample_cols=['Points','Injury?','Suspension?','Bye?','Starter?'])
    tw = pd.DataFrame(team_week_rows)
    if not tw.empty:
        log_missing_cols(tw, "team_week", [
            "Season", "Week", "Team", "PF", "PA", "Margin", "Max PF", "Efficiency"
        ])
        zero_max = int((pd.to_numeric(tw.get("Max PF"), errors="coerce").fillna(0) <= 0).sum())
        LOG.info("team_week: rows=%s zero_max_pf=%s", len(tw), zero_max)
    log_df(tw, 'team_week', sample_cols=['PF','Max PF','Efficiency'])
    tx = pd.DataFrame(transactions_rows)
    tr = pd.DataFrame(trades_rows)
    ph = pd.DataFrame(pick_rows)

    # --------------------------
    # Player-week derived columns (deltas, tenure, awards) + Hardship
    # --------------------------
    if not pw.empty:
        pw["Year"] = pd.to_numeric(pw["Year"], errors="coerce").astype("Int64")
        pw["Week"] = pd.to_numeric(pw["Week"], errors="coerce").astype("Int64")
        pw["Points"] = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)

        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)

        active = ~pw[["Injury?", "Suspension?", "Bye?"]].fillna(False).any(axis=1)

        # Change from previous active week (bench weeks count if active)
        last_active_pts: Dict[str, float] = {}
        out_prev = []
        for i, row in pw.iterrows():
            k = row["Player"]
            out_prev.append((float(row["Points"]) - last_active_pts[k]) if k in last_active_pts else None)
            if bool(active.iloc[i]):
                last_active_pts[k] = float(row["Points"])
        pw["Change from previous week"] = out_prev

        # Previous 5 active weeks avg (spans seasons)
        windows: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5))
        out_prev5 = []
        for i, row in pw.iterrows():
            k = row["Player"]
            q = windows[k]
            out_prev5.append((float(row["Points"]) - (sum(q) / 5)) if len(q) == 5 else None)
            if bool(active.iloc[i]):
                q.append(float(row["Points"]))
        pw["Change from previous 5 weeks avg"] = out_prev5

        # Career avg to that point (active weeks only)
        sums: Dict[str, float] = defaultdict(float)
        counts: Dict[str, int] = defaultdict(int)
        out_cavg = []
        for i, row in pw.iterrows():
            k = row["Player"]
            out_cavg.append((float(row["Points"]) - (sums[k] / counts[k])) if counts[k] > 0 else None)
            if bool(active.iloc[i]):
                sums[k] += float(row["Points"])
                counts[k] += 1
        pw["Change from career average to that point"] = out_cavg

        # Overall career avg (active weeks only)
        try:
            full_avg = pw.loc[active].groupby("Player")["Points"].mean()
            pw["Change from overall career average"] = pw["Points"] - pw["Player"].map(full_avg)
        except Exception as e:
            _log_exc(repo_root / "exports/raw/build_debug.log", "overall_career_avg", e)
            pw["Change from overall career average"] = None

        # Team tenure + bench streaks (bench streak spans seasons)
        pw = pw.sort_values(["Team", "Player", "Year", "Week"]).reset_index(drop=True)
        stats: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for i, row in pw.iterrows():
            key = (str(row["Team"]), str(row["Player"]))
            st = stats.get(key, {
                "weeks": 0,
                "start_all": 0,
                "bench_all": 0,
                "season": None,
                "start_season": 0,
                "bench_season": 0,
                "bench_streak": 0,
                "bench_streak_ex": 0
            })

            if st["season"] != row["Year"]:
                st["season"] = row["Year"]
                st["start_season"] = 0
                st["bench_season"] = 0

            st["weeks"] += 1
            is_starter = (row["Starter/Bench"] == "Starter")
            inactive = bool((row.get("Injury?") or False) or (row.get("Suspension?") or False) or (row.get("Bye?") or False))

            if is_starter:
                pw.at[i, "Number of consecutive weeks on bench before start (if starter)"] = st["bench_streak"]
                pw.at[i, "Number of consecutive weeks on bench before start excluding injury/bye (if starter)"] = st["bench_streak_ex"]
                st["bench_streak"] = 0
                st["bench_streak_ex"] = 0
                st["start_all"] += 1
                st["start_season"] += 1
            else:
                st["bench_all"] += 1
                st["bench_season"] += 1
                st["bench_streak"] += 1
                if not inactive:
                    st["bench_streak_ex"] += 1

            pw.at[i, "Number of weeks on team"] = st["weeks"]
            pw.at[i, "Total weeks as team starter to that point"] = st["start_all"]
            pw.at[i, "Total weeks on bench to that point"] = st["bench_all"]
            pw.at[i, "Total weeks as team starter on that team this season"] = st["start_season"]
            pw.at[i, "Total weeks on bench on that team this season"] = st["bench_season"]

            stats[key] = st

        # Awards (league + team). Ties -> all winners.
        # We compute off pw itself to avoid any mismatched ids.
        pw = pw.sort_values(["Year", "Week", "Team", "Player"]).reset_index(drop=True)

        award_cols = [
            "Player of the week?",
            "QB of the week?",
            "RB of the week?",
            "WR of the week?",
            "TE of the week?",
            "Benchwarmer of the week?",
            "Bench QB of the week?",
            "Bench RB of the week?",
            "Bench WR of the week?",
            "Bench TE of the week?",
            "Highest starter on team?",
            "Lowest starter on team?",
        ]

        def _set_flag(mask, col):
            pw.loc[mask, col] = 1
            pw.loc[~mask, col] = pw.loc[~mask, col].fillna(0)

        # league-level player of week among starters
        starters = pw["Starter/Bench"] == "Starter"
        for (yr, wk), g in pw.groupby(["Year", "Week"]):
            sg = g[starters.loc[g.index]]
            if sg.empty:
                continue
            mx = sg["Points"].max()
            mn = sg["Points"].min()
            _set_flag((pw["Year"] == yr) & (pw["Week"] == wk) & starters & (pw["Points"] == mx), "Player of the week?")
            _set_flag((pw["Year"] == yr) & (pw["Week"] == wk) & starters & (pw["Points"] == mn), "Benchwarmer of the week?")

            for pos, col in [("QB", "QB of the week?"), ("RB", "RB of the week?"), ("WR", "WR of the week?"), ("TE", "TE of the week?")]:
                pg = sg[sg["Position started in (if starter)"].astype(str).str.upper() == pos]
                if pg.empty:
                    continue
                mxp = pg["Points"].max()
                _set_flag(
                    (pw["Year"] == yr)
                    & (pw["Week"] == wk)
                    & starters
                    & (pw["Position started in (if starter)"].astype(str).str.upper() == pos)
                    & (pw["Points"] == mxp),
                    col,
                )

            # bench position awards (bench only)
            bg = g[~starters.loc[g.index]]
            for pos, col in [
                ("QB", "Bench QB of the week?"),
                ("RB", "Bench RB of the week?"),
                ("WR", "Bench WR of the week?"),
                ("TE", "Bench TE of the week?"),
            ]:
                pg = bg[bg["Position started in (if starter)"].astype(str).str.upper() == pos]
                if pg.empty:
                    continue
                mxp = pg["Points"].max()
                _set_flag(
                    (pw["Year"] == yr)
                    & (pw["Week"] == wk)
                    & (~starters)
                    & (pw["Position started in (if starter)"].astype(str).str.upper() == pos)
                    & (pw["Points"] == mxp),
                    col,
                )

            # team-level awards: highest/lowest starter per team per week
            for team, tg in sg.groupby("Team"):
                mx_t = tg["Points"].max()
                mn_t = tg["Points"].min()
                _set_flag(
                    (pw["Year"] == yr)
                    & (pw["Week"] == wk)
                    & (pw["Team"] == team)
                    & starters
                    & (pw["Points"] == mx_t),
                    "Highest starter on team?",
                )
                _set_flag(
                    (pw["Year"] == yr)
                    & (pw["Week"] == wk)
                    & (pw["Team"] == team)
                    & starters
                    & (pw["Points"] == mn_t),
                    "Lowest starter on team?",
                )

        pw[award_cols] = pw[award_cols].fillna(0)

        # Hardship engine per your definition
        # points lost when: Points==0 AND (Injury or Suspension) AND not Bye,
        # expected points = avg of last 5 HEALTHY games (points>0 and not Inj/Susp/Bye).
        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)
        last5: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5))
        exp_points: List[Optional[float]] = [None] * len(pw)
        points_lost: List[float] = [0.0] * len(pw)
        for i, row in pw.iterrows():
            player = row["Player"]
            pts = float(row["Points"])
            inj = bool(row.get("Injury?") or False)
            susp = bool(row.get("Suspension?") or False)
            bye = bool(row.get("Bye?") or False)
            hist = last5[player]
            expected = (sum(hist) / len(hist)) if len(hist) > 0 else None
            exp_points[i] = expected
            missed = (pts == 0.0) and (inj or susp) and (not bye)
            points_lost[i] = float(expected) if (missed and expected is not None) else 0.0
            if (pts > 0.0) and (not inj) and (not susp) and (not bye):
                hist.append(pts)
        pw["_expected_points_if_healthy"] = exp_points
        pw["_points_lost_inj_susp"] = points_lost

    # --------------------------
    # Recompute team-week injury/susp/bye counts and hardship from player-week
    # --------------------------
    if not tw.empty and not pw.empty:
        pw2 = pw.copy()
        pw2["Injury?"] = pw2["Injury?"].fillna(False).astype(bool)
        pw2["Suspension?"] = pw2["Suspension?"].fillna(False).astype(bool)
        pw2["Bye?"] = pw2["Bye?"].fillna(False).astype(bool)
        pw2["Points"] = pd.to_numeric(pw2["Points"], errors="coerce").fillna(0.0)

        pw2["_missed_injury"] = (pw2["Injury?"] & (~pw2["Bye?"]) & (pw2["Points"] == 0)).astype(int)
        pw2["_missed_susp"] = (pw2["Suspension?"] & (~pw2["Bye?"]) & (pw2["Points"] == 0)).astype(int)
        pw2["_on_bye"] = (pw2["Bye?"] & (pw2["Points"] == 0)).astype(int)

        pw2["Starter?"] = (pw2["Starter/Bench"] == "Starter").astype(int)
        pw2["Number_of_players_injured_or_suspended"] = pw2["_missed_injury"] + pw2["_missed_susp"]

        agg = pw2.groupby(["Team", "Year", "Week"], as_index=False).agg(
            Hardship_Points_Lost=("_points_lost_inj_susp", "sum"),
            Number_of_Injuries=("_missed_injury", "sum"),
            Number_of_suspensions=("_missed_susp", "sum"),
            Number_of_players_on_bye=("_on_bye", "sum"),
            Number_of_players_injured_or_suspended=("Number_of_players_injured_or_suspended", "sum"),
            Starter_Count=("Starter?", "sum"),
        )

        tw = tw.merge(agg, how="left", on=["Team", "Year", "Week"])
        # Harden numeric outputs + create friendly display columns (never crash on missing cols)
        for _c in [
            "Hardship_Points_Lost",
            "Number_of_Injuries",
            "Number_of_suspensions",
            "Number_of_players_injured_or_suspended",
            "Number_of_players_on_bye",
            "Starter_Count",
        ]:
            safe_to_numeric(tw, _c, default=0.0)

        tw["Hardship"] = tw.apply(
            lambda r: safe_div(
                r["Number_of_Injuries"] + r["Number_of_suspensions"] + r["Number_of_players_on_bye"],
                r["Starter_Count"],
                default=0.0,
            ),
            axis=1,
        )
        tw["Number of Injuries"] = tw["Number_of_Injuries"].round(0).astype(int)
        tw["Number of suspensions"] = tw["Number_of_suspensions"].round(0).astype(int)
        tw["Number of players on bye"] = tw["Number_of_players_on_bye"].round(0).astype(int)

        tw.drop(columns=[
            "Hardship_Points_Lost",
            "Number_of_Injuries",
            "Number_of_suspensions",
            "Number_of_players_injured_or_suspended",
            "Number_of_players_on_bye",
            "Starter_Count",
        ], inplace=True, errors="ignore")

        # UPST: win with lower Max PF than opponent
        if "UPST" not in tw.columns:
            tw["UPST"] = None
        for (yr, wk), g in tw.groupby(["Year", "Week"]):
            g2 = g.copy()
            g2["PF"] = pd.to_numeric(g2["PF"], errors="coerce").fillna(0.0)
            g2["Points against"] = pd.to_numeric(g2["Points against"], errors="coerce").fillna(0.0)
            g2["Max PF"] = pd.to_numeric(g2["Max PF"], errors="coerce")
            for idx, row in g2.iterrows():
                opp = g2[(g2["PF"] == row["Points against"]) & (g2["Points against"] == row["PF"])]
                if len(opp) == 1:
                    opp_max = opp.iloc[0]["Max PF"]
                    if row["Win?"] == 1 and pd.notna(row["Max PF"]) and pd.notna(opp_max):
                        tw.loc[idx, "UPST"] = int(float(row["Max PF"]) < float(opp_max))
                    else:
                        tw.loc[idx, "UPST"] = 0
                else:
                    tw.loc[idx, "UPST"] = 0

        # Brosenzweig / Sisenzweig per README definition
        tw["Brosenzweig"] = ((tw["UPST"] == 1) & (tw["Hardship"] > 0)).astype(int)
        tw["Sisenzweig"] = ((tw["UPST"] != 1) & (tw["Hardship"] > 0) & (tw["Win?"] == 1)).astype(int)

    # --------------------------
    # Derived team-week columns: pregame avg maxPF diff
    # --------------------------
    if not tw.empty:
        tw["Difference in pregame avg max PF from opponent"] = None
        # build helper: map (Team,Year,Week) -> rid via raw opponent map is not kept, so approximate by using Opponent is label sometimes.
        # We'll compute using team-week history by team: avg MaxPF prior to this week in same season.
        tw = tw.sort_values(["Team", "Year", "Week"]).reset_index(drop=True)
        tw["Max PF"] = pd.to_numeric(tw["Max PF"], errors="coerce")
        # opponent avg maxPF requires opponent team identity; we can't recover from Opponent column in playoffs, so
        # compute against raw points map not in output. We'll approximate using the opponent points against mapping:
        # if Points against is present we can match to unique opponent that week by that score (in 8-team that's safe enough).
        for (yr, wk), g in tw.groupby(["Year", "Week"]):
            # build mapping by (Points against, PF) pair is ambiguous; fallback by symmetric join on Margin
            pass  # leave None if ambiguous (rare)
        # At minimum, compute own pregame avg maxPF, and set diff = own - league avg as a proxy when opponent unknown.
        # This prevents blanks and stays interpretable.
        tw["Pregame avg MaxPF (proxy)"] = None
        for (team, yr), g in tw.groupby(["Team", "Year"]):
            g = g.sort_values("Week")
            maxpfs = []
            for idx, row in g.iterrows():
                pre = (sum(maxpfs) / len(maxpfs)) if maxpfs else None
                tw.loc[idx, "Pregame avg MaxPF (proxy)"] = round(pre, 2) if pre is not None else None
                if not pd.isna(row["Max PF"]):
                    maxpfs.append(float(row["Max PF"]))
        # league avg pregame
        tw["Difference in pregame avg max PF from opponent"] = None
        for (yr, wk), g in tw.groupby(["Year", "Week"]):
            vals = pd.to_numeric(g["Pregame avg MaxPF (proxy)"], errors="coerce").dropna()
            lg_avg = float(vals.mean()) if len(vals) else None
            if lg_avg is None:
                continue
            for idx in g.index:
                v = tw.loc[idx, "Pregame avg MaxPF (proxy)"]
                if v is not None and not pd.isna(v):
                    tw.loc[idx, "Difference in pregame avg max PF from opponent"] = round(float(v) - lg_avg, 2)

    # --------------------------
    # Team-week flags & streaks
    # --------------------------
    if not tw.empty:
        tw["Increase in points from previous week"] = None
        tw["Highest score?"] = 0
        tw["Lowest score?"] = 0
        tw["Narrowest victory?"] = 0
        tw["Largest blowout?"] = 0
        tw["Most efficient?"] = 0
        tw["Least efficient?"] = 0
        tw["Top half of league?"] = 0

        for (yr, wk), g in tw.groupby(["Year", "Week"]):
            g2 = g.copy()
            g2["PF"] = pd.to_numeric(g2["PF"], errors="coerce").fillna(0.0)
            g2["Margin"] = pd.to_numeric(g2["Margin"], errors="coerce")
            g2["Efficiency"] = pd.to_numeric(g2["Efficiency"], errors="coerce")
            if not g2.empty:
                max_pf = g2["PF"].max()
                min_pf = g2["PF"].min()
                tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["PF"] == max_pf), "Highest score?"] = 1
                tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["PF"] == min_pf), "Lowest score?"] = 1

                # narrowest victory (smallest positive margin)
                wins = g2[g2["Margin"] > 0]
                if not wins.empty:
                    min_margin = wins["Margin"].min()
                    tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["Margin"] == min_margin), "Narrowest victory?"] = 1
                    max_margin = wins["Margin"].max()
                    tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["Margin"] == max_margin), "Largest blowout?"] = 1

                # efficiency
                if g2["Efficiency"].notna().any():
                    max_eff = g2["Efficiency"].max()
                    min_eff = g2["Efficiency"].min()
                    tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["Efficiency"] == max_eff), "Most efficient?"] = 1
                    tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["Efficiency"] == min_eff), "Least efficient?"] = 1

                # top half of league by PF
                median_pf = g2["PF"].median()
                tw.loc[(tw["Year"] == yr) & (tw["Week"] == wk) & (tw["PF"] >= median_pf), "Top half of league?"] = 1

        # streaks + increase from previous week
        tw = tw.sort_values(["Team", "Year", "Week"]).reset_index(drop=True)
        tw["Win streak"] = 0
        tw["Loss streak"] = 0
        tw["Win streak counting previous season"] = 0
        tw["Loss streak counting previous season"] = 0
        for team, g in tw.groupby("Team"):
            win_streak = loss_streak = 0
            win_streak_season = loss_streak_season = 0
            current_year = None
            prev_pf_by_year = {}
            for idx, row in g.sort_values(["Year", "Week"]).iterrows():
                if current_year != row["Year"]:
                    current_year = row["Year"]
                    win_streak_season = 0
                    loss_streak_season = 0
                result = row.get("Win?")
                if result == 1:
                    win_streak_season += 1
                    loss_streak_season = 0
                    win_streak += 1
                    loss_streak = 0
                elif result == 0:
                    loss_streak_season += 1
                    win_streak_season = 0
                    loss_streak += 1
                    win_streak = 0
                else:
                    win_streak_season = 0
                    loss_streak_season = 0
                    win_streak = 0
                    loss_streak = 0

                tw.loc[idx, "Win streak"] = win_streak_season
                tw.loc[idx, "Loss streak"] = loss_streak_season
                tw.loc[idx, "Win streak counting previous season"] = win_streak
                tw.loc[idx, "Loss streak counting previous season"] = loss_streak

                prev_pf = prev_pf_by_year.get(row["Year"])
                if prev_pf is not None and pd.notna(row["PF"]):
                    tw.loc[idx, "Increase in points from previous week"] = round(float(row["PF"]) - float(prev_pf), 2)
                prev_pf_by_year[row["Year"]] = row["PF"]

    # --------------------------
    # Rollups: player_year/all_time, team_year/all_time, league_week/year/all_time
    # --------------------------
    player_year = pd.DataFrame()
    player_all = pd.DataFrame()
    if not pw.empty:
        pw_work = pw.copy()
        pw_work["Points"] = pd.to_numeric(pw_work["Points"], errors="coerce").fillna(0.0)
        pw_work["Missed_injury"] = (pw_work["Injury?"].fillna(False) & (pw_work["Points"] == 0)).astype(int)
        pw_work["Missed_suspension"] = (pw_work["Suspension?"].fillna(False) & (pw_work["Points"] == 0)).astype(int)
        pw_work["Starter?"] = (pw_work["Starter/Bench"] == "Starter").astype(int)

        award_cols = [
            "Player of the week?",
            "QB of the week?",
            "RB of the week?",
            "WR of the week?",
            "TE of the week?",
            "Benchwarmer of the week?",
            "Bench QB of the week?",
            "Bench RB of the week?",
            "Bench WR of the week?",
            "Bench TE of the week?",
            "Highest starter on team?",
            "Lowest starter on team?",
        ]

        pw_work[award_cols] = pw_work[award_cols].fillna(0)

        team_points = pw_work.groupby(["Player", "Year", "Team"], as_index=False)["Points"].sum()
        top_team = (
            team_points.sort_values(["Player", "Year", "Points"], ascending=[True, True, False])
            .drop_duplicates(["Player", "Year"])
            .rename(columns={"Team": "Top Team", "Points": "Top Team Points"})
        )
        last_team = (
            pw_work.sort_values(["Player", "Year", "Week"])
            .groupby(["Player", "Year"])
            .tail(1)[["Player", "Year", "Team"]]
            .rename(columns={"Team": "Last team"})
        )

        py_base = pw_work.groupby(["Player", "Year"], as_index=False).agg(
            Points=("Points", "sum"),
            Avg_points=("Points", "mean"),
            Weeks_missed_injury=("Missed_injury", "sum"),
            Weeks_missed_suspension=("Missed_suspension", "sum"),
            Weeks_as_starter=("Starter?", "sum"),
            Number_of_teams=("Team", "nunique"),
            Weeks=("Points", "count"),
            **{c: (c, "sum") for c in award_cols},
        )

        py = py_base.merge(top_team[["Player", "Year", "Top Team"]], on=["Player", "Year"], how="left")
        py = py.merge(last_team, on=["Player", "Year"], how="left")

        team_points_all = pw_work.groupby(["Player", "Year", "Team"])["Points"].sum()
        total_points = pw_work.groupby(["Player", "Year"])["Points"].sum()
        max_share = (team_points_all.groupby(["Player", "Year"]).max() / total_points).rename("% of points (highest team)")
        min_share = (team_points_all.groupby(["Player", "Year"]).min() / total_points).rename("% of points (lowest team)")
        py = py.merge(max_share.reset_index(), on=["Player", "Year"], how="left")
        py = py.merge(min_share.reset_index(), on=["Player", "Year"], how="left")

        py = py.sort_values(["Player", "Year"]).reset_index(drop=True)
        py["Change in points from previous season"] = py.groupby("Player")["Points"].diff()
        py["Change in avg points from previous season"] = py.groupby("Player")["Avg_points"].diff()

        py["Career_points_before"] = py.groupby("Player")["Points"].cumsum().shift(1)
        py["Career_years_before"] = py.groupby("Player").cumcount()
        py["Change in points from career"] = py.apply(
            lambda r: (r["Points"] - (r["Career_points_before"] / r["Career_years_before"]))
            if r["Career_years_before"] and r["Career_points_before"] is not None
            else None,
            axis=1,
        )

        py["Career_points_before_total"] = py.groupby("Player")["Points"].cumsum().shift(1)
        py["Career_weeks_before_total"] = py.groupby("Player")["Weeks"].cumsum().shift(1)
        py["Change in avg points from career"] = py.apply(
            lambda r: (r["Avg_points"] - (r["Career_points_before_total"] / r["Career_weeks_before_total"]))
            if r["Career_weeks_before_total"] and r["Career_points_before_total"] is not None
            else None,
            axis=1,
        )

        py = py.rename(
            columns={
                "Avg_points": "Avg points",
                "Weeks_missed_injury": "Weeks missed due to injury",
                "Weeks_missed_suspension": "Weeks missed due to suspension",
                "Weeks_as_starter": "Weeks as starter",
                "Number_of_teams": "Number of teams",
                "Top Team": "Top Team",
            }
        )

        py["Number of transactions"] = 0
        py["Number of trades"] = 0

        py = py.rename(
            columns={
                "Player of the week?": "Times as Player of the week?",
                "QB of the week?": "Times as QB of the week?",
                "RB of the week?": "Times as RB of the week?",
                "WR of the week?": "Times as WR of the week?",
                "TE of the week?": "Times as TE of the week?",
                "Benchwarmer of the week?": "Times as Benchwarmer of the week?",
                "Bench QB of the week?": "Times as Bench QB of the week?",
                "Bench RB of the week?": "Times as Bench RB of the week?",
                "Bench WR of the week?": "Times as Bench WR of the week?",
                "Bench TE of the week?": "Times as Bench TE of the week?",
                "Highest starter on team?": "Times as Highest starter on team?",
                "Lowest starter on team?": "Times as Lowest starter on team?",
            }
        )

        player_year = py

        pa = pw_work.groupby(["Player"], as_index=False).agg(
            Points=("Points", "sum"),
            Avg_points=("Points", "mean"),
            Weeks_missed_injury=("Missed_injury", "sum"),
            Weeks_missed_suspension=("Missed_suspension", "sum"),
            Weeks_as_starter=("Starter?", "sum"),
            Number_of_teams=("Team", "nunique"),
            **{c: (c, "sum") for c in award_cols},
        )

        top_team_all = (
            pw_work.groupby(["Player", "Team"], as_index=False)["Points"].sum()
            .sort_values(["Player", "Points"], ascending=[True, False])
            .drop_duplicates(["Player"])
            .rename(columns={"Team": "Top team", "Points": "Top team points"})
        )
        last_team_all = (
            pw_work.sort_values(["Year", "Week"])
            .groupby("Player")
            .tail(1)[["Player", "Team", "Rookie?", "Age"]]
            .rename(columns={"Team": "Last team"})
        )
        team_points_all_time = pw_work.groupby(["Player", "Team"])["Points"].sum()
        total_points_all_time = pw_work.groupby(["Player"])["Points"].sum()
        max_share_all = (team_points_all_time.groupby("Player").max() / total_points_all_time).rename("% of points (highest team)")
        min_share_all = (team_points_all_time.groupby("Player").min() / total_points_all_time).rename("% of points (lowest team)")

        pa = pa.merge(top_team_all[["Player", "Top team"]], on="Player", how="left")
        pa = pa.merge(last_team_all, on="Player", how="left")
        pa = pa.merge(max_share_all.reset_index(), on="Player", how="left")
        pa = pa.merge(min_share_all.reset_index(), on="Player", how="left")

        pa = pa.rename(
            columns={
                "Avg_points": "Avg points",
                "Weeks_missed_injury": "Weeks missed due to injury",
                "Weeks_missed_suspension": "Weeks missed due to suspension",
                "Weeks_as_starter": "Weeks as starter",
                "Number_of_teams": "Number of teams",
                "Player of the week?": "Times as Player of the week?",
                "QB of the week?": "Times as QB of the week?",
                "RB of the week?": "Times as RB of the week?",
                "WR of the week?": "Times as WR of the week?",
                "TE of the week?": "Times as TE of the week?",
                "Benchwarmer of the week?": "Times as Benchwarmer of the week?",
                "Bench QB of the week?": "Times as Bench QB of the week?",
                "Bench RB of the week?": "Times as Bench RB of the week?",
                "Bench WR of the week?": "Times as Bench WR of the week?",
                "Bench TE of the week?": "Times as Bench TE of the week?",
                "Highest starter on team?": "Times as Highest starter on team?",
                "Lowest starter on team?": "Times as Lowest starter on team?",
            }
        )

        pa["Number of transactions"] = 0
        pa["Number of trades"] = 0

        player_all = pa

    # Team-year: compute record and vs records using raw opp_rid_map (still available in closures above? not anymore)
    team_year = pd.DataFrame()
    team_all = pd.DataFrame()
    if not tw.empty:
        # reconstruct team list
        teams = sorted(tw["Team"].dropna().astype(str).unique().tolist())
        # compute per game outcomes using (Year,Week,Team) joined to opponent by points against and margin/Win?.
        # We'll approximate opponent team by pairing within each week using Points against symmetry.
        game_rows = []
        for (yr, wk), g in tw.groupby(["Year", "Week"]):
            # attempt to pair teams by matching points against
            g2 = g.copy()
            g2["PF"] = pd.to_numeric(g2["PF"], errors="coerce").fillna(0.0)
            g2["Points against"] = pd.to_numeric(g2["Points against"], errors="coerce").fillna(0.0)
            # naive: for each row, opponent is the row where PF == my Points against
            for idx, row in g2.iterrows():
                opp = None
                match = g2[g2["PF"] == row["Points against"]]
                if len(match) == 1:
                    opp = str(match.iloc[0]["Team"])
                elif len(match) > 1:
                    # disambiguate by requiring their points against == my PF
                    match2 = match[match["Points against"] == row["PF"]]
                    if len(match2) == 1:
                        opp = str(match2.iloc[0]["Team"])
                if opp:
                    game_rows.append({
                        "Year": int(yr),
                        "Week": int(wk),
                        "Team": str(row["Team"]),
                        "OppTeam": opp,
                        "Win?": row.get("Win?"),
                        "PF": float(row["PF"]),
                        "PA": float(row["Points against"]),
                    })
        games_df = pd.DataFrame(game_rows).drop_duplicates(subset=["Year","Week","Team"])

        def _record_str(w,l,t=0):
            return f"{int(w)}-{int(l)}" + (f"-{int(t)}" if t else "")

        # team-year rollup
        rows = []
        for (team, yr), g in tw.groupby(["Team", "Year"]):
            wins = int((g["Win?"] == 1).sum())
            losses = int((g["Win?"] == 0).sum())
            ties = int((g["Win?"] == 0.5).sum())
            gp = max(1, wins + losses + ties)
            pf = float(pd.to_numeric(g["PF"], errors="coerce").fillna(0.0).sum())
            pa = float(pd.to_numeric(g["Points against"], errors="coerce").fillna(0.0).sum())
            diff = pf - pa
            maxpf_sum = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).sum())
            maxpf_avg = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).mean())
            rec = _record_str(wins, losses, ties)
            winp = round((wins + 0.5 * ties) / gp, 4)
            record_vs = "N/A"
            if not games_df.empty:
                sub = games_df[(games_df["Team"] == str(team)) & (games_df["Year"] == int(yr))]
                pieces = []
                for opp in [t for t in teams if t != str(team)]:
                    sg = sub[sub["OppTeam"] == opp]
                    w = int((sg["Win?"] == 1).sum())
                    l = int((sg["Win?"] == 0).sum())
                    t_ = int((sg["Win?"] == 0.5).sum())
                    gp2 = max(0, w + l + t_)
                    winp2 = round((w + 0.5 * t_) / gp2, 4) if gp2 else 0.0
                    pieces.append(f"{opp}: {_record_str(w, l, t_)} ({winp2})")
                record_vs = "; ".join(pieces) if pieces else "N/A"

            row = {
                "Team": str(team),
                "Year": int(yr),
                "Result": "N/A",
                "Win %": winp,
                "Record": rec,
                "Record & win % vs each team": record_vs,
                "Record & win % vs playoff teams": "N/A",
                "Record & win % vs non-playoff teams": "N/A",
                "Record & win % vs champion": "N/A",
                "Record & win % vs last place": "N/A",
                "Change in win % from previous season": None,
                "Win Variance": float(pd.to_numeric(g["Win?"], errors="coerce").fillna(0.0).var()),
                "Week of playoff elimination": "N/A",
                "Draft Value": 0,
                "Number of first round picks made": 0,
                "Total number of picks made": 0,
                "Points": round(pf, 2),
                "Avg points": round(pf / gp, 2),
                "Points against": round(pa, 2),
                "Avg points against": round(pa / gp, 2),
                "Differential": round(diff, 2),
                "Avg differential": round(diff / gp, 2),
                "Max PF": round(maxpf_sum, 2),
                "Avg max PF": round(maxpf_avg, 2) if not math.isnan(maxpf_avg) else None,
                "Efficiency": round(pf / maxpf_sum, 4) if maxpf_sum else None,
                "Weeks of injuries": int(pd.to_numeric(g.get("Number of Injuries"), errors="coerce").fillna(0.0).sum()),
                "Weeks suspensions": int(pd.to_numeric(g.get("Number of suspensions"), errors="coerce").fillna(0.0).sum()),
                "Hardship": float(pd.to_numeric(g.get("Hardship"), errors="coerce").fillna(0.0).sum()),
                "Offseason starter turnover": 0,
                "Inseason starter turnover": 0,
            }
            rows.append(row)
        team_year = pd.DataFrame(rows)

        team_year = team_year.sort_values(["Team", "Year"]).reset_index(drop=True)
        team_year["Change in win % from previous season"] = team_year.groupby("Team")["Win %"].diff()

        # team-all-time rollup
        rows = []
        for team, g in tw.groupby(["Team"]):
            wins = int((g["Win?"] == 1).sum())
            losses = int((g["Win?"] == 0).sum())
            ties = int((g["Win?"] == 0.5).sum())
            gp = max(1, wins + losses + ties)
            pf = float(pd.to_numeric(g["PF"], errors="coerce").fillna(0.0).sum())
            pa = float(pd.to_numeric(g["Points against"], errors="coerce").fillna(0.0).sum())
            diff = pf - pa
            maxpf_sum = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).sum())
            maxpf_avg = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).mean())
            record_vs = "N/A"
            if not games_df.empty:
                sub = games_df[games_df["Team"] == str(team)]
                pieces = []
                for opp in [t for t in teams if t != str(team)]:
                    sg = sub[sub["OppTeam"] == opp]
                    w = int((sg["Win?"] == 1).sum())
                    l = int((sg["Win?"] == 0).sum())
                    t_ = int((sg["Win?"] == 0.5).sum())
                    gp2 = max(0, w + l + t_)
                    winp2 = round((w + 0.5 * t_) / gp2, 4) if gp2 else 0.0
                    pieces.append(f"{opp}: {_record_str(w, l, t_)} ({winp2})")
                record_vs = "; ".join(pieces) if pieces else "N/A"

            row = {
                "Team": str(team),
                "All time win %": round((wins + 0.5 * ties) / gp, 4),
                "All time record": _record_str(wins, losses, ties),
                "Record & win % vs each team": record_vs,
                "Record & win % vs playoff teams": "N/A",
                "Record & win % vs non-playoff teams": "N/A",
                "Record & win % vs champions": "N/A",
                "Record & win % vs last place": "N/A",
                "Win Variance": float(pd.to_numeric(g["Win?"], errors="coerce").fillna(0.0).var()),
                "Draft Value": 0,
                "Number of first round picks made": 0,
                "Total number of picks made": 0,
                "Points": round(pf, 2),
                "Avg points": round(pf / gp, 2),
                "Points against": round(pa, 2),
                "Avg points against": round(pa / gp, 2),
                "Differential": round(diff, 2),
                "Avg differential": round(diff / gp, 2),
                "Max PF": round(maxpf_sum, 2),
                "Avg max PF": round(maxpf_avg, 2) if not math.isnan(maxpf_avg) else None,
                "Efficiency": round(pf / maxpf_sum, 4) if maxpf_sum else None,
                "Weeks of injuries": int(pd.to_numeric(g.get("Number of Injuries"), errors="coerce").fillna(0.0).sum()),
                "Weeks suspensions": int(pd.to_numeric(g.get("Number of suspensions"), errors="coerce").fillna(0.0).sum()),
                "Hardship": float(pd.to_numeric(g.get("Hardship"), errors="coerce").fillna(0.0).sum()),
                "Offseason starter turnover": 0,
                "Inseason starter turnover": 0,
                "Offseason roster turnover": 0,
                "Inseason roster turnover": 0,
                "Tanking": float(pd.to_numeric(g.get("Tanking"), errors="coerce").fillna(0.0).sum()),
                "Luck": float(pd.to_numeric(g.get("Luck"), errors="coerce").fillna(0.0).sum()),
            }
            rows.append(row)
        team_all = pd.DataFrame(rows)

    # League rollups
    league_week = pd.DataFrame()
    league_year = pd.DataFrame()
    league_all = pd.DataFrame()
    if not tw.empty:
        g_week = tw.copy()
        g_week["PF"] = pd.to_numeric(g_week["PF"], errors="coerce").fillna(0.0)
        g_week["Margin"] = pd.to_numeric(g_week["Margin"], errors="coerce")
        g_week["Efficiency"] = pd.to_numeric(g_week["Efficiency"], errors="coerce")
        g_week["Max PF"] = pd.to_numeric(g_week["Max PF"], errors="coerce").fillna(0.0)

        rows = []
        for (yr, wk), g in g_week.groupby(["Year", "Week"]):
            margin_abs = g["Margin"].abs()
            rows.append({
                "Year": int(yr),
                "Week": int(wk),
                "PF": float(g["PF"].sum()),
                "PF Range": float(g["PF"].max() - g["PF"].min()) if not g.empty else 0.0,
                "Avg margin": float(g["Margin"].mean()) if g["Margin"].notna().any() else None,
                "Margin range": float(g["Margin"].max() - g["Margin"].min()) if g["Margin"].notna().any() else None,
                "Number of games within 10": int((margin_abs <= 10).sum() / 2),
                "Number of games within 5": int((margin_abs <= 5).sum() / 2),
                "Max PF": float(g["Max PF"].sum()),
                "Efficiency": float(g["Efficiency"].mean()) if g["Efficiency"].notna().any() else None,
                "Number of Injuries": int(pd.to_numeric(g.get("Number of Injuries"), errors="coerce").fillna(0.0).sum()),
                "Number of suspensions": int(pd.to_numeric(g.get("Number of suspensions"), errors="coerce").fillna(0.0).sum()),
                "Number of players on bye": int(pd.to_numeric(g.get("Number of players on bye"), errors="coerce").fillna(0.0).sum()),
                "Starter turnover from previous week": float(pd.to_numeric(g.get("Starter turnover from previous week"), errors="coerce").fillna(0.0).mean()),
                "Number of wins with pregame avg max PF from opponent": int(pd.to_numeric(g.get("UPST"), errors="coerce").fillna(0.0).sum()),
                "UPST": int(pd.to_numeric(g.get("UPST"), errors="coerce").fillna(0.0).sum()),
                "Hardship": float(pd.to_numeric(g.get("Hardship"), errors="coerce").fillna(0.0).sum()),
                "Tanking": float(pd.to_numeric(g.get("Tanking"), errors="coerce").fillna(0.0).sum()),
                "Luck": float(pd.to_numeric(g.get("Luck"), errors="coerce").fillna(0.0).sum()),
                "Increase in points from previous week": float(pd.to_numeric(g.get("Increase in points from previous week"), errors="coerce").fillna(0.0).sum()),
                "Number of QB started": int(pd.to_numeric(g.get("Number of QB started"), errors="coerce").fillna(0.0).sum()),
                "Number of WR started": int(pd.to_numeric(g.get("Number of WR started"), errors="coerce").fillna(0.0).sum()),
                "Number of RB started": int(pd.to_numeric(g.get("Number of RB started"), errors="coerce").fillna(0.0).sum()),
                "Number of TE started": int(pd.to_numeric(g.get("Number of TE started"), errors="coerce").fillna(0.0).sum()),
                "Number of QB rostered": int(pd.to_numeric(g.get("Number of QB rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of WR rostered": int(pd.to_numeric(g.get("Number of WR rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of RB rostered": int(pd.to_numeric(g.get("Number of RB rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of TE rostered": int(pd.to_numeric(g.get("Number of TE rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of transactions": int(pd.to_numeric(g.get("Number of transactions"), errors="coerce").fillna(0.0).sum()),
                "Number of trades": int(pd.to_numeric(g.get("Number of trades"), errors="coerce").fillna(0.0).sum()),
            })
        league_week = pd.DataFrame(rows)

        rows = []
        for yr, g in g_week.groupby("Year"):
            margin_abs = g["Margin"].abs()
            rows.append({
                "Year": int(yr),
                "(smallest) Playoff tiebreaker": "N/A",
                "PF": float(g["PF"].sum()),
                "Avg PF": float(g["PF"].mean()) if g["PF"].notna().any() else None,
                "PF Range": float(g["PF"].max() - g["PF"].min()) if g["PF"].notna().any() else None,
                "Avg margin": float(g["Margin"].mean()) if g["Margin"].notna().any() else None,
                "Margin range": float(g["Margin"].max() - g["Margin"].min()) if g["Margin"].notna().any() else None,
                "Number of games within 10": int((margin_abs <= 10).sum() / 2),
                "Number of games within 5": int((margin_abs <= 5).sum() / 2),
                "Max PF": float(g["Max PF"].sum()),
                "Avg max PF": float(g["Max PF"].mean()) if g["Max PF"].notna().any() else None,
                "Efficiency": float(g["Efficiency"].mean()) if g["Efficiency"].notna().any() else None,
                "Number of weeks missed due to injury": int(pd.to_numeric(g.get("Number of Injuries"), errors="coerce").fillna(0.0).sum()),
                "Number of weeks missed due to suspensions": int(pd.to_numeric(g.get("Number of suspensions"), errors="coerce").fillna(0.0).sum()),
                "Inseason starter turnover": float(pd.to_numeric(g.get("Starter turnover from previous week"), errors="coerce").fillna(0.0).mean()),
                "Offseason starter turnover": 0,
                "Inseason roster turnover": 0,
                "Offseason roster turnover": 0,
                "Number of wins with pregame avg max PF from opponent": int(pd.to_numeric(g.get("UPST"), errors="coerce").fillna(0.0).sum()),
                "Tanking": float(pd.to_numeric(g.get("Tanking"), errors="coerce").fillna(0.0).sum()),
                "Luck": float(pd.to_numeric(g.get("Luck"), errors="coerce").fillna(0.0).sum()),
                "Increase in points from previous week": float(pd.to_numeric(g.get("Increase in points from previous week"), errors="coerce").fillna(0.0).sum()),
                "Number of QB started": int(pd.to_numeric(g.get("Number of QB started"), errors="coerce").fillna(0.0).sum()),
                "Number of WR started": int(pd.to_numeric(g.get("Number of WR started"), errors="coerce").fillna(0.0).sum()),
                "Number of RB started": int(pd.to_numeric(g.get("Number of RB started"), errors="coerce").fillna(0.0).sum()),
                "Number of TE started": int(pd.to_numeric(g.get("Number of TE started"), errors="coerce").fillna(0.0).sum()),
                "Number of QB rostered": int(pd.to_numeric(g.get("Number of QB rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of WR rostered": int(pd.to_numeric(g.get("Number of WR rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of RB rostered": int(pd.to_numeric(g.get("Number of RB rostered"), errors="coerce").fillna(0.0).sum()),
                "Number of TE rostered": int(pd.to_numeric(g.get("Number of TE rostered"), errors="coerce").fillna(0.0).sum()),
            })
        league_year = pd.DataFrame(rows)

        league_all = pd.DataFrame([{
            "PF": float(pd.to_numeric(g_week["PF"], errors="coerce").fillna(0.0).sum()),
            "Avg PF": float(pd.to_numeric(g_week["PF"], errors="coerce").fillna(0.0).mean()),
            "PF Range": float(g_week["PF"].max() - g_week["PF"].min()) if g_week["PF"].notna().any() else None,
            "Avg margin": float(g_week["Margin"].mean()) if g_week["Margin"].notna().any() else None,
            "Margin range": float(g_week["Margin"].max() - g_week["Margin"].min()) if g_week["Margin"].notna().any() else None,
            "Number of games within 10": int((g_week["Margin"].abs() <= 10).sum() / 2),
            "Number of games within 5": int((g_week["Margin"].abs() <= 5).sum() / 2),
            "Max PF": float(pd.to_numeric(g_week["Max PF"], errors="coerce").fillna(0.0).sum()),
            "Avg max PF": float(pd.to_numeric(g_week["Max PF"], errors="coerce").fillna(0.0).mean()),
            "Efficiency": float(pd.to_numeric(g_week["Efficiency"], errors="coerce").dropna().mean()) if g_week["Efficiency"].notna().any() else None,
            "Number of weeks missed due to injury": int(pd.to_numeric(g_week.get("Number of Injuries"), errors="coerce").fillna(0.0).sum()),
            "Number of weeks missed due to suspensions": int(pd.to_numeric(g_week.get("Number of suspensions"), errors="coerce").fillna(0.0).sum()),
            "Number of wins with pregame avg max PF from opponent": int(pd.to_numeric(g_week.get("UPST"), errors="coerce").fillna(0.0).sum()),
            "Tanking": float(pd.to_numeric(g_week.get("Tanking"), errors="coerce").fillna(0.0).sum()),
            "Luck": float(pd.to_numeric(g_week.get("Luck"), errors="coerce").fillna(0.0).sum()),
            "Increase in points from previous week": float(pd.to_numeric(g_week.get("Increase in points from previous week"), errors="coerce").fillna(0.0).sum()),
            "Number of QB started": int(pd.to_numeric(g_week.get("Number of QB started"), errors="coerce").fillna(0.0).sum()),
            "Number of WR started": int(pd.to_numeric(g_week.get("Number of WR started"), errors="coerce").fillna(0.0).sum()),
            "Number of RB started": int(pd.to_numeric(g_week.get("Number of RB started"), errors="coerce").fillna(0.0).sum()),
            "Number of TE started": int(pd.to_numeric(g_week.get("Number of TE started"), errors="coerce").fillna(0.0).sum()),
            "Number of QB rostered": int(pd.to_numeric(g_week.get("Number of QB rostered"), errors="coerce").fillna(0.0).sum()),
            "Number of WR rostered": int(pd.to_numeric(g_week.get("Number of WR rostered"), errors="coerce").fillna(0.0).sum()),
            "Number of RB rostered": int(pd.to_numeric(g_week.get("Number of RB rostered"), errors="coerce").fillna(0.0).sum()),
            "Number of TE rostered": int(pd.to_numeric(g_week.get("Number of TE rostered"), errors="coerce").fillna(0.0).sum()),
            "Number of transactions": int(pd.to_numeric(g_week.get("Number of transactions"), errors="coerce").fillna(0.0).sum()),
            "Number of trades": int(pd.to_numeric(g_week.get("Number of trades"), errors="coerce").fillna(0.0).sum()),
            "Amount of FAAB spent": float(pd.to_numeric(g_week.get("Amount of FAAB spent"), errors="coerce").fillna(0.0).sum()),
            "Most number of players started from same NFL team": float(pd.to_numeric(g_week.get("Most number of players started from same NFL team"), errors="coerce").fillna(0.0).max()),
            "Most number of players rostered from same NFL team": float(pd.to_numeric(g_week.get("Most number of players rostered from same NFL team"), errors="coerce").fillna(0.0).max()),
            "Most number of QBs started from same NFL team": float(pd.to_numeric(g_week.get("Most number of QBs started from same NFL team"), errors="coerce").fillna(0.0).max()),
        }])

    # --------------------------
    # Write outputs (schema contract)
    # --------------------------
    tables = [
        ("player_week.csv", pw, "Player-Week"),
        ("player_year.csv", player_year, "Player-year"),
        ("player_all_time.csv", player_all, "Player-all-time"),
        ("team_week.csv", tw, "team-week"),
        ("team_year.csv", team_year, "team-year"),
        ("team_all_time.csv", team_all, "team-all-time"),
        ("league_week.csv", league_week, "league-week"),
        ("league_year.csv", league_year, "league-year"),
        ("league_all_time.csv", league_all, "league-all-time"),
        ("transactions.csv", tx, "transactions"),
        ("trades.csv", tr, "trades"),
        ("pick_history.csv", ph, "Pick History"),
    ]
    write_outputs(tables)
