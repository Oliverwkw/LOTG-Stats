from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import json
import re
from datetime import datetime, timezone, timedelta, date
from collections import Counter, deque

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
# Config
# --------------------------

@dataclass
class RunConfig:
    league_id: str
    min_season: int | None
    max_season: int | None
    season_type: str = "regular"


# --------------------------
# Helpers (robust)
# --------------------------

def _to_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default


def _to_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _safe_df(obj) -> pd.DataFrame:
    return obj if isinstance(obj, pd.DataFrame) else pd.DataFrame()


def _has_cols(df: pd.DataFrame, cols: List[str]) -> bool:
    return isinstance(df, pd.DataFrame) and all(c in df.columns for c in cols)


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


def _walk_league_chain(sc: SleeperClient, start_league_id: str, min_season: int | None, max_season: int | None) -> List[Dict[str, Any]]:
    """
    Walk previous_league_id chain. Any API error: stop gracefully.
    """
    chain = []
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
        lid = str(lg.get("previous_league_id") or "")
        if lid == "None":
            lid = ""

    chain = sorted(chain, key=lambda x: _to_int(x.get("season"), 0))
    if max_season is not None:
        chain = [x for x in chain if _to_int(x.get("season"), 0) <= max_season]
    return chain


def _league_roster_positions(lg: Dict[str, Any]) -> List[str]:
    settings = lg.get("settings") or {}
    rp = settings.get("roster_positions") or []
    return list(rp) if isinstance(rp, list) else []


def _team_name_map(users: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {}
    for u in users or []:
        uid = str(u.get("user_id"))
        meta = u.get("metadata") or {}
        out[uid] = meta.get("team_name") or u.get("display_name") or uid
    return out


def _infer_injury_flags(injuries: pd.DataFrame, gsis_id: Optional[str], season: int, week: int) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Best-effort. If injuries dataset schema changes, return (None, None).
    """
    injuries = _safe_df(injuries)
    if injuries.empty or not gsis_id:
        return (None, None)

    # normalize common cols
    if "season" in injuries.columns:
        injuries["season"] = pd.to_numeric(injuries["season"], errors="coerce").astype("Int64")
    if "week" in injuries.columns:
        injuries["week"] = pd.to_numeric(injuries["week"], errors="coerce").astype("Int64")

    if "gsis_id" not in injuries.columns:
        return (None, None)

    try:
        sub = injuries[
            (injuries["season"] == season) &
            (injuries["week"] == week) &
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
    injury = any(k in s for k in ["out", "doubt", "question", "ir", "injured", "pup"]) and not suspension
    return (injury, suspension)


def _played_teams_by_week(games: pd.DataFrame, season: int) -> Dict[int, set]:
    """
    Best-effort bye inference from nfldata games.csv.
    If games data missing, return {} and bye flags will be None.
    """
    games = _safe_df(games)
    by_week: Dict[int, set] = {}
    if games.empty or "season" not in games.columns:
        return by_week

    try:
        sub = games[games["season"] == season].copy()
    except Exception:
        return by_week
    if sub.empty:
        return by_week

    if "week" not in sub.columns:
        return by_week
    sub["week"] = pd.to_numeric(sub["week"], errors="coerce").astype("Int64")

    if "home_team" not in sub.columns or "away_team" not in sub.columns:
        return by_week

    for wk, g in sub.groupby("week"):
        if pd.isna(wk):
            continue
        played = set(g["home_team"].dropna().astype(str).tolist() + g["away_team"].dropna().astype(str).tolist())
        by_week[int(wk)] = played
    return by_week


def _download_csv_best_effort(urls: List[str], path: Path, timeout: int = 120) -> pd.DataFrame:
    """
    Best-effort download. If all URLs fail, return empty DF.
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


def _ensure_plan_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    df = _safe_df(df).copy()
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


# --------------------------
# Main build
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
    # External datasets (all best-effort)
    # --------------------------
    dp_ids = _safe_df(load_dynastyprocess_playerids(ext))
    for c in ["sleeper_id", "gsis_id", "name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    # DynastyProcess player values (best-effort map)
    dp_val_map: Dict[str, float] = {}
    dp_vals_players = _safe_df(load_dynastyprocess_values_players(ext))
    if not dp_vals_players.empty:
        name_col = _first_col(dp_vals_players, ["player", "name", "Player", "Name"])
        val_col = _first_col(dp_vals_players, ["value", "Value", "dp_value", "DP Value"])
        if name_col and val_col:
            try:
                dp_vals_players["player_key"] = dp_vals_players[name_col].astype(str).map(clean_name)
                dp_vals_players["dp_value"] = pd.to_numeric(dp_vals_players[val_col], errors="coerce")
                dp_val_map = dp_vals_players.groupby("player_key")["dp_value"].max().to_dict()
            except Exception:
                dp_val_map = {}

    # DynastyProcess pick values (best-effort map)
    dp_pick_val: Dict[str, float] = {}
    dp_vals_picks = _safe_df(load_dynastyprocess_values_picks(ext))
    if not dp_vals_picks.empty:
        pick_col = _first_col(dp_vals_picks, ["pick", "Pick"])
        val_col = _first_col(dp_vals_picks, ["value", "Value", "pick_value", "Pick Value"])
        if pick_col and val_col:
            try:
                dp_vals_picks["pick_key"] = dp_vals_picks[pick_col].astype(str).str.lower()
                dp_vals_picks["pick_value"] = pd.to_numeric(dp_vals_picks[val_col], errors="coerce")
                dp_pick_val = dp_vals_picks.groupby("pick_key")["pick_value"].max().to_dict()
            except Exception:
                dp_pick_val = {}

    # KTC community file (best-effort)
    ktc_latest: Dict[str, float] = {}
    ktc = pd.DataFrame()
    try:
        ktc = _download_csv_best_effort(
            urls=[
                "https://raw.githubusercontent.com/Adeiko/AdeTrades/master/KtcValues.csv",
                "https://github.com/Adeiko/AdeTrades/raw/master/KtcValues.csv",
            ],
            path=cache_dir / "KtcValues.csv",
            timeout=120,
        )
        if not ktc.empty:
            cols_lower = {c.lower(): c for c in ktc.columns}
            ktc_player_col = cols_lower.get("player") or cols_lower.get("name") or (ktc.columns[0] if len(ktc.columns) > 0 else None)
            ktc_value_col = cols_lower.get("value") or cols_lower.get("ktcvalue") or cols_lower.get("ktc") or (ktc.columns[1] if len(ktc.columns) > 1 else None)
            ktc_date_col = cols_lower.get("date") or cols_lower.get("asof") or None

            if ktc_player_col and ktc_value_col:
                ktc["player_key"] = ktc[ktc_player_col].astype(str).map(clean_name)
                if ktc_date_col and ktc_date_col in ktc.columns:
                    ktc["asof_date"] = pd.to_datetime(ktc[ktc_date_col], errors="coerce").dt.date
                else:
                    ktc["asof_date"] = pd.NaT
                ktc["ktc_value"] = pd.to_numeric(ktc[ktc_value_col], errors="coerce")
                ktc_latest = ktc.sort_values(["asof_date"]).groupby("player_key")["ktc_value"].last().to_dict()
    except Exception:
        ktc_latest = {}
        ktc = pd.DataFrame()

    # nfldata games for byes (best-effort)
    games = pd.DataFrame()
    try:
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
    except Exception:
        games = pd.DataFrame()

    # Sleeper player meta (best-effort)
    players_nfl = {}
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
            "team": meta.get("team"),
            "birth_date": meta.get("birth_date") or meta.get("birthdate"),
            "years_exp": meta.get("years_exp"),
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
    # Iterate seasons
    # --------------------------
    for lg in leagues:
        league_id = str(lg.get("league_id"))
        season = _to_int(lg.get("season"), 0) or 0
        roster_positions = _league_roster_positions(lg)

        # Users / rosters (best-effort)
        try:
            users = sc.users(league_id)
        except Exception:
            users = []
        try:
            rosters = sc.rosters(league_id)
        except Exception:
            rosters = []

        user_team_name = _team_name_map(users)

        roster_owner: Dict[int, str] = {}
        for r in rosters or []:
            rid = _to_int(r.get("roster_id"), None)
            if rid is None:
                continue
            roster_owner[rid] = str(r.get("owner_id") or "")

        roster_to_team: Dict[int, str] = {}
        for rid, owner in roster_owner.items():
            roster_to_team[rid] = user_team_name.get(owner, f"Roster {rid}")

        # Save raw snapshots (non-fatal)
        try:
            (raw_dir / f"league_{season}.json").write_text(json.dumps(lg, indent=2))
            (raw_dir / f"users_{season}.json").write_text(json.dumps(users, indent=2))
            (raw_dir / f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))
        except Exception:
            pass

        # Injuries (best-effort)
        injuries = pd.DataFrame()
        try:
            injuries = _safe_df(load_nflverse_injuries(ext, season))
        except Exception:
            injuries = pd.DataFrame()

        played_by_week = _played_teams_by_week(games, season)

        # Draft picks / pick history (best-effort; if Sleeper endpoints change, just skip)
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

        # --------------------------
        # Weekly loop (stop when matchups empty or errors)
        # --------------------------
        week = 1
        prev_starters_by_team: Dict[str, set] = {}

        while True:
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

            # matchup df safe
            mdf = _safe_df(pd.DataFrame(matchups))
            if not mdf.empty:
                if "points" in mdf.columns:
                    mdf["points"] = pd.to_numeric(mdf["points"], errors="coerce").fillna(0.0)
                else:
                    mdf["points"] = 0.0
                if "roster_id" in mdf.columns:
                    mdf["roster_id"] = pd.to_numeric(mdf["roster_id"], errors="coerce").fillna(-1).astype(int)
                else:
                    mdf["roster_id"] = -1
            else:
                break

            # opponent map
            opp_map: Dict[int, int] = {}
            if "matchup_id" in mdf.columns:
                for mid, g in mdf.groupby("matchup_id"):
                    rids = g["roster_id"].tolist()
                    if len(rids) == 2:
                        a, b = rids
                        opp_map[a] = b
                        opp_map[b] = a

            # tx summaries
            faab_spent: Dict[str, float] = {}
            trade_count: Dict[str, int] = {}
            tx_count: Dict[str, int] = {}

            for t in txs or []:
                creator = str(t.get("creator") or "")
                if not creator:
                    continue
                team = user_team_name.get(creator)
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

            week_team_pf = {}
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue
                team = roster_to_team.get(rid, f"Roster {rid}")
                week_team_pf[team] = float(_to_float(m.get("points"), 0.0) or 0.0)

            # --------------------------
            # Build team-week + player-week
            # --------------------------
            for m in matchups or []:
                rid = _to_int(m.get("roster_id"), None)
                if rid is None:
                    continue

                team = roster_to_team.get(rid, f"Roster {rid}")
                pf = float(_to_float(m.get("points"), 0.0) or 0.0)

                opp_rid = opp_map.get(rid)
                opp_team = roster_to_team.get(opp_rid, f"Roster {opp_rid}") if opp_rid is not None else None
                opp_points = None
                if opp_rid is not None and not mdf.empty:
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
                ppts = {}
                if isinstance(ppts_raw, dict):
                    for k, v in ppts_raw.items():
                        if v is None:
                            continue
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

                # injuries/susp/bye counts best-effort
                injuries_ct = susp_ct = byes_ct = 0
                played_set = played_by_week.get(week, set())

                for pid in players:
                    nfl_team = pid_meta.get(pid, {}).get("team")
                    gsis = None
                    if not dp_ids.empty and "sleeper_id" in dp_ids.columns and "gsis_id" in dp_ids.columns:
                        try:
                            match = dp_ids.loc[dp_ids["sleeper_id"].astype(str) == pid]
                            if not match.empty:
                                gsis = str(match["gsis_id"].iloc[0])
                        except Exception:
                            gsis = None

                    inj, susp = _infer_injury_flags(injuries, gsis, season, week)
                    if inj:
                        injuries_ct += 1
                    if susp:
                        susp_ct += 1
                    if nfl_team and played_set and nfl_team not in played_set:
                        byes_ct += 1

                hardship = round((injuries_ct + susp_ct + byes_ct) / max(1, len(starters)), 4) if starters else None
                tanking = (round((max_pf - pf) / max_pf, 4) if max_pf else None)

                # Upset by MaxPF best-effort
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

                bros = 1 if (upst == 1 and (hardship or 0) > 0 and win == 1) else 0
                sis = 1 if (upst == 0 and (hardship or 0) > 0 and win == 1) else 0

                team_week_rows.append({
                    "Team": team,
                    "Week": week,
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
                    "Hardship": hardship,
                    "Tanking": tanking,
                    "Luck": round(luck, 4) if luck is not None else None,
                    "Brosenzweig": bros,
                    "Sisenzweig": sis,
                    "Number of Injuries": injuries_ct,
                    "Number of suspensions": susp_ct,
                    "Number of players on bye": byes_ct,
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

                # Player-week rows
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

                    inj, susp = _infer_injury_flags(injuries, gsis, season, week)
                    bye = True if (nfl_team and played_set and nfl_team not in played_set) else None

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

            # --------------------------
            # Transactions rows (non-trade)
            # --------------------------
            for t in txs or []:
                if t.get("type") == "trade":
                    continue

                ttype = t.get("type")
                created_date = _epoch_ms_to_date(t.get("created"))
                creator = str(t.get("creator") or "")
                team = user_team_name.get(creator) if creator else None

                adds = t.get("adds") or {}
                drops = t.get("drops") or {}
                meta = t.get("metadata") or {}
                faab = meta.get("waiver_bid") if isinstance(meta, dict) else None
                num_bids = meta.get("num_bids") if isinstance(meta, dict) else None

                if not isinstance(adds, dict):
                    adds = {}
                if not isinstance(drops, dict):
                    drops = {}

                for pid, rid in adds.items():
                    pid = str(pid)
                    dropped = None
                    for dp, drid in drops.items():
                        if str(drid) == str(rid):
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

            # --------------------------
            # Trades rows (best-effort values)
            # --------------------------
            def _player_value(name: str, asof: Optional[date]) -> Tuple[Optional[float], Optional[float]]:
                key = clean_name(name)
                ktc_val = None

                # try historical if ktc has dates
                if asof is not None and not ktc.empty and "player_key" in ktc.columns and "asof_date" in ktc.columns and "ktc_value" in ktc.columns:
                    try:
                        sub = ktc[(ktc["player_key"] == key) & (ktc["asof_date"].notna()) & (ktc["asof_date"] <= asof)]
                        if not sub.empty:
                            ktc_val = float(sub.sort_values("asof_date")["ktc_value"].iloc[-1])
                    except Exception:
                        ktc_val = None

                if ktc_val is None:
                    v = ktc_latest.get(key)
                    ktc_val = float(v) if v is not None else None

                dp_val = dp_val_map.get(key)
                dp_val = float(dp_val) if dp_val is not None else None
                return ktc_val, dp_val

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
                for _, rid in adds.items():
                    rr = _to_int(rid, None)
                    if rr is not None:
                        rids.add(rr)

                for dp in draft_picks:
                    if not isinstance(dp, dict):
                        continue
                    for k in ["owner_id", "previous_owner_id", "roster_id"]:
                        if k in dp:
                            rr = _to_int(dp.get(k), None)
                            if rr is not None:
                                rids.add(rr)

                teams = [roster_to_team.get(rid, f"Roster {rid}") for rid in sorted(rids)]
                if len(teams) < 2:
                    continue

                team_gets = {tm: {"players": [], "picks": []} for tm in teams}

                for pid, rid in adds.items():
                    rr = _to_int(rid, None)
                    if rr is None:
                        continue
                    tm = roster_to_team.get(rr, f"Roster {rid}")
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
                    ktc_sum = 0.0
                    dp_sum = 0.0
                    any_ktc = False
                    any_dp = False

                    for nm in gets["players"]:
                        kv, dv = _player_value(nm, created_date)
                        if kv is not None:
                            ktc_sum += kv
                            any_ktc = True
                        if dv is not None:
                            dp_sum += dv
                            any_dp = True

                    side.append((tm, (ktc_sum if any_ktc else None), (dp_sum if any_dp else None), gets))

                ktc_diff = None
                dp_diff = None
                if len(side) == 2 and side[0][1] is not None and side[1][1] is not None:
                    ktc_diff = side[0][1] - side[1][1]
                if len(side) == 2 and side[0][2] is not None and side[1][2] is not None:
                    dp_diff = side[0][2] - side[1][2]

                trades_rows.append({
                    "Team A": teams[0],
                    "Team B": teams[1],
                    "Team C": teams[2] if len(teams) > 2 else None,
                    "Week": week,
                    "Year": season,
                    "Date": str(created_date) if created_date else None,
                    "Assets received by Team A": json.dumps(side[0][3]),
                    "Assets received by Team B": json.dumps(side[1][3]),
                    "Assets received by Team C": json.dumps(side[2][3]) if len(side) > 2 else None,
                    "KTC Value Difference at deal time": ktc_diff,
                    "Oliver value difference at deal time": dp_diff,
                    "Pick Value received by Team A": None,
                    "Pick Value received by Team B": None,
                    "Pick Value received by Team C": None,
                    "Value received by Team A": side[0][2],
                    "Value received by Team B": side[1][2],
                    "Value received by Team C": side[2][2] if len(side) > 2 else None,
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
    # Player-week derived columns (robust)
    # --------------------------
    if not pw.empty:
        pw = pw.sort_values(["Player", "Year", "Week"])
        active = ~pw[["Injury?", "Suspension?", "Bye?"]].fillna(False).any(axis=1)

        # Change from previous active week
        pw["Change from previous week"] = None
        last_active_pts: Dict[str, float] = {}
        for idx, row in pw.iterrows():
            k = row["Player"]
            if k in last_active_pts:
                pw.at[idx, "Change from previous week"] = float(row["Points"]) - last_active_pts[k]
            if bool(active.loc[idx]):
                last_active_pts[k] = float(row["Points"])

        # previous 5 active weeks avg (spans seasons)
        pw["Change from previous 5 weeks avg"] = None
        windows: Dict[str, deque] = {}
        for idx, row in pw.iterrows():
            k = row["Player"]
            q = windows.get(k, deque(maxlen=5))
            if len(q) == 5:
                pw.at[idx, "Change from previous 5 weeks avg"] = float(row["Points"]) - (sum(q) / 5)
            if bool(active.loc[idx]):
                q.append(float(row["Points"]))
            windows[k] = q

        # career avg to that point (active weeks only)
        pw["Change from career average to that point"] = None
        sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for idx, row in pw.iterrows():
            k = row["Player"]
            if counts.get(k, 0) > 0:
                pw.at[idx, "Change from career average to that point"] = float(row["Points"]) - (sums[k] / counts[k])
            if bool(active.loc[idx]):
                sums[k] = sums.get(k, 0.0) + float(row["Points"])
                counts[k] = counts.get(k, 0) + 1

        # overall career avg (active weeks only)
        try:
            full_avg = pw.loc[active].groupby("Player")["Points"].mean()
            pw["Change from overall career average"] = pw["Points"] - pw["Player"].map(full_avg)
        except Exception:
            pw["Change from overall career average"] = None

        # bench streak spans seasons; starter/bench totals by season and all-time
        pw = pw.sort_values(["Team", "Player", "Year", "Week"])
        stats: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for idx, row in pw.iterrows():
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
                pw.at[idx, "Number of consecutive weeks on bench before start (if starter)"] = st["bench_streak"]
                pw.at[idx, "Number of consecutive weeks on bench before start excluding injury/bye (if starter)"] = st["bench_streak_ex"]
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

            pw.at[idx, "Number of weeks on team"] = st["weeks"]
            pw.at[idx, "Total weeks as team starter to that point"] = st["start_all"]
            pw.at[idx, "Total weeks on bench to that point"] = st["bench_all"]
            pw.at[idx, "Total weeks as team starter on that team this season"] = st["start_season"]
            pw.at[idx, "Total weeks on bench on that team this season"] = st["bench_season"]

            stats[key] = st

    # --------------------------
    # Team-week derived columns (robust)
    # --------------------------
    if not tw.empty:
        tw = tw.sort_values(["Year", "Week", "PF"], ascending=[True, True, False])

        # flags per week
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

        tw = tw.sort_values(["Team", "Year", "Week"])
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
    def _align(df: pd.DataFrame, plan_key: str) -> pd.DataFrame:
        cols = catalog.get(plan_key, [])
        return _ensure_plan_columns(df, cols)

    player_year = pd.DataFrame()
    player_all = pd.DataFrame()
    if not pw.empty:
        rows = []
        for (player, year), g in pw.groupby(["Player", "Year"]):
            rows.append({
                "Player": player,
                "Year": _to_int(year, year),
                "Points": round(float(pd.to_numeric(g["Points"], errors="coerce").fillna(0).sum()), 2),
                "Best week": round(float(pd.to_numeric(g["Points"], errors="coerce").max()), 2),
                "Worst week": round(float(pd.to_numeric(g["Points"], errors="coerce").min()), 2),
            })
        player_year = pd.DataFrame(rows)

        rows = []
        for player, g in pw.groupby(["Player"]):
            rows.append({
                "Player": player,
                "Points": round(float(pd.to_numeric(g["Points"], errors="coerce").fillna(0).sum()), 2),
                "Best week": round(float(pd.to_numeric(g["Points"], errors="coerce").max()), 2),
                "Worst week": round(float(pd.to_numeric(g["Points"], errors="coerce").min()), 2),
            })
        player_all = pd.DataFrame(rows)

    team_year = pd.DataFrame()
    team_all = pd.DataFrame()
    if not tw.empty:
        rows = []
        for (team, year), g in tw.groupby(["Team", "Year"]):
            wins = int((g["Win?"] == 1).sum()) if "Win?" in g.columns else 0
            losses = int((g["Win?"] == 0).sum()) if "Win?" in g.columns else 0
            ties = int((g["Win?"] == 0.5).sum()) if "Win?" in g.columns else 0
            games = max(1, wins + losses + ties)
            points = float(pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0).sum())
            maxpf = float(pd.to_numeric(g.get("Max PF", 0), errors="coerce").fillna(0).sum())

            rows.append({
                "Team": team,
                "Year": _to_int(year, year),
                "Win %": round((wins + 0.5 * ties) / games, 4),
                "Record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
                "Points": round(points, 2),
                "Avg points": round(points / games, 2),
                "Max PF": round(maxpf, 2),
                "Avg max PF": round(maxpf / games, 2),
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
            games = max(1, wins + losses + ties)
            points = float(pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0).sum())
            maxpf = float(pd.to_numeric(g.get("Max PF", 0), errors="coerce").fillna(0).sum())

            rows.append({
                "Team": team,
                "Seasons": int(g.get("Year", pd.Series(dtype=int)).nunique()) if "Year" in g.columns else None,
                "Win %": round((wins + 0.5 * ties) / games, 4),
                "Record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
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
            rows.append({
                "Year": _to_int(year, year),
                "Week": _to_int(week, week),
                "PF": round(float(pd.to_numeric(g.get("PF", 0), errors="coerce").fillna(0).sum()), 2),
                "PF Range": round(float(pd.to_numeric(g.get("PF", 0), errors="coerce").max() - pd.to_numeric(g.get("PF", 0), errors="coerce").min()), 2),
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
            "Years": int(tw.get("Year", pd.Series(dtype=int)).nunique()) if "Year" in tw.columns else None,
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

    # Excel workbook (one tab per CSV)
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)

    for csvf in sorted(out_dir.glob("*.csv")):
        ws = wb.create_sheet(title=csvf.stem[:31])
        try:
            d = pd.read_csv(csvf)
        except Exception:
            d = pd.DataFrame()
        ws.append(list(d.columns))
        for row in d.itertuples(index=False, name=None):
            ws.append(list(row))

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
