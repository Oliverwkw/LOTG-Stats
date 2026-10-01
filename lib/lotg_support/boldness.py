"""Boldness — how far a lineup call went against what the manager could see.

`player_week` already carries a start/sit signal, "Difference in averages of
best/worst startables over previous 5 games", but it answers a different
question. Its reference player is picked by what he ACTUALLY scored that week
(the bench's top scorer, any position, taxi and IR included), and only then are
the two 5-game averages compared. That is "how far behind the man who turned out
best was this starter on paper" — a hindsight choice of comparison — not "how
far did this call go against the information on the table". This module is the
second one.

## The stat

For every start, before kickoff:

    Boldness = max(0, E[best eligible available bench option] - E[starter])

where `E` is the player's expected points (below), "eligible" means the bench
player could legally fill the starter's slot (`inquiry.season_eligibility`, so
position drift is handled), and "available" means not on bye / injured /
suspended by the build's own flags (`inquiry.unavailable`) and not parked on the
taxi squad. A signed twin, `Edge`, keeps the negative side (a safe call is
negative). `Team boldness` is the ex-ante version of Max PF minus PF: the best
lineup the expectations allowed (`lineup.compute_optimal_lineup`, the build's
own routine, fed E instead of points) minus the expected points of the lineup
actually set — so two starters gambling against the same bench player are not
double-counted.

## Expected points

A shrunk, season-decayed average of the player's own NFL games, re-scored into
league settings (`contracts.lotg_points`), with three adjustments the question
asked for:

* **Between seasons.** Games from the current season count 1; the previous
  season `prior_season_weight` (d); two seasons back d². A game played for a
  different NFL team than the player's team that week is further multiplied by
  `team_change_weight`. So week 1 is judged on last year at half weight, and a
  player's own season takes over as it accumulates — no "N/A until 5 games".
* **Rookies.** A player with no NFL game yet is not N/A: he gets a prior from
  past rookies at his position and NFL draft round (`rookie_priors`, learned only
  from seasons BEFORE the one being judged), and that prior is shrunk away as his
  own games arrive. Starting an undrafted rookie in week 1 is therefore
  measurable, and reads as bold, which it is.
* **Cuffs (role changes).** A backup's history is a backup's history. When a
  same-team, same-position teammate with a higher E sits out the week (no stat
  line and no offensive snap — inactives are announced before kickoff) while
  still on that team's weekly roster (injured reserve included), having played
  for it this season (or last, in the first `preseason_grace_weeks`), the backup is
  promoted for as long as the absence lasts — the NEXT MAN UP only (the
  highest-E teammate still available): E = max(own E, beta[pos] x
  teammate's E). `beta` is calibrated from
  every such promotion in the NFL 2019-2025 (`calibrate_beta`), not chosen. The
  build's cuff columns halve a difference after the fact; this changes the
  expectation instead, so an activated cuff is simply not bold.

Everything debatable is a field on `Params`.

## Guards

* `check_points_reconcile` — the re-scored game log must reproduce the build's
  own `player_week["Points"]` for rostered players (same tolerance story as
  `scoring_events.check_touchdown_join`).
* `check_calibration` — if E is unbiased, a start with boldness B should lose to
  its reference by about B on average: the slope of (starter - reference) actual
  points on Edge must be near -1. This is the test that E means something.
* `check_team_boldness_bounds` — Team boldness is never negative and the
  optimiser fed ACTUAL points reproduces `team_week["Max PF"]` (minus the
  semifinal bonus) wherever the pool is the same, which ties the lineup half to
  the build.

## Traps

* `Q.unavailable` maps the build's flags to ids by NAME, so two players sharing
  a name share flags. Rare; counted nowhere.
* Historical taxi status is only known at season end (rosters.json). A player
  promoted off taxi mid-season was, before that, unstartable and may be named as
  a reference; `Ref taxi-eligible?` flags rookies who never started that season
  so such rows can be read by hand.
* A starter flagged unavailable is a dead start, not a bold one: it is kept,
  flagged `Starter unavailable?`, and excluded from the history boards by
  default.
* Expected points have no matchup, weather or Vegas input. Two-thirds of what a
  manager weighs is in here; the rest is not in any file this repo has.

Read-only and inquiry-only: nothing in `src/` or `.github/workflows/` imports
this module.
"""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass, asdict, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from lotg_support import contracts as C
from lotg_support import external as X
from lotg_support import inquiry as Q
from lotg_support import lineup as L
from lotg_support import scoring_events as SE

POSITIONS: Tuple[str, ...] = ("QB", "RB", "WR", "TE")
#: nflverse calls some backs FB; they fill RB slots here.
_POSITION_ALIASES = {"FB": "RB", "HB": "RB"}
#: First season the cached nflverse weekly files cover.
FIRST_LOG_SEASON = 2018
#: Draft-round buckets for the rookie prior.
_ROOKIE_BUCKETS = ("R1", "R2", "R3", "R4-7", "UDFA")
#: Sleeper statuses that mean "will not play" for the in-progress week.
LIVE_OUT_STATUSES = frozenset({"Out", "IR", "PUP", "Sus", "NA", "DNR"})


@dataclass(frozen=True)
class Params:
    """Every debatable choice, named. Defaults are the tuned ones (see
    `tune()` and the note in plan/notes when written)."""
    prior_season_weight: float = 0.25  # d: weight of a last-season game (tuned: interior optimum)
    team_change_weight: float = 0.5    # extra multiplier for a game on another NFL team
    shrink_games: float = 2.0          # pseudo-games of prior for a veteran
    rookie_shrink_games: float = 3.0   # pseudo-games of the draft-round prior for a rookie
    promotion_lookback: Optional[int] = None  # None: the teammate counts while he is on the team's weekly
                                       # roster and not playing; N: only if he played in one of its last N games
    promote: bool = True               # apply the cuff/role promotion
    preseason_grace_weeks: int = 4     # the absent teammate must have played for the team THIS season,
                                       # except in weeks 1..N where last season counts (preseason injury)
    beta: Optional[Tuple[Tuple[str, float], ...]] = None   # None -> calibrate_beta()


# ---------------------------------------------------------------------------
# The game log
# ---------------------------------------------------------------------------
def _config() -> X.ExternalConfig:
    return X.ExternalConfig(cache_dir=Q.repo_root() / ".cache")


@functools.lru_cache(maxsize=1)
def _player_ids() -> pd.DataFrame:
    ids = X.load_nflverse_player_ids(_config())
    ids = ids[ids["gsis_id"].notna()].copy()
    ids["gsis_id"] = ids["gsis_id"].astype(str)
    ids["pos"] = ids["position"].astype(str).str.upper().replace(_POSITION_ALIASES)
    return ids.drop_duplicates("gsis_id").set_index("gsis_id")


@functools.lru_cache(maxsize=16)
def _season_log(season: int) -> pd.DataFrame:
    """One row per (gsis_id, week) the player TOOK THE FIELD in a regular-season
    game: a stat line, or an offensive snap with none (scored 0, as the build's
    5-game window does). Columns: gsis_id, season, week, team, points."""
    stats = SE.weekly_stats(season)
    stats = stats.assign(points=C.lotg_points(stats).astype(float))
    stats = stats[["player_id", "week", "team", "points"]].rename(columns={"player_id": "gsis_id"})
    stats["week"] = stats["week"].astype(int)
    try:
        snaps = X.load_nflverse_snap_counts(_config(), season)
    except Exception:
        snaps = pd.DataFrame()
    if not snaps.empty:
        snaps = snaps[(snaps["game_type"].astype(str).str.upper() == "REG")
                      & (pd.to_numeric(snaps["offense_snaps"], errors="coerce") > 0)]
        pfr = _player_ids()["pfr_id"].dropna()
        pfr_to_gsis = {v: k for k, v in pfr.items()}
        try:
            wr = X.load_nflverse_weekly_rosters(_config(), season)
            for p, g in zip(wr["pfr_id"], wr["gsis_id"]):
                if isinstance(p, str) and isinstance(g, str):
                    pfr_to_gsis.setdefault(p, g)
        except Exception:
            pass
        snaps = snaps.assign(gsis_id=snaps["pfr_player_id"].map(pfr_to_gsis))
        snaps = snaps[snaps["gsis_id"].notna()][["gsis_id", "week", "team"]]
        snaps["week"] = snaps["week"].astype(int)
        have = set(zip(stats["gsis_id"], stats["week"]))
        extra = snaps[[k not in have for k in zip(snaps["gsis_id"], snaps["week"])]]
        stats = pd.concat([stats, extra.assign(points=0.0)], ignore_index=True)
    stats["season"] = int(season)
    pos = _player_ids()["pos"]
    stats["position"] = stats["gsis_id"].map(pos)
    stats = stats[stats["position"].isin(POSITIONS)]
    return stats.drop_duplicates(["gsis_id", "week"]).reset_index(drop=True)


def game_log(seasons: Sequence[int]) -> pd.DataFrame:
    """The appearance log for several seasons, oldest first."""
    frames = [_season_log(int(s)) for s in seasons if int(s) >= FIRST_LOG_SEASON]
    if not frames:
        return pd.DataFrame(columns=["gsis_id", "season", "week", "team", "points", "position"])
    return pd.concat(frames, ignore_index=True)


@functools.lru_cache(maxsize=16)
def _weekly_teams(season: int) -> Dict[Tuple[str, int], str]:
    """(gsis_id, week) -> NFL team on that week's roster (nflverse weekly rosters)."""
    try:
        wr = X.load_nflverse_weekly_rosters(_config(), season)
    except Exception:
        return {}
    wr = wr[wr["game_type"].astype(str).str.upper() == "REG"]
    return {(str(g), int(w)): str(t) for g, w, t in zip(wr["gsis_id"], wr["week"], wr["team"])
            if isinstance(g, str)}


# ---------------------------------------------------------------------------
# Priors
# ---------------------------------------------------------------------------
def _bucket(draft_round) -> str:
    try:
        r = int(float(draft_round))
    except (TypeError, ValueError):
        return "UDFA"
    if r == 1:
        return "R1"
    if r == 2:
        return "R2"
    if r == 3:
        return "R3"
    return "R4-7" if r <= 7 else "UDFA"


@functools.lru_cache(maxsize=16)
def _rookie_priors_cached(season: int) -> Tuple[Tuple[Tuple[str, str], float], ...]:
    ids = _player_ids()
    out: Dict[Tuple[str, str], float] = {}
    rows = []
    for y in range(FIRST_LOG_SEASON, int(season)):
        log = _season_log(y)
        rook = ids.index[(pd.to_numeric(ids["rookie_season"], errors="coerce") == y)]
        sub = log[log["gsis_id"].isin(set(rook))]
        if sub.empty:
            continue
        sub = sub.assign(bucket=sub["gsis_id"].map(ids["draft_round"]).map(_bucket))
        rows.append(sub[["position", "bucket", "points"]])
    if rows:
        allr = pd.concat(rows, ignore_index=True)
        for (pos, b), g in allr.groupby(["position", "bucket"]):
            if len(g) >= 20:       # too few appearances -> fall back to the position mean
                out[(pos, b)] = float(g["points"].mean())
        for pos, g in allr.groupby("position"):
            out[(pos, "*")] = float(g["points"].mean())
    return tuple(sorted(out.items()))


def rookie_priors(season: int) -> Dict[Tuple[str, str], float]:
    """{(position, draft bucket): mean points per appearance of rookies in their
    rookie season}, learned only from seasons before `season`. `(pos, "*")` is
    the all-rookie fallback for a thin bucket."""
    return dict(_rookie_priors_cached(int(season)))


@functools.lru_cache(maxsize=16)
def _vet_priors_cached(season: int) -> Tuple[Tuple[str, float], ...]:
    log = game_log([season - 1])
    if log.empty:
        log = game_log([season - 2])
    return tuple(sorted({p: float(g["points"].mean()) for p, g in log.groupby("position")}.items()))


def veteran_priors(season: int) -> Dict[str, float]:
    """{position: mean points per appearance} the previous season — the prior a
    veteran with almost no history is shrunk toward."""
    return dict(_vet_priors_cached(int(season)))


# ---------------------------------------------------------------------------
# Expected points
# ---------------------------------------------------------------------------
def _base_expectations(season: int, weeks: Sequence[int], p: Params) -> pd.DataFrame:
    """E before any role promotion, for every player with history or a rookie
    prior, for each requested week."""
    log = game_log([season - 2, season - 1, season])
    ids = _player_ids()
    rpri = rookie_priors(season)
    vpri = veteran_priors(season)
    teams_now = _weekly_teams(season)
    rookies = set(ids.index[pd.to_numeric(ids["rookie_season"], errors="coerce") == season])
    rookies &= set(ids.index[ids["pos"].isin(POSITIONS)])
    last_team = {}
    out = []
    for wk in sorted(set(int(w) for w in weeks)):
        before = log[(log["season"] < season) | (log["week"] < wk)]
        # The player's NFL team THIS week: weekly roster, else his latest game.
        latest = before.sort_values(["season", "week"]).groupby("gsis_id")["team"].last()
        players = set(before["gsis_id"]) | rookies
        cur_team = {g: teams_now.get((g, wk), latest.get(g)) for g in players}
        w = np.power(p.prior_season_weight, (season - before["season"]).to_numpy(dtype=float))
        moved = before["team"].to_numpy() != before["gsis_id"].map(cur_team).to_numpy()
        w = np.where(moved & (before["season"].to_numpy() < season), w * p.team_change_weight, w)
        b = before.assign(_w=w, _wp=w * before["points"].to_numpy())
        agg = b.groupby("gsis_id").agg(W=("_w", "sum"), S=("_wp", "sum"),
                                       n_cur=("season", lambda s: int((s == season).sum())),
                                       n_all=("week", "size"))
        rows = []
        for g in players:
            pos = ids["pos"].get(g)
            if pos not in POSITIONS:
                continue
            Wsum, Ssum = (float(agg.at[g, "W"]), float(agg.at[g, "S"])) if g in agg.index else (0.0, 0.0)
            is_rookie = g in rookies
            if is_rookie:
                prior = rpri.get((pos, _bucket(ids["draft_round"].get(g))), rpri.get((pos, "*"), vpri.get(pos, 0.0)))
                k = p.rookie_shrink_games
                source = "rookie prior" if Wsum == 0 else "rookie history"
            else:
                prior = vpri.get(pos, 0.0)
                k = p.shrink_games
                source = "history" if Wsum > 0 else "positional prior"
            rows.append((g, wk, cur_team.get(g), pos, (Ssum + k * prior) / (Wsum + k), Wsum,
                         int(agg.at[g, "n_cur"]) if g in agg.index else 0, is_rookie, source))
        out.append(pd.DataFrame(rows, columns=["gsis_id", "week", "team", "position", "E_base",
                                               "weight", "games_this_season", "rookie", "source"]))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _team_game_index(log: pd.DataFrame) -> Dict[str, List[Tuple[int, int]]]:
    """team -> its game weeks (season, week), in order, as seen in the log."""
    tg = log[["team", "season", "week"]].drop_duplicates().sort_values(["season", "week"])
    return {t: list(zip(g["season"], g["week"])) for t, g in tg.groupby("team")}


def _promotion_events(season: int, base: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Rows (gsis_id, week, promoted_over, E_over): the NEXT MAN UP — the
    highest-E available player at a team-position — when a teammate with a
    higher E sits out the week while on that team's weekly roster (and, if
    `promotion_lookback` is set, after playing in one of the team's last N
    games). Only the next man up is promoted: calibrating over every backup
    behind an absent starter (RB3s, WR5s) dilutes beta to the point where a
    real handcuff reads as bold for starting.

    "Sat out" is known before kickoff (inactives are announced ~90 minutes
    ahead): in a played week it is "no stat line and no offensive snap"; in a
    week not yet played it is Sleeper's current status (`LIVE_OUT_STATUSES`)."""
    log = game_log([season - 1, season])
    cur = log[log["season"] == season]
    played_team = dict(zip(zip(cur["gsis_id"], cur["week"]), cur["team"]))
    played_weeks = set(cur["week"])
    appear = set(zip(log["gsis_id"], log["season"], log["week"], log["team"]))
    tgi = _team_game_index(log)
    on_roster = _weekly_teams(season)
    live_out = _live_out_gsis()
    games_of: Dict[str, List[Tuple[int, int, str]]] = {}
    for g, gs, gw, gt in appear:
        games_of.setdefault(g, []).append((int(gs), int(gw), str(gt)))
    rows = []
    for (wk, team, pos), grp in base[base["team"].notna()].groupby(["week", "team", "position"]):
        if len(grp) < 2:
            continue
        if wk in played_weeks:
            sat = lambda g: (g, wk) not in played_team
            present = [r for r in grp.itertuples() if played_team.get((r.gsis_id, wk)) == team]
        else:
            sat = lambda g: g in live_out
            present = [r for r in grp.itertuples()
                       if not sat(r.gsis_id) and on_roster.get((r.gsis_id, wk), r.team) == team]
        # The absent teammate must be on this team's weekly roster THIS week
        # (injured reserve included) — a retired or released player keeps his
        # last team in the game log and would otherwise "sit out" forever.
        absent = [r for r in grp.itertuples() if sat(r.gsis_id) and on_roster.get((r.gsis_id, wk)) == team]
        # ...and must have played for it this season (last season too in the
        # first weeks): a starter missing the whole year (Deshaun Watson 2021)
        # is not a role anyone is filling in for, and his stale E would
        # inflate the backup all season.
        absent = [r for r in absent
                  if any(gs == season and gt == team and gw < wk for gs, gw, gt in games_of.get(r.gsis_id, ()))
                  or (wk <= p.preseason_grace_weeks
                      and any(gs == season - 1 and gt == team for gs, gw, gt in games_of.get(r.gsis_id, ())))]
        if p.promotion_lookback is not None:
            games = [gw for gw in tgi.get(team, []) if gw < (season, wk)][-p.promotion_lookback:]
            absent = [r for r in absent if any((r.gsis_id, s, w, team) in appear for s, w in games)]
        if not absent or not present:
            continue
        top_out = max(absent, key=lambda r: r.E_base)
        nxt = max(present, key=lambda r: r.E_base)
        if top_out.E_base > nxt.E_base:
            rows.append((nxt.gsis_id, wk, top_out.gsis_id, top_out.E_base))
    return pd.DataFrame(rows, columns=["gsis_id", "week", "promoted_over", "E_over"])


@functools.lru_cache(maxsize=1)
def _live_out_gsis() -> frozenset:
    blob = Q._snap("sleeper_players_nfl.json") or {}
    bridge = SE.gsis_bridge()
    return frozenset(bridge[pid] for pid, m in blob.items()
                     if (m or {}).get("injury_status") in LIVE_OUT_STATUSES and pid in bridge)


@functools.lru_cache(maxsize=4)
def _calibrate_beta_cached(seasons: Tuple[int, ...], base_params: Params) -> Tuple[Tuple[str, float], ...]:
    p = replace(base_params, promote=False, beta=None)
    num: Dict[str, float] = {}
    den: Dict[str, float] = {}
    cnt: Dict[str, int] = {}
    for y in seasons:
        weeks = range(1, 19)
        base = _base_expectations(y, weeks, p)
        ev = _promotion_events(y, base, p)
        if ev.empty:
            continue
        log = _season_log(y)
        actual = dict(zip(zip(log["gsis_id"], log["week"]), log["points"]))
        ev = ev.merge(base[["gsis_id", "week", "position", "E_base"]], on=["gsis_id", "week"])
        for r in ev.itertuples():
            a = actual.get((r.gsis_id, r.week))
            if a is None:           # the backup did not play either; nothing to learn
                continue
            num[r.position] = num.get(r.position, 0.0) + float(a)
            den[r.position] = den.get(r.position, 0.0) + float(r.E_over)
            cnt[r.position] = cnt.get(r.position, 0) + 1
    return tuple(sorted((pos, num[pos] / den[pos]) for pos in num if den[pos] > 0 and cnt[pos] >= 30))


def calibrate_beta(seasons: Sequence[int] = tuple(range(2019, 2026)),
                   params: Params = Params()) -> Dict[str, float]:
    """{position: beta}: across every NFL next-man-up event in `seasons`, the
    promoted backup's actual points over the departed teammate's expectation
    (ratio of sums). Positions with fewer than 30 events are omitted (no
    promotion applied for them)."""
    return dict(_calibrate_beta_cached(tuple(int(s) for s in seasons), replace(params, beta=None)))


def expected_points(season: int, weeks: Optional[Sequence[int]] = None,
                    params: Params = Params()) -> pd.DataFrame:
    """Pre-kickoff expected points for every NFL skill player, per week.

    Columns: gsis_id, week, team, position, E_base, E, weight (effective games of
    history), games_this_season, rookie, source, promoted_over, E_over."""
    weeks = list(weeks) if weeks is not None else list(range(1, 19))
    base = _base_expectations(int(season), weeks, params)
    base["E"] = base["E_base"]
    base["promoted_over"] = None
    base["E_over"] = np.nan
    if params.promote and not base.empty:
        beta = dict(params.beta) if params.beta is not None else calibrate_beta(params=params)
        ev = _promotion_events(int(season), base, params)
        if not ev.empty:
            base = base.drop(columns=["promoted_over", "E_over"]).merge(ev, on=["gsis_id", "week"], how="left")
            lift = base["position"].map(beta).fillna(0.0) * base["E_over"].fillna(0.0)
            promoted = base["promoted_over"].notna() & (lift > base["E_base"])
            base["E"] = np.where(promoted, lift, base["E_base"])
            base.loc[~promoted, ["promoted_over", "E_over"]] = [None, np.nan]
    return base


# ---------------------------------------------------------------------------
# Availability on the league side
# ---------------------------------------------------------------------------
def _taxi(season: int) -> frozenset:
    try:
        ros = Q._snap(f"season_{int(season)}/rosters.json")
    except FileNotFoundError:
        return frozenset()
    return frozenset(str(i) for r in ros for i in (r.get("taxi") or []))


def _live_unavailable(season: int, wk: int) -> set:
    """For a week the build has not exported: Sleeper's current statuses plus
    byes off the cached schedule."""
    blob = Q._snap("sleeper_players_nfl.json") or {}
    out = {pid for pid, m in blob.items() if (m or {}).get("injury_status") in LIVE_OUT_STATUSES}
    path = Q.repo_root() / ".cache" / "nfldata_games.csv"
    if path.exists():
        g = pd.read_csv(path, usecols=["season", "week", "game_type", "home_team", "away_team"])
        g = g[(g["season"] == season) & (g["week"] == wk) & (g["game_type"] == "REG")]
        playing = set(g["home_team"]) | set(g["away_team"])
        if playing:
            out |= {pid for pid, m in blob.items() if (m or {}).get("team") and m["team"] not in playing}
    return out


def stakes(season: int) -> Dict[Tuple[str, int], str]:
    """{(team lower-case, week): reason} for weeks a team had nothing (or
    something perverse) to play for: past its 'Week of playoff elimination'
    in the regular season, a toilet-bowl game (through the 2024 draft,
    winning one cost draft position), or the final regular-season week with
    its seed already locked (`_seed_locked`). Completed seasons only — the build fills
    that column for the in-progress season too, with the current standings
    read as final, so it is not trusted there."""
    out: Dict[Tuple[str, int], str] = {}
    season = int(season)
    if season not in Q.completed_seasons():
        return out
    ty = Q.load_sheet("team_year")
    ty = ty[Q.numeric(ty, "Year") == season]
    reg = Q.season_meta(season).regular_season_weeks
    for t, e in zip(ty["Team"], pd.to_numeric(ty["Week of playoff elimination"], errors="coerce")):
        if pd.notna(e) and e > 0:
            for wk in range(int(e) + 1, reg + 1):
                out[(str(t).lower(), wk)] = "eliminated"
    tw = Q.load_sheet("team_week")
    tw = tw[Q.numeric(tw, "Year") == season]
    for t, wk, nm in zip(tw["Team"], Q.numeric(tw, "Week"), tw["Week Name"]):
        if pd.notna(wk) and "toilet" in str(nm).lower():
            out[(str(t).lower(), int(wk))] = "toilet bowl"
    for t in _seed_locked(season, tw, reg):
        out.setdefault((t, reg), "seed locked")
    return out


@functools.lru_cache(maxsize=1)
def _max_weekly_spread() -> float:
    """Largest (max PF - min PF) in any regular-season week on record: no PF
    tiebreak gap wider than this can close in a single week."""
    tw = Q.load_sheet("team_week")
    tw = tw.assign(_pf=pd.to_numeric(tw["PF"], errors="coerce"),
                   _y=Q.numeric(tw, "Year"), _w=Q.numeric(tw, "Week"))
    g = tw.groupby(["_y", "_w"])["_pf"]
    return float((g.max() - g.min()).max())


def _seed_locked(season: int, tw: pd.DataFrame, reg: int) -> List[str]:
    """Teams whose seed could not move in the final regular-season week under
    ANY result of that week's games. A tie in wins counts as movable unless the
    season PF gap exceeds the largest one-week PF spread the league has ever
    produced (`_max_weekly_spread`), so this is conservative."""
    wk_s = Q.numeric(tw, "Week")
    prior = tw[(wk_s < reg)]
    wins: Dict[str, float] = {}
    pf: Dict[str, float] = {}
    for t, w, x in zip(prior["Team"], prior["Win?"], pd.to_numeric(prior["PF"], errors="coerce")):
        k = str(t).lower()
        wins[k] = wins.get(k, 0.0) + (1.0 if str(w).lower() in ("true", "1") else 0.0)
        pf[k] = pf.get(k, 0.0) + (float(x) if pd.notna(x) else 0.0)
    spread = _max_weekly_spread()
    teams = Q.teams(season)
    games = [(teams.get(a, "").lower(), teams.get(b, "").lower()) for a, b in Q.pairings(season, reg)]
    return locked_seeds(wins, pf, games, spread)


def locked_seeds(wins: Dict[str, float], pf: Dict[str, float],
                 games: Sequence[Tuple[str, str]], spread: float) -> List[str]:
    """Pure core of `_seed_locked`: every win/loss outcome of `games` is
    enumerated; a team is locked when its possible seeds collapse to one. Ties
    in wins are movable unless the PF gap exceeds `spread`."""
    if not wins or not games:
        return []
    possible: Dict[str, set] = {t: set() for t in wins}
    for mask in range(2 ** len(games)):
        final = dict(wins)
        for i, (a, b) in enumerate(games):
            w = a if (mask >> i) & 1 else b
            final[w] = final.get(w, 0.0) + 1
        for t in wins:
            above = sum(1 for u in wins if u != t and final[u] > final[t])
            tied = sum(1 for u in wins if u != t and final[u] == final[t]
                       and abs(pf.get(u, 0.0) - pf.get(t, 0.0)) <= spread)
            above += sum(1 for u in wins if u != t and final[u] == final[t]
                         and pf.get(u, 0.0) - pf.get(t, 0.0) > spread)
            possible[t].update(range(above + 1, above + tied + 2))
    return sorted(t for t, seeds in possible.items() if len(seeds) == 1)


# ---------------------------------------------------------------------------
# Boldness
# ---------------------------------------------------------------------------
def season_weeks(season: int, include_live: bool = True) -> Tuple[List[int], Optional[int]]:
    """(scored weeks within the league calendar, the live week or None)."""
    meta = Q.season_meta(season)
    played = [w for w in Q.played_weeks(season) if w <= meta.last_week]
    live = None
    if include_live and season not in Q.completed_seasons():
        nxt = (max(played) + 1) if played else 1
        try:
            if nxt <= meta.last_week and Q.week(season, nxt):
                live = nxt
        except FileNotFoundError:
            pass
    return played, live


def boldness(season: int, weeks: Optional[Sequence[int]] = None,
             params: Params = Params(), include_live: bool = True) -> pd.DataFrame:
    """One row per start (empty slots counted, not listed): the starter, his E,
    the best eligible available bench option and its E, Boldness, Edge, what
    actually happened, and every flag a reader needs to classify the row."""
    season = int(season)
    played, live = season_weeks(season, include_live)
    wks = [w for w in (list(weeks) if weeks is not None else played + ([live] if live else []))]
    if not wks:
        return pd.DataFrame()
    meta = Q.season_meta(season)
    slots = meta.starting_slots
    E = expected_points(season, wks, params)
    E_idx = {(r.gsis_id, r.week): r for r in E.itertuples()}
    bridge = SE.gsis_bridge()
    elig = Q.season_eligibility(season)
    unavail_hist = Q.unavailable(season)
    taxi = _taxi(season)
    teams = Q.teams(season)
    names = Q.players().names()
    stake = stakes(season)
    started_ever = set()
    rows = []
    for wk in sorted(wks):
        is_live = (wk == live)
        unavail = _live_unavailable(season, wk) if is_live else {pid for pid, w in unavail_hist if w == wk}
        for rid, wr in Q.week(season, wk).items():
            starters = list(wr.starters)
            bench = [b for b in wr.bench if b not in taxi and b not in unavail]

            def info(pid):
                g = bridge.get(pid)
                return E_idx.get((g, wk)) if g else None

            for idx, s in enumerate(starters):
                if s == Q.EMPTY_SLOT or idx >= len(slots):
                    continue
                slot = slots[idx]
                si = info(s)
                cands = [(info(b), b) for b in bench
                         if info(b) is not None and (elig.get(b, frozenset()) & set(slot))]
                ref = max(cands, key=lambda c: c[0].E) if cands else (None, None)
                ri, r = ref
                e_s = float(si.E) if si is not None else np.nan
                e_r = float(ri.E) if ri is not None else np.nan
                edge = e_r - e_s if (si is not None and ri is not None) else np.nan
                rows.append({
                    "Year": season, "Week": wk, "Team": teams.get(rid, f"Roster {rid}"),
                    "Slot": "/".join(slot) if len(slot) > 1 else slot[0],
                    "Starter": names.get(s, s), "Starter ID": s,
                    "Starter position": si.position if si is not None else None,
                    "E starter": round(e_s, 2) if si is not None else None,
                    "Reference": names.get(r, r) if r else None, "Reference ID": r,
                    "Reference position": ri.position if ri is not None else None,
                    "E reference": round(e_r, 2) if ri is not None else None,
                    "Edge": round(edge, 2) if pd.notna(edge) else None,
                    "Boldness": round(max(0.0, edge), 2) if pd.notna(edge) else None,
                    "Starter points": None if is_live else wr.players_points.get(s),
                    "Reference points": None if (is_live or not r) else wr.players_points.get(r),
                    "Starter source": si.source if si is not None else "unresolved",
                    "Starter rookie?": bool(si.rookie) if si is not None else None,
                    "Starter games this season": int(si.games_this_season) if si is not None else None,
                    "Starter promoted over": names.get(_sleeper_of(si.promoted_over), si.promoted_over)
                    if si is not None and isinstance(si.promoted_over, str) else None,
                    "Reference source": ri.source if ri is not None else None,
                    "Reference promoted?": bool(isinstance(ri.promoted_over, str)) if ri is not None else None,
                    "Ref taxi-eligible?": bool(ri is not None and ri.rookie and r not in started_ever),
                    "Starter unavailable?": s in unavail,
                    "Low stakes": stake.get((teams.get(rid, "").lower(), wk)),
                    "Live week?": is_live,
                })
            started_ever.update(p for p in starters if p != Q.EMPTY_SLOT)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Result"] = pd.to_numeric(df["Starter points"], errors="coerce") - pd.to_numeric(df["Reference points"], errors="coerce")
    return df


@functools.lru_cache(maxsize=1)
def _gsis_to_sleeper() -> Dict[str, str]:
    return {g: s for s, g in SE.gsis_bridge().items()}


def _sleeper_of(gsis: Optional[str]) -> Optional[str]:
    return _gsis_to_sleeper().get(gsis) if gsis else None


def team_boldness(season: int, weeks: Optional[Sequence[int]] = None,
                  params: Params = Params(), include_live: bool = True) -> pd.DataFrame:
    """One row per team-week: the ex-ante Max PF (best lineup E allowed, via the
    build's optimiser) minus the expected points of the lineup set."""
    season = int(season)
    played, live = season_weeks(season, include_live)
    wks = list(weeks) if weeks is not None else played + ([live] if live else [])
    E = expected_points(season, wks, params)
    E_idx = {(r.gsis_id, r.week): float(r.E) for r in E.itertuples()}
    bridge = SE.gsis_bridge()
    pos = Q.players().positions()
    unavail_hist = Q.unavailable(season)
    taxi = _taxi(season)
    teams = Q.teams(season)
    rows = []
    for wk in sorted(wks):
        is_live = wk == live
        unavail = _live_unavailable(season, wk) if is_live else {pid for pid, w in unavail_hist if w == wk}
        for rid, wr in Q.week(season, wk).items():
            starters = [s for s in wr.starters if s != Q.EMPTY_SLOT]
            pool = starters + [b for b in wr.bench if b not in taxi and b not in unavail]
            e = {p: E_idx.get((bridge.get(p), wk)) for p in pool}
            unresolved = [p for p, v in e.items() if v is None]
            e = {p: v for p, v in e.items() if v is not None}
            chosen = sum(e.get(s, 0.0) for s in starters)
            best = L.compute_optimal_lineup(e, pos, season)
            rows.append({"Year": season, "Week": wk, "Team": teams.get(rid, f"Roster {rid}"),
                         "Ex-ante max": round(best, 2), "Expected PF": round(chosen, 2),
                         "Team boldness": round(max(0.0, best - chosen), 2),
                         "Unresolved players": len(unresolved), "Live week?": is_live})
    return pd.DataFrame(rows)


def history(seasons: Optional[Sequence[int]] = None, params: Params = Params(),
            include_live: bool = True) -> pd.DataFrame:
    """`boldness()` for every snapshot season (2021 on), concatenated."""
    seasons = seasons or [s for s in Q.snapshot_seasons() if s >= 2021]
    frames = [boldness(s, params=params, include_live=include_live) for s in seasons]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def check_points_reconcile(season: int, min_rate: float = 0.97, tolerance: float = 0.011) -> List[str]:
    """The re-scored game log must reproduce the build's own player_week Points
    for rostered player-weeks it covers. Not an identity — nflverse
    back-corrects and `lotg_points` has a known residual — so a rate."""
    pw = Q.load_sheet("player_week")
    pw = pw[Q.numeric(pw, "Year") == season]
    bridge = SE.gsis_bridge()
    name_to_id = {}
    for pid, nm in Q.players().names().items():
        name_to_id.setdefault(nm, pid)
    log = _season_log(season)
    pts = dict(zip(zip(log["gsis_id"], log["week"]), log["points"]))
    n = agree = 0
    for nm, wk, p in zip(pw["Player"], Q.numeric(pw, "Week"), pd.to_numeric(pw["Points"], errors="coerce")):
        g = bridge.get(name_to_id.get(nm, ""))
        v = pts.get((g, int(wk))) if g and pd.notna(wk) else None
        if v is None or pd.isna(p) or p == 0:
            continue
        n += 1
        agree += abs(v - p) <= tolerance
    if n == 0:
        return [f"{season}: nothing to reconcile"]
    rate = agree / n
    return [] if rate >= min_rate else [f"{season}: re-scored log matches player_week Points on {rate:.3f} of {n}"]


def calibration(df: pd.DataFrame) -> Dict[str, float]:
    """Slope/intercept of Result on Edge over completed, available, resolved starts."""
    d = df[(~df["Live week?"]) & (~df["Starter unavailable?"])].dropna(subset=["Edge", "Result"])
    if len(d) < 30:
        return {"n": len(d)}
    slope, icpt = np.polyfit(d["Edge"].astype(float), d["Result"].astype(float), 1)
    return {"n": int(len(d)), "slope": float(slope), "intercept": float(icpt),
            "r": float(np.corrcoef(d["Edge"].astype(float), d["Result"].astype(float))[0, 1])}


def check_calibration(df: pd.DataFrame, lo: float = -1.4, hi: float = -0.6) -> List[str]:
    """If E is unbiased, Result ≈ -Edge on average: the slope must sit near -1."""
    c = calibration(df)
    if "slope" not in c:
        return [f"too few rows to calibrate ({c['n']})"]
    return [] if lo <= c["slope"] <= hi else [f"calibration slope {c['slope']:.2f} outside [{lo}, {hi}]"]


def check_team_boldness_bounds(season: int, params: Params = Params()) -> List[str]:
    """Team boldness is never negative, and the optimiser fed ACTUAL points
    over the full roster reproduces the build's Max PF (semifinal bonus aside)."""
    probs: List[str] = []
    tb = team_boldness(season, params=params, include_live=False)
    if (tb["Team boldness"] < 0).any():
        probs.append(f"{season}: negative team boldness")
    tw = Q.load_sheet("team_week")
    tw = tw[Q.numeric(tw, "Year") == season]
    built = {(str(t).lower(), int(w)): float(m) for t, w, m in
             zip(tw["Team"], Q.numeric(tw, "Week"), pd.to_numeric(tw["Max PF"], errors="coerce"))
             if pd.notna(w) and pd.notna(m)}
    pos = Q.players().positions()
    teams = Q.teams(season)
    played, _ = season_weeks(season, include_live=False)
    n = agree = 0
    for wk in played[:3]:
        for rid, wr in Q.week(season, wk).items():
            v = L.compute_optimal_lineup(dict(wr.players_points), pos, season)
            b = built.get((teams.get(rid, "").lower(), wk))
            if b is None:
                continue
            n += 1
            agree += abs(v - b) <= 0.02
    if n and agree / n < 0.9:
        probs.append(f"{season}: optimiser on actual points matches Max PF on {agree}/{n}")
    return probs


def tune(seasons: Sequence[int] = (2021, 2022, 2023, 2024, 2025),
         grid_d: Sequence[float] = (0.25, 0.5, 0.75, 1.0),
         grid_k: Sequence[float] = (1.0, 2.0, 4.0)) -> pd.DataFrame:
    """MAE of E against what rostered players actually scored, over a small grid.
    Reported for sensitivity, not to be re-tuned every season (see the playbook's
    forecasting trap about knobs with no interior optimum)."""
    bridge = SE.gsis_bridge()
    out = []
    targets = {}
    for y in seasons:
        rostered = set()
        for wk in season_weeks(y, include_live=False)[0]:
            for wr in Q.week(y, wk).values():
                rostered |= {(bridge.get(p), wk) for p in wr.players if bridge.get(p)}
        log = _season_log(y)
        targets[y] = {(g, w): pt for g, w, pt in zip(log["gsis_id"], log["week"], log["points"])
                      if (g, w) in rostered}
    for d in grid_d:
        for k in grid_k:
            p = Params(prior_season_weight=d, shrink_games=k, promote=False)
            err = []
            for y in seasons:
                e = _base_expectations(y, range(1, 19), p)
                ed = dict(zip(zip(e["gsis_id"], e["week"]), e["E_base"]))
                err += [abs(ed[key] - v) for key, v in targets[y].items() if key in ed]
            out.append({"prior_season_weight": d, "shrink_games": k, "MAE": float(np.mean(err)), "n": len(err)})
    return pd.DataFrame(out).sort_values("MAE")
