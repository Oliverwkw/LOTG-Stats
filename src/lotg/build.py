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


# --------------------------
# Team name mapping (HANDLE, not franchise name)
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
# NFL team normalization
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
    if not {"season", "week", "home_team", "away_team"}.issubset(set(games.columns)):
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
# Injury/Suspension detection (platform-ish, best effort)
# --------------------------

def _infer_flags_from_sleeper_player_meta(meta: Dict[str, Any]) -> Tuple[Optional[bool], Optional[bool]]:
    if not isinstance(meta, dict):
        return (None, None)
    status = str(meta.get("status") or "").lower()
    injury_status = str(meta.get("injury_status") or "").lower()

    if "susp" in status or "susp" in injury_status:
        return (False, True)

    # Treat only "out/ir/pup/nfi/inactive" as injury.
    injury_markers = ["ir", "out", "inactive", "pup", "nfi", "covid"]
    if any(k in status for k in injury_markers) or any(k in injury_status for k in injury_markers):
        return (True, False)

    if status in ("active", "") and injury_status in ("", "healthy", "none", "null"):
        return (False, False)

    return (None, None)

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

def _ensure_plan_columns(df: pd.DataFrame, cols: List[str], keep_extras: bool = True) -> pd.DataFrame:
    df = _safe_df(df).copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    if not keep_extras:
        return df[cols]
    extras = [c for c in df.columns if c not in cols]
    return df[cols + extras]


# --------------------------
# Playoff labeling
# --------------------------

def _parse_bracket_entries(entries: Any, bracket_type: str) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    out = []
    for it in entries:
        if not isinstance(it, dict):
            continue
        out.append({
            "matchup_id": it.get("matchup_id", it.get("m")),
            "round": it.get("round", it.get("r")),
            "placement": it.get("placement", it.get("p")),
            "t1": it.get("t1"),
            "t2": it.get("t2"),
            "bracket": bracket_type,
        })
    return out

def _playoff_label_for(entry: Dict[str, Any]) -> Optional[str]:
    b = entry.get("bracket")
    r = _to_int(entry.get("round"), None)
    p = _to_int(entry.get("placement"), None)

    if b == "winners":
        if p == 3:
            return "3rd Place"
        if r == 1:
            return "Semifinal"
        if r == 2:
            return "Final"
    if b == "losers":
        if p == 5:
            return "5th Place"
        if r == 1:
            return "Toilet Semis"
        if r == 2:
            return "Toilet Final"
    return None


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

    try:
        dp_ids = _safe_df(load_dynastyprocess_playerids(ext))
    except Exception:
        dp_ids = pd.DataFrame()

    for c in ["sleeper_id", "gsis_id", "name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    dp_val_map: Dict[str, float] = {}
    try:
        dp_vals_players = _safe_df(load_dynastyprocess_values_players(ext))
    except Exception:
        dp_vals_players = pd.DataFrame()

    if not dp_vals_players.empty:
        name_col = _first_col(dp_vals_players, ["player", "name", "Player", "Name"])
        val_col = _first_col(dp_vals_players, ["value", "Value", "dp_value", "DP Value", "trade_value", "Trade Value"])
        if name_col and val_col:
            try:
                tmp = dp_vals_players[[name_col, val_col]].copy()
                tmp["player_key"] = tmp[name_col].astype(str).map(clean_name)
                tmp["dp_value"] = pd.to_numeric(tmp[val_col], errors="coerce")
                dp_val_map = tmp.groupby("player_key")["dp_value"].max().to_dict()
            except Exception:
                dp_val_map = {}

    dp_pick_val: Dict[str, float] = {}
    try:
        dp_vals_picks = _safe_df(load_dynastyprocess_values_picks(ext))
    except Exception:
        dp_vals_picks = pd.DataFrame()

    if not dp_vals_picks.empty:
        pick_col = _first_col(dp_vals_picks, ["pick", "Pick"])
        val_col = _first_col(dp_vals_picks, ["value", "Value", "pick_value", "Pick Value", "trade_value", "Trade Value"])
        if pick_col and val_col:
            try:
                tmp = dp_vals_picks[[pick_col, val_col]].copy()
                tmp["pick_key"] = tmp[pick_col].astype(str).str.lower()
                tmp["pick_value"] = pd.to_numeric(tmp[val_col], errors="coerce")
                dp_pick_val = tmp.groupby("pick_key")["pick_value"].max().to_dict()
            except Exception:
                dp_pick_val = {}

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
        }

    leagues = _walk_league_chain(sc, run_cfg.league_id, run_cfg.min_season, run_cfg.max_season)

    raw_dir = repo_root / "exports" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    player_week_rows: List[Dict[str, Any]] = []
    team_week_rows: List[Dict[str, Any]] = []
    transactions_rows: List[Dict[str, Any]] = []
    trades_rows: List[Dict[str, Any]] = []
    pick_rows: List[Dict[str, Any]] = []

    all_teams_seen: set[str] = set()

    for lg in leagues:
        league_id = str(lg.get("league_id"))
        season = _to_int(lg.get("season"), 0) or 0
        roster_positions = _league_roster_positions(lg)

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
            all_teams_seen.add(roster_to_team[rid])

        try:
            (raw_dir / f"league_{season}.json").write_text(json.dumps(lg, indent=2))
            (raw_dir / f"users_{season}.json").write_text(json.dumps(users, indent=2))
            (raw_dir / f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))
        except Exception:
            pass

        try:
            injuries = _safe_df(load_nflverse_injuries(ext, season))
        except Exception:
            injuries = pd.DataFrame()

        played_by_week = _played_teams_by_week(games, season)

        # playoff labels (Opponent column becomes label in playoff/toilet weeks)
        playoff_week_start = _to_int((lg.get("settings") or {}).get("playoff_week_start"), 15) or 15
        playoff_labels: Dict[Tuple[int, int], str] = {}  # (week, matchup_id) -> label
        try:
            wb = _parse_bracket_entries(sc.winners_bracket(league_id), "winners")
        except Exception:
            wb = []
        try:
            lb = _parse_bracket_entries(sc.losers_bracket(league_id), "losers")
        except Exception:
            lb = []
        for e in wb + lb:
            mid = _to_int(e.get("matchup_id"), None)
            label = _playoff_label_for(e)
            if mid is None or not label:
                continue
            r = _to_int(e.get("round"), None)
            if r == 1:
                wk = playoff_week_start
            elif r == 2:
                wk = playoff_week_start + 1
            else:
                wk = playoff_week_start + (r - 1 if r else 0)
            playoff_labels[(wk, mid)] = label

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

        # week exclusion rule:
        excluded_week = 18 if season >= 2021 else 17

        week = 1
        prev_starters_by_team: Dict[str, set] = {}

        while True:
            if week == excluded_week:
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

            week_team_pf: Dict[str, float] = {}
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue
                team = roster_to_team.get(rid, f"Roster {rid}")
                week_team_pf[team] = float(_to_float(m.get("points"), 0.0) or 0.0)

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

                ppts_raw = m.get("players_points") or {}
                ppts: Dict[str, float] = {}
                if isinstance(ppts_raw, dict):
                    for k, v in ppts_raw.items():
                        try:
                            ppts[str(k)] = float(v)
                        except Exception:
                            pass

                pos_map = {pid: (pid_meta.get(pid, {}).get("pos") or "") for pid in players}

                try:
                    max_pf, _ = max_points_lineup(roster_positions, players, ppts, pos_map)
                except Exception:
                    max_pf = None

                eff = safe_div(pf, max_pf) if max_pf else None

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

                matchup_id = _to_int(m.get("matchup_id"), None)
                opp_label = playoff_labels.get((week, matchup_id)) if matchup_id is not None else None
                opp_display = opp_label or opp_team_actual

                team_week_rows.append({
                    "Team": team,
                    "Week": week,
                    "Year": season,
                    "PF": round(pf, 2),
                    "Win?": win,
                    "Opponent": opp_display,
                    "_OpponentTeamActual": opp_team_actual,
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
                    "Hardship": None,
                    "Tanking": (round((max_pf - pf) / max_pf, 4) if max_pf else None),
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

                    gsis = None
                    if not dp_ids.empty and "sleeper_id" in dp_ids.columns and "gsis_id" in dp_ids.columns:
                        try:
                            match = dp_ids.loc[dp_ids["sleeper_id"].astype(str) == pid]
                            if not match.empty:
                                gsis = str(match["gsis_id"].iloc[0])
                        except Exception:
                            gsis = None

                    f1 = _infer_flags_from_sleeper_player_meta(meta)
                    f2 = _infer_flags_from_nflverse(injuries, gsis, season, week)
                    inj, susp = _merge_flags(f1, f2)

                    bye = None
                    if nfl_team and played_set:
                        bye = (_norm_team(nfl_team) not in played_set)
                    if pts > 0:
                        bye = False

                    player_week_rows.append({
                        "Player": full_name,
                        "Team": team,
                        "Week": week,
                        "Year": season,
                        "Points": round(pts, 2),
                        "Injury?": bool(inj) if inj is not None else None,
                        "Suspension?": bool(susp) if susp is not None else None,
                        "Bye?": bool(bye) if bye is not None else None,
                        "Starter/Bench": "Starter" if started else "Bench",
                        "% of points (if starter)": round(pts / pf, 4) if started and pf else None,
                        "Position started in (if starter)": slot,
                        # advanced columns filled later / left blank if not computed yet
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

            week += 1

    pw = pd.DataFrame(player_week_rows)
    tw = pd.DataFrame(team_week_rows)
    tx = pd.DataFrame(transactions_rows)
    tr = pd.DataFrame(trades_rows)
    ph = pd.DataFrame(pick_rows)

    # --------------------------
    # Player-week derived columns + hardship engine
    # --------------------------
    if not pw.empty:
        pw = pw.sort_values(["Player", "Year", "Week"]).reset_index(drop=True)

        # "active" for change-metrics: exclude injury/susp/bye, but DO NOT exclude bench (bench counts)
        active = ~pw[["Injury?", "Suspension?", "Bye?"]].fillna(False).any(axis=1)

        pw["Change from previous week"] = None
        last_active_pts: Dict[str, float] = {}
        for i, row in pw.iterrows():
            k = row["Player"]
            if k in last_active_pts:
                pw.at[i, "Change from previous week"] = float(row["Points"]) - last_active_pts[k]
            if bool(active.iloc[i]):
                last_active_pts[k] = float(row["Points"])

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

        # Hardship: points lost due to injury/suspension for rostered players (missed with 0, not bye)
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

            # Update history ONLY with healthy games:
            if (pts > 0.0) and (not inj) and (not susp) and (not bye):
                hist.append(pts)
            last5[player] = hist

        pw["_expected_points_if_healthy"] = exp_points
        pw["_points_lost_inj_susp"] = points_lost

    # --------------------------
    # Team-week hardship / counts from player-week
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

        agg = pw2.groupby(["Team", "Year", "Week"], as_index=False).agg(
            Hardship=("_points_lost_inj_susp", "sum"),
            Number_of_Injuries=("_missed_injury", "sum"),
            Number_of_suspensions=("_missed_susp", "sum"),
            Number_of_players_on_bye=("_on_bye", "sum"),
        )
        tw = tw.merge(agg, how="left", on=["Team", "Year", "Week"])

        tw["Hardship"] = pd.to_numeric(tw["Hardship"], errors="coerce").fillna(0.0)
        tw["Number of Injuries"] = pd.to_numeric(tw["Number_of_Injuries"], errors="coerce").fillna(0).astype(int)
        tw["Number of suspensions"] = pd.to_numeric(tw["Number_of_suspensions"], errors="coerce").fillna(0).astype(int)
        tw["Number of players on bye"] = pd.to_numeric(tw["Number_of_players_on_bye"], errors="coerce").fillna(0).astype(int)

        tw.drop(columns=["Number_of_Injuries", "Number_of_suspensions", "Number_of_players_on_bye"], inplace=True, errors="ignore")

        # Brosenzweig / Sisenzweig (weekly league rank based)
        try:
            tw["_rank_pf_desc"] = tw.groupby(["Year", "Week"])["PF"].rank(ascending=False, method="min")
            tw["_rank_pf_asc"] = tw.groupby(["Year", "Week"])["PF"].rank(ascending=True, method="min")
            tw["Brosenzweig"] = ((tw["_rank_pf_desc"] == 2) & (tw["Win?"] == 0)).astype(int)
            tw["Sisenzweig"] = ((tw["_rank_pf_asc"] == 2) & (tw["Win?"] == 1)).astype(int)
            tw.drop(columns=["_rank_pf_desc", "_rank_pf_asc"], inplace=True, errors="ignore")
        except Exception:
            tw["Brosenzweig"] = None
            tw["Sisenzweig"] = None

    # --------------------------
    # Team-year / all-time with vs columns
    # --------------------------
    team_year = pd.DataFrame()
    team_all = pd.DataFrame()

    teams_sorted = sorted(all_teams_seen)

    def _record_str(w: int, l: int, t: int) -> str:
        return f"{w}-{l}" + (f"-{t}" if t else "")

    def _winpct(w: int, l: int, t: int) -> Optional[float]:
        g = w + l + t
        return round((w + 0.5 * t) / g, 4) if g else None

    if not tw.empty:
        base = tw.copy()
        base["_opp_actual"] = base.get("_OpponentTeamActual")
        base["Win?"] = pd.to_numeric(base["Win?"], errors="coerce")

        rows = []
        for (team, year), g in base.groupby(["Team", "Year"]):
            wins = int((g["Win?"] == 1).sum())
            losses = int((g["Win?"] == 0).sum())
            ties = int((g["Win?"] == 0.5).sum())

            row = {
                "Team": team,
                "Year": _to_int(year, year),
                "Record": _record_str(wins, losses, ties),
                "Win %": _winpct(wins, losses, ties),
            }

            # versus columns (include self for 16 cols in 8-team)
            for opp in teams_sorted:
                gg = g[g["_opp_actual"] == opp]
                w = int((gg["Win?"] == 1).sum())
                l = int((gg["Win?"] == 0).sum())
                t = int((gg["Win?"] == 0.5).sum())
                row[f"record vs {opp}"] = _record_str(w, l, t)
                row[f"win % vs {opp}"] = _winpct(w, l, t)

            rows.append(row)
        team_year = pd.DataFrame(rows)

        rows = []
        for team, g in base.groupby(["Team"]):
            wins = int((g["Win?"] == 1).sum())
            losses = int((g["Win?"] == 0).sum())
            ties = int((g["Win?"] == 0.5).sum())
            row = {
                "Team": team,
                "Seasons": int(g["Year"].nunique()) if "Year" in g.columns else None,
                "Record": _record_str(wins, losses, ties),
                "Win %": _winpct(wins, losses, ties),
            }
            for opp in teams_sorted:
                gg = g[g["_opp_actual"] == opp]
                w = int((gg["Win?"] == 1).sum())
                l = int((gg["Win?"] == 0).sum())
                t = int((gg["Win?"] == 0.5).sum())
                row[f"record vs {opp}"] = _record_str(w, l, t)
                row[f"win % vs {opp}"] = _winpct(w, l, t)
            rows.append(row)
        team_all = pd.DataFrame(rows)

        # remove internal opponent column before export
        tw.drop(columns=["_OpponentTeamActual"], inplace=True, errors="ignore")

    # --------------------------
    # Minimal league aggregates (placeholders for plan columns)
    # --------------------------
    player_year = pd.DataFrame()
    player_all = pd.DataFrame()
    league_week = pd.DataFrame()
    league_year = pd.DataFrame()
    league_all = pd.DataFrame()

    if not pw.empty:
        player_year = pw.groupby(["Player", "Year"], as_index=False).agg(
            Points=("Points", "sum"),
            **{"Best week": ("Points", "max"), "Worst week": ("Points", "min")},
        )
        player_all = pw.groupby(["Player"], as_index=False).agg(
            Points=("Points", "sum"),
            **{"Best week": ("Points", "max"), "Worst week": ("Points", "min")},
        )

    if not tw.empty:
        league_week = tw.groupby(["Year", "Week"], as_index=False).agg(
            PF=("PF", "sum"),
            **{"PF Range": ("PF", lambda s: float(pd.to_numeric(s, errors="coerce").max() - pd.to_numeric(s, errors="coerce").min()))}
        )
        league_year = tw.groupby(["Year"], as_index=False).agg(PF=("PF", "sum"), **{"Max PF": ("Max PF", "sum")})
        league_all = pd.DataFrame([{"PF": float(pd.to_numeric(tw["PF"], errors="coerce").fillna(0).sum()), "Years": int(tw["Year"].nunique())}])

    # --------------------------
    # Write outputs
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
        ("transactions.csv", pd.DataFrame(transactions_rows), "transactions"),
        ("trades.csv", pd.DataFrame(trades_rows), "trades"),
        ("pick_history.csv", ph, "Pick History"),
    ]

    for fname, frame, plan_key in tables:
        cols = catalog.get(plan_key, [])
        frame = _safe_df(frame)
        out = _ensure_plan_columns(frame, cols, keep_extras=True)
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
