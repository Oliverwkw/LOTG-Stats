from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import json
import pandas as pd
from tqdm import tqdm
import yaml
from dateutil import parser as dateparser
from datetime import datetime, timezone, timedelta, date
import re

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

@dataclass
class RunConfig:
    league_id: str
    min_season: int | None
    max_season: int | None
    season_type: str = "regular"

def _walk_league_chain(sc: SleeperClient, start_league_id: str, min_season: int | None, max_season: int | None) -> List[Dict[str, Any]]:
    chain=[]
    lid = str(start_league_id)
    seen=set()
    while lid and lid not in seen:
        seen.add(lid)
        lg = sc.league(lid)
        season = int(lg.get("season")) if str(lg.get("season","")).isdigit() else None
        if season is not None and min_season is not None and season < min_season:
            break
        chain.append(lg)
        lid = str(lg.get("previous_league_id") or "")
        if lid == "None":
            lid = ""
    chain = sorted(chain, key=lambda x: int(x.get("season") or 0))
    if max_season is not None:
        chain = [x for x in chain if int(x.get("season") or 0) <= max_season]
    return chain

def _league_roster_positions(lg: Dict[str, Any]) -> List[str]:
    settings = lg.get("settings") or {}
    rp = settings.get("roster_positions") or []
    return list(rp) if isinstance(rp, list) else []

def _draft_rounds(lg: Dict[str, Any]) -> int:
    settings = lg.get("settings") or {}
    dr = settings.get("draft_rounds")
    try:
        return int(dr)
    except Exception:
        return 4

def _num_teams(lg: Dict[str, Any]) -> int:
    settings = lg.get("settings") or {}
    nt = settings.get("num_teams")
    try:
        return int(nt)
    except Exception:
        return 12

def _team_name_map(users: List[Dict[str, Any]]) -> Dict[str, str]:
    out={}
    for u in users:
        uid=str(u.get("user_id"))
        meta=u.get("metadata") or {}
        out[uid]=meta.get("team_name") or u.get("display_name") or uid
    return out

def _epoch_ms_to_date(ms: int) -> Optional[date]:
    try:
        return datetime.fromtimestamp(ms/1000, tz=timezone.utc).date()
    except Exception:
        return None

def _calc_age(birth_date_str: Optional[str], on_date: date) -> Optional[float]:
    if not birth_date_str:
        return None
    try:
        bd = dateparser.parse(birth_date_str).date()
        return round((on_date - bd).days / 365.25, 2)
    except Exception:
        return None

def _infer_injury_flags(injuries: pd.DataFrame, gsis_id: Optional[str], season: int, week: int) -> Tuple[Optional[bool], Optional[bool]]:
    if injuries is None or injuries.empty or not gsis_id:
        return (None, None)
    lower = {c.lower(): c for c in injuries.columns}
    status_col = None
    for cand in ["report_status", "status", "game_status", "injury_status", "practice_status"]:
        if cand in lower:
            status_col = lower[cand]
            break
    if status_col is None:
        return (None, None)
    try:
        sub = injuries[(injuries.get("season") == season) & (injuries.get("week") == week) & (injuries.get("gsis_id").astype(str) == str(gsis_id))]
    except Exception:
        return (None, None)
    if sub.empty:
        return (None, None)
    s = str(sub.iloc[0][status_col] or "").lower()
    if not s:
        return (None, None)
    suspension = ("susp" in s) or ("sspd" in s)
    injury = any(k in s for k in ["out","doubt","question","ir","injured","pup"]) and not suspension
    return (injury, suspension)

def _played_teams_by_week(games: pd.DataFrame, season: int) -> Dict[int, set]:
    by_week = {}
    if games is None or games.empty:
        return by_week
    sub = games[games.get("season") == season].copy()
    if sub.empty:
        return by_week
    sub["week"] = pd.to_numeric(sub.get("week"), errors="coerce").astype("Int64")
    for wk, g in sub.groupby("week"):
        played = set(g.get("home_team").dropna().astype(str).tolist() + g.get("away_team").dropna().astype(str).tolist())
        by_week[int(wk)] = played
    return by_week

def build_all(repo_root: Path) -> None:
    plan_csv = repo_root / "plan" / "LOTG Plan - Sheet1.csv"
    catalog = load_plan_catalog(plan_csv)

    cfg = yaml.safe_load((repo_root/"config/league.yaml").read_text())
    run_cfg = RunConfig(
        league_id=str(cfg["league_id"]),
        min_season=cfg.get("min_season"),
        max_season=cfg.get("max_season"),
        season_type=str(cfg.get("season_type","regular")).lower(),
    )

    http = HttpConfig(timeout_seconds=30, max_retries=10, backoff_base_seconds=0.7)
    sc = SleeperClient(http)

    cache_dir = repo_root / ".cache"
    cache_dir.mkdir(exist_ok=True)
    ext = ExternalConfig(cache_dir=cache_dir, timeout_seconds=120)

    dp_ids = load_dynastyprocess_playerids(ext)
    for c in ["sleeper_id","gsis_id","name"]:
        if c in dp_ids.columns:
            dp_ids[c] = dp_ids[c].astype(str)

    dp_vals_players = load_dynastyprocess_values_players(ext)
    dp_vals_players["player_key"] = dp_vals_players.get("player", dp_vals_players.get("name","")).astype(str).map(clean_name)
    dp_vals_players["dp_value"] = pd.to_numeric(dp_vals_players.get("value"), errors="coerce")
    dp_val_map = dp_vals_players.groupby("player_key")["dp_value"].max().to_dict()

    dp_vals_picks = load_dynastyprocess_values_picks(ext)
    dp_vals_picks["pick_key"] = dp_vals_picks.get("pick").astype(str).str.lower()
    dp_vals_picks["pick_value"] = pd.to_numeric(dp_vals_picks.get("value"), errors="coerce")
    dp_pick_val = dp_vals_picks.groupby("pick_key")["pick_value"].max().to_dict()

    # community KTC dataset
    ktc_url = "https://raw.githubusercontent.com/Adeiko/AdeTrades/master/KtcValues.csv"
    ktc_path = cache_dir / "KtcValues.csv"
    if not ktc_path.exists():
        import requests
        r = requests.get(ktc_url, timeout=120)
        r.raise_for_status()
        ktc_path.write_bytes(r.content)
    ktc = pd.read_csv(ktc_path)
    ktc_cols = {c.lower(): c for c in ktc.columns}
    ktc_player_col = ktc_cols.get("player") or ktc_cols.get("name") or list(ktc.columns)[0]
    ktc_value_col = ktc_cols.get("value") or ktc_cols.get("ktcvalue") or ktc_cols.get("ktc") or list(ktc.columns)[1]
    ktc_date_col = ktc_cols.get("date") or ktc_cols.get("asof") or None
    ktc["player_key"] = ktc[ktc_player_col].astype(str).map(clean_name)
    if ktc_date_col:
        ktc["asof_date"] = pd.to_datetime(ktc[ktc_date_col], errors="coerce").dt.date
    else:
        ktc["asof_date"] = pd.NaT
    ktc["ktc_value"] = pd.to_numeric(ktc[ktc_value_col], errors="coerce")
    ktc_latest = ktc.sort_values(["asof_date"]).groupby("player_key")["ktc_value"].last().to_dict()

    players_nfl = sc.players_nfl()
    pid_meta = {}
    for pid, meta in players_nfl.items():
        if not isinstance(meta, dict):
            continue
        pid = str(pid)
        full = meta.get("full_name") or (str(meta.get("first_name","")) + " " + str(meta.get("last_name",""))).strip()
        pos = meta.get("position")
        team = meta.get("team")
        bd = meta.get("birth_date") or meta.get("birthdate") or None
        yrs = meta.get("years_exp")
        pid_meta[pid] = {"full_name": full, "pos": pos, "team": team, "birth_date": bd, "years_exp": yrs}

    # nfldata games for byes
    games_path = cache_dir / "nfldata_games.csv"
    if not games_path.exists():
        import requests
        url = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        games_path.write_bytes(r.content)
    games = pd.read_csv(games_path)
    games["season"] = pd.to_numeric(games.get("season"), errors="coerce").astype("Int64")

    leagues = _walk_league_chain(sc, run_cfg.league_id, run_cfg.min_season, run_cfg.max_season)

    raw_dir = repo_root / "exports" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    player_week_rows=[]
    team_week_rows=[]
    transactions_rows=[]
    trades_rows=[]
    pick_rows=[]

    for lg in tqdm(leagues, desc="Seasons"):
        league_id = str(lg["league_id"])
        season = int(lg.get("season") or 0)
        roster_positions = _league_roster_positions(lg)

        users = sc.users(league_id)
        rosters = sc.rosters(league_id)
        user_team_name = _team_name_map(users)
        roster_owner = {int(r["roster_id"]): str(r.get("owner_id")) for r in rosters}
        roster_to_team = {rid: user_team_name.get(owner, f"Roster {rid}") for rid, owner in roster_owner.items()}

        (raw_dir/f"league_{season}.json").write_text(json.dumps(lg, indent=2))
        (raw_dir/f"users_{season}.json").write_text(json.dumps(users, indent=2))
        (raw_dir/f"rosters_{season}.json").write_text(json.dumps(rosters, indent=2))

        try:
            injuries = load_nflverse_injuries(ext, season)
            injuries["season"] = pd.to_numeric(injuries.get("season"), errors="coerce").astype("Int64")
            injuries["week"] = pd.to_numeric(injuries.get("week"), errors="coerce").astype("Int64")
            if "gsis_id" in injuries.columns:
                injuries["gsis_id"] = injuries["gsis_id"].astype(str)
        except Exception:
            injuries = pd.DataFrame()

        played_by_week = _played_teams_by_week(games, season)

        # Draft picks for Pick History
        try:
            drafts = sc.drafts(league_id)
        except Exception:
            drafts = []
        draft_picks_all=[]
        for d in drafts:
            did = str(d.get("draft_id") or "")
            if not did:
                continue
            try:
                picks = sc.draft_picks(did)
            except Exception:
                picks=[]
            for p in picks:
                p["draft_id"]=did
            draft_picks_all.extend(picks)
        for p in draft_picks_all:
            rnd = p.get("round")
            pick_no = p.get("pick_no")
            roster_id = p.get("roster_id")
            player = p.get("player_id")
            team = roster_to_team.get(int(roster_id), f"Roster {roster_id}") if roster_id is not None else None
            pick_rows.append({
                "Year": season,
                "Original Team": team,
                "Number": f"R{rnd}.{pick_no}",
                "Player Picked": pid_meta.get(str(player),{}).get("full_name") if player else None,
                "Trade 1": None, "Trade 2": None, "Trade 3": None, "Trade 4": None, "Trade 5": None,
                "Trade 6": None, "Trade 7": None, "Trade 8": None, "Trade 9": None, "Trade 10": None,
                "etc": None,
            })

        week=1
        prev_starters_by_team={}
        while True:
            matchups = sc.matchups(league_id, week)
            if not matchups:
                break
            txs = sc.transactions(league_id, week)

            mdf = pd.DataFrame(matchups)
            mdf["points"] = pd.to_numeric(mdf.get("points"), errors="coerce").fillna(0.0)
            mdf["roster_id"] = pd.to_numeric(mdf.get("roster_id"), errors="coerce").astype(int)

            opp_map={}
            for mid, g in mdf.groupby("matchup_id"):
                rids=g["roster_id"].tolist()
                if len(rids)==2:
                    a,b=rids
                    opp_map[a]=b
                    opp_map[b]=a

            faab_spent={}
            trade_count={}
            tx_count={}
            for t in txs:
                creator = str(t.get("creator") or "")
                if not creator:
                    continue
                team = user_team_name.get(creator)
                if not team:
                    continue
                tx_count[team]=tx_count.get(team,0)+1
                if t.get("type")=="trade":
                    trade_count[team]=trade_count.get(team,0)+1
                meta = t.get("metadata") or {}
                bid = None
                if isinstance(meta, dict):
                    bid = meta.get("waiver_bid") or meta.get("faab")
                try:
                    bid = float(bid) if bid is not None else 0.0
                except Exception:
                    bid = 0.0
                faab_spent[team]=faab_spent.get(team,0.0)+bid

            week_team_pf = {roster_to_team[int(m["roster_id"])]: float(m.get("points") or 0.0) for m in matchups}

            for m in matchups:
                rid = int(m["roster_id"])
                team = roster_to_team.get(rid, f"Roster {rid}")
                pf = float(m.get("points") or 0.0)
                opp_rid = opp_map.get(rid)
                opp_team = roster_to_team.get(opp_rid, f"Roster {opp_rid}") if opp_rid is not None else None
                opp_points = float(mdf.loc[mdf["roster_id"]==opp_rid,"points"].iloc[0]) if opp_rid is not None and (mdf["roster_id"]==opp_rid).any() else None
                margin = (pf - opp_points) if opp_points is not None else None
                win = None
                if margin is not None:
                    win = 1 if margin>0 else 0 if margin<0 else 0.5

                starters = [str(x) for x in (m.get("starters") or []) if x]
                players = [str(x) for x in (m.get("players") or []) if x]
                ppts_raw = (m.get("players_points") or {})
                ppts = {str(k): float(v) for k,v in ppts_raw.items() if v is not None}

                pos_map = {pid: (pid_meta.get(pid,{}).get("pos") or "") for pid in players}
                max_pf, _ = max_points_lineup(roster_positions, players, ppts, pos_map)
                eff = safe_div(pf, max_pf) if max_pf else None

                scores = list(week_team_pf.values())
                expected = sum(1 for s in scores if pf > s) / max(1,(len(scores)-1))
                luck = (win - expected) if (win is not None) else None

                prev = prev_starters_by_team.get(team, set())
                turnover = len(set(starters).symmetric_difference(prev)) if prev else None
                prev_starters_by_team[team]=set(starters)

                starter_points = [ppts.get(pid, 0.0) for pid in starters]
                donuts = sum(1 for x in starter_points if float(x)==0.0)
                under10 = sum(1 for x in starter_points if float(x)<10.0)
                over20 = sum(1 for x in starter_points if float(x)>20.0)
                over30 = sum(1 for x in starter_points if float(x)>30.0)
                over40 = sum(1 for x in starter_points if float(x)>40.0)
                over50 = sum(1 for x in starter_points if float(x)>50.0)
                diff_hi_lo = (max(starter_points) - min(starter_points)) if starter_points else None

                # roster composition
                def count_pos(pids, pos):
                    return sum(1 for pid in pids if pid_meta.get(pid,{}).get("pos")==pos)
                qb_s, rb_s, wr_s, te_s = count_pos(starters,"QB"), count_pos(starters,"RB"), count_pos(starters,"WR"), count_pos(starters,"TE")
                qb_r, rb_r, wr_r, te_r = count_pos(players,"QB"), count_pos(players,"RB"), count_pos(players,"WR"), count_pos(players,"TE")
                rook_s = sum(1 for pid in starters if pid_meta.get(pid,{}).get("years_exp") in (0,"0",0.0))
                rook_r = sum(1 for pid in players if pid_meta.get(pid,{}).get("years_exp") in (0,"0",0.0))

                approx_date = date(season, 9, 1) + timedelta(days=7*(week-1))
                ages = [a for a in (_calc_age(pid_meta.get(pid,{}).get("birth_date"), approx_date) for pid in players) if a is not None]
                avg_age = round(sum(ages)/len(ages),2) if ages else None

                from collections import Counter
                roster_nfl_teams = [pid_meta.get(pid,{}).get("team") for pid in players if pid_meta.get(pid,{}).get("team")]
                start_nfl_teams = [pid_meta.get(pid,{}).get("team") for pid in starters if pid_meta.get(pid,{}).get("team")]
                most_start_same = max(Counter(start_nfl_teams).values()) if start_nfl_teams else None
                most_roster_same = max(Counter(roster_nfl_teams).values()) if roster_nfl_teams else None

                # injuries/susp/bye counts
                injuries_ct=susp_ct=byes_ct=0
                played_set = played_by_week.get(week, set())
                for pid in players:
                    nfl_team = pid_meta.get(pid,{}).get("team")
                    try:
                        gsis = dp_ids.loc[dp_ids["sleeper_id"]==pid,"gsis_id"].iloc[0]
                    except Exception:
                        gsis=None
                    inj, susp = _infer_injury_flags(injuries, str(gsis) if gsis else None, season, week)
                    if inj: injuries_ct += 1
                    if susp: susp_ct += 1
                    if nfl_team and played_set and nfl_team not in played_set:
                        byes_ct += 1
                hardship = round((injuries_ct + susp_ct + byes_ct)/max(1,len(starters)),4)
                tanking = (round((max_pf - pf)/max_pf,4) if max_pf else None)

                # Upset based on max_pf
                opp_maxpf=None
                if opp_rid is not None:
                    opp_m = next((x for x in matchups if int(x["roster_id"])==int(opp_rid)), None)
                    if opp_m:
                        opp_players = [str(x) for x in (opp_m.get("players") or []) if x]
                        opp_ppts = {str(k): float(v) for k,v in (opp_m.get("players_points") or {}).items() if v is not None}
                        opp_pos_map = {pid: (pid_meta.get(pid,{}).get("pos") or "") for pid in opp_players}
                        opp_maxpf, _ = max_points_lineup(roster_positions, opp_players, opp_ppts, opp_pos_map)
                upst=None
                if win is not None and opp_maxpf is not None:
                    upst = 1 if (max_pf < opp_maxpf and win==1) else 0
                bros = 1 if (upst==1 and win==1 and hardship>0) else 0
                sis = 1 if (upst==0 and win==1 and hardship>0) else 0

                team_week_rows.append({
                    "Team": team,
                    "Week": week,
                    "Year": season,
                    "PF": round(pf,2),
                    "Win?": win,
                    "Opponent": opp_team,
                    "Points against": round(opp_points,2) if opp_points is not None else None,
                    "Margin": round(margin,2) if margin is not None else None,
                    "Max PF": max_pf,
                    "Efficiency": round(eff,4) if eff is not None else None,
                    "Starter turnover from previous week": turnover,
                    "Difference between highest and lowest starters": round(diff_hi_lo,2) if diff_hi_lo is not None else None,
                    "Combined matchup score": round(pf + (opp_points or 0.0),2) if opp_points is not None else None,
                    "Number of donuts": donuts,
                    "Number of players under 10": under10,
                    "Number of players over 20": over20,
                    "Number of players over 30": over30,
                    "Number of players over 40": over40,
                    "Number of players over 50": over50,
                    "UPST": upst,
                    "Hardship": hardship,
                    "Tanking": tanking,
                    "Luck": round(luck,4) if luck is not None else None,
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
                    "Number of transactions": tx_count.get(team,0),
                    "Number of trades": trade_count.get(team,0),
                    "Amount of FAAB spent": round(faab_spent.get(team,0.0),2),
                    "Most number of players started from same NFL team": most_start_same,
                    "Most number of players rostered from same NFL team": most_roster_same,
                    "Number of NFL teams among starting players": len(set(start_nfl_teams)) if start_nfl_teams else None,
                    "Number of NFL teams amoung rostered players": len(set(roster_nfl_teams)) if roster_nfl_teams else None,
                    "Number of rookies started": rook_s,
                    "Number of rookies rostered": rook_r,
                    "Player average age": avg_age,
                })

                starter_slot={}
                for i,pid in enumerate(starters):
                    if i < len(roster_positions):
                        starter_slot[pid] = roster_positions[i]

                for pid in players:
                    meta = pid_meta.get(pid,{})
                    full_name = meta.get("full_name") or pid
                    nfl_team = meta.get("team")
                    pts = float(ppts.get(pid, 0.0))
                    started = (pid in starters)
                    slot = starter_slot.get(pid) if started else None

                    try:
                        gsis = dp_ids.loc[dp_ids["sleeper_id"]==pid,"gsis_id"].iloc[0]
                    except Exception:
                        gsis=None
                    inj, susp = _infer_injury_flags(injuries, str(gsis) if gsis else None, season, week)
                    played_set = played_by_week.get(week, set())
                    bye = True if (nfl_team and played_set and nfl_team not in played_set) else None

                    player_week_rows.append({
                        "Player": full_name,
                        "Team": team,
                        "Week": week,
                        "Year": season,
                        "Points": round(pts,2),
                        "Injury?": bool(inj) if inj is not None else None,
                        "Suspension?": bool(susp) if susp is not None else None,
                        "Bye?": bool(bye) if bye is not None else None,
                        "Starter/Bench": "Starter" if started else "Bench",
                        "% of points (if starter)": round(pts/pf,4) if started and pf else None,
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
                    })

            # Transactions table
            for t in txs:
                if t.get("type")=="trade":
                    continue
                ttype = t.get("type")
                created_date = _epoch_ms_to_date(int(t.get("created") or 0))
                creator = str(t.get("creator") or "")
                team = user_team_name.get(creator) if creator else None
                adds = t.get("adds") or {}
                drops = t.get("drops") or {}
                meta = t.get("metadata") or {}
                faab = meta.get("waiver_bid") if isinstance(meta, dict) else None
                num_bids = meta.get("num_bids") if isinstance(meta, dict) else None

                for pid, rid in (adds or {}).items():
                    pid=str(pid)
                    dropped=None
                    for dp, drid in (drops or {}).items():
                        if str(drid)==str(rid):
                            dropped=str(dp); break
                    transactions_rows.append({
                        "Team": team,
                        "Player Added": pid_meta.get(pid,{}).get("full_name") or pid,
                        "Player Dropped": pid_meta.get(dropped,{}).get("full_name") if dropped else None,
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

            # Trades table
            for t in txs:
                if t.get("type")!="trade":
                    continue
                created_date = _epoch_ms_to_date(int(t.get("created") or 0))
                adds = t.get("adds") or {}
                draft_picks = t.get("draft_picks") or []
                rids=set()
                for _, rid in adds.items():
                    try: rids.add(int(rid))
                    except Exception: pass
                for dp in draft_picks:
                    for k in ["owner_id","previous_owner_id","roster_id"]:
                        if k in dp:
                            try: rids.add(int(dp[k]))
                            except Exception: pass
                teams=[roster_to_team.get(rid, f"Roster {rid}") for rid in sorted(rids)]
                if len(teams)<2:
                    continue

                team_gets={tm: {"players": [], "picks": []} for tm in teams}
                for pid, rid in adds.items():
                    tm = roster_to_team.get(int(rid), f"Roster {rid}")
                    team_gets.setdefault(tm, {"players": [], "picks": []})
                    team_gets[tm]["players"].append(pid_meta.get(str(pid),{}).get("full_name") or str(pid))
                for dp in draft_picks:
                    owner = roster_to_team.get(int(dp.get("owner_id")), f"Roster {dp.get('owner_id')}")
                    team_gets.setdefault(owner, {"players": [], "picks": []})
                    team_gets[owner]["picks"].append(f"{dp.get('season')} R{dp.get('round')}")
                def player_value(name, asof):
                    key=clean_name(name)
                    ktc_val=None
                    if asof is not None and "asof_date" in ktc.columns and ktc["asof_date"].notna().any():
                        sub=ktc[(ktc["player_key"]==key) & (ktc["asof_date"].notna()) & (ktc["asof_date"]<=asof)]
                        if not sub.empty:
                            ktc_val=float(sub.sort_values("asof_date")["ktc_value"].iloc[-1])
                    if ktc_val is None:
                        ktc_val=ktc_latest.get(key)
                        ktc_val=float(ktc_val) if ktc_val is not None else None
                    dp_val=dp_val_map.get(key)
                    dp_val=float(dp_val) if dp_val is not None else None
                    return ktc_val, dp_val
                side=[]
                for tm in teams:
                    gets=team_gets.get(tm, {"players": [], "picks": []})
                    ktc_sum=0.0; dp_sum=0.0
                    for nm in gets["players"]:
                        kv,dv=player_value(nm, created_date)
                        if kv is not None: ktc_sum+=kv
                        if dv is not None: dp_sum+=dv
                    side.append((tm, ktc_sum if ktc_sum else None, dp_sum if dp_sum else None, gets))
                ktc_diff=None; dp_diff=None
                if len(side)==2 and side[0][1] is not None and side[1][1] is not None:
                    ktc_diff=side[0][1]-side[1][1]
                if len(side)==2 and side[0][2] is not None and side[1][2] is not None:
                    dp_diff=side[0][2]-side[1][2]
                trades_rows.append({
                    "Team A": teams[0],
                    "Team B": teams[1],
                    "Team C": teams[2] if len(teams)>2 else None,
                    "Week": week,
                    "Year": season,
                    "Date": str(created_date) if created_date else None,
                    "Assets received by Team A": json.dumps(side[0][3]),
                    "Assets received by Team B": json.dumps(side[1][3]),
                    "Assets received by Team C": json.dumps(side[2][3]) if len(side)>2 else None,
                    "KTC Value Difference at deal time": ktc_diff,
                    "Oliver value difference at deal time": dp_diff,
                    "Pick Value received by Team A": None,
                    "Pick Value received by Team B": None,
                    "Pick Value received by Team C": None,
                    "Value received by Team A": side[0][2],
                    "Value received by Team B": side[1][2],
                    "Value received by Team C": side[2][2] if len(side)>2 else None,
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

    pw = pd.DataFrame(player_week_rows)
    tw = pd.DataFrame(team_week_rows)
    tx = pd.DataFrame(transactions_rows)
    tr = pd.DataFrame(trades_rows)
    ph = pd.DataFrame(pick_rows)

    # Player-week derived columns
    if not pw.empty:
        pw_cols = catalog.get("Player-Week", [])
        for c in pw_cols:
            if c not in pw.columns:
                pw[c]=None
        pw = pw.sort_values(["Player","Year","Week"])
        active = ~pw[["Injury?","Suspension?","Bye?"]].fillna(False).any(axis=1)

        pw["Change from previous week"]=None
        last={}
        for idx,row in pw.iterrows():
            k=row["Player"]
            if k in last:
                pw.at[idx,"Change from previous week"]=row["Points"]-last[k]
            if bool(active.loc[idx]):
                last[k]=row["Points"]

        from collections import deque
        pw["Change from previous 5 weeks avg"]=None
        windows={}
        for idx,row in pw.iterrows():
            k=row["Player"]
            q=windows.get(k, deque(maxlen=5))
            if len(q)==5:
                pw.at[idx,"Change from previous 5 weeks avg"]=row["Points"]-(sum(q)/5)
            if bool(active.loc[idx]):
                q.append(float(row["Points"]))
            windows[k]=q

        pw["Change from career average to that point"]=None
        sums={}; counts={}
        for idx,row in pw.iterrows():
            k=row["Player"]
            if counts.get(k,0)>0:
                pw.at[idx,"Change from career average to that point"]=row["Points"]-(sums[k]/counts[k])
            if bool(active.loc[idx]):
                sums[k]=sums.get(k,0.0)+float(row["Points"])
                counts[k]=counts.get(k,0)+1
        full_avg = pw.loc[active].groupby("Player")["Points"].mean()
        pw["Change from overall career average"]=pw["Points"]-pw["Player"].map(full_avg)

        pw = pw.sort_values(["Team","Player","Year","Week"])
        stats={}
        for idx,row in pw.iterrows():
            key=(row["Team"], row["Player"])
            st=stats.get(key, {"weeks":0,"start_all":0,"bench_all":0,"season":None,"start_season":0,"bench_season":0,"bench_streak":0,"bench_streak_ex":0})
            if st["season"]!=row["Year"]:
                st["season"]=row["Year"]; st["start_season"]=0; st["bench_season"]=0
            st["weeks"]+=1
            is_starter = (row["Starter/Bench"]=="Starter")
            inactive = bool((row.get("Injury?") or False) or (row.get("Suspension?") or False) or (row.get("Bye?") or False))
            if is_starter:
                pw.at[idx,"Number of consecutive weeks on bench before start (if starter)"]=st["bench_streak"]
                pw.at[idx,"Number of consecutive weeks on bench before start excluding injury/bye (if starter)"]=st["bench_streak_ex"]
                st["bench_streak"]=0; st["bench_streak_ex"]=0
                st["start_all"]+=1; st["start_season"]+=1
            else:
                st["bench_all"]+=1; st["bench_season"]+=1
                st["bench_streak"]+=1
                if not inactive:
                    st["bench_streak_ex"]+=1
            pw.at[idx,"Number of weeks on team"]=st["weeks"]
            pw.at[idx,"Total weeks as team starter to that point"]=st["start_all"]
            pw.at[idx,"Total weeks on bench to that point"]=st["bench_all"]
            pw.at[idx,"Total weeks as team starter on that team this season"]=st["start_season"]
            pw.at[idx,"Total weeks on bench on that team this season"]=st["bench_season"]
            stats[key]=st

    # Team-week derived
    if not tw.empty:
        tw_cols=catalog.get("team-week", [])
        for c in tw_cols:
            if c not in tw.columns:
                tw[c]=None
        tw = tw.sort_values(["Year","Week","PF"], ascending=[True,True,False])
        tw["Highest score?"]=tw.groupby(["Year","Week"])["PF"].transform(lambda s: (s==s.max()).astype(int))
        tw["Lowest score?"]=tw.groupby(["Year","Week"])["PF"].transform(lambda s: (s==s.min()).astype(int))
        tw["Most efficient?"]=tw.groupby(["Year","Week"])["Efficiency"].transform(lambda s: (s==s.max()).astype(int))
        tw["Least efficient?"]=tw.groupby(["Year","Week"])["Efficiency"].transform(lambda s: (s==s.min()).astype(int))
        tw["Top half of league?"]=tw.groupby(["Year","Week"])["PF"].transform(lambda s: (s.rank(ascending=False, method="min") <= (len(s)/2)).astype(int))
        tw = tw.sort_values(["Team","Year","Week"])
        tw["Increase in points from previous week"]=tw.groupby(["Team"])["PF"].diff()
        # streaks
        tw["Win streak"]=None; tw["Loss streak"]=None
        for team, g in tw.groupby("Team"):
            wst=lst=0
            for idx,row in g.sort_values(["Year","Week"]).iterrows():
                if row["Win?"]==1: wst+=1; lst=0
                elif row["Win?"]==0: lst+=1; wst=0
                else: wst=lst=0
                tw.at[idx,"Win streak"]=wst
                tw.at[idx,"Loss streak"]=lst

    # Aggregates: player-year, player-all-time
    def align(df, cols):
        for c in cols:
            if c not in df.columns:
                df[c]=None
        return df[cols]

    player_year=pd.DataFrame()
    player_all=pd.DataFrame()
    if not pw.empty:
        py_cols=catalog.get("Player-year", [])
        pa_cols=catalog.get("Player-all-time", [])
        rows=[]
        for (player, year), g in pw.groupby(["Player","Year"]):
            rows.append({
                "Player": player,
                "Year": int(year),
                "Points": round(g["Points"].sum(),2),
                "Best week": round(g["Points"].max(),2),
                "Worst week": round(g["Points"].min(),2),
            })
        player_year=pd.DataFrame(rows)
        player_year=align(player_year, py_cols)
        rows=[]
        for player, g in pw.groupby(["Player"]):
            rows.append({
                "Player": player,
                "Points": round(g["Points"].sum(),2),
                "Best week": round(g["Points"].max(),2),
                "Worst week": round(g["Points"].min(),2),
            })
        player_all=pd.DataFrame(rows)
        player_all=align(player_all, pa_cols)

    team_year=pd.DataFrame()
    team_all=pd.DataFrame()
    if not tw.empty:
        ty_cols=catalog.get("team-year", [])
        ta_cols=catalog.get("team-all-time", [])
        rows=[]
        for (team, year), g in tw.groupby(["Team","Year"]):
            wins=(g["Win?"]==1).sum(); losses=(g["Win?"]==0).sum(); ties=(g["Win?"]==0.5).sum()
            games=int(wins+losses+ties)
            points=float(g["PF"].sum())
            maxpf=float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0).sum())
            rows.append({
                "Team": team,
                "Year": int(year),
                "Win %": round((wins+0.5*ties)/games,4) if games else None,
                "Record": f"{int(wins)}-{int(losses)}" + (f"-{int(ties)}" if ties else ""),
                "Points": round(points,2),
                "Avg points": round(points/games,2) if games else None,
                "Max PF": round(maxpf,2),
                "Avg max PF": round(maxpf/games,2) if games else None,
                "Efficiency": round(points/maxpf,4) if maxpf else None,
                "Number of transactions": int(pd.to_numeric(g["Number of transactions"], errors="coerce").fillna(0).sum()),
                "Number of trades": int(pd.to_numeric(g["Number of trades"], errors="coerce").fillna(0).sum()),
                "Amount of FAAB spent": round(pd.to_numeric(g["Amount of FAAB spent"], errors="coerce").fillna(0).sum(),2),
            })
        team_year=pd.DataFrame(rows)
        team_year=align(team_year, ty_cols)

        rows=[]
        for team, g in tw.groupby(["Team"]):
            wins=(g["Win?"]==1).sum(); losses=(g["Win?"]==0).sum(); ties=(g["Win?"]==0.5).sum()
            games=int(wins+losses+ties)
            points=float(g["PF"].sum())
            maxpf=float(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0).sum())
            rows.append({
                "Team": team,
                "Seasons": int(g["Year"].nunique()),
                "Win %": round((wins+0.5*ties)/games,4) if games else None,
                "Record": f"{int(wins)}-{int(losses)}" + (f"-{int(ties)}" if ties else ""),
                "Points": round(points,2),
                "Max PF": round(maxpf,2),
                "Efficiency": round(points/maxpf,4) if maxpf else None,
            })
        team_all=pd.DataFrame(rows)
        team_all=align(team_all, ta_cols)

    league_week=pd.DataFrame()
    league_year=pd.DataFrame()
    league_all=pd.DataFrame()
    if not tw.empty:
        lw_cols=catalog.get("league-week", [])
        ly_cols=catalog.get("league-year", [])
        la_cols=catalog.get("league-all-time", [])
        rows=[]
        for (year, week), g in tw.groupby(["Year","Week"]):
            rows.append({
                "Year": int(year),
                "Week": int(week),
                "PF": round(g["PF"].sum(),2),
                "PF Range": round(g["PF"].max()-g["PF"].min(),2),
                "Number of Injuries": int(pd.to_numeric(g["Number of Injuries"], errors="coerce").fillna(0).sum()),
                "Number of suspensions": int(pd.to_numeric(g["Number of suspensions"], errors="coerce").fillna(0).sum()),
                "Number of players on bye": int(pd.to_numeric(g["Number of players on bye"], errors="coerce").fillna(0).sum()),
            })
        league_week=pd.DataFrame(rows)
        league_week=align(league_week, lw_cols)

        rows=[]
        for year, g in tw.groupby(["Year"]):
            rows.append({
                "Year": int(year),
                "PF": round(g["PF"].sum(),2),
                "Max PF": round(pd.to_numeric(g["Max PF"], errors="coerce").fillna(0).sum(),2),
            })
        league_year=pd.DataFrame(rows)
        league_year=align(league_year, ly_cols)

        league_all=pd.DataFrame([{
            "PF": round(tw["PF"].sum(),2),
            "Years": int(tw["Year"].nunique()),
        }])
        league_all=align(league_all, la_cols)

    out_dir = repo_root/"exports"
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

    for fname, frame, plan_col in tables:
        cols = catalog.get(plan_col, [])
        if frame is None or frame.empty:
            frame = pd.DataFrame([{c: None for c in cols}]).iloc[0:0]
        out = align(frame, cols)
        require_columns(out, cols, fname.replace(".csv",""))
        out.to_csv(out_dir/fname, index=False)

    # Excel
    from openpyxl import Workbook
    wb=Workbook()
    wb.remove(wb.active)
    for csvf in sorted(out_dir.glob("*.csv")):
        ws=wb.create_sheet(title=csvf.stem[:31])
        d=pd.read_csv(csvf)
        ws.append(list(d.columns))
        for row in d.itertuples(index=False, name=None):
            ws.append(list(row))
    wb.save(out_dir/"LOTG_Stats.xlsx")

    import zipfile
    with zipfile.ZipFile(out_dir/"LOTG_Exports.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in out_dir.glob("*.csv"):
            z.write(f, arcname=f.name)
        z.write(out_dir/"LOTG_Stats.xlsx", arcname="LOTG_Stats.xlsx")
