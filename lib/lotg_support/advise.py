"""Roster advice data in one call: start/sit, add/drop, and strategy. Read-only.

`trade` covers trades; this covers the other everyday questions. Each command
prints the data a good answer is built on, with its caveats — never the answer
itself. The judgement (news, matchups, the league's strategy guide in project
memory) stays with whoever is answering.

Sources, every one checked against the build where the build has the number:
- Sleeper's live league (rosters, lineups, taxi/IR) and its player dictionary
  (team, injury status, depth chart) — the same API the build snapshots;
- Sleeper's weekly NFL stats for EVERY player, scored with this league's own
  scoring table from the snapshot's league.json (free agents included, which the
  exports cannot do: player_week only has rostered players). Reconciled against
  player_week `Points` in tests/test_advise.py;
- Sleeper's weekly projections, scored the same way;
- the forecast (title / playoff odds, with the trade module's calibration cache).

Network results are cached under `.cache/sleeper/`: finished weeks forever, the
current week and the player dictionary for a few hours.
"""
from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import inquiry as Q
from . import live

POSITIONS = ("QB", "RB", "WR", "TE")
SLEEPER = "https://api.sleeper.app"


# ---------------------------------------------------------------------------
# Fetching, cached
# ---------------------------------------------------------------------------
def _cache_dir():
    d = Q.repo_root() / ".cache" / "sleeper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_cached(url: str, name: str, max_age_h: Optional[float]):
    """GET json with an on-disk cache. max_age_h=None: never refetch."""
    path = _cache_dir() / name
    if path.exists() and (max_age_h is None or time.time() - path.stat().st_mtime < max_age_h * 3600):
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": "LOTG-Stats-inquiry/1.0",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        if path.exists():           # stale beats nothing; the caller states the as-of
            return json.loads(path.read_text())
        raise
    path.write_text(json.dumps(data))
    return data


def players_dict() -> Dict[str, dict]:
    """Sleeper's player dictionary, refreshed every 6 h."""
    return _get_cached(f"{SLEEPER}/v1/players/nfl", "players_nfl.json", 6)


def scoring(year: int) -> Dict[str, float]:
    return {k: float(v) for k, v in Q._snap(f"season_{int(year)}/league.json")["scoring_settings"].items()}


def _score(stats: dict, table: Dict[str, float]) -> float:
    return float(sum(float(v) * table[k] for k, v in stats.items()
                     if k in table and isinstance(v, (int, float))))


def week_points(year: int, week: int) -> pd.DataFrame:
    """Every player's league-scored points for one NFL week (player_id, points, gp)."""
    done = (Q.finalized_week(year) or 0) >= week
    raw = _get_cached(f"{SLEEPER}/v1/stats/nfl/regular/{year}/{week}", f"stats_{year}_{week:02d}.json",
                      None if done else 2)
    table = scoring(year)
    rows = [{"pid": str(pid), "week": int(week), "points": round(_score(s, table), 2),
             "gp": float(s.get("gp", 0) or 0)} for pid, s in (raw or {}).items()]
    return pd.DataFrame(rows, columns=["pid", "week", "points", "gp"])


def season_points(year: int) -> pd.DataFrame:
    """Season totals (one call), league-scored: pid, points, gp, ppg."""
    done = year < max(Q.export_seasons())
    raw = _get_cached(f"{SLEEPER}/v1/stats/nfl/regular/{year}", f"stats_{year}_season.json",
                      None if done else 12)
    table = scoring(min(year, max(Q.export_seasons())) if year >= 2021 else 2021)
    rows = []
    for pid, s in (raw or {}).items():
        gp = float(s.get("gp", 0) or 0)
        if gp > 0:
            pts = _score(s, table)
            rows.append({"pid": str(pid), "points": round(pts, 2), "gp": gp, "ppg": round(pts / gp, 1)})
    return pd.DataFrame(rows, columns=["pid", "points", "gp", "ppg"])


def week_projection(year: int, week: int) -> pd.Series:
    """Sleeper's projection for every skill player, league-scored: {pid: points}."""
    from . import projections as P
    path = _cache_dir() / f"proj_{year}_{week:02d}.csv"
    if path.exists() and time.time() - path.stat().st_mtime < 3 * 3600:
        df = pd.read_csv(path, dtype={"sleeper_id": str})
    else:
        df = P.fetch_sleeper_week(year, week)
        if len(df):
            df.to_csv(path, index=False)
    if df.empty:
        return pd.Series(dtype=float)
    return pd.Series(P.score_stats(df, scoring(year)).round(2).values, index=df["sleeper_id"].astype(str))


# ---------------------------------------------------------------------------
# The league right now
# ---------------------------------------------------------------------------
@dataclass
class League:
    year: int
    week: int                       # the upcoming / current NFL week
    done: int                       # last finalized week
    teams: Dict[int, str]           # roster_id -> team name
    owner: Dict[str, str]           # pid -> team
    slot: Dict[str, str]            # pid -> starter / bench / taxi / IR
    budget_left: Dict[str, int]
    fetched: str


def league_now() -> League:
    lid = live.league_id()
    with ThreadPoolExecutor(4) as ex:
        st, ro = ex.submit(live.nfl_state), ex.submit(live._get, f"/league/{lid}/rosters")
        us, lg = ex.submit(live._get, f"/league/{lid}/users"), ex.submit(live._get, f"/league/{lid}")
        state, rosters, users, league = st.result(), ro.result(), us.result(), lg.result()
    year = int(state.get("league_season") or state["season"])
    week = int(state.get("display_week") or state["week"])
    teams = Q.teams(year)
    budget = int((league.get("settings") or {}).get("waiver_budget") or 0)
    owner, slot, left = {}, {}, {}
    for r in rosters:
        t = teams.get(int(r["roster_id"]), str(r["roster_id"]))
        taxi, res, start = set(r.get("taxi") or ()), set(r.get("reserve") or ()), set(r.get("starters") or ())
        for pid in r.get("players") or ():
            owner[str(pid)] = t
            slot[str(pid)] = ("taxi" if pid in taxi else "IR" if pid in res else
                              "starter" if pid in start else "bench")
        left[t] = budget - int((r.get("settings") or {}).get("waiver_budget_used") or 0)
    return League(year, week, Q.finalized_week(year) or 0, teams, owner, slot, left,
                  f"{live.now_et():%a %Y-%m-%d %H:%M} ET")


def _opponents(year: int) -> Dict[Tuple[int, str], str]:
    g = Q.schedule()
    g = g[(g["season"] == year) & (g["game_type"] == "REG")] if "game_type" in g.columns else g[g["season"] == year]
    out = {}
    for w, h, a in zip(g["week"], g["home_team"], g["away_team"]):
        out[(int(w), _nt(h))] = f"vs {_nt(a)}"
        out[(int(w), _nt(a))] = f"@ {_nt(h)}"
    return out


def _nt(t) -> str:
    from .gametime import norm_team
    return norm_team(t)


def board(lg: League, recent: int = 3) -> pd.DataFrame:
    """One row per QB/RB/WR/TE who is rostered or active on an NFL team:
    owner and slot, this season's games / PPG / last-`recent` PPG, last
    season's PPG, Sleeper's projection for the upcoming week, injury status,
    depth chart, bye and opponent."""
    pdct = players_dict()
    weeks = list(range(1, lg.done + 1))
    with ThreadPoolExecutor(8) as ex:
        wk = list(ex.map(lambda w: week_points(lg.year, w), weeks))
        prev_f = ex.submit(season_points, lg.year - 1)
        proj_f = ex.submit(week_projection, lg.year, lg.week)
        prev, proj = prev_f.result(), proj_f.result()
    pts = pd.concat(wk) if wk else pd.DataFrame(columns=["pid", "week", "points", "gp"])
    played = pts[pts["gp"] > 0]
    g = played.groupby("pid").agg(G=("points", "size"), PPG=("points", "mean"))
    last = played[played["week"] > lg.done - recent].groupby("pid")["points"].mean().rename("last")
    opp = _opponents(lg.year)
    sched = live._schedule()
    rows = []
    for pid, m in pdct.items():
        pos = (m.get("position") or "").upper()
        if pos not in POSITIONS:
            continue
        team = m.get("team") or ""
        if pid not in lg.owner and (not team or not m.get("active", True)):
            continue
        rows.append({
            "pid": pid, "Player": m.get("full_name") or f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(),
            "Pos": pos, "NFL": team or "FA", "Age": m.get("age"),
            "Owner": lg.owner.get(pid, "FA"), "Slot": lg.slot.get(pid, ""),
            "G": int(g["G"].get(pid, 0)), "PPG": round(float(g["PPG"].get(pid, np.nan)), 1),
            f"L{recent}": round(float(last.get(pid, np.nan)), 1),
            f"{lg.year - 1} PPG": float(prev.set_index("pid")["ppg"].get(pid, np.nan)) if len(prev) else np.nan,
            f"proj wk{lg.week}": float(proj.get(pid, np.nan)),
            "inj": m.get("injury_status") or "",
            "depth": f"{m.get('depth_chart_position') or ''}{m.get('depth_chart_order') or ''}",
            "opp": opp.get((lg.week, _nt(team)), "BYE" if team else ""),
            "kick": (lambda k: f"{k:%a %H:%M}" if k else "")(sched.team_kickoff(lg.year, lg.week, team)
                                                          if (sched and team) else None),
        })
    return pd.DataFrame(rows)


def dvp(lg: League, top: int = 2) -> pd.DataFrame:
    """Points allowed by each NFL defense to each position this season: the
    mean, per game, of the top-`top` scorers at that position against it
    (what fantasy starters there scored). rank 1 = most allowed."""
    pdct = players_dict()
    g = Q.schedule()
    g = g[g["season"] == lg.year]
    opp = {}
    for w, h, a in zip(g["week"], g["home_team"], g["away_team"]):
        opp[(int(w), _nt(h))], opp[(int(w), _nt(a))] = _nt(a), _nt(h)
    rows = []
    for w in range(1, lg.done + 1):
        d = week_points(lg.year, w)
        d = d[d["gp"] > 0]
        for pid, p in zip(d["pid"], d["points"]):
            m = pdct.get(pid) or {}
            pos, team = (m.get("position") or "").upper(), m.get("team") or ""
            if pos in POSITIONS and team and (w, _nt(team)) in opp:
                rows.append((w, opp[(w, _nt(team))], pos, p))
    df = pd.DataFrame(rows, columns=["week", "defense", "Pos", "points"])
    if df.empty:
        return df
    topn = df.sort_values("points", ascending=False).groupby(["week", "defense", "Pos"]).head(top)
    out = topn.groupby(["defense", "Pos"])["points"].mean().rename("allowed").reset_index()
    out["rank"] = out.groupby("Pos")["allowed"].rank(ascending=False, method="min").astype(int)
    return out


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------
def lineup_slots(year: int) -> List[str]:
    """The league's starting slots that season, from league.json."""
    pos = Q._snap(f"season_{int(year)}/league.json")["roster_positions"]
    return [p for p in pos if p not in ("BN", "IR", "TAXI")]


_ELIGIBLE = {"QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
             "FLEX": {"RB", "WR", "TE"}, "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
             "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}}


def best_lineup(values: Dict[str, float], pos: Dict[str, str], slots: Sequence[str]
                ) -> Tuple[float, List[Tuple[str, str]]]:
    """Optimal (total, [(slot, pid)]): fixed slots first, then the narrowest
    flex outward. Exact for nested slot eligibility (QB/RB/WR/TE ⊂ FLEX ⊂
    SUPER_FLEX), which is this league's lineup; checked against
    lineup.compute_optimal_lineup in tests/test_advise.py."""
    order = sorted(range(len(slots)), key=lambda i: len(_ELIGIBLE.get(slots[i], set(POSITIONS))))
    free = sorted((p for p in values if pd.notna(values[p])), key=lambda p: -values[p])
    used, picks = set(), [None] * len(slots)
    for i in order:
        elig = _ELIGIBLE.get(slots[i], set(POSITIONS))
        for p in free:
            if p not in used and pos.get(p) in elig:
                used.add(p)
                picks[i] = p
                break
    total = float(sum(values[p] for p in picks if p))
    return total, [(slots[i], picks[i]) for i in range(len(slots))]


def value_column(b: pd.DataFrame, lg: League, basis: str) -> pd.Series:
    """Per-player weekly value on a stated basis:
    proj   — Sleeper's projection for the upcoming week (0 if on bye / out);
    season — this season's PPG (last season's where he has no games);
    recent — the last-3 PPG, falling back like season."""
    if basis == "proj":
        return b[f"proj wk{lg.week}"].fillna(0.0)
    col = "PPG" if basis == "season" else "L3"
    prior = b[f"{lg.year - 1} PPG"].fillna(b[f"proj wk{lg.week}"])
    # fewer than 3 games is a small sample: average it with last season / the projection
    small = b["G"] < 3
    v = b[col].where(~small, pd.concat([b[col], prior], axis=1).mean(axis=1)).fillna(prior).fillna(0.0)
    out = (b["opp"] == "BYE") | b["inj"].isin(["Out", "IR", "PUP", "Sus", "NA"])
    return v.where(~out, 0.0)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def team_frame(b: pd.DataFrame, team: str) -> pd.DataFrame:
    return b[b["Owner"] == team].copy()


def start_sit(b: pd.DataFrame, lg: League, team: str) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """The set lineup next to the best lineup on three bases (projection,
    season PPG, last 3). Rows are every startable player (taxi / IR cannot
    start)."""
    t = team_frame(b, team)
    t = t[~t["Slot"].isin(["taxi", "IR"])]
    slots = lineup_slots(lg.year)
    pos = dict(zip(t["pid"], t["Pos"]))
    totals, chosen = {}, {}
    for basis in ("proj", "season", "recent"):
        vals = dict(zip(t["pid"], value_column(t, lg, basis)))
        tot, picks = best_lineup(vals, pos, slots)
        totals[basis] = round(tot, 1)
        chosen[basis] = {p: s for s, p in picks if p}
    cur = dict(zip(t["pid"], value_column(t, lg, "proj")))
    totals["set lineup (proj)"] = round(sum(cur[p] for p in t[t["Slot"] == "starter"]["pid"]), 1)
    t["set"] = np.where(t["Slot"] == "starter", "START", "")
    for basis in ("proj", "season", "recent"):
        t[f"best:{basis}"] = t["pid"].map(chosen[basis]).fillna("")
    t["flag"] = [("start? " if r.set == "" and r["best:proj"] else "sit? " if r.set and not r["best:proj"] else "")
                 + ("BYE " if r.opp == "BYE" else "") + (r.inj + " " if r.inj else "")
                 for _, r in t.iterrows()]
    cols = ["Player", "Pos", "NFL", "opp", "kick", "inj", "depth", "G", "PPG", "L3", f"{lg.year - 1} PPG",
            f"proj wk{lg.week}", "set", "best:proj", "best:season", "best:recent", "flag"]
    t = t.sort_values(["Pos", f"proj wk{lg.week}"], ascending=[True, False])
    return t[cols], totals


def waivers(b: pd.DataFrame, lg: League, team: str, n: int = 15, positions: Optional[Sequence[str]] = None
            ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Free agents ranked by what they add to `team`'s best lineup (weekly
    points, on the projection and on season PPG), and the team's drop
    candidates (least lineup value lost; taxi excluded)."""
    t = team_frame(b, team)
    t = t[~t["Slot"].isin(["taxi", "IR"])]
    slots = lineup_slots(lg.year)
    fa = b[(b["Owner"] == "FA")]
    if positions:
        fa = fa[fa["Pos"].isin([p.upper() for p in positions])]
    # pre-filter to the plausible: anyone with a projection or games this year
    fa = fa[(fa[f"proj wk{lg.week}"].fillna(0) > 0) | (fa["G"] > 0)]
    base, gains = {}, {}
    for basis in ("proj", "season"):
        vals = dict(zip(t["pid"], value_column(t, lg, basis)))
        pos = dict(zip(t["pid"], t["Pos"]))
        base[basis] = best_lineup(vals, pos, slots)[0]
        fv = dict(zip(fa["pid"], value_column(fa, lg, basis)))
        fp = dict(zip(fa["pid"], fa["Pos"]))
        g = {}
        for pid, v in fv.items():
            vals[pid], pos[pid] = v, fp[pid]
            g[pid] = best_lineup(vals, pos, slots)[0] - base[basis]
            del vals[pid], pos[pid]
        gains[basis] = g
    fa = fa.assign(**{"+lineup (proj)": fa["pid"].map(gains["proj"]).round(1),
                      "+lineup (season)": fa["pid"].map(gains["season"]).round(1)})
    fa = fa.sort_values(["+lineup (season)", "+lineup (proj)", "PPG"], ascending=False)
    keep = ["Player", "Pos", "NFL", "Age", "inj", "depth", "G", "PPG", "L3", f"{lg.year - 1} PPG",
            f"proj wk{lg.week}", "opp", "+lineup (proj)", "+lineup (season)"]
    top = fa.head(n)[keep]
    # drop candidates: removing whom costs the least
    loss = []
    vals_s = dict(zip(t["pid"], value_column(t, lg, "season")))
    pos = dict(zip(t["pid"], t["Pos"]))
    for pid in t["pid"]:
        v = vals_s.pop(pid)
        loss.append(base["season"] - best_lineup(vals_s, pos, slots)[0])
        vals_s[pid] = v
    drops = t.assign(**{"-lineup (season)": np.round(loss, 1)}).sort_values(["-lineup (season)", "PPG"])
    drops = drops[["Player", "Pos", "NFL", "Age", "Slot", "inj", "depth", "G", "PPG", "L3",
                   f"{lg.year - 1} PPG", f"proj wk{lg.week}", "-lineup (season)"]].head(8)
    return top, drops


def position_strength(b: pd.DataFrame, lg: League) -> pd.DataFrame:
    """Each team's startable strength by position: the sum of its top-k
    season-PPG players there (k = how many that position usually starts:
    QB 2 in superflex, RB 3, WR 4, TE 1), and the league rank (1 = best)."""
    k = {"QB": 2, "RB": 3, "WR": 4, "TE": 1}
    r = b[(b["Owner"] != "FA") & (~b["Slot"].isin(["taxi"]))].copy()
    r["v"] = value_column(r.assign(opp=""), lg, "season")
    rows = []
    for (team, pos), g in r.groupby(["Owner", "Pos"]):
        rows.append({"team": team, "Pos": pos, "top-k PPG": round(g["v"].nlargest(k[pos]).sum(), 1)})
    df = pd.DataFrame(rows)
    df["rank"] = df.groupby("Pos")["top-k PPG"].rank(ascending=False, method="min").astype(int)
    out = df.pivot(index="team", columns="Pos", values=["top-k PPG", "rank"])
    return out.astype({c: int for c in out.columns if c[0] == "rank"})


def age_profile(b: pd.DataFrame) -> pd.DataFrame:
    r = b[b["Owner"] != "FA"].copy()
    r["Age"] = pd.to_numeric(r["Age"], errors="coerce")
    return r.groupby(["Owner", "Pos"])["Age"].mean().round(1).unstack()


def picks_owned(year: int, lg: League) -> pd.DataFrame:
    """Future rookie picks each team holds (own picks minus traded, plus acquired)."""
    traded = Q._snap(f"season_{int(year)}/traded_picks.json")
    rounds = int((Q._snap(f"season_{int(year)}/league.json").get("settings") or {}).get("draft_rounds") or 4)
    seasons = sorted({int(t["season"]) for t in traded} | {year + 1, year + 2, year + 3})
    hold = {(s, r, rid): rid for s in seasons for r in range(1, rounds + 1) for rid in lg.teams}
    for t in traded:
        hold[(int(t["season"]), int(t["round"]), int(t["roster_id"]))] = int(t["owner_id"])
    rows = [{"team": lg.teams[o], "season": s, "round": r, "original": lg.teams[rid]}
            for (s, r, rid), o in hold.items() if s > year]
    df = pd.DataFrame(rows)
    return df.groupby(["team", "season"])["round"].apply(lambda x: " ".join(str(v) for v in sorted(x))).unstack()
