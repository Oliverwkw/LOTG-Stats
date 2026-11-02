"""Grade the advice tools: walk-forward replays of start/sit, waivers and trades. Read-only.

The season forecast has its own backtest (`forecast.backtest`). This module
asks the same question of the three tools a manager acts on:

* `startsit` — every completed team-week since 2021 is replayed: the lineup
  `advise.start_sit` would have recommended on each basis (Sleeper projection,
  season PPG, last-3 PPG, and candidate rules), built only from what was known
  before that week's games, scored with what the players actually scored, next
  to the lineup the manager set. Regular-season wins are re-decided against the
  opponent's actual score.
* `waivers` — every completed waiver / free-agent add since 2021: the free
  agents ranked the way `advise.waivers` ranks them on the morning of the add,
  and whether the tool's top pick outscored the player actually added over the
  next N weeks (raw points, and points added to the team's hindsight-best
  lineup).
* `trades` — every two-team in-season trade with players in a completed
  season: `trade.run`'s before/after forecast, rewound to the week before the
  trade (leave-season-out calibration, backtest availability — the same rules
  `forecast.backtest` uses), against what the trade actually did to each side's
  best lineup over the rest of the regular season.

Point in time throughout: a week's recommendation reads only stats from earlier
weeks, Sleeper's projection for that week, the roster as it stood, and byes
(the schedule is known in advance). Nothing reads the week's own results,
`Injury?` flags or the build's projection columns (those zero players who did
not play, which is hindsight).

Data: the snapshot (rosters, lineups, transactions — 2021 on; 2020 has no
snapshot, so it is out), Sleeper's weekly NFL stats scored with each season's
league scoring (`advise._score`; equal to the matchup points, tests/test_advise),
Sleeper's weekly projections (the build's `.cache/projections/` copy when
present). Both are cached slim under `.cache/grade/`.

Known approximations, printed with every report:
* positions are Sleeper's current dictionary (position drift);
* taxi is not recorded weekly: a player on that season's final taxi squad who
  the team had not yet started that season is treated as unstartable;
* "out" for the PPG bases = no Sleeper projection row that week, or one under
  0.5 (how Sleeper's history marks a ruled-out player: of players who scored
  10+, 0.5-3% had no row), or a bye — the live tool reads the injury feed.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import advise as A
from . import inquiry as Q

POSITIONS = A.POSITIONS
OUT_PROJECTION = 0.5            # projections.MIN_PROJECTION: under this a listed player is ruled out
BASES = ("proj", "season", "recent")
# Candidate rules graded next to the tool's own three: `blend` = the mean of the
# projection and the season basis, `blend3` = the mean of all three.
CANDIDATES = ("blend", "blend3")
TRACK_FILE = "track_record.json"


# ---------------------------------------------------------------------------
# Data, cached slim
# ---------------------------------------------------------------------------
def cache_dir() -> Path:
    d = Q.repo_root() / ".cache" / "grade"
    d.mkdir(parents=True, exist_ok=True)
    return d


def seasons() -> List[int]:
    """Snapshot seasons with at least one finalized week (2021 on)."""
    return [y for y in Q.snapshot_seasons() if (Q.finalized_week(y) or 0) >= 1]


def last_done_week(year: int) -> int:
    return min(int(Q.finalized_week(year) or 0), Q.season_meta(year).last_week)


def _scoring(year: int) -> Dict[str, float]:
    try:
        return A.scoring(year)
    except FileNotFoundError:           # 2020: no snapshot; advise.season_points uses 2021's table too
        return A.scoring(min(Q.snapshot_seasons()))


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "LOTG-Stats-inquiry/1.0",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _cached_weeks(path: Path, weeks: Sequence[int], fetch, cols: Sequence[str]) -> pd.DataFrame:
    have = pd.read_csv(path, dtype={"pid": str}) if path.exists() else pd.DataFrame(columns=list(cols))
    missing = [w for w in weeks if w not in set(pd.to_numeric(have["week"]).astype(int))]
    if missing:
        with ThreadPoolExecutor(6) as ex:
            new = list(ex.map(fetch, missing))
        have = pd.concat([have] + [n for n in new if len(n)], ignore_index=True)
        have.to_csv(path, index=False)
    have["pid"] = have["pid"].astype(str)
    have["week"] = pd.to_numeric(have["week"]).astype(int)
    return have[have["week"].isin(list(weeks))].reset_index(drop=True)


@lru_cache(maxsize=None)
def weekly_points(year: int) -> pd.DataFrame:
    """Every player's league-scored points for each finalized week: pid, week, points, gp.
    A finished week is fetched once; an unfinished week is never cached."""
    done = last_done_week(year) if year in Q.snapshot_seasons() else 17
    table = _scoring(year)

    def fetch(w: int) -> pd.DataFrame:
        raw = _get_json(f"{A.SLEEPER}/v1/stats/nfl/regular/{year}/{w}") or {}
        rows = [(str(pid), w, round(A._score(s, table), 2), float(s.get("gp", 0) or 0))
                for pid, s in raw.items() if s.get("gp") or any(k in table for k in s)]
        return pd.DataFrame(rows, columns=["pid", "week", "points", "gp"])

    return _cached_weeks(cache_dir() / f"points_{year}.csv", range(1, done + 1), fetch,
                         ["pid", "week", "points", "gp"])


@lru_cache(maxsize=None)
def weekly_projections(year: int) -> pd.DataFrame:
    """Sleeper's weekly projection, league-scored: pid, week, proj. Read from the
    build's `.cache/projections/sleeper_{year}.csv` when it is there."""
    from . import projections as P
    weeks = range(1, Q.season_meta(year).last_week + 1)
    table = _scoring(year)
    build = Q.repo_root() / ".cache" / "projections" / f"sleeper_{year}.csv"
    if build.exists():
        df = pd.read_csv(build, dtype={"sleeper_id": str}, low_memory=False)
        out = pd.DataFrame({"pid": df["sleeper_id"].astype(str), "week": df["week"].astype(int),
                            "proj": P.score_stats(df, table).round(2).values})
        if set(weeks) <= set(out["week"]):
            return out[out["week"].isin(list(weeks))].reset_index(drop=True)

    def fetch(w: int) -> pd.DataFrame:
        df = P.fetch_sleeper_week(year, w)
        if df.empty:
            return pd.DataFrame(columns=["pid", "week", "proj"])
        return pd.DataFrame({"pid": df["sleeper_id"].astype(str), "week": w,
                             "proj": P.score_stats(df, table).round(2).values})

    return _cached_weeks(cache_dir() / f"proj_{year}.csv", weeks, fetch, ["pid", "week", "proj"])


@lru_cache(maxsize=None)
def _byes(year: int) -> Dict[int, frozenset]:
    """{week: NFL teams on bye}, from the schedule (known before the season)."""
    from .gametime import norm_team
    g = Q.schedule()
    if g.empty:
        return {}
    g = g[(g["season"] == year) & (g["game_type"].astype(str).str.upper() == "REG")]
    teams = {norm_team(t) for t in pd.concat([g["home_team"], g["away_team"]])}
    out = {}
    for w, gw in g.groupby("week"):
        playing = {norm_team(t) for t in pd.concat([gw["home_team"], gw["away_team"]])}
        out[int(w)] = frozenset(teams - playing)
    return out


@lru_cache(maxsize=None)
def _nfl_team_by_week(year: int) -> Dict[Tuple[str, int], str]:
    """(pid, week) -> NFL team that week, for rostered players (player_week's `NFL team`)."""
    from . import fast
    from .gametime import norm_team
    pw = fast.player_weeks()
    pw = pw[pw["Year"] == year]
    by_name = _pid_by_name()
    out = {}
    for name, wk, nfl in zip(pw["Player"], pw["Week"], pw["NFL team"]):
        pid = by_name.get(name)
        if pid and isinstance(nfl, str) and nfl and nfl.upper() not in ("NFL", "FA", "NAN"):
            out[(pid, int(wk))] = norm_team(nfl)
    return out


@lru_cache(maxsize=None)
def _pid_by_name() -> Dict[str, str]:
    players = Q.players()
    seen: Dict[str, Optional[str]] = {}
    for pid in _all_pids():
        n = players.name(pid)
        seen[n] = None if n in seen and seen[n] != pid else pid
    return {n: p for n, p in seen.items() if p}


@lru_cache(maxsize=None)
def _all_pids() -> Tuple[str, ...]:
    out = set()
    for y in Q.snapshot_seasons():
        for w in range(1, last_done_week(y) + 1):
            for row in Q.week(y, w).values():
                out.update(row.players)
    return tuple(sorted(out))


@lru_cache(maxsize=None)
def _positions() -> Dict[str, str]:
    d = Q._snap("sleeper_players_nfl.json")
    return {str(k): (v.get("position") or "").upper() for k, v in d.items()}


@lru_cache(maxsize=None)
def _final_taxi(year: int) -> Dict[int, frozenset]:
    try:
        rosters = Q._snap(f"season_{int(year)}/rosters.json")
    except FileNotFoundError:
        return {}
    return {int(r["roster_id"]): frozenset(str(p) for p in (r.get("taxi") or ())) for r in rosters}


@lru_cache(maxsize=None)
def _first_start(year: int) -> Dict[Tuple[int, str], int]:
    out: Dict[Tuple[int, str], int] = {}
    for w in range(1, last_done_week(year) + 1):
        for rid, row in Q.week(year, w).items():
            for p in row.starters:
                out.setdefault((rid, p), w)
    return out


def startable(year: int, week: int, rid: int, players: Iterable[str]) -> List[str]:
    """The roster's QB/RB/WR/TE minus (approximate) taxi: on the season's final
    taxi squad and not yet started by this team by `week`."""
    taxi, first, pos = _final_taxi(year).get(rid, frozenset()), _first_start(year), _positions()
    return [p for p in players if pos.get(p) in POSITIONS
            and not (p in taxi and first.get((rid, p), 99) > week)]


# ---------------------------------------------------------------------------
# What the tool knew before a week's games
# ---------------------------------------------------------------------------
@dataclass
class Known:
    """Everything the advice tools would have read on the morning of `week`."""
    year: int
    week: int
    G: pd.Series
    PPG: pd.Series
    L3: pd.Series
    prev: pd.Series
    proj: pd.Series                 # pid -> projection (only players Sleeper listed)
    bye: frozenset                  # pids on bye that week

    def values(self, pids: Sequence[str], basis: str) -> Dict[str, float]:
        """advise.value_column's rules on one basis, point in time."""
        idx = pd.Index(list(dict.fromkeys(pids)))
        proj = self.proj.reindex(idx)
        if basis == "proj":
            return dict(zip(idx, proj.fillna(0.0).where(~idx.isin(self.bye), 0.0)))
        if basis in ("blend", "blend3"):
            s = pd.Series(self.values(pids, "season"))
            parts = [proj, s] + ([pd.Series(self.values(pids, "recent"))] if basis == "blend3" else [])
            v = pd.concat(parts, axis=1).mean(axis=1).where(proj >= OUT_PROJECTION, 0.0)
            return dict(zip(idx, v.fillna(0.0).where(~idx.isin(self.bye), 0.0)))
        col = (self.PPG if basis == "season" else self.L3).reindex(idx)
        g = self.G.reindex(idx).fillna(0)
        prior = self.prev.reindex(idx).fillna(proj)
        v = col.where(g >= 3, pd.concat([col, prior], axis=1).mean(axis=1)).fillna(prior).fillna(0.0)
        # no projection row, or one under 0.5, is how Sleeper's history marks a player ruled out
        out = idx.isin(self.bye) | (proj.isna() | (proj < OUT_PROJECTION)).to_numpy()
        return dict(zip(idx, v.where(~out, 0.0)))


@lru_cache(maxsize=None)
def _season_ppg(year: int) -> pd.Series:
    p = weekly_points(year)
    p = p[p["gp"] > 0]
    return p.groupby("pid")["points"].mean().round(1)


def known(year: int, week: int, recent: int = 3) -> Known:
    p = weekly_points(year)
    played = p[(p["gp"] > 0) & (p["week"] < week)]
    g = played.groupby("pid")["points"]
    last = played[played["week"] >= week - recent].groupby("pid")["points"].mean()
    try:
        prev = _season_ppg(year - 1)
    except Exception:            # noqa: BLE001 — no prior season reachable: the projection stands in
        prev = pd.Series(dtype=float)
    pr = weekly_projections(year)
    pr = pr[pr["week"] == week].drop_duplicates("pid").set_index("pid")["proj"]
    teams = _nfl_team_by_week(year)
    off = _byes(year).get(week, frozenset())
    bye = frozenset(pid for (pid, w), t in teams.items() if w == week and t in off)
    return Known(year, week, g.size(), g.mean(), last, prev, pr, bye)


# ---------------------------------------------------------------------------
# Start/sit replay
# ---------------------------------------------------------------------------
def _pts(year: int, week: int) -> Dict[str, float]:
    p = weekly_points(year)
    p = p[p["week"] == week]
    return dict(zip(p["pid"], p["points"]))


def _lineup_points(picks, pts: Dict[str, float]) -> float:
    return float(sum(pts.get(p, 0.0) for _, p in picks if p))


@lru_cache(maxsize=None)
def _team_week() -> pd.DataFrame:
    from . import fast
    return fast.typed_sheet("team_week")


def replay_startsit(years: Optional[Sequence[int]] = None,
                    bases: Sequence[str] = BASES + CANDIDATES) -> pd.DataFrame:
    """One row per team-week: actual starters' points, each basis's recommended
    lineup's points, the hindsight-best lineup, the build's PF and Margin, and
    whether each basis would have flipped the result (regular season only)."""
    tw = _team_week()
    tw = tw.set_index(["Team", "Year", "Week"])
    rows = []
    for year in (years or seasons()):
        slots = A.lineup_slots(year)
        teams = Q.teams(year)
        meta = Q.season_meta(year)
        for week in range(1, last_done_week(year) + 1):
            kn, pts = known(year, week), _pts(year, week)
            for rid, row in Q.week(year, week).items():
                if row.matchup_id is None:
                    continue
                team = teams.get(rid, str(rid))
                pool = startable(year, week, rid, row.players)
                pos = {p: _positions()[p] for p in pool}
                starters = [p for p in row.starters if p and p != "0"]
                r = {"Team": team, "Year": year, "Week": week, "playoffs": week >= meta.playoff_week_start,
                     "actual": round(sum(pts.get(p, 0.0) for p in starters), 2),
                     "empty slots": len(slots) - len(starters)}
                for b in bases:
                    _, picks = A.best_lineup(kn.values(pool, b), pos, slots)
                    r[b] = round(_lineup_points(picks, pts), 2)
                    chosen = {p for _, p in picks if p}
                    r[f"{b}_changes"] = len(chosen - set(starters))
                opt, _ = A.best_lineup({p: pts.get(p, 0.0) for p in pool}, pos, slots)
                r["optimal"] = round(opt, 2)
                key = (team, year, week)
                if key in tw.index:
                    t = tw.loc[key]
                    t = t.iloc[0] if isinstance(t, pd.DataFrame) else t
                    r["PF"], r["Margin"], r["Win?"] = t.get("PF"), t.get("Margin"), t.get("Win?")
                rows.append(r)
    df = pd.DataFrame(rows)
    reg = ~df["playoffs"] & df["Margin"].notna()
    for b in bases:
        cf = df["Margin"] + (df[b] - df["actual"])
        won = df["Margin"] > 0
        df[f"{b}_flip"] = np.where(reg, np.where(~won & (cf > 0), 1, np.where(won & (cf < 0), -1, 0)), 0)
    return df


def reference_startsit(df: pd.DataFrame) -> str:
    """The build's own start/sit columns next to the replay, as a cross-check:
    the share of team-weeks with a starter the build's `Start/sit miss (Sleeper
    Projection)` calls against the projection (> 0), and the replay's share of
    team-weeks where the projection lineup differs from the set one. They
    measure the same thing two ways (the build's projection column is zeroed
    for players who did not play, and fills Sleeper's holes)."""
    from . import fast
    col = "Start/sit miss (Sleeper Projection)"
    pw = fast.typed_sheet("player_week")
    if col not in pw.columns:
        return ""
    pw = pw[(pw["Starter/Bench"] == "Starter") & pw["Year"].isin(df["Year"].unique())]
    miss = pd.to_numeric(pw[col], errors="coerce")
    tw_any = (miss > 0.005).groupby([pw["Team"], pw["Year"], pw["Week"]]).any()
    keys = pd.MultiIndex.from_frame(df[["Team", "Year", "Week"]])
    built = tw_any.reindex(keys).dropna()
    return (f"build's Start/sit miss (Sleeper Projection) > 0 for some starter in {100 * built.mean():.0f}% of "
            f"{len(built)} team-weeks; the replay's projection lineup differs from the set one in "
            f"{100 * (df['proj_changes'] > 0).mean():.0f}% (mean {df['proj_changes'].mean():.1f} players)")


def _mean_se(x: pd.Series) -> Tuple[float, float]:
    x = pd.to_numeric(x, errors="coerce").dropna()
    if len(x) < 2:
        return (float(x.mean()) if len(x) else float("nan")), float("nan")
    return float(x.mean()), float(x.std(ddof=1) / math.sqrt(len(x)))


def summarize_startsit(df: pd.DataFrame, by: Optional[str] = None,
                       bases: Sequence[str] = BASES + CANDIDATES) -> pd.DataFrame:
    """Per basis (and optionally per `by` group): weeks, mean points vs the set
    lineup (± standard error), share of weeks at least as good, net wins."""
    out = []
    groups = [(None, df)] if by is None else list(df.groupby(by))
    for key, g in groups:
        reg = g[~g["playoffs"]]
        for b in bases:
            d = g[b] - g["actual"]
            m, se = _mean_se(d)
            out.append({**({by: key} if by else {}), "basis": b, "weeks": len(g), "vs set pts/wk": round(m, 2),
                        "±se": round(se, 2), "≥ set %": round(100 * float((d >= -0.005).mean()), 1),
                        "wins +": int((reg[f"{b}_flip"] == 1).sum()), "wins -": int((reg[f"{b}_flip"] == -1).sum()),
                        "net wins": int(reg[f"{b}_flip"].sum()),
                        "set == rec %": round(100 * float((g[f"{b}_changes"] == 0).mean()), 1)})
        h = g["optimal"] - g["actual"]
        out.append({**({by: key} if by else {}), "basis": "hindsight best", "weeks": len(g),
                    "vs set pts/wk": round(float(h.mean()), 2), "±se": np.nan, "≥ set %": 100.0,
                    "wins +": np.nan, "wins -": np.nan, "net wins": np.nan, "set == rec %": np.nan})
    return pd.DataFrame(out)


def by_season_startsit(df: pd.DataFrame, bases: Sequence[str] = BASES + CANDIDATES) -> pd.DataFrame:
    """Mean points vs the set lineup per season and basis — how stable a rule is."""
    t = pd.DataFrame({b: (df[b] - df["actual"]) for b in bases})
    t["Year"] = df["Year"]
    return t.groupby("Year").mean().round(2)


def paired_test(df: pd.DataFrame, a: str, b: str) -> Dict[str, float]:
    """Basis a minus basis b per team-week: mean, se, t, seasons a won."""
    d = df[a] - df[b]
    m, se = _mean_se(d)
    per = d.groupby(df["Year"]).mean()
    return {"mean": round(m, 3), "se": round(se, 3), "t": round(m / se, 2) if se else float("nan"),
            "seasons a ahead": f"{int((per > 0).sum())}/{len(per)}", "n": int(len(d))}


# ---------------------------------------------------------------------------
# Waivers replay
# ---------------------------------------------------------------------------
@dataclass
class Add:
    year: int
    leg: int
    rid: int
    team: str
    pid: str
    kind: str
    bid: Optional[float]


def adds(years: Optional[Sequence[int]] = None) -> List[Add]:
    """Completed waiver / free-agent adds of QB/RB/WR/TE, from the snapshot."""
    out = []
    pos = _positions()
    for y in (years or seasons()):
        teams = Q.teams(y)
        for w in range(1, Q.season_meta(y).last_week + 1):
            try:
                tx = Q._snap(f"season_{y}/weeks/week_{w:02d}/transactions.json")
            except FileNotFoundError:
                continue
            for t in tx:
                if t.get("status") != "complete" or t.get("type") not in ("waiver", "free_agent"):
                    continue
                for pid, rid in (t.get("adds") or {}).items():
                    if pos.get(str(pid)) in POSITIONS:
                        bid = (t.get("settings") or {}).get("waiver_bid")
                        out.append(Add(y, int(t.get("leg") or w), int(rid), teams.get(int(rid), str(rid)),
                                       str(pid), t["type"], bid))
    return out


def _fa_pool(year: int, leg: int, kn: Known) -> List[str]:
    rostered = set()
    for row in Q.week(year, leg - 1).values():
        rostered.update(row.players)
    pos = _positions()
    cand = set(kn.proj[kn.proj > 0].index) | set(kn.G[kn.G > 0].index)
    return [p for p in cand if p not in rostered and pos.get(p) in POSITIONS]


RANKINGS = ("season", "proj", "recent", "blend")


def rank_free_agents(year: int, leg: int, rid: int, kn: Known, extra: Sequence[str] = (),
                     rankings: Sequence[str] = RANKINGS) -> pd.DataFrame:
    """advise.waivers's ranking on the morning of `leg`: each free agent's gain
    to the team's best lineup on each basis; `tool_rank` = the tool's order
    (+season, then +proj, then PPG)."""
    slots = A.lineup_slots(year)
    base_roster = startable(year, leg - 1, rid, Q.week(year, leg - 1)[rid].players)
    fa = [p for p in dict.fromkeys(_fa_pool(year, leg, kn) + list(extra)) if p not in base_roster]
    pos_all = _positions()
    out = pd.DataFrame({"pid": fa, "Pos": [pos_all.get(p) for p in fa]})
    for b in rankings:
        vals = kn.values(base_roster + fa, b)
        pos = {p: pos_all[p] for p in base_roster}
        base_v = {p: vals[p] for p in base_roster}
        base, picks = A.best_lineup(base_v, pos, slots)
        # a free agent only helps if he beats the weakest starter he is eligible to replace
        floor = min((base_v[p] for _, p in picks if p), default=0.0)
        gains = []
        for p in fa:
            v = vals[p]
            if v <= floor and all(p_ for _, p_ in picks):
                gains.append(0.0)
                continue
            base_v[p], pos[p] = v, pos_all[p]
            gains.append(A.best_lineup(base_v, pos, slots)[0] - base)
            del base_v[p], pos[p]
        out[f"+{b}"] = np.round(gains, 2)
    out["PPG"] = kn.PPG.reindex(out["pid"]).values
    out = out.sort_values(["+season", "+proj", "PPG"], ascending=False, na_position="last").reset_index(drop=True)
    out["tool_rank"] = np.arange(1, len(out) + 1)
    return out


def _realized(year: int, rid: int, leg: int, pid: str, horizon: int) -> Tuple[float, float, int]:
    """(raw points, points added to the team's hindsight-best lineup, weeks) over
    weeks leg..leg+horizon-1, against the team's roster before the add."""
    slots = A.lineup_slots(year)
    base_roster = [p for p in startable(year, leg - 1, rid, Q.week(year, leg - 1)[rid].players) if p != pid]
    pos_all = _positions()
    end = min(leg + horizon - 1, last_done_week(year))
    raw = gain = 0.0
    n = 0
    for w in range(leg, end + 1):
        pts = _pts(year, w)
        vals = {p: pts.get(p, 0.0) for p in base_roster}
        pos = {p: pos_all[p] for p in base_roster}
        b, _ = A.best_lineup(vals, pos, slots)
        vals[pid], pos[pid] = pts.get(pid, 0.0), pos_all.get(pid)
        gain += A.best_lineup(vals, pos, slots)[0] - b
        raw += pts.get(pid, 0.0)
        n += 1
    return raw, gain, n


def replay_waivers(years: Optional[Sequence[int]] = None, horizon: int = 4,
                   rankings: Sequence[str] = RANKINGS) -> pd.DataFrame:
    """One row per add (leg 2 on, at least one finalized week after it): the
    actual add's rank in the tool's list and its next-`horizon`-week outcome,
    next to the tool's top pick overall, its top pick at the added player's
    position, and each ranking's top pick."""
    rows = []
    knowns: Dict[Tuple[int, int], Known] = {}
    outcome: Dict[Tuple[int, int, int, str], Tuple[float, float, int]] = {}
    for ad in adds(years):
        if ad.leg < 2 or ad.leg > last_done_week(ad.year):
            continue
        try:
            Q.week(ad.year, ad.leg - 1)[ad.rid]
        except (FileNotFoundError, KeyError):
            continue
        kn = knowns.setdefault((ad.year, ad.leg), known(ad.year, ad.leg))
        ranked = rank_free_agents(ad.year, ad.leg, ad.rid, kn, extra=[ad.pid], rankings=rankings)

        def res(pid):
            k = (ad.year, ad.rid, ad.leg, pid)
            if k not in outcome:
                outcome[k] = _realized(ad.year, ad.rid, ad.leg, pid, horizon)
            return outcome[k]

        mine = ranked[ranked["pid"] == ad.pid]
        if mine.empty:          # already on the roster the week before (a drop and re-add)
            continue
        me = mine.iloc[0]
        a_raw, a_gain, n = res(ad.pid)
        r = {"Year": ad.year, "leg": ad.leg, "Team": ad.team, "kind": ad.kind, "bid": ad.bid,
             "added": Q.players().name(ad.pid), "Pos": me["Pos"], "tool rank": int(me["tool_rank"]),
             "pool": len(ranked), "weeks": n, "added raw": round(a_raw, 2), "added gain": round(a_gain, 2),
             "added +season": me["+season"]}
        top = ranked.iloc[0]
        t_raw, t_gain, _ = res(top["pid"])
        r.update({"top": Q.players().name(top["pid"]), "top raw": round(t_raw, 2), "top gain": round(t_gain, 2)})
        same = ranked[ranked["Pos"] == me["Pos"]].iloc[0]
        s_raw, s_gain, _ = res(same["pid"])
        r.update({"top same pos": Q.players().name(same["pid"]), "same raw": round(s_raw, 2),
                  "same gain": round(s_gain, 2), "same is added": same["pid"] == ad.pid})
        for b in rankings:
            pick = ranked.sort_values([f"+{b}", "PPG"], ascending=False).iloc[0]
            pr, pg, _ = res(pick["pid"])
            r[f"{b} top gain"], r[f"{b} top raw"] = round(pg, 2), round(pr, 2)
        rows.append(r)
    df = pd.DataFrame(rows)
    if len(df):
        df.to_csv(cache_dir() / f"waivers_h{horizon}.csv", index=False)
    return df


def summarize_waivers(df: pd.DataFrame, rankings: Sequence[str] = RANKINGS) -> pd.DataFrame:
    out = []
    for label, a, b in (("tool top vs added: lineup gain", "top gain", "added gain"),
                        ("tool top vs added: raw pts", "top raw", "added raw"),
                        ("tool top at added's position vs added: lineup gain", "same gain", "added gain"),
                        ("tool top at added's position vs added: raw pts", "same raw", "added raw")):
        d = df[a] - df[b]
        m, se = _mean_se(d)
        out.append({"comparison": label, "adds": len(d), "mean diff": round(m, 2), "±se": round(se, 2),
                    "tool ahead %": round(100 * float((d > 0).mean()), 1),
                    "tied %": round(100 * float((d.abs() < 0.005).mean()), 1)})
    for b in rankings:
        d = df[f"{b} top gain"] - df["added gain"]
        m, se = _mean_se(d)
        out.append({"comparison": f"rank on +{b} only: top vs added, lineup gain", "adds": len(d),
                    "mean diff": round(m, 2), "±se": round(se, 2),
                    "tool ahead %": round(100 * float((d > 0).mean()), 1),
                    "tied %": round(100 * float((d.abs() < 0.005).mean()), 1)})
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Trade replay
# ---------------------------------------------------------------------------
@dataclass
class PastTrade:
    year: int
    leg: int
    tid: str
    a: int                              # roster ids
    b: int
    a_gets: Tuple[str, ...]
    b_gets: Tuple[str, ...]
    picks: int
    faab: int


def past_trades(years: Optional[Sequence[int]] = None) -> List[PastTrade]:
    """Two-team trades moving at least one QB/RB/WR/TE, made during the regular
    season with at least two regular-season weeks still to play."""
    out = []
    pos = _positions()
    for y in (years or Q.completed_seasons()):
        meta = Q.season_meta(y)
        for w in range(1, meta.regular_season_weeks + 1):
            try:
                tx = Q._snap(f"season_{y}/weeks/week_{w:02d}/transactions.json")
            except FileNotFoundError:
                continue
            for t in tx:
                if t.get("type") != "trade" or t.get("status") != "complete" or len(t.get("roster_ids") or ()) != 2:
                    continue
                a, b = (int(x) for x in t["roster_ids"])
                ad = {str(p): int(r) for p, r in (t.get("adds") or {}).items() if pos.get(str(p)) in POSITIONS}
                if not ad:
                    continue
                leg = int(t.get("leg") or w)
                if leg < 2 or leg > meta.regular_season_weeks - 1:
                    continue
                out.append(PastTrade(y, leg, str(t.get("transaction_id")), a, b,
                                     tuple(p for p, r in ad.items() if r == a),
                                     tuple(p for p, r in ad.items() if r == b),
                                     len(t.get("draft_picks") or ()), len(t.get("waiver_budget") or ())))
    return out


def _roster_week_of(tr: PastTrade) -> Optional[int]:
    """The first week whose rosters show the trade done."""
    last = Q.season_meta(tr.year).regular_season_weeks
    for w in range(tr.leg, last + 1):
        try:
            wk = Q.week(tr.year, w)
        except FileNotFoundError:
            continue
        if all(p in wk[tr.a].players for p in tr.a_gets) and all(p in wk[tr.b].players for p in tr.b_gets):
            return w
    return None


def _realized_trade(tr: PastTrade, rw: int) -> Dict[int, Tuple[float, float, int]]:
    """{rid: (mean best-lineup pts/wk with the trade, without it, weeks)} over
    the rest of the regular season, each week's actual roster with the trade
    undone (players received removed, players sent put back)."""
    slots = A.lineup_slots(tr.year)
    pos_all = _positions()
    last = min(Q.season_meta(tr.year).regular_season_weeks, last_done_week(tr.year))
    res = {tr.a: [0.0, 0.0, 0], tr.b: [0.0, 0.0, 0]}
    for w in range(rw, last + 1):
        pts, wk = _pts(tr.year, w), Q.week(tr.year, w)
        for rid, got, sent in ((tr.a, tr.a_gets, tr.b_gets), (tr.b, tr.b_gets, tr.a_gets)):
            with_ = startable(tr.year, w, rid, wk[rid].players)
            without = [p for p in with_ if p not in got] + [p for p in sent if p not in with_]
            for i, roster in enumerate((with_, without)):
                vals = {p: pts.get(p, 0.0) for p in roster}
                res[rid][i] += A.best_lineup(vals, {p: pos_all.get(p) for p in roster}, slots)[0]
            res[rid][2] += 1
    return {rid: (v[0] / max(v[2], 1), v[1] / max(v[2], 1), v[2]) for rid, v in res.items()}


def _naive_delta(tr: PastTrade, rw: int, basis: str = "season") -> Dict[int, float]:
    """advise's lineup arithmetic as a baseline: Δ best lineup on a PPG basis at the trade."""
    import dataclasses
    # a bye in the trade week is not the trade's: value everyone as if playing
    kn = dataclasses.replace(known(tr.year, rw), bye=frozenset())
    slots = A.lineup_slots(tr.year)
    pos_all = _positions()
    wk = Q.week(tr.year, rw)
    out = {}
    for rid, got, sent in ((tr.a, tr.a_gets, tr.b_gets), (tr.b, tr.b_gets, tr.a_gets)):
        with_ = startable(tr.year, rw, rid, wk[rid].players)
        without = [p for p in with_ if p not in got] + [p for p in sent if p not in with_]
        tot = [A.best_lineup(kn.values(roster, basis), {p: pos_all.get(p) for p in roster}, slots)[0]
               for roster in (with_, without)]
        out[rid] = tot[0] - tot[1]
    return out


def replay_trades(years: Optional[Sequence[int]] = None, sims: int = 2000, seed: int = 20260807,
                  progress=None) -> pd.DataFrame:
    """One row per side of each past trade: the forecast's Δ (pts/wk, title %,
    playoffs %, expected wins) from trade.run's before/after, rewound to the
    week before the trade; the naive season-PPG lineup Δ; and the realized Δ in
    best-lineup pts/wk over the rest of the regular season. Cached per trade in
    `.cache/grade/trades.csv` (it takes ~4 s a trade)."""
    from . import forecast as F
    from . import trade as T
    path = cache_dir() / "trades.csv"
    have = pd.read_csv(path, dtype={"tid": str}) if path.exists() else pd.DataFrame()
    done = set(have["tid"]) if len(have) else set()
    trades = past_trades(years)
    rows = []
    calibs: Dict[int, object] = {}
    back = F._backtest_availability(F.AvailabilityModel())
    for i, tr in enumerate(trades):
        if tr.tid in done:
            continue
        rw = _roster_week_of(tr)
        if rw is None or rw > Q.season_meta(tr.year).regular_season_weeks - 1:
            continue
        if tr.year not in calibs:
            others = [y for y in Q.completed_seasons() if y != tr.year and y - 1 in Q.export_seasons()]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                calibs[tr.year] = F.calibrate(others)
        teams = Q.teams(tr.year)
        players = Q.players()
        undo = T.Trade(tr.year, rw, teams[tr.a], teams[tr.b],
                       give={p: players.name(p) for p in tr.a_gets}, get={p: players.name(p) for p in tr.b_gets})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with T._patched(undo, {}, ()):
                before = T._odds(F.forecast(tr.year, sims=sims, availability=back, calibration=calibs[tr.year],
                                            seed=seed, as_of_week=rw - 1)).set_index("team")
            with T._patched(None, {}, ()):
                after = T._odds(F.forecast(tr.year, sims=sims, availability=back, calibration=calibs[tr.year],
                                           seed=seed, as_of_week=rw - 1)).set_index("team")
        real = _realized_trade(tr, rw)
        naive = _naive_delta(tr, rw)
        for rid, got, sent in ((tr.a, tr.a_gets, tr.b_gets), (tr.b, tr.b_gets, tr.a_gets)):
            t = teams[rid]
            rows.append({"tid": tr.tid, "Year": tr.year, "leg": tr.leg, "roster week": rw, "Team": t,
                         "partner": teams[tr.b if rid == tr.a else tr.a],
                         "gets": ", ".join(players.name(p) for p in got) or "-",
                         "sends": ", ".join(players.name(p) for p in sent) or "-",
                         "picks": tr.picks, "faab": tr.faab,
                         "fc pts/wk": round(after.at[t, "projection"] - before.at[t, "projection"], 2),
                         "fc title %": round(after.at[t, "champion"] - before.at[t, "champion"], 2),
                         "fc playoffs %": round(after.at[t, "playoffs"] - before.at[t, "playoffs"], 2),
                         "fc exp wins": round(after.at[t, "expected_wins"] - before.at[t, "expected_wins"], 3),
                         "naive pts/wk": round(naive[rid], 2),
                         "real pts/wk": round(real[rid][0] - real[rid][1], 2), "real weeks": real[rid][2]})
        if progress:
            progress(i + 1, len(trades))
    if rows:
        have = pd.concat([have, pd.DataFrame(rows)], ignore_index=True) if len(have) else pd.DataFrame(rows)
        have.to_csv(path, index=False)
    if years and len(have):
        have = have[have["Year"].isin(list(years))]
    return have.reset_index(drop=True)


def _hit(pred: pd.Series, real: pd.Series, min_abs: float) -> Tuple[int, int, float]:
    m = pred.abs() >= min_abs
    hits = int((np.sign(pred[m]) == np.sign(real[m])).sum())
    n = int(m.sum())
    return hits, n, (100.0 * hits / n if n else float("nan"))


def summarize_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Direction hit rates (predicted sign = realized sign of best-lineup pts/wk),
    rank correlations, and the same for the naive baseline."""
    out = []
    real = df["real pts/wk"]
    for col, thr in (("fc pts/wk", 0.5), ("fc title %", 0.5), ("fc playoffs %", 1.0),
                     ("fc exp wins", 0.05), ("naive pts/wk", 0.5)):
        hits, n, pct = _hit(df[col], real, thr)
        lo, hi = _wilson(hits, n)
        rho = float(pd.concat([df[col], real], axis=1).corr(method="spearman").iloc[0, 1]) if len(df) > 2 else float("nan")
        out.append({"prediction": col, "|pred| at least": thr, "sides": n, "direction right": hits,
                    "hit %": round(pct, 1), "95% CI": f"{lo:.0f}-{hi:.0f}", "Spearman vs realized": round(rho, 2)})
    return pd.DataFrame(out)


def _wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if not n:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


# ---------------------------------------------------------------------------
# Track record line for advise / trade
# ---------------------------------------------------------------------------
def save_track_record(record: Dict[str, str]) -> Path:
    path = cache_dir() / TRACK_FILE
    path.write_text(json.dumps({**record, "written": time.strftime("%Y-%m-%d")}, indent=1))
    return path


# The headline of the last full run (2026-10-29, through 2026 week 7), used when
# this checkout has no `.cache/grade/track_record.json`. Refresh with
# `python scripts/grade_tools.py all --save` and paste the lines here.
FALLBACK = {
    "startsit": ("track record (2026-10-29): following the projection lineup vs the set one, +1.3 ± 0.5 pts/wk,"
                 " net -3 wins over 736 team-weeks 2021-2026; season/L3 lineups LOSE 2.9/5.4 pts/wk to the set one"),
    "waivers": ("track record (2026-10-29): the tool's top add vs the add made, next 4 wks, +0.7 ± 0.4 lineup pts"
                " (ahead 36%, tied 30%); at the same position -0.7 ± 0.4; 715 adds"),
    "trade": ("track record (2026-10-29): the forecast's pts/wk delta had the right sign on 84% (74-91) of 64 past"
              " trade sides (naive season-PPG lineup: 69%); title-odds sign 47% (noise when pts/wk moves < 0.5)"),
}


def track_record(tool: str) -> str:
    """One line on how far `tool` has been right, from the last grade_tools run
    (`.cache/grade/track_record.json`), else the committed headline."""
    try:
        rec = json.loads((cache_dir() / TRACK_FILE).read_text())
        if tool in rec:
            return f"{rec[tool]} [grade_tools {rec.get('written', '')}]"
    except (OSError, ValueError):
        pass
    return FALLBACK.get(tool, "")
