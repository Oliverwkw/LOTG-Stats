
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta, date
from collections import Counter, deque, defaultdict
import json
import math

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
    season_type: str = "regular"  # sleeper stats season type


# --------------------------
# Small helpers
# --------------------------

def _to_int(x: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return default

def _to_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(x)
        if not math.isfinite(v):
            return default
        return v
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

def _scoring_settings_from_league(lg: Dict[str, Any]) -> Dict[str, float]:
    ss = lg.get("scoring_settings") or (lg.get("settings") or {}).get("scoring_settings") or {}
    out: Dict[str, float] = {}
    if isinstance(ss, dict):
        for k, v in ss.items():
            try:
                out[str(k)] = float(v)
            except Exception:
                continue
    return out

def _calc_fantasy_points_from_stats(stats: Dict[str, Any], scoring: Dict[str, float]) -> float:
    if not isinstance(stats, dict) or not scoring:
        return 0.0
    total = 0.0
    for stat_key, mult in scoring.items():
        if stat_key not in stats:
            continue
        try:
            val = stats.get(stat_key)
            if val is None:
                continue
            total += float(val) * float(mult)
        except Exception:
            continue
    return float(total)

def _load_week_points_cached(sc: SleeperClient, cache_dir: Path, season: int, week: int, scoring: Dict[str, float], season_type: str="regular") -> Dict[str, float]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    fp = cache_dir / f"sleeper_week_points_{season}_{week}.json"
    if fp.exists() and fp.stat().st_size > 0:
        try:
            raw = json.loads(fp.read_text())
            if isinstance(raw, dict):
                return {str(k): float(v) for k, v in raw.items()}
        except Exception:
            pass
    pts: Dict[str, float] = {}
    try:
        raw_stats = sc.nfl_stats_week(season, week, season_type=season_type)
    except Exception:
        raw_stats = {}
    if isinstance(raw_stats, dict):
        for pid, st in raw_stats.items():
            try:
                pts[str(pid)] = round(_calc_fantasy_points_from_stats(st, scoring), 4)
            except Exception:
                continue
    try:
        fp.write_text(json.dumps(pts))
    except Exception:
        pass
    return pts

# --------------------------
# Team handle mapping (display_name)
# --------------------------

def _team_handle_map(users: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for u in users or []:
        uid = str(u.get("user_id"))
        handle = u.get("display_name")
        if not handle:
            meta = u.get("metadata") or {}
            handle = meta.get("team_name") or uid
        out[uid] = str(handle)
    return out

# --------------------------
# NFL team normalization + bye schedule
# --------------------------
_TEAM_NORMALIZE = {
    "LA": "LAR","STL": "LAR","SD": "LAC","WSH": "WAS","ARZ": "ARI","AZ": "ARI",
    "NWE": "NE","KCC": "KC","NOR": "NO","SFO": "SF","TAM": "TB","GNB": "GB","LVR": "LV",
    "ARI": "ARI","ATL": "ATL","BAL": "BAL","BUF": "BUF","CAR": "CAR","CHI": "CHI","CIN": "CIN","CLE": "CLE",
    "DAL": "DAL","DEN": "DEN","DET": "DET","GB": "GB","HOU": "HOU","IND": "IND","JAX": "JAX","KC": "KC",
    "LAC": "LAC","LAR": "LAR","LV": "LV","MIA": "MIA","MIN": "MIN","NE": "NE","NO": "NO","NYG": "NYG","NYJ": "NYJ",
    "PHI": "PHI","PIT": "PIT","SEA": "SEA","SF": "SF","TB": "TB","TEN": "TEN","WAS": "WAS",
}
def _norm_team(t: Any) -> Optional[str]:
    if not t:
        return None
    s = str(t).strip().upper()
    return _TEAM_NORMALIZE.get(s, s)

def _download_csv_best_effort(urls: List[str], path: Path, timeout: int = 120) -> pd.DataFrame:
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
    games = _safe_df(games)
    out: Dict[int, set] = {}
    if games.empty:
        return out
    if not {"season","week","home_team","away_team"}.issubset(set(games.columns)):
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
# Injury/Suspension (nflverse + sanity)
# --------------------------
def _infer_flags_from_nflverse(injuries: pd.DataFrame, gsis_id: Optional[str], season: int, week: int) -> Tuple[Optional[bool], Optional[bool]]:
    injuries = _safe_df(injuries)
    if injuries.empty or not gsis_id or "gsis_id" not in injuries.columns:
        return (None, None)
    try:
        if "season" in injuries.columns:
            injuries["season"] = pd.to_numeric(injuries["season"], errors="coerce").astype("Int64")
        if "week" in injuries.columns:
            injuries["week"] = pd.to_numeric(injuries["week"], errors="coerce").astype("Int64")
    except Exception:
        pass
    try:
        sub = injuries[(injuries.get("season", season) == season) & (injuries.get("week", week) == week) & (injuries["gsis_id"].astype(str) == str(gsis_id))]
    except Exception:
        return (None, None)
    if sub.empty:
        return (None, None)
    status_col = _first_col(sub, ["report_status","status","game_status","injury_status","practice_status","designation"])
    if not status_col:
        return (None, None)
    s = str(sub.iloc[0].get(status_col) or "").lower()
    if not s:
        return (None, None)
    suspension = ("susp" in s) or ("sspd" in s)
    injury = (("out" in s) or ("ir" in s) or ("inactive" in s) or ("pup" in s) or ("nfi" in s) or ("doubt" in s)) and not suspension
    return (injury, suspension)

# --------------------------
# Plan columns
# --------------------------
def _ensure_plan_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    df = _safe_df(df).copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]

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
    """
    Sleeper's `settings.roster_positions` is intended to describe starter slots, but leagues
    sometimes include non-starter slots (BN/IR/TAXI/RES). Those break MaxPF/lineup logic.
    We defensively filter them out and keep only true starter-eligible slots.
    """
    settings = lg.get("settings") or {}
    rp = settings.get("roster_positions") or []
    if not isinstance(rp, list):
        return []
    drop = {"BN", "IR", "TAXI", "RES", "PUP"}
    out = [str(x) for x in rp if x and str(x).upper() not in drop]
    return out


# Sleeper's `roster_positions` includes bench/IR/taxi entries (e.g., "BN").
# These must be excluded from optimal lineup (Max PF) calculations.
_NON_START_SLOTS = {
    "BN", "BENCH",
    "IR", "RES", "RESERVE",
    "TAXI", "TAXI_R", "TAXI_W",
}


def _starting_positions(roster_positions: List[str]) -> List[str]:
    out: List[str] = []
    for p in roster_positions or []:
        if not p:
            continue
        ps = str(p).strip().upper()
        if ps in _NON_START_SLOTS:
            continue
        out.append(str(p))
    return out

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

    http = HttpConfig(timeout_seconds=40, max_retries=12, backoff_base_seconds=0.8)
    sc = SleeperClient(http)

    cache_dir = repo_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    ext = ExternalConfig(cache_dir=cache_dir, timeout_seconds=180)

    # External datasets (best-effort)
    try:
        dp_ids = _safe_df(load_dynastyprocess_playerids(ext))
    except Exception:
        dp_ids = pd.DataFrame()

    for c in ["sleeper_id","gsis_id","name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    # games schedule for byes
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

    # Sleeper NFL players (current)
    try:
        players_nfl = sc.players_nfl()
    except Exception:
        players_nfl = {}
    pid_meta: Dict[str, Dict[str, Any]] = {}
    for pid, meta in (players_nfl or {}).items():
        if not isinstance(meta, dict):
            continue
        pid = str(pid)
        full = meta.get("full_name") or (str(meta.get("first_name","")) + " " + str(meta.get("last_name",""))).strip()
        pid_meta[pid] = {
            "full_name": full or pid,
            "pos": meta.get("position"),
            "team": _norm_team(meta.get("team")),
            "birth_date": meta.get("birth_date") or meta.get("birthdate"),
            "years_exp": meta.get("years_exp"),
        }

    # League chain
    leagues = _walk_league_chain(sc, run_cfg.league_id, run_cfg.min_season, run_cfg.max_season)

    raw_dir = repo_root / "exports" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    roster_week_rows: List[Dict[str, Any]] = []
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
        roster_positions = _league_roster_positions(lg)
        start_positions = _starting_positions(roster_positions)
        scoring_settings = _scoring_settings_from_league(lg)

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

        # raw snapshots
        try:
            (raw_dir / f"league_{season}.json").write_text(json.dumps(lg, indent=2))
            (raw_dir / f"users_{season}.json").write_text(json.dumps(users, indent=2))
            (raw_dir / f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))
        except Exception:
            pass

        # nflverse injuries for season
        try:
            injuries = _safe_df(load_nflverse_injuries(ext, season))
        except Exception:
            injuries = pd.DataFrame()

        played_by_week = _played_teams_by_week(games, season)

        # traded picks (used for draft-capital inventory)
        try:
            traded_picks = sc.traded_picks(league_id)
        except Exception:
            traded_picks = []

        # draft picks (rookie drafts)
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

        # weekly loop
        week = 1
        prev_starters_by_team: Dict[str, set] = {}

        max_week = 17 if season >= 2021 else 16

        while True:
            if week > max_week:
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

            # weekly fantasy points for all NFL players
            week_points = _load_week_points_cached(sc, cache_dir, season, week, scoring_settings, season_type=run_cfg.season_type)

            # matchup df for opponent mapping
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

            week_team_pf: Dict[str, float] = {}
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue
                team = roster_to_team.get(rid, f"Roster {rid}")
                week_team_pf[team] = float(_to_float(m.get("points"), 0.0) or 0.0)

            # transaction summaries
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

            played_set = played_by_week.get(week, set())

            # Build roster-week and team-week
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue
                team = roster_to_team.get(rid, f"Roster {rid}")
                pf = float(_to_float(m.get("points"), 0.0) or 0.0)

                opp_rid = opp_map.get(rid)
                opp_team_actual = roster_to_team.get(opp_rid, f"Roster {opp_rid}") if opp_rid is not None else None
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

                # points map for roster players (prefer Sleeper computed points, fallback to scored stats)
                ppts_raw = m.get("players_points") or {}
                ppts: Dict[str, float] = {}
                if isinstance(ppts_raw, dict):
                    for k, v in ppts_raw.items():
                        vv = _to_float(v, 0.0) or 0.0
                        ppts[str(k)] = float(vv)

                # fill for all roster players using week_points (bench included)
                for pid in players:
                    if pid not in ppts:
                        ppts[pid] = float(week_points.get(pid, 0.0))

                pos_map = {pid: (pid_meta.get(pid, {}).get("pos") or "") for pid in players}

                # Max PF + efficiency
                try:
                    max_pf, _ = max_points_lineup(start_positions, players, ppts, pos_map)
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

                rook_s = sum(1 for pid in starters if str(pid_meta.get(pid, {}).get("years_exp")).strip() in ("0","0.0"))
                rook_r = sum(1 for pid in players if str(pid_meta.get(pid, {}).get("years_exp")).strip() in ("0","0.0"))

                approx_date = date(season, 9, 1) + timedelta(days=7 * (week - 1))
                ages = [a for a in (_calc_age(pid_meta.get(pid, {}).get("birth_date"), approx_date) for pid in players) if a is not None]
                avg_age = round(sum(ages) / len(ages), 2) if ages else None

                roster_nfl_teams = [pid_meta.get(pid, {}).get("team") for pid in players if pid_meta.get(pid, {}).get("team")]
                start_nfl_teams = [pid_meta.get(pid, {}).get("team") for pid in starters if pid_meta.get(pid, {}).get("team")]
                most_start_same = max(Counter(start_nfl_teams).values()) if start_nfl_teams else None
                most_roster_same = max(Counter(roster_nfl_teams).values()) if roster_nfl_teams else None

                # UPST placeholder (compute later with rollup once team avgs known)
                upst = None

                team_week_rows.append({
                    "Team": team,
                    "Week": week,
                    "Year": season,
                    "PF": round(pf, 2),
                    "Win?": win,
                    "Opponent": opp_team_actual,
                    "Points against": round(opp_points, 2) if opp_points is not None else None,
                    "Margin": round(margin, 2) if margin is not None else None,
                    "Max PF": round(float(max_pf), 2) if max_pf is not None else None,
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
                    "Hardship": None,
                    "Tanking": None,
                    "Luck": round(luck, 4) if luck is not None else None,
                    "Brosenzweig": None,
                    "Sisenzweig": None,
                    "Number of Injuries": None,
                    "Number of suspensions": None,
                    "Number of players on bye": None,
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

                # roster-week rows (core structure)
                starter_slot = {}
                for i, pid in enumerate(starters):
                    if i < len(roster_positions):
                        starter_slot[pid] = roster_positions[i]

                for pid in players:
                    meta = pid_meta.get(pid, {})
                    full_name = meta.get("full_name") or pid
                    nfl_team = meta.get("team")
                    pts = float(ppts.get(pid, 0.0))
                    started = pid in starters
                    slot = starter_slot.get(pid) if started else None

                    # gsis id lookup for nflverse injuries
                    gsis = None
                    if not dp_ids.empty and "sleeper_id" in dp_ids.columns and "gsis_id" in dp_ids.columns:
                        try:
                            match = dp_ids.loc[dp_ids["sleeper_id"].astype(str) == pid]
                            if not match.empty:
                                gsis = str(match["gsis_id"].iloc[0])
                        except Exception:
                            gsis = None

                    inj, susp = _infer_flags_from_nflverse(injuries, gsis, season, week)

                    bye = None
                    if nfl_team and played_set:
                        bye = (_norm_team(nfl_team) not in played_set)
                    if pts > 0:
                        bye = False

                    # sanity: if played (pts>0), cannot be "out"
                    if pts > 0:
                        inj = False
                        susp = False

                    roster_week_rows.append({
                        "Player": full_name,
                        "PlayerID": pid,
                        "Team": team,
                        "RosterID": rid,
                        "Week": week,
                        "Year": season,
                        "Points": round(pts, 2),
                        "Started": bool(started),
                        "Slot": slot,
                        "Pos": meta.get("pos"),
                        "NFL Team": nfl_team,
                        "Injury?": bool(inj) if inj is not None else None,
                        "Suspension?": bool(susp) if susp is not None else None,
                        "Bye?": bool(bye) if bye is not None else None,
                    })

            # Transactions rows (non-trade) - keep base only (advanced computed later from roster ledger)
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
                if not isinstance(adds, dict): adds = {}
                if not isinstance(drops, dict): drops = {}
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

            # TODO: trades_rows kept minimal (KTC/Oliver etc blank)
            week += 1

    # --------------------------
    # Build DataFrames from core roster-week
    # --------------------------
    rw = pd.DataFrame(roster_week_rows)
    tw = pd.DataFrame(team_week_rows)
    tx = pd.DataFrame(transactions_rows)
    tr = pd.DataFrame(trades_rows)
    ph = pd.DataFrame(pick_rows)

    # Player-Week (derived from roster-week)
    pw = pd.DataFrame()
    if not rw.empty:
        pw = rw.copy()
        pw["Starter/Bench"] = pw["Started"].map(lambda x: "Starter" if bool(x) else "Bench")
        pw["Position started in (if starter)"] = pw["Slot"]
        # % of points if starter
        team_pf_map = {(r["Team"], r["Year"], r["Week"]): r["PF"] for r in team_week_rows}
        pw["% of points (if starter)"] = pw.apply(lambda r: (r["Points"]/team_pf_map.get((r["Team"], r["Year"], r["Week"]), 0)) if r["Starter/Bench"]=="Starter" and team_pf_map.get((r["Team"], r["Year"], r["Week"]), 0) else None, axis=1)

        # remove internal cols not in plan
        pw.rename(columns={"NFL Team":"NFL team"}, inplace=True)

        # change metrics over ACTIVE games (exclude bye/inj/susp), bench still counts
        pw = pw.sort_values(["Player","Year","Week"]).reset_index(drop=True)
        active = ~pw[["Injury?","Suspension?","Bye?"]].fillna(False).any(axis=1)

        # change from previous active week
        pw["Change from previous week"] = None
        last_active_pts: Dict[str, float] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            if k in last_active_pts:
                pw.at[i, "Change from previous week"] = float(row["Points"]) - last_active_pts[k]
            if bool(active.iloc[i]):
                last_active_pts[k] = float(row["Points"])

        # prev 5 active avg (spans seasons)
        pw["Change from previous 5 weeks avg"] = None
        windows: Dict[str, deque] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            q = windows.get(k, deque(maxlen=5))
            if len(q) == 5:
                pw.at[i, "Change from previous 5 weeks avg"] = float(row["Points"]) - (sum(q) / 5)
            if bool(active.iloc[i]):
                q.append(float(row["Points"]))
            windows[k] = q

        # career avg to that point (active)
        pw["Change from career average to that point"] = None
        sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            if counts.get(k, 0) > 0:
                pw.at[i, "Change from career average to that point"] = float(row["Points"]) - (sums[k] / counts[k])
            if bool(active.iloc[i]):
                sums[k] = sums.get(k, 0.0) + float(row["Points"])
                counts[k] = counts.get(k, 0) + 1

        # overall career avg (active)
        try:
            full_avg = pw.loc[active].groupby("Player")["Points"].mean()
            pw["Change from overall career average"] = pw["Points"] - pw["Player"].map(full_avg)
        except Exception:
            pw["Change from overall career average"] = None

        # team tenure + bench streaks
        pw = pw.sort_values(["Team","Player","Year","Week"]).reset_index(drop=True)
        stats: Dict[Tuple[str,str], Dict[str, Any]] = {}
        pw["Number of weeks on team"] = None
        pw["Number of consecutive weeks on bench before start (if starter)"] = None
        pw["Number of consecutive weeks on bench before start excluding injury/bye (if starter)"] = None
        pw["Total weeks as team starter to that point"] = None
        pw["Total weeks on bench to that point"] = None
        pw["Total weeks as team starter on that team this season"] = None
        pw["Total weeks on bench on that team this season"] = None

        for i, row in pw.iterrows():
            key = (row["Team"], row["Player"])
            st = stats.get(key, {"weeks":0,"start_all":0,"bench_all":0,"season":None,"start_season":0,"bench_season":0,"bench_streak":0,"bench_streak_ex":0})
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

        # Awards (league + team)
        # league player of week among starters
        pw["Player of week? (league)"] = 0
        pw["QB of week? (league)"] = 0
        pw["RB of week? (league)"] = 0
        pw["WR of week? (league)"] = 0
        pw["TE of week? (league)"] = 0
        pw["Bench QB of week? (league)"] = 0
        pw["Bench RB of week? (league)"] = 0
        pw["Bench WR of week? (league)"] = 0
        pw["Bench TE of week? (league)"] = 0
        pw["Player of week? (team)"] = 0
        pw["QB of week? (team)"] = 0
        pw["RB of week? (team)"] = 0
        pw["WR of week? (team)"] = 0
        pw["TE of week? (team)"] = 0

        for (yr,wk), g in pw.groupby(["Year","Week"]):
            starters = g[g["Starter/Bench"]=="Starter"]
            if not starters.empty:
                mx = starters["Points"].max()
                pw.loc[starters.index[starters["Points"]==mx], "Player of week? (league)"] = 1
                for pos,col in [("QB","QB of week? (league)"),("RB","RB of week? (league)"),("WR","WR of week? (league)"),("TE","TE of week? (league)")]:
                    gp = starters[starters["Pos"]==pos]
                    if not gp.empty:
                        m2 = gp["Points"].max()
                        pw.loc[gp.index[gp["Points"]==m2], col] = 1
            bench = g[g["Starter/Bench"]=="Bench"]
            for pos,col in [("QB","Bench QB of week? (league)"),("RB","Bench RB of week? (league)"),("WR","Bench WR of week? (league)"),("TE","Bench TE of week? (league)")]:
                gp = bench[bench["Pos"]==pos]
                if not gp.empty:
                    m2 = gp["Points"].max()
                    pw.loc[gp.index[gp["Points"]==m2], col] = 1

            # team awards
            for team, gt in g.groupby("Team"):
                st = gt[gt["Starter/Bench"]=="Starter"]
                if not st.empty:
                    mx = st["Points"].max()
                    pw.loc[st.index[st["Points"]==mx], "Player of week? (team)"] = 1
                    for pos,col in [("QB","QB of week? (team)"),("RB","RB of week? (team)"),("WR","WR of week? (team)"),("TE","TE of week? (team)")]:
                        gp = st[st["Pos"]==pos]
                        if not gp.empty:
                            m2 = gp["Points"].max()
                            pw.loc[gp.index[gp["Points"]==m2], col] = 1

        # Hardship: expected points from last 5 healthy games, missed due to inj/susp with 0 pts and not bye
        pw = pw.sort_values(["Player","Year","Week"]).reset_index(drop=True)
        last5: Dict[str, deque] = {}
        pw["_expected_points_if_healthy"] = None
        pw["_points_lost_inj_susp"] = 0.0
        for i,row in pw.iterrows():
            player=row["Player"]
            pts=float(row["Points"] or 0.0)
            inj=bool(row.get("Injury?") or False)
            susp=bool(row.get("Suspension?") or False)
            bye=bool(row.get("Bye?") or False)
            hist=last5.get(player, deque(maxlen=5))
            expected=(sum(hist)/len(hist)) if len(hist)>0 else None
            pw.at[i,"_expected_points_if_healthy"]=expected
            if pts==0.0 and (inj or susp) and (not bye) and expected is not None:
                pw.at[i,"_points_lost_inj_susp"]=float(expected)
            if pts>0.0 and (not inj) and (not susp) and (not bye):
                hist.append(pts)
            last5[player]=hist

    # Recompute team-week injury/susp/bye/hardship from player-week
    if not tw.empty and not pw.empty:
        pw2=pw.copy()
        pw2["Injury?"]=pw2["Injury?"].fillna(False).astype(bool)
        pw2["Suspension?"]=pw2["Suspension?"].fillna(False).astype(bool)
        pw2["Bye?"]=pw2["Bye?"].fillna(False).astype(bool)
        pw2["_missed_injury"]=(pw2["Injury?"] & (~pw2["Bye?"]) & (pw2["Points"]==0)).astype(int)
        pw2["_missed_susp"]=(pw2["Suspension?"] & (~pw2["Bye?"]) & (pw2["Points"]==0)).astype(int)
        pw2["_on_bye"]=(pw2["Bye?"] & (pw2["Points"]==0)).astype(int)
        agg=pw2.groupby(["Team","Year","Week"],as_index=False).agg(
            Hardship=("_points_lost_inj_susp","sum"),
            Injuries=("_missed_injury","sum"),
            Suspensions=("_missed_susp","sum"),
            Byes=("_on_bye","sum"),
        )
        tw=tw.merge(agg,how="left",on=["Team","Year","Week"],suffixes=("_x","_y"))

        # Robustly select the post-merge hardship column.
        # If TW already had a placeholder 'Hardship', pandas will create Hardship_x/Hardship_y.
        # Prefer the computed value from player-week aggregation when present.
        if "Hardship" in tw.columns:
            hardship_series = tw["Hardship"]
        elif "Hardship_y" in tw.columns:
            hardship_series = tw["Hardship_y"].combine_first(tw.get("Hardship_x"))
        elif "Hardship_x" in tw.columns:
            hardship_series = tw["Hardship_x"]
        else:
            hardship_series = pd.Series([0.0] * len(tw), index=tw.index)

        tw["Hardship"] = pd.to_numeric(hardship_series, errors="coerce").fillna(0.0)

        # cleanup merge artifacts
        tw.drop(columns=[
            "Hardship_x", "Hardship_y",
            "Number_of_Injuries", "Number_of_suspensions", "Number_of_players_on_bye",
        ], inplace=True, errors="ignore")
        if "Hardship" in tw.columns:
            hardship_series = tw["Hardship"]
        elif "Hardship_y" in tw.columns:
            hardship_series = tw["Hardship_y"].combine_first(tw.get("Hardship_x"))
        elif "Hardship_x" in tw.columns:
            hardship_series = tw["Hardship_x"]
        else:
            hardship_series = 0.0

        tw["Hardship"] = pd.to_numeric(hardship_series, errors="coerce").fillna(0.0)

        # cleanup any merge suffix columns
        tw.drop(columns=[c for c in ["Hardship_x", "Hardship_y"] if c in tw.columns], inplace=True, errors="ignore")
        tw["Number of Injuries"]=pd.to_numeric(tw["Injuries"],errors="coerce").fillna(0).astype(int)
        tw["Number of suspensions"]=pd.to_numeric(tw["Suspensions"],errors="coerce").fillna(0).astype(int)
        tw["Number of players on bye"]=pd.to_numeric(tw["Byes"],errors="coerce").fillna(0).astype(int)
        tw.drop(columns=["Injuries","Suspensions","Byes"],inplace=True,errors="ignore")
        # Brosenzweig / Sisenzweig (2nd highest lose; 2nd lowest win) across all matchups that week
        tw["Brosenzweig"]=0
        tw["Sisenzweig"]=0
        for (yr,wk), g in tw.groupby(["Year","Week"]):
            g2=g.sort_values("PF",ascending=False)
            if len(g2)>=2:
                second_hi=g2.iloc[1]["PF"]
                second_lo=g2.sort_values("PF",ascending=True).iloc[1]["PF"] if len(g2)>=2 else None
                idx_hi=g2.index[g2["PF"]==second_hi]
                tw.loc[idx_hi, "Brosenzweig"] = ((tw.loc[idx_hi,"Win?"]==0).astype(int))
                idx_lo=g2.index[g2["PF"]==second_lo] if second_lo is not None else []
                tw.loc[idx_lo, "Sisenzweig"] = ((tw.loc[idx_lo,"Win?"]==1).astype(int))

    # Increase in points from previous week (spans playoff weeks too; week1 N/A)
    if not tw.empty:
        tw=tw.sort_values(["Team","Year","Week"]).reset_index(drop=True)
        tw["Increase in points from previous week"]=None
        for team,g in tw.groupby("Team"):
            g=g.sort_values(["Year","Week"])
            prev=None
            for idx,row in g.iterrows():
                if prev is None:
                    tw.at[idx,"Increase in points from previous week"]=None
                else:
                    tw.at[idx,"Increase in points from previous week"]=float(row["PF"])-float(prev)
                prev=float(row["PF"])
        # weekly flags
        try:
            tw["Highest score?"]=tw.groupby(["Year","Week"])["PF"].transform(lambda s:(s==s.max()).astype(int))
            tw["Lowest score?"]=tw.groupby(["Year","Week"])["PF"].transform(lambda s:(s==s.min()).astype(int))
        except Exception:
            pass

    # Rollups (best-effort)
    player_year=pd.DataFrame()
    player_all=pd.DataFrame()
    if not pw.empty:
        player_year=pw.groupby(["Player","Year"],as_index=False).agg(Points=("Points","sum"),Best_week=("Points","max"),Worst_week=("Points","min"))
        player_year.rename(columns={"Best_week":"Best week","Worst_week":"Worst week"},inplace=True)
        player_all=pw.groupby(["Player"],as_index=False).agg(Points=("Points","sum"),Best_week=("Points","max"),Worst_week=("Points","min"))
        player_all.rename(columns={"Best_week":"Best week","Worst_week":"Worst week"},inplace=True)

    team_year=pd.DataFrame()
    team_all=pd.DataFrame()
    if not tw.empty:
        def rec(g):
            wins=int((g["Win?"]==1).sum()); losses=int((g["Win?"]==0).sum()); ties=int((g["Win?"]==0.5).sum())
            games=max(1,wins+losses+ties)
            return wins,losses,ties,games
        rows=[]
        for (team,yr),g in tw.groupby(["Team","Year"]):
            wins,losses,ties,games=rec(g)
            points=float(pd.to_numeric(g["PF"],errors="coerce").fillna(0).sum())
            maxpf=float(pd.to_numeric(g["Max PF"],errors="coerce").fillna(0).sum())
            rows.append({"Team":team,"Year":int(yr),"Win %":round((wins+0.5*ties)/games,4),"Record":f"{wins}-{losses}"+(f"-{ties}" if ties else ""),"Points":round(points,2),"Avg points":round(points/games,2),"Max PF":round(maxpf,2),"Avg max PF":round(maxpf/games,2),"Efficiency":round(points/maxpf,4) if maxpf else None})
        team_year=pd.DataFrame(rows)
        rows=[]
        for team,g in tw.groupby(["Team"]):
            wins,losses,ties,games=rec(g)
            points=float(pd.to_numeric(g["PF"],errors="coerce").fillna(0).sum())
            maxpf=float(pd.to_numeric(g["Max PF"],errors="coerce").fillna(0).sum())
            rows.append({"Team":team,"Seasons":int(g["Year"].nunique()),"Win %":round((wins+0.5*ties)/games,4),"Record":f"{wins}-{losses}"+(f"-{ties}" if ties else ""),"Points":round(points,2),"Max PF":round(maxpf,2),"Efficiency":round(points/maxpf,4) if maxpf else None})
        team_all=pd.DataFrame(rows)

        # Head-to-head all-time records (includes playoffs)
        try:
            teams_sorted = sorted([str(t) for t in team_all["Team"].dropna().unique().tolist()])
            # Aggregate W/L/T from team-week rows (each team has one row per game).
            h2h = tw[["Team", "Opponent", "Win?"]].dropna(subset=["Team", "Opponent"]).copy()
            h2h["Win?"] = pd.to_numeric(h2h["Win?"], errors="coerce")
            h2h["w"] = (h2h["Win?"] == 1).astype(int)
            h2h["l"] = (h2h["Win?"] == 0).astype(int)
            h2h["t"] = (h2h["Win?"] == 0.5).astype(int)
            h2h_agg = h2h.groupby(["Team", "Opponent"], as_index=False).agg(w=("w", "sum"), l=("l", "sum"), t=("t", "sum"))
            h2h_map = {(r["Team"], r["Opponent"]): (int(r["w"]), int(r["l"]), int(r["t"])) for _, r in h2h_agg.iterrows()}

            for opp in teams_sorted:
                rec_col = f"record vs {opp}"
                pct_col = f"win % vs {opp}"
                team_all[rec_col] = None
                team_all[pct_col] = None
                for i, tm in team_all["Team"].items():
                    if pd.isna(tm) or str(tm) == "":
                        continue
                    tm = str(tm)
                    if tm == opp:
                        team_all.at[i, rec_col] = "0-0"
                        team_all.at[i, pct_col] = None
                        continue
                    w, l, t = h2h_map.get((tm, opp), (0, 0, 0))
                    if t:
                        team_all.at[i, rec_col] = f"{w}-{l}-{t}"
                    else:
                        team_all.at[i, rec_col] = f"{w}-{l}"
                    games = w + l + t
                    team_all.at[i, pct_col] = round((w + 0.5 * t) / games, 4) if games > 0 else None
        except Exception:
            pass

    league_week=pd.DataFrame()
    league_year=pd.DataFrame()
    league_all=pd.DataFrame()
    if not tw.empty:
        league_week=tw.groupby(["Year","Week"],as_index=False).agg(PF=("PF","sum"),PF_Range=("PF",lambda s: float(s.max()-s.min())))
        league_week.rename(columns={"PF_Range":"PF Range"},inplace=True)
        league_year=tw.groupby(["Year"],as_index=False).agg(PF=("PF","sum"),MaxPF=("Max PF","sum"))
        league_year.rename(columns={"MaxPF":"Max PF"},inplace=True)
        league_all=pd.DataFrame([{"PF":float(pd.to_numeric(tw["PF"],errors="coerce").fillna(0).sum()),"Years":int(tw["Year"].nunique())}])

    # --------------------------
    # Write outputs per plan
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

    # Excel workbook with filters (avoid Excel Table objects; they have caused workbook
    # corruption/repair prompts in some environments).
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
        # Apply an AutoFilter across the full used range.
        nrows = max(1, ws.max_row)
        ncols = max(1, ws.max_column)
        ref = f"A1:{get_column_letter(ncols)}{nrows}"
        ws.auto_filter.ref = ref
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
