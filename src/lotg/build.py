from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta, date
from collections import Counter, deque
import json

import pandas as pd
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
from .lineup import max_points_lineup
from .plan import load_plan_catalog, require_columns


# --------------------------
# Run config
# --------------------------

@dataclass
class RunConfig:
    league_id: str
    min_season: int | None
    max_season: int | None
    season_type: str = "regular"


# --------------------------
# Small safe helpers
# --------------------------

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

def _epoch_ms_to_date(ms: Any) -> Optional[date]:
    try:
        ms_i = int(ms)
        if ms_i <= 0:
            return None
        return datetime.fromtimestamp(ms_i / 1000, tz=timezone.utc).date()
    except Exception:
        return None

def _calc_age(birth_date_str: Optional[str], on_date: date) -> Optional[float]:
    if not birth_date_str:
        return None
    try:
        bd = dateparser.parse(str(birth_date_str)).date()
        return round((on_date - bd).days / 365.25, 2)
    except Exception:
        return None

def _regular_season_week_cap(season: int) -> int:
    # NFL week 18 begins in 2021. Exclude it entirely from all data/calcs.
    return 17 if season >= 2021 else 16

def _safe_bool_series(s: pd.Series) -> pd.Series:
    """
    Convert a column with True/False/None/NaN/"TRUE"/"FALSE" into strict boolean,
    avoiding pandas' downcasting warnings.
    """
    if s is None:
        return pd.Series([], dtype=bool)
    try:
        out = s.copy()
        # Normalize common string cases
        out = out.replace({"TRUE": True, "True": True, "true": True, "FALSE": False, "False": False, "false": False})
        out = out.fillna(False)
        return out.astype(bool)
    except Exception:
        try:
            return pd.Series([bool(x) for x in s.fillna(False).tolist()], index=s.index, dtype=bool)
        except Exception:
            return pd.Series([False] * len(s), index=getattr(s, "index", None), dtype=bool)


# --------------------------
# Team name mapping (HANDLE, not franchise name)
# --------------------------

def _team_handle_map(users: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Sleeper 'display_name' is the handle. Use that as Team everywhere.
    """
    out: Dict[str, str] = {}
    for u in users or []:
        uid = str(u.get("user_id"))
        handle = u.get("display_name")
        if not handle:
            # fallback only if missing
            meta = u.get("metadata") or {}
            handle = meta.get("team_name") or uid
        out[uid] = str(handle)
    return out


# --------------------------
# NFL team normalization + bye schedule
# --------------------------

_TEAM_NORMALIZE = {
    "LA": "LAR",
    "STL": "LAR",
    "SD": "LAC",
    "WSH": "WAS",
    "JAX": "JAX",
    "ARZ": "ARI",
    "AZ": "ARI",
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

def _download_csv_best_effort(urls: List[str], path: Path, timeout: int = 120) -> pd.DataFrame:
    """
    Best-effort cached CSV download. Never raises; returns empty DF on failure.
    """
    import requests

    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.stat().st_size > 0:
        try:
            return pd.read_csv(path)
        except Exception:
            pass

    last_err = None
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200 and r.content:
                path.write_bytes(r.content)
                try:
                    return pd.read_csv(path)
                except Exception:
                    return pd.DataFrame()
            last_err = f"{r.status_code} {url}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e} {url}"

    try:
        (path.parent / (path.name + ".error.txt")).write_text(str(last_err))
    except Exception:
        pass

    return pd.DataFrame()

def _played_teams_by_week(games: pd.DataFrame, season: int) -> Dict[int, set]:
    """
    Returns {week: set(teams_that_played)} for the given season.
    If games schema missing, returns {}.
    """
    games = _safe_df(games)
    out: Dict[int, set] = {}
    if games.empty:
        return out
    if "season" not in games.columns or "week" not in games.columns:
        return out
    if "home_team" not in games.columns or "away_team" not in games.columns:
        return out

    try:
        sub = games[games["season"] == season].copy()
    except Exception:
        return out
    if sub.empty:
        return out

    sub["week"] = pd.to_numeric(sub["week"], errors="coerce").astype("Int64")
    for wk, g in sub.groupby("week"):
        if pd.isna(wk):
            continue
        home = g["home_team"].dropna().astype(str).map(_norm_team).tolist()
        away = g["away_team"].dropna().astype(str).map(_norm_team).tolist()
        out[int(wk)] = set([t for t in (home + away) if t])
    return out


# --------------------------
# Brackets / playoff labeling
# --------------------------

def _get_json_best_effort(url: str, timeout: int = 30) -> Any:
    import requests
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def _load_brackets(league_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    base = "https://api.sleeper.app/v1"
    w = _get_json_best_effort(f"{base}/league/{league_id}/winners_bracket") or []
    l = _get_json_best_effort(f"{base}/league/{league_id}/losers_bracket") or []
    w = w if isinstance(w, list) else []
    l = l if isinstance(l, list) else []
    return w, l

def _build_playoff_week_labels(league_id: str, lg: Dict[str, Any], roster_to_team: Dict[int, str]) -> Dict[Tuple[int, int], str]:
    """
    Returns map: (week, roster_id) -> label
    Labels supported:
      - Semifinal
      - Final
      - Toilet Semis
      - Toilet Final
      - 3rd Place
      - 5th Place
    """
    labels: Dict[Tuple[int, int], str] = {}
    settings = lg.get("settings") or {}
    playoff_start = _to_int(settings.get("playoff_week_start"), None)

    if not playoff_start:
        return labels

    winners, losers = _load_brackets(league_id)

    # Max rounds (for stage inference) — robust to missing/odd entries
    def _max_round(entries: List[Dict[str, Any]]) -> int:
        mx = 0
        for e in entries:
            try:
                r = int(e.get("r") or 0)
                mx = max(mx, r)
            except Exception:
                pass
        return mx

    max_r_w = _max_round(winners)
    max_r_l = _max_round(losers)

    def _week_for_round(rnd: int) -> int:
        return playoff_start + (rnd - 1)

    # Helper: assign for both teams in a matchup entry
    def _assign(entry: Dict[str, Any], label: str):
        try:
            rnd = int(entry.get("r") or 0)
        except Exception:
            return
        if rnd <= 0:
            return
        wk = _week_for_round(rnd)
        for k in ("t1", "t2"):
            try:
                rid = entry.get(k)
                if rid is None:
                    continue
                rid_i = int(rid)
                labels[(wk, rid_i)] = label
            except Exception:
                continue

    # Winners bracket:
    # - If entry has p==3 => 3rd Place (many leagues represent it here)
    # - Else last round => Final
    # - Else round immediately before last => Semifinal
    for e in winners:
        p = e.get("p")
        if str(p) == "3":
            _assign(e, "3rd Place")
            continue
        try:
            rnd = int(e.get("r") or 0)
        except Exception:
            continue
        if rnd <= 0:
            continue
        if max_r_w <= 1:
            # Edge case small/odd: treat as Final
            _assign(e, "Final")
        elif rnd == max_r_w:
            _assign(e, "Final")
        elif rnd == max_r_w - 1:
            _assign(e, "Semifinal")

    # Losers bracket:
    # - If entry has p==5 => 5th Place
    # - Else last round => Toilet Final
    # - Else round immediately before last => Toilet Semis
    for e in losers:
        p = e.get("p")
        if str(p) == "5":
            _assign(e, "5th Place")
            continue
        try:
            rnd = int(e.get("r") or 0)
        except Exception:
            continue
        if rnd <= 0:
            continue
        if max_r_l <= 1:
            _assign(e, "Toilet Final")
        elif rnd == max_r_l:
            _assign(e, "Toilet Final")
        elif rnd == max_r_l - 1:
            _assign(e, "Toilet Semis")

    return labels


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

def _league_roster_positions(lg: Dict[str, Any]) -> List[str]:
    settings = lg.get("settings") or {}
    rp = settings.get("roster_positions") or []
    return list(rp) if isinstance(rp, list) else []


# --------------------------
# Injury/Suspension detection (defensive + consistent)
# --------------------------

def _infer_flags_from_sleeper_player_meta(meta: Dict[str, Any]) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Returns (injury, suspension) from Sleeper player fields when present.
    Conservative: only flags True when clearly not healthy / suspended.
    """
    if not isinstance(meta, dict):
        return (None, None)

    status = str(meta.get("status") or "").lower()
    injury_status = str(meta.get("injury_status") or "").lower()
    practice = str(meta.get("practice_participation") or "").lower()

    # suspension
    if "susp" in status or "susp" in injury_status:
        return (False, True)

    # clear healthy indicators
    if status in ("active", "") and injury_status in ("", "healthy", "null", "none"):
        return (False, False)

    # injury-ish statuses. NOTE: questionable/doubtful can still play; we do not auto-count as "out".
    injury_markers = ["ir", "out", "inactive", "pup", "nfi", "injured", "dnp", "covid"]
    if any(k in status for k in injury_markers) or any(k in injury_status for k in injury_markers):
        return (True, False)

    if practice in ("dnp", "did not practice"):
        return (True, False)

    return (None, None)

def _infer_flags_from_nflverse(injuries: pd.DataFrame, gsis_id: Optional[str], season: int, week: int) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Best-effort from nflverse injuries.
    """
    injuries = _safe_df(injuries)
    if injuries.empty or not gsis_id:
        return (None, None)
    if "gsis_id" not in injuries.columns:
        return (None, None)

    try:
        if "season" in injuries.columns:
            injuries["season"] = pd.to_numeric(injuries["season"], errors="coerce").astype("Int64")
        if "week" in injuries.columns:
            injuries["week"] = pd.to_numeric(injuries["week"], errors="coerce").astype("Int64")
    except Exception:
        pass

    try:
        sub = injuries[
            (injuries.get("season", season) == season) &
            (injuries.get("week", week) == week) &
            (injuries["gsis_id"].astype(str) == str(gsis_id))
        ]
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
    injury = (("out" in s) or ("ir" in s) or ("doubt" in s) or ("inactive" in s) or ("pup" in s)) and not suspension
    return (injury, suspension)

def _merge_flags(primary: Tuple[Optional[bool], Optional[bool]], secondary: Tuple[Optional[bool], Optional[bool]]) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Merge two (inj, susp) pairs:
    - If either says suspension True -> suspension True
    - Else if either says injury True -> injury True
    - Else if both False -> False
    - Else None if unknown
    """
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
# Column enforcement
# --------------------------

def _ensure_plan_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    df = _safe_df(df).copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


# --------------------------
# Main entry
# --------------------------

def build_all(repo_root: Path) -> None:
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
    sc = SleeperClient(http)

    cache_dir = repo_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    ext = ExternalConfig(cache_dir=cache_dir, timeout_seconds=120)

    # --------------------------
    # External datasets (NEVER crash build)
    # --------------------------

    # DynastyProcess ids
    try:
        dp_ids = _safe_df(load_dynastyprocess_playerids(ext))
    except Exception:
        dp_ids = pd.DataFrame()

    for c in ["sleeper_id", "gsis_id", "name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    # DynastyProcess player values (robust)
    dp_val_map: Dict[str, float] = {}
    try:
        dp_vals_players = load_dynastyprocess_values_players(ext)
    except Exception:
        dp_vals_players = pd.DataFrame()
    dp_vals_players = _safe_df(dp_vals_players)

    if not dp_vals_players.empty:
        name_col = _first_col(dp_vals_players, ["player", "name", "Player", "Name"])
        val_col = _first_col(dp_vals_players, ["value", "Value", "dp_value", "DP Value", "trade_value", "Trade Value"])
        if name_col and val_col:
            try:
                dp_vals_players["player_key"] = dp_vals_players[name_col].astype(str).map(clean_name)
                dp_vals_players["dp_value"] = pd.to_numeric(dp_vals_players[val_col], errors="coerce")
                dp_val_map = dp_vals_players.groupby("player_key")["dp_value"].max().to_dict()
            except Exception:
                dp_val_map = {}

    # DynastyProcess pick values (robust)
    dp_pick_val: Dict[str, float] = {}
    try:
        dp_vals_picks = load_dynastyprocess_values_picks(ext)
    except Exception:
        dp_vals_picks = pd.DataFrame()
    dp_vals_picks = _safe_df(dp_vals_picks)

    if not dp_vals_picks.empty:
        pick_col = _first_col(dp_vals_picks, ["pick", "Pick"])
        val_col = _first_col(dp_vals_picks, ["value", "Value", "pick_value", "Pick Value", "trade_value", "Trade Value"])
        if pick_col and val_col:
            try:
                dp_vals_picks["pick_key"] = dp_vals_picks[pick_col].astype(str).str.lower()
                dp_vals_picks["pick_value"] = pd.to_numeric(dp_vals_picks[val_col], errors="coerce")
                dp_pick_val = dp_vals_picks.groupby("pick_key")["pick_value"].max().to_dict()
            except Exception:
                dp_pick_val = {}

    # nfldata games (for byes)
    games = _download_csv_best_effort(
        urls=[
            "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
            "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
        ],
        path=cache_dir / "nfldata_games.csv",
        timeout=120,
    )
    if "season" in games.columns:
        games["season"] = pd.to_numeric(games["season"], errors="coerce").astype("Int64")

    # Sleeper NFL players
    try:
        players_nfl = sc.players_nfl()
    except Exception:
        players_nfl = {}

    pid_meta: Dict[str, Dict[str, Any]] = {}
    for pid, meta in (players_nfl or {}).items():
        if not isinstance(meta, dict):
            continue
        pid = str(pid)
        full = meta.get("full_name") or (str(meta.get("first_name", "")) + " " + str(meta.get("last_name", ""))).strip()
        pid_meta[pid] = {
            "full_name": full or pid,
            "pos": meta.get("position"),
            "team": _norm_team(meta.get("team")),
            "birth_date": meta.get("birth_date") or meta.get("birthdate"),
            "years_exp": meta.get("years_exp"),
            "status": meta.get("status"),
            "injury_status": meta.get("injury_status"),
            "practice_participation": meta.get("practice_participation"),
        }

    # --------------------------
    # League chain
    # --------------------------
    leagues = _walk_league_chain(sc, run_cfg.league_id, run_cfg.min_season, run_cfg.max_season)

    raw_dir = repo_root / "exports" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    player_week_rows: List[Dict[str, Any]] = []
    team_week_rows: List[Dict[str, Any]] = []
    transactions_rows: List[Dict[str, Any]] = []
    trades_rows: List[Dict[str, Any]] = []
    pick_rows: List[Dict[str, Any]] = []

    # --------------------------
    # Build seasons
    # --------------------------
    for lg in leagues:
        league_id = str(lg.get("league_id"))
        season = _to_int(lg.get("season"), 0) or 0
        cap = _regular_season_week_cap(season)
        roster_positions = _league_roster_positions(lg)

        # users/rosters
        try:
            users = sc.users(league_id)
        except Exception:
            users = []
        try:
            rosters = sc.rosters(league_id)
        except Exception:
            rosters = []

        user_handle = _team_handle_map(users)

        roster_owner: Dict[int, str] = {}
        for r in rosters or []:
            rid = _to_int(r.get("roster_id"), None)
            if rid is None:
                continue
            roster_owner[rid] = str(r.get("owner_id") or "")

        roster_to_team: Dict[int, str] = {}
        for rid, owner in roster_owner.items():
            roster_to_team[rid] = user_handle.get(owner, f"Roster {rid}")

        # playoff/toilet labels by (week, roster_id)
        playoff_labels = _build_playoff_week_labels(league_id, lg, roster_to_team)

        # raw snapshots
        try:
            (raw_dir / f"league_{season}.json").write_text(json.dumps(lg, indent=2))
            (raw_dir / f"users_{season}.json").write_text(json.dumps(users, indent=2))
            (raw_dir / f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))
        except Exception:
            pass

        # nflverse injuries for the season (best-effort)
        try:
            injuries = _safe_df(load_nflverse_injuries(ext, season))
        except Exception:
            injuries = pd.DataFrame()

        played_by_week = _played_teams_by_week(games, season)

        # draft picks history (best-effort)
        try:
            drafts = sc.drafts(league_id)
        except Exception:
            drafts = []
        draft_picks_all: List[Dict[str, Any]] = []
        for d in drafts or []:
            did = str(d.get("draft_id") or "")
            if not did:
                continue
            try:
                picks = sc.draft_picks(did)
            except Exception:
                picks = []
            for p in picks or []:
                p["draft_id"] = did
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

        # weekly loop (EXCLUDES week 18 / week 17 pre-2021 entirely)
        week = 1
        prev_starters_by_team: Dict[str, set] = {}

        while True:
            if week > cap:
                break

            try:
                matchups = sc.matchups(league_id, week)
            except Exception:
                matchups = None

            if not matchups:
                break

            try:
                txs = sc.transactions(league_id, week)
            except Exception:
                txs = []

            mdf = _safe_df(pd.DataFrame(matchups))
            if mdf.empty:
                break

            if "points" in mdf.columns:
                mdf["points"] = pd.to_numeric(mdf["points"], errors="coerce").fillna(0.0)
            else:
                mdf["points"] = 0.0

            if "roster_id" in mdf.columns:
                mdf["roster_id"] = pd.to_numeric(mdf["roster_id"], errors="coerce").fillna(-1).astype(int)
            else:
                mdf["roster_id"] = -1

            opp_map: Dict[int, int] = {}
            if "matchup_id" in mdf.columns:
                for _, g in mdf.groupby("matchup_id"):
                    rids = g["roster_id"].tolist()
                    if len(rids) == 2:
                        a, b = rids
                        opp_map[a] = b
                        opp_map[b] = a

            # team scoring list for "luck"/expected win
            week_team_pf: Dict[str, float] = {}
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue
                team = roster_to_team.get(rid, f"Roster {rid}")
                week_team_pf[team] = float(_to_float(m.get("points"), 0.0) or 0.0)

            # tx summaries (by creator handle)
            faab_spent: Dict[str, float] = {}
            trade_count: Dict[str, int] = {}
            tx_count: Dict[str, int] = {}

            for t in txs or []:
                creator = str(t.get("creator") or "")
                if not creator:
                    continue
                team = user_handle.get(creator)
                if not team:
                    continue

                tx_count[team] = tx_count.get(team, 0) + 1
                if t.get("type") == "trade":
                    trade_count[team] = trade_count.get(team, 0) + 1

                meta = t.get("metadata") or {}
                bid = 0.0
                if isinstance(meta, dict):
                    bid = _to_float(meta.get("waiver_bid") or meta.get("faab") or 0.0, 0.0) or 0.0
                faab_spent[team] = faab_spent.get(team, 0.0) + bid

            # Build team-week + player-week
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue

                team = roster_to_team.get(rid, f"Roster {rid}")
                pf = float(_to_float(m.get("points"), 0.0) or 0.0)

                opp_rid = opp_map.get(rid)
                opp_team = roster_to_team.get(opp_rid, f"Roster {opp_rid}") if opp_rid is not None else None
                opp_points = None
                if opp_rid is not None:
                    try:
                        opp_points = float(mdf.loc[mdf["roster_id"] == opp_rid, "points"].iloc[0])
                    except Exception:
                        opp_points = None

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

                pos_map = {pid: (pid_meta.get(pid, {}).get("pos") or "") for pid in players}

                # Max PF best-effort
                try:
                    max_pf, _ = max_points_lineup(roster_positions, players, ppts, pos_map)
                except Exception:
                    max_pf = None

                eff = safe_div(pf, max_pf) if max_pf else None

                # expected win percentile vs league that week
                scores = list(week_team_pf.values())
                expected = None
                luck = None
                if scores and len(scores) > 1:
                    expected = sum(1 for s in scores if pf > s) / max(1, (len(scores) - 1))
                    if win is not None:
                        luck = (win - expected)

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
                    return sum(1 for pid in pids if pid_meta.get(pid, {}).get("pos") == pos)

                qb_s, rb_s, wr_s, te_s = count_pos(starters, "QB"), count_pos(starters, "RB"), count_pos(starters, "WR"), count_pos(starters, "TE")
                qb_r, rb_r, wr_r, te_r = count_pos(players, "QB"), count_pos(players, "RB"), count_pos(players, "WR"), count_pos(players, "TE")

                rook_s = sum(1 for pid in starters if pid_meta.get(pid, {}).get("years_exp") in (0, "0", 0.0))
                rook_r = sum(1 for pid in players if pid_meta.get(pid, {}).get("years_exp") in (0, "0", 0.0))

                approx_date = date(season, 9, 1) + timedelta(days=7 * (week - 1))
                ages = [a for a in (_calc_age(pid_meta.get(pid, {}).get("birth_date"), approx_date) for pid in players) if a is not None]
                avg_age = round(sum(ages) / len(ages), 2) if ages else None

                roster_nfl_teams = [pid_meta.get(pid, {}).get("team") for pid in players if pid_meta.get(pid, {}).get("team")]
                start_nfl_teams = [pid_meta.get(pid, {}).get("team") for pid in starters if pid_meta.get(pid, {}).get("team")]
                most_start_same = max(Counter(start_nfl_teams).values()) if start_nfl_teams else None
                most_roster_same = max(Counter(roster_nfl_teams).values()) if roster_nfl_teams else None

                # Opponent MaxPF for UPST
                opp_maxpf = None
                if opp_rid is not None:
                    try:
                        opp_m = next((x for x in matchups if _to_int(x.get("roster_id"), -1) == int(opp_rid)), None)
                        if opp_m:
                            opp_players = [str(x) for x in (opp_m.get("players") or []) if x]
                            opp_ppts_raw = opp_m.get("players_points") or {}
                            opp_ppts = {}
                            if isinstance(opp_ppts_raw, dict):
                                for k, v in opp_ppts_raw.items():
                                    try:
                                        opp_ppts[str(k)] = float(v)
                                    except Exception:
                                        pass
                            opp_pos_map = {pid: (pid_meta.get(pid, {}).get("pos") or "") for pid in opp_players}
                            opp_maxpf, _ = max_points_lineup(roster_positions, opp_players, opp_ppts, opp_pos_map)
                    except Exception:
                        opp_maxpf = None

                upst = None
                if win is not None and max_pf is not None and opp_maxpf is not None:
                    upst = 1 if (max_pf < opp_maxpf and win == 1) else 0

                # Week label for last two weeks / placement games (NO opponent included)
                week_label: Any = week
                lbl = playoff_labels.get((week, rid))
                if lbl:
                    week_label = lbl

                team_week_rows.append({
                    "Team": team,
                    "Week": week_label,
                    "Year": season,
                    "PF": round(pf, 2),
                    "Win?": win,
                    "Opponent": opp_team,
                    "Points against": round(opp_points, 2) if opp_points is not None else None,
                    "Margin": round(margin, 2) if margin is not None else None,
                    "Max PF": max_pf,
                    "Efficiency": round(eff, 4) if eff is not None else None,
                    "Starter turnover from previous week": turnover,
                    "Difference between highest and lowest starters": round(diff_hi_lo, 2) if diff_hi_lo is not None else None,
                    "Combined matchup score": round(pf + (opp_points or 0.0), 2) if opp_points is not None else None,
                    "Number of donuts": donuts,
                    "Number of players under 10": under10,
                    "Number of players over 20": over20,
                    "Number of players over 30": over30,
                    "Number of players over 40": over40,
                    "Number of players over 50": over50,
                    "UPST": upst,
                    "Hardship": None,                   # recomputed later
                    "Tanking": (round((max_pf - pf) / max_pf, 4) if max_pf else None),
                    "Luck": round(luck, 4) if luck is not None else None,
                    "Brosenzweig": None,               # recomputed later
                    "Sisenzweig": None,                # recomputed later
                    "Number of Injuries": None,         # recomputed later
                    "Number of suspensions": None,      # recomputed later
                    "Number of players on bye": None,   # recomputed later
                    "Number of QB started": qb_s,
                    "Number of WR started": wr_s,
                    "Number of RB started": rb_s,
                    "Number of TE started": te_s,
                    "Number of QB rostered": qb_r,
                    "Number of WR rostered": wr_r,
                    "Number of RB rostered": rb_r,
                    "Number of TE rostered": te_r,
                    "Number of transactions": tx_count.get(team, 0),
                    "Number of trades": trade_count.get(team, 0),
                    "Amount of FAAB spent": round(faab_spent.get(team, 0.0), 2),
                    "Most number of players started from same NFL team": most_start_same,
                    "Most number of players rostered from same NFL team": most_roster_same,
                    "Number of NFL teams among starting players": len(set(start_nfl_teams)) if start_nfl_teams else None,
                    "Number of NFL teams amoung rostered players": len(set(roster_nfl_teams)) if roster_nfl_teams else None,
                    "Number of rookies started": rook_s,
                    "Number of rookies rostered": rook_r,
                    "Player average age": avg_age,
                })

                # Player-week
                starter_slot = {}
                for i, pid in enumerate(starters):
                    if i < len(roster_positions):
                        starter_slot[pid] = roster_positions[i]

                played_set = played_by_week.get(week, set())
                for pid in players:
                    meta = pid_meta.get(pid, {})
                    full_name = meta.get("full_name") or pid
                    nfl_team = meta.get("team")
                    pts = float(ppts.get(pid, 0.0))
                    started = pid in starters
                    slot = starter_slot.get(pid) if started else None

                    # gsis id lookup for nflverse
                    gsis = None
                    if not dp_ids.empty and "sleeper_id" in dp_ids.columns and "gsis_id" in dp_ids.columns:
                        try:
                            match = dp_ids.loc[dp_ids["sleeper_id"].astype(str) == pid]
                            if not match.empty:
                                gsis = str(match["gsis_id"].iloc[0])
                        except Exception:
                            gsis = None

                    # Flags
                    f1 = _infer_flags_from_sleeper_player_meta(meta)
                    f2 = _infer_flags_from_nflverse(injuries, gsis, season, week)
                    inj, susp = _merge_flags(f1, f2)

                    # Schedule-based BYE.
                    bye = None
                    if nfl_team and played_set:
                        bye = (_norm_team(nfl_team) not in played_set)

                    # If player scored > 0, bye is definitely False; also injury/susp shouldn't be treated as "missed"
                    if pts > 0:
                        bye = False
                        if inj is True:
                            inj = False
                        if susp is True:
                            susp = False

                    # Week label for player-week must match team-week
                    week_label_pw: Any = week
                    if playoff_labels.get((week, rid)):
                        week_label_pw = playoff_labels[(week, rid)]

                    player_week_rows.append({
                        "Player": full_name,
                        "Team": team,
                        "Week": week_label_pw,
                        "Year": season,
                        "Points": round(pts, 2),
                        "Injury?": bool(inj) if inj is not None else None,
                        "Suspension?": bool(susp) if susp is not None else None,
                        "Bye?": bool(bye) if bye is not None else None,
                        "Starter/Bench": "Starter" if started else "Bench",
                        "% of points (if starter)": round(pts / pf, 4) if started and pf else None,
                        "Position started in (if starter)": slot,
                        # advanced columns filled later
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
                    })

            # Transactions rows (non-trade)
            for t in txs or []:
                if t.get("type") == "trade":
                    continue

                ttype = t.get("type")
                created_date = _epoch_ms_to_date(t.get("created"))
                creator = str(t.get("creator") or "")
                team = user_handle.get(creator) if creator else None

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
                        "Date": str(created_date) if created_date else None,
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

            # Trades rows (best-effort, robust)
            def _player_value_dp(name: str) -> Optional[float]:
                key = clean_name(name)
                v = dp_val_map.get(key)
                return float(v) if v is not None else None

            for t in txs or []:
                if t.get("type") != "trade":
                    continue

                created_date = _epoch_ms_to_date(t.get("created"))
                adds = t.get("adds") or {}
                draft_picks = t.get("draft_picks") or []

                if not isinstance(adds, dict):
                    adds = {}
                if not isinstance(draft_picks, list):
                    draft_picks = []

                rids = set()
                for _, rrid in adds.items():
                    rr = _to_int(rrid, None)
                    if rr is not None:
                        rids.add(rr)
                for dp in draft_picks:
                    if not isinstance(dp, dict):
                        continue
                    rr = _to_int(dp.get("owner_id"), None)
                    if rr is not None:
                        rids.add(rr)

                teams = [roster_to_team.get(rid, f"Roster {rid}") for rid in sorted(rids)]
                if len(teams) < 2:
                    continue

                team_gets = {tm: {"players": [], "picks": []} for tm in teams}

                for pid, rrid in adds.items():
                    rr = _to_int(rrid, None)
                    if rr is None:
                        continue
                    tm = roster_to_team.get(rr, f"Roster {rrid}")
                    team_gets.setdefault(tm, {"players": [], "picks": []})
                    team_gets[tm]["players"].append(pid_meta.get(str(pid), {}).get("full_name") or str(pid))

                for dp in draft_picks:
                    if not isinstance(dp, dict):
                        continue
                    owner_id = _to_int(dp.get("owner_id"), None)
                    owner = roster_to_team.get(owner_id, f"Roster {dp.get('owner_id')}")
                    team_gets.setdefault(owner, {"players": [], "picks": []})
                    team_gets[owner]["picks"].append(f"{dp.get('season')} R{dp.get('round')}")

                side = []
                for tm in teams:
                    gets = team_gets.get(tm, {"players": [], "picks": []})
                    dp_sum = 0.0
                    any_dp = False
                    for nm in gets["players"]:
                        dv = _player_value_dp(nm)
                        if dv is not None:
                            dp_sum += dv
                            any_dp = True
                    side.append((tm, (dp_sum if any_dp else None), gets))

                dp_diff = None
                if len(side) == 2 and side[0][1] is not None and side[1][1] is not None:
                    dp_diff = side[0][1] - side[1][1]

                trades_rows.append({
                    "Team A": teams[0],
                    "Team B": teams[1],
                    "Team C": teams[2] if len(teams) > 2 else None,
                    "Week": week,
                    "Year": season,
                    "Date": str(created_date) if created_date else None,
                    "Assets received by Team A": json.dumps(side[0][2]),
                    "Assets received by Team B": json.dumps(side[1][2]),
                    "Assets received by Team C": json.dumps(side[2][2]) if len(side) > 2 else None,
                    "KTC Value Difference at deal time": None,
                    "Oliver value difference at deal time": dp_diff,
                    "Pick Value received by Team A": None,
                    "Pick Value received by Team B": None,
                    "Pick Value received by Team C": None,
                    "Value received by Team A": side[0][1],
                    "Value received by Team B": side[1][1],
                    "Value received by Team C": side[2][1] if len(side) > 2 else None,
                    "KTC Value Difference at end of season": None,
                    "KTC Value Difference 1 year later": None,
                    "KTC Value Difference 2 years later": None,
                    "Oliver Value Difference at end of season": None,
                    "Oliver Value Difference 1 year later": None,
                    "Oliver Value Difference 2 years later": None,
                    "Points accrued by Team A side before trade (if player)": None,
                    "Points accrued by Team B side before trade (if player)": None,
                    "Points accrued by Team C side before trade (if player)": None,
                    "Points accrued by Team A side after trade (if player)": None,
                    "Points accrued by Team B side after trade (if player)": None,
                    "Points accrued by Team C side after trade (if player)": None,
                    "Assets retained by Team A side now": None,
                    "Assets retained by Team B side now": None,
                    "Assets retained by Team C side now": None,
                    "Current KTC Value difference of assets retained by each side": None,
                    "Current Oliver Value difference of assets retained by each side": None,
                })

            week += 1

    # --------------------------
    # Convert to DataFrames
    # --------------------------
    pw = pd.DataFrame(player_week_rows)
    tw = pd.DataFrame(team_week_rows)
    tx = pd.DataFrame(transactions_rows)
    tr = pd.DataFrame(trades_rows)
    ph = pd.DataFrame(pick_rows)

    # --------------------------
    # Player-week derived columns + hardship engine
    # --------------------------
    # Hardship definition:
    # For each rostered player-week:
    # - If Injury? or Suspension? is True
    # - And Bye? is False (or None treated as False) AND Points == 0
    # => points lost = avg(last 5 HEALTHY games points),
    # where HEALTHY games are prior games with:
    # - Points > 0
    # - Injury? != True
    # - Suspension? != True
    # - Bye? != True
    #
    if not pw.empty:
        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)

        inj_col = _safe_bool_series(pw.get("Injury?", pd.Series([False] * len(pw))))
        susp_col = _safe_bool_series(pw.get("Suspension?", pd.Series([False] * len(pw))))
        bye_col = _safe_bool_series(pw.get("Bye?", pd.Series([False] * len(pw))))

        active = ~(inj_col | susp_col | bye_col)

        # Change from previous active week
        pw["Change from previous week"] = None
        last_active_pts: Dict[str, float] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            pts = float(row["Points"]) if row["Points"] is not None else 0.0
            if k in last_active_pts:
                pw.at[i, "Change from previous week"] = pts - last_active_pts[k]
            if bool(active.iloc[i]):
                last_active_pts[k] = pts

        # Previous 5 active weeks avg (spans seasons)
        pw["Change from previous 5 weeks avg"] = None
        windows: Dict[str, deque] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            pts = float(row["Points"]) if row["Points"] is not None else 0.0
            q = windows.get(k, deque(maxlen=5))
            if len(q) == 5:
                pw.at[i, "Change from previous 5 weeks avg"] = pts - (sum(q) / 5)
            if bool(active.iloc[i]):
                q.append(pts)
            windows[k] = q

        # Career avg to that point (active weeks only)
        pw["Change from career average to that point"] = None
        sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            pts = float(row["Points"]) if row["Points"] is not None else 0.0
            if counts.get(k, 0) > 0:
                pw.at[i, "Change from career average to that point"] = pts - (sums[k] / counts[k])
            if bool(active.iloc[i]):
                sums[k] = sums.get(k, 0.0) + pts
                counts[k] = counts.get(k, 0) + 1

        # Overall career avg (active weeks only)
        try:
            full_avg = pw.loc[active].groupby("Player")["Points"].mean()
            pw["Change from overall career average"] = pw["Points"] - pw["Player"].map(full_avg)
        except Exception:
            pw["Change from overall career average"] = None

        # Team tenure + bench streaks (bench streak spans seasons)
        pw = pw.sort_values(["Team", "Player", "Year", "Week"]).reset_index(drop=True)
        stats: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for i, row in pw.iterrows():
            key = (row["Team"], row["Player"])
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

        # Hardship engine (player-level expected points)
        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)

        def is_true(v) -> bool:
            return bool(v) is True

        last5: Dict[str, deque] = {}
        exp_points: List[Optional[float]] = [None] * len(pw)
        points_lost: List[float] = [0.0] * len(pw)

        for i, row in pw.iterrows():
            player = row["Player"]
            pts = float(row["Points"]) if row["Points"] is not None else 0.0

            inj = is_true(row.get("Injury?"))
            susp = is_true(row.get("Suspension?"))
            bye = is_true(row.get("Bye?"))

            hist = last5.get(player, deque(maxlen=5))

            expected = (sum(hist) / len(hist)) if len(hist) > 0 else None
            exp_points[i] = expected

            missed_due_to_inj_or_susp = (pts == 0.0) and (inj or susp) and (not bye)
            if missed_due_to_inj_or_susp and expected is not None:
                points_lost[i] = float(expected)
            else:
                points_lost[i] = 0.0

            # Update history ONLY with "healthy" games:
            if (pts > 0.0) and (not inj) and (not susp) and (not bye):
                hist.append(pts)

            last5[player] = hist

        pw["_expected_points_if_healthy"] = exp_points
        pw["_points_lost_inj_susp"] = points_lost

    # --------------------------
    # Recompute team-week injury/susp/bye counts and hardship from player-week
    # --------------------------
    if not tw.empty and not pw.empty:
        tw = tw.copy()

        pw2 = pw.copy()
        pw2["Injury?"] = _safe_bool_series(pw2.get("Injury?", pd.Series([False] * len(pw2))))
        pw2["Suspension?"] = _safe_bool_series(pw2.get("Suspension?", pd.Series([False] * len(pw2))))
        pw2["Bye?"] = _safe_bool_series(pw2.get("Bye?", pd.Series([False] * len(pw2))))

        # missed counts (exclude bye)
        pw2["_missed_injury"] = (pw2["Injury?"] & (~pw2["Bye?"]) & (pw2["Points"] == 0)).astype(int)
        pw2["_missed_susp"] = (pw2["Suspension?"] & (~pw2["Bye?"]) & (pw2["Points"] == 0)).astype(int)
        pw2["_on_bye"] = (pw2["Bye?"] & (pw2["Points"] == 0)).astype(int)

        agg = pw2.groupby(["Team", "Year", "Week"], as_index=False).agg(
            Hardship=("_points_lost_inj_susp", "sum"),
            Number_of_Injuries=("_missed_injury", "sum"),
            Number_of_suspensions=("_missed_susp", "sum"),
            Number_of_players_on_bye=("_on_bye", "sum"),
        )

        tw = tw.merge(agg, how="left", on=["Team", "Year", "Week"], suffixes=("", "_agg"))

        # overwrite placeholders safely (NO scalar fillna)
        hardship_series = pd.Series([None] * len(tw), index=tw.index)
        if "Hardship" in tw.columns:
            hardship_series = pd.to_numeric(tw["Hardship"], errors="coerce")
        if "Hardship_agg" in tw.columns:
            hy = pd.to_numeric(tw["Hardship_agg"], errors="coerce")
            hardship_series = hardship_series.fillna(hy)
        tw["Hardship"] = hardship_series.fillna(0.0)

        # Minimum hardship rule (if hardship > 0, enforce at least 1.0)
        tw.loc[tw["Hardship"] > 0, "Hardship"] = tw.loc[tw["Hardship"] > 0, "Hardship"].clip(lower=1.0)

        for c_in, c_out in [
            ("Number_of_Injuries", "Number of Injuries"),
            ("Number_of_suspensions", "Number of suspensions"),
            ("Number_of_players_on_bye", "Number of players on bye"),
        ]:
            if c_in in tw.columns:
                tw[c_out] = pd.to_numeric(tw[c_in], errors="coerce").fillna(0).astype(int)

        tw.drop(columns=[c for c in ["Hardship_agg", "Number_of_Injuries", "Number_of_suspensions", "Number_of_players_on_bye"] if c in tw.columns],
                inplace=True, errors="ignore")

        # Brosenzweig / Sisenzweig definitions tied to hardship>0
        try:
            tw["Brosenzweig"] = ((tw["UPST"] == 1) & (tw["Hardship"] > 0)).astype(int)
            tw["Sisenzweig"] = ((tw["UPST"] == 0) & (tw["Hardship"] > 0) & (tw["Win?"] == 1)).astype(int)
        except Exception:
            tw["Brosenzweig"] = None
            tw["Sisenzweig"] = None

    # --------------------------
    # Team-week derived columns (robust)
    # --------------------------
    if not tw.empty:
        tw = tw.sort_values(["Year", "Week", "PF"], ascending=[True, True, False]).reset_index(drop=True)

        try:
            tw["Highest score?"] = tw.groupby(["Year", "Week"])["PF"].transform(lambda s: (s == s.max()).astype(int))
            tw["Lowest score?"] = tw.groupby(["Year", "Week"])["PF"].transform(lambda s: (s == s.min()).astype(int))
        except Exception:
            tw["Highest score?"] = None
            tw["Lowest score?"] = None

        try:
            tw["Most efficient?"] = tw.groupby(["Year", "Week"])["Efficiency"].transform(lambda s: (s == s.max()).astype(int))
            tw["Least efficient?"] = tw.groupby(["Year", "Week"])["Efficiency"].transform(lambda s: (s == s.min()).astype(int))
        except Exception:
            tw["Most efficient?"] = None
            tw["Least efficient?"] = None

        try:
            tw["Top half of league?"] = tw.groupby(["Year", "Week"])["PF"].transform(
                lambda s: (s.rank(ascending=False, method="min") <= (len(s) / 2)).astype(int)
            )
        except Exception:
            tw["Top half of league?"] = None

        tw = tw.sort_values(["Team", "Year", "Week"]).reset_index(drop=True)
        try:
            tw["Increase in points from previous week"] = tw.groupby(["Team"])["PF"].diff()
        except Exception:
            tw["Increase in points from previous week"] = None

        # win/loss streaks
        tw["Win streak"] = None
        tw["Loss streak"] = None
        try:
            for team, g in tw.groupby("Team"):
                wst = lst = 0
                for idx, row in g.sort_values(["Year", "Week"]).iterrows():
                    if row.get("Win?") == 1:
                        wst += 1
                        lst = 0
                    elif row.get("Win?") == 0:
                        lst += 1
                        wst = 0
                    else:
                        wst = lst = 0
                    tw.at[idx, "Win streak"] = wst
                    tw.at[idx, "Loss streak"] = lst
        except Exception:
            pass

    # --------------------------
    # Aggregates (simple, robust)
    # --------------------------
    player_year = pd.DataFrame()
    player_all = pd.DataFrame()
    if not pw.empty:
        rows = []
        for (player, year), g in pw.groupby(["Player", "Year"]):
            pts = pd.to_numeric(g["Points"], errors="coerce").fillna(0)
            rows.append({
                "Player": player,
                "Year": _to_int(year, year),
                "Points": round(float(pts.sum()), 2),
                "Best week": round(float(pts.max()), 2),
                "Worst week": round(float(pts.min()), 2),
            })
        player_year = pd.DataFrame(rows)

        rows = []
        for player, g in pw.groupby(["Player"]):
            pts = pd.to_numeric(g["Points"], errors="coerce").fillna(0)
            rows.append({
                "Player": player,
                "Points": round(float(pts.sum()), 2),
                "Best week": round(float(pts.max()), 2),
                "Worst week": round(float(pts.min()), 2),
            })
        player_all = pd.DataFrame(rows)

    # --- Record vs each team (encoded as 16 key/value pairs where possible) ---
    def _record_vs_each_team_blob(tw_df: pd.DataFrame, team: str, year: Optional[int] = None) -> Optional[str]:
        """
        Produces JSON string with keys like:
          "<OPP> Record": "W-L-T"
          "<OPP> Win%": 0.625
        If the league has 8 opponents, that yields 16 entries (record+win% per opponent).
        """
        if tw_df.empty:
            return None
        sub = tw_df.copy()
        if year is not None:
            sub = sub[sub["Year"] == year]
        sub = sub[sub["Team"] == team]
        if sub.empty:
            return None

        # Keep only numeric weeks (regular matchups). Labeled playoff rows still have Opponent set; keep them too.
        opps = sorted([o for o in sub["Opponent"].dropna().astype(str).unique().tolist() if o and o != team])
        out: Dict[str, Any] = {}

        for opp in opps:
            g = sub[sub["Opponent"].astype(str) == str(opp)]
            if g.empty:
                continue
            w = int((g["Win?"] == 1).sum()) if "Win?" in g.columns else 0
            l = int((g["Win?"] == 0).sum()) if "Win?" in g.columns else 0
            t = int((g["Win?"] == 0.5).sum()) if "Win?" in g.columns else 0
            games = max(1, w + l + t)
            winp = round((w + 0.5 * t) / games, 4)
            out[f"{opp} Record"] = f"{w}-{l}" + (f"-{t}" if t else "")
            out[f"{opp} Win%"] = winp

        try:
            return json.dumps(out, ensure_ascii=False)
        except Exception:
            return str(out)

    team_year = pd.DataFrame()
    team_all = pd.DataFrame()
    if not tw.empty:
        rows = []
        for (team, year), g in tw.groupby(["Team", "Year"]):
            wins = int((g["Win?"] == 1).sum()) if "Win?" in g.columns else 0
            losses = int((g["Win?"] == 0).sum()) if "Win?" in g.columns else 0
            ties = int((g["Win?"] == 0.5).sum()) if "Win?" in g.columns else 0
            games_ct = max(1, wins + losses + ties)

            points = float(pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0).sum())
            maxpf = float(pd.to_numeric(g.get("Max PF", 0), errors="coerce").fillna(0).sum())

            rows.append({
                "Team": team,
                "Year": _to_int(year, year),
                "Win %": round((wins + 0.5 * ties) / games_ct, 4),
                "Record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
                "Record & win % vs each team": _record_vs_each_team_blob(tw, team, _to_int(year, year)),
                "Points": round(points, 2),
                "Avg points": round(points / games_ct, 2),
                "Max PF": round(maxpf, 2),
                "Avg max PF": round(maxpf / games_ct, 2),
                "Efficiency": round(points / maxpf, 4) if maxpf else None,
                "Number of transactions": int(pd.to_numeric(g.get("Number of transactions", 0), errors="coerce").fillna(0).sum()),
                "Number of trades": int(pd.to_numeric(g.get("Number of trades", 0), errors="coerce").fillna(0).sum()),
                "Amount of FAAB spent": round(float(pd.to_numeric(g.get("Amount of FAAB spent", 0), errors="coerce").fillna(0).sum()), 2),
            })
        team_year = pd.DataFrame(rows)

        rows = []
        for team, g in tw.groupby(["Team"]):
            wins = int((g["Win?"] == 1).sum()) if "Win?" in g.columns else 0
            losses = int((g["Win?"] == 0).sum()) if "Win?" in g.columns else 0
            ties = int((g["Win?"] == 0.5).sum()) if "Win?" in g.columns else 0
            games_ct = max(1, wins + losses + ties)

            points = float(pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0).sum())
            maxpf = float(pd.to_numeric(g.get("Max PF", 0), errors="coerce").fillna(0).sum())

            rows.append({
                "Team": team,
                "Seasons": int(g["Year"].nunique()) if "Year" in g.columns else None,
                "Win %": round((wins + 0.5 * ties) / games_ct, 4),
                "Record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
                "Record & win % vs each team": _record_vs_each_team_blob(tw, team, None),
                "Points": round(points, 2),
                "Max PF": round(maxpf, 2),
                "Efficiency": round(points / maxpf, 4) if maxpf else None,
            })
        team_all = pd.DataFrame(rows)

    league_week = pd.DataFrame()
    league_year = pd.DataFrame()
    league_all = pd.DataFrame()
    if not tw.empty:
        rows = []
        for (year, week), g in tw.groupby(["Year", "Week"]):
            pf = pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0)
            rows.append({
                "Year": _to_int(year, year),
                "Week": week,
                "PF": round(float(pf.sum()), 2),
                "PF Range": round(float(pf.max() - pf.min()), 2),
                "Number of Injuries": int(pd.to_numeric(g.get("Number of Injuries", 0), errors="coerce").fillna(0).sum()),
                "Number of suspensions": int(pd.to_numeric(g.get("Number of suspensions", 0), errors="coerce").fillna(0).sum()),
                "Number of players on bye": int(pd.to_numeric(g.get("Number of players on bye", 0), errors="coerce").fillna(0).sum()),
            })
        league_week = pd.DataFrame(rows)

        rows = []
        for year, g in tw.groupby(["Year"]):
            rows.append({
                "Year": _to_int(year, year),
                "PF": round(float(pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0).sum()), 2),
                "Max PF": round(float(pd.to_numeric(g.get("Max PF", 0), errors="coerce").fillna(0).sum()), 2),
            })
        league_year = pd.DataFrame(rows)

        league_all = pd.DataFrame([{
            "PF": round(float(pd.to_numeric(tw.get("PF", 0), errors="coerce").fillna(0).sum()), 2),
            "Years": int(tw["Year"].nunique()) if "Year" in tw.columns else None,
        }])

    # --------------------------
    # Write outputs (schema contract)
    # --------------------------
    out_dir = repo_root / "exports"
    out_dir.mkdir(exist_ok=True)

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

    for fname, frame, plan_key in tables:
        cols = catalog.get(plan_key, [])
        frame = _safe_df(frame)
        out = _ensure_plan_columns(frame, cols)
        require_columns(out, cols, fname.replace(".csv", ""))
        out.to_csv(out_dir / fname, index=False)

    # --------------------------
    # Excel workbook with filterable Tables (one table per sheet)
    # --------------------------
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    wb.remove(wb.active)

    def _safe_table_name(s: str) -> str:
        s = "".join(ch if ch.isalnum() else "_" for ch in s)
        if not s:
            s = "Table"
        if s[0].isdigit():
            s = "T_" + s
        return s[:31]

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

        nrows = max(1, ws.max_row)
        ncols = max(1, ws.max_column)
        ref = f"A1:{get_column_letter(ncols)}{nrows}"

        tname = _safe_table_name(f"{sheet_name}_tbl")
        table = Table(displayName=tname, ref=ref)
        style = TableStyleInfo(
            name="TableStyleMedium9",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        table.tableStyleInfo = style
        ws.add_table(table)

        try:
            for j, col in enumerate(d.columns, 1):
                max_len = max([len(str(col))] + [len(str(x)) for x in d[col].head(200).fillna("").astype(str).tolist()])
                ws.column_dimensions[get_column_letter(j)].width = min(60, max(10, max_len + 2))
        except Exception:
            pass

    wb.save(out_dir / "LOTG_Stats.xlsx")

    # Zip exports
    import zipfile
    with zipfile.ZipFile(out_dir / "LOTG_Exports.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in out_dir.glob("*.csv"):
            z.write(f, arcname=f.name)
        z.write(out_dir / "LOTG_Stats.xlsx", arcname="LOTG_Stats.xlsx")
        for f in (out_dir / "raw").glob("*"):
            if f.is_file():
                z.write(f, arcname=f"raw/{f.name}")
