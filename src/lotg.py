
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional, Set
from datetime import datetime, timezone, timedelta, date
from collections import Counter, deque, defaultdict
import json
import math
import re
import traceback
import logging
import warnings
import numpy as np
import os
import sys

warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays")

LOG = logging.getLogger("lotg")
if not LOG.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


import pandas as pd


def _round_from_label(label: Any) -> str:
    s = str(label or "").strip().lower()
    if s in ("semifinal", "semifinals"):
        return "semifinals"
    if s in ("final", "finals"):
        return "Finals"
    if s in ("toilet semis", "toilet semifinal", "toilet semifinals"):
        return "Toilet Semis"
    if s in ("toilet final", "toilet finals"):
        return "toilet finals"
    if s in ("3rd place", "third place"):
        return "3rd place game"
    if s in ("toilet trash", "trash"):
        return "toilet trash"
    return "regular season"
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

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

SUPPORT_ROOT = Path(__file__).resolve().parent.parent / "lib"
if str(SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ROOT))

from lotg_support.utils import HttpConfig, safe_div, clean_name, safe_bool
from lotg_support.sleeper import SleeperClient
from lotg_support.external import (
    ExternalConfig,
    load_dynastyprocess_playerids,
    load_dynastyprocess_values_players,
    load_dynastyprocess_values_picks,
    load_nflverse_injuries,
    load_nflverse_player_ids,
    load_nflverse_stats_player_week,
)
from lotg_support.lineup import compute_optimal_lineup
from lotg_support.plan import load_plan_catalog, require_columns

import league_all_time
import league_week
import league_year
import pick_history
import player_all_time
import player_week
import player_year
import team_all_time
import team_week
import team_year
import trades
import transactions
import formulas

DOCUMENT_MODULES = [
    player_week,
    player_year,
    player_all_time,
    team_week,
    team_year,
    team_all_time,
    league_week,
    league_year,
    league_all_time,
    transactions,
    trades,
    pick_history,
    formulas,
]


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



def _norm_team_name(name: Any) -> str:
    """Normalize owner/team names for consistent joins (case-insensitive, space-insensitive)."""
    s = str(name or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    return s



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


def _fatal_log(repo_root: Path, where: str, e: Exception) -> None:
    """Best-effort fatal logging for CI visibility when process exits non-zero."""
    debug = repo_root / "exports" / "raw" / "build_debug.log"
    _log_exc(debug, where, e)
    try:
        print(f"FATAL [{where}] {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
    except Exception:
        pass

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


def _valid_pid(pid: Any) -> bool:
    """Return True if pid is a real Sleeper player id (not placeholders like '0')."""
    if pid is None:
        return False
    # handle pandas/numpy NaN
    try:
        if isinstance(pid, float) and np.isnan(pid):
            return False
    except Exception:
        pass
    s = str(pid).strip()
    if s == "" or s.lower() == "nan":
        return False
    if s == "0" or s == "-1":
        return False
    return True
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


def _rookie_season(meta: Dict[str, Any], current_season: Optional[int]) -> Optional[int]:
    draft_year = _to_int(meta.get("draft_year"), None)
    if draft_year:
        return draft_year
    years_exp = _to_float(meta.get("years_exp"), None)
    if years_exp is None or current_season is None or years_exp < 0:
        return None
    return int(current_season) - int(years_exp)


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
    for url in urls:
        fetched = False
        for trust_env in (False, True):
            try:
                session = requests.Session()
                session.trust_env = trust_env
                kwargs = {"timeout": timeout}
                if not trust_env:
                    kwargs["proxies"] = {"http": None, "https": None}
                r = session.get(url, **kwargs)
                if r.status_code == 200 and r.content:
                    path.write_bytes(r.content)
                    fetched = True
                    break
                last_err = f"{r.status_code} {url} trust_env={trust_env}"
            except Exception as e:
                last_err = f"{type(e).__name__}: {e} {url} trust_env={trust_env}"

        if fetched:
            try:
                return pd.read_csv(path)
            except Exception:
                return pd.DataFrame()

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


def _append_team_vs_columns(frame: pd.DataFrame, cols: List[str]) -> List[str]:
    if frame.empty or "Team" not in frame.columns:
        return cols
    teams = sorted(frame["Team"].dropna().astype(str).unique().tolist())
    extra = []
    for team in teams:
        extra.append(f"Record vs {team}")
        extra.append(f"Win % vs {team}")
    return cols + [c for c in extra if c not in cols]


def _column_kind(col: str) -> str:
    """Infer expected output type for a plan column: text | boolean | numeric."""
    col_l = str(col or "").strip().lower()

    # Explicit text columns first (some contain words like "week"/"year" but are labels).
    text_exact = {
        "week name",
        "team",
        "player",
        "opponent",
        "top team",
        "last team",
        "original team",
        "player picked",
        "reference player name",
        "nfl team",
        "position",
        "position started in (if starter)",
        "starter/bench",
        "type of transaction",
        "assets sent",
        "assets received",
        "assets dropped",
        "assets received",
        "team's traded with",
        "reason",
        "date",
        "date dropped/traded",
        "record",
        "all time record",
        "(smallest) playoff tiebreaker",
        "round",
        "number",
        "result",
        "etc",
        # Formulas sheet — pure documentation, all four columns are text
        "stat",
        "sheet",
        "formula",
        "notes",
    }
    if col_l in text_exact:
        return "text"

    # Substring-based markers: a column counts as text when its label *contains*
    # any of these tokens. Important: keep these specific enough that they
    # don't grab numeric columns by accident.
    text_markers = [
        "record vs ",
        "link to ",
        "trade ",
        "pick",
        "type of transaction",  # 'type of transaction (waiver/free agency)' variants
        "player added",
        "player dropped",
        "assets received",
        "assets dropped",
        "assets received",
        "team's traded with",
        "teams traded with",
    ]
    if any(m in col_l for m in text_markers):
        return "text"

    # Boolean / flag-style columns.
    bool_exact = {
        "injury?",
        "suspension?",
        "bye?",
        "rookie?",
        "win?",
        "loss?",
        "player of the week?",
        "qb of the week?",
        "rb of the week?",
        "wr of the week?",
        "te of the week?",
        "benchwarmer of the week?",
        "bench qb of the week?",
        "bench rb of the week?",
        "bench wr of the week?",
        "bench te of the week?",
        "highest starter on team?",
        "lowest starter on team?",
    }
    # "Times X of the week?" / "Times Top half of league?" etc. are aggregate
    # counts in player_year/team_year — they end in '?' but are integers.
    # Numeric kind first prevents boolean coercion of summed counts.
    if col_l.startswith("times ") or col_l.startswith("number of ") or col_l.startswith("weeks "):
        return "numeric"

    if col_l in bool_exact or col_l.endswith("?"):
        return "boolean"

    # Remaining metrics are numeric by contract.
    return "numeric"


def _is_text_column(col: str) -> bool:
    return _column_kind(col) == "text"


def _fill_empty_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            continue
        if df[col].isna().all():
            df[col] = _default_fill_for_column(col)
    return df


def _default_fill_for_column(col: str) -> Any:
    kind = _column_kind(col)
    if kind == "text":
        return "N/A"
    if kind == "boolean":
        return False
    return 0.0


def _preserve_na(col: str) -> bool:
    """Numeric columns where a missing value carries meaning (no prior data)
    and should render as 'N/A' instead of being filled with 0.0. Most of
    these describe a *change* relative to a prior period — for the first
    week/season the comparison literally doesn't exist."""
    col_l = str(col or "").strip().lower()
    if col_l.startswith("change from ") or col_l.startswith("change in "):
        return True
    # KTC value differences: 'at deal time' / 'at end of season' / '1 year
    # later' / '2 years later'. A blank here means the reference date is
    # in the future, or at least one side of the trade had no resolvable
    # KTC value (e.g. pre-2022 trades where DynastyProcess data is
    # sparse). Both cases are distinct from 'the diff is actually zero',
    # so don't collapse them to 0.0.
    if col_l.startswith("ktc value difference"):
        return True
    # KTC columns on transactions.csv. Blank means the player wasn't
    # tracked by dynasty-daddy (low-value / pre-2021), or the row was
    # a drop-only / no-drop row, or the reference date is in the
    # future. Distinct from 'KTC is actually zero'.
    if col_l.startswith("ktc value of player added") or col_l.startswith("ktc value of player dropped"):
        return True
    if col_l.startswith("net ktc value"):
        return True
    # Faab-vs-second-place: blank means the row isn't a waiver, or the
    # waiver was uncontested (no runner-up). Either case is distinct
    # from 'won by zero' so don't collapse to 0.0.
    if col_l in {
        "faab difference over second place",
        "faab % difference over second place",
    }:
        return True
    # PPG / age / start-rate columns on transactions.csv. Blank = the
    # row had no Player Added/Dropped to compute against, or the
    # player has no pre-pickup game log. Distinct from 'value is
    # actually zero'.
    if col_l in {
        "average ppg on team",
        "average ppg of dropped player over same time",
        "ppg of 5 games before pickup",
        "difference of averages",
        "difference of averages adjusted by position",
        "age difference",
        "player addition value",
        "number of starts before next drop",
        "% of starts made while rostered",
        "injury adjusted % of starts made while rostered",
    }:
        return True
    # Pick-value columns on trades.csv: blank means the trade had no
    # picks at all, or all picks failed to resolve (e.g., picks for a
    # draft too far in the future). Distinct from 'the pick value is
    # actually zero', so don't collapse to 0.0.
    if col_l in {
        "pick value received",
        "change in pick value at draft time",
    }:
        return True
    if col_l in {
        "win variance",
        "weeks between pickup and start",
    }:
        return True
    return False


def _fill_missing_values(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    truthy = {"true", "t", "1", "yes", "y"}
    falsy = {"false", "f", "0", "no", "n", ""}

    for col in cols:
        if col not in df.columns:
            continue

        kind = _column_kind(col)
        default = _default_fill_for_column(col)

        if kind == "text":
            df[col] = df[col].astype(object).replace("", default).fillna(default)
            continue

        if kind == "boolean":
            def _coerce_bool(v: Any) -> bool:
                if pd.isna(v):
                    return default
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                s = str(v).strip().lower()
                if s in truthy:
                    return True
                if s in falsy:
                    return False
                return default

            df[col] = df[col].map(_coerce_bool)
            continue

        # numeric path
        if _preserve_na(col):
            # First-occurrence values stay as NaN and render as 'N/A' in CSV.
            num = pd.to_numeric(df[col], errors="coerce")
            df[col] = num.astype(object).where(num.notna(), "N/A")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    return df


def _default_player_week_benchmark_cases() -> pd.DataFrame:
    """Fallback benchmark cases for player_week validation."""
    rows = [
        {"player": "Nick Chubb", "season": 2022, "week": 1, "expected_nfl_team": "CLE", "check_type": "HEALTHY_WEEK", "why_this_week": "Healthy baseline (Active/played; no flags)"},
        {"player": "Nick Chubb", "season": 2023, "week": 3, "expected_nfl_team": "CLE", "check_type": "INJURY_WEEK", "why_this_week": "Post-knee-injury non-start week (should show Injury/IR, not Played)"},
        {"player": "Nick Chubb", "season": 2024, "week": 16, "expected_nfl_team": "CLE", "check_type": "INJURY_WEEK", "why_this_week": "Post-broken-foot non-start week (clear Injury miss)"},
        {"player": "Nick Chubb", "season": 2025, "week": 1, "expected_nfl_team": "HOU", "check_type": "TEAM_WEEK", "why_this_week": "Team mapping check: should show Texans in 2025"},
        {"player": "Cooper Kupp", "season": 2021, "week": 1, "expected_nfl_team": "LAR", "check_type": "HEALTHY_WEEK", "why_this_week": "Healthy baseline"},
        {"player": "Cooper Kupp", "season": 2022, "week": 11, "expected_nfl_team": "LAR", "check_type": "INJURY_WEEK", "why_this_week": "On IR for high-ankle (non-start; Injury/IR)"},
        {"player": "Cooper Kupp", "season": 2023, "week": 1, "expected_nfl_team": "LAR", "check_type": "INJURY_WEEK", "why_this_week": "Start-of-season IR (non-start; Injury/IR)"},
        {"player": "Cooper Kupp", "season": 2024, "week": 3, "expected_nfl_team": "LAR", "check_type": "INJURY_WEEK", "why_this_week": "Post-ankle injury non-start week"},
        {"player": "Cooper Kupp", "season": 2025, "week": 1, "expected_nfl_team": "SEA", "check_type": "TEAM_WEEK", "why_this_week": "Team mapping check: Seahawks"},
        {"player": "Rashee Rice", "season": 2023, "week": 1, "expected_nfl_team": "KC", "check_type": "HEALTHY_WEEK", "why_this_week": "Healthy baseline"},
        {"player": "Rashee Rice", "season": 2024, "week": 5, "expected_nfl_team": "KC", "check_type": "INJURY_WEEK", "why_this_week": "After Week 4 knee injury (non-start; Injury/IR)"},
        {"player": "Rashee Rice", "season": 2025, "week": 1, "expected_nfl_team": "KC", "check_type": "SUSPENSION_WEEK", "why_this_week": "Start-of-season suspension (must show Suspension, not Injury)"},
        {"player": "Rashee Rice", "season": 2025, "week": 6, "expected_nfl_team": "KC", "check_type": "SUSPENSION_WEEK", "why_this_week": "Final week of 6-game suspension"},
        {"player": "Jordan Addison", "season": 2023, "week": 1, "expected_nfl_team": "MIN", "check_type": "HEALTHY_WEEK", "why_this_week": "Healthy rookie baseline"},
        {"player": "Jordan Addison", "season": 2024, "week": 2, "expected_nfl_team": "MIN", "check_type": "INJURY_WEEK", "why_this_week": "Ruled out (ankle); did not start"},
        {"player": "Jordan Addison", "season": 2024, "week": 9, "expected_nfl_team": "MIN", "check_type": "SUSPENSION_WEEK", "why_this_week": "MIDSEASON suspension week (must show Suspension, not Injury/Bye)"},
        {"player": "Jordan Addison", "season": 2025, "week": 1, "expected_nfl_team": "MIN", "check_type": "SUSPENSION_WEEK", "why_this_week": "Start-of-season 3-game suspension"},
        {"player": "Jordan Addison", "season": 2025, "week": 3, "expected_nfl_team": "MIN", "check_type": "SUSPENSION_WEEK", "why_this_week": "Final week of 3-game suspension"},
        {"player": "Allen Lazard", "season": 2022, "week": 4, "expected_nfl_team": "GB", "check_type": "HEALTHY_WEEK", "why_this_week": "Healthy Packers baseline"},
        {"player": "Allen Lazard", "season": 2022, "week": 1, "expected_nfl_team": "GB", "check_type": "INJURY_WEEK", "why_this_week": "Missed opener (ankle; non-start)"},
        {"player": "Allen Lazard", "season": 2023, "week": 1, "expected_nfl_team": "NYJ", "check_type": "TEAM_WEEK", "why_this_week": "Team mapping check: Jets"},
        {"player": "Allen Lazard", "season": 2024, "week": 8, "expected_nfl_team": "NYJ", "check_type": "INJURY_WEEK", "why_this_week": "Post-chest-injury IR week (non-start)"},
        {"player": "Allen Lazard", "season": 2025, "week": 1, "expected_nfl_team": "NYJ", "check_type": "TEAM_WEEK", "why_this_week": "Team mapping continuity check"},
    ]
    return pd.DataFrame(rows)


def _load_player_week_benchmark_cases(repo_root: Path) -> pd.DataFrame:
    path = repo_root / "plan" / "player_week_benchmark_cases.csv"
    if path.exists():
        try:
            df = pd.read_csv(path)
            required = {"player", "season", "week", "expected_nfl_team", "check_type", "why_this_week"}
            if not df.empty and required.issubset(set(df.columns)):
                return df
        except Exception:
            pass
    return _default_player_week_benchmark_cases()


def _finalize_validation_output(out: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(out)
    if df.empty:
        return df
    # keep detailed reason but force Error marker per request
    if "Error" in df.columns:
        df = df.rename(columns={"Error": "Reason"})
    df["Error"] = "error"
    wanted = [
        "Player", "Season", "Week", "Check Type", "Column", "Error", "Reason", "Expected", "Observed Example"
    ]
    cols = [c for c in wanted if c in df.columns] + [c for c in df.columns if c not in wanted]
    return df[cols]


def _known_player_column_errors(repo_root: Path, player_week_df: pd.DataFrame) -> pd.DataFrame:
    """Case-based benchmark validation focused on player_week rows."""
    cases = _load_player_week_benchmark_cases(repo_root)
    pw = _safe_df(player_week_df).copy()

    out: List[Dict[str, Any]] = []

    if pw.empty:
        for _, c in cases.iterrows():
            out.append({
                "Player": c.get("player"),
                "Season": _to_int(c.get("season"), None),
                "Week": _to_int(c.get("week"), None),
                "Check Type": c.get("check_type"),
                "Column": "ALL",
                "Error": "No player_week rows available for validation",
                "Expected": c.get("why_this_week"),
                "Observed Example": "No rows",
            })
        return _finalize_validation_output(out)

    pw["_player_norm"] = pw.get("Player", pd.Series(dtype=str)).astype(str).map(clean_name).str.lower()
    pw["_year"] = pd.to_numeric(pw.get("Year"), errors="coerce").astype("Int64")
    pw["_week"] = pd.to_numeric(pw.get("Week"), errors="coerce").astype("Int64")

    for _, c in cases.iterrows():
        player = clean_name(c.get("player")).lower()
        season = _to_int(c.get("season"), None)
        week = _to_int(c.get("week"), None)
        check_type = str(c.get("check_type") or "").upper().strip()
        expected_team = _norm_team(c.get("expected_nfl_team"))
        why = str(c.get("why_this_week") or "").strip()

        sub = pw[(pw["_player_norm"] == player) & (pw["_year"] == season) & (pw["_week"] == week)].copy()
        if sub.empty:
            out.append({
                "Player": clean_name(c.get("player")),
                "Season": season,
                "Week": week,
                "Check Type": check_type,
                "Column": "ALL",
                "Error": "Case row missing from output",
                "Expected": why,
                "Observed Example": "No matching row",
            })
            continue

        # team mapping check for all case types
        obs_team = sub.get("NFL team", pd.Series(dtype=object)).map(_norm_team)
        if expected_team and not bool((obs_team == expected_team).all()):
            out.append({
                "Player": clean_name(c.get("player")),
                "Season": season,
                "Week": week,
                "Check Type": check_type,
                "Column": "NFL team",
                "Error": "Team mismatch",
                "Expected": expected_team,
                "Observed Example": ", ".join(sorted(set(obs_team.astype(str).tolist()))),
            })

        inj = sub.get("Injury?", pd.Series(dtype=bool)).map(lambda v: safe_bool(v, default=False))
        sus = sub.get("Suspension?", pd.Series(dtype=bool)).map(lambda v: safe_bool(v, default=False))
        bye = sub.get("Bye?", pd.Series(dtype=bool)).map(lambda v: safe_bool(v, default=False))
        sb = sub.get("Starter/Bench", pd.Series(dtype=object)).astype(str).str.lower().str.strip()

        if check_type == "HEALTHY_WEEK":
            if bool(inj.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Injury?", "Error": "Unexpected injury flag", "Expected": "False", "Observed Example": "True"})
            if bool(sus.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Suspension?", "Error": "Unexpected suspension flag", "Expected": "False", "Observed Example": "True"})
            if bool(bye.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Bye?", "Error": "Unexpected bye flag", "Expected": "False", "Observed Example": "True"})

        elif check_type == "INJURY_WEEK":
            if not bool(inj.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Injury?", "Error": "Missing injury flag", "Expected": "True", "Observed Example": "False"})
            if bool(sus.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Suspension?", "Error": "Suspension should not be set", "Expected": "False", "Observed Example": "True"})
            if (sb == "starter").any():
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Starter/Bench", "Error": "Expected non-start week", "Expected": "Bench", "Observed Example": "Starter"})

        elif check_type == "SUSPENSION_WEEK":
            if not bool(sus.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Suspension?", "Error": "Missing suspension flag", "Expected": "True", "Observed Example": "False"})
            if bool(inj.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Injury?", "Error": "Injury should not be set", "Expected": "False", "Observed Example": "True"})
            if bool(bye.any()):
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Bye?", "Error": "Bye should not be set during suspension", "Expected": "False", "Observed Example": "True"})
            if (sb == "starter").any():
                out.append({"Player": clean_name(c.get("player")), "Season": season, "Week": week, "Check Type": check_type, "Column": "Starter/Bench", "Error": "Expected non-start week", "Expected": "Bench", "Observed Example": "Starter"})

    return _finalize_validation_output(out)




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

    # nflverse player id mapping (for injury + team-by-week)
    sleeper_to_gsis: Dict[str, str] = {}
    try:
        nfl_ids = _safe_df(load_nflverse_player_ids(ext))
        if (not nfl_ids.empty) and ("sleeper_id" in nfl_ids.columns) and ("gsis_id" in nfl_ids.columns):
            nfl_ids = nfl_ids.dropna(subset=["sleeper_id", "gsis_id"]).copy()
            nfl_ids["sleeper_id"] = nfl_ids["sleeper_id"].astype(str)
            nfl_ids["gsis_id"] = nfl_ids["gsis_id"].astype(str)
            sleeper_to_gsis = dict(zip(nfl_ids["sleeper_id"], nfl_ids["gsis_id"]))
    except Exception as e:
        _log_exc(debug, "load_nflverse_player_ids", e)

    # ------------- External data -------------

    try:
        dp_ids = _safe_df(load_dynastyprocess_playerids(ext))
    except Exception as e:
        dp_ids = pd.DataFrame()
        _log_exc(debug, "load_dynastyprocess_playerids", e)

    def _norm_id(x: Any) -> str:
        """
        Normalise an id read from a CSV to a bare integer-string.
        pandas reads columns containing NaN as float64, so a plain
        astype(str) on '7564' (int) yields '7564.0' (float). Strip
        the .0 suffix and any whitespace so dict lookups against
        bare Sleeper pids ('7564', '5859') succeed.
        """
        s = str(x).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    for c in ["sleeper_id", "gsis_id", "name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    dp_sleeper_to_gsis: Dict[str, str] = {}
    if (not dp_ids.empty) and ("sleeper_id" in dp_ids.columns) and ("gsis_id" in dp_ids.columns):
        try:
            m = dp_ids[["sleeper_id", "gsis_id"]].dropna().copy()
            m["sleeper_id"] = m["sleeper_id"].astype(str).map(_norm_id)
            m["gsis_id"] = m["gsis_id"].astype(str).map(lambda v: str(v).strip())
            # Drop rows whose ids degenerated to empty/nan strings after coercion.
            m = m[(m["sleeper_id"] != "") & (m["sleeper_id"].str.lower() != "nan")]
            m = m[(m["gsis_id"] != "") & (m["gsis_id"].str.lower() != "nan")]
            dp_sleeper_to_gsis = dict(zip(m["sleeper_id"], m["gsis_id"]))
        except Exception:
            dp_sleeper_to_gsis = {}

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
            games["week"] = pd.to_numeric(games["week"], errors="coerce").astype("Int64")
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
        # Sleeper's /players/nfl returns gsis_id with leading/trailing whitespace for
        # roughly 22% of players (e.g. A.J. Brown -> ' 00-0035676'). Strip it here
        # so every downstream lookup (player_team_by_week, injuries_by_gsis_week,
        # nflverse enrichment) hits the dict keys correctly.
        raw_gsis = meta.get("gsis_id")
        clean_gsis = str(raw_gsis).strip() if raw_gsis is not None else None
        pid_meta[pid] = {
            "full_name": full or pid,
            "pos": (meta.get("position") or ""),
            "team": _norm_team(meta.get("team")),
            "birth_date": meta.get("birth_date") or meta.get("birthdate"),
            "years_exp": meta.get("years_exp"),
            "draft_year": meta.get("draft_year"),
            "status": meta.get("status"),
            "injury_status": meta.get("injury_status"),
            "gsis_id": clean_gsis if clean_gsis else None,
        }
        pid_pos[pid] = (pid_meta[pid]["pos"] or "").upper()

    # Enrich pid_meta with nflverse player metadata (authoritative rookie_season,
    # birth_date, position). Sleeper's draft_year/years_exp are often missing or
    # current-relative, which is why Rookie? produced False for every row even
    # for known rookies (Chase 2021, Williams 2024, etc.).
    try:
        nfl_players = _safe_df(load_nflverse_player_ids(ext))
    except Exception as e:
        nfl_players = pd.DataFrame()
        _log_exc(debug, "load_nflverse_player_ids_enrich", e)

    if not nfl_players.empty and "gsis_id" in nfl_players.columns:
        nfl_players = nfl_players.copy()
        nfl_players["gsis_id"] = nfl_players["gsis_id"].astype(str)
        nfl_by_gsis = {
            str(row.get("gsis_id")): row
            for _, row in nfl_players.iterrows()
            if isinstance(row.get("gsis_id"), str) and row.get("gsis_id")
        }
        for pid, m in pid_meta.items():
            # Look up gsis_id via the full chain — Sleeper's meta lacks gsis_id for
            # many players (e.g. Ja'Marr Chase, Caleb Williams). DP's db_playerids
            # provides the sleeper_id <-> gsis_id mapping that closes the gap.
            gsis = (
                m.get("gsis_id")
                or dp_sleeper_to_gsis.get(str(pid))
                or sleeper_to_gsis.get(str(pid))
            )
            if not gsis:
                continue
            # Backfill gsis_id onto pid_meta so the per-week injury / team
            # lookups also benefit (otherwise they re-resolve every row).
            if not m.get("gsis_id"):
                m["gsis_id"] = gsis
            nrow = nfl_by_gsis.get(str(gsis))
            if nrow is None:
                continue
            # rookie_season is authoritative; override Sleeper's draft_year when nflverse has it
            rs = nrow.get("rookie_season")
            try:
                rs_int = int(float(rs)) if rs is not None and str(rs) != "nan" else None
            except Exception:
                rs_int = None
            if rs_int is not None:
                m["draft_year"] = rs_int
            # birth_date: prefer nflverse if Sleeper is missing it
            if not m.get("birth_date"):
                bd = nrow.get("birth_date")
                if bd is not None and str(bd) != "nan":
                    m["birth_date"] = str(bd)
            # latest_team / draft_team fallback: when Sleeper shows team=None
            # (retired / free agent / out of league), use nflverse's last-known
            # team so per-week NFL team isn't NAN for players whose career ended
            # within the league window (Tarik Cohen 2021 - BAL, Josh Doctson 2021
            # - WAS, etc.). We only fill it when Sleeper has nothing.
            if not m.get("team"):
                lt = nrow.get("latest_team") or nrow.get("draft_team")
                if lt is not None and str(lt) != "nan" and str(lt).strip():
                    m["team"] = _norm_team(str(lt))

    # ------------- League chain -------------
    leagues = _walk_league_chain(sc, run_cfg.league_id, run_cfg.min_season, run_cfg.max_season)
    raw_dir = repo_root / "exports" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    def write_outputs(tables: List[Tuple[str, pd.DataFrame, str]]) -> None:
        out_dir = repo_root / "exports"
        out_dir.mkdir(exist_ok=True)
        for fname, frame, plan_key in tables:
            cols = catalog.get(plan_key, [])
            if plan_key in {"team-year", "team-all-time"}:
                cols = _append_team_vs_columns(frame, cols)
            frame = _safe_df(frame)
            out = _ensure_plan_columns(frame, cols)
            out = _fill_empty_columns(out, cols)
            out = _fill_missing_values(out, cols)
            # Round numeric columns at output to suppress float noise
            # (e.g., Luck = 188.49633333333333, change-in-win% = -0.05879999..).
            # 4 decimals is enough precision for fantasy football stats.
            # Previous version used errors='ignore' which pandas treats as
            # 'leave unchanged' for any column with a non-numeric value, so
            # rounding silently no-op'd on most columns.
            try:
                for c in out.columns:
                    if _column_kind(c) == "numeric":
                        try:
                            coerced = pd.to_numeric(out[c], errors="coerce")
                            # Only overwrite when we actually got numeric data.
                            if coerced.notna().any():
                                rounded = coerced.round(4)
                                if _preserve_na(c):
                                    # Keep 'N/A' as a string for first-occurrence
                                    # rows (no prior data to compare against).
                                    out[c] = rounded.astype(object).where(rounded.notna(), "N/A")
                                else:
                                    out[c] = rounded
                        except Exception:
                            continue
            except Exception as e:
                _log_exc(debug, f"round_numeric_{fname}", e)
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
                ws.freeze_panes = "E2"

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
        for doc in DOCUMENT_MODULES:
            src = fallback_dir / doc.FILE_NAME
            if src.exists():
                try:
                    fallback_tables.append((doc.FILE_NAME, pd.read_csv(src), doc.PLAN_KEY))
                except Exception:
                    fallback_tables.append((doc.FILE_NAME, pd.DataFrame(), doc.PLAN_KEY))
            else:
                fallback_tables.append((doc.FILE_NAME, pd.DataFrame(), doc.PLAN_KEY))
        _log(debug, f"[{_now_iso()}] WARN no leagues found; using fallback data/ outputs")
        write_outputs(fallback_tables)
        return

    league_seasons = [_to_int(lg.get("season"), None) for lg in leagues]
    league_seasons = [s for s in league_seasons if s is not None]
    current_season_for_rookies = max(league_seasons) if league_seasons else (_to_int(run_cfg.max_season, None) or date.today().year)
    rookie_season_by_pid = {
        pid: _rookie_season(meta, current_season_for_rookies)
        for pid, meta in pid_meta.items()
    }

    def is_rookie_pid(pid: Any, season: int) -> bool:
        rookie_season = rookie_season_by_pid.get(str(pid))
        return rookie_season is not None and int(season) == int(rookie_season)

    # ------------- Output rows -------------
    player_week_rows: List[Dict[str, Any]] = []
    team_week_rows: List[Dict[str, Any]] = []
    transactions_rows: List[Dict[str, Any]] = []
    # Cross-season per-player NFL game log (sourced from nflverse, so
    # weeks count as "played" whether or not the player was on a
    # fantasy roster at the time). Used by the transactions polish
    # pass to compute pre-pickup PPG without being limited to pw —
    # rookies and UFAs picked up after their NFL debut now resolve.
    # Keyed by Sleeper sleeper_id; each entry: {year, week, points,
    # _wk_date}. Points use fantasy_points_ppr as the approximation
    # (most leagues are 0.5-PPR or full PPR; rankings are stable
    # between the two for trend purposes).
    nfl_log_by_sid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    trades_rows: List[Dict[str, Any]] = []
    # Orphan drops: a player dropped without a corresponding add in the same
    # transaction (pure waiver-to-FA). These don't get a transactions.csv row
    # but they still matter for the per-player event log when computing
    # 'Weeks between pickup and start' / 'Date dropped/traded'.
    orphan_drop_events: List[Dict[str, Any]] = []
    pick_rows: List[Dict[str, Any]] = []
    player_tx_week: Dict[Tuple[str, int, int], int] = defaultdict(int)
    player_drop_week: Dict[Tuple[str, int, int], int] = defaultdict(int)
    player_tx_year: Dict[Tuple[str, int], int] = defaultdict(int)
    player_drop_year: Dict[Tuple[str, int], int] = defaultdict(int)
    player_tx_all: Dict[str, int] = defaultdict(int)
    player_drop_all: Dict[str, int] = defaultdict(int)

    def _player_display_name(pid: Any) -> str:
        pid_str = str(pid)
        return pid_meta.get(pid_str, {}).get("full_name") or pid_str

    # Internal ledger helpers
    # key: (season, week, roster_id) -> opponent roster_id + opponent points
    opp_rid_map: Dict[Tuple[int, int, int], Optional[int]] = {}
    opp_pf_map: Dict[Tuple[int, int, int], Optional[float]] = {}
    stage_label_map: Dict[Tuple[int, int, int], Optional[str]] = {}
    playoff_start_by_season: Dict[int, Optional[int]] = {}
    roster_ids_by_season: Dict[int, List[int]] = {}
    roster_to_team_by_season: Dict[int, Dict[int, str]] = {}
    draft_rounds_by_season: Dict[int, int] = {}
    included_draft_rounds_by_season: Dict[int, int] = {}

    # Draft pick ownership ledger
    # key: (season, round, original_owner_id) -> current_owner_id
    pick_current_owner: Dict[Tuple[int, int, int], int] = {}
    pick_trade_events: Dict[Tuple[int, int, int], List[Tuple[Optional[datetime], int, int, Optional[int]]]] = {}
    pick_holdings: Dict[Tuple[int, int, int], List[int]] = defaultdict(list)

    def _ensure_pick_bases(target_season: int, source_season: int) -> None:
        if target_season < 2021:
            return
        rounds = draft_rounds_by_season.get(target_season) or draft_rounds_by_season.get(source_season)
        roster_ids = roster_ids_by_season.get(target_season) or roster_ids_by_season.get(source_season) or []
        if not rounds or not roster_ids:
            return
        draft_rounds_by_season.setdefault(target_season, int(rounds))
        roster_ids_by_season.setdefault(target_season, list(roster_ids))
        for rnd in range(1, int(rounds) + 1):
            for rid in roster_ids:
                key = (int(target_season), int(rnd), int(rid))
                if key in pick_current_owner:
                    continue
                pick_current_owner[key] = int(rid)
                pick_trade_events[key] = []
                pick_holdings[(int(target_season), int(rnd), int(rid))].append(int(rid))

    def _format_pick_number(season: int, round_num: Optional[int], pick_no: Optional[int]) -> Optional[str]:
        if round_num is None:
            return None
        team_count = len(roster_ids_by_season.get(season, [])) or None
        if pick_no is None or team_count is None:
            return f"{int(round_num)}.??"
        slot = ((int(pick_no) - 1) % int(team_count)) + 1
        return f"{int(round_num)}.{slot:02d}"

    def _format_pick_label(season: int, round_num: Optional[int], pick_no: Optional[int]) -> Optional[str]:
        num = _format_pick_number(season, round_num, pick_no)
        if num is None:
            return None
        return f"{int(season)} {num}"

    def _slot_for_roster(season: int, roster_id: int) -> Optional[int]:
        roster_ids = sorted(roster_ids_by_season.get(season, []))
        if not roster_ids:
            return None
        try:
            return roster_ids.index(int(roster_id)) + 1
        except ValueError:
            return None

    def _select_pick_key(
        season: int,
        round_num: int,
        prev_owner: int,
        original_owner: Optional[int],
    ) -> Optional[Tuple[int, int, int]]:
        if original_owner is not None:
            key = (int(season), int(round_num), int(original_owner))
            if key in pick_current_owner:
                return key
        candidates = pick_holdings.get((int(season), int(round_num), int(prev_owner)), [])
        if len(candidates) == 1:
            return (int(season), int(round_num), int(candidates[0]))
        if candidates:
            return (int(season), int(round_num), int(sorted(candidates)[0]))
        return None

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
    traded_picks_by_season: Dict[int, List[Dict[str, Any]]] = {}
    season_roster_to_team: Dict[int, Dict[int, str]] = {}
    season_team_to_roster: Dict[int, Dict[str, int]] = {}
    season_draft_picks_all: Dict[int, List[Dict[str, Any]]] = {}
    draft_picks_records: List[Dict[str, Any]] = []

    for lg in leagues:
        league_id = str(lg.get("league_id"))
        season = _to_int(lg.get("season"), 0) or 0

        # playoff start week (Sleeper setting)
        settings = lg.get("settings") or {}
        playoff_start = _to_int(settings.get("playoff_week_start"), None)
        playoff_start_by_season[season] = playoff_start

        # cache played_by_week
        if season not in played_by_week_by_season:
            played_by_week_by_season[season] = _played_teams_by_week(games, season) if not games.empty else {}
        played_by_week = played_by_week_by_season.get(season, {})

        # nflverse weekly player stats (team-by-week + played detection)
        player_team_by_week: Dict[Tuple[str, int], str] = {}
        player_pos_by_week: Dict[Tuple[str, int], str] = {}
        # Season-level fallback team for each player. Used when a specific week
        # has no stats row (player injured / inactive / on bye / suspended) —
        # the right answer is "the team they were on that season," not "the
        # team they're on today." Fixes A.J. Brown 2021 wks 4/12-15 (was PHI,
        # should be TEN), Cooper Kupp 2022 wk11+ (was SEA, should be LAR), etc.
        player_season_team: Dict[str, str] = {}
        played_players_by_week: Dict[int, set] = {}
        try:
            spw = _safe_df(load_nflverse_stats_player_week(ext, season))
            if (not spw.empty) and ("player_id" in spw.columns) and ("week" in spw.columns):
                spw["week"] = pd.to_numeric(spw["week"], errors="coerce").astype("Int64")
                spw["player_id"] = spw["player_id"].astype(str)
                # nflverse has used 'recent_team' historically and 'team' in current releases.
                # Accept either; older code only checked 'recent_team' and silently produced
                # an empty mapping for every season, which is why NFL team / Position columns
                # were stuck on the live Sleeper snapshot for all historical rows.
                team_col = "recent_team" if "recent_team" in spw.columns else ("team" if "team" in spw.columns else None)
                if team_col:
                    spw[team_col] = spw[team_col].astype(str)
                    for r in spw[["player_id", "week", team_col]].dropna().itertuples(index=False):
                        player_team_by_week[(str(r.player_id), int(r.week))] = str(getattr(r, team_col))
                    try:
                        modes = (
                            spw[["player_id", team_col]].dropna()
                            .groupby("player_id")[team_col]
                            .agg(lambda s: s.mode().iat[0] if not s.mode().empty else None)
                        )
                        for pid_x, tm_x in modes.items():
                            if tm_x and str(tm_x) != "nan":
                                player_season_team[str(pid_x)] = str(tm_x)
                    except Exception as e:
                        _log_exc(debug, f"player_season_team_{season}", e)
                if "position" in spw.columns:
                    spw["position"] = spw["position"].astype(str)
                    for r in spw[["player_id", "week", "position"]].dropna().itertuples(index=False):
                        player_pos_by_week[(str(r.player_id), int(r.week))] = str(r.position).upper()
                for wk_i, g in spw.groupby("week"):
                    if pd.isna(wk_i):
                        continue
                    played_players_by_week[int(wk_i)] = set(g["player_id"].dropna().astype(str).tolist())

                # Build cross-season per-player game log so the
                # transactions polish pass can compute pre-pickup PPG
                # for players who weren't yet rostered (rookies, UFAs).
                # nflverse uses GSIS player_ids; bridge to Sleeper IDs
                # via pid_meta.
                try:
                    gsis_to_sid = {
                        str((meta or {}).get("gsis_id") or "").strip(): str(sid)
                        for sid, meta in pid_meta.items()
                        if (meta or {}).get("gsis_id")
                    }
                    gsis_to_sid.pop("", None)
                    if gsis_to_sid:
                        pts_col = "fantasy_points_ppr" if "fantasy_points_ppr" in spw.columns else (
                            "fantasy_points" if "fantasy_points" in spw.columns else None
                        )
                        if pts_col:
                            for r in spw[["player_id", "week", pts_col]].dropna(subset=["player_id", "week"]).itertuples(index=False):
                                gsis = str(r.player_id)
                                sid = gsis_to_sid.get(gsis)
                                if not sid:
                                    continue
                                try:
                                    wk = int(r.week)
                                    pts = float(getattr(r, pts_col))
                                except Exception:
                                    continue
                                # Approx Thursday-of-week date for sorting.
                                try:
                                    wk_d = date(int(season), 9, 7) + timedelta(days=7 * (wk - 1))
                                    wk_iso = wk_d.isoformat()
                                except Exception:
                                    wk_iso = ""
                                nfl_log_by_sid[sid].append({
                                    "year": int(season),
                                    "week": wk,
                                    "points": pts,
                                    "_wk_date": wk_iso,
                                })
                except Exception as e:
                    _log_exc(debug, f"nfl_log_by_sid_{season}", e)
        except Exception as e:
            _log_exc(debug, f"load_nflverse_stats_player_week_{season}", e)

        # nflverse injuries (optional; used as secondary signal)
        try:
            injuries = _safe_df(load_nflverse_injuries(ext, season))
        except Exception as e:
            injuries = pd.DataFrame()
            _log_exc(debug, f"load_nflverse_injuries_{season}", e)

            # placeholder to anchor following logic (keep in scope)
        injuries_by_gsis_week: Dict[Tuple[str, int], Tuple[Optional[bool], Optional[bool]]] = {}
        if not injuries.empty and "gsis_id" in injuries.columns:
            try:
                inj_df = injuries.copy()
                inj_df["season"] = pd.to_numeric(inj_df.get("season"), errors="coerce").astype("Int64")
                inj_df["week"] = pd.to_numeric(inj_df.get("week"), errors="coerce").astype("Int64")
                inj_df["gsis_id"] = inj_df["gsis_id"].astype(str)
                status_col = _first_col(
                    inj_df,
                    ["report_status", "status", "game_status", "injury_status", "practice_status"],
                )
                if status_col:
                    for (gsis, yr, wk), grp in inj_df.groupby(["gsis_id", "season", "week"]):
                        if pd.isna(wk) or pd.isna(yr):
                            continue
                        s = str(grp.iloc[0].get(status_col) or "").lower()
                        suspension = ("susp" in s) or ("sspd" in s)
                        injury = (("out" in s) or ("ir" in s) or ("inactive" in s) or ("pup" in s)) and not suspension
                        injuries_by_gsis_week[(gsis, int(yr), int(wk))] = (injury, suspension)
            except Exception as e:
                _log_exc(debug, f"injury_index_{season}", e)

        # Overlay curated suspensions (data/suspensions.csv). nflverse's injury
        # feed is the NFL's official game-status report and does NOT list
        # suspended players (they're simply absent from the roster). Without
        # this overlay, Suspension? would always be False for every player and
        # year. Each row expands to (gsis_id, season, week) keys for the
        # inclusive range [week_start, week_end].
        try:
            susp_path = repo_root / "data" / "suspensions.csv"
            if susp_path.exists():
                susp_df = pd.read_csv(susp_path)
                for _, srow in susp_df.iterrows():
                    if int(srow.get("season", 0)) != int(season):
                        continue
                    g = str(srow.get("gsis_id") or "").strip()
                    if not g:
                        continue
                    try:
                        wks = int(srow.get("week_start", 0))
                        wke = int(srow.get("week_end", 0))
                    except Exception:
                        continue
                    if wks <= 0 or wke <= 0 or wke < wks:
                        continue
                    for wk_n in range(wks, wke + 1):
                        injuries_by_gsis_week[(g, int(season), int(wk_n))] = (False, True)
        except Exception as e:
            _log_exc(debug, f"suspensions_overlay_{season}", e)

        # Overlay curated injuries (data/injuries.csv). The nflverse injury
        # report only covers weeks a player is on the active roster with a
        # game-status question — players on season-ending IR usually drop off
        # the report entirely, so the file doesn't say "Out" for those weeks.
        # This overlay marks season-ending and multi-week IR stints that the
        # nflverse feed misses. Only sets Injury? if the key doesn't already
        # carry a suspension (suspension always wins).
        try:
            inj_path = repo_root / "data" / "injuries.csv"
            if inj_path.exists():
                inj_overlay_df = pd.read_csv(inj_path)
                for _, irow in inj_overlay_df.iterrows():
                    if int(irow.get("season", 0)) != int(season):
                        continue
                    g = str(irow.get("gsis_id") or "").strip()
                    if not g:
                        continue
                    try:
                        wks = int(irow.get("week_start", 0))
                        wke = int(irow.get("week_end", 0))
                    except Exception:
                        continue
                    if wks <= 0 or wke <= 0 or wke < wks:
                        continue
                    for wk_n in range(wks, wke + 1):
                        existing = injuries_by_gsis_week.get((g, int(season), int(wk_n)))
                        # Don't overwrite a confirmed suspension
                        if existing is not None and existing[1] is True:
                            continue
                        injuries_by_gsis_week[(g, int(season), int(wk_n))] = (True, False)
        except Exception as e:
            _log_exc(debug, f"injuries_overlay_{season}", e)

        # Gap-fill heuristic: for every player who has at least one nflverse
        # weekly stats row this season AND every week between the season's first
        # and last played week, mark Injury?=True for the missing weeks.
        # Catches mid-season IR stints (Aaron Jones 2025 wks 3-5, Adam Thielen
        # 2024 wks 4-9) AND end-of-season IRs (Travis Hunter 2025 wks 10-17,
        # Michael Penix Jr 2025 wks 12-17) in one pass.
        #
        # Conservative: only fires for players who played at least one nflverse
        # game in the season (so we never invent injuries for never-active
        # backups), and never overwrites an existing key (so the curated
        # suspensions / injuries overlays and nflverse Out reports still win).
        played_by_gsis_season: Dict[str, set] = defaultdict(set)
        try:
            if played_players_by_week:
                season_max_week = 0
                for wk_i, played_set in played_players_by_week.items():
                    try:
                        wk_int = int(wk_i)
                    except Exception:
                        continue
                    if wk_int > season_max_week:
                        season_max_week = wk_int
                    for pid_s in played_set:
                        pid_clean = str(pid_s).strip()
                        if pid_clean:
                            played_by_gsis_season[pid_clean].add(wk_int)
                for gsis_s, played_weeks in played_by_gsis_season.items():
                    if not played_weeks:
                        continue
                    for wk in range(1, int(season_max_week) + 1):
                        if wk in played_weeks:
                            continue
                        key = (gsis_s, int(season), int(wk))
                        if key in injuries_by_gsis_week:
                            continue
                        injuries_by_gsis_week[key] = (True, False)
        except Exception as e:
            _log_exc(debug, f"injury_gap_fill_{season}", e)

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
            raw_name = user_handle.get(roster_owner[rid], f"Roster {rid}")
            canon = _norm_team_name(raw_name)
            # Preserve a stable display name for this canonical team key.
            if 'team_display' not in locals():
                team_display = {}
            if canon not in team_display:
                team_display[canon] = str(raw_name)
            roster_to_team[rid] = team_display[canon]

        season_roster_to_team[season] = dict(roster_to_team)
        season_team_to_roster[season] = {
            _norm_team_name(v): k for k, v in roster_to_team.items() if v is not None
        }

        # Gap-fill (part 2): full-season absences. A player on a fantasy roster
        # who NEVER appeared in nflverse weekly stats this season is almost
        # always a season-ending injury sustained before he had a chance to
        # play (Gus Edwards 2021 ACL, J.J. McCarthy 2024 meniscus, Cam Akers
        # 2021 Achilles, Jordan Travis 2024 broken leg, etc.). Mark every week
        # as Injury?=True so Hardship / Weeks of injuries reflect reality.
        try:
            if season_max_week_for_fill := (max(played_players_by_week.keys()) if played_players_by_week else 0):
                rostered_gsis: set = set()
                for r in rosters or []:
                    for pid_r in (r.get("players") or []):
                        gsis_r = (pid_meta.get(str(pid_r), {}) or {}).get("gsis_id")
                        if not gsis_r:
                            # Try DP and legacy mappings for completeness.
                            gsis_r = (
                                dp_sleeper_to_gsis.get(str(pid_r))
                                or sleeper_to_gsis.get(str(pid_r))
                            )
                        if gsis_r:
                            rostered_gsis.add(str(gsis_r).strip())
                for gsis_r in rostered_gsis:
                    if not gsis_r:
                        continue
                    # If this player has any nflverse appearance, the earlier
                    # gap-fill (part 1) already filled their gaps. Skip.
                    if played_by_gsis_season.get(gsis_r):
                        continue
                    for wk in range(1, int(season_max_week_for_fill) + 1):
                        key = (gsis_r, int(season), int(wk))
                        if key in injuries_by_gsis_week:
                            continue
                        injuries_by_gsis_week[key] = (True, False)
        except Exception as e:
            _log_exc(debug, f"injury_gap_fill_never_played_{season}", e)

        # traded picks snapshot (used for pick history reconstruction)
        try:
            traded_picks = sc.traded_picks(league_id) or []
            traded_picks_by_season[season] = traded_picks
        except Exception as e:
            traded_picks = []
            traded_picks_by_season[season] = []
            _log_exc(debug, f"traded_picks_{season}", e)

        # raw snapshots
        try:
            (raw_dir / f"league_{season}.json").write_text(json.dumps(lg, indent=2))
            (raw_dir / f"users_{season}.json").write_text(json.dumps(users, indent=2))
            (raw_dir / f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))
        except Exception:
            pass

        
        # traded picks raw snapshot (for future draft capital / tanking + debugging)
        try:
            (raw_dir / f"traded_picks_{season}.json").write_text(json.dumps(traded_picks, indent=2))
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
            max_round = 0
            picks_with_players = 0
            rookie_picks = 0
            for p in picks or []:
                rnd = _to_int(p.get("round"), None)
                if rnd is not None:
                    max_round = max(max_round, int(rnd))
                pid = p.get("player_id")
                if _valid_pid(pid):
                    picks_with_players += 1
                    if is_rookie_pid(pid, season):
                        rookie_picks += 1
            if max_round == 5:
                continue
            if max_round > 0 and max_round > 5:
                continue
            if picks_with_players == 0:
                continue
            if (rookie_picks / float(picks_with_players)) <= 0.5:
                continue
            if max_round:
                included_draft_rounds_by_season[season] = max(
                    included_draft_rounds_by_season.get(season, 0),
                    int(max_round),
                )
            for p in picks or []:
                p["draft_id"] = did
                p["draft_season"] = season
            draft_picks_all.extend(picks or [])

        season_draft_picks_all[int(season)] = list(draft_picks_all)
        draft_picks_records.extend(draft_picks_all)

        for p in draft_picks_all:
            rnd = _to_int(p.get("round"), None)
            pick_no = _to_int(p.get("pick_no"), None)
            roster_id = _to_int(p.get("roster_id"), None)
            # Note: Sleeper's `picked_by` is a USER_ID (long string), not a
            # roster_id. Using it as a roster_id produces garbage like
            # "Roster 603431474020032512". The team that made the pick is the
            # one stored in `roster_id`. For "Original Team" semantics (who
            # owned the pick before any trades), we look up the chain root in
            # round_chain later; here, default to roster_id as the team-of-pick.
            picked_by_uid = p.get("picked_by")
            player = p.get("player_id")
            origin_rid = roster_id
            team = roster_to_team.get(origin_rid, f"Roster {origin_rid}") if origin_rid is not None else None

            # Draft APIs are not fully consistent; recover display number even when pick_no is missing.
            if rnd is not None and pick_no is not None:
                number = f"R{rnd}.{pick_no}"
            elif rnd is not None:
                number = f"R{rnd}"
            else:
                number = None

            # Resolve player name from Sleeper player map first, then pick metadata.
            player_name = pid_meta.get(str(player), {}).get("full_name") if player else None
            if not player_name:
                md = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
                player_name = md.get("first_name") and f"{md.get('first_name')} {md.get('last_name','').strip()}".strip()
            if not player_name:
                player_name = p.get("player") or p.get("player_name")

            pick_rows.append({
                "Year": season,
                "Original Team": team,
                "Number": number,
                "Player Picked": player_name,
                "Trade 1": None, "Trade 2": None, "Trade 3": None, "Trade 4": None, "Trade 5": None,
                "Trade 6": None, "Trade 7": None, "Trade 8": None, "Trade 9": None, "Trade 10": None,
                "etc": None,
            })

        # If draft picks are unavailable, synthesize pick-history skeleton rows from traded_picks.
        if not draft_picks_all and traded_picks:
            for tp in traded_picks:
                yr = _to_int(tp.get("season"), season)
                rnd = _to_int(tp.get("round"), None)
                prev = _to_int(tp.get("previous_owner_id") or tp.get("previous_owner") or tp.get("previous_owner_roster_id"), None)
                owner = _to_int(tp.get("owner_id") or tp.get("roster_id") or tp.get("owner_roster_id"), None)
                if yr is None or rnd is None or prev is None:
                    continue
                row = {
                    "Year": int(yr),
                    "Original Team": roster_to_team.get(int(prev), f"Roster {prev}"),
                    "Number": f"R{int(rnd)}",
                    "Player Picked": "Unknown",
                    "Trade 1": roster_to_team.get(int(owner), f"Roster {owner}") if owner is not None and int(owner) != int(prev) else None,
                    "Trade 2": None,
                    "Trade 3": None,
                    "Trade 4": None,
                    "Trade 5": None,
                    "Trade 6": None,
                    "Trade 7": None,
                    "Trade 8": None,
                    "Trade 9": None,
                    "Trade 10": None,
                    "etc": "Sourced from traded_picks fallback",
                }
                pick_rows.append(row)

        # robust last completed week
        try:
            last_week = last_completed_week(league_id, season)
        except Exception as e:
            last_week = 0
            _log_exc(debug, f"last_completed_week_{season}", e)

        # Preseason / in-progress league with no completed games: still scan a
        # few weeks so offseason transactions (rookie-draft pick swaps, trades,
        # free-agent adds) flow into trades.csv / transactions.csv. The
        # team_week / player_week construction inside the loop will produce
        # empty rows for unplayed weeks; those self-filter at output time.
        preseason_only = last_week <= 0
        if preseason_only:
            _log(debug, f"[{_now_iso()}] INFO season {season}: preseason — scanning offseason transactions only")
            last_week = 1

        # Exclude week 18 always; if season < 2021 exclude week 17 (kept for future ESPN import)
        def week_allowed(wk: int) -> bool:
            if wk == 18:
                return False
            if season < 2021 and wk == 17:
                return False
            return True

        # storage for week/team scoring for expected win, etc.
        team_pf_by_week: Dict[int, Dict[str, float]] = defaultdict(dict)
        semis_bonus_by_week: Dict[int, Dict[int, float]] = defaultdict(dict)

        # ------------- Pre-fetch all weekly matchups & transactions -------------
        matchups_by_week: Dict[int, List[Dict[str, Any]]] = {}
        tx_by_week: Dict[int, List[Dict[str, Any]]] = {}
        seen_tx_ids: Set[str] = set()
        # bids_per_player_week[(season, wk, player_id)] = total waiver
        # attempts (complete + failed) targeting that player in that week.
        # Sleeper doesn't ship a 'num_bids' field; we derive it by counting
        # waiver transactions BEFORE filtering out failed claims, so the
        # winning row can carry the contested-bid count for downstream
        # display.
        bids_per_player_week: Dict[Tuple[int, int, str], int] = defaultdict(int)
        # total_bids_amount_per_player_week — sum of waiver_bid amounts
        # across all attempts (winner + losers) on the same player that
        # week. Surfaces on transactions.csv as 'Total FAAB bid' so the
        # context for a winning bid is visible: e.g. a 5-FAAB win that
        # beat a single 1-FAAB bid is much less impressive than a
        # 5-FAAB win that beat 4 other bids summing to 50.
        total_bids_amount_per_player_week: Dict[Tuple[int, int, str], float] = defaultdict(float)
        # bid_amounts_per_player_week — full sorted list of competing bid
        # amounts. Powers the 'FAAB difference over second place' and
        # 'FAAB % difference over second place' columns: how decisively
        # did the winner outbid the runner-up.
        bid_amounts_per_player_week: Dict[Tuple[int, int, str], List[float]] = defaultdict(list)

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
                raw_tx = sc.transactions(wk, league_id) or []
                deduped_tx: List[Dict[str, Any]] = []
                for t in raw_tx:
                    tx_id = t.get("transaction_id")
                    if tx_id is None:
                        deduped_tx.append(t)
                        continue
                    tx_id_str = str(tx_id)
                    if tx_id_str in seen_tx_ids:
                        continue
                    seen_tx_ids.add(tx_id_str)
                    deduped_tx.append(t)

                # Sleeper-data quirk dedup. The transaction_id check above
                # catches verbatim duplicates only — Sleeper sometimes emits
                # two distinct transaction_ids for what's logically the same
                # event:
                #   (a) Duplicate waiver claim — same creator, same adds set,
                #       within 60 seconds; one has Player Dropped=None and
                #       the other carries the real drop. Keep the row with
                #       the drop, discard the bare one.
                #   (b) Inverted commissioner swap — same timestamp, two
                #       rows with adds/drops mirrored. Keep the one whose
                #       smallest-added-pid is alphabetically first.
                # Doing this here (before the per-week tx_count / faab
                # counters consume the list) keeps team_week / team_year
                # FAAB consistent with transactions.csv.
                def _tx_ts(t: Dict[str, Any]) -> int:
                    try:
                        return int(t.get("created") or 0)
                    except Exception:
                        return 0
                def _tx_adds(t: Dict[str, Any]) -> Tuple[str, ...]:
                    a = t.get("adds") or {}
                    if not isinstance(a, dict):
                        return tuple()
                    return tuple(sorted(str(k) for k in a.keys()))
                def _tx_drops(t: Dict[str, Any]) -> Tuple[str, ...]:
                    d = t.get("drops") or {}
                    if not isinstance(d, dict):
                        return tuple()
                    return tuple(sorted(str(k) for k in d.keys()))

                deduped_tx.sort(key=lambda t: (_tx_ts(t), t.get("transaction_id") or ""))
                pruned: List[Dict[str, Any]] = []
                for t in deduped_tx:
                    t_ts = _tx_ts(t)
                    t_adds = _tx_adds(t)
                    t_drops = _tx_drops(t)
                    t_creator = str(t.get("creator") or "")
                    replaced = False
                    drop_self = False
                    for idx in range(len(pruned) - 1, -1, -1):
                        p = pruned[idx]
                        p_ts = _tx_ts(p)
                        if t_ts and p_ts and abs(t_ts - p_ts) > 60_000:
                            break  # outside 60-second window
                        p_adds = _tx_adds(p)
                        p_drops = _tx_drops(p)
                        p_creator = str(p.get("creator") or "")
                        # Case (a): same creator, same adds, drops differ by
                        # one side being empty.
                        if (
                            t_creator and p_creator and t_creator == p_creator
                            and t_adds == p_adds
                        ):
                            if not p_drops and t_drops:
                                pruned[idx] = t
                                replaced = True
                                break
                            if not t_drops and p_drops:
                                drop_self = True
                                break
                        # Case (b): identical timestamp, inverted swap.
                        if t_ts and p_ts and t_ts == p_ts:
                            if t_adds == p_drops and t_drops == p_adds and t_adds and t_drops:
                                # Inverted view of one event. Keep the
                                # alphabetically-earlier adds tuple.
                                if t_adds < p_adds:
                                    pruned[idx] = t
                                drop_self = True
                                break
                    if replaced or drop_self:
                        continue
                    pruned.append(t)

                # Count waiver attempts per player BEFORE filtering out the
                # failed claims. Sleeper returns every team's waiver bid as
                # its own transaction (one status=complete winner, plus
                # status=failed for each losing bid). The losing bids never
                # actually moved the player and shouldn't pollute tx_count,
                # FAAB-spent, or transactions.csv — but we want the count
                # of contested bids on the winning row.
                for t in pruned:
                    if t.get("type") != "waiver":
                        continue
                    adds_for_count = t.get("adds") or {}
                    if not isinstance(adds_for_count, dict):
                        continue
                    bid_settings = t.get("settings") or {}
                    bid_amt = 0.0
                    if isinstance(bid_settings, dict):
                        try:
                            bid_amt = float(bid_settings.get("waiver_bid") or 0)
                        except Exception:
                            bid_amt = 0.0
                    for pid_key in adds_for_count.keys():
                        key = (int(season), int(wk), str(pid_key))
                        bids_per_player_week[key] += 1
                        total_bids_amount_per_player_week[key] += bid_amt
                        bid_amounts_per_player_week[key].append(float(bid_amt))

                # Drop failed transactions. Sleeper's status taxonomy:
                #   complete -> the move actually happened
                #   failed   -> rejected (lost waiver, roster full, etc.)
                # Anything other than 'complete' didn't move players or
                # money and should not appear in the dataset.
                pruned = [t for t in pruned if (t.get("status") or "complete") == "complete"]

                tx_by_week[wk] = pruned
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
                        seed_by_rid = {rid: idx + 1 for idx, (_, rid, *_ ) in enumerate(reg)}
                        top4 = set([rid for _, rid, *_ in reg[:4]])
                        bottom4 = set([rid for _, rid, *_ in reg[4:]])
                        # apply semifinal bonus to higher seeded teams (playoff_start week only)
                        for rid in list(top4):
                            opp = opp_rid_map.get((season, playoff_start, rid))
                            if opp is None:
                                continue
                            if rid < opp and opp in top4:
                                seed_a = seed_by_rid.get(rid)
                                seed_b = seed_by_rid.get(opp)
                                if seed_a is None or seed_b is None:
                                    continue
                                higher = rid if seed_a < seed_b else opp
                                semis_bonus_by_week[playoff_start][higher] = 5.0
                                higher_team = roster_to_team.get(higher, f"Roster {higher}")
                                lower = opp if higher == rid else rid
                                lower_team = roster_to_team.get(lower, f"Roster {lower}")
                                team_pf_by_week[playoff_start][higher_team] = (
                                    team_pf_by_week[playoff_start].get(higher_team, 0.0) + 5.0
                                )
                                opp_pf_map[(season, playoff_start, lower)] = team_pf_by_week[playoff_start].get(higher_team, 0.0)
                                opp_pf_map[(season, playoff_start, higher)] = team_pf_by_week[playoff_start].get(lower_team, 0.0)
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
        prev_roster_by_team: Dict[str, set] = {}
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
                    ttype = t.get("type")

                    # Date-validity gate. If Sleeper's 'created' timestamp
                    # is missing or unparseable, this transaction can't be
                    # anchored in time — it would emit a row with Date='N/A'
                    # which breaks Link prev/next ordering, Tanking joins,
                    # and (Team, Season) reconciliation. Skip the whole
                    # transaction so tx_count / trade_count / faab_spent
                    # stay row-for-row consistent with the detail CSVs.
                    if _epoch_ms_to_dt(t.get("created")) is None:
                        continue

                    # Resolve every team participating in this transaction via
                    # roster_ids -> roster_to_team. We deliberately do NOT use
                    # user_handle.get(creator) here: user_handle is rebuilt per
                    # season from that season's users feed, so it returns this
                    # season's display name (e.g. "Shmuel256"), which can drift
                    # year-to-year. roster_to_team uses the canonical stable
                    # display name that team_week / team_year rows are keyed by.
                    # Without this, the same manager's tx fragment under two
                    # different team labels and the rollup is wrong.
                    roster_ids_in_tx = [_to_int(r, None) for r in (t.get("roster_ids") or [])]
                    roster_ids_in_tx = [r for r in roster_ids_in_tx if r is not None]
                    teams_in_tx: list[str] = []
                    for rid_ in roster_ids_in_tx:
                        nm = roster_to_team.get(int(rid_))
                        if nm and nm not in teams_in_tx:
                            teams_in_tx.append(nm)

                    # creator_team is only used as a tiebreaker when roster_ids
                    # is empty (rare; mostly placeholder transactions). Resolve
                    # creator -> owner_id -> roster_id -> stable team name when
                    # possible so we still don't go through user_handle directly.
                    creator = str(t.get("creator") or "")
                    creator_team = None
                    if creator and not teams_in_tx:
                        for rid_, owner_ in roster_owner.items():
                            if owner_ == creator:
                                creator_team = roster_to_team.get(rid_)
                                break
                        if creator_team is None:
                            creator_team = user_handle.get(creator)

                    if ttype == "trade":
                        # Credit both sides.
                        for tm in teams_in_tx:
                            trade_count[tm] += 1
                            tx_count[tm] += 1
                    else:
                        # waiver / free_agent / commissioner — credit the
                        # destination roster of EACH add AND the dropping
                        # roster of each drop that doesn't pair with an add
                        # in this same transaction. Net effect:
                        #   - swap (1 add + 1 drop on same roster): +1
                        #   - multi-roster commish swap (2 adds + 2 drops
                        #     across 2 rosters): +1 per roster
                        #   - pure drop (0 adds + N drops on same roster):
                        #     +N (each visible in transactions.csv too)
                        # team_week / team_year 'Number of transactions'
                        # reconciles row-for-row with transactions.csv.
                        adds_dict = t.get("adds") if isinstance(t.get("adds"), dict) else {}
                        drops_dict = t.get("drops") if isinstance(t.get("drops"), dict) else {}
                        # rosters that received an add — each gets +1 here.
                        add_rosters: Set[int] = set()
                        for _pid, _rrid in (adds_dict or {}).items():
                            _rid_i = _to_int(_rrid, None)
                            tm_name = roster_to_team.get(int(_rid_i)) if _rid_i is not None else None
                            if not tm_name:
                                tm_name = (teams_in_tx[0] if teams_in_tx else None) or creator_team
                            if tm_name:
                                tx_count[tm_name] += 1
                                if _rid_i is not None:
                                    add_rosters.add(int(_rid_i))
                        # remaining drops (per roster) become "orphan" drops
                        # for tx_count purposes. Group by roster and credit
                        # +1 per leftover drop after pairing one drop with
                        # each add on the same roster.
                        drops_by_rid_count: Dict[int, int] = defaultdict(int)
                        for _dpid, _drid in (drops_dict or {}).items():
                            _drid_i = _to_int(_drid, None)
                            if _drid_i is None:
                                continue
                            drops_by_rid_count[int(_drid_i)] += 1
                        adds_by_rid_count: Dict[int, int] = defaultdict(int)
                        for _pid, _rrid in (adds_dict or {}).items():
                            _rid_i = _to_int(_rrid, None)
                            if _rid_i is None:
                                continue
                            adds_by_rid_count[int(_rid_i)] += 1
                        for _rid_i, n_drops in drops_by_rid_count.items():
                            n_orphan = max(0, n_drops - adds_by_rid_count.get(_rid_i, 0))
                            if n_orphan <= 0:
                                continue
                            tm_name = roster_to_team.get(int(_rid_i))
                            if not tm_name:
                                tm_name = (teams_in_tx[0] if teams_in_tx else None) or creator_team
                            if tm_name:
                                tx_count[tm_name] += n_orphan

                    # FAAB lives under settings.waiver_bid on Sleeper transactions
                    # (legacy code looked under metadata, which was always empty).
                    settings_obj = t.get("settings") or {}
                    if isinstance(settings_obj, dict):
                        bid = _to_float(settings_obj.get("waiver_bid"), 0.0) or 0.0
                    else:
                        bid = 0.0
                    if not bid:
                        meta = t.get("metadata") or {}
                        if isinstance(meta, dict):
                            bid = _to_float(
                                meta.get("waiver_bid") or meta.get("faab") or 0.0, 0.0
                            ) or 0.0
                    if bid:
                        primary = (teams_in_tx[0] if teams_in_tx else None) or creator_team
                        if primary:
                            faab_spent[primary] += float(bid)
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
                    bonus = semis_bonus_by_week.get(wk, {}).get(rid)
                    if bonus:
                        pf += bonus

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

                    prev = prev_starters_by_team.get(team)
                    cur_s = set([pid for pid in starters if _valid_pid(pid)])
                    if prev is None:
                        turnover = None
                    else:
                        inter = cur_s.intersection(prev)
                        turnover = max(len(cur_s), len(prev)) - len(inter)
                    prev_starters_by_team[team] = cur_s

                    prev_r = prev_roster_by_team.get(team)
                    cur_r = set([pid for pid in players if _valid_pid(pid)])
                    if prev_r is None:
                        roster_turnover = None
                    else:
                        inter_r = cur_r.intersection(prev_r)
                        roster_turnover = max(len(cur_r), len(prev_r)) - len(inter_r)
                    prev_roster_by_team[team] = cur_r

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

                    rook_s = len({pid for pid in starters if is_rookie_pid(pid, season)})
                    rook_r = len({pid for pid in players if is_rookie_pid(pid, season)})

                    approx_date = date(season, 9, 1) + timedelta(days=7 * (wk - 1))
                    ages = [a for a in (_calc_age(pid_meta.get(pid, {}).get("birth_date"), approx_date) for pid in players) if a is not None]
                    avg_age = round(sum(ages) / len(ages), 2) if ages else None

                    def _nfl_team_for_pid_week(pid_val: Any) -> Optional[str]:
                        m = pid_meta.get(str(pid_val), {}) if isinstance(pid_meta, dict) else {}
                        gs = dp_sleeper_to_gsis.get(str(pid_val)) or m.get("gsis_id") or sleeper_to_gsis.get(str(pid_val))
                        tm = (
                            (player_team_by_week.get((str(gs), int(wk))) if gs else None)
                            or (player_season_team.get(str(gs)) if gs else None)
                            or m.get("team")
                        )
                        return _norm_team(tm)

                    roster_nfl_teams = [t for t in (_nfl_team_for_pid_week(pid) for pid in players) if t]
                    start_nfl_teams = [t for t in (_nfl_team_for_pid_week(pid) for pid in starters) if t]
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
                    week_name = label if label else f"Week {wk}"

                    # Skip team_week / player_week rows for preseason weeks
                    # where no games have been played. Transactions / trades
                    # for the same week were already harvested earlier in this
                    # iteration, so 2026 offseason trades still reach
                    # trades.csv without polluting the score tables with
                    # phantom 0-PF rows.
                    if preseason_only:
                        continue
                    team_week_rows.append({
                        "Team": team,
                        "Opponent Team (raw)": opp_team,
                        "Week": wk,
                        "Week Name": week_name,
                        "Year": season,
                        "PF": round(pf, 2),
                        "Win?": win,
                        "Opponent": opp_team,
                        "Week label": label,
                        "Round": _round_from_label(label),
                        "Points against": round(float(opp_points), 2) if opp_points is not None else None,
                        "Margin": round(float(margin), 2) if margin is not None else None,
                        "Max PF": round(max_pf, 2) if max_pf is not None else None,
                        "Efficiency": round(eff, 4) if eff is not None else None,
                        "Number of Injuries": None,         # computed later from player_week
                        "Number of suspensions": None,      # computed later from player_week
                        "Number of players on bye": None,   # computed later from player_week
                        "Largest deficit overcome (if win)": None,
                        "Starter turnover from previous week": turnover,
                        "Roster turnover from previous week": roster_turnover,
                        "Difference in pregame avg max PF from opponent": None,  # computed later
                        "UPST": None,                      # computed later
                        "Hardship": None,                  # computed later
                        "Tanking": None,                   # computed later (needs pick ledger; best effort later)
                        "Luck": round(luck_raw, 4) if luck_raw is not None else None,
                        "Win Variance": round(luck_raw, 4) if luck_raw is not None else None,
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
                        "Number of NFL teams among rostered players": len(set(roster_nfl_teams)) if roster_nfl_teams else None,
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

                    # starter slot labels: map roster positions to labeled starter slots
                    starter_slot = {}
                    roster_positions = [str(x) for x in (lg.get("roster_positions") or []) if x]
                    non_start_slots = {"BN", "BE", "BENCH", "IR", "TAXI"}
                    starter_slots = [pos for pos in roster_positions if str(pos).upper() not in non_start_slots]

                    def _base_slot(pos: str) -> str:
                        upper = str(pos or "").upper()
                        if upper in ("SUPER_FLEX", "SUPERFLEX", "SFLEX", "SFLX"):
                            return "SFLX"
                        if upper in ("FLEX", "FLX"):
                            return "FLX"
                        return upper

                    if starter_slots and starters:
                        counts: Dict[str, int] = {}
                        for pid, slot in zip(starters, starter_slots):
                            base = _base_slot(slot)
                            if not base:
                                continue
                            counts[base] = counts.get(base, 0) + 1
                            idx = counts[base]

                            label = base
                            if base == "RB":
                                label = f"RB{idx}"
                            elif base == "WR":
                                label = f"WR{idx}"
                            elif base == "FLX":
                                label = f"FLX{idx}"
                            elif base == "SFLX":
                                label = "SFLX"
                            elif base == "QB":
                                label = "QB"
                            starter_slot[pid] = label

                    # fallback to player position if starter slot data is missing
                    if not starter_slot:
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
                        position = pid_pos.get(pid)

                        # gsis id lookup for nflverse (pre-indexed for speed/reliability)
                        gsis = (
                            dp_sleeper_to_gsis.get(str(pid))
                            or meta.get("gsis_id")
                            or sleeper_to_gsis.get(str(pid))
                        )

                        # Prefer week-specific nflverse team when available; fallback to Sleeper player meta.
                        nfl_team = (
                            (player_team_by_week.get((str(gsis), int(wk))) if gsis else None)
                            or (player_season_team.get(str(gsis)) if gsis else None)
                            or meta.get("team")
                        )
                        nfl_team = _norm_team(nfl_team)

                        pts = float(ppts.get(pid, 0.0))
                        started = pid in starters
                        slot = starter_slot.get(pid) if started else "N/A"
                        # Position-as-of-week from nflverse weekly stats when present; otherwise
                        # fall back to Sleeper's live position. Handles in-career switchers
                        # (e.g. Taysom Hill QB/TE) and rookies whose Sleeper meta lags.
                        player_position = (
                            (player_pos_by_week.get((str(gsis), int(wk))) if gsis else None)
                            or pid_pos.get(pid)
                            or None
                        )

                        # Bye is schedule-based. If player scored >0 -> not a bye.
                        bye = None
                        if nfl_team and played_set:
                            bye = (_norm_team(nfl_team) not in played_set)
                        if pts > 0:
                            # Player scored points; not a bye week. Do NOT override injury/suspension flags:
                            # a player can play while injured or returning from suspension.
                            bye = False

                        # Flags (platform primary, nflverse secondary)
                        # Injury/suspension (new approach): authoritative nflverse injuries, keyed by gsis_id (via player_ids mapping).
                        # Only mark if the player did NOT play that week (no stats row) and it is not a bye.
                        inj = False
                        susp = False
                        try:
                            played_players = played_players_by_week.get(int(wk), set())
                            played = bool(gsis) and (str(gsis) in played_players)
                        except Exception:
                            played = False
                        # bye may be None when we couldn't compute it (no NFL team
                        # resolvable + player never had stats this season — e.g.
                        # career-ending injury cases like Gus Edwards 2021, Tarik
                        # Cohen 2021). Treat None like False so we still consider
                        # the player injured when they have pts=0 and no
                        # contradicting suspension entry.
                        if ((pts or 0.0) == 0.0) and (bye is not True) and (not played) and gsis:
                            existing = injuries_by_gsis_week.get((str(gsis), season, int(wk)))
                            if existing is not None and existing[1] is True:
                                # Confirmed suspension wins.
                                susp = True
                                inj = False
                            else:
                                # Player was rostered, scored 0, not on bye, did
                                # not appear in nflverse stats — they were
                                # missing for some reason. Default to injury.
                                # Captures full-season IR cases the per-season
                                # gap-fill couldn't see because the player was
                                # dropped from the roster before season end.
                                inj = True
                                susp = False

                        # Fallback injury/suspension inference (Sleeper metadata is not historical but fixes obvious cases):
                        # If the player scored 0, was not on bye, and Sleeper marks them OUT/IR/SUSP, treat as missed.
                        if (pts or 0.0) == 0.0 and bye is False:
                            meta_p = pid_meta.get(str(pid), {}) if isinstance(pid_meta, dict) else {}
                            st = str(meta_p.get("status") or "").lower()
                            inj_st = str(meta_p.get("injury_status") or meta_p.get("injuryStatus") or "").lower()
                            # suspension signals
                            if ("susp" in st) or ("susp" in inj_st):
                                susp = True
                                inj = False if inj is None else inj
                            # injury signals
                            elif any(x in (st + " " + inj_st) for x in ["out", "ir", "inactive", "pup", "doubtful"]):
                                inj = True

                        if inj is None:
                            inj = False
                        if susp is None:
                            susp = False
                        if susp:
                            inj = False
                        if bye is None:
                            bye = False

                        rookie = is_rookie_pid(pid, season)
                        age = _calc_age(meta.get("birth_date"), approx_date)

                        diff_best_bench = (pts - best_bench_pts) if (started and best_bench_pts is not None) else None
                        diff_worst_starter = (pts - worst_starter_pts) if ((not started) and worst_starter_pts is not None) else None
                        ref_player = None
                        if started and best_bench_pid:
                            ref_player = pid_meta.get(best_bench_pid, {}).get("full_name") or best_bench_pid
                        elif (not started) and worst_starter_pid:
                            ref_player = pid_meta.get(worst_starter_pid, {}).get("full_name") or worst_starter_pid

                        if preseason_only:
                            continue
                        player_week_rows.append({
                            "Player ID": str(pid) if pid is not None else None,
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
                            "Position": player_position,
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
                    # For waivers, 'created' is when the bid was
                    # submitted but 'status_updated' is when the waiver
                    # actually ran and the player moved. A single
                    # submission date can be misleading when waivers
                    # span multiple processing days — we've seen pairs
                    # of claims submitted within minutes that actually
                    # resolved on different days. Prefer status_updated
                    # for waiver-type transactions; for free_agent,
                    # commissioner, and trades the events resolve at
                    # creation, so 'created' is correct.
                    _t_type = t.get("type")
                    _resolve_ms = t.get("status_updated") if _t_type == "waiver" else None
                    if _resolve_ms is None:
                        _resolve_ms = t.get("created")
                    created_date = _epoch_ms_to_date(_resolve_ms)
                    created_dt = _epoch_ms_to_dt(_resolve_ms)
                    # Mirror the date-validity gate from Loop 1 (per-week
                    # counters). If we can't anchor the transaction in
                    # time, don't emit a row — the matching tx_count
                    # entry was already skipped upstream.
                    if created_dt is None:
                        continue
                    creator = str(t.get("creator") or "")
                    # Resolve via the canonical roster_to_team mapping so the
                    # 'Team' column in the output stays consistent across
                    # seasons even if the manager renames themselves on
                    # Sleeper (e.g. shmuel256 / Shmuel256). roster_ids in the
                    # transaction usually has exactly one entry for non-trade
                    # actions; fall back to user_handle when there's no
                    # resolvable roster_id (rare).
                    team = None
                    try:
                        tx_roster_ids = [_to_int(r, None) for r in (t.get("roster_ids") or [])]
                        for rid_ in tx_roster_ids:
                            if rid_ is None:
                                continue
                            nm = roster_to_team.get(int(rid_))
                            if nm:
                                team = nm
                                break
                    except Exception:
                        team = None
                    if not team and creator:
                        # creator -> owner_id -> roster_id -> canonical team
                        for rid_, owner_ in roster_owner.items():
                            if owner_ == creator:
                                team = roster_to_team.get(rid_)
                                if team:
                                    break
                    if not team and creator:
                        team = user_handle.get(creator)

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

                        # update pick ledger with trade order
                        if draft_picks:
                            for dp in [x for x in draft_picks if isinstance(x, dict)]:
                                dp_season = _to_int(dp.get("season"), season)
                                dp_round = _to_int(dp.get("round"), None)
                                prev_owner = _to_int(
                                    dp.get("previous_owner_id") or dp.get("previous_owner") or dp.get("previous_owner_roster_id"),
                                    None,
                                )
                                new_owner = _to_int(
                                    dp.get("owner_id") or dp.get("roster_id") or dp.get("owner_roster_id"),
                                    None,
                                )
                                original_owner = _to_int(dp.get("original_owner_id") or dp.get("original_owner"), None)
                                if prev_owner is None and new_owner is not None and len(roster_ids_int) == 2:
                                    prev_owner = [rid for rid in roster_ids_int if rid != new_owner][0]
                                if dp_season is None or dp_round is None or prev_owner is None or new_owner is None:
                                    continue
                                _ensure_pick_bases(int(dp_season), season)
                                key = _select_pick_key(int(dp_season), int(dp_round), int(prev_owner), original_owner)
                                if not key:
                                    _log(
                                        debug,
                                        f"[{_now_iso()}] WARN pick ledger unresolved: season={dp_season} round={dp_round} prev={prev_owner} new={new_owner} orig={original_owner}",
                                    )
                                    continue
                                pick_holdings[(key[0], key[1], int(prev_owner))] = [
                                    oid for oid in pick_holdings.get((key[0], key[1], int(prev_owner)), []) if oid != key[2]
                                ]
                                pick_holdings[(key[0], key[1], int(new_owner))].append(int(key[2]))
                                pick_holdings[(key[0], key[1], int(new_owner))] = sorted(
                                    set(pick_holdings[(key[0], key[1], int(new_owner))])
                                )
                                pick_current_owner[key] = int(new_owner)
                                pick_trade_events.setdefault(key, []).append(
                                    (created_dt, int(prev_owner), int(new_owner), int(wk)),
                                )

                        # received assets by team (display names) plus a
                        # parallel mapping of sleeper player ids for KTC
                        # value lookups downstream.
                        recv_players: Dict[int, List[str]] = defaultdict(list)
                        recv_player_ids: Dict[int, List[str]] = defaultdict(list)
                        for pid, rrid in adds.items():
                            rr = _to_int(rrid, None)
                            if rr is None:
                                continue
                            recv_players[rr].append(pid_meta.get(str(pid), {}).get("full_name") or str(pid))
                            recv_player_ids[rr].append(str(pid))

                        recv_picks: Dict[int, List[str]] = defaultdict(list)
                        for dp in draft_picks:
                            if not isinstance(dp, dict):
                                continue
                            owner_id = _to_int(dp.get("owner_id"), None)
                            if owner_id is None:
                                continue
                            dp_season = _to_int(dp.get("season"), season)
                            dp_round = _to_int(dp.get("round"), None)
                            if dp_round is None:
                                continue
                            label = _format_pick_label(int(dp_season), dp_round, None)
                            if label:
                                recv_picks[owner_id].append(label)

                        # Build row per roster in roster_ids_int
                        for rid in roster_ids_int:
                            tm = roster_to_team.get(rid, f"Roster {rid}")
                            others = [roster_to_team.get(o, f"Roster {o}") for o in roster_ids_int if o != rid]
                            received = []
                            received.extend(recv_players.get(rid, []))
                            received.extend(recv_picks.get(rid, []))
                            received_ids = list(recv_player_ids.get(rid, []))
                            received_picks = list(recv_picks.get(rid, []))
                            dropped = []
                            dropped_ids: List[str] = []
                            dropped_picks: List[str] = []
                            for o in roster_ids_int:
                                if o == rid:
                                    continue
                                dropped.extend(recv_players.get(o, []))
                                dropped.extend(recv_picks.get(o, []))
                                dropped_ids.extend(recv_player_ids.get(o, []))
                                dropped_picks.extend(recv_picks.get(o, []))
                            trades_rows.append({
                                "Team": tm,
                                "Team's traded with": "; ".join(sorted(set([x for x in others if x]))),
                                "Assets received": "; ".join(received) if received else None,
                                "Assets dropped": "; ".join(dropped) if dropped else None,
                                "Date": created_dt.isoformat() if created_dt else (str(created_date) if created_date else None),
                                "Season": int(season),
                                # Internal-only sleeper ID lists used by the
                                # KTC value lookup pass. Not in the schema
                                # catalog, so they get filtered out before
                                # write_outputs serializes the CSV.
                                "_recv_player_ids": received_ids,
                                "_drop_player_ids": dropped_ids,
                                "_recv_picks": received_picks,
                                "_drop_picks": dropped_picks,
                                # KTC columns — 'at deal time' is computed
                                # by a post-processing pass; the other three
                                # time points stay None until a follow-up
                                # PR populates them.
                                "KTC value difference at deal time": None,
                                "KTC value difference at end of season": None,
                                "KTC value difference 1 year later": None,
                                "KTC value difference 2 years later": None,
                                "Pick value received": None,
                                "Change in pick value at draft time": None,
                                "Assets retained now": None,
                                "Assets traded away": None,
                                "Return from trades": None,
                                "Additional assets traded away in those deals": None,
                                "Return from trades of trades...of trades. Keep going until present day": None,
                                "Asset difference in average age": None,
                                "Tanking": None,
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
                    settings_obj = t.get("settings") or {}
                    # Sleeper exposes the waiver bid on transaction.settings.waiver_bid
                    # (not on metadata, which is almost always null). The previous
                    # code looked at metadata only, so Faab was None for every
                    # transaction, and downstream coercion stamped it as 0.0.
                    faab = None
                    if isinstance(settings_obj, dict):
                        faab = settings_obj.get("waiver_bid")
                    if faab is None and isinstance(meta, dict):
                        faab = meta.get("waiver_bid") or meta.get("faab")
                    # Number of bids: derived in the fetch loop from all
                    # waiver attempts (complete + failed) against the same
                    # player in the same week. Sleeper's API doesn't carry
                    # this on the transaction settings — every field they
                    # do expose (priority, seq, waiver_bid) describes only
                    # THIS team's claim. Resolved per-add below where we
                    # have the player id in hand.
                    num_bids = None  # placeholder; set per-add

                    if not isinstance(adds, dict):
                        adds = {}
                    if not isinstance(drops, dict):
                        drops = {}

                    drops_by_roster: Dict[str, List[str]] = defaultdict(list)
                    for dp, drid in drops.items():
                        drops_by_roster[str(drid)].append(str(dp))
                    for pid, rrid in adds.items():
                        pid = str(pid)
                        rrid_str = str(rrid)
                        player_tx_week[(pid, season, wk)] += 1
                        player_tx_year[(pid, season)] += 1
                        player_tx_all[pid] += 1
                        dropped = None
                        drop_list = drops_by_roster.get(rrid_str)
                        if drop_list:
                            dropped = drop_list.pop(0)
                            if not drop_list:
                                drops_by_roster.pop(rrid_str, None)

                        if dropped:
                            dropped_id = str(dropped)
                            player_tx_week[(dropped_id, season, wk)] += 1
                            player_tx_year[(dropped_id, season)] += 1
                            player_tx_all[dropped_id] += 1
                            player_drop_week[(dropped_id, season, wk)] += 1
                            player_drop_year[(dropped_id, season)] += 1
                            player_drop_all[dropped_id] += 1

                        # Team for THIS specific add = the roster the player
                        # is going TO (rrid). For multi-roster transactions
                        # like commissioner-driven swaps, the outer 'team'
                        # variable points at only the first roster, so a
                        # second add to a different roster needs its own
                        # team resolution. Fall back to the outer 'team' if
                        # rrid doesn't resolve.
                        row_rrid_int = _to_int(rrid_str, None)
                        row_team = (
                            roster_to_team.get(int(row_rrid_int)) if row_rrid_int is not None else None
                        ) or team

                        # Resolve Number of bids, Total FAAB bid, and the
                        # winner-vs-second-place columns from the per-week
                        # tallies. Only meaningful for waiver claims;
                        # free-agent and commissioner adds aren't bid on.
                        row_num_bids = None
                        row_total_faab = None
                        row_faab_diff_2nd = None
                        row_faab_pct_2nd = None
                        if ttype == "waiver":
                            key = (int(season), int(wk), str(pid))
                            row_num_bids = bids_per_player_week.get(key, 0) or None
                            row_total_faab = total_bids_amount_per_player_week.get(key, 0.0) or None
                            # Compute the runner-up from the pre-filter
                            # tally. Two important details:
                            # 1) The winner is the team owning THIS row
                            #    (status=complete). Its bid amount is the
                            #    'faab' value we just read off settings.
                            #    Don't take amounts[0] — Sleeper records
                            #    failed bids alongside the winner, and a
                            #    higher-amount failed bid (roster full,
                            #    not enough FAAB, etc.) would otherwise
                            #    look like 'the winner'.
                            # 2) Any bid > winner_bid_val that ended up
                            #    losing must have been INVALIDATED — a
                            #    valid higher bid would have won the
                            #    auction. Exclude those from runner-up
                            #    consideration; they aren't real competing
                            #    bids. This is what was producing diffs
                            #    larger than the winning bid (e.g. Dont'e
                            #    Thornton showed diff=40 on a 16-FAAB win).
                            winner_bid_val = float(faab) if faab is not None else 0.0
                            competing = list(bid_amounts_per_player_week.get(key, []))
                            try:
                                # Remove exactly one occurrence of the
                                # winning bid (the row we're emitting).
                                # If multiple bids tied at winner_bid_val,
                                # the others are legitimate runners-up.
                                competing.remove(winner_bid_val)
                            except ValueError:
                                pass
                            competing = [b for b in competing if b <= winner_bid_val]
                            if competing:
                                second = max(competing)
                                row_faab_diff_2nd = round(winner_bid_val - second, 2)
                                if second > 0:
                                    row_faab_pct_2nd = round((winner_bid_val - second) / second * 100.0, 2)
                                # If second == 0 the percentage is
                                # undefined; leave % blank but still
                                # surface the absolute difference.

                        transactions_rows.append({
                            "Team": row_team,
                            "Player Added": pid_meta.get(pid, {}).get("full_name") or pid,
                            "Player Dropped": pid_meta.get(dropped, {}).get("full_name") if dropped else None,
                            "type of transaction (waiver/free agency)": ttype,
                            "Faab": faab,
                            "Total FAAB bid": row_total_faab,
                            "FAAB difference over second place": row_faab_diff_2nd,
                            "FAAB % difference over second place": row_faab_pct_2nd,
                            "Date": created_dt.isoformat() if created_dt else (str(created_date) if created_date else None),
                            "Season": int(season),
                            # Internal-only sleeper IDs for the KTC pass.
                            # Filtered out before write_outputs (not in the
                            # plan catalog).
                            "_added_pid": str(pid) if pid else None,
                            "_dropped_pid": str(dropped) if dropped else None,
                            "Number of bids": row_num_bids,
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
                            "Tanking": None,
                            "Number of times picked up by this team": None,
                        })

                    for rrid_orphan_str, drop_list in drops_by_roster.items():
                        for dp_str in drop_list:
                            dropped_id = str(dp_str)
                            player_tx_week[(dropped_id, season, wk)] += 1
                            player_tx_year[(dropped_id, season)] += 1
                            player_tx_all[dropped_id] += 1
                            player_drop_week[(dropped_id, season, wk)] += 1
                            player_drop_year[(dropped_id, season)] += 1
                            player_drop_all[dropped_id] += 1
                            # tx_count for orphan drops is credited in Loop 1
                            # (the per-week tx summary pass earlier) so that
                            # team_week's read of tx_count sees the right
                            # totals.
                            # Record an orphan-drop event so the transactions
                            # polish pass can bound 'Date dropped/traded' /
                            # 'Weeks between pickup and start' correctly.
                            try:
                                rid_int = _to_int(rrid_orphan_str, None)
                                drop_team = roster_to_team.get(int(rid_int)) if rid_int is not None else None
                                drop_player_name = (pid_meta.get(dropped_id, {}) or {}).get("full_name") or dropped_id
                                drop_dt = created_dt.isoformat() if created_dt else (str(created_date) if created_date else None)
                                # Skip orphan-drop emission when we have no
                                # timestamp — the row would be unanchored in
                                # time and pollutes downstream reconciliation.
                                if drop_team and drop_player_name and drop_dt:
                                    orphan_drop_events.append({
                                        "Team": drop_team,
                                        "Player Dropped": drop_player_name,
                                        "Date": drop_dt,
                                    })
                                    # Also emit a transactions.csv row so the
                                    # detail file reconciles with team_year's
                                    # 'Number of transactions' count. Pure drops
                                    # are real transactions in Sleeper and were
                                    # previously invisible — tx_count would
                                    # increment but no row would be written.
                                    transactions_rows.append({
                                        "Team": drop_team,
                                        "Player Added": None,
                                        "Player Dropped": drop_player_name,
                                        "type of transaction (waiver/free agency)": ttype,
                                        "Faab": None,
                                        "Total FAAB bid": None,
                                        "FAAB difference over second place": None,
                                        "FAAB % difference over second place": None,
                                        "Date": drop_dt,
                                        "Season": int(season),
                                        "_added_pid": None,
                                        "_dropped_pid": str(dropped_id) if dropped_id else None,
                                        "Number of bids": None,
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
                                        "Tanking": None,
                                        "Number of times picked up by this team": None,
                                    })
                            except Exception:
                                pass
                except Exception as e:
                    _log_exc(debug, f"transactions_trades_rows_{season}_wk{wk}", e)

    # Ensure pick ledger includes seasons from 2021 through three years after latest draft.
    latest_draft_season = max(
        [r.get("draft_season") for r in draft_picks_records if r.get("draft_season") is not None],
        default=None,
    )
    latest_league_season = max(roster_ids_by_season.keys(), default=None)
    base_season = latest_draft_season or latest_league_season
    if base_season is not None:
        max_future_season = int(base_season) + 3
        seed_source = max(draft_rounds_by_season.keys(), default=int(base_season))
        for yr in range(2021, max_future_season + 1):
            _ensure_pick_bases(int(yr), int(seed_source))

    # --------------------------
    # Convert to DataFrames
    # --------------------------
    pw = pd.DataFrame(player_week_rows)

    if not pw.empty and "Team" in pw.columns:
        pw["_team_canon"] = pw["Team"].apply(_norm_team_name)
        canon_to_disp = {}
        for t in pw["Team"].dropna().astype(str).tolist():
            c=_norm_team_name(t)
            if c and c not in canon_to_disp:
                canon_to_disp[c]=t
        pw["Team"] = pw["_team_canon"].map(canon_to_disp).fillna(pw["Team"])
        pw.drop(columns=["_team_canon"], inplace=True, errors="ignore")
    if not pw.empty and {"Player ID", "Year", "Week"}.issubset(pw.columns):
        pw_keys = pw[["Player ID", "Year", "Week"]].copy()
        pw_keys["Player ID"] = pw_keys["Player ID"].astype(str)
        pw_keys["Year"] = pd.to_numeric(pw_keys["Year"], errors="coerce").astype("Int64")
        pw_keys["Week"] = pd.to_numeric(pw_keys["Week"], errors="coerce").astype("Int64")
        pw["Number of transactions"] = [
            int(player_tx_week.get(
                (
                    str(player_id),
                    int(year) if pd.notna(year) else None,
                    int(week) if pd.notna(week) else None,
                ),
                0,
            ))
            for player_id, year, week in pw_keys.itertuples(index=False, name=None)
        ]
        pw["Number of drops"] = [
            int(player_drop_week.get(
                (
                    str(player_id),
                    int(year) if pd.notna(year) else None,
                    int(week) if pd.notna(week) else None,
                ),
                0,
            ))
            for player_id, year, week in pw_keys.itertuples(index=False, name=None)
        ]
    log_df(pw, 'player_week', sample_cols=['Points','Injury?','Suspension?','Bye?','Starter?'])
    tw = pd.DataFrame(team_week_rows)

    # Normalize team names (case-insensitive) across seasons so joins don't duplicate teams like 'Shmuel256' vs 'shmuel256'.
    if not tw.empty and "Team" in tw.columns:
        tw["_team_canon"] = tw["Team"].apply(_norm_team_name)
        canon_to_disp: Dict[str,str] = {}
        for t in tw["Team"].dropna().astype(str).tolist():
            c=_norm_team_name(t)
            if c and c not in canon_to_disp:
                canon_to_disp[c]=t
        tw["Team"] = tw["_team_canon"].map(canon_to_disp).fillna(tw["Team"])
        tw.drop(columns=["_team_canon"], inplace=True, errors="ignore")
    if not tw.empty:
        log_missing_cols(tw, "team_week", [
            "Year", "Week", "Team", "PF", "Points against", "Margin", "Max PF", "Efficiency"
        ])
        zero_max = int((pd.to_numeric(tw.get("Max PF"), errors="coerce").fillna(0) <= 0).sum())
        LOG.info("team_week: rows=%s zero_max_pf=%s", len(tw), zero_max)
    log_df(tw, 'team_week', sample_cols=['PF','Max PF','Efficiency'])

    # Override rookie counts to ensure unique rookie IDs per team-week (v3).
    try:
        if not pw.empty and {"Team", "Year", "Week", "Player ID", "Starter/Bench", "Rookie?"}.issubset(pw.columns):
            rookies = pw[["Team", "Year", "Week", "Player ID", "Starter/Bench", "Rookie?"]].copy()
            rookies = rookies.dropna(subset=["Team", "Year", "Week", "Player ID"])
            rookies["Player ID"] = rookies["Player ID"].astype(str)
            rookies["Starter/Bench"] = rookies["Starter/Bench"].astype(str)
            rookies["Rookie?"] = pd.to_numeric(rookies["Rookie?"], errors="coerce").fillna(0).astype(int)
            rookies = rookies[rookies["Rookie?"] == 1]

            rookies_rostered = (
                rookies.groupby(["Team", "Year", "Week"])["Player ID"]
                .nunique()
                .reset_index()
                .rename(columns={"Player ID": "Number of rookies rostered"})
            )
            rookies_started = (
                rookies[rookies["Starter/Bench"].str.lower().eq("starter")]
                .groupby(["Team", "Year", "Week"])["Player ID"]
                .nunique()
                .reset_index()
                .rename(columns={"Player ID": "Number of rookies started"})
            )

            if not tw.empty:
                tw = tw.drop(columns=["Number of rookies started", "Number of rookies rostered"], errors="ignore")
                tw = tw.merge(rookies_rostered, on=["Team", "Year", "Week"], how="left")
                tw = tw.merge(rookies_started, on=["Team", "Year", "Week"], how="left")
                tw["Number of rookies rostered"] = (
                    pd.to_numeric(tw.get("Number of rookies rostered"), errors="coerce").fillna(0).astype(int)
                )
                tw["Number of rookies started"] = (
                    pd.to_numeric(tw.get("Number of rookies started"), errors="coerce").fillna(0).astype(int)
                )
    except Exception as e:
        _log_exc(debug, "team_week_rookie_unique_counts", e)

    # ---- Tanking (user formula)
    # Tanking(team, week) uses season-to-date averages through that week.
    # Tanking(team, year) is the final week value.
    def _safe_div(n, d):
        try:
            d = float(d)
            n = float(n)
            if d == 0 or (pd.isna(d) or pd.isna(n)):
                return 0.0
            return n / d
        except Exception:
            return 0.0

    def _tanking_score(avg_pf, avg_max_pf, avg_age, league_avg_pf, league_avg_max_pf, league_avg_age, pick_sum, future_cap):
        # 1/6 *(1 - (AvgPF-2/3 L)/(L-2/3 L))
        denom1 = (league_avg_pf - (2.0/3.0)*league_avg_pf)  # L/3
        term1 = 1.0 - _safe_div((avg_pf - (2.0/3.0)*league_avg_pf), denom1)

        # 1/6 *(1 - (AvgMaxPF-LPF)/(LMaxPF-LPF))
        denom2 = (league_avg_max_pf - league_avg_pf)
        term2 = 1.0 - _safe_div((avg_max_pf - league_avg_pf), denom2)

        # 1/6 *(1 - (AvgAge-21)/(LAvgAge-21))
        denom3 = (league_avg_age - 21.0)
        term3 = 1.0 - _safe_div((avg_age - 21.0), denom3)

        # 1/6 *(sum picks value)
        term4 = float(pick_sum or 0.0)

        # 1/9 *(future draft capital weights)
        term5 = float(future_cap or 0.0)

        return (1.0/6.0)*term1 + (1.0/6.0)*term2 + (1.0/6.0)*term3 + (1.0/6.0)*term4 + (1.0/9.0)*term5

    def _future_cap_from_traded(traded_picks, roster_id: int, season: int) -> float:
        # weights provided by user
        w = {1: 0.25, 2: 0.09, 3: 0.03, 4: 0.01}
        tot = 0.0
        for tp in traded_picks or []:
            try:
                tp_season = _to_int(tp.get("season"), None)
                if tp_season is None or tp_season <= season:
                    continue
                owner = _to_int(tp.get("owner_id") or tp.get("roster_id"), None)
                if owner is None or owner != roster_id:
                    continue
                rnd = _to_int(tp.get("round"), None)
                if rnd in w:
                    tot += w[rnd]
            except Exception:
                continue
        return tot

    # Per-season pick value (that year's draft picks)
    pick_value_by_team_season = {}
    for season_key, picks_for_season in season_draft_picks_all.items():
        season_map = season_roster_to_team.get(int(season_key), {})
        for p in picks_for_season or []:
            try:
                y = _to_int(p.get("draft_season"), season_key)
                if y is None:
                    continue
                rid = _to_int(p.get("roster_id"), None)
                if rid is None:
                    continue
                team = season_map.get(rid)
                if not team:
                    continue
                pick_no = p.get("pick_no")
                if pick_no is None:
                    # fall back: approximate overall pick if not provided
                    rnd = _to_int(p.get("round"), 0)
                    slot = _to_int(p.get("draft_slot"), 0) or _to_int(p.get("pick_in_round"), 0)
                    if rnd and slot:
                        pick_no = (rnd - 1) * max(1, len(season_map)) + slot
                pick_no = _to_int(pick_no, None)
                if pick_no is None:
                    continue
                # rookie drafts only (heuristic): ignore huge pick numbers
                if pick_no > 1000:
                    continue
                val = 1.0 / (float(pick_no) + 1.0)
                pick_value_by_team_season[(str(team), int(y))] = pick_value_by_team_season.get((str(team), int(y)), 0.0) + val
            except Exception:
                continue

    # Team-week tanking: compute season-to-date
    if not tw.empty:
        tw["Tanking"] = pd.to_numeric(tw.get("Tanking"), errors="coerce")

        # weekly team age average (all rostered, starter+bench)
        # Guard against missing/empty age columns.
        if "Age" in pw.columns:
            age_week = pw.groupby(["Team", "Year", "Week"], dropna=False)["Age"].mean().reset_index()
            age_week.rename(columns={"Age": "TeamWeekAvgAge"}, inplace=True)
        else:
            age_week = pd.DataFrame(columns=["Team", "Year", "Week", "TeamWeekAvgAge"])

        tw2 = tw.merge(age_week, on=["Team", "Year", "Week"], how="left")
        tw2["TeamWeekAvgAge"] = pd.to_numeric(tw2["TeamWeekAvgAge"], errors="coerce")

        tanking_rows = []
        for season in sorted(tw2["Year"].dropna().unique()):
            g = tw2[tw2["Year"] == season].copy()
            if g.empty:
                continue

            # league averages season-to-date by week (equal-weight per week)
            g_sorted = g.sort_values("Week").copy()
            # ensure numeric to avoid object-mean failures
            g_sorted["PF"] = pd.to_numeric(g_sorted.get("PF"), errors="coerce")
            g_sorted["Max PF"] = pd.to_numeric(g_sorted.get("Max PF"), errors="coerce")
            g_sorted["TeamWeekAvgAge"] = pd.to_numeric(g_sorted.get("TeamWeekAvgAge"), errors="coerce")

            pf_week = g_sorted.groupby("Week")["PF"].mean().sort_index()
            maxpf_week = g_sorted.groupby("Week")["Max PF"].mean().sort_index()
            age_week_lg = g_sorted.groupby("Week")["TeamWeekAvgAge"].mean().sort_index()

            league_avg_pf_upto = pf_week.expanding().mean()
            league_avg_maxpf_upto = maxpf_week.expanding().mean()
            league_avg_age_upto = age_week_lg.expanding().mean()

            for team, tg in g.groupby("Team"):
                tg = tg.sort_values("Week").copy()
                # expanding means
                pf_exp = pd.to_numeric(tg.get("PF"), errors="coerce").expanding().mean()
                maxpf_exp = pd.to_numeric(tg.get("Max PF"), errors="coerce").expanding().mean()

                # age expanding: use weekly mean age
                age_exp = pd.to_numeric(tg.get("TeamWeekAvgAge"), errors="coerce").expanding().mean()

                rid = season_team_to_roster.get(int(season), {}).get(_norm_team_name(team))
                pick_sum = pick_value_by_team_season.get((str(team), int(season)), 0.0)
                future_cap = _future_cap_from_traded(traded_picks_by_season.get(int(season), []), rid, int(season)) if rid is not None else 0.0

                for i, row in tg.reset_index(drop=True).iterrows():
                    # Week can be missing/NaN in some corrupt rows; guard to avoid crashes.
                    try:
                        wk_int = int(row["Week"]) if pd.notna(row["Week"]) else None
                    except Exception:
                        wk_int = None

                    lg_pf = league_avg_pf_upto.iloc[-1] if len(league_avg_pf_upto) else 0.0
                    lg_mx = league_avg_maxpf_upto.iloc[-1] if len(league_avg_maxpf_upto) else 0.0
                    lg_ag = league_avg_age_upto.iloc[-1] if len(league_avg_age_upto) else 0.0
                    if wk_int is not None:
                        lg_pf = league_avg_pf_upto.get(wk_int, lg_pf)
                        lg_mx = league_avg_maxpf_upto.get(wk_int, lg_mx)
                        lg_ag = league_avg_age_upto.get(wk_int, lg_ag)

                    score = _tanking_score(
                        avg_pf=pf_exp.iloc[i],
                        avg_max_pf=maxpf_exp.iloc[i],
                        avg_age=age_exp.iloc[i],
                        league_avg_pf=lg_pf,
                        league_avg_max_pf=lg_mx,
                        league_avg_age=lg_ag,
                        pick_sum=pick_sum,
                        future_cap=future_cap,
                    )
                    tanking_rows.append((row["Team"], row["Year"], row["Week"], float(score)))

        if tanking_rows:
            tank_df = pd.DataFrame(tanking_rows, columns=["Team", "Year", "Week", "Tanking"])
            tw = tw.drop(columns=["Tanking"], errors="ignore").merge(tank_df, on=["Team", "Year", "Week"], how="left")
        else:
            tw["Tanking"] = 0.0

    
    # ---- Week Name propagation (custom week naming)
    # Use team_week's Week Name where available.
    if (not tw.empty) and ("Week Name" in tw.columns):
        # player_week
        if "Week Name" not in pw.columns:
            pw = pw.merge(tw[["Team","Year","Week","Week Name","Round"]].drop_duplicates(), on=["Team","Year","Week"], how="left")

        # derive a league-wide Week Name per (Year,Week) for league_week rollups
        def _mode_nonnull(vals):
            vals = [v for v in vals if isinstance(v, str) and v and v != "N/A"]
            if not vals:
                return None
            # prefer non-generic labels
            nongeneric = [v for v in vals if not v.startswith("Week ")]
            base = nongeneric if nongeneric else vals
            return pd.Series(base).mode().iloc[0] if len(base) else None

        week_name_global = tw.groupby(["Year","Week"])["Week Name"].apply(_mode_nonnull).reset_index()
    else:
        week_name_global = pd.DataFrame(columns=["Year","Week","Week Name"])

    # --------------------------
    # Merge manual transactions overrides. Sleeper's transactions API
    # occasionally omits real pickups (we've seen one case: Puka Nacua's
    # 2023-09-04 add to Shmuel256, confirmed via Week 1 matchup rosters
    # but missing from the transactions endpoint across every leg).
    # data/manual_transactions.csv lets us drop in those rows by hand.
    # We append them BEFORE the polish + KTC passes so they participate
    # in pickup-counter, drop-date, link-prev/next, and KTC enrichment.
    # --------------------------
    try:
        manual_path = repo_root / "data" / "manual_transactions.csv"
        if manual_path.exists():
            mdf = pd.read_csv(manual_path)
            # Build a quick name -> sleeper_id lookup so KTC enrichment
            # can resolve added/dropped players downstream.
            name_to_sid: Dict[str, str] = {}
            for sid, meta in pid_meta.items():
                fn = (meta or {}).get("full_name")
                if fn:
                    name_to_sid.setdefault(str(fn), str(sid))
            # Build the canonical set of team names so we can refuse to
            # emit manual rows whose Team doesn't match. A typo silently
            # showed up as a phantom team in an earlier iteration.
            canonical_teams: Set[str] = set()
            if not tw.empty and "Team" in tw.columns:
                canonical_teams = {str(t) for t in tw["Team"].dropna().unique()}

            n_added = 0
            for _, mrow in mdf.iterrows():
                added_name = (str(mrow.get("Player Added") or "").strip() or None)
                dropped_name = (str(mrow.get("Player Dropped") or "").strip() or None)
                if added_name in ("", "nan"): added_name = None
                if dropped_name in ("", "nan"): dropped_name = None
                if not added_name and not dropped_name:
                    continue
                # Sanity-check the Date — a corrupted CSV (e.g.
                # unquoted commas in Notes) can shift every field one
                # column left, which surfaced once as Puka Nacua's row
                # claiming Date=2023 and Faab="waiver". Fail loud.
                try:
                    datetime.fromisoformat(str(mrow.get("Date")).replace("Z","+00:00"))
                except Exception:
                    _log(debug, f"[{_now_iso()}] WARN manual transactions: skipping row with bad Date {mrow.get('Date')!r} (CSV likely malformed)")
                    continue
                team_val = str(mrow.get("Team") or "").strip()
                if canonical_teams and team_val not in canonical_teams:
                    _log(debug, f"[{_now_iso()}] WARN manual transactions: Team {team_val!r} doesn't match any canonical team — skipping")
                    continue
                added_pid = name_to_sid.get(added_name) if added_name else None
                dropped_pid = name_to_sid.get(dropped_name) if dropped_name else None
                row: Dict[str, Any] = {
                    "Team": str(mrow.get("Team")),
                    "Player Added": added_name,
                    "Player Dropped": dropped_name,
                    "type of transaction (waiver/free agency)": str(mrow.get("Type") or "free_agent"),
                    "Faab": _to_float(mrow.get("Faab"), None),
                    "Total FAAB bid": _to_float(mrow.get("Total FAAB bid"), None),
                    "FAAB difference over second place": None,
                    "FAAB % difference over second place": None,
                    "Date": str(mrow.get("Date")),
                    "Season": int(mrow.get("Season")) if pd.notna(mrow.get("Season")) else None,
                    "_added_pid": added_pid,
                    "_dropped_pid": dropped_pid,
                    "Number of bids": _to_float(mrow.get("Number of bids"), None),
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
                    "Tanking": None,
                    "Number of times picked up by this team": None,
                }
                transactions_rows.append(row)
                # Also credit per-week/year/all counters so player
                # rollups stay consistent with the manual entries.
                try:
                    season_i = int(mrow.get("Season"))
                except Exception:
                    season_i = None
                if added_pid and season_i is not None:
                    player_tx_year[(str(added_pid), season_i)] += 1
                    player_tx_all[str(added_pid)] += 1
                if dropped_pid and season_i is not None:
                    player_tx_year[(str(dropped_pid), season_i)] += 1
                    player_tx_all[str(dropped_pid)] += 1
                    player_drop_year[(str(dropped_pid), season_i)] += 1
                    player_drop_all[str(dropped_pid)] += 1
                n_added += 1
            if n_added:
                _log(debug, f"[{_now_iso()}] INFO merged {n_added} manual transaction(s) from data/manual_transactions.csv")
            # Bump team_week / team_year counters so the rollup tables
            # reflect the manual rows we just added. Find the Year+Week
            # rows that match each manual row's Date and increment.
            if n_added and not tw.empty and "Year" in tw.columns and "Week" in tw.columns:
                from datetime import date as _dt_date
                # NFL week 1 starts the first Thursday of September. For
                # the dates we care about, a simple approximation is
                # enough: week N starts roughly Sep 7 + 7*(N-1) of that
                # year. Pre-season / week 1 prep dates map to week 1.
                def _week_for_date(dstr: str, season: int):
                    try:
                        d = datetime.fromisoformat(str(dstr).replace("Z","+00:00")).date()
                    except Exception:
                        return None
                    season_start = _dt_date(int(season), 9, 5)
                    if d < season_start:
                        return 1
                    diff = (d - season_start).days // 7 + 1
                    return min(max(1, diff), 17)

                for _, mrow in mdf.iterrows():
                    season = mrow.get("Season")
                    if pd.isna(season):
                        continue
                    season = int(season)
                    wk = _week_for_date(str(mrow.get("Date")), season)
                    team = str(mrow.get("Team"))
                    if not wk:
                        continue
                    mask = (tw["Team"]==team) & (tw["Year"]==season) & (tw["Week"]==wk)
                    matches = tw[mask]
                    if matches.empty:
                        continue
                    idx_ = matches.index[0]
                    cur = pd.to_numeric(tw.at[idx_, "Number of transactions"], errors="coerce")
                    tw.at[idx_, "Number of transactions"] = int((0 if pd.isna(cur) else cur) + 1)
                    faab = _to_float(mrow.get("Faab"), 0.0) or 0.0
                    if faab:
                        cur_f = pd.to_numeric(tw.at[idx_, "Amount of FAAB spent"], errors="coerce")
                        tw.at[idx_, "Amount of FAAB spent"] = round((0.0 if pd.isna(cur_f) else cur_f) + faab, 2)
    except Exception as e:
        _log_exc(debug, "manual_transactions_merge", e)

    # --------------------------
    # transactions_rows post-processing: fill polish columns now that the
    # full history is available.
    #
    #  - Number of times picked up by this team: running per-(team, player)
    #    pickup count, chronological.
    #  - Date dropped/traded: for each pickup, the next date this team
    #    dropped or traded away this player (None if still rostered).
    #  - Weeks between pickup and start: count of player_week rows for
    #    (Team, Player) that occur after the pickup date but before the
    #    player's first start on that team. None if never started.
    # --------------------------
    try:
        if transactions_rows:
            # Sort by date so the running counters scan chronologically.
            def _date_key(r):
                d = r.get("Date") or ""
                return str(d)
            transactions_rows.sort(key=_date_key)

            # (Source-level dedup of Sleeper transactions now runs in the
            # per-week fetch loop, so transactions_rows are already deduped
            # by the time we get here.)

            # 1) Number of times picked up by this team
            pickup_count: Dict[Tuple[str, str], int] = defaultdict(int)
            for r in transactions_rows:
                name = r.get("Player Added")
                team = r.get("Team")
                if not name or not team:
                    continue
                key = (str(team), str(name))
                pickup_count[key] += 1
                r["Number of times picked up by this team"] = pickup_count[key]

            # 2) Build per-(team, player) event log to find next drop/trade-out.
            # NOTE: don't name a local 'date' here — that would shadow the
            # imported datetime.date class for the entire build_all function
            # (Python decides locals at compile time), which broke player_week
            # construction earlier with an UnboundLocalError. Use dt_str.
            event_log: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
            for r in transactions_rows:
                team = r.get("Team")
                add = r.get("Player Added")
                dropped = r.get("Player Dropped")
                dt_str = r.get("Date") or ""
                if team and add:
                    event_log[(str(team), str(add))].append((str(dt_str), "add"))
                if team and dropped:
                    event_log[(str(team), str(dropped))].append((str(dt_str), "drop"))
            # Players traded away count as "left this team" too.
            for tr_row in trades_rows:
                team = tr_row.get("Team")
                dt_str = tr_row.get("Date") or ""
                dropped_assets = str(tr_row.get("Assets dropped") or "")
                if dropped_assets in ("0.0", "None", ""):
                    continue
                for asset in dropped_assets.split(";"):
                    asset = asset.strip()
                    if not asset or re.match(r"^\d{4}\b", asset):
                        continue
                    if team:
                        event_log[(str(team), asset)].append((str(dt_str), "trade_out"))
            # Orphan drops (player dropped without a same-transaction add) —
            # these never made it into transactions_rows but they are real
            # departures and must close the event window for the prior pickup.
            for od in orphan_drop_events:
                t_od = od.get("Team")
                p_od = od.get("Player Dropped")
                d_od = od.get("Date") or ""
                if t_od and p_od and d_od:
                    event_log[(str(t_od), str(p_od))].append((str(d_od), "drop"))
            for k in event_log:
                event_log[k].sort()

            for r in transactions_rows:
                team = r.get("Team")
                add = r.get("Player Added")
                add_date = r.get("Date") or ""
                if not (team and add and add_date):
                    continue
                # Next departure event strictly after add_date.
                next_evt = None
                for ev_date, ev_type in event_log.get((str(team), str(add)), []):
                    if ev_type == "add":
                        continue
                    if ev_date and ev_date > add_date:
                        next_evt = ev_date
                        break
                if next_evt:
                    r["Date dropped/traded"] = next_evt

            # 3) Weeks between pickup and start. Needs pw which exists at this
            # point in build_all. Map (Team, Player Name) -> sorted list of
            # (Year, Week, Starter?) rows. For each pickup, count player_week
            # rows that fall between pickup date and first start on that team.
            if not pw.empty and {"Team", "Player", "Year", "Week", "Starter/Bench"}.issubset(set(pw.columns)):
                # Approximate fantasy-week date: NFL week 1 starts ~Sept 7,
                # subsequent weeks each Thursday after. Good enough for an
                # "is this player_week row after the pickup date" gate.
                def _approx_week_date(year: int, week: int) -> str:
                    try:
                        d = date(int(year), 9, 7) + timedelta(days=7 * (int(week) - 1))
                        return d.isoformat()
                    except Exception:
                        return ""

                pw_min = pw[["Team", "Player", "Year", "Week", "Starter/Bench"]].copy()
                pw_min = pw_min.sort_values(["Team", "Player", "Year", "Week"]).reset_index(drop=True)
                # Bucket by (team, player) for fast lookup
                pw_by_tp: Dict[Tuple[str, str], List[Tuple[int, int, bool, str]]] = defaultdict(list)
                for _, prow in pw_min.iterrows():
                    try:
                        yr = int(prow["Year"]); wk = int(prow["Week"])
                    except Exception:
                        continue
                    started = str(prow["Starter/Bench"]) == "Starter"
                    pw_by_tp[(str(prow["Team"]), str(prow["Player"]))].append(
                        (yr, wk, started, _approx_week_date(yr, wk))
                    )

                for r in transactions_rows:
                    team = r.get("Team")
                    add = r.get("Player Added")
                    add_date = r.get("Date") or ""
                    if not (team and add and add_date):
                        continue
                    rows = pw_by_tp.get((str(team), str(add)))
                    if not rows:
                        continue
                    # Counting restarts on each pickup. If the player was
                    # dropped/traded away after this pickup, the bench window
                    # ends at that drop. So bound the search at the NEXT
                    # departure for the same (team, player) after add_date.
                    drop_after = r.get("Date dropped/traded") or ""
                    weeks_before_start = 0
                    found_start = False
                    for yr, wk, started, wk_date in rows:
                        if wk_date and wk_date < add_date:
                            continue
                        # Stop counting once the player was let go again.
                        if drop_after and wk_date and wk_date >= drop_after:
                            break
                        if started:
                            found_start = True
                            break
                        weeks_before_start += 1
                    if found_start:
                        r["Weeks between pickup and start"] = weeks_before_start
    except Exception as e:
        _log_exc(debug, "transactions_polish", e)

    # --------------------------
    # transactions_rows polish pass 2: PPG-derived columns, age diff,
    # cuff detection, post-pickup start-rate metrics, and composite
    # 'Player addition value'.
    #
    # Definitions (per league owner):
    #   Avg PPG (added/dropped): mean of points scored in the last 5
    #     played games BEFORE the pickup date, regardless of fantasy
    #     team. Bye and injury weeks are not "played games" — skip them.
    #   Difference of averages: added_avg - dropped_avg
    #   Difference adjusted by position:
    #     added_adj  = added_avg * all_starter_avg / pos_avg[added_pos]
    #     dropped_adj = dropped_avg * all_starter_avg / pos_avg[dropped_pos]
    #     adjusted_diff = added_adj - dropped_adj
    #     (normalises positions to a common scale)
    #   Cuff at time of pickup?: another STARTER on the picking team
    #     at the pickup week shares NFL team + position with the added
    #     player AND averaged 10+ PPG more in last 5 played games.
    #   Number of starts before next drop: count of pw rows for
    #     (Team, Player Added) with Starter/Bench=='Starter' that fall
    #     between Date and Date dropped/traded.
    #   % of starts made while rostered: starts / weeks_rostered.
    #   Injury adjusted version: same, but exclude Bye? and Injury?
    #     rows from BOTH numerator and denominator.
    #   Player addition value:
    #     adjusted_diff * (1 + pct_starts) * (1 + pct_starts_inj_adj)
    #       + CUFF_BONUS  (only added when 'Cuff at time of pickup?'=True)
    # --------------------------
    try:
        if transactions_rows and not pw.empty:
            from datetime import date as _date_cls
            # --- precompute per-player game logs across the whole pw ---
            pw_min_p = pw[["Player", "Team", "Year", "Week", "Points",
                           "Position", "NFL team", "Starter/Bench",
                           "Injury?", "Bye?"]].copy()

            def _approx_week_date2(year, week):
                try:
                    d = _date_cls(int(year), 9, 7) + timedelta(days=7 * (int(week) - 1))
                    return d.isoformat()
                except Exception:
                    return ""

            pw_min_p["_wk_date"] = [
                _approx_week_date2(y, w) for y, w in zip(pw_min_p["Year"], pw_min_p["Week"])
            ]

            # Index by player (regardless of fantasy team) for the
            # "last 5 played games before date" lookup.
            pw_by_player: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            # Index by (team, week, year) for the cuff lookup — gives
            # us the picking team's roster snapshot at the pickup week.
            pw_by_team_week: Dict[Tuple[str, int, int], List[Dict[str, Any]]] = defaultdict(list)
            # Index by (team, player) for the start-rate walk.
            pw_by_team_player: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

            for _, prow in pw_min_p.iterrows():
                d = {
                    "Player": str(prow.get("Player") or ""),
                    "Team": str(prow.get("Team") or ""),
                    "Year": int(prow["Year"]) if pd.notna(prow["Year"]) else None,
                    "Week": int(prow["Week"]) if pd.notna(prow["Week"]) else None,
                    "Points": float(prow["Points"]) if pd.notna(prow["Points"]) else 0.0,
                    "Position": str(prow.get("Position") or "").upper(),
                    "NFL team": str(prow.get("NFL team") or ""),
                    "Starter/Bench": str(prow.get("Starter/Bench") or ""),
                    "Injury?": bool(prow.get("Injury?")),
                    "Bye?": bool(prow.get("Bye?")),
                    "_wk_date": str(prow.get("_wk_date") or ""),
                }
                pw_by_player[d["Player"]].append(d)
                if d["Year"] is not None and d["Week"] is not None:
                    pw_by_team_week[(d["Team"], d["Year"], d["Week"])].append(d)
                pw_by_team_player[(d["Team"], d["Player"])].append(d)

            # All-time starter averages for the position adjustment.
            starters = pw[pw["Starter/Bench"] == "Starter"]
            all_starter_avg = float(starters["Points"].mean()) if not starters.empty else 0.0
            pos_avg: Dict[str, float] = {}
            if not starters.empty and "Position" in starters.columns:
                pos_avg = {
                    str(k).upper(): float(v)
                    for k, v in starters.groupby("Position")["Points"].mean().to_dict().items()
                }

            def _pos_adjust(ppg: Optional[float], pos: Optional[str]) -> Optional[float]:
                if ppg is None:
                    return None
                p = pos_avg.get((pos or "").upper())
                if not p or p <= 0 or not all_starter_avg:
                    return ppg
                return round(ppg * all_starter_avg / p, 4)

            # Build name -> sleeper_id once so we can hit nfl_log_by_sid
            # (which is keyed by Sleeper id) from a player display name.
            name_to_sid_local: Dict[str, str] = {}
            for sid, meta in pid_meta.items():
                fn = (meta or {}).get("full_name")
                if fn:
                    name_to_sid_local.setdefault(str(fn), str(sid))

            def _player_games(player_name: Optional[str]) -> List[Dict[str, Any]]:
                """Return the player's NFL game log: list of dicts with
                _wk_date and Points. Prefer nflverse (covers all NFL
                weeks regardless of fantasy roster status); fall back
                to pw (filtering out bye / injury rows since those
                aren't 'played' for our purposes)."""
                if not player_name:
                    return []
                sid = name_to_sid_local.get(player_name)
                games: List[Dict[str, Any]] = []
                if sid:
                    for entry in nfl_log_by_sid.get(sid, []):
                        if entry["_wk_date"]:
                            games.append({"_wk_date": entry["_wk_date"], "Points": entry["points"]})
                if not games:
                    for r in pw_by_player.get(player_name, []):
                        if r["_wk_date"] and not r["Bye?"] and not r["Injury?"]:
                            games.append({"_wk_date": r["_wk_date"], "Points": r["Points"]})
                return games

            def _avg_ppg_last5_before(player_name: Optional[str], pickup_date_iso: str) -> Optional[float]:
                """Mean fantasy points over the 5 most-recent played
                games BEFORE the pickup date. If fewer than 5 games
                exist on record, averages whatever's available (e.g.,
                2 games -> mean of 2). Used for cuff detection and the
                'PPG of 5 games before pickup' column."""
                games = _player_games(player_name)
                played = [g for g in games if g["_wk_date"] < pickup_date_iso]
                if not played:
                    return None
                played.sort(key=lambda g: g["_wk_date"], reverse=True)
                window = played[:5]
                return round(sum(g["Points"] for g in window) / len(window), 4)

            def _avg_ppg_in_window(
                player_name: Optional[str],
                start_iso: str,
                end_iso: Optional[str],
            ) -> Optional[float]:
                """Mean fantasy points across NFL games in [start, end).
                end_iso=None means 'no upper bound' — counts through
                end of dataset. Used for the forward-looking 'Average
                PPG on team' and 'over same time' columns: the window
                is the time the added player was on the picking team."""
                games = _player_games(player_name)
                in_window: List[float] = []
                for g in games:
                    if not g["_wk_date"]:
                        continue
                    if g["_wk_date"] < start_iso:
                        continue
                    if end_iso and g["_wk_date"] >= end_iso:
                        continue
                    in_window.append(g["Points"])
                if not in_window:
                    return None
                return round(sum(in_window) / len(in_window), 4)

            def _player_pos_nfl_team_at(player_name: Optional[str], pickup_date_iso: str) -> Tuple[Optional[str], Optional[str]]:
                """Best-effort position+NFL team for the player AS OF the
                pickup date (latest pw row before that)."""
                if not player_name:
                    return None, None
                rows = pw_by_player.get(player_name, [])
                before = [r for r in rows if r["_wk_date"] and r["_wk_date"] <= pickup_date_iso]
                if not before:
                    # fall back to first pw row
                    if rows:
                        r = rows[0]
                        return (r["Position"] or None), (r["NFL team"] or None)
                    return None, None
                before.sort(key=lambda r: r["_wk_date"], reverse=True)
                r = before[0]
                return (r["Position"] or None), (r["NFL team"] or None)

            CUFF_BONUS = 5.0  # PPG-equivalent bonus when player is a cuff at pickup

            for r in transactions_rows:
                team = r.get("Team")
                added = r.get("Player Added")
                dropped = r.get("Player Dropped")
                pickup_date = r.get("Date") or ""
                # Date is an ISO string at this stage; convert for comparison.
                pickup_iso = str(pickup_date)
                # Pull a YYYY-MM-DD prefix for week-date string comparison.
                pickup_iso_prefix = pickup_iso[:10] if len(pickup_iso) >= 10 else pickup_iso

                # Compute the player's tenure window on this team.
                # 'Average PPG on team' and 'over same time' are
                # forward-looking: from pickup date to the next
                # drop/trade of the added player (or open-ended if
                # the player is still rostered).
                drop_after_iso = str(r.get("Date dropped/traded") or "")
                drop_after_prefix = drop_after_iso[:10] if len(drop_after_iso) >= 10 else (
                    drop_after_iso or None
                )

                # --- Avg PPG family ---
                # Forward-looking: how did the added player do on this
                # team, and what was the dropped player doing in NFL
                # over the same window?
                added_on_team = (
                    _avg_ppg_in_window(added, pickup_iso_prefix, drop_after_prefix)
                    if added else None
                )
                dropped_same_window = (
                    _avg_ppg_in_window(dropped, pickup_iso_prefix, drop_after_prefix)
                    if dropped else None
                )
                # Pre-pickup snapshot: trailing 5-game average. Useful
                # for evaluating the pickup decision (what did the
                # market know about this guy at the time).
                added_pre5 = _avg_ppg_last5_before(added, pickup_iso_prefix) if added else None
                # Pre-pickup average for the dropped player too (used
                # in the cuff comparison; still computed once).
                dropped_pre5 = _avg_ppg_last5_before(dropped, pickup_iso_prefix) if dropped else None

                if added_on_team is not None:
                    r["Average PPG on team"] = added_on_team
                if dropped_same_window is not None:
                    r["Average PPG of dropped player over same time"] = dropped_same_window
                if added_pre5 is not None:
                    r["PPG of 5 games before pickup"] = added_pre5
                if added_on_team is not None or dropped_same_window is not None:
                    r["Difference of averages"] = round(
                        (added_on_team or 0.0) - (dropped_same_window or 0.0), 4
                    )

                # --- Position adjustment ---
                # Position adjustment now uses the forward-looking
                # tenure averages (matches user's clarification:
                # 'adjust adjusted averages to match this').
                added_pos, added_nfl = _player_pos_nfl_team_at(added, pickup_iso_prefix)
                dropped_pos, dropped_nfl = _player_pos_nfl_team_at(dropped, pickup_iso_prefix)
                added_adj = _pos_adjust(added_on_team, added_pos)
                dropped_adj = _pos_adjust(dropped_same_window, dropped_pos)
                adj_diff = None
                if added_adj is not None or dropped_adj is not None:
                    adj_diff = round((added_adj or 0.0) - (dropped_adj or 0.0), 4)
                    r["Difference of averages adjusted by position"] = adj_diff

                # The cuff comparison still uses the pre-pickup 5-game
                # snapshot — that's the form info available at pickup.
                # Bind it under the original name the cuff code reads.
                added_avg = added_pre5

                # --- Age difference (added - dropped, years) ---
                def _age_for(name):
                    if not name:
                        return None
                    # Find this player's sleeper_id via pid_meta full_name
                    for sid, meta in pid_meta.items():
                        if (meta or {}).get("full_name") == name:
                            bd = meta.get("birth_date")
                            if bd:
                                try:
                                    pickup_d = datetime.fromisoformat(pickup_iso.replace("Z","+00:00")).date()
                                    born = dateparser.parse(str(bd)).date()
                                    return round((pickup_d - born).days / 365.25, 2)
                                except Exception:
                                    return None
                            return None
                    return None
                added_age = _age_for(added)
                dropped_age = _age_for(dropped)
                if added_age is not None or dropped_age is not None:
                    r["Age difference"] = round((added_age or 0.0) - (dropped_age or 0.0), 2)

                # --- Cuff at time of pickup? ---
                # Identify the pickup's NFL Year+Week (best effort) so
                # we can look at the picking team's roster that week.
                # The pw _wk_date approximation gives us a 7-day bucket
                # we can match against the pickup_iso.
                cuff = False
                if added and team and added_nfl and added_pos:
                    # Find the team's pw rows for the same week
                    candidate_team_rows: List[Dict[str, Any]] = []
                    for r2 in pw_by_team_week.values():
                        for entry in r2:
                            if entry["Team"] != team:
                                continue
                            # Pickup must fall within ~7 days of this week
                            if entry["_wk_date"] and entry["_wk_date"] <= pickup_iso_prefix:
                                if not candidate_team_rows or entry["_wk_date"] > candidate_team_rows[0]["_wk_date"]:
                                    candidate_team_rows = [entry]
                                elif entry["_wk_date"] == candidate_team_rows[0]["_wk_date"]:
                                    candidate_team_rows.append(entry)
                    # Build the full roster for that week (all players,
                    # not just the one we found above)
                    if candidate_team_rows:
                        wk_date = candidate_team_rows[0]["_wk_date"]
                        yr = candidate_team_rows[0]["Year"]
                        wk = candidate_team_rows[0]["Week"]
                        roster_that_week = pw_by_team_week.get((team, yr, wk), [])
                        for mate in roster_that_week:
                            if mate["Player"] == added:
                                continue
                            if mate["Starter/Bench"] != "Starter":
                                continue
                            if mate["NFL team"] != added_nfl:
                                continue
                            if mate["Position"] != added_pos:
                                continue
                            # Check mate's last-5 PPG > added's last-5 PPG + 10
                            mate_avg = _avg_ppg_last5_before(mate["Player"], pickup_iso_prefix)
                            if mate_avg is not None and (added_avg or 0.0) + 10 <= mate_avg:
                                cuff = True
                                break
                r["Cuff at time of pickup?"] = bool(cuff)

                # --- Start-rate metrics after the pickup ---
                # Walk pw rows for (Team, Player Added) between Date and
                # Date dropped/traded. Count starts, weeks rostered,
                # injury-adjusted starts/weeks.
                if added and team:
                    drop_after = str(r.get("Date dropped/traded") or "")
                    drop_after_prefix = drop_after[:10] if len(drop_after) >= 10 else drop_after
                    weeks_played = 0
                    starts = 0
                    inj_weeks_played = 0
                    inj_starts = 0
                    for entry in pw_by_team_player.get((team, added), []):
                        wk_date = entry["_wk_date"]
                        if not wk_date or wk_date < pickup_iso_prefix:
                            continue
                        if drop_after_prefix and wk_date >= drop_after_prefix:
                            break
                        weeks_played += 1
                        if entry["Starter/Bench"] == "Starter":
                            starts += 1
                        if not entry["Bye?"] and not entry["Injury?"]:
                            inj_weeks_played += 1
                            if entry["Starter/Bench"] == "Starter":
                                inj_starts += 1
                    r["Number of starts before next drop"] = int(starts)
                    if weeks_played > 0:
                        r["% of starts made while rostered"] = round(starts / weeks_played, 4)
                    if inj_weeks_played > 0:
                        r["Injury adjusted % of starts made while rostered"] = round(inj_starts / inj_weeks_played, 4)

                # --- Player addition value composite ---
                # Only meaningful when we have the adjusted diff.
                if adj_diff is not None:
                    pct_starts = float(r.get("% of starts made while rostered") or 0.0)
                    pct_inj = float(r.get("Injury adjusted % of starts made while rostered") or 0.0)
                    cuff_bonus = CUFF_BONUS if cuff else 0.0
                    addition_val = adj_diff * (1.0 + pct_starts) * (1.0 + pct_inj) + cuff_bonus
                    r["Player addition value"] = round(addition_val, 4)
    except Exception as e:
        _log_exc(debug, "transactions_polish_v2", e)

    # --------------------------
    # KTC value pass — single pass that powers all KTC columns on both
    # trades.csv and transactions.csv. Data source: dynasty-daddy.com's
    # public API, which scrapes KeepTradeCut daily and exposes per-player
    # daily history back to April 2021. We use trade_value (1QB format).
    #
    # Reference points per trade (4):
    #   - deal time:       the trade date itself
    #   - end of season:   Jan 5 of (trade.Season + 1)
    #   - 1 year later:    Jan 5 of (trade.Season + 2)
    #   - 2 years later:   Jan 5 of (trade.Season + 3)
    # 'End of season' uses Jan 5 because Sleeper championships finish by
    # week 17 and 'immediately after the championship' is the year-end
    # boundary we agreed on (see Season-column PR).
    #
    # Per transaction row: KTC of added, dropped, and net at deal time.
    # --------------------------
    try:
        from lotg_support.ktc import build_index, asset_value_at
        today = datetime.utcnow().date()

        # League-format detection so the KTC values we pull match the
        # user's setup. dynasty-daddy publishes two value series per
        # asset: trade_value (1QB) and sf_trade_value (superflex). A
        # superflex league should use sf_trade_value or QBs read way
        # too low and trade rollups read backwards.
        ktc_value_col = "trade_value"
        try:
            for lg in leagues or []:
                rp = [str(x).upper() for x in (lg.get("roster_positions") or [])]
                if any(p in {"SUPER_FLEX", "SUPERFLEX", "SFLEX", "SFLX"} for p in rp):
                    ktc_value_col = "sf_trade_value"
                    break
                if rp.count("QB") >= 2:
                    ktc_value_col = "sf_trade_value"
                    break
        except Exception:
            pass
        _log(debug, f"[{_now_iso()}] INFO ktc value column: {ktc_value_col}")

        # Collect every sleeper_id and pick label we'll need across both
        # detail tables. dynasty-daddy serves per-player histories one
        # API call at a time, so pre-fetching only what we use keeps the
        # build fast (the cache makes subsequent runs cheaper still).
        needed_sids: Set[str] = set()
        needed_picks: Set[str] = set()
        for row in trades_rows:
            for sid in (row.get("_recv_player_ids") or []):
                if sid:
                    needed_sids.add(str(sid))
            for sid in (row.get("_drop_player_ids") or []):
                if sid:
                    needed_sids.add(str(sid))
            for plabel in (row.get("_recv_picks") or []):
                if plabel:
                    needed_picks.add(str(plabel))
            for plabel in (row.get("_drop_picks") or []):
                if plabel:
                    needed_picks.add(str(plabel))
        for tx_row in transactions_rows:
            sid = tx_row.get("_added_pid")
            if sid:
                needed_sids.add(str(sid))
            sid = tx_row.get("_dropped_pid")
            if sid:
                needed_sids.add(str(sid))

        # Pass full_name+pos for every sleeper_id we need so the KTC
        # module can derive name_id slugs for retired/aged-out players
        # not in dynasty-daddy's active directory.
        sid_to_meta = {
            str(sid): {
                "full_name": (pid_meta.get(str(sid)) or {}).get("full_name") or "",
                "pos": (pid_meta.get(str(sid)) or {}).get("pos") or "",
            }
            for sid in needed_sids
        }
        idx = build_index(
            repo_root,
            needed_sids,
            needed_picks,
            value_col=ktc_value_col,
            sid_to_meta=sid_to_meta,
        )

        def _side_total(
            target: date,
            player_ids: List[str],
            pick_labels: List[str],
        ) -> Tuple[float, int]:
            total = 0.0
            hits = 0
            for sid in player_ids:
                v = asset_value_at(None, str(sid), target, idx)
                if v is not None:
                    total += v
                    hits += 1
            for plabel in pick_labels:
                v = asset_value_at(str(plabel), None, target, idx)
                if v is not None:
                    total += v
                    hits += 1
            return total, hits

        def _diff_at(
            target: date,
            recv_ids: List[str],
            drop_ids: List[str],
            recv_picks: List[str],
            drop_picks: List[str],
        ) -> Optional[float]:
            if target > today:
                return None
            r_total, r_hits = _side_total(target, recv_ids, recv_picks)
            d_total, d_hits = _side_total(target, drop_ids, drop_picks)
            if not (r_hits and d_hits):
                return None
            return round(r_total - d_total, 1)

        # --- Trades pass ---
        for row in trades_rows:
            ds = row.get("Date")
            if not ds:
                continue
            try:
                trade_dt = datetime.fromisoformat(str(ds).replace("Z", "+00:00"))
                trade_date = trade_dt.date()
            except Exception:
                continue
            season_i = row.get("Season")
            try:
                season_i = int(season_i) if season_i is not None else None
            except Exception:
                season_i = None

            recv_ids = list(row.get("_recv_player_ids") or [])
            drop_ids = list(row.get("_drop_player_ids") or [])
            recv_picks = list(row.get("_recv_picks") or [])
            drop_picks = list(row.get("_drop_picks") or [])

            # Deal time
            if trade_date <= today:
                diff = _diff_at(trade_date, recv_ids, drop_ids, recv_picks, drop_picks)
                if diff is not None:
                    row["KTC value difference at deal time"] = diff

                # 'Pick value received' = sum of received-side pick
                # values at deal time. Player side intentionally excluded.
                pick_recv_total = 0.0
                pick_recv_hits = 0
                for plabel in recv_picks:
                    v = asset_value_at(str(plabel), None, trade_date, idx)
                    if v is not None:
                        pick_recv_total += v
                        pick_recv_hits += 1
                if pick_recv_hits:
                    row["Pick value received"] = round(pick_recv_total, 1)

            # 'Change in pick value at draft time' — for each received
            # pick, (value at post-draft snapshot for that pick's year)
            # minus (value at trade date). Sums across picks. Picks
            # whose drafts are in the future don't contribute.
            pick_change_total = 0.0
            pick_change_hits = 0
            for plabel in recv_picks:
                parts = str(plabel).strip().split()
                if len(parts) != 2:
                    continue
                try:
                    pick_year = int(parts[0])
                except Exception:
                    continue
                post_draft = date(pick_year, 9, 5)
                if post_draft > today:
                    continue
                v_before = asset_value_at(str(plabel), None, trade_date, idx)
                v_after = asset_value_at(str(plabel), None, post_draft, idx)
                if v_before is None or v_after is None:
                    continue
                pick_change_total += (v_after - v_before)
                pick_change_hits += 1
            if pick_change_hits:
                row["Change in pick value at draft time"] = round(pick_change_total, 1)

            if season_i is None:
                continue
            ref_points = [
                ("KTC value difference at end of season", date(season_i + 1, 1, 5)),
                ("KTC value difference 1 year later",     date(season_i + 2, 1, 5)),
                ("KTC value difference 2 years later",    date(season_i + 3, 1, 5)),
            ]
            for col_name, ref_date in ref_points:
                # Floor at the trade date — an end-of-season ref earlier
                # than the trade itself doesn't make sense.
                if ref_date < trade_date:
                    ref_date = trade_date
                diff = _diff_at(ref_date, recv_ids, drop_ids, recv_picks, drop_picks)
                if diff is not None:
                    row[col_name] = diff

        # --- Transactions pass: 4 reference points × 3 columns each ---
        # For each transaction we look up the added and dropped players'
        # KTC values at four moments: the transaction date itself, then
        # the same Jan-5-after-season-end ladder we use for trades. Net
        # is added − dropped (missing side treated as zero). Future-
        # dated references stay N/A via _preserve_na.
        def _tx_value_at(
            target: date,
            added_pid: Optional[str],
            dropped_pid: Optional[str],
        ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
            v_a = asset_value_at(None, str(added_pid), target, idx) if added_pid else None
            v_d = asset_value_at(None, str(dropped_pid), target, idx) if dropped_pid else None
            v_net = None
            if v_a is not None or v_d is not None:
                v_net = round((v_a or 0.0) - (v_d or 0.0), 1)
            return v_a, v_d, v_net

        tx_ref_points = [
            ("at deal time",     "deal"),
            ("at end of season", "end"),
            ("1 year later",     "y1"),
            ("2 years later",    "y2"),
        ]
        for tx_row in transactions_rows:
            ds = tx_row.get("Date")
            if not ds:
                continue
            try:
                tx_dt = datetime.fromisoformat(str(ds).replace("Z", "+00:00"))
                tx_date = tx_dt.date()
            except Exception:
                continue
            season_i = tx_row.get("Season")
            try:
                season_i = int(season_i) if season_i is not None else None
            except Exception:
                season_i = None
            added_pid = tx_row.get("_added_pid")
            dropped_pid = tx_row.get("_dropped_pid")

            for label, tag in tx_ref_points:
                if tag == "deal":
                    ref = tx_date
                else:
                    if season_i is None:
                        continue
                    offset = {"end": 1, "y1": 2, "y2": 3}[tag]
                    ref = date(season_i + offset, 1, 5)
                    # Never refer to a date earlier than the transaction
                    # itself — matches the floor used in the trades pass.
                    if ref < tx_date:
                        ref = tx_date
                if ref > today:
                    continue
                v_a, v_d, v_net = _tx_value_at(ref, added_pid, dropped_pid)
                if v_a is not None:
                    tx_row[f"KTC value of player added {label}"] = round(v_a, 1)
                if v_d is not None:
                    tx_row[f"KTC value of player dropped {label}"] = round(v_d, 1)
                if v_net is not None:
                    tx_row[f"Net KTC value {label}"] = v_net
    except Exception as e:
        _log_exc(debug, "ktc_value_diff", e)
    # Surface any dynasty-daddy fetch failures so a silent partial
    # population is visible in the build log.
    try:
        from lotg_support.ktc import get_http_errors
        for err in get_http_errors()[:25]:
            _log(debug, f"[{_now_iso()}] WARN ktc fetch: {err}")
    except Exception:
        pass

    tx = pd.DataFrame(transactions_rows)
    tr = pd.DataFrame(trades_rows)
    ph = pd.DataFrame(pick_rows)
    if not ph.empty:
        try:
            dedupe_cols = [c for c in ["Year", "Original Team", "Number", "Player Picked"] if c in ph.columns]
            if dedupe_cols:
                ph = ph.drop_duplicates(subset=dedupe_cols, keep="first").reset_index(drop=True)
        except Exception:
            pass

    # --------------------------
    # Reconstruct draft pick trade history from Sleeper's traded_picks API.
    #
    # The previous implementation relied on pick_trade_events / pick_holdings
    # state built during per-season trade processing. That state assumed each
    # team starts with its own pick in every round, which fails for an
    # ESPN-era league: trades that originated before Sleeper's tracking
    # window can't be anchored to an original owner (we saw 445 'pick
    # ledger unresolved' warnings against this data).
    #
    # Simpler approach: read traded_picks_by_season as a flat event log.
    # Each event has (season, round, previous_owner_id, owner_id). Group
    # events by (season, round) and walk a directed graph (prev → new) to
    # find each pick's original owner and its full chain. For an ESPN-era
    # pick that wasn't traded inside Sleeper, no event row exists and we
    # leave Original Team set to the picker (no chain to render).
    # --------------------------
    try:
        if not ph.empty and traded_picks_by_season:
            # Use the most-recent season's snapshot; it accumulates history.
            latest_season = max(traded_picks_by_season.keys())
            all_events = traded_picks_by_season.get(latest_season, []) or []
            # Group events by (season, round). Sleeper returns events in
            # roughly chronological order within a snapshot; we'll preserve
            # insertion order.
            events_by_sr: Dict[Tuple[int, int], List[Tuple[int, int]]] = defaultdict(list)
            for tp in all_events:
                try:
                    s = int(tp.get("season"))
                    rd = int(tp.get("round"))
                    prev = _to_int(tp.get("previous_owner_id"), None)
                    new = _to_int(tp.get("owner_id"), None)
                    if prev is None or new is None:
                        continue
                    events_by_sr[(s, rd)].append((int(prev), int(new)))
                except Exception:
                    continue

            # For each (season, round), walk chains.
            # chain_by_final[(season, round, final_rid)] = [origin, mid1, ..., final]
            chain_by_final: Dict[Tuple[int, int, int], List[int]] = {}
            for (s, rd), events in events_by_sr.items():
                if not events:
                    continue
                # For each starting prev, follow its chain forward.
                # A roster can have at most one outgoing edge among events for
                # a given pick (a pick has one current owner at any time).
                outgoing: Dict[int, int] = {}
                incoming: Dict[int, int] = {}
                for prev, new in events:
                    # If multiple outgoing for same prev in same (s, rd):
                    # this means the team had multiple picks in the same round.
                    # In Sleeper dynasty leagues that's normal (post-trade).
                    # We can't disambiguate by pick_no, so we take last-seen.
                    outgoing[prev] = new
                    incoming[new] = prev
                # Roots = roster_ids that appear as prev but never as new
                roots = set(outgoing.keys()) - set(incoming.keys())
                for root in roots:
                    chain = [int(root)]
                    cur = root
                    while cur in outgoing:
                        nxt = outgoing[cur]
                        if nxt in chain:  # cycle guard
                            break
                        chain.append(int(nxt))
                        cur = nxt
                    final = chain[-1]
                    chain_by_final[(s, rd, int(final))] = chain

            # Apply to ph
            for i, r in ph.iterrows():
                yr = _to_int(r.get("Year"), None)
                num = str(r.get("Number") or "")
                m = re.match(r"R(\d+)(?:\.|$)", num)
                if yr is None or not m:
                    continue
                rnd = int(m.group(1))

                # "Original Team" was set to roster_to_team[roster_id] at pick
                # construction; convert back to roster_id.
                final_team_disp = str(r.get("Original Team") or "")
                final_rid = season_team_to_roster.get(int(yr), {}).get(_norm_team_name(final_team_disp))
                if final_rid is None:
                    continue

                chain = chain_by_final.get((int(yr), rnd, int(final_rid)))
                if not chain or len(chain) < 2:
                    # Either no trade history found, or chain of length 1
                    # (picker == origin, no trades on this pick).
                    continue

                rid_to_team = season_roster_to_team.get(int(yr), {})
                # Rewrite Original Team to the chain origin
                ph.at[i, "Original Team"] = rid_to_team.get(int(chain[0]), f"Roster {chain[0]}")
                # Trade 1..N = intermediate owners (exclude the origin at index 0)
                for j, owner_rid in enumerate(chain[1:11], start=1):
                    try:
                        ph.at[i, f"Trade {j}"] = rid_to_team.get(int(owner_rid), f"Roster {owner_rid}")
                    except Exception:
                        continue
    except Exception as e:
        _log_exc(debug, "pick_history_reconstruct", e)


    # --------------------------
    # Player-week derived columns (deltas, tenure, awards) + Hardship
    # --------------------------
    if not pw.empty:
        pw["Year"] = pd.to_numeric(pw["Year"], errors="coerce").astype("Int64")
        pw["Week"] = pd.to_numeric(pw["Week"], errors="coerce").astype("Int64")
        pw["Points"] = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)

        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)

        # Fill missing NFL team with nearest known value for same player-season, then player-level mode.
        if "NFL team" in pw.columns:
            pw["NFL team"] = pw["NFL team"].replace("", np.nan)
            pw["NFL team"] = pw.groupby(["Player", "Year"])["NFL team"].transform(lambda s: s.ffill().bfill())
            team_mode = pw.groupby("Player")["NFL team"].agg(lambda s: s.dropna().mode().iloc[0] if len(s.dropna()) else np.nan)
            pw["NFL team"] = pw["NFL team"].fillna(pw["Player"].map(team_mode))
            pw["NFL team"] = pw["NFL team"].map(_norm_team)

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

        # league-level player of week among starters.
        # Pick exactly ONE winner per (Year, Week) per award. Tie-breaker rules:
        #   - Player of the week (max score): on tie, alphabetical Player name first
        #   - Benchwarmer (min score): if 2+ starters tie at 0 points, no winner
        #     (it's not meaningful to call out one of many who all sat out). If 2+
        #     tie at a non-zero low, alphabetical first wins.
        starters = pw["Starter/Bench"] == "Starter"
        pos_col = "Position" if "Position" in pw.columns else "Position started in (if starter)"
        pos_series = pw[pos_col].astype(str).str.upper()

        def _pick_one(sub_df: pd.DataFrame, by_max: bool) -> Optional[int]:
            """Return the row index of the single award winner, or None."""
            if sub_df.empty:
                return None
            extreme = sub_df["Points"].max() if by_max else sub_df["Points"].min()
            tied = sub_df[sub_df["Points"] == extreme]
            # Multi-way tie at 0 for min: don't award.
            if (not by_max) and float(extreme) == 0.0 and len(tied) >= 2:
                return None
            tied_sorted = tied.assign(_p=tied["Player"].astype(str)).sort_values("_p", kind="stable")
            return int(tied_sorted.index[0])

        for (yr, wk), g in pw.groupby(["Year", "Week"]):
            sg = g[starters.loc[g.index]]
            if sg.empty:
                continue
            # Player of the week
            idx = _pick_one(sg, by_max=True)
            if idx is not None:
                _set_flag(pw.index == idx, "Player of the week?")
            # Benchwarmer of the week
            idx = _pick_one(sg, by_max=False)
            if idx is not None:
                _set_flag(pw.index == idx, "Benchwarmer of the week?")

            for pos, col in [("QB", "QB of the week?"), ("RB", "RB of the week?"), ("WR", "WR of the week?"), ("TE", "TE of the week?")]:
                pg = sg[pos_series.loc[sg.index] == pos]
                idx = _pick_one(pg, by_max=True)
                if idx is not None:
                    _set_flag(pw.index == idx, col)

            # bench position awards (bench only)
            bg = g[~starters.loc[g.index]]
            for pos, col in [
                ("QB", "Bench QB of the week?"),
                ("RB", "Bench RB of the week?"),
                ("WR", "Bench WR of the week?"),
                ("TE", "Bench TE of the week?"),
            ]:
                pg = bg[pos_series.loc[bg.index] == pos]
                idx = _pick_one(pg, by_max=True)
                if idx is not None:
                    _set_flag(pw.index == idx, col)

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

        # Hardship engine.
        # Points lost when Points==0 AND (Injury or Suspension) AND NOT Bye.
        # Expected points = mean of the player's 5 active weeks BEFORE their
        # most recent active week (i.e. exclude the most recent active week
        # itself, since that game may have been cut short by a mid-game
        # injury and would otherwise depress the baseline).
        # An "active week" is points>0 AND not Injury/Susp/Bye.
        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)
        # Keep up to 6 most-recent active points; we will average the oldest
        # 5 (everything except the most recent active week).
        last6: Dict[str, deque] = defaultdict(lambda: deque(maxlen=6))
        exp_points: List[Optional[float]] = [None] * len(pw)
        points_lost: List[float] = [0.0] * len(pw)
        for i, row in pw.iterrows():
            player = row["Player"]
            pts = float(row["Points"])
            inj = bool(row.get("Injury?") or False)
            susp = bool(row.get("Suspension?") or False)
            bye = bool(row.get("Bye?") or False)
            hist = last6[player]
            # Baseline = up to 5 active weeks *before* the most recent active week.
            if len(hist) >= 2:
                baseline = list(hist)[:-1]
                expected = sum(baseline) / len(baseline)
            else:
                expected = None
            exp_points[i] = expected
            missed = (pts == 0.0) and (inj or susp) and (not bye)
            points_lost[i] = float(expected) if (missed and expected is not None) else 0.0
            if (pts > 0.0) and (not inj) and (not susp) and (not bye):
                hist.append(pts)
        pw["_expected_points_if_healthy"] = exp_points
        pw["_points_lost_inj_susp"] = points_lost

        # --------------------------
        # Activated Cuff detection
        # --------------------------
        # A player has an "activated cuff" in week W if all of:
        #   - their own last-5-played PPG average is < 10 (i.e. low-scorer)
        #   - another NFL teammate (same NFL team AND same position) is
        #     injured or suspended in W
        #   - that teammate's last-5-played avg exceeds this player's by >10 PPG
        # _expected_points_if_healthy is the rolling 5-played-game mean built by
        # the hardship engine just above, so reuse it as last-5-avg.
        try:
            cuff_col = (
                "- Activated Cuff? (Was a player of the same nfl team/position "
                "& who averages >10 PPG more over last 5 played games injured? "
                "Only for players with avg <10 PPG)"
            )
            pw_c = pw.copy()
            pw_c["_avg"] = pd.to_numeric(pw_c.get("_expected_points_if_healthy"), errors="coerce")
            pw_c["_inj"] = pw_c.get("Injury?", False).fillna(False).astype(bool)
            pw_c["_sus"] = pw_c.get("Suspension?", False).fillna(False).astype(bool)
            pw_c["_inj_or_sus"] = pw_c["_inj"] | pw_c["_sus"]
            pw_c["_nfl_team"] = pw_c.get("NFL team").astype(str)
            pw_c["_pos"] = pw_c.get("Position").astype(str)

            # Build the injured-teammate index: highest last-5 avg of any
            # injured/suspended player per (Year, Week, NFL team, Position).
            # Restricting to max() per group keeps the per-row comparison O(1).
            inj_rows = pw_c[
                pw_c["_inj_or_sus"]
                & pw_c["_avg"].notna()
                & (pw_c["_nfl_team"] != "")
                & (pw_c["_nfl_team"].str.lower() != "nan")
                & (pw_c["_pos"] != "")
            ]
            inj_max_by_group: Dict[Tuple[int, int, str, str], float] = {}
            if not inj_rows.empty:
                inj_grp = inj_rows.groupby(["Year", "Week", "_nfl_team", "_pos"])["_avg"].max()
                for (yr, wk, nt, ps), v in inj_grp.items():
                    try:
                        inj_max_by_group[(int(yr), int(wk), str(nt), str(ps))] = float(v)
                    except Exception:
                        continue

            activated: List[int] = [0] * len(pw_c)
            if inj_max_by_group:
                for i, row in pw_c.iterrows():
                    my_avg = row["_avg"]
                    if pd.isna(my_avg) or my_avg >= 10.0:
                        continue
                    nt = row["_nfl_team"]
                    ps = row["_pos"]
                    if not nt or nt.lower() == "nan" or not ps:
                        continue
                    try:
                        yr = int(row["Year"])
                        wk = int(row["Week"])
                    except Exception:
                        continue
                    best = inj_max_by_group.get((yr, wk, nt, ps))
                    if best is not None and best > float(my_avg) + 10.0:
                        activated[i] = 1
            pw[cuff_col] = activated
        except Exception as e:
            _log_exc(debug, "cuff_detection", e)

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

        tw["Hardship"] = pd.to_numeric(tw.get("Hardship_Points_Lost"), errors="coerce").fillna(0.0)
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

        # Brosenzweig / Sisenzweig (correct definition)
        # Brosenzweig: LOSS while 2nd-highest scoring team of the week.
        # Sisenzweig: WIN while 2nd-lowest scoring team of the week.
        tw["Brosenzweig"] = 0
        tw["Sisenzweig"] = 0
        if "PF" in tw.columns and "Win?" in tw.columns:
            tw_pf = tw.copy()
            tw_pf["PF"] = pd.to_numeric(tw_pf["PF"], errors="coerce").fillna(0.0)
            tw_pf["Win?"] = pd.to_numeric(tw_pf["Win?"], errors="coerce")
            for (yr, wk), g in tw_pf.groupby(["Year", "Week"]):
                if g.empty:
                    continue
                # ranks: 1 = highest (desc), 1 = lowest (asc)
                r_desc = g["PF"].rank(method="min", ascending=False)
                r_asc = g["PF"].rank(method="min", ascending=True)
                mask_b = (g["Win?"] == 0) & (r_desc == 2)
                mask_s = (g["Win?"] == 1) & (r_asc == 2)
                tw.loc[g.index[mask_b], "Brosenzweig"] = 1
                tw.loc[g.index[mask_s], "Sisenzweig"] = 1

        # Luck formula override:
        # 1/3*(1 - Hardship/league_avg_hardship) + WinVariance/4 - 1/10*Brosenzweig + 1/3*Efficiency
        try:
            tw["Hardship"] = pd.to_numeric(tw.get("Hardship"), errors="coerce").fillna(0.0)
            tw["Efficiency"] = pd.to_numeric(tw.get("Efficiency"), errors="coerce").fillna(0.0)
            if "Win Variance" in tw.columns:
                tw["Win Variance"] = pd.to_numeric(tw.get("Win Variance"), errors="coerce").fillna(0.0)
            else:
                tw["Win Variance"] = pd.to_numeric(tw.get("Luck"), errors="coerce").fillna(0.0)
            tw["Brosenzweig"] = pd.to_numeric(tw.get("Brosenzweig"), errors="coerce").fillna(0.0)

            lg_hard = tw.groupby(["Year", "Week"])["Hardship"].transform("mean")
            hardship_term = 1.0 - (tw["Hardship"] / lg_hard.replace(0, np.nan))
            hardship_term = hardship_term.replace([np.inf, -np.inf], np.nan).fillna(1.0)

            tw["Luck"] = (
                (1.0/3.0) * hardship_term
                + 0.25 * tw["Win Variance"]
                - 0.1 * tw["Brosenzweig"]
                + (1.0/3.0) * tw["Efficiency"]
            )
        except Exception as e:
            _log_exc(debug, "team_week_luck_formula", e)

    # --------------------------
    
        # Fill remaining schema columns in team-week (best-effort)
        try:
            # Cuffs: use player-week activated cuff flag (rostered and started)
            cuff_col = (
                "- Activated Cuff? (Was a player of the same nfl team/position "
                "& who averages >10 PPG more over last 5 played games injured? "
                "Only for players with avg <10 PPG)"
            )
            if (not pw.empty) and (cuff_col in pw.columns):
                pw_c = pw[["Team","Year","Week",cuff_col,"Starter/Bench"]].copy()
                pw_c[cuff_col] = pd.to_numeric(pw_c[cuff_col], errors="coerce").fillna(0.0)
                agg_c = pw_c.groupby(["Team","Year","Week"], as_index=False).agg(
                    **{
                        "Number of cuffs rostered": (cuff_col, "sum"),
                        "Number of cuffs started": (cuff_col, lambda s: float(s[pw_c.loc[s.index,"Starter/Bench"]=="Starter"].sum()) if len(s) else 0.0),
                    }
                )
                # Drop any pre-existing cuff cols before merge so the aggregated
                # values land in the natural column names (not '_c' suffixes).
                # The original merge used suffixes=("","_c") which kept the all-zero
                # placeholder column and put the real data under "Number of cuffs
                # rostered_c" — meaning team_week / team_year / league rollups all
                # read zeros despite the per-player flag being correct.
                tw = tw.drop(columns=["Number of cuffs rostered", "Number of cuffs started"], errors="ignore")
                tw = tw.merge(agg_c, how="left", on=["Team","Year","Week"])
                tw["Number of cuffs rostered"] = pd.to_numeric(tw.get("Number of cuffs rostered"), errors="coerce").fillna(0.0).round(0).astype(int)
                tw["Number of cuffs started"] = pd.to_numeric(tw.get("Number of cuffs started"), errors="coerce").fillna(0.0).round(0).astype(int)

            # Future draft capital (weighted rounds) + startup placeholder left blank for now
            if "Future draft capital" in tw.columns:
                fdc_vals = []
                for _, r in tw.iterrows():
                    yr = _to_int(r.get("Year"), None)
                    team_norm = _norm_team_name(r.get("Team"))
                    rid = season_team_to_roster.get(int(yr), {}).get(team_norm) if yr is not None else None
                    if yr is None or rid is None:
                        fdc_vals.append(0.0)
                        continue
                    fdc_vals.append(float(_future_cap_from_traded(traded_picks_by_season.get(int(yr), []), int(rid), int(yr))))
                tw["Future draft capital"] = pd.to_numeric(pd.Series(fdc_vals, index=tw.index), errors="coerce").fillna(0.0)

            if "Startup draft players remaining" in tw.columns:
                tw["Startup draft players remaining"] = None
        except Exception as e:
            _log_exc(debug, "team_week_fill_schema_cols", e)
# Derived team-week columns: pregame avg maxPF diff
    # --------------------------
    if not tw.empty:
        tw = tw.sort_values(["Team", "Year", "Week"]).reset_index(drop=True)
        tw["Max PF"] = pd.to_numeric(tw["Max PF"], errors="coerce")

        # Own pregame average Max PF (season-to-date, excluding current week)
        tw["Pregame avg MaxPF"] = tw.groupby(["Team", "Year"])["Max PF"].apply(
            lambda s: s.shift(1).expanding().mean()
        ).reset_index(level=[0, 1], drop=True)

        # Opponent-aware difference where matchup mapping is available.
        tw["Difference in pregame avg max PF from opponent"] = None

        tw_key = tw.copy()
        tw_key["_TeamNorm"] = tw_key["Team"].astype(str).map(_norm_team_name)
        tw_key["_OppNorm"] = tw_key.get("Opponent", pd.Series(dtype=str)).astype(str).map(_norm_team_name)

        by_key = {
            (int(r["Year"]), int(r["Week"]), str(r["_TeamNorm"])): int(i)
            for i, r in tw_key[["Year", "Week", "_TeamNorm"]].iterrows()
            if pd.notna(r["Year"]) and pd.notna(r["Week"])
        }

        # Primary: direct opponent lookup. Fallback: league-average pregame baseline.
        for i, r in tw_key.iterrows():
            yr = _to_int(r.get("Year"), None)
            wk = _to_int(r.get("Week"), None)
            opp_n = str(r.get("_OppNorm") or "")
            own_pre = _to_float(r.get("Pregame avg MaxPF"), None)
            if yr is None or wk is None or own_pre is None:
                continue

            opp_pre = None
            if opp_n:
                j = by_key.get((int(yr), int(wk), opp_n))
                if j is not None:
                    opp_pre = _to_float(tw_key.loc[j, "Pregame avg MaxPF"], None)

            if opp_pre is None:
                same_week = tw_key[(tw_key["Year"] == yr) & (tw_key["Week"] == wk)]
                vals = pd.to_numeric(same_week["Pregame avg MaxPF"], errors="coerce").dropna()
                if len(vals):
                    opp_pre = float(vals.mean())

            if opp_pre is not None:
                tw.loc[i, "Difference in pregame avg max PF from opponent"] = round(float(own_pre) - float(opp_pre), 2)

        # Align UPST with intended meaning: win despite lower pregame maxPF profile.
        tw["UPST"] = (
            (pd.to_numeric(tw.get("Win?"), errors="coerce") == 1)
            & (pd.to_numeric(tw.get("Difference in pregame avg max PF from opponent"), errors="coerce") < 0)
        ).astype(int)

        tw.drop(columns=["Pregame avg MaxPF"], inplace=True, errors="ignore")

    # --------------------------
    
    # --------------------------
    # Player-week: rolling 5-game diffs vs reference player + cuff adjusted diff
    # --------------------------
    if not pw.empty:
        try:
            pw["Year"] = pd.to_numeric(pw["Year"], errors="coerce").astype("Int64")
            pw["Week"] = pd.to_numeric(pw["Week"], errors="coerce").astype("Int64")
            pw["Points"] = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)

            # "played games" exclude injury/susp/bye
            played_mask = ~pw[["Injury?", "Suspension?", "Bye?"]].fillna(False).any(axis=1)

            pw_sorted = pw.sort_values(["Player", "Year", "Week"]).reset_index()
            # map (player,year,week)-> rolling avg last5 played (including current if played)
            rolling_avg = {}
            # NOTE: do NOT import deque inside this function.
            # An inner import would make `deque` a local variable for the entire
            # enclosing scope, which breaks earlier lambdas that reference the
            # global `deque` (CI failure: cannot access free variable 'deque').
            hist = defaultdict(lambda: deque(maxlen=5))
            for _, r in pw_sorted.iterrows():
                p=str(r["Player"]); yr=int(r["Year"]) if pd.notna(r["Year"]) else None; wk=int(r["Week"]) if pd.notna(r["Week"]) else None
                if yr is None or wk is None:
                    continue
                key=(p,yr,wk)
                # compute avg of previous played games (last5) BEFORE adding current
                prev=list(hist[(p,yr)])
                avg_prev=float(np.mean(prev)) if prev else None
                # if played, include current for future
                if bool(played_mask.loc[r["index"]]):
                    hist[(p,yr)].append(float(r["Points"]))
                rolling_avg[key]=avg_prev

            def get_avg(p,yr,wk):
                return rolling_avg.get((str(p),int(yr),int(wk)))

            diffs=[]
            cuff_adj=[]
            for _, r in pw.iterrows():
                ref=r.get("Reference player name")
                if not isinstance(ref,str) or ref.strip()=="":
                    diffs.append(None); cuff_adj.append(None); continue
                yr=r.get("Year"); wk=r.get("Week"); player=r.get("Player")
                if pd.isna(yr) or pd.isna(wk):
                    diffs.append(None); cuff_adj.append(None); continue
                avg_p=get_avg(player,yr,wk)
                avg_r=get_avg(ref,yr,wk)
                if (avg_p is None) or (avg_r is None):
                    diffs.append(None); cuff_adj.append(None); continue
                started = (r.get("Starter/Bench") == "Starter")
                diff = (avg_r-avg_p) if started else (avg_p-avg_r)
                diffs.append(round(float(diff),2))
                cuff = float(r.get(
                    "- Activated Cuff? (Was a player of the same nfl team/position "
                    "& who averages >10 PPG more over last 5 played games injured? "
                    "Only for players with avg <10 PPG)"
                ) or 0)
                cuff_adj.append(round(float(diff) * (0.5 if cuff else 1.0), 2))
            pw["Difference in averages of best/worst startables over previous 5 games"] = diffs
            pw["Cuff adjusted difference"] = cuff_adj
        except Exception as e:
            _log_exc(debug, "player_week_rolling_diffs", e)

    # --------------------------
    # Team-week: Tanking (math formula computed earlier in build_all by
    # _tanking_score and merged into tw via tank_df). Keep that score as-is
    # here — no more binary override. Round to 4 decimals for readability.
    # --------------------------
    if not tw.empty:
        try:
            tw["Tanking"] = pd.to_numeric(tw.get("Tanking"), errors="coerce").fillna(0.0).round(4)
        except Exception as e:
            _log_exc(debug, "team_week_tanking_round", e)
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
    if (
        not pw.empty
        and not tw.empty
        and {"Team", "Year", "Week"}.issubset(pw.columns)
        and {"Team", "Year", "Week", "Win?"}.issubset(tw.columns)
    ):
        tw_keys = tw[["Team", "Year", "Week", "Win?"]].copy()
        tw_keys["Team"] = tw_keys["Team"].astype(str)
        for col in ["Year", "Week"]:
            tw_keys[col] = pd.to_numeric(tw_keys[col], errors="coerce").astype("Int64").astype(object)
        win_map = tw_keys.set_index(["Team", "Year", "Week"])["Win?"].to_dict()

        pw_keys = pw[["Team", "Year", "Week"]].copy()
        pw_keys["Team"] = pw_keys["Team"].astype(str)
        for col in ["Year", "Week"]:
            pw_keys[col] = pd.to_numeric(pw_keys[col], errors="coerce").astype("Int64").astype(object)
        pw["Team win?"] = [
            win_map.get((team, year, week))
            for team, year, week in pw_keys.itertuples(index=False, name=None)
        ]

    player_year = pd.DataFrame()
    player_all = pd.DataFrame()
    if not pw.empty:
        pw_work = pw.copy()
        if "Player ID" in pw_work.columns:
            pw_work["Player ID"] = pw_work["Player ID"].astype(str)
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

        team_points = pw_work.groupby(["Player ID", "Year", "Team"], as_index=False)["Points"].sum()
        top_team = (
            team_points.sort_values(["Player ID", "Year", "Points"], ascending=[True, True, False])
            .drop_duplicates(["Player ID", "Year"])
            .rename(columns={"Team": "Top Team", "Points": "Top Team Points"})
        )
        last_team = (
            pw_work.sort_values(["Player ID", "Year", "Week"])
            .groupby(["Player ID", "Year"])
            .tail(1)[["Player ID", "Year", "Team"]]
            .rename(columns={"Team": "Last team"})
        )

        # Per-season rookie flag is taken as max across the season's weeks (a player
        # either was a rookie in YYYY or wasn't — every week of that season agrees).
        # Per-season age is the mean of weekly age (effectively mid-season age).
        pw_work["_rookie_int"] = pd.to_numeric(pw_work.get("Rookie?"), errors="coerce").fillna(0).astype(int)
        pw_work["_age_num"] = pd.to_numeric(pw_work.get("Age"), errors="coerce")

        # PPG split by starter/bench needs separate sums + counts.
        pw_work["_starter_points"] = pw_work["Points"].where(pw_work["Starter?"] == 1, other=0.0)
        pw_work["_bench_points"] = pw_work["Points"].where(pw_work["Starter?"] == 0, other=0.0)
        pw_work["_bench_weeks"] = (pw_work["Starter?"] == 0).astype(int)

        py_base = pw_work.groupby(["Player ID", "Year"], as_index=False).agg(
            Player=("Player", "first"),
            Points=("Points", "sum"),
            Avg_points=("Points", "mean"),
            Weeks_missed_injury=("Missed_injury", "sum"),
            Weeks_missed_suspension=("Missed_suspension", "sum"),
            Weeks_as_starter=("Starter?", "sum"),
            Weeks_as_bench=("_bench_weeks", "sum"),
            Number_of_teams=("Team", "nunique"),
            Weeks=("Points", "count"),
            Rookie_flag=("_rookie_int", "max"),
            Age_avg=("_age_num", "mean"),
            Starter_points_sum=("_starter_points", "sum"),
            Bench_points_sum=("_bench_points", "sum"),
            **{c: (c, "sum") for c in award_cols},
        )

        # Convert sums + counts -> averages, then drop the helper sum columns.
        py_base["PPG starter"] = py_base.apply(
            lambda r: round(r["Starter_points_sum"] / r["Weeks_as_starter"], 4)
            if r["Weeks_as_starter"] else None,
            axis=1,
        )
        py_base["PPG bench"] = py_base.apply(
            lambda r: round(r["Bench_points_sum"] / r["Weeks_as_bench"], 4)
            if r["Weeks_as_bench"] else None,
            axis=1,
        )
        py_base["PPG starter vs bench diff"] = py_base.apply(
            lambda r: round((r["PPG starter"] or 0) - (r["PPG bench"] or 0), 4)
            if r["PPG starter"] is not None and r["PPG bench"] is not None else None,
            axis=1,
        )
        py_base["Rookie?"] = py_base["Rookie_flag"].astype(bool)
        py_base["Age"] = py_base["Age_avg"].round(2)
        py_base = py_base.drop(columns=[
            "Rookie_flag", "Age_avg", "Starter_points_sum", "Bench_points_sum",
        ])

        py = py_base.merge(top_team[["Player ID", "Year", "Top Team"]], on=["Player ID", "Year"], how="left")
        py = py.merge(last_team, on=["Player ID", "Year"], how="left")

        team_points_all = pw_work.groupby(["Player ID", "Year", "Team"])["Points"].sum()
        total_points = pw_work.groupby(["Player ID", "Year"])["Points"].sum()
        max_share = (team_points_all.groupby(["Player ID", "Year"]).max() / total_points).rename("% of points (highest team)")
        min_share = (team_points_all.groupby(["Player ID", "Year"]).min() / total_points).rename("% of points (lowest team)")
        py = py.merge(max_share.reset_index(), on=["Player ID", "Year"], how="left")
        py = py.merge(min_share.reset_index(), on=["Player ID", "Year"], how="left")

        py = py.sort_values(["Player ID", "Year"]).reset_index(drop=True)
        py["Change in points from previous season"] = py.groupby("Player ID")["Points"].diff()
        py["Change in avg points from previous season"] = py.groupby("Player ID")["Avg_points"].diff()

        # Use transform() so the shift respects group boundaries. The
        # previous version was groupby(...).cumsum().shift(1) which shifts the
        # resulting global Series — first row of each player would inherit
        # the prior player's career totals, so a rookie's 'Change from career'
        # could come out positive against some unrelated veteran's stats.
        py["Career_points_before"] = py.groupby("Player ID")["Points"].transform(
            lambda s: s.cumsum().shift(1)
        )
        py["Career_years_before"] = py.groupby("Player ID").cumcount()
        py["Change in points from career"] = py.apply(
            lambda r: (r["Points"] - (r["Career_points_before"] / r["Career_years_before"]))
            if r["Career_years_before"] and pd.notna(r["Career_points_before"])
            else None,
            axis=1,
        )

        py["Career_points_before_total"] = py.groupby("Player ID")["Points"].transform(
            lambda s: s.cumsum().shift(1)
        )
        py["Career_weeks_before_total"] = py.groupby("Player ID")["Weeks"].transform(
            lambda s: s.cumsum().shift(1)
        )
        py["Change in avg points from career"] = py.apply(
            lambda r: (r["Avg_points"] - (r["Career_points_before_total"] / r["Career_weeks_before_total"]))
            if pd.notna(r["Career_weeks_before_total"]) and r["Career_weeks_before_total"]
            and pd.notna(r["Career_points_before_total"])
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

        py["Number of transactions"] = [
            int(player_tx_year.get((str(player_id), int(year) if pd.notna(year) else None), 0))
            for player_id, year in py[["Player ID", "Year"]].itertuples(index=False, name=None)
        ]
        py["Number of drops"] = [
            int(player_drop_year.get((str(player_id), int(year) if pd.notna(year) else None), 0))
            for player_id, year in py[["Player ID", "Year"]].itertuples(index=False, name=None)
        ]

        # Per-player trade counts from trades_rows. Each trade in trades.csv
        # has one row per team involved; the players sent to that team are
        # listed in that row's 'Assets received' (sic — column name is
        # misspelled in the schema and we preserve it). To avoid double
        # counting we only read the 'received' side: every traded player
        # appears in exactly one team's received cell per trade.
        player_trade_year: Dict[Tuple[str, int], int] = defaultdict(int)
        player_trade_all: Dict[str, int] = defaultdict(int)
        try:
            for tr_row in trades_rows:
                # Prefer the fantasy-year Season (which keeps offseason
                # trades attributed to the league iteration they belong to);
                # fall back to the calendar year of the Date for safety.
                yr_val = tr_row.get("Season")
                if yr_val is None:
                    date_s = tr_row.get("Date")
                    if not date_s:
                        continue
                    try:
                        yr_val = int(str(date_s)[:4])
                    except Exception:
                        continue
                try:
                    yr = int(yr_val)
                except Exception:
                    continue
                recv = tr_row.get("Assets received")
                if not recv or str(recv) == "0.0":
                    continue
                for asset in str(recv).split(";"):
                    asset = asset.strip()
                    if not asset:
                        continue
                    # Skip pick labels (start with a 4-digit year, e.g.
                    # '2025 1.??' or '2026 R2'). Player names never start
                    # with a 4-digit number.
                    if re.match(r"^\d{4}\b", asset):
                        continue
                    player_trade_year[(asset, yr)] += 1
                    player_trade_all[asset] += 1
        except Exception as e:
            _log_exc(debug, "player_trade_count", e)

        py["Number of trades"] = [
            int(player_trade_year.get((str(player_name), int(year) if pd.notna(year) else 0), 0))
            for player_name, year in py[["Player", "Year"]].itertuples(index=False, name=None)
        ]

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

        pa = pw_work.groupby(["Player ID"], as_index=False).agg(
            Player=("Player", "first"),
            Points=("Points", "sum"),
            Avg_points=("Points", "mean"),
            Weeks_missed_injury=("Missed_injury", "sum"),
            Weeks_missed_suspension=("Missed_suspension", "sum"),
            Weeks_as_starter=("Starter?", "sum"),
            Weeks_as_bench=("_bench_weeks", "sum"),
            Number_of_teams=("Team", "nunique"),
            Starter_points_sum=("_starter_points", "sum"),
            Bench_points_sum=("_bench_points", "sum"),
            **{c: (c, "sum") for c in award_cols},
        )
        # Same formula as player_year: derive PPG starter / bench / diff
        # from the per-week sums, drop the helper columns at the end.
        pa["PPG starter"] = pa.apply(
            lambda r: round(r["Starter_points_sum"] / r["Weeks_as_starter"], 4)
            if r["Weeks_as_starter"] else None,
            axis=1,
        )
        pa["PPG bench"] = pa.apply(
            lambda r: round(r["Bench_points_sum"] / r["Weeks_as_bench"], 4)
            if r["Weeks_as_bench"] else None,
            axis=1,
        )
        pa["PPG starter vs bench diff"] = pa.apply(
            lambda r: round((r["PPG starter"] or 0) - (r["PPG bench"] or 0), 4)
            if r["PPG starter"] is not None and r["PPG bench"] is not None else None,
            axis=1,
        )
        pa = pa.drop(columns=["Starter_points_sum", "Bench_points_sum", "Weeks_as_bench"], errors="ignore")

        top_team_all = (
            pw_work.groupby(["Player ID", "Team"], as_index=False)["Points"].sum()
            .sort_values(["Player ID", "Points"], ascending=[True, False])
            .drop_duplicates(["Player ID"])
            .rename(columns={"Team": "Top team", "Points": "Top team points"})
        )
        last_team_all = (
            pw_work.sort_values(["Year", "Week"])
            .groupby("Player ID")
            .tail(1)[["Player ID", "Team", "Rookie?", "Age"]]
            .rename(columns={"Team": "Last team"})
        )
        team_points_all_time = pw_work.groupby(["Player ID", "Team"])["Points"].sum()
        total_points_all_time = pw_work.groupby(["Player ID"])["Points"].sum()
        max_share_all = (team_points_all_time.groupby("Player ID").max() / total_points_all_time).rename("% of points (highest team)")
        min_share_all = (team_points_all_time.groupby("Player ID").min() / total_points_all_time).rename("% of points (lowest team)")

        pa = pa.merge(top_team_all[["Player ID", "Top team"]], on="Player ID", how="left")
        pa = pa.merge(last_team_all, on="Player ID", how="left")
        pa = pa.merge(max_share_all.reset_index(), on="Player ID", how="left")
        pa = pa.merge(min_share_all.reset_index(), on="Player ID", how="left")

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

        pa["Number of transactions"] = [
            int(player_tx_all.get(str(player_id), 0))
            for player_id in pa["Player ID"].tolist()
        ]
        pa["Number of drops"] = [
            int(player_drop_all.get(str(player_id), 0))
            for player_id in pa["Player ID"].tolist()
        ]
        # Career trade count, keyed by Player name (matches trades.csv assets).
        pa["Number of trades"] = [
            int(player_trade_all.get(str(name), 0)) for name in pa["Player"].tolist()
        ]

        player_all = pa

    # Team-year: compute record and vs records using raw opp_rid_map (still available in closures above? not anymore)
    team_year = pd.DataFrame()
    team_all = pd.DataFrame()
    if not tw.empty:
        # reconstruct team list
        teams = sorted(tw["Team"].dropna().astype(str).unique().tolist())
        # compute per game outcomes using raw opponent team when available.
        game_rows = []
        for (yr, wk), g in tw.groupby(["Year", "Week"]):
            g2 = g.copy()
            g2["PF"] = pd.to_numeric(g2["PF"], errors="coerce").fillna(0.0)
            g2["Points against"] = pd.to_numeric(g2["Points against"], errors="coerce").fillna(0.0)
            for idx, row in g2.iterrows():
                opp = row.get("Opponent Team (raw)")
                if not opp or pd.isna(opp):
                    match = g2[g2["PF"] == row["Points against"]]
                    if len(match) == 1:
                        opp = str(match.iloc[0]["Team"])
                    elif len(match) > 1:
                        match2 = match[match["Points against"] == row["PF"]]
                        if len(match2) == 1:
                            opp = str(match2.iloc[0]["Team"])
                if opp:
                    game_rows.append({
                        "Year": int(yr),
                        "Week": int(wk),
                        "Team": str(row["Team"]),
                        "OppTeam": str(opp),
                        "Win?": row.get("Win?"),
                        "PF": float(row["PF"]),
                        "PA": float(row["Points against"]),
                    })
        games_df = pd.DataFrame(game_rows).drop_duplicates(subset=["Year","Week","Team"])

        def _record_str(w, l, t=0):
            return f"{int(w)}-{int(l)}" + (f"-{int(t)}" if t else "")

        def _place_map(rows: List[Tuple[Any, ...]]) -> Dict[str, int]:
            if not rows:
                return {}
            return {str(team): idx + 1 for idx, (team, *_rest) in enumerate(rows)}

        def _normalize_games(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df.copy()
            gdf = df.copy()
            gdf["Team"] = gdf["Team"].astype(str)
            gdf["OppTeam"] = gdf["OppTeam"].astype(str)
            gdf["Win?"] = pd.to_numeric(gdf["Win?"], errors="coerce")
            gdf["Year"] = pd.to_numeric(gdf["Year"], errors="coerce").fillna(0).astype(int)
            return gdf

        def _wlt_for_team(df: pd.DataFrame, team: str, year: Optional[int] = None, opps: Optional[set] = None) -> Tuple[int, int, int]:
            if df.empty:
                return (0, 0, 0)
            sub = df[df["Team"] == str(team)]
            if year is not None:
                sub = sub[sub["Year"] == int(year)]
            if opps is not None:
                sub = sub[sub["OppTeam"].isin({str(o) for o in opps})]
            w = int((sub["Win?"] == 1).sum())
            l = int((sub["Win?"] == 0).sum())
            t = int((sub["Win?"] == 0.5).sum())
            return (w, l, t)

        def _win_pct(wlt: Tuple[int, int, int]) -> float:
            w, l, t = wlt
            gp = w + l + t
            return round((w + 0.5 * t) / gp, 4) if gp else 0.0

        def _wlt_for_team_pairs(df: pd.DataFrame, team: str, year_team_pairs: set) -> Tuple[int, int, int]:
            if df.empty or not year_team_pairs:
                return (0, 0, 0)
            sub = df[df["Team"] == str(team)]
            sub = sub[sub["YearOpp"].isin(year_team_pairs)]
            w = int((sub["Win?"] == 1).sum())
            l = int((sub["Win?"] == 0).sum())
            t = int((sub["Win?"] == 0.5).sum())
            return (w, l, t)

        def _playoff_elimination_weeks(
            df: pd.DataFrame,
            teams_by_year: Dict[int, set],
            playoff_starts: Dict[int, Optional[int]],
            playoff_teams: Dict[int, set],
        ) -> Dict[int, Dict[str, Optional[int]]]:
            elim_by_year: Dict[int, Dict[str, Optional[int]]] = {}
            if df.empty:
                return elim_by_year
            gdf = df.copy()
            gdf["Week"] = pd.to_numeric(gdf["Week"], errors="coerce")
            gdf["Win?"] = pd.to_numeric(gdf["Win?"], errors="coerce")
            for season, teams in teams_by_year.items():
                season_games = gdf[gdf["Year"] == int(season)].copy()
                playoff_start = playoff_starts.get(int(season))
                if playoff_start:
                    season_games = season_games[season_games["Week"] < playoff_start]
                if season_games.empty:
                    continue
                season_games = season_games.dropna(subset=["Week"])
                weeks = sorted({int(w) for w in season_games["Week"].tolist()})
                if not weeks:
                    continue

                season_games["wins"] = (season_games["Win?"] == 1).astype(int)
                season_games["losses"] = (season_games["Win?"] == 0).astype(int)
                season_games["ties"] = (season_games["Win?"] == 0.5).astype(int)
                week_results = season_games.groupby(["Team", "Week"], as_index=False)[["wins", "losses", "ties"]].sum()

                all_rows = pd.MultiIndex.from_product(
                    [sorted({str(t) for t in teams}), weeks], names=["Team", "Week"]
                ).to_frame(index=False)
                week_results = all_rows.merge(week_results, on=["Team", "Week"], how="left").fillna(0)
                week_results[["wins", "losses", "ties"]] = week_results[["wins", "losses", "ties"]].astype(int)

                week_results["cum_wins"] = week_results.groupby("Team")["wins"].cumsum()
                week_results["cum_losses"] = week_results.groupby("Team")["losses"].cumsum()
                week_results["cum_ties"] = week_results.groupby("Team")["ties"].cumsum()
                total_games = season_games.groupby("Team")["Week"].count().to_dict()
                week_results["total_games"] = week_results["Team"].map(total_games).fillna(0).astype(int)
                week_results["games_played"] = (
                    week_results["cum_wins"] + week_results["cum_losses"] + week_results["cum_ties"]
                )
                week_results["remaining"] = (week_results["total_games"] - week_results["games_played"]).clip(lower=0)
                week_results["max_win_pct"] = (
                    week_results["cum_wins"]
                    + week_results["remaining"]
                    + 0.5 * week_results["cum_ties"]
                ) / week_results["total_games"].replace(0, np.nan)
                week_results["min_win_pct"] = (
                    week_results["cum_wins"] + 0.5 * week_results["cum_ties"]
                ) / week_results["total_games"].replace(0, np.nan)

                elim_map: Dict[str, Optional[int]] = {}
                season_playoffs = {str(t) for t in playoff_teams.get(int(season), set())}
                for team in sorted({str(t) for t in teams}):
                    if team in season_playoffs:
                        elim_map[team] = None
                        continue
                    elim_week = None
                    for wk in weeks:
                        t_row = week_results[(week_results["Team"] == team) & (week_results["Week"] == wk)]
                        if t_row.empty:
                            continue
                        t_max = float(t_row["max_win_pct"].iloc[0])
                        others = week_results[(week_results["Week"] == wk) & (week_results["Team"] != team)]
                        if int((others["min_win_pct"] > t_max).sum()) >= 4:
                            elim_week = int(wk)
                            break
                    elim_map[team] = elim_week
                elim_by_year[int(season)] = elim_map
            return elim_by_year

        games_df = _normalize_games(games_df)
        if not games_df.empty:
            games_df["YearOpp"] = list(zip(games_df["Year"], games_df["OppTeam"]))

        playoff_teams_by_season: Dict[int, set] = {}
        champion_by_season: Dict[int, Optional[str]] = {}
        last_place_by_season: Dict[int, Optional[str]] = {}
        teams_by_season: Dict[int, set] = {}
        place_record_by_year: Dict[int, Dict[str, int]] = {}
        place_pf_by_year: Dict[int, Dict[str, int]] = {}
        place_maxpf_by_year: Dict[int, Dict[str, int]] = {}
        standings_place_by_season: Dict[int, Dict[str, int]] = {}
        pf_place_by_season: Dict[int, Dict[str, int]] = {}
        maxpf_place_by_season: Dict[int, Dict[str, int]] = {}
        for yr, g in tw.groupby("Year"):
            season = int(yr)
            teams_by_season[season] = set(g["Team"].dropna().astype(str).tolist())
            playoff_start = playoff_start_by_season.get(season)
            reg = g.copy()
            if playoff_start:
                reg = reg[pd.to_numeric(reg["Week"], errors="coerce") < playoff_start]
            reg["PF"] = pd.to_numeric(reg["PF"], errors="coerce").fillna(0.0)
            reg["Max PF"] = pd.to_numeric(reg["Max PF"], errors="coerce").fillna(0.0)
            reg["Win?"] = pd.to_numeric(reg["Win?"], errors="coerce")
            standings = []
            for team, tg in reg.groupby("Team"):
                wins = int((tg["Win?"] == 1).sum())
                losses = int((tg["Win?"] == 0).sum())
                ties = int((tg["Win?"] == 0.5).sum())
                pf = float(tg["PF"].sum())
                maxpf = float(tg["Max PF"].sum())
                standings.append((team, wins, losses, ties, pf, maxpf))
            standings.sort(key=lambda x: (x[1] + 0.5 * x[3], x[4]), reverse=True)
            standings_place_by_season[season] = {
                str(team): idx + 1 for idx, (team, *_rest) in enumerate(standings)
            }
            pf_sorted = sorted(standings, key=lambda x: x[4], reverse=True)
            pf_place_by_season[season] = {
                str(team): idx + 1 for idx, (team, *_rest) in enumerate(pf_sorted)
            }
            reg["Max PF"] = pd.to_numeric(reg.get("Max PF"), errors="coerce").fillna(0.0)
            maxpf_totals = []
            for team, tg in reg.groupby("Team"):
                maxpf_totals.append((team, float(tg["Max PF"].sum())))
            maxpf_totals.sort(key=lambda x: x[1], reverse=True)
            maxpf_place_by_season[season] = {
                str(team): idx + 1 for idx, (team, _maxpf) in enumerate(maxpf_totals)
            }
            playoff_teams_by_season[season] = set([t for t, *_ in standings[:4]])
            last_place_by_season[season] = standings[-1][0] if standings else None
            place_record_by_year[season] = _place_map(standings)
            standings_pf = sorted(standings, key=lambda x: x[4], reverse=True)
            standings_maxpf = sorted(standings, key=lambda x: x[5], reverse=True)
            place_pf_by_year[season] = _place_map(standings_pf)
            place_maxpf_by_year[season] = _place_map(standings_maxpf)
            champ = None
            if "Week label" in g.columns:
                finals = g[g["Week label"] == "Final"]
                champ_row = finals[finals["Win?"] == 1]
                if not champ_row.empty:
                    champ = str(champ_row.iloc[0]["Team"])
            if not champ and standings:
                champ = standings[0][0]
            champion_by_season[season] = champ

        playoff_elimination_by_season: Dict[int, Dict[str, Optional[int]]] = {}
        try:
            playoff_elimination_by_season = _playoff_elimination_weeks(
                games_df, teams_by_season, playoff_start_by_season, playoff_teams_by_season
            )
        except Exception as e:
            _log_exc(debug, "playoff_elimination_calc", e)

        
        # Determine season finishing positions (Result) from playoff/toilet brackets when available.
        season_finish: Dict[int, Dict[str, str]] = {}
        try:
            for yr, g in tw.groupby("Year"):
                season = int(yr)
                playoff_start = playoff_start_by_season.get(season)
                if not playoff_start:
                    continue
                finals_week = playoff_start + 1
                fin_map: Dict[str, str] = {}
                # Finals
                gf = tw[(tw["Year"]==season) & (tw["Week"]==finals_week) & (tw["Week label"]=="Final")].copy()
                gf["PF"] = pd.to_numeric(gf["PF"], errors="coerce").fillna(0.0)
                gf["Win?"] = pd.to_numeric(gf["Win?"], errors="coerce")
                if len(gf) == 2:
                    if gf["Win?"].notna().any():
                        gf = gf.sort_values("Win?", ascending=False)
                    else:
                        gf = gf.sort_values("PF", ascending=False)
                    fin_map[str(gf.iloc[0]["Team"])] = "Champion"
                    fin_map[str(gf.iloc[1]["Team"])] = "2nd"
                # 3rd place
                g3 = tw[(tw["Year"]==season) & (tw["Week"]==finals_week) & (tw["Week label"]=="3rd Place")].copy()
                g3["PF"] = pd.to_numeric(g3["PF"], errors="coerce").fillna(0.0)
                g3["Win?"] = pd.to_numeric(g3["Win?"], errors="coerce")
                if len(g3) == 2:
                    if g3["Win?"].notna().any():
                        g3 = g3.sort_values("Win?", ascending=False)
                    else:
                        g3 = g3.sort_values("PF", ascending=False)
                    fin_map[str(g3.iloc[0]["Team"])] = "3rd"
                    fin_map[str(g3.iloc[1]["Team"])] = "4th"

                # Non-playoff finishes (5th-8th) are based on regular-season record cutoff,
                # with PF as the tiebreaker. (Pre-2025: through 17 games; 2025+: through 15 games.)
                cutoff = 17 if season < 2025 else 15
                try:
                    all_teams = [str(t) for t in tw[tw["Year"] == season]["Team"].dropna().unique().tolist()]
                    playoff_teams = set([t for t, r in fin_map.items() if r in ("Champion", "2nd", "3rd", "4th")])
                    non_playoff = [t for t in all_teams if t not in playoff_teams]
                    if non_playoff and (not games_df.empty):
                        reg = games_df[(games_df["Year"] == season) & (games_df["Week"] <= cutoff)].copy()
                        reg["PF"] = pd.to_numeric(reg.get("PF", 0.0), errors="coerce").fillna(0.0)
                        reg["Win?"] = pd.to_numeric(reg.get("Win?", 0.0), errors="coerce").fillna(0.0)
                        sub = reg[reg["Team"].astype(str).isin(non_playoff)]
                        rows_np = []
                        for team_np, gg in sub.groupby(sub["Team"].astype(str)):
                            w = int((gg["Win?"] == 1).sum())
                            l = int((gg["Win?"] == 0).sum())
                            t_ = int((gg["Win?"] == 0.5).sum())
                            pf_sum = float(gg["PF"].sum())
                            win_pct = (w + 0.5 * t_) / max(1, w + l + t_)
                            rows_np.append((team_np, win_pct, pf_sum))
                        # Sort: record (win %) then PF
                        rows_np.sort(key=lambda x: (x[1], x[2]), reverse=True)
                        place = 5
                        for team_np, *_ in rows_np:
                            if place == 5:
                                fin_map[team_np] = "5th"
                            elif place == 6:
                                fin_map[team_np] = "6th"
                            elif place == 7:
                                fin_map[team_np] = "7th"
                            elif place == 8:
                                fin_map[team_np] = "8th"
                            place += 1
                            if place > 8:
                                break
                except Exception:
                    pass
                season_finish[season] = fin_map
        except Exception as e:
            _log_exc(debug, "season_finish_map", e)

        # team-year rollup
        all_time_rows = []
        for team, g in tw.groupby("Team"):
            wins = int((g["Win?"] == 1).sum())
            losses = int((g["Win?"] == 0).sum())
            ties = int((g["Win?"] == 0.5).sum())
            pf = float(pd.to_numeric(g["PF"], errors="coerce").fillna(0.0).sum())
            maxpf_sum = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).sum())
            all_time_rows.append((team, wins, losses, ties, pf, maxpf_sum))
        all_time_rows.sort(key=lambda x: (x[1] + 0.5 * x[3], x[4]), reverse=True)
        all_time_place_record = _place_map(all_time_rows)
        all_time_place_pf = _place_map(sorted(all_time_rows, key=lambda x: x[4], reverse=True))
        all_time_place_maxpf = _place_map(sorted(all_time_rows, key=lambda x: x[5], reverse=True))

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
            place_map = standings_place_by_season.get(int(yr), {})
            pf_place_map = pf_place_by_season.get(int(yr), {})
            maxpf_place_map = maxpf_place_by_season.get(int(yr), {})
            place = place_map.get(str(team))
            pf_place = pf_place_map.get(str(team))
            maxpf_place = maxpf_place_map.get(str(team))
            win_variance = None
            if place is not None and pf_place is not None and maxpf_place is not None:
                win_variance = -1 * float(place - ((pf_place + maxpf_place) / 2))
            row = {
                "Team": str(team),
                "Year": int(yr),
                "Result": "N/A",
                "Win %": winp,
                "Record": rec,
                "Record & win % vs each team": "N/A",
                "Record & win % vs playoff teams": "N/A",
                "Record & win % vs non-playoff teams": "N/A",
                "Record & win % vs champion": "N/A",
                "Record & win % vs last place": "N/A",
                "Change in win % from previous season": None,
                "Win Variance": win_variance,
                "Week of playoff elimination": playoff_elimination_by_season.get(int(yr), {}).get(str(team)),
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
                # Roll up per-week activity (already computed in team_week) into
                # the season total. Previously these stayed at N/A because no
                # aggregation step carried them across.
                "Number of transactions": int(pd.to_numeric(g.get("Number of transactions"), errors="coerce").fillna(0.0).sum()),
                "Number of trades": int(pd.to_numeric(g.get("Number of trades"), errors="coerce").fillna(0.0).sum()),
                "Amount of FAAB spent": round(float(pd.to_numeric(g.get("Amount of FAAB spent"), errors="coerce").fillna(0.0).sum()), 2),
                # Highest combined matchup score (own PF + opponent PF) the
                # team participated in during the season. team_week already
                # computes Combined matchup score per game.
                "Combined matchup score": float(pd.to_numeric(g.get("Combined matchup score"), errors="coerce").fillna(0.0).max()),
            }
            rows.append(row)
        team_year = pd.DataFrame(rows)

        # Pick-history-based rollups (Draft Value, # picks made by round).
        # Uses the final-owner team (who actually drafted) for each pick row,
        # which after the trade-chain rewrite above lives in pick_rows' Trade
        # columns (last non-empty Trade N) or in 'Original Team' when no trade
        # chain exists.
        try:
            if not ph.empty:
                phx = ph.copy()
                # Resolve picker = last non-empty Trade column, else Original Team
                def _picker(row):
                    for j in range(10, 0, -1):
                        v = row.get(f"Trade {j}")
                        if v and str(v) != "nan" and str(v).strip() not in ("", "N/A"):
                            return str(v)
                    return str(row.get("Original Team") or "")
                phx["_Picker"] = phx.apply(_picker, axis=1)
                # Parse round from Number (e.g., 'R1.2' -> 1)
                phx["_Round"] = phx["Number"].astype(str).str.extract(r"^R(\d+)").astype(float)
                # Parse pick-no for draft value (1/(pick_no+1)).
                phx["_PickNo"] = phx["Number"].astype(str).str.extract(r"^R\d+\.(\d+)").astype(float)
                phx["_DraftVal"] = phx["_PickNo"].apply(lambda x: 1.0 / (x + 1.0) if pd.notna(x) else 0.0)
                pick_agg = phx.groupby(["_Picker", "Year"], dropna=False).agg(
                    _draft_value=("_DraftVal", "sum"),
                    _total_picks=("Number", "count"),
                    _r1=("_Round", lambda s: int((s == 1.0).sum())),
                ).reset_index().rename(columns={"_Picker": "Team"})
                team_year = team_year.merge(pick_agg, on=["Team", "Year"], how="left")
                team_year["Draft Value"] = team_year["_draft_value"].fillna(0.0).round(4)
                team_year["Number of first round picks made"] = team_year["_r1"].fillna(0).astype(int)
                team_year["Total number of picks made"] = team_year["_total_picks"].fillna(0).astype(int)
                team_year.drop(columns=["_draft_value", "_total_picks", "_r1"], inplace=True, errors="ignore")
        except Exception as e:
            _log_exc(debug, "team_year_pick_rollups", e)

        # Future draft capital: weighted future picks owned by team at end of
        # each season. Uses _future_cap_from_traded against the traded_picks
        # snapshot stored per season.
        try:
            future_cap_vals = []
            for idx, row in team_year.iterrows():
                team = str(row["Team"])
                year = int(row["Year"])
                rid = season_team_to_roster.get(int(year), {}).get(_norm_team_name(team))
                if rid is None:
                    future_cap_vals.append(0.0)
                    continue
                tps = traded_picks_by_season.get(int(year), [])
                future_cap_vals.append(round(_future_cap_from_traded(tps, int(rid), int(year)), 4))
            team_year["Future draft capital"] = future_cap_vals
        except Exception as e:
            _log_exc(debug, "team_year_future_cap", e)

        # Rebuild all win % and record columns for team-year (single source of truth)
        try:
            teams_by_year = team_year.groupby("Year")["Team"].apply(lambda s: sorted(s.dropna().astype(str).unique().tolist())).to_dict()
            for idx, row in team_year.iterrows():
                team = str(row["Team"])
                year = int(row["Year"])
                wlt = _wlt_for_team(games_df, team, year=year)
                team_year.at[idx, "Record"] = _record_str(*wlt)
                team_year.at[idx, "Win %"] = _win_pct(wlt)

                opp_list = [t for t in teams_by_year.get(year, []) if t != team]
                pieces = []
                for opp in opp_list:
                    wlt_opp = _wlt_for_team(games_df, team, year=year, opps={opp})
                    pieces.append(f"{opp}: {_record_str(*wlt_opp)} ({_win_pct(wlt_opp)})")
                team_year.at[idx, "Record & win % vs each team"] = "; ".join(pieces) if pieces else "N/A"

                playoffs = playoff_teams_by_season.get(year, set())
                champ = champion_by_season.get(year)
                lastp = last_place_by_season.get(year)
                non_playoffs = set(teams_by_season.get(year, set())) - set(playoffs) if playoffs else set()

                wlt_play = _wlt_for_team(games_df, team, year=year, opps=playoffs if playoffs else None)
                wlt_non = _wlt_for_team(games_df, team, year=year, opps=non_playoffs if non_playoffs else None)
                wlt_champ = _wlt_for_team(games_df, team, year=year, opps={champ} if champ else None)
                wlt_last = _wlt_for_team(games_df, team, year=year, opps={lastp} if lastp else None)

                team_year.at[idx, "Record & win % vs playoff teams"] = f"{_record_str(*wlt_play)} ({_win_pct(wlt_play)})" if playoffs else "N/A"
                team_year.at[idx, "Record & win % vs non-playoff teams"] = f"{_record_str(*wlt_non)} ({_win_pct(wlt_non)})" if non_playoffs else "N/A"
                team_year.at[idx, "Record & win % vs champion"] = f"{_record_str(*wlt_champ)} ({_win_pct(wlt_champ)})" if champ else "N/A"
                team_year.at[idx, "Record & win % vs last place"] = f"{_record_str(*wlt_last)} ({_win_pct(wlt_last)})" if lastp else "N/A"

            if not games_df.empty:
                for year, teams_list in teams_by_year.items():
                    for team in teams_list:
                        for opp in teams_list:
                            if opp == team:
                                continue
                            wlt_opp = _wlt_for_team(games_df, team, year=int(year), opps={opp})
                            team_year.loc[
                                (team_year["Year"] == int(year)) & (team_year["Team"] == team),
                                f"Record vs {opp}",
                            ] = _record_str(*wlt_opp)
                            team_year.loc[
                                (team_year["Year"] == int(year)) & (team_year["Team"] == team),
                                f"Win % vs {opp}",
                            ] = _win_pct(wlt_opp)
        except Exception as e:
            _log_exc(debug, "team_year_rebuild_records", e)

        # Compute starter/roster turnover metrics.
        # Definitions:
        #  - Inseason starter turnover  = (distinct players started any week this season)
        #                                 minus (typical week's starter count)
        #  - Inseason roster turnover   = same logic for full roster
        #  - Offseason starter/roster turnover = symmetric-difference between last
        #    week of prior season and first week of this season, divided by 2 so a
        #    swap of 3 starters reads as "3" rather than "6".
        # The endpoints-only inseason calculation we replaced missed streaming,
        # mid-season trades, and waiver churn whenever the final lineup happened
        # to resemble the opening one.
        try:
            if not pw.empty and "Starter/Bench" in pw.columns:
                pw_t = pw.copy()
                pw_t["Week"] = pd.to_numeric(pw_t["Week"], errors="coerce")

                def _set_for(team, year, week, starters_only):
                    df = pw_t[(pw_t["Team"] == team) & (pw_t["Year"] == year) & (pw_t["Week"] == week)]
                    if starters_only:
                        df = df[df["Starter/Bench"].astype(str).str.lower().eq("starter")]
                    return set(df["Player"].dropna().astype(str).tolist())

                def _distinct_minus_baseline(team, year, starters_only):
                    """Return (distinct players used) - (typical week's count).
                    Typical = median across weeks of the per-week count, so a
                    single short week (e.g. opening week with empty slots) does
                    not skew the baseline."""
                    g = pw_t[(pw_t["Team"] == team) & (pw_t["Year"] == year)]
                    if starters_only:
                        g = g[g["Starter/Bench"].astype(str).str.lower().eq("starter")]
                    weeks = sorted([int(w) for w in g["Week"].dropna().unique().tolist()])
                    if not weeks:
                        return 0
                    weekly_counts = [
                        len(set(g[g["Week"] == w]["Player"].dropna().astype(str).tolist()))
                        for w in weeks
                    ]
                    weekly_counts = [c for c in weekly_counts if c > 0]
                    if not weekly_counts:
                        return 0
                    baseline = int(round(sorted(weekly_counts)[len(weekly_counts) // 2]))
                    distinct = len(set(g["Player"].dropna().astype(str).tolist()))
                    return max(0, distinct - baseline)

                for (team, year), g in pw_t.groupby(["Team", "Year"]):
                    weeks = sorted([int(w) for w in g["Week"].dropna().unique().tolist()])
                    if not weeks:
                        continue
                    first_w = weeks[0]
                    in_s = _distinct_minus_baseline(team, year, starters_only=True)
                    in_r = _distinct_minus_baseline(team, year, starters_only=False)
                    team_year.loc[(team_year["Team"] == team) & (team_year["Year"] == year), "Inseason starter turnover"] = in_s
                    team_year.loc[(team_year["Team"] == team) & (team_year["Year"] == year), "Inseason roster turnover"] = in_r

                    # Offseason vs previous season: endpoint comparison with /2 so
                    # the count reads as "players swapped" instead of "slot changes".
                    prev_year = int(year) - 1
                    if ((pw_t["Team"] == team) & (pw_t["Year"] == prev_year)).any():
                        gprev = pw_t[(pw_t["Team"] == team) & (pw_t["Year"] == prev_year)]
                        prev_weeks = sorted([int(w) for w in gprev["Week"].dropna().unique().tolist()])
                        if prev_weeks:
                            prev_last = prev_weeks[-1]
                            s_prev = _set_for(team, prev_year, prev_last, True)
                            r_prev = _set_for(team, prev_year, prev_last, False)
                            s_first = _set_for(team, year, first_w, True)
                            r_first = _set_for(team, year, first_w, False)
                            off_s = len(s_prev.symmetric_difference(s_first)) // 2
                            off_r = len(r_prev.symmetric_difference(r_first)) // 2
                            team_year.loc[(team_year["Team"] == team) & (team_year["Year"] == year), "Offseason starter turnover"] = off_s
                            team_year.loc[(team_year["Team"] == team) & (team_year["Year"] == year), "Offseason roster turnover"] = off_r
        except Exception as e:
            _log_exc(debug, "turnover_metrics_team_year", e)

        # --------------------------
        # Fill missing Team-year columns from team-week (flags, tanking, luck, roster composition, etc.)
        # --------------------------
        try:
            agg_year = tw.groupby(["Team", "Year"], as_index=False).agg(
                **{
                    "Tanking": ("Tanking", "sum"),
                    "Luck": ("Luck", "sum"),
                    "Times Brosenzweig": ("Brosenzweig", "sum"),
                    "Times Sisenzweig": ("Sisenzweig", "sum"),
                    "Times Highest score?": ("Highest score?", "sum"),
                    "Times Lowest score?": ("Lowest score?", "sum"),
                    "Times Narrowest victory?": ("Narrowest victory?", "sum"),
                    "Times Largest blowout?": ("Largest blowout?", "sum"),
                    "Times Most efficient?": ("Most efficient?", "sum"),
                    "Times Least efficient?": ("Least efficient?", "sum"),
                    "Times Top half of league?": ("Top half of league?", "sum"),
                    "Most number of players started from same NFL team": ("Most number of players started from same NFL team", "max"),
                    "Most number of players rostered from same NFL team": ("Most number of players rostered from same NFL team", "max"),
                    "Most number of QBs started from same NFL team": ("Most number of QBs started from same NFL team", "max"),
                    "Most number of QBs rostered from same NFL team": ("Most number of QBs rostered from same NFL team", "max"),
                    "Most number of RBs started from same NFL team": ("Most number of RBs started from same NFL team", "max"),
                    "Most number of RBs rostered from same NFL team": ("Most number of RBs rostered from same NFL team", "max"),
                    "Most number of WR started from same NFL team": ("Most number of WR started from same NFL team", "max"),
                    "Most number of WR rostered from same NFL team": ("Most number of WR rostered from same NFL team", "max"),
                    "Most number of TE started from same NFL team": ("Most number of TE started from same NFL team", "max"),
                    "Most number of TE rostered from same NFL team": ("Most number of TE rostered from same NFL team", "max"),
                    "Number of NFL teams among starting players": ("Number of NFL teams among starting players", "max"),
                    "Number of NFL teams among rostered players": ("Number of NFL teams among rostered players", "max"),
                    "Number of rookies started": ("Number of rookies started", "sum"),
                    "Number of rookies rostered": ("Number of rookies rostered", "sum"),
                    "Player average age": ("Player average age", "mean"),
                    "Difference between highest and lowest starters": ("Difference between highest and lowest starters", "max"),
                    "Number of donuts": ("Number of donuts", "sum"),
                    "Number of players under 10": ("Number of players under 10", "sum"),
                    "Number of players over 20": ("Number of players over 20", "sum"),
                    "Number of players over 30": ("Number of players over 30", "sum"),
                    "Number of players over 40": ("Number of players over 40", "sum"),
                    "Number of players over 50": ("Number of players over 50", "sum"),
                    "Number of cuffs rostered": ("Number of cuffs rostered", "sum"),
                    "Number of cuffs started": ("Number of cuffs started", "sum"),
                }
            )
            team_year = team_year.merge(agg_year, how="left", on=["Team", "Year"])

        except Exception as e:
            _log_exc(debug, "team_year_aggregate_fill", e)


        # Result + vs-category records (rebuilt using normalized games)
        try:

            # Fill Result from bracket-derived finish map when available.
            if "Result" in team_year.columns and season_finish:
                def _res(team, year):
                    m = season_finish.get(int(year), {})
                    return m.get(str(team))
                team_year["Result"] = team_year.apply(lambda r: _res(r["Team"], r["Year"]), axis=1)

            results = []
            for _, r in team_year.iterrows():
                team = str(r["Team"])
                yr = int(r["Year"])
                playoffs = playoff_teams_by_season.get(yr, set())
                champ = champion_by_season.get(yr)
                lastp = last_place_by_season.get(yr)
                teams_in_year = set(team_year[team_year["Year"] == yr]["Team"].astype(str).tolist())
                non_playoffs = teams_in_year - set(playoffs) if playoffs else set()

                res = season_finish.get(yr, {}).get(team, r.get("Result"))
                if not res:
                    if champ and team == champ:
                        res = "Champion"
                    elif lastp and team == lastp:
                        res = "Last place"
                    elif team in playoffs:
                        res = "Playoffs"
                    else:
                        res = "Missed playoffs"

                wlt_play = _wlt_for_team(games_df, team, year=yr, opps=playoffs if playoffs else None)
                wlt_non = _wlt_for_team(games_df, team, year=yr, opps=non_playoffs if non_playoffs else None)
                wlt_champ = _wlt_for_team(games_df, team, year=yr, opps={champ} if champ else None)
                wlt_last = _wlt_for_team(games_df, team, year=yr, opps={lastp} if lastp else None)

                results.append({
                    "Team": team,
                    "Year": yr,
                    "Result": res,
                    "Record vs playoff teams": _record_str(*wlt_play) if playoffs else "N/A",
                    "Win % vs playoff teams": _win_pct(wlt_play) if playoffs else None,
                    "Record vs non-playoff teams": _record_str(*wlt_non) if non_playoffs else "N/A",
                    "Win % vs non-playoff teams": _win_pct(wlt_non) if non_playoffs else None,
                    "Record vs champion": _record_str(*wlt_champ) if champ else "N/A",
                    "Win % vs champion": _win_pct(wlt_champ) if champ else None,
                    "Record vs last place": _record_str(*wlt_last) if lastp else "N/A",
                    "Win % vs last place": _win_pct(wlt_last) if lastp else None,
                })
            extra = pd.DataFrame(results)
            team_year = team_year.drop(columns=[c for c in extra.columns if c in team_year.columns and c not in ["Team","Year"]], errors="ignore")
            team_year = team_year.merge(extra, how="left", on=["Team","Year"])
            team_year["Week of playoff elimination"] = team_year.get("Week of playoff elimination", "N/A")
            team_year["Offseason roster turnover"] = team_year.get("Offseason roster turnover", 0).fillna(0)
            team_year["Inseason roster turnover"] = team_year.get("Inseason roster turnover", 0).fillna(0)
        except Exception as e:
            _log_exc(debug, "team_year_results_vs_records", e)

        team_year = team_year.sort_values(["Team", "Year"]).reset_index(drop=True)
        team_year["Change in win % from previous season"] = team_year.groupby("Team")["Win %"].diff()
        team_year_win_variance = {}
        for team, val in team_year.groupby("Team")["Win Variance"].mean().items():
            team_year_win_variance[str(team)] = float(val) if pd.notna(val) else None

        # team-all-time rollup
        championship_counts = {}
        for champ in champion_by_season.values():
            if champ:
                champ_name = str(champ)
                championship_counts[champ_name] = championship_counts.get(champ_name, 0) + 1

        rows = []
        for team, g in tw.groupby("Team"):
            wins = int((g["Win?"] == 1).sum())
            losses = int((g["Win?"] == 0).sum())
            ties = int((g["Win?"] == 0.5).sum())
            gp = max(1, wins + losses + ties)
            pf = float(pd.to_numeric(g["PF"], errors="coerce").fillna(0.0).sum())
            pa = float(pd.to_numeric(g["Points against"], errors="coerce").fillna(0.0).sum())
            diff = pf - pa
            maxpf_sum = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).sum())
            maxpf_avg = float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0.0).mean())
            all_time_place_record_value = all_time_place_record.get(str(team))
            all_time_place_pf_value = all_time_place_pf.get(str(team))
            all_time_place_maxpf_value = all_time_place_maxpf.get(str(team))
            if (
                all_time_place_record_value is not None
                and all_time_place_pf_value is not None
                and all_time_place_maxpf_value is not None
            ):
                win_variance = (
                    all_time_place_record_value
                    - ((all_time_place_pf_value + all_time_place_maxpf_value) / 2)
                )
            else:
                win_variance = None
            row = {
                "Team": str(team),
                "All time win %": round((wins + 0.5 * ties) / gp, 4),
                "All time record": _record_str(wins, losses, ties),
                "Championships": championship_counts.get(str(team), 0),
                "Record & win % vs each team": "N/A",
                "Record & win % vs playoff teams": "N/A",
                "Record & win % vs non-playoff teams": "N/A",
                "Record & win % vs champions": "N/A",
                "Record & win % vs last place": "N/A",
                "Win Variance": team_year_win_variance.get(str(team)),
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

        # Rebuild all win % and record columns for team-all-time
        try:
            playoff_pairs = {
                (year, team)
                for year, teams in playoff_teams_by_season.items()
                for team in teams
            }
            champ_pairs = {
                (year, champ)
                for year, champ in champion_by_season.items()
                if champ
            }
            last_place_pairs = {
                (year, lastp)
                for year, lastp in last_place_by_season.items()
                if lastp
            }
            non_playoff_pairs = {
                (year, team)
                for year, teams in teams_by_season.items()
                for team in teams
                if team not in playoff_teams_by_season.get(year, set())
            }
            for idx, row in team_all.iterrows():
                team = str(row["Team"])
                wlt = _wlt_for_team(games_df, team)
                team_all.at[idx, "All time record"] = _record_str(*wlt)
                team_all.at[idx, "All time win %"] = _win_pct(wlt)

                opp_list = [t for t in teams if t != team]
                pieces = []
                for opp in opp_list:
                    wlt_opp = _wlt_for_team(games_df, team, opps={opp})
                    pieces.append(f"{opp}: {_record_str(*wlt_opp)} ({_win_pct(wlt_opp)})")
                    team_all.at[idx, f"Record vs {opp}"] = _record_str(*wlt_opp)
                    team_all.at[idx, f"Win % vs {opp}"] = _win_pct(wlt_opp)
                team_all.at[idx, "Record & win % vs each team"] = "; ".join(pieces) if pieces else "N/A"

            for idx, row in team_all.iterrows():
                team = str(row["Team"])
                wlt_play = _wlt_for_team_pairs(games_df, team, playoff_pairs)
                wlt_non = _wlt_for_team_pairs(games_df, team, non_playoff_pairs)
                wlt_ch = _wlt_for_team_pairs(games_df, team, champ_pairs)
                wlt_last = _wlt_for_team_pairs(games_df, team, last_place_pairs)

                team_all.at[idx, "Record & win % vs playoff teams"] = f"{_record_str(*wlt_play)} ({_win_pct(wlt_play)})" if playoff_pairs else "N/A"
                team_all.at[idx, "Record & win % vs non-playoff teams"] = f"{_record_str(*wlt_non)} ({_win_pct(wlt_non)})" if non_playoff_pairs else "N/A"
                team_all.at[idx, "Record & win % vs champions"] = f"{_record_str(*wlt_ch)} ({_win_pct(wlt_ch)})" if champ_pairs else "N/A"
                team_all.at[idx, "Record & win % vs last place"] = f"{_record_str(*wlt_last)} ({_win_pct(wlt_last)})" if last_place_pairs else "N/A"
        except Exception as e:
            _log_exc(debug, "team_all_rebuild_records", e)

        # --------------------------
        # Fill missing Team-all-time columns from team-week (flags, roster composition, etc.)
        # --------------------------
        try:
            agg_all = tw.groupby("Team", as_index=False).agg(
                **{
                    "Times Brosenzweig": ("Brosenzweig", "sum"),
                    "Times Sisenzweig": ("Sisenzweig", "sum"),
                    "Times Highest score?": ("Highest score?", "sum"),
                    "Times Lowest score?": ("Lowest score?", "sum"),
                    "Times Narrowest victory?": ("Narrowest victory?", "sum"),
                    "Times Largest blowout?": ("Largest blowout?", "sum"),
                    "Times Most efficient?": ("Most efficient?", "sum"),
                    "Times Least efficient?": ("Least efficient?", "sum"),
                    "Times Top half of league?": ("Top half of league?", "sum"),
                    "Most number of players started from same NFL team": ("Most number of players started from same NFL team", "max"),
                    "Most number of players rostered from same NFL team": ("Most number of players rostered from same NFL team", "max"),
                    "Most number of QBs started from same NFL team": ("Most number of QBs started from same NFL team", "max"),
                    "Most number of QBs rostered from same NFL team": ("Most number of QBs rostered from same NFL team", "max"),
                    "Most number of RBs started from same NFL team": ("Most number of RBs started from same NFL team", "max"),
                    "Most number of RBs rostered from same NFL team": ("Most number of RBs rostered from same NFL team", "max"),
                    "Most number of WR started from same NFL team": ("Most number of WR started from same NFL team", "max"),
                    "Most number of WR rostered from same NFL team": ("Most number of WR rostered from same NFL team", "max"),
                    "Most number of TE started from same NFL team": ("Most number of TE started from same NFL team", "max"),
                    "Most number of TE rostered from same NFL team": ("Most number of TE rostered from same NFL team", "max"),
                    "Number of NFL teams among starting players": ("Number of NFL teams among starting players", "max"),
                    "Number of NFL teams among rostered players": ("Number of NFL teams among rostered players", "max"),
                    "Number of rookies started": ("Number of rookies started", "sum"),
                    "Number of rookies rostered": ("Number of rookies rostered", "sum"),
                    "Player average age": ("Player average age", "mean"),
                    "Difference between highest and lowest starters": ("Difference between highest and lowest starters", "max"),
                    "Combined matchup score": ("Combined matchup score", "max"),
                    "Number of donuts": ("Number of donuts", "sum"),
                    "Number of players under 10": ("Number of players under 10", "sum"),
                    "Number of players over 20": ("Number of players over 20", "sum"),
                    "Number of players over 30": ("Number of players over 30", "sum"),
                    "Number of players over 40": ("Number of players over 40", "sum"),
                    "Number of players over 50": ("Number of players over 50", "sum"),
                    "Number of cuffs rostered": ("Number of cuffs rostered", "sum"),
                    "Number of cuffs started": ("Number of cuffs started", "sum"),
                }
            )
            team_all = team_all.merge(agg_all, how="left", on="Team")
        except Exception as e:
            _log_exc(debug, "team_all_aggregate_fill", e)

        # Roll up team_year-only fields into team_all_time. These were all
        # hardcoded to 0 (Draft Value, picks made, transactions, trades,
        # FAAB, turnover, future cap) because the previous agg_all merge
        # only pulled from team_week which doesn't have them.
        try:
            if not team_year.empty:
                ty_for_all = team_year.groupby("Team", as_index=False).agg(
                    **{
                        "Draft Value": ("Draft Value", "sum"),
                        "Number of first round picks made": ("Number of first round picks made", "sum"),
                        "Total number of picks made": ("Total number of picks made", "sum"),
                        "Number of transactions": ("Number of transactions", "sum"),
                        "Number of trades": ("Number of trades", "sum"),
                        "Amount of FAAB spent": ("Amount of FAAB spent", "sum"),
                        "Offseason starter turnover": ("Offseason starter turnover", "sum"),
                        "Inseason starter turnover": ("Inseason starter turnover", "sum"),
                        "Offseason roster turnover": ("Offseason roster turnover", "sum"),
                        "Inseason roster turnover": ("Inseason roster turnover", "sum"),
                        "Future draft capital": ("Future draft capital", "sum"),
                    }
                )
                team_all = team_all.drop(
                    columns=[c for c in ty_for_all.columns if c != "Team" and c in team_all.columns],
                    errors="ignore",
                ).merge(ty_for_all, on="Team", how="left")
        except Exception as e:
            _log_exc(debug, "team_all_from_team_year", e)

        # Top-up rollup: trades / transactions / FAAB from preseason seasons
        # that didn't produce a team_year row (e.g. 2026 before NFL Week 1).
        # We read trades_rows / transactions_rows directly and add only the
        # delta — counts already attributed to a team_year stay attributed.
        try:
            ty_years = set(team_year["Year"].astype(int).unique().tolist()) if not team_year.empty else set()
            # Trades not represented in team_year
            extra_trades_by_team: Dict[str, int] = defaultdict(int)
            for tr_row in trades_rows:
                try:
                    dt = tr_row.get("Date")
                    if not dt:
                        continue
                    yr = int(str(dt)[:4])
                    if yr in ty_years:
                        continue
                    tm = tr_row.get("Team")
                    if tm:
                        extra_trades_by_team[str(tm)] += 1
                except Exception:
                    continue
            extra_tx_by_team: Dict[str, int] = defaultdict(int)
            extra_faab_by_team: Dict[str, float] = defaultdict(float)
            for tx_row in transactions_rows:
                try:
                    dt = tx_row.get("Date")
                    if not dt:
                        continue
                    yr = int(str(dt)[:4])
                    if yr in ty_years:
                        continue
                    tm = tx_row.get("Team")
                    if tm:
                        extra_tx_by_team[str(tm)] += 1
                        try:
                            faab = float(tx_row.get("Faab") or 0.0)
                        except Exception:
                            faab = 0.0
                        extra_faab_by_team[str(tm)] += faab
                except Exception:
                    continue

            if extra_trades_by_team or extra_tx_by_team or extra_faab_by_team:
                for idx, row in team_all.iterrows():
                    tm = str(row.get("Team") or "")
                    if tm in extra_trades_by_team:
                        cur = pd.to_numeric(team_all.at[idx, "Number of trades"], errors="coerce")
                        team_all.at[idx, "Number of trades"] = int((0 if pd.isna(cur) else cur) + extra_trades_by_team[tm])
                    if tm in extra_tx_by_team:
                        cur = pd.to_numeric(team_all.at[idx, "Number of transactions"], errors="coerce")
                        team_all.at[idx, "Number of transactions"] = int((0 if pd.isna(cur) else cur) + extra_tx_by_team[tm])
                    if tm in extra_faab_by_team:
                        cur = pd.to_numeric(team_all.at[idx, "Amount of FAAB spent"], errors="coerce")
                        team_all.at[idx, "Amount of FAAB spent"] = round(float((0 if pd.isna(cur) else cur) + extra_faab_by_team[tm]), 2)
        except Exception as e:
            _log_exc(debug, "team_all_preseason_topup", e)

        # Unique-player positional counts for team-year and team-all-time (by Player ID)
        try:
            required_cols = {"Team", "Year", "Player ID", "Position", "Starter/Bench"}
            if not pw.empty and required_cols.issubset(set(pw.columns)):
                pw_counts = pw[list(required_cols)].copy()
                pw_counts = pw_counts.dropna(subset=["Player ID", "Team", "Year"])
                pw_counts["Player ID"] = pw_counts["Player ID"].astype(str)
                pw_counts["Position"] = pw_counts["Position"].astype(str).str.upper()
                pw_counts["Starter/Bench"] = pw_counts["Starter/Bench"].astype(str)
                pw_counts = pw_counts[pw_counts["Position"].isin(["QB", "RB", "WR", "TE"])]

                year_rostered = (
                    pw_counts.groupby(["Team", "Year", "Position"])["Player ID"]
                    .nunique()
                    .unstack("Position")
                    .fillna(0)
                    .reset_index()
                )
                year_started = (
                    pw_counts[pw_counts["Starter/Bench"].str.lower().eq("starter")]
                    .groupby(["Team", "Year", "Position"])["Player ID"]
                    .nunique()
                    .unstack("Position")
                    .fillna(0)
                    .reset_index()
                )

                started_rename = {pos: f"Number of {pos} started" for pos in ["QB", "RB", "WR", "TE"] if pos in year_started.columns}
                rostered_rename = {pos: f"Number of {pos} rostered" for pos in ["QB", "RB", "WR", "TE"] if pos in year_rostered.columns}
                year_started = year_started.rename(columns=started_rename)
                year_rostered = year_rostered.rename(columns=rostered_rename)

                if not team_year.empty:
                    team_year = team_year.merge(year_started, on=["Team", "Year"], how="left")
                    team_year = team_year.merge(year_rostered, on=["Team", "Year"], how="left")
                    for pos in ["QB", "RB", "WR", "TE"]:
                        team_year[f"Number of {pos} started"] = (
                            pd.to_numeric(team_year.get(f"Number of {pos} started"), errors="coerce")
                            .fillna(0)
                            .astype(int)
                        )
                        team_year[f"Number of {pos} rostered"] = (
                            pd.to_numeric(team_year.get(f"Number of {pos} rostered"), errors="coerce")
                            .fillna(0)
                            .astype(int)
                        )

                all_rostered = (
                    pw_counts.groupby(["Team", "Position"])["Player ID"]
                    .nunique()
                    .unstack("Position")
                    .fillna(0)
                )
                all_started = (
                    pw_counts[pw_counts["Starter/Bench"].str.lower().eq("starter")]
                    .groupby(["Team", "Position"])["Player ID"]
                    .nunique()
                    .unstack("Position")
                    .fillna(0)
                )

                if not team_all.empty:
                    for pos in ["QB", "RB", "WR", "TE"]:
                        if pos in all_started.columns:
                            team_all[f"Number of {pos} started"] = (
                                team_all["Team"].map(all_started[pos]).fillna(0).astype(int)
                            )
                        else:
                            team_all[f"Number of {pos} started"] = 0
                        if pos in all_rostered.columns:
                            team_all[f"Number of {pos} rostered"] = (
                                team_all["Team"].map(all_rostered[pos]).fillna(0).astype(int)
                            )
                        else:
                            team_all[f"Number of {pos} rostered"] = 0

                if "Rookie?" in pw.columns:
                    rookies = pw[["Team", "Year", "Player ID", "Starter/Bench", "Rookie?"]].copy()
                    rookies = rookies.dropna(subset=["Player ID", "Team", "Year"])
                    rookies["Player ID"] = rookies["Player ID"].astype(str)
                    rookies["Starter/Bench"] = rookies["Starter/Bench"].astype(str)
                    rookies["Rookie?"] = pd.to_numeric(rookies["Rookie?"], errors="coerce").fillna(0).astype(int)
                    rookies = rookies[rookies["Rookie?"] == 1]

                    year_rookies_rostered = (
                        rookies.groupby(["Team", "Year"])["Player ID"]
                        .nunique()
                        .reset_index()
                    )
                    year_rookies_started = (
                        rookies[rookies["Starter/Bench"].str.lower().eq("starter")]
                        .groupby(["Team", "Year"])["Player ID"]
                        .nunique()
                        .reset_index()
                    )

                    if not team_year.empty:
                        team_year = team_year.drop(
                            columns=["Number of rookies started", "Number of rookies rostered"],
                            errors="ignore",
                        )
                        team_year = team_year.merge(
                            year_rookies_started.rename(columns={"Player ID": "Number of rookies started"}),
                            on=["Team", "Year"],
                            how="left",
                        )
                        team_year = team_year.merge(
                            year_rookies_rostered.rename(columns={"Player ID": "Number of rookies rostered"}),
                            on=["Team", "Year"],
                            how="left",
                        )
                        team_year["Number of rookies started"] = (
                            pd.to_numeric(team_year.get("Number of rookies started"), errors="coerce")
                            .fillna(0)
                            .astype(int)
                        )
                        team_year["Number of rookies rostered"] = (
                            pd.to_numeric(team_year.get("Number of rookies rostered"), errors="coerce")
                            .fillna(0)
                            .astype(int)
                        )

                    all_rookies_rostered = rookies.groupby("Team")["Player ID"].nunique()
                    all_rookies_started = (
                        rookies[rookies["Starter/Bench"].str.lower().eq("starter")]
                        .groupby("Team")["Player ID"]
                        .nunique()
                    )

                    if not team_all.empty:
                        team_all["Number of rookies started"] = (
                            team_all["Team"].map(all_rookies_started).fillna(0).astype(int)
                        )
                        team_all["Number of rookies rostered"] = (
                            team_all["Team"].map(all_rookies_rostered).fillna(0).astype(int)
                        )
        except Exception as e:
            _log_exc(debug, "team_unique_player_counts", e)

        # vs-category records (all-time)
        try:
            playoff_pairs = {
                (year, team)
                for year, teams in playoff_teams_by_season.items()
                for team in teams
            }
            champ_pairs = {
                (year, champ)
                for year, champ in champion_by_season.items()
                if champ
            }
            last_place_pairs = {
                (year, lastp)
                for year, lastp in last_place_by_season.items()
                if lastp
            }
            non_playoff_pairs = {
                (year, team)
                for year, teams in teams_by_season.items()
                for team in teams
                if team not in playoff_teams_by_season.get(year, set())
            }

            extra = []
            for team in team_all["Team"].astype(str).tolist():
                wlt_play = _wlt_for_team_pairs(games_df, team, playoff_pairs)
                wlt_non = _wlt_for_team_pairs(games_df, team, non_playoff_pairs)
                wlt_ch = _wlt_for_team_pairs(games_df, team, champ_pairs)
                wlt_last = _wlt_for_team_pairs(games_df, team, last_place_pairs)

                extra.append({
                    "Team": team,
                    "Record vs playoff teams": _record_str(*wlt_play) if playoff_pairs else "N/A",
                    "Win % vs playoff teams": _win_pct(wlt_play) if playoff_pairs else None,
                    "Record vs non-playoff teams": _record_str(*wlt_non) if non_playoff_pairs else "N/A",
                    "Win % vs non-playoff teams": _win_pct(wlt_non) if non_playoff_pairs else None,
                    "Record vs champions": _record_str(*wlt_ch) if champ_pairs else "N/A",
                    "Win % vs champions": _win_pct(wlt_ch) if champ_pairs else None,
                    "Record vs last place": _record_str(*wlt_last) if last_place_pairs else "N/A",
                    "Win % vs last place": _win_pct(wlt_last) if last_place_pairs else None,
                })
            extra = pd.DataFrame(extra)
            team_all = team_all.drop(columns=[c for c in extra.columns if c in team_all.columns and c!="Team"], errors="ignore")
            team_all = team_all.merge(extra, how="left", on="Team")
        except Exception as e:
            _log_exc(debug, "team_all_vs_records", e)

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
                "Avg margin": (float(g.loc[pd.to_numeric(g.get("Win?"), errors="coerce") == 1, "Margin"].mean()) if (pd.to_numeric(g.get("Win?"), errors="coerce") == 1).any() else None),
                "Margin range": (float(g.loc[pd.to_numeric(g.get("Win?"), errors="coerce") == 1, "Margin"].max() - g.loc[pd.to_numeric(g.get("Win?"), errors="coerce") == 1, "Margin"].min()) if (pd.to_numeric(g.get("Win?"), errors="coerce") == 1).any() else None),
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
                "Amount of FAAB spent": float(pd.to_numeric(g.get("Amount of FAAB spent"), errors="coerce").fillna(0.0).sum()),
            })
        league_week = pd.DataFrame(rows)

        # Attach Week Name (custom week naming) if available
        try:
            if 'week_name_global' in locals() and (not week_name_global.empty):
                league_week = league_week.merge(week_name_global, on=["Year","Week"], how="left")
        except Exception as e:
            _log_exc(debug, "league_week_week_name", e)


        # Fill additional league-week columns from team-week (schema completeness)
        try:
            agg_lw = g_week.groupby(["Year","Week"], as_index=False).agg(
                **{
                    "Most number of players started from same NFL team": ("Most number of players started from same NFL team", "max"),
                    "Most number of players rostered from same NFL team": ("Most number of players rostered from same NFL team", "max"),
                    "Most number of QBs started from same NFL team": ("Most number of QBs started from same NFL team", "max"),
                    "Most number of QBs rostered from same NFL team": ("Most number of QBs rostered from same NFL team", "max"),
                    "Most number of RBs started from same NFL team": ("Most number of RBs started from same NFL team", "max"),
                    "Most number of RBs rostered from same NFL team": ("Most number of RBs rostered from same NFL team", "max"),
                    "Most number of WR started from same NFL team": ("Most number of WR started from same NFL team", "max"),
                    "Most number of WR rostered from same NFL team": ("Most number of WR rostered from same NFL team", "max"),
                    "Most number of TE started from same NFL team": ("Most number of TE started from same NFL team", "max"),
                    "Most number of TE rostered from same NFL team": ("Most number of TE rostered from same NFL team", "max"),
                    "Number of NFL teams among starting players": ("Number of NFL teams among starting players", "max"),
                    "Number of NFL teams among rostered players": ("Number of NFL teams among rostered players", "max"),
                    "Number of rookies started": ("Number of rookies started", "sum"),
                    "Number of rookies rostered": ("Number of rookies rostered", "sum"),
                    "Player average age": ("Player average age", "mean"),
                    "Difference between highest and lowest starters": ("Difference between highest and lowest starters", "max"),
                    "Number of donuts": ("Number of donuts", "sum"),
                    "Number of players under 10": ("Number of players under 10", "sum"),
                    "Number of players over 20": ("Number of players over 20", "sum"),
                    "Number of players over 30": ("Number of players over 30", "sum"),
                    "Number of players over 40": ("Number of players over 40", "sum"),
                    "Number of players over 50": ("Number of players over 50", "sum"),
                    "Number of cuffs rostered": ("Number of cuffs rostered", "sum"),
                    "Number of cuffs started": ("Number of cuffs started", "sum"),
                    "Startup draft players remaining": ("Startup draft players remaining", "max"),
                }
            )
            league_week = league_week.merge(agg_lw, how="left", on=["Year","Week"])
            league_week["Amount of FAAB spent"] = pd.to_numeric(league_week.get("Amount of FAAB spent"), errors="coerce").fillna(0.0)
        except Exception as e:
            _log_exc(debug, "league_week_fill_extra", e)

        rows = []
        for yr, g in g_week.groupby("Year"):
            margin_abs = g["Margin"].abs()
            win_mask = pd.to_numeric(g.get("Win?"), errors="coerce") == 1
            rows.append({
                "Year": int(yr),
                "(smallest) Playoff tiebreaker": "N/A",
                "PF": float(g["PF"].sum()),
                "Avg PF": float(g["PF"].mean()) if g["PF"].notna().any() else None,
                "PF Range": float(g["PF"].max() - g["PF"].min()) if g["PF"].notna().any() else None,
                "Avg margin": float(g.loc[win_mask, "Margin"].mean()) if win_mask.any() else None,
                "Margin range": float(g.loc[win_mask, "Margin"].max() - g.loc[win_mask, "Margin"].min()) if win_mask.any() else None,
                "Number of games within 10": int((margin_abs <= 10).sum() / 2),
                "Number of games within 5": int((margin_abs <= 5).sum() / 2),
                "Max PF": float(g["Max PF"].sum()),
                "Avg max PF": float(g["Max PF"].mean()) if g["Max PF"].notna().any() else None,
                "Efficiency": float(g["Efficiency"].mean()) if g["Efficiency"].notna().any() else None,
                "Number of weeks missed due to injury": int(pd.to_numeric(g.get("Number of Injuries"), errors="coerce").fillna(0.0).sum()),
                "Number of weeks missed due to suspensions": int(pd.to_numeric(g.get("Number of suspensions"), errors="coerce").fillna(0.0).sum()),
                # League-year turnover = sum across all teams from team_year
                # (team_year is computed before league_year). Inseason starter
                # turnover was previously averaged from team_week, which is a
                # different thing; switch to team_year sum for consistency.
                "Inseason starter turnover": 0,  # filled from team_year below
                "Offseason starter turnover": 0,  # filled from team_year below
                "Inseason roster turnover": 0,    # filled from team_year below
                "Offseason roster turnover": 0,   # filled from team_year below
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
                "Amount of FAAB spent": float(pd.to_numeric(g.get("Amount of FAAB spent"), errors="coerce").fillna(0.0).sum()),
            })
        league_year = pd.DataFrame(rows)

        # Fill additional league-year columns from team-week
        try:
            agg_ly = g_week.groupby(["Year"], as_index=False).agg(
                **{
                    "Most number of players started from same NFL team": ("Most number of players started from same NFL team", "max"),
                    "Most number of players rostered from same NFL team": ("Most number of players rostered from same NFL team", "max"),
                    "Most number of QBs started from same NFL team": ("Most number of QBs started from same NFL team", "max"),
                    "Most number of QBs rostered from same NFL team": ("Most number of QBs rostered from same NFL team", "max"),
                    "Most number of RBs started from same NFL team": ("Most number of RBs started from same NFL team", "max"),
                    "Most number of RBs rostered from same NFL team": ("Most number of RBs rostered from same NFL team", "max"),
                    "Most number of WR started from same NFL team": ("Most number of WR started from same NFL team", "max"),
                    "Most number of WR rostered from same NFL team": ("Most number of WR rostered from same NFL team", "max"),
                    "Most number of TE started from same NFL team": ("Most number of TE started from same NFL team", "max"),
                    "Most number of TE rostered from same NFL team": ("Most number of TE rostered from same NFL team", "max"),
                    "Number of NFL teams among starting players": ("Number of NFL teams among starting players", "max"),
                    "Number of NFL teams among rostered players": ("Number of NFL teams among rostered players", "max"),
                    "Number of rookies started": ("Number of rookies started", "sum"),
                    "Number of rookies rostered": ("Number of rookies rostered", "sum"),
                    "Player average age": ("Player average age", "mean"),
                    "Difference between highest and lowest starters": ("Difference between highest and lowest starters", "max"),
                    "Number of donuts": ("Number of donuts", "sum"),
                    "Number of players under 10": ("Number of players under 10", "sum"),
                    "Number of players over 20": ("Number of players over 20", "sum"),
                    "Number of players over 30": ("Number of players over 30", "sum"),
                    "Number of players over 40": ("Number of players over 40", "sum"),
                    "Number of players over 50": ("Number of players over 50", "sum"),
                    "Number of cuffs rostered": ("Number of cuffs rostered", "sum"),
                    "Number of cuffs started": ("Number of cuffs started", "sum"),
                    "Startup draft players remaining": ("Startup draft players remaining", "max"),
                }
            )
            league_year = league_year.merge(agg_ly, how="left", on=["Year"])
            league_year["Amount of FAAB spent"] = pd.to_numeric(league_year.get("Amount of FAAB spent"), errors="coerce").fillna(0.0)
        except Exception as e:
            _log_exc(debug, "league_year_fill_extra", e)

        # Roll up turnover + transactions/trades from team_year into league_year.
        # These were hardcoded to 0 even though the team_year aggregation produces
        # real values per team.
        try:
            if not team_year.empty:
                ty_agg = team_year.groupby("Year", as_index=False).agg(
                    **{
                        "Offseason starter turnover": ("Offseason starter turnover", "sum"),
                        "Inseason starter turnover": ("Inseason starter turnover", "sum"),
                        "Offseason roster turnover": ("Offseason roster turnover", "sum"),
                        "Inseason roster turnover": ("Inseason roster turnover", "sum"),
                        "_ty_tx": ("Number of transactions", "sum"),
                        "_ty_tr": ("Number of trades", "sum"),
                    }
                )
                league_year = league_year.drop(
                    columns=[
                        "Offseason starter turnover",
                        "Inseason starter turnover",
                        "Offseason roster turnover",
                        "Inseason roster turnover",
                    ],
                    errors="ignore",
                ).merge(ty_agg, on="Year", how="left")
                # Number of transactions / trades roll up from team_year too —
                # league_year had these at 0 before despite team_year being correct.
                if "_ty_tx" in league_year.columns:
                    league_year["Number of transactions"] = pd.to_numeric(league_year["_ty_tx"], errors="coerce").fillna(0).astype(int)
                if "_ty_tr" in league_year.columns:
                    league_year["Number of trades"] = pd.to_numeric(league_year["_ty_tr"], errors="coerce").fillna(0).astype(int)
                league_year.drop(columns=["_ty_tx", "_ty_tr"], inplace=True, errors="ignore")
        except Exception as e:
            _log_exc(debug, "league_year_team_year_rollup", e)

        league_all = pd.DataFrame([{
            "PF": float(pd.to_numeric(g_week["PF"], errors="coerce").fillna(0.0).sum()),
            "Avg PF": float(pd.to_numeric(g_week["PF"], errors="coerce").fillna(0.0).mean()),
            "PF Range": float(g_week["PF"].max() - g_week["PF"].min()) if g_week["PF"].notna().any() else None,
            "Avg margin": (float(g_week.loc[pd.to_numeric(g_week.get("Win?"), errors="coerce") == 1, "Margin"].mean()) if (pd.to_numeric(g_week.get("Win?"), errors="coerce") == 1).any() else None),
            "Margin range": (float(g_week.loc[pd.to_numeric(g_week.get("Win?"), errors="coerce") == 1, "Margin"].max() - g_week.loc[pd.to_numeric(g_week.get("Win?"), errors="coerce") == 1, "Margin"].min()) if (pd.to_numeric(g_week.get("Win?"), errors="coerce") == 1).any() else None),
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

        # Fill additional league-all-time columns from team-week
        try:
            league_all["Most number of players started from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of players started from same NFL team"), errors="coerce").max())
            league_all["Most number of players rostered from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of players rostered from same NFL team"), errors="coerce").max())
            league_all["Most number of QBs started from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of QBs started from same NFL team"), errors="coerce").max())
            league_all["Most number of QBs rostered from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of QBs rostered from same NFL team"), errors="coerce").max())
            league_all["Most number of RBs started from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of RBs started from same NFL team"), errors="coerce").max())
            league_all["Most number of RBs rostered from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of RBs rostered from same NFL team"), errors="coerce").max())
            league_all["Most number of WR started from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of WR started from same NFL team"), errors="coerce").max())
            league_all["Most number of WR rostered from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of WR rostered from same NFL team"), errors="coerce").max())
            league_all["Most number of TE started from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of TE started from same NFL team"), errors="coerce").max())
            league_all["Most number of TE rostered from same NFL team"] = float(pd.to_numeric(g_week.get("Most number of TE rostered from same NFL team"), errors="coerce").max())
            league_all["Number of NFL teams among starting players"] = float(pd.to_numeric(g_week.get("Number of NFL teams among starting players"), errors="coerce").max())
            league_all["Number of NFL teams among rostered players"] = float(pd.to_numeric(g_week.get("Number of NFL teams among rostered players"), errors="coerce").max())
            league_all["Number of rookies started"] = float(pd.to_numeric(g_week.get("Number of rookies started"), errors="coerce").sum())
            league_all["Number of rookies rostered"] = float(pd.to_numeric(g_week.get("Number of rookies rostered"), errors="coerce").sum())
            league_all["Player average age"] = float(pd.to_numeric(g_week.get("Player average age"), errors="coerce").mean())
            league_all["Difference between highest and lowest starters"] = float(pd.to_numeric(g_week.get("Difference between highest and lowest starters"), errors="coerce").max())
            league_all["Number of donuts"] = float(pd.to_numeric(g_week.get("Number of donuts"), errors="coerce").sum())
            league_all["Number of players under 10"] = float(pd.to_numeric(g_week.get("Number of players under 10"), errors="coerce").sum())
            league_all["Number of players over 20"] = float(pd.to_numeric(g_week.get("Number of players over 20"), errors="coerce").sum())
            league_all["Number of players over 30"] = float(pd.to_numeric(g_week.get("Number of players over 30"), errors="coerce").sum())
            league_all["Number of players over 40"] = float(pd.to_numeric(g_week.get("Number of players over 40"), errors="coerce").sum())
            league_all["Number of players over 50"] = float(pd.to_numeric(g_week.get("Number of players over 50"), errors="coerce").sum())
            league_all["Number of cuffs rostered"] = float(pd.to_numeric(g_week.get("Number of cuffs rostered"), errors="coerce").sum())
            league_all["Number of cuffs started"] = float(pd.to_numeric(g_week.get("Number of cuffs started"), errors="coerce").sum())
            league_all["Startup draft players remaining"] = float(pd.to_numeric(g_week.get("Startup draft players remaining"), errors="coerce").max())
            league_all["Amount of FAAB spent"] = float(pd.to_numeric(g_week.get("Amount of FAAB spent"), errors="coerce").fillna(0.0).sum())
        except Exception as e:
            _log_exc(debug, "league_all_fill_extra", e)


    # --------------------------
    # Write outputs (schema contract)
    # --------------------------
    
    # --------------------------
    # Transactions / Trades: link columns + tanking (best-effort)
    # --------------------------
    try:
        # normalize date
        if not tx.empty and "Date" in tx.columns:
            # format='ISO8601' parses each value independently against
            # any ISO-8601 variant rather than inferring one format
            # across the column. Without it, pandas locks onto the
            # first row's format (Sleeper's microsecond-precision
            # space-separated form) and silently coerces any other
            # ISO variant to NaT — which dropped the manual Puka row
            # whose Date was the cleaner 'YYYY-MM-DDTHH:MM:SS+ZZ:ZZ'.
            tx["Date"] = pd.to_datetime(tx["Date"], errors="coerce", utc=True, format="ISO8601")
            # Drop rows that couldn't be anchored to a real timestamp. The
            # orphan-drop guard in the source loop only catches the case
            # where both created_dt and created_date are None; values that
            # stringify but fail pd.to_datetime (e.g., 'None'/'NaT'/garbled
            # epochs) still produce NaT here. Those rows can't be ordered
            # for link-prev/next or year-tanking joins, and would otherwise
            # land in transactions.csv with Date='N/A'.
            tx = tx[tx["Date"].notna()].reset_index(drop=True)
            tx = tx.sort_values(["Team","Date"]).reset_index(drop=True)
            # link columns as row numbers (1-indexed within each team).
            # 'Link to previous' on row 1 is NaN, otherwise points at row N-1.
            # 'Link to next' on the last row of each team is NaN, otherwise
            # points at row N+1. The previous formula used shift(-1)+2 which
            # was off-by-one (row 1 got linked to row 3 instead of row 2).
            tx["Link to previous transaction"] = tx.groupby("Team").cumcount().replace(0, np.nan)
            tx["Link to next transaction"] = tx.groupby("Team").cumcount() + 2
            tx.loc[tx.groupby("Team").tail(1).index, "Link to next transaction"] = np.nan

            # Tanking — single column joined off team_year for the row's
            # Season (fantasy year). Previously this was emitted as separate
            # 'Tanking before' / 'Tanking after' columns, but the rollup
            # was always a single season-level value so the two columns
            # were guaranteed equal — misleading. Collapse to one column.
            if not team_year.empty and "Season" in tx.columns:
                ty_map = team_year.set_index(["Team","Year"])["Tanking"].to_dict()
                tx["Tanking"] = [float(ty_map.get((str(t), int(y)), 0)) for t,y in zip(tx["Team"], tx["Season"])]
        else:
            if "Tanking" in tx.columns:
                tx["Tanking"] = pd.to_numeric(tx["Tanking"], errors="coerce").fillna(0.0)
    except Exception as e:
        _log_exc(debug, "transactions_links_tanking", e)

    try:
        if not tr.empty and "Date" in tr.columns:
            tr["Date"] = pd.to_datetime(tr["Date"], errors="coerce", utc=True, format="ISO8601")
            # Same guard as transactions: drop rows we can't anchor in time.
            tr = tr[tr["Date"].notna()].reset_index(drop=True)
            tr = tr.sort_values(["Team","Date"]).reset_index(drop=True)
            tr["Link to previous transaction"] = tr.groupby("Team").cumcount().replace(0, np.nan)
            tr["Link to next transaction"] = tr.groupby("Team").cumcount() + 2
            tr.loc[tr.groupby("Team").tail(1).index, "Link to next transaction"] = np.nan

            if not team_year.empty and "Season" in tr.columns:
                ty_map = team_year.set_index(["Team","Year"])["Tanking"].to_dict()
                tr["Tanking"] = [float(ty_map.get((str(t), int(y)), 0)) for t,y in zip(tr["Team"], tr["Season"])]
    except Exception as e:
        _log_exc(debug, "trades_links_tanking", e)
    # Known-player validation report (best-effort): checks core columns against public expectations.
    try:
        validation = _known_player_column_errors(repo_root, pw)
        val_path = repo_root / "exports" / "raw" / "known_player_column_errors.csv"
        val_path.parent.mkdir(parents=True, exist_ok=True)
        validation.to_csv(val_path, index=False)
        if not validation.empty:
            _log(debug, f"[{_now_iso()}] WARN known-player validation mismatches: {len(validation)}")
    except Exception as e:
        _log_exc(debug, "known_player_validation", e)

    context = {
        "player_week": pw,
        "player_year": player_year,
        "player_all_time": player_all,
        "team_week": tw,
        "team_year": team_year,
        "team_all_time": team_all,
        "league_week": league_week,
        "league_year": league_year,
        "league_all_time": league_all,
        "transactions": tx,
        "trades": tr,
        "pick_history": ph,
    }
    tables = [
        (doc.FILE_NAME, doc.build_output(context), doc.PLAN_KEY)
        for doc in DOCUMENT_MODULES
    ]
    write_outputs(tables)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    try:
        cfg = yaml.safe_load((repo_root / "config/league.yaml").read_text())
        league_id = str(cfg["league_id"])
        min_season = cfg.get("min_season")
        max_season = cfg.get("max_season")

        mode = str(os.environ.get("LOTG_MODE", "both")).lower().strip()
        if mode not in {"snapshot", "build", "both"}:
            mode = "both"

        if mode in {"snapshot", "both"}:
            from lotg_support.snapshot import snapshot_all
            try:
                snapshot_all(repo_root, league_id=league_id, min_season=min_season, max_season=max_season)
            except Exception as e:
                _fatal_log(repo_root, "snapshot_all", e)
                raise

        if mode in {"build", "both"}:
            try:
                build_all(repo_root)
            except Exception as e:
                _fatal_log(repo_root, "build_all", e)
                raise
    except Exception as e:
        _fatal_log(repo_root, "main", e)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise
