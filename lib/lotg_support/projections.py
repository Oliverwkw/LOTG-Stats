"""Projections: Sleeper, Claude and Enhanced, per player-week.

Three pre-kickoff projections of a player's points, each in the league's own
scoring for that season [per user, 2026-10-07]:

* **Claude** — the pre-kickoff expected points `lotg_support.boldness` computes
  (recency-weighted NFL games, that season's scoring, the LOTG rookie-slot
  prior, the next-man-up cuff lift). Called the Claude projections everywhere
  outside that module so they are never confused with the Boldness stat.
* **Sleeper** — Sleeper's own weekly projection (Rotowire), what the league sees
  live. Where Sleeper has none, or a weird one (a row with no projected stats,
  e.g. adp only — Tom Brady's whole 2021 — or ~0 for a player who was not ruled
  out), it falls back to the Enhanced model fitted WITHOUT Sleeper, then to
  Claude.
* **Enhanced** — the most accurate broad-use projection found [see the
  2026-10-07 entries in plan/MASTER_TODO.md]: a least-squares model on √points
  over four projections (Sleeper, ESPN, FantasyPros consensus, Claude; a missing
  one reads the average of the rest) plus their √ values and disagreement, the
  Vegas implied team total / opponent total / spread, the player's record
  against the projections, the opponent's record against his position, home,
  dome and wind; back to points by smearing. 2020-25 held out: MAE 6.307,
  RMSE 8.008, bias 0.00; team-week total RMSE 24.2 (Claude alone 28.0).
  Refit on completed seasons only: each completed season is predicted by a
  model fitted on the OTHER completed seasons, the current season by one fitted
  on all of them, so a season's own results never feed its projections. With
  no outside source at all, Enhanced = Claude.

A player KNOWN OUT that week (flagged bye / injured / suspended and scored 0)
projects 0 under all three. That is also why no projection can stand in for an
"expected if healthy" baseline [per user: the out-week trap].

So does a player who DID NOT PLAY (`did_not_play`) [per user, 2026-10-07]: his
NFL team's game was played and its stats are in, and he has no stat line and
no offensive snap and scored 0 — a healthy scratch or a dressed backup who
never got on the field (Fernando Mendoza 2026, LV's third quarterback,
projected 14-17 a week on his draft-slot prior; Desmond Ridder 2022's 13
weeks behind Mariota). Only the published columns are zeroed: the models
still fit on the same rows. The voided 2022 week 17 Bills at Bengals game
(`struck_games`) never counts — Ja'Marr Chase started it and keeps his
projection [per user].

Sources are fetched by the build and cached as slim per-season CSVs under
`.cache/projections/` with `external`'s freshness rules: a completed season is
fetched once, the current one again when its copy is over a week old, and a
failed download keeps the copy on disk (never a 0).
"""
from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests

from lotg_support import external as X

POSITIONS: Tuple[str, ...] = ("QB", "RB", "WR", "TE")
NAMES: Tuple[str, ...] = ("Sleeper", "Claude", "Enhanced")
REG_WEEKS = range(1, 19)

SLEEPER_URL = ("https://api.sleeper.com/projections/nfl/{season}/{week}"
               "?season_type=regular&position%5B%5D={pos}")
ESPN_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
            "/segments/0/leaguedefaults/3?view=kona_player_info&scoringPeriodId={week}")
FPECR_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_fpecr.parquet"

# ESPN stat ids -> Sleeper stat keys (re-scores ESPN's own PPR total within 0.05
# on 96% of projections; the rest are return TDs this league does not score).
ESPN_STATS = {"3": "pass_yd", "4": "pass_td", "19": "pass_2pt", "20": "pass_int",
              "24": "rush_yd", "25": "rush_td", "26": "rush_2pt", "42": "rec_yd",
              "43": "rec_td", "44": "rec_2pt", "53": "rec", "68": "fum", "72": "fum_lost"}
# The projected stats kept from Sleeper: every offensive stat a season of this
# league has scored (+ any bonus_*), so the cache is a few hundred KB a season.
SLEEPER_KEEP = frozenset({"pass_yd", "pass_td", "pass_int", "pass_2pt", "rush_yd", "rush_td",
                          "rush_2pt", "rec", "rec_yd", "rec_td", "rec_2pt", "fum", "fum_lost",
                          "fum_rec_td", "st_td"})
# A projection this small for a player who was not ruled out is a data hole, not
# a forecast (Sleeper's adp-only rows score 0).
MIN_PROJECTION = 0.5


def _cache_dir(cfg: X.ExternalConfig) -> Path:
    d = Path(cfg.cache_dir) / "projections"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_json(url: str, timeout: int, headers: Optional[dict] = None):
    """GET + JSON, direct first then via the environment's proxy settings."""
    last = None
    for trust_env in (False, True):
        try:
            s = requests.Session()
            s.trust_env = trust_env
            kw = {"timeout": timeout, "headers": headers or {}}
            if not trust_env:
                kw["proxies"] = {"http": None, "https": None}
            r = s.get(url, **kw)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # pragma: no cover - network
            last = e
    raise last


def _needs_fetch(path: Path, season: int, current_season: int, force: bool) -> bool:
    """A completed season is fetched once; the current one when stale."""
    have = path.exists() and path.stat().st_size > 0
    if force:
        return True
    if int(season) < int(current_season):
        return not have
    return X.cache_is_stale(path)


def _write(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".part")
    df.to_csv(tmp, index=False)
    tmp.replace(path)
    X.record_fetch(path)


# ---------------------------------------------------------------------------
# Sleeper
# ---------------------------------------------------------------------------
def fetch_sleeper_week(season: int, week: int, timeout: int = 60) -> pd.DataFrame:
    """One week of Sleeper projections, every skill position: player_id + the
    projected stats the league scores. A row with no projected points (adp only
    — Tom Brady's 2021) is NOT kept: it is no projection, never a 0."""
    rows = []
    for pos in POSITIONS:
        for r in _get_json(SLEEPER_URL.format(season=season, week=week, pos=pos), timeout) or []:
            stats = r.get("stats") or {}
            if "pts_ppr" not in stats:
                continue
            rec = {k: v for k, v in stats.items() if isinstance(v, (int, float))
                   and (k in SLEEPER_KEEP or k.startswith("bonus_"))}
            rec.update(season=int(season), week=int(week), sleeper_id=str(r.get("player_id")),
                       has_projection=True)
            rows.append(rec)
    return pd.DataFrame(rows)


def load_sleeper(cfg: X.ExternalConfig, season: int, current_season: int,
                 weeks: Iterable[int] = REG_WEEKS, force: bool = False) -> pd.DataFrame:
    path = _cache_dir(cfg) / f"sleeper_{int(season)}.csv"
    if _needs_fetch(path, season, current_season, force):
        try:
            frames = [fetch_sleeper_week(season, w, cfg.timeout_seconds) for w in weeks]
            df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
            if not df.empty:
                _write(df, path)
        except Exception:
            if not (path.exists() and path.stat().st_size > 0):
                return pd.DataFrame()
    return X.read_cached_csv(path, dtype={"sleeper_id": str}) if path.exists() else pd.DataFrame()


# ---------------------------------------------------------------------------
# ESPN
# ---------------------------------------------------------------------------
def fetch_espn_week(season: int, week: int, timeout: int = 90) -> pd.DataFrame:
    """One week of ESPN projections (statSourceId 1) for QB/RB/WR/TE slots, as
    Sleeper stat keys."""
    flt = {"players": {"filterSlotIds": {"value": [0, 2, 4, 6]}, "limit": 1500,
                       "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                       "filterStatsForTopScoringPeriodIds": {
                           "value": 1, "additionalValue": [f"11{int(season)}{int(week)}"]}}}
    blob = _get_json(ESPN_URL.format(season=season, week=week), timeout,
                     headers={"X-Fantasy-Filter": json.dumps(flt)})
    rows = []
    for p in (blob or {}).get("players", []):
        pl = p.get("player") or {}
        for s in pl.get("stats", []):
            if s.get("statSourceId") != 1 or s.get("scoringPeriodId") != int(week):
                continue
            rec = {ESPN_STATS[k]: v for k, v in (s.get("stats") or {}).items() if k in ESPN_STATS}
            if not any(v for v in rec.values()):
                continue        # ESPN projects him to do nothing (out): no projection, never 0
            rec.update(season=int(season), week=int(week), espn_id=str(pl.get("id")),
                       espn_total=s.get("appliedTotal"))
            rows.append(rec)
    return pd.DataFrame(rows)


def load_espn(cfg: X.ExternalConfig, season: int, current_season: int,
              weeks: Iterable[int] = REG_WEEKS, force: bool = False) -> pd.DataFrame:
    path = _cache_dir(cfg) / f"espn_{int(season)}.csv"
    if _needs_fetch(path, season, current_season, force):
        try:
            frames = [fetch_espn_week(season, w, cfg.timeout_seconds) for w in weeks]
            df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
            if not df.empty:
                _write(df, path)
        except Exception:
            if not (path.exists() and path.stat().st_size > 0):
                return pd.DataFrame()
    return X.read_cached_csv(path, dtype={"espn_id": str}) if path.exists() else pd.DataFrame()


# ---------------------------------------------------------------------------
# FantasyPros weekly consensus ranks (DynastyProcess' archive)
# ---------------------------------------------------------------------------
def load_fantasypros(cfg: X.ExternalConfig, force: bool = False) -> pd.DataFrame:
    """Weekly positional ECR (`ecr_type == "wp"`) for QB/RB/WR/TE, slimmed from
    DynastyProcess' db_fpecr archive: fantasypros_id, pos, ecr, scrape_date."""
    path = _cache_dir(cfg) / "fantasypros_weekly_ecr.csv"
    if force or X.cache_is_stale(path):
        try:
            r = requests.get(FPECR_URL, timeout=max(cfg.timeout_seconds, 180))
            r.raise_for_status()
            d = pd.read_parquet(io.BytesIO(r.content),
                                columns=["id", "pos", "ecr", "ecr_type", "scrape_date"])
            d = d[(d.ecr_type == "wp") & d.pos.isin(POSITIONS)]
            d = d.rename(columns={"id": "fantasypros_id"}).drop(columns="ecr_type")
            d["scrape_date"] = pd.to_datetime(d.scrape_date.astype(str)).dt.strftime("%Y-%m-%d")
            if not d.empty:
                _write(d, path)
        except Exception:
            pass
    return X.read_cached_csv(path, dtype={"fantasypros_id": str}) if path.exists() else pd.DataFrame()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_stats(stats: pd.DataFrame, table: Dict[str, float]) -> pd.Series:
    """Σ stat × league points over the stat columns the table scores."""
    cols = [c for c in stats.columns if c in table]
    if not cols:
        return pd.Series(0.0, index=stats.index)
    return (stats[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
            * pd.Series({c: table[c] for c in cols})).sum(axis=1)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
SOURCES_FULL: Tuple[str, ...] = ("sleeper", "espn", "fp", "claude")
SOURCES_WEAK: Tuple[str, ...] = ("espn", "fp", "claude")      # Sleeper's fallback model
FORM_PRIOR = 8.0        # pseudo-starts at 0 in the player's record v projections
DVP_PRIOR = 4.0         # pseudo-games at 0 in the opponent v position
DVP_TOP = 2             # the position's top N scorers against a defence ~ what starters scored


@dataclass
class Inputs:
    """What the projections read. `player_week` needs Year, Week, Team, Player,
    Position, NFL team, Points, Starter/Bench, a key column (`key`: Player ID in
    the build, Player in the exports), `out` (known out: flagged and 0 pts) and
    optionally `did_not_play` (`did_not_play()`; zeroes the published columns
    only).
    `claude`: Year, Week, <key>, E. `games`: the nfldata schedule. `ids`:
    DynastyProcess player ids. `scoring(season)` -> {stat: points}."""
    player_week: pd.DataFrame
    claude: pd.DataFrame
    games: pd.DataFrame
    ids: pd.DataFrame
    scoring: Callable[[int], Dict[str, float]]
    current_season: int
    sleeper: Dict[int, pd.DataFrame]
    espn: Dict[int, pd.DataFrame]
    fantasypros: pd.DataFrame
    key: str = "Player ID"


def _id_str(v) -> pd.Series:
    """An id column as clean strings: a numeric load turns 28013 into
    "28013.0" and a missing id into "nan" — neither may match anything
    (the build reads the DynastyProcess id table with numeric dtypes)."""
    s = pd.Series(v).astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    return s.where(~s.str.lower().isin(("nan", "none", "", "<na>")))


def _norm_team(t) -> str:
    from lotg_support.gametime import norm_team
    return norm_team(t)


def _schedule_lines(games: pd.DataFrame) -> Tuple[dict, dict, dict]:
    """(season, week, team) -> (implied, opp implied, home, dome, wind);
    -> opponent; (season, week) -> Sunday date."""
    lines, opp, sunday = {}, {}, {}
    g = games[games.get("game_type", "REG").astype(str).str.upper() == "REG"] if "game_type" in games else games
    for r in g.itertuples(index=False):
        s, w = int(r.season), int(r.week)
        h, a = _norm_team(r.home_team), _norm_team(r.away_team)
        opp[(s, w, h)], opp[(s, w, a)] = a, h
        try:
            d = pd.Timestamp(str(r.gameday)[:10])
            if d.weekday() == 6:
                sunday[(s, w)] = min(sunday.get((s, w), d), d)
        except Exception:
            pass
        tl, sl = getattr(r, "total_line", np.nan), getattr(r, "spread_line", np.nan)
        if pd.isna(tl) or pd.isna(sl):
            continue
        dome = 1.0 if str(getattr(r, "roof", "")) in ("dome", "closed") else 0.0
        wind = getattr(r, "wind", np.nan)
        wind = 0.0 if pd.isna(wind) else float(wind)
        hi, ai = (tl + sl) / 2, (tl - sl) / 2            # spread_line > 0: home favoured
        lines[(s, w, h)] = (hi, ai, 1.0, dome, wind)
        lines[(s, w, a)] = (ai, hi, 0.0, dome, wind)
    return lines, opp, sunday


def source_frame(inp: Inputs) -> pd.DataFrame:
    """Per player_week row: each source's projection in league points (NaN =
    none), the known-out flag, schedule features."""
    pw = inp.player_week
    out = pd.DataFrame(index=pw.index)
    yr = pd.to_numeric(pw["Year"], errors="coerce").astype("Int64")
    wk = pd.to_numeric(pw["Week"], errors="coerce").astype("Int64")
    key = pw[inp.key].astype(str)
    ids = inp.ids
    # The Sleeper id of every row: the build's Player ID; from the exports, via names.
    if inp.key == "Player ID":
        sid = _id_str(key)
    else:
        sid = pd.Series(np.nan, index=pw.index, dtype=object)
    # Claude
    cl = {(int(y), int(w), str(k)): float(e) for y, w, k, e in
          inp.claude[["Year", "Week", inp.key, "E"]].itertuples(index=False, name=None) if pd.notna(e)}
    if inp.key != "Player ID" and "Player ID" in inp.claude.columns:
        smap = {(int(y), int(w), str(k)): str(p) for y, w, k, p in
                inp.claude[["Year", "Week", inp.key, "Player ID"]].itertuples(index=False, name=None)}
        sid = pd.Series([smap.get((int(y), int(w), k)) if pd.notna(y) else None
                         for y, w, k in zip(yr, wk, key)], index=pw.index, dtype=object)
    out["claude"] = [cl.get((int(y), int(w), k)) if pd.notna(y) and pd.notna(w) else np.nan
                     for y, w, k in zip(yr, wk, key)]
    # Sleeper / ESPN, scored with each season's league rules
    _sl = _id_str(ids["sleeper_id"])
    espn2sl = {e: s_ for e, s_ in zip(_id_str(ids["espn_id"]), _sl) if pd.notna(e) and pd.notna(s_)}
    fp2sl = {f: s_ for f, s_ in zip(_id_str(ids["fantasypros_id"]), _sl) if pd.notna(f) and pd.notna(s_)}
    sl_pts, es_pts = {}, {}
    for season, df in inp.sleeper.items():
        if df is None or df.empty:
            continue
        df = df[df["has_projection"].astype(str).str.lower().isin(("true", "1"))]
        pts = score_stats(df, inp.scoring(int(season)))
        sl_pts.update({(int(season), int(w), p): v for w, p, v in zip(df.week, _id_str(df.sleeper_id), pts)})
    for season, df in inp.espn.items():
        if df is None or df.empty:
            continue
        pts = score_stats(df, inp.scoring(int(season)))
        for w, e, v in zip(df.week, _id_str(df.espn_id), pts):
            s_ = espn2sl.get(e)
            if s_:
                es_pts[(int(season), int(w), s_)] = v
    out["sleeper"] = [sl_pts.get((int(y), int(w), str(s_))) if pd.notna(y) and s_ else np.nan
                      for y, w, s_ in zip(yr, wk, sid)]
    out["espn"] = [es_pts.get((int(y), int(w), str(s_))) if pd.notna(y) and s_ else np.nan
                   for y, w, s_ in zip(yr, wk, sid)]
    out[["sleeper", "espn"]] = out[["sleeper", "espn"]].astype(float)
    # Schedule features
    lines, opp, sunday = _schedule_lines(inp.games)
    team = [_norm_team(t) for t in pw["NFL team"]]
    L = [lines.get((int(y), int(w), t)) if pd.notna(y) and pd.notna(w) else None for y, w, t in zip(yr, wk, team)]
    for i, c in enumerate(("implied", "opp_implied", "home", "dome", "wind")):
        out[c] = [l[i] if l else np.nan for l in L]
    out["opp_team"] = [opp.get((int(y), int(w), t)) if pd.notna(y) and pd.notna(w) else None
                       for y, w, t in zip(yr, wk, team)]
    # FantasyPros rank (pre-kickoff snapshot only): the last scrape in the 5
    # days up to the week's Sunday; dropped for a player who had already kicked off.
    out["fp_rank"] = np.nan
    fp = inp.fantasypros
    if fp is not None and not fp.empty:
        fp = fp.assign(sid=_id_str(fp["fantasypros_id"]).map(fp2sl),
                       sd=pd.to_datetime(fp["scrape_date"]))
        fp = fp[fp.sid.notna()]
        wk_of = {}
        for (s_, w_), sun in sunday.items():
            for d_ in fp.sd.unique():
                d_ = pd.Timestamp(d_)
                if pd.Timedelta(0) <= sun - d_ <= pd.Timedelta(days=5):
                    wk_of[d_] = (s_, w_)
        fp["yw"] = fp.sd.map(wk_of)
        fp = fp[fp.yw.notna()].sort_values("sd").groupby(["yw", "sid"]).tail(1)
        fp["prk"] = fp.groupby(["yw", "pos"]).ecr.rank(method="first")
        fr = {(yw[0], yw[1], s_): (r_, d_) for yw, s_, r_, d_ in fp[["yw", "sid", "prk", "sd"]].itertuples(index=False)}
        from lotg_support.gametime import load_schedule
        sched = load_schedule(inp.games)
        vals = []
        for y, w, s_, t in zip(yr, wk, sid, pw["NFL team"]):
            v = fr.get((int(y), int(w), str(s_))) if pd.notna(y) and s_ else None
            if v is None:
                vals.append(np.nan)
                continue
            ko = sched.team_kickoff(int(y), int(w), t)
            vals.append(np.nan if (ko is not None and v[1] >= pd.Timestamp(ko.date())) else v[0])
        out["fp_rank"] = vals
    # Known out: flagged bye / injured / suspended and scored 0
    out["out"] = pw["out"].astype(bool).values
    return out


# QB cameo [per user, 2026-10-10]: a quarterback who only came in for a kneel-down
# or a mop-up snap or two did not really play either. 2020-26 QB appearances on
# this league's rosters: <=5% of the offense's snaps scored 0.14 a game (93%
# under 1 point), 5-10% 1.39 (65%), over half 16.76 (1%).
QB_CAMEO_SHARE = 0.10        # at most this share of his team's offensive snaps ...
QB_CAMEO_POINTS = 1.0        # ... and under this many points ...
QB_ROLE_SHARE = 0.5          # ... and NOT his team's quarterback going in (under this
                             # share of its previous game this season): the starter
                             # hurt on the first drive (Kyler Murray 2022 wk 14,
                             # Aaron Rodgers 2023 wk 1) is a bust, not a cameo


def did_not_play(pw: pd.DataFrame, gsis: pd.Series, appeared: pd.DataFrame,
                 games: pd.DataFrame, snaps: Optional[pd.DataFrame] = None) -> pd.Series:
    """Per player_week row: True when the player did not take the field in a
    game his NFL team played — no stat line and no offensive snap (`appeared`:
    `boldness.game_log` rows, gsis_id / season / week / team, the same "sat
    out" the next-man-up lift uses) — and he scored 0. `gsis`: each row's gsis
    id; `pw` needs Year, Week, NFL team and Points.

    Only weeks whose result is known count: the team has a regular-season game
    in the schedule AND somebody on that team appears in the log that week (its
    stats have landed — never a week still being played; the schedule's final
    score is not required, a cached schedule lags the stats). No game (a bye),
    no gsis id or no NFL team: False. The struck 2022 week 17 Bills at Bengals
    game never counts [per user].

    With `snaps` (`boldness.snap_shares`: gsis_id / season / week / team /
    offense_pct) a QB CAMEO counts too: a quarterback with at most
    QB_CAMEO_SHARE of his team's offensive snaps who scored under
    QB_CAMEO_POINTS, unless he was its quarterback going in — QB_ROLE_SHARE or
    more of its snaps in its previous game this season (in its first game, his
    last game of the season before). Jake Browning 2024 wk 8 (3 kneel-downs,
    Burrow had every snap the week before) is a cameo."""
    from lotg_support.struck_games import STRUCK_GAME_IDS
    res = pd.Series(False, index=pw.index)
    if appeared is None or appeared.empty or games is None or games.empty:
        return res
    g = games
    if "game_type" in g.columns:
        g = g[g["game_type"].astype(str).str.upper() == "REG"]
    if "game_id" in g.columns:
        g = g[~g["game_id"].astype(str).isin(STRUCK_GAME_IDS)]
    played = set()
    for s, w, h, a in g[["season", "week", "home_team", "away_team"]].itertuples(index=False):
        if pd.notna(s) and pd.notna(w):
            played.add((int(s), int(w), _norm_team(h)))
            played.add((int(s), int(w), _norm_team(a)))
    ap = appeared.dropna(subset=["gsis_id", "season", "week"])
    seen = set(zip(ap["gsis_id"].astype(str), ap["season"].astype(int), ap["week"].astype(int)))
    landed = {(int(s), int(w), _norm_team(t)) for s, w, t in
              zip(ap["season"], ap["week"], ap["team"]) if pd.notna(t)}
    yr = pd.to_numeric(pw["Year"], errors="coerce")
    wk = pd.to_numeric(pw["Week"], errors="coerce")
    zero = pd.to_numeric(pw["Points"], errors="coerce").fillna(0) == 0
    if "Position" in pw.columns:              # the log only carries these positions
        zero &= pw["Position"].astype(str).str.upper().isin(POSITIONS)
    gs = _id_str(gsis.reindex(pw.index))
    for i, y, w, t, g_, z in zip(pw.index, yr, wk, pw["NFL team"], gs, zero):
        if not z or pd.isna(y) or pd.isna(w) or pd.isna(g_) or not str(t or "").strip():
            continue
        key = (int(y), int(w), _norm_team(t))
        if key in played and key in landed and (str(g_), int(y), int(w)) not in seen:
            res.at[i] = True
    if snaps is not None and not snaps.empty and "Position" in pw.columns:
        res |= _qb_cameo(pw, gs, yr, wk, snaps, played)
    return res


def _qb_cameo(pw, gs, yr, wk, snaps, played) -> pd.Series:
    """The QB-cameo half of `did_not_play` (see there)."""
    out = pd.Series(False, index=pw.index)
    sn = snaps.dropna(subset=["gsis_id", "season", "week"])
    pct = {(str(g), int(s), int(w)): (float(p) if pd.notna(p) else 0.0, _norm_team(t))
           for g, s, w, t, p in zip(sn["gsis_id"], sn["season"], sn["week"], sn["team"], sn["offense_pct"])}
    team_weeks: Dict[Tuple[int, str], List[int]] = {}
    last_share: Dict[Tuple[str, int], Tuple[int, float]] = {}
    for (g, s, w), (p, t) in pct.items():
        team_weeks.setdefault((s, t), []).append(w)
        if p > 0 and w >= last_share.get((g, s), (-1, 0.0))[0]:
            last_share[(g, s)] = (w, p)
    for k in team_weeks:
        team_weeks[k] = sorted(set(team_weeks[k]))
    qb = pw["Position"].astype(str).str.upper().eq("QB")
    low = pd.to_numeric(pw["Points"], errors="coerce").fillna(0) < QB_CAMEO_POINTS
    for i, y, w, g_ in zip(pw.index, yr, wk, gs):
        if not (qb.at[i] and low.at[i]) or pd.isna(y) or pd.isna(w) or pd.isna(g_):
            continue
        y, w, g_ = int(y), int(w), str(g_)
        p, team = pct.get((g_, y, w), (0.0, ""))
        if not (0 < p <= QB_CAMEO_SHARE) or (y, w, team) not in played:
            continue
        prev = [x for x in team_weeks.get((y, team), []) if x < w]
        role = (pct.get((g_, y, prev[-1]), (0.0, ""))[0] if prev
                else last_share.get((g_, y - 1), (0, 0.0))[1])
        if role < QB_ROLE_SHARE:
            out.at[i] = True
    return out


def _sqrt(v):
    return np.sqrt(np.clip(v, 0, None))


def _fp_points(src: pd.DataFrame, pw: pd.DataFrame, train_seasons: Sequence[int]) -> pd.Series:
    """FantasyPros rank -> points per position, a + b·ln(rank), fitted on the
    STARTED rows of `train_seasons` (never the season being projected)."""
    yr = pd.to_numeric(pw["Year"], errors="coerce")
    pos = pw["Position"].astype(str)
    pts = pd.to_numeric(pw["Points"], errors="coerce")
    started = pw["Starter/Bench"].astype(str).eq("Starter") & ~src["out"]
    out = pd.Series(np.nan, index=pw.index)
    for p in POSITIONS:
        tr = started & yr.isin(train_seasons) & pos.eq(p) & src["fp_rank"].notna()
        if tr.sum() < 50:
            continue
        A = np.c_[np.ones(int(tr.sum())), np.log(src.loc[tr, "fp_rank"])]
        a, b = np.linalg.lstsq(A, pts[tr].values, rcond=None)[0]
        m = pos.eq(p) & src["fp_rank"].notna()
        out[m] = a + b * np.log(src.loc[m, "fp_rank"])
    return out


def _features(src: pd.DataFrame, pw: pd.DataFrame, sources: Sequence[str]) -> np.ndarray:
    S = src[list(sources)].values.astype(float)
    m = np.nanmean(S, axis=1)
    S = np.where(np.isnan(S), m[:, None], S)          # a missing source reads the average of the rest
    sd = S.std(axis=1)
    f = lambda c, d=0.0: src[c].fillna(d).values.astype(float)
    imp, oimp = f("implied", 23.5), f("opp_implied", 23.5)
    spread = imp - oimp
    return np.column_stack([np.ones(len(src)), S, sd, m * sd, imp, m * imp / 24, oimp, spread,
                            spread * m / 15, f("player_form"), f("form3"), f("dvp"), f("home", 0.5),
                            f("dome", 0.0), f("wind", 0.0), _sqrt(S)])


def _form_and_dvp(src: pd.DataFrame, pw: pd.DataFrame, avg: pd.Series) -> None:
    """The player's record v the projections (his previous STARTS: points −
    average projection, shrunk with FORM_PRIOR starts at 0; and the last 3), and
    the opponent's record v his position (points over league average allowed to
    the position's top DVP_TOP scorers, season to date, shrunk). Both read only
    earlier weeks."""
    yr = pd.to_numeric(pw["Year"], errors="coerce")
    wk = pd.to_numeric(pw["Week"], errors="coerce")
    t = yr * 100 + wk
    pts = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)
    start = pw["Starter/Bench"].astype(str).eq("Starter") & ~src["out"] & avg.notna()
    res = (pts - avg).where(start)
    key = pw["Player"].astype(str)
    df = pd.DataFrame({"k": key, "t": t, "res": res}).sort_values(["k", "t"])
    g = df.groupby("k").res
    prev_sum = g.transform(lambda s: s.fillna(0).cumsum().shift(1).fillna(0))
    prev_n = g.transform(lambda s: s.notna().astype(int).cumsum().shift(1).fillna(0))
    df["form"] = prev_sum / (prev_n + FORM_PRIOR)
    df["form3"] = g.transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean()).fillna(0.0)
    src["player_form"] = df["form"].reindex(src.index).fillna(0.0)
    src["form3"] = df["form3"].reindex(src.index).fillna(0.0)
    # opponent v position, from every rostered player who had a game
    played = src["opp_team"].notna() & ~src["out"]
    a = pd.DataFrame({"Year": yr, "Week": wk, "opp": src["opp_team"], "pos": pw["Position"].astype(str),
                      "pts": pts})[played]
    top = a.sort_values("pts", ascending=False).groupby(["Year", "Week", "opp", "pos"]).head(DVP_TOP)
    al = top.groupby(["Year", "Week", "opp", "pos"]).pts.mean().reset_index()
    al["over"] = al.pts - al.groupby(["Year", "pos"]).pts.transform("mean")
    al = al.sort_values(["Year", "opp", "pos", "Week"])
    grp = al.groupby(["Year", "opp", "pos"]).over
    al["dvp"] = grp.transform(lambda s: s.shift(1).fillna(0).cumsum()) / (al.groupby(["Year", "opp", "pos"]).cumcount() + DVP_PRIOR)
    m = {(int(y), int(w), o, p): v for y, w, o, p, v in al[["Year", "Week", "opp", "pos", "dvp"]].itertuples(index=False)}
    src["dvp"] = [m.get((int(y), int(w), o, p), 0.0) if pd.notna(y) and o else 0.0
                  for y, w, o, p in zip(yr, wk, src["opp_team"], pw["Position"].astype(str))]


def _fit(X: np.ndarray, y: np.ndarray):
    """Least squares on √points; returns (coef, training residuals on √ scale)."""
    ys = _sqrt(y)
    b = np.linalg.lstsq(X, ys, rcond=None)[0]
    return b, ys - X @ b


def _predict(X: np.ndarray, b: np.ndarray, resid: np.ndarray) -> np.ndarray:
    """Back to points by smearing: mean over training residuals of (fit + r)²."""
    fit = X @ b
    r = resid[None, :]
    out = np.empty(len(fit))
    for i in range(0, len(fit), 2000):                 # chunks keep the matrix small
        out[i:i + 2000] = (np.clip(fit[i:i + 2000, None] + r, 0, None) ** 2).mean(axis=1)
    return out


def project(inp: Inputs) -> pd.DataFrame:
    """Sleeper / Claude / Enhanced Projection for every player_week row, plus
    the source values (diagnostics). See the module docstring."""
    pw = inp.player_week
    src = source_frame(inp)
    yr = pd.to_numeric(pw["Year"], errors="coerce")
    pts = pd.to_numeric(pw["Points"], errors="coerce")
    done = sorted(int(s) for s in yr.dropna().unique() if int(s) < int(inp.current_season))
    for c in ("sleeper", "espn"):                      # a data hole, not a forecast
        src.loc[~src["out"] & (src[c] < MIN_PROJECTION), c] = np.nan
    src["fp"] = np.nan
    seasons = sorted(int(s) for s in yr.dropna().unique())
    for s in seasons:
        train = [t for t in done if t != s]
        rows = yr.eq(s)
        src.loc[rows, "fp"] = _fp_points(src, pw, train)[rows]
    avg = src[list(SOURCES_FULL)].mean(axis=1)
    _form_and_dvp(src, pw, avg)
    started = pw["Starter/Bench"].astype(str).eq("Starter") & ~src["out"] & src["claude"].notna() & pts.notna()
    Xf, Xw = _features(src, pw, SOURCES_FULL), _features(src, pw, SOURCES_WEAK)
    enh = pd.Series(np.nan, index=pw.index)
    weak = pd.Series(np.nan, index=pw.index)
    for s in seasons:
        train = started & yr.isin([t for t in done if t != s])
        if train.sum() < 500:
            continue
        rows = yr.eq(s).values
        bf, rf = _fit(Xf[train.values], pts[train].values)
        bw, rw = _fit(Xw[train.values], pts[train].values)
        enh[rows] = _predict(Xf[rows], bf, rf)
        weak[rows] = _predict(Xw[rows], bw, rw)
    outside = src[["sleeper", "espn", "fp"]].notna().any(axis=1)
    claude = src["claude"]
    res = pd.DataFrame(index=pw.index)
    res["Claude Projection"] = claude
    res["Enhanced Projection"] = enh.where(outside & enh.notna(), claude)
    weak_ok = src[["espn", "fp"]].notna().any(axis=1) & weak.notna()
    res["Sleeper Projection"] = src["sleeper"].where(src["sleeper"].notna(), weak.where(weak_ok, claude))
    # Known out, or did not play (no stat line / snap in a played game): 0.
    # Only here — the fits above keep reading `out` alone.
    dnp = (pw["did_not_play"].fillna(False).astype(bool) if "did_not_play" in pw.columns
           else pd.Series(False, index=pw.index))
    zero = src["out"] | dnp
    for c in ("Sleeper Projection", "Claude Projection", "Enhanced Projection"):
        res.loc[zero, c] = 0.0
        res[c] = res[c].round(2)
    # The Claude projection BEFORE the known-out zeroing: an "if healthy" figure
    # for the Hardship (Claude Projections) columns — never read the zeroed one.
    res["_claude_raw"] = claude
    res["_sources"] = src[list(SOURCES_FULL)].notna().sum(axis=1)
    res["_sleeper_fallback"] = src["sleeper"].isna() & ~zero
    res["_did_not_play"] = dnp & ~src["out"]
    return res


# ---------------------------------------------------------------------------
# Columns [per user, 2026-10-07]
# ---------------------------------------------------------------------------
def proj_col(x: str) -> str:
    return f"{x} Projection"


def above_col(x: str) -> str:
    return f"Points above {x} Projection"


def over_col(x: str) -> str:
    return f"Overachiever ({x} Projection)"


def under_col(x: str) -> str:
    return f"Underachiever ({x} Projection)"


def streak_col(award: str) -> str:
    return f"{award} streak"


AWARD_COLUMNS: Tuple[str, ...] = tuple(c for x in NAMES for c in (over_col(x), under_col(x)))
WEEK_COLUMNS: Tuple[str, ...] = tuple(c for x in NAMES for c in (
    proj_col(x), above_col(x), over_col(x), under_col(x),
    streak_col(over_col(x)), streak_col(under_col(x))))
LEAGUE_WEEK_COLUMNS: Tuple[str, ...] = tuple(c for x in NAMES for c in (proj_col(x), above_col(x)))


def rollup_columns(times_prefix: Optional[str]) -> Tuple[str, ...]:
    """Year / all-time columns: totals, per-week averages and (player / team
    sheets) the award counts. League sheets have no awards (`times_prefix` None)."""
    out = []
    for x in NAMES:
        out += [proj_col(x), above_col(x), f"Avg {proj_col(x)}", f"Avg {above_col(x)}"]
        if times_prefix:
            out += [f"{times_prefix}{over_col(x)}", f"{times_prefix}{under_col(x)}"]
    return tuple(out)


def _started(pw: pd.DataFrame) -> pd.Series:
    return pw["Starter/Bench"].astype(str).eq("Starter")


def player_week_awards(pw: pd.DataFrame, out: pd.Series) -> pd.DataFrame:
    """Overachiever / Underachiever per projection: the starter (not known out)
    with the week's highest / lowest Points above that projection, league-wide.
    One winner a week, alphabetical by player on a tie (as Player of the week).
    1 / 0 per row."""
    res = pd.DataFrame(0, index=pw.index, columns=list(AWARD_COLUMNS))
    elig = _started(pw) & ~out.astype(bool)
    pts = pd.to_numeric(pw["Points"], errors="coerce")
    for x in NAMES:
        diff = pts - pd.to_numeric(pw[proj_col(x)], errors="coerce")
        d = pd.DataFrame({"Year": pw["Year"], "Week": pw["Week"], "Player": pw["Player"].astype(str),
                          "v": diff})[elig & diff.notna()]
        if d.empty:
            continue
        for col, asc in ((over_col(x), False), (under_col(x), True)):
            win = d.sort_values(["Year", "Week", "v", "Player"], ascending=[True, True, asc, True]) \
                   .groupby(["Year", "Week"]).head(1).index
            res.loc[win, col] = 1
    return res


def team_week_projection(tw: pd.DataFrame, pw: pd.DataFrame) -> pd.DataFrame:
    """Team, Year, Week + per projection: X Projection (the starters'
    projections + any PF the starters did not score — the semifinal +5 — so the
    bonus is never 'above projection') and Points above X Projection (PF − it)."""
    st = pw[_started(pw)]
    agg = {proj_col(x): (proj_col(x), "sum") for x in NAMES}
    agg["_st_pts"] = ("Points", "sum")
    g = st.assign(Points=pd.to_numeric(st["Points"], errors="coerce").fillna(0.0),
                  **{proj_col(x): pd.to_numeric(st[proj_col(x)], errors="coerce") for x in NAMES}) \
          .groupby(["Team", "Year", "Week"]).agg(**agg).reset_index()
    t = tw[["Team", "Year", "Week", "PF"]].merge(g, on=["Team", "Year", "Week"], how="left")
    pf = pd.to_numeric(t["PF"], errors="coerce")
    bonus = (pf - t["_st_pts"]).fillna(0.0)
    for x in NAMES:
        t[proj_col(x)] = (t[proj_col(x)] + bonus).round(2)
        t[above_col(x)] = (pf - t[proj_col(x)]).round(2)
    return t.drop(columns=["PF", "_st_pts"])


def team_week_awards(t: pd.DataFrame) -> pd.DataFrame:
    """Team Overachiever / Underachiever per projection: highest / lowest Points
    above X Projection that week (ties: every tied team, as Highest score?)."""
    res = pd.DataFrame(0, index=t.index, columns=list(AWARD_COLUMNS))
    for x in NAMES:
        v = pd.to_numeric(t[above_col(x)], errors="coerce")
        g = v.groupby([t["Year"], t["Week"]])
        res.loc[v.notna() & (v == g.transform("max")), over_col(x)] = 1
        res.loc[v.notna() & (v == g.transform("min")), under_col(x)] = 1
    return res


def rollup(frame: pd.DataFrame, keys: List[str], times_prefix: Optional[str]) -> pd.DataFrame:
    """Sum / per-week average of each projection and Points above it over
    `keys`, + award counts (player / team sheets)."""
    agg = {}
    for x in NAMES:
        p, a = proj_col(x), above_col(x)
        agg[p] = (p, "sum")
        agg[a] = (a, "sum")
        agg[f"Avg {p}"] = (p, "mean")
        agg[f"Avg {a}"] = (a, "mean")
        if times_prefix:
            agg[f"{times_prefix}{over_col(x)}"] = (over_col(x), "sum")
            agg[f"{times_prefix}{under_col(x)}"] = (under_col(x), "sum")
    cols = sorted({v[0] for v in agg.values()})
    f = frame[keys + cols].copy()
    for c in cols:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    out = f.groupby(keys, dropna=False).agg(**agg).reset_index()
    for c in out.columns:
        if c not in keys:
            out[c] = out[c].round(2)
    return out


# ---------------------------------------------------------------------------
# Projection versions of other stats [per user, 2026-10-07]
# ---------------------------------------------------------------------------
UPSET_GAP = 9.0     # UPST: a win while projected this many points (or more) behind
                    # [per user: Enhanced, "8-10 point threshold"; underdogs that far
                    # behind won 26% at 8, 9 and 10 alike over 2020-26 — 9 is the middle]


def startsit_col(x: str, adjusted: bool = False) -> str:
    return f"Start/sit miss ({x} Projection)" + (" adjusted by position" if adjusted else "")


def opp_gap_col(x: str) -> str:
    return f"Difference in {x} Projection from opponent"


STARTSIT_COLUMNS: Tuple[str, ...] = tuple(startsit_col(x, a) for x in NAMES for a in (False, True))
OPP_GAP_COLUMNS: Tuple[str, ...] = tuple(opp_gap_col(x) for x in NAMES)
COMBINED_SPECS: Tuple[Tuple[str, str, str], ...] = tuple(
    (f"Combined {c}", c, "sum") for x in NAMES for c in (proj_col(x), above_col(x)))


def startsit_miss(pw: pd.DataFrame, pos_factor: Callable[[int, str], float]) -> pd.DataFrame:
    """The 'best/worst startables over previous 5 games' comparison on each
    projection instead of 5-game averages, against the SAME reference player
    (player_week "Reference player ID"): a starter's reference (the best
    startable bench player) minus him, a bench player minus his reference (the
    worst benchable starter). Positive = the lineup call went against the
    projection. Adjusted twin: each side × its position factor for the season."""
    out = pd.DataFrame(np.nan, index=pw.index, columns=list(STARTSIT_COLUMNS))
    if "Reference player ID" not in pw.columns:
        return out
    pid = _id_str(pw["Player ID"])
    yr = pd.to_numeric(pw["Year"], errors="coerce")
    wk = pd.to_numeric(pw["Week"], errors="coerce")
    pos = pw["Position"].astype(str) if "Position" in pw.columns else pd.Series("", index=pw.index)
    pos_of = dict(zip(pid, pos))
    ref = _id_str(pw["Reference player ID"])
    started = pw["Starter/Bench"].astype(str).eq("Starter").to_numpy()
    for x in NAMES:
        v = pd.to_numeric(pw[proj_col(x)], errors="coerce")
        look = {(p, int(y), int(w)): e for p, y, w, e in zip(pid, yr, wk, v)
                if pd.notna(p) and pd.notna(y) and pd.notna(w) and pd.notna(e)}
        mine = v.to_numpy(dtype=float)
        theirs = np.array([look.get((r, int(y), int(w)), np.nan) if pd.notna(r) and pd.notna(y) and pd.notna(w)
                           else np.nan for r, y, w in zip(ref, yr, wk)])
        out[startsit_col(x)] = np.round(np.where(started, theirs - mine, mine - theirs), 2)
        fac_me = np.array([pos_factor(int(y), p_) if pd.notna(y) else np.nan for y, p_ in zip(yr, pos)])
        fac_ref = np.array([pos_factor(int(y), pos_of.get(r, "")) if pd.notna(y) and pd.notna(r) else np.nan
                            for y, r in zip(yr, ref)])
        a_me, a_ref = mine * fac_me, theirs * fac_ref
        out[startsit_col(x, True)] = np.round(np.where(started, a_ref - a_me, a_me - a_ref), 2)
    return out


def opponent_gaps(tw: pd.DataFrame) -> pd.DataFrame:
    """Per projection: the team's X Projection minus its opponent's (the
    projection version of 'Difference in pregame avg max PF from opponent'),
    and UPST on Enhanced: 1 for a win while projected UPSET_GAP+ behind."""
    opp = tw[["Team", "Year", "Week"] + [proj_col(x) for x in NAMES]].rename(
        columns={"Team": "Opponent", **{proj_col(x): f"_o{x}" for x in NAMES}})
    t = tw[["Opponent", "Year", "Week"] + [proj_col(x) for x in NAMES]].merge(
        opp, on=["Opponent", "Year", "Week"], how="left")
    out = pd.DataFrame(index=tw.index)
    for x in NAMES:
        out[opp_gap_col(x)] = (pd.to_numeric(t[proj_col(x)], errors="coerce")
                               - pd.to_numeric(t[f"_o{x}"], errors="coerce")).round(2).to_numpy()
    won = tw["Win?"].astype(str).str.lower().isin(("true", "1", "1.0")).to_numpy()
    gap = out[opp_gap_col("Enhanced")].to_numpy(dtype=float)
    out["UPST"] = np.where(np.isnan(gap), np.nan, (won & (gap <= -UPSET_GAP)).astype(float))
    return out
