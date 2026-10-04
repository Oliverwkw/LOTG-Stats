"""Boldness — how far a lineup call went against what the manager could see.

`player_week` already carries a start/sit signal, "Difference in averages of
best/worst startables over previous 5 games": each starter against the best
startable bench player, on 5-game averages. This is the same comparison, built
out so that it measures boldness rather than hindsight:

* the reference is the bench player with the best PRE-KICKOFF expectation, not
  the one who turned out to score the most that week (the build's column picks
  its reference by actual points, then compares averages);
* "startable" is enforced: he must be able to come into the lineup in the
  starter's place, the other starters reshuffling slots as needed
  (`lineup_fits`), and be available (not on bye / injured / suspended by the
  build's own flags, `inquiry.unavailable`);
* the expectation knows about recency, seasons, rookies and cuffs (below).

## The stat

    Edge     = E[best startable bench player] - E[starter]
    Boldness = max(0, Edge)
    Bust odds = P(the reference outscores the starter), a logistic fit of the
                actual result on Edge (`fit_bust_odds`)

`Team boldness` is the ex-ante Max PF (`best_lineup_value`, fed E, under the
same slots and per-season eligibility as the starts) minus the expected points
of the lineup set, so two starters gambling against the same bench player are
not double-counted.

**Empty slots are not boldness** [per user, 2026-10-02]. A slot left empty is
a tank or a clinched game being coasted (plehv79's thrown 2022 Toilet Semis,
shmuel256 emptying two slots in the 2020 Final once it was won), not a
start/sit gamble. Both halves judge the lineup on the slots that were FILLED
only: the ex-ante max fills only those, and a starter's reference must be able
to take his place among them. Empty slots are counted instead (`Empty slots`).
A dead start (below) is judged the same way, but is not counted as empty.
An empty-slot row still appears in `boldness()` (its reference shows what could
have filled it) but carries no Boldness.

## Expected points

A shrunk, weighted average of the player's own NFL games, scored with the
league's settings FOR THE SEASON BEING JUDGED (the build's `lotg._league_score`
with that season's table: Sleeper's from 2021, the ESPN league's for 2020) —
so 2021 week 1, leaning on 2020 games, re-scores them as PPR.

* **Recency.** A game's weight halves every `recency_half_life` games played
  since. A 40-point breakout moves E straight away; two quiet years behind it
  fade.
* **Between seasons.** On top of recency, a last-season game weighs
  `prior_season_weight`, two back its square, and a game for a different NFL
  team `team_change_weight` more. Week 1 is judged on last year, discounted.
* **Rookies.** A rookie picked in that season's LOTG rookie draft gets a prior
  from the slot (`rookie_slot_priors`): a curve fitted on earlier drafts' picks'
  ROOKIE-YEAR points per game only — Gibbs' 2023, never his 2026 — so this
  year's 1.03 is priced on what 1.03-ish picks did as rookies. A rookie not
  drafted here falls back to past rookies at his position and NFL round. Either
  prior speaks for the first few weeks only: its weight fades linearly to
  nothing by `rookie_prior_weeks` (4), after which the rookie is judged on his
  own games like anyone else — De'Von Achane, the 2023 1.11, was a 9.5
  expectation in week 1 and 16.8 the week after his 51-point game, so starting
  him then was not bold. (Fade length barely moves accuracy: rookie MAE 4.91-4.93
  for anything from 1 week to never; "a few weeks" is a choice, not a fit.)
* **Cuffs (role changes).** When a same-team, same-position teammate with a
  higher E sits out (no stat line and no offensive snap — inactives are known
  before kickoff; in the live week, Sleeper's status) while on that team's
  weekly roster, having played for it this season (or last, in the first
  `preseason_grace_weeks`), the NEXT MAN UP is lifted to a x the teammate's
  E + b x his own, (a, b) per position fitted on every such NFL event
  2019-2025 (`calibrate_beta`). The next man up is the highest-E backup the
  team has used this season (`next_man_must_have_played`): a healthy-scratch
  rookie on his draft-round prior is not in line.

Everything debatable is a field on `Params`; `tune()` reports the sensitivity.

## Guards

* `check_points_reconcile` — the re-scored game log reproduces the build's own
  `player_week["Points"]` (2020's ESPN points included).
* `check_calibration` — the slope of (starter - reference) actual points on
  Edge must sit near -1: E means something.
* `check_team_boldness_bounds` — Team boldness is never negative, and
  `best_lineup_value` fed ACTUAL points reproduces `team_week["Max PF"]`.

## Traps

* **Taxi counts as bench, by design.** Taxi status is not tracked week by week
  anywhere in this dataset, and cannot be: `rosters.json` carries a `taxi` list
  only as of the moment the snapshot was taken (2023 on), and the transaction
  log records no taxi moves. It does not need to be: keeping a player on the
  taxi squad is a lineup decision like benching him, so a taxi player is an
  ordinary bench option here, and parking a productive rookie there reads as
  bold — because it was.
* `Q.unavailable` maps the build's flags to ids by NAME, so two players sharing
  a name share flags. Rare; counted nowhere.
* A DEAD START — a starter flagged unavailable (bye / injured / suspended) who
  scored 0 — is treated exactly like an empty slot [per user, 2026-10-02]: no
  Boldness, and his slot drops out of the lineup comparison. Flagged
  `Dead start?`. A flagged starter who did score keeps his Boldness.
* nflverse's position is a player's, not his role's (Taysom Hill), and an
  offseason depth-chart change is not an injury (Jordan Love 2023): both read
  bold in week 1.
* No matchup, weather or betting input: E is the player's own record only.

BUILD CODE since the boldness PR: the build calls `build_columns()` inside
`build_inputs(...)` for player_week "Boldness" and the team sheets' "Lineup
Boldness", so a change here changes the exports and follows the phase workflow
(plan/MASTER_TODO.md). Run outside the build (scripts/boldness.py, inquiries)
it reads the committed exports and snapshot instead.
"""
from __future__ import annotations

import contextlib
import functools
import json
from dataclasses import dataclass, asdict, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from lotg_support import contracts as C
from lotg_support import external as X
from lotg_support import inquiry as Q
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
    prior_season_weight: float = 0.5   # d: extra weight on a last-season game (tuned with recency)
    recency_half_life: Optional[float] = 8.0  # a game's weight halves every N games played since
                                              # (None: no recency decay). Tuned: 8 beats none, 16
                                              # and 4; 2 is clearly worse (single games are noisy)
    team_change_weight: float = 0.5    # extra multiplier for a game on another NFL team
    shrink_games: float = 2.0          # pseudo-games of prior for a veteran
    rookie_shrink_games: float = 3.0   # pseudo-games of the draft-slot prior for a rookie in week 1
    rookie_prior_weeks: Optional[float] = 4.0  # the slot prior fades linearly to nothing by this week,
                                               # after which a rookie is judged like anyone else
                                               # (None: never fades)
    promotion_lookback: Optional[int] = None  # None: the teammate counts while he is on the team's weekly
                                       # roster and not playing; N: only if he played in one of its last N games
    promote: bool = True               # apply the cuff/role promotion
    preseason_grace_weeks: int = 4     # the absent teammate must have played for the team THIS season,
                                       # except in weeks 1..N where last season counts (preseason injury)
    next_man_must_have_played: bool = True  # once the team has played this season, the next man up
                                            # must have appeared for it (not a scratch on his prior)
    beta: Optional[Tuple[Tuple[str, Tuple[float, float]], ...]] = None  # None -> calibrate_beta():
                                       # {pos: (a, b)}, lift = a x teammate's E + b x own E


# ---------------------------------------------------------------------------
# Build inputs. Run from an inquiry, everything comes from the committed
# exports and snapshot. Run INSIDE the build, those are last run's files (a
# build-only run reuses a snapshot up to a week old and never refreshes its
# matchups), so the build hands over its own in-memory inputs instead and every
# reader below checks them first.
# ---------------------------------------------------------------------------
_INJECTED: Optional[Dict[str, Any]] = None


def _clear_caches() -> None:
    for name, obj in list(globals().items()):
        if callable(getattr(obj, "cache_clear", None)) and name.startswith(("_", "scoring_table")):
            obj.cache_clear()


@contextlib.contextmanager
def build_inputs(*, matchups: Dict[int, Dict[int, List[dict]]],
                 roster_positions: Dict[int, Sequence[str]],
                 teams: Dict[int, Dict[int, str]],
                 unavailable: Dict[int, Set[Tuple[str, int]]],
                 rookie_picks: pd.DataFrame,
                 scoring: Dict[int, Dict[str, float]],
                 score: Callable[..., float],
                 score_map: Dict[str, Tuple[str, ...]],
                 bridge: Dict[str, str]):
    """Point the module at the build's own data for the duration.

    matchups {season: {week: Sleeper matchup dicts}} (late-listing corrected),
    roster_positions {season: Sleeper roster_positions}, teams {season:
    {roster_id: team}}, unavailable {season: {(player_id, week)}} from the
    build's own Bye?/Injury?/Suspension? flags, rookie_picks with Year / Number /
    Player Picked (rookie drafts only), scoring {season: settings}, the build's
    `_league_score` and score map, and its sleeper->gsis bridge."""
    global _INJECTED
    _INJECTED = dict(matchups=matchups, roster_positions=roster_positions, teams=teams,
                     unavailable=unavailable, rookie_picks=rookie_picks, scoring=scoring,
                     score=score, score_map=score_map, bridge=bridge)
    _clear_caches()
    try:
        yield
    finally:
        _INJECTED = None
        _clear_caches()


def build_columns(params: "Params" = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """The exported columns, for every season the build handed over.

    Returns (starts, lineups): starts = Year, Week, Team, Player ID, Boldness
    (one row per filled starting slot); lineups = Year, Week, Team, Lineup
    Boldness, Empty slots. Call inside `build_inputs`."""
    if _INJECTED is None:
        raise RuntimeError("build_columns() needs build_inputs(...)")
    params = params or Params()
    starts, lineups = [], []
    for season in sorted(_INJECTED["matchups"]):
        if not played_weeks(season):
            continue
        b = boldness(season, params=params, include_live=False)
        if not b.empty:
            b = b[b["Starter ID"].notna()].copy()
            # No startable bench player at all = nothing bolder was on offer: 0,
            # not N/A. A starter with no expectation (unresolved) and a dead
            # start (ruled out, scored 0 — judged as an empty slot) stay N/A.
            b.loc[b["Boldness"].isna() & b["E starter"].notna() & ~b["Dead start?"], "Boldness"] = 0.0
            starts.append(b[["Year", "Week", "Team", "Starter ID", "Boldness"]]
                          .rename(columns={"Starter ID": "Player ID"}))
        t = team_boldness(season, params=params, include_live=False)
        if not t.empty:
            lineups.append(t[["Year", "Week", "Team", "Team boldness", "Empty slots"]]
                           .rename(columns={"Team boldness": "Lineup Boldness"}))
    cat = lambda fr, cols: pd.concat(fr, ignore_index=True) if fr else pd.DataFrame(columns=cols)
    return (cat(starts, ["Year", "Week", "Team", "Player ID", "Boldness"]),
            cat(lineups, ["Year", "Week", "Team", "Lineup Boldness", "Empty slots"]))


def _unavailable(season: int) -> Set[Tuple[str, int]]:
    if _INJECTED is not None:
        return set(_INJECTED["unavailable"].get(int(season), set()))
    return Q.unavailable(season)


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


@functools.lru_cache(maxsize=1)
def _build_scorer():
    """The build's own per-row scorer (`lotg._league_score`), as wins_added
    reaches it — one implementation of league scoring, not two."""
    if _INJECTED is not None:
        return _INJECTED["score"], _INJECTED["score_map"]
    from lotg_support import wins_added as W
    W._src_on_path()
    import lotg  # noqa: E402  (src/, import-safe)
    return lotg._league_score, lotg._LEAGUE_SCORE_MAP


@functools.lru_cache(maxsize=16)
def scoring_table(season: int) -> Tuple[Tuple[str, float], ...]:
    """The league's scoring settings for `season`: Sleeper's from 2021, the
    ESPN league's for 2020 (pre-PPR), and 2020's for anything earlier — the
    same choice `wins_added.nflverse_points_from_cache` makes."""
    if _INJECTED is not None and int(season) in _INJECTED["scoring"]:
        table = _INJECTED["scoring"][int(season)]
        return tuple(sorted((str(k), float(v)) for k, v in table.items() if v is not None))
    if _INJECTED is not None and int(season) < min(_INJECTED["scoring"]):
        table = _INJECTED["scoring"][min(_INJECTED["scoring"])]   # pre-league: first season's
        return tuple(sorted((str(k), float(v)) for k, v in table.items() if v is not None))
    from lotg_support import wins_added as W
    if int(season) >= 2021:
        lj = Q.repo_root() / "exports" / "snapshot" / f"season_{int(season)}" / "league.json"
        table = json.loads(lj.read_text()).get("scoring_settings") or {}
    else:
        table = W._espn_2020()["league"]["scoring_settings"]
    return tuple(sorted((str(k), float(v)) for k, v in table.items() if v is not None))


@functools.lru_cache(maxsize=128)
def _season_log(season: int, scoring_season: Optional[int] = None) -> pd.DataFrame:
    """One row per (gsis_id, week) the player TOOK THE FIELD in a regular-season
    game: a stat line, or an offensive snap with none (scored 0, as the build's
    5-game window does). Columns: gsis_id, season, week, team, points, position.

    Points are scored with `scoring_season`'s league settings (default: the
    game's own season). A season is judged on its OWN rules, so 2021 week 1,
    leaning on 2020 games, re-scores them as PPR — 2020 itself was not."""
    score, score_map = _build_scorer()
    table = dict(scoring_table(int(scoring_season if scoring_season is not None else season)))
    raw = SE.weekly_stats(season)
    pos = _player_ids()["pos"]
    cols = [c for cs in score_map.values() for c in cs if c in raw.columns]
    pts = [score({k: (None if pd.isna(v) else v) for k, v in zip(cols, vals)}, table, pos.get(str(g)))
           for g, vals in zip(raw["player_id"].astype(str), raw[cols].itertuples(index=False, name=None))]
    stats = pd.DataFrame({"gsis_id": raw["player_id"].astype(str).to_numpy(),
                          "week": raw["week"].astype(int).to_numpy(),
                          "team": raw["team"].to_numpy(), "points": pts})
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
    stats["position"] = stats["gsis_id"].map(pos)
    stats = stats[stats["position"].isin(POSITIONS)]
    return stats.drop_duplicates(["gsis_id", "week"]).reset_index(drop=True)


def game_log(seasons: Sequence[int], scoring_season: Optional[int] = None) -> pd.DataFrame:
    """The appearance log for several seasons, oldest first, every game scored
    with `scoring_season`'s settings (default: each game's own season)."""
    frames = [_season_log(int(s), scoring_season) for s in seasons if int(s) >= FIRST_LOG_SEASON]
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
        log = _season_log(y, int(season))
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


def _pick_order(number) -> Optional[Tuple[int, int]]:
    try:
        r, k = str(number).split(".")
        return int(r), int(k)
    except (ValueError, AttributeError):
        return None


@functools.lru_cache(maxsize=1)
def _rookie_draft_rows() -> Tuple[Tuple[int, str, int, str], ...]:
    """(draft year, gsis_id, overall pick, position) for every LOTG rookie-draft
    pick that was a real NFL rookie that year (the rookie draft also takes
    veterans — those are not priced by slot)."""
    rp = _INJECTED["rookie_picks"] if _INJECTED is not None else Q.load_sheet("rookie_picks")
    ids = _player_ids()
    bridge = _bridge()
    by_name: Dict[str, List[str]] = {}
    for pid, nm in Q.players().names().items():
        by_name.setdefault(nm, []).append(pid)
    out = []
    for y, grp in rp.groupby(Q.numeric(rp, "Year")):
        if pd.isna(y):
            continue
        order = sorted(((o, nm) for nm, o in ((n, _pick_order(num)) for n, num in
                        zip(grp["Player Picked"], grp["Number"])) if o), key=lambda t: t[0])
        for overall, ((_r, _k), nm) in enumerate(order, start=1):
            cands = [bridge.get(pid) for pid in by_name.get(nm, [])]
            cands = sorted({g for g in cands if g and g in ids.index
                            and ids.at[g, "pos"] in POSITIONS
                            and pd.to_numeric(ids.at[g, "rookie_season"], errors="coerce") == y})
            if len(cands) == 1:
                out.append((int(y), cands[0], overall, ids.at[cands[0], "pos"]))
    return tuple(out)


@functools.lru_cache(maxsize=16)
def _rookie_slot_priors_cached(season: int) -> Tuple[Tuple[str, float], ...]:
    rows = _rookie_draft_rows()
    train = []
    for y, g, overall, pos in rows:
        if y >= season:
            continue
        log = _season_log(y, int(season))          # ROOKIE-YEAR games only, today's rules
        pts = log.loc[log["gsis_id"] == g, "points"]
        if len(pts):
            train.append((np.log(overall), pos, float(pts.mean()), len(pts)))
    if len(train) < 30:
        return ()
    X = np.array([[1.0, lo] + [1.0 if pos == q else 0.0 for q in POSITIONS[1:]] for lo, pos, _, _ in train])
    yv = np.array([t[2] for t in train])
    wv = np.sqrt(np.array([t[3] for t in train], dtype=float))
    coef, *_ = np.linalg.lstsq(X * wv[:, None], yv * wv, rcond=None)
    out = {}
    for y, g, overall, pos in rows:
        if y == season:
            x = np.array([1.0, np.log(overall)] + [1.0 if pos == q else 0.0 for q in POSITIONS[1:]])
            out[g] = max(0.0, float(x @ coef))
    return tuple(sorted(out.items()))


def rookie_slot_priors(season: int) -> Dict[str, float]:
    """{gsis_id: prior} for this season's LOTG rookie-draft picks.

    Fitted on earlier drafts only, on each pick's ROOKIE-YEAR points per game
    (Gibbs' 2023, never his 2026): ppg ~ a + b*ln(overall pick) + position,
    weighted by games played. One pick per slot per year is too thin to average
    slot by slot, hence the curve. Empty for a season with under 30 past
    rookies to learn from (2021, the first rookie draft) — those fall back to
    the NFL-draft-round prior."""
    return dict(_rookie_slot_priors_cached(int(season)))


@functools.lru_cache(maxsize=16)
def _vet_priors_cached(season: int) -> Tuple[Tuple[str, float], ...]:
    log = game_log([season - 1], scoring_season=season)
    if log.empty:
        log = game_log([season - 2], scoring_season=season)
    return tuple(sorted({p: float(g["points"].mean()) for p, g in log.groupby("position")}.items()))


def veteran_priors(season: int) -> Dict[str, float]:
    """{position: mean points per appearance} the previous season — the prior a
    veteran with almost no history is shrunk toward."""
    return dict(_vet_priors_cached(int(season)))


# ---------------------------------------------------------------------------
# Expected points
# ---------------------------------------------------------------------------
def _rostered_gsis(season: int) -> Set[str]:
    """gsis ids of everyone on a league roster in any played week of the season."""
    bridge = _bridge()
    out: Set[str] = set()
    for wk in played_weeks(season):
        for wr in week_rows(season, wk).values():
            for pid in wr.players or wr.starters:
                g = bridge.get(str(pid))
                if g:
                    out.add(g)
    return out


def _base_expectations(season: int, weeks: Sequence[int], p: Params,
                        league_rostered: bool = True) -> pd.DataFrame:
    """E before any role promotion, for every player with history or a rookie
    prior, for each requested week — plus, with `league_rostered`, everyone on
    a league roster that season (the positional prior for no-history players).
    The beta calibration passes False: it is an NFL fit, and the league's
    rosters (the build's vs the snapshot's) must not move it."""
    log = game_log([season - 2, season - 1, season], scoring_season=season)
    ids = _player_ids()
    rpri = rookie_priors(season)
    spri = rookie_slot_priors(season)
    vpri = veteran_priors(season)
    teams_now = _weekly_teams(season)
    rookies = set(ids.index[pd.to_numeric(ids["rookie_season"], errors="coerce") == season])
    rookies &= set(ids.index[ids["pos"].isin(POSITIONS)])
    rostered = _rostered_gsis(season) if league_rostered else set()
    last_team = {}
    _pos = ids["pos"].to_dict() if ids.index.is_unique else None
    pos_of = (lambda g: _pos.get(g)) if _pos is not None else (lambda g: ids["pos"].get(g))
    out = []
    for wk in sorted(set(int(w) for w in weeks)):
        before = log[(log["season"] < season) | (log["week"] < wk)]
        # The player's NFL team THIS week: weekly roster, else his latest game.
        latest = before.sort_values(["season", "week"]).groupby("gsis_id")["team"].last()
        # Rostered players with no game in the window (Philip Rivers' 2025
        # return, Travis Etienne's lost rookie year) still get an E: the
        # positional prior, not N/A.
        players = set(before["gsis_id"]) | rookies | rostered
        cur_team = {g: teams_now.get((g, wk), latest.get(g)) for g in players}
        before = before.sort_values(["season", "week"])
        w = np.power(p.prior_season_weight, (season - before["season"]).to_numpy(dtype=float))
        if p.recency_half_life:
            ago = before.groupby("gsis_id").cumcount(ascending=False).to_numpy(dtype=float)
            w = w * np.power(0.5, ago / float(p.recency_half_life))
        moved = before["team"].to_numpy() != before["gsis_id"].map(cur_team).to_numpy()
        w = np.where(moved & (before["season"].to_numpy() < season), w * p.team_change_weight, w)
        b = before.assign(_w=w, _wp=w * before["points"].to_numpy(),
                          _cur=(before["season"].to_numpy() == season).astype(int))
        agg = b.groupby("gsis_id").agg(W=("_w", "sum"), S=("_wp", "sum"),
                                       n_cur=("_cur", "sum"),
                                       n_all=("week", "size"))
        # Plain dicts for the per-player lookups below: `.at` on the frame
        # was most of this loop's runtime.
        aW, aS, aN = agg["W"].to_dict(), agg["S"].to_dict(), agg["n_cur"].to_dict()
        rows = []
        for g in players:
            pos = pos_of(g)
            if pos not in POSITIONS:
                continue
            Wsum, Ssum = (float(aW[g]), float(aS[g])) if g in aW else (0.0, 0.0)
            is_rookie = g in rookies
            if is_rookie:
                if g in spri:          # picked in this season's LOTG rookie draft
                    prior, how = spri[g], "slot"
                else:                  # not drafted here: NFL draft round
                    prior = rpri.get((pos, _bucket(ids["draft_round"].get(g))), rpri.get((pos, "*"), vpri.get(pos, 0.0)))
                    how = "nfl round"
                # The slot speaks for the first few weeks only, then it is the
                # player's own games (shrunk like anyone's): fade the slot's
                # pseudo-games out and the ordinary positional prior in.
                fade = 1.0 if not p.rookie_prior_weeks else max(0.0, 1.0 - (wk - 1) / float(p.rookie_prior_weeks))
                k_r, k_v = p.rookie_shrink_games * fade, p.shrink_games * (1.0 - fade)
                vp = vpri.get(pos, 0.0)
                k = k_r + k_v
                prior = (k_r * prior + k_v * vp) / k if k > 0 else vp
                source = (f"rookie prior ({how})" if Wsum == 0 and fade > 0
                          else (f"rookie history ({how})" if fade > 0 else "history"))
            else:
                prior = vpri.get(pos, 0.0)
                k = p.shrink_games
                source = "history" if Wsum > 0 else "positional prior"
            rows.append((g, wk, cur_team.get(g), pos, (Ssum + k * prior) / (Wsum + k), Wsum,
                         int(aN[g]) if g in aN else 0, is_rookie, source))
        out.append(pd.DataFrame(rows, columns=["gsis_id", "week", "team", "position", "E_base",
                                               "weight", "games_this_season", "rookie", "source"]))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _team_game_index(log: pd.DataFrame) -> Dict[str, List[Tuple[int, int]]]:
    """team -> its game weeks (season, week), in order, as seen in the log."""
    tg = log[["team", "season", "week"]].drop_duplicates().sort_values(["season", "week"])
    return {t: list(zip(g["season"], g["week"])) for t, g in tg.groupby("team")}


def _promotion_events(season: int, base: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Rows (gsis_id, week, promoted_over, E_over): the NEXT MAN UP — the
    highest-E available player at a team-position whom the team has used this
    season (`next_man_must_have_played`) — when a teammate with a
    higher E sits out the week while on that team's weekly roster (and, if
    `promotion_lookback` is set, after playing in one of the team's last N
    games). Only the next man up is promoted: calibrating over every backup
    behind an absent starter (RB3s, WR5s) dilutes beta to the point where a
    real handcuff reads as bold for starting.

    "Sat out" is known before kickoff (inactives are announced ~90 minutes
    ahead): in a played week it is "no stat line and no offensive snap"; in a
    week not yet played it is Sleeper's current status (`LIVE_OUT_STATUSES`)."""
    log = game_log([season - 1, season], scoring_season=season)
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
    # Grouped by hand from ONE itertuples pass (rows keep their frame order
    # within a group, groups come in sorted key order — what groupby gave):
    # an itertuples per group, three times over, was most of this function.
    groups: Dict[Tuple[Any, Any, Any], list] = {}
    for r in base[base["team"].notna()].itertuples():
        groups.setdefault((r.week, r.team, r.position), []).append(r)
    for (wk, team, pos) in sorted(groups):
        grp = groups[(wk, team, pos)]
        if len(grp) < 2:
            continue
        if wk in played_weeks:
            sat = lambda g: (g, wk) not in played_team
            present = [r for r in grp if played_team.get((r.gsis_id, wk)) == team]
        else:
            sat = lambda g: g in live_out
            present = [r for r in grp
                       if not sat(r.gsis_id) and on_roster.get((r.gsis_id, wk), r.team) == team]
        # The absent teammate must be on this team's weekly roster THIS week
        # (injured reserve included) — a retired or released player keeps his
        # last team in the game log and would otherwise "sit out" forever.
        absent = [r for r in grp if sat(r.gsis_id) and on_roster.get((r.gsis_id, wk)) == team]
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
        # The next man up is someone the team has actually used: once it has
        # played a game this season, a backup who has not appeared for it
        # (a healthy-scratch rookie on his draft-round prior) is not next in
        # line, however his prior compares with the incumbent backup's.
        if p.next_man_must_have_played and any(s == season and w < wk for s, w in tgi.get(team, ())):
            used = [r for r in present
                    if any(gs == season and gt == team and gw < wk for gs, gw, gt in games_of.get(r.gsis_id, ()))]
            present = used or present
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
def _calibrate_beta_cached(seasons: Tuple[int, ...], base_params: Params) -> Tuple[Tuple[str, Tuple[float, float]], ...]:
    p = replace(base_params, promote=False, beta=None)
    rows: Dict[str, List[Tuple[float, float, float]]] = {}
    for y in seasons:
        weeks = range(1, 19)
        base = _base_expectations(y, weeks, p, league_rostered=False)
        ev = _promotion_events(y, base, p)
        if ev.empty:
            continue
        log = _season_log(y, y)
        actual = dict(zip(zip(log["gsis_id"], log["week"]), log["points"]))
        ev = ev.merge(base[["gsis_id", "week", "position", "E_base"]], on=["gsis_id", "week"])
        for r in ev.itertuples():
            a = actual.get((r.gsis_id, r.week))
            if a is None:           # the backup did not play either; nothing to learn
                continue
            rows.setdefault(r.position, []).append((float(r.E_over), float(r.E_base), float(a)))
    out = []
    for pos, rs in rows.items():
        if len(rs) < 30:
            continue
        m = np.asarray(rs)
        a, b = np.linalg.lstsq(m[:, :2], m[:, 2], rcond=None)[0]
        out.append((pos, (float(a), float(b))))
    return tuple(sorted(out))


def calibrate_beta(seasons: Sequence[int] = tuple(range(2019, 2026)),
                   params: Params = Params()) -> Dict[str, Tuple[float, float]]:
    """{position: (a, b)}: the next man up is expected to score
    a x the departed teammate's E + b x his own E. Least squares (no
    intercept) over every NFL next-man-up event in `seasons` where the backup
    played. Positions with fewer than 30 events are omitted (no promotion).

    Two terms, not one ratio: a single beta x the teammate's E (the first
    version) is right on average but not across the range — out of sample it
    overrated the weakest quarter of backups by about 3 points at every
    position and underrated the strongest quarter by about 2.5. A backup's own
    record says how much of the role he inherits; the two-term fit is
    unbiased in every quartile of backup-to-starter ratio (2019-2025, leave
    one season out) and has the lower error."""
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
            coef = base["position"].map(beta)
            lift = (coef.map(lambda c: c[0] if isinstance(c, tuple) else 0.0) * base["E_over"].fillna(0.0)
                    + coef.map(lambda c: c[1] if isinstance(c, tuple) else 0.0) * base["E_base"])
            promoted = base["promoted_over"].notna() & (lift > base["E_base"])
            base["E"] = np.where(promoted, lift, base["E_base"])
            base.loc[~promoted, ["promoted_over", "E_over"]] = [None, np.nan]
    return base


# ---------------------------------------------------------------------------
# Availability on the league side
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# One season's league side: snapshot seasons from Sleeper, 2020 from the ESPN
# backfill (`wins_added._espn_2020`, the same Sleeper-shaped emit the build's
# Wins added uses), so every function below reads lineups one way.
# ---------------------------------------------------------------------------
def _espn() -> Dict:
    from lotg_support import wins_added as W
    return W._espn_2020()


def season_slots(season: int) -> Tuple[Tuple[str, ...], ...]:
    if _INJECTED is not None:
        rp = _INJECTED["roster_positions"].get(int(season)) or ()
        return tuple(Q._FLEX_POOL.get(p, (p,)) for p in rp if p not in ("BN", "IR", "TAXI"))
    meta = Q.season_meta(int(season))
    if meta.starting_slots:
        return tuple(meta.starting_slots)
    from lotg_support import wins_added as W
    return W._slots_for(_espn()["league"]["roster_positions"])


@functools.lru_cache(maxsize=64)
def _week_rows_cached(season: int, wk: int) -> Tuple[Tuple[int, Q.WeekRow], ...]:
    if _INJECTED is not None:
        rows = _INJECTED["matchups"].get(int(season), {}).get(int(wk)) or []
    elif Q.season_meta(season).has_snapshot:
        return tuple(Q.week(season, wk).items())
    else:
        rows = _espn()["matchups_by_week"].get(int(wk)) or []
    return tuple((int(r["roster_id"]), Q.WeekRow(
        roster_id=int(r["roster_id"]), matchup_id=r.get("matchup_id"),
        points=float(r.get("points") or 0.0),
        starters=tuple(str(p) for p in (r.get("starters") or ())),
        players=tuple(str(p) for p in (r.get("players") or ())),
        players_points={str(k): float(v or 0.0) for k, v in (r.get("players_points") or {}).items()},
    )) for r in rows)


def week_rows(season: int, wk: int) -> Dict[int, Q.WeekRow]:
    """{roster_id: WeekRow} for any season with lineups, 2020 included."""
    return dict(_week_rows_cached(int(season), int(wk)))


def played_weeks(season: int) -> List[int]:
    if _INJECTED is not None:
        return [w for w in sorted(_INJECTED["matchups"].get(int(season), {}))
                if any(r.points for r in week_rows(season, w).values())]
    meta = Q.season_meta(int(season))
    if meta.has_snapshot:      # Q.played_weeks stops at the build's last finalized week
        return [w for w in Q.played_weeks(season) if w <= meta.last_week]
    done = Q.finalized_week(int(season))
    last = meta.last_week if done is None else min(meta.last_week, done)
    return [w for w in sorted(_espn()["matchups_by_week"]) if w <= last
            and any(r.points for r in week_rows(season, w).values())]


@functools.lru_cache(maxsize=16)
def _teams_cached(season: int) -> Tuple[Tuple[int, str], ...]:
    if _INJECTED is not None:
        return tuple((int(k), str(v)) for k, v in _INJECTED["teams"].get(int(season), {}).items() if v)
    if Q.season_meta(season).has_snapshot:
        return tuple(Q.teams(season).items())
    d = _espn()
    users = {u["user_id"]: u.get("display_name") for u in d["users"]}
    return tuple((int(r["roster_id"]), Q.canonical_team(users.get(r["owner_id"], f"Roster {r['roster_id']}")))
                 for r in d["rosters"])


def season_teams(season: int) -> Dict[int, str]:
    return dict(_teams_cached(int(season)))


@functools.lru_cache(maxsize=16)
def _eligibility_cached(season: int) -> Tuple[Tuple[str, frozenset], ...]:
    if _INJECTED is None and Q.season_meta(season).has_snapshot:
        return tuple(Q.season_eligibility(season).items())
    # 2020: Sleeper's position (or the ESPN emit's) plus every strict slot the
    # player was really fielded in — the same rule season_eligibility uses.
    base = dict(Q.players().positions())
    if int(season) <= 2020:
        for pid, m in _espn()["player_meta"].items():
            base.setdefault(str(pid), m.get("pos"))
    slots = season_slots(season)
    out: Dict[str, set] = {pid: ({p} if p else set()) for pid, p in base.items()}
    for wk in played_weeks(season):
        for wr in week_rows(season, wk).values():
            for idx, pid in enumerate(wr.starters):
                if pid != Q.EMPTY_SLOT and idx < len(slots) and len(slots[idx]) == 1:
                    out.setdefault(pid, set()).add(slots[idx][0])
    return tuple((pid, frozenset(v)) for pid, v in out.items() if v)


def season_eligibility(season: int) -> Dict[str, frozenset]:
    return dict(_eligibility_cached(int(season)))


@functools.lru_cache(maxsize=1)
def _bridge() -> Dict[str, str]:
    """sleeper id -> gsis: the inquiry bridge, plus the 2020 emit's own ids (or,
    inside the build, the build's own bridge first)."""
    out = dict(_INJECTED["bridge"]) if _INJECTED is not None else {}
    for k, v in SE.gsis_bridge().items():
        out.setdefault(k, v)
    for pid, m in _espn()["player_meta"].items():
        g = str((m or {}).get("gsis_id") or "").strip()
        if g and g.lower() != "nan":
            out.setdefault(str(pid), g)
    return out


def season_weeks(season: int, include_live: bool = True) -> Tuple[List[int], Optional[int]]:
    """(scored weeks within the league calendar, the live week or None)."""
    meta = Q.season_meta(season)
    played = played_weeks(season)
    live = None
    if include_live and meta.has_snapshot and season not in Q.completed_seasons():
        nxt = (max(played) + 1) if played else 1
        try:
            if nxt <= meta.last_week and Q.week(season, nxt):
                live = nxt
        except FileNotFoundError:
            pass
    return played, live


def lineup_fits(players: Sequence[str], slots: Sequence[Tuple[str, ...]],
                elig: Dict[str, frozenset]) -> bool:
    """Can these players all start at once, each in a slot he is eligible for?
    Bipartite matching (Kuhn) — ten slots, so cheap. A player missing from
    `elig` is eligible nowhere."""
    if len(players) > len(slots):
        return False
    owner: Dict[int, int] = {}
    pos = [elig.get(p, frozenset()) for p in players]

    def place(i: int, seen: set) -> bool:
        for j, slot in enumerate(slots):
            if j in seen or not (pos[i] & set(slot)):
                continue
            seen.add(j)
            if j not in owner or place(owner[j], seen):
                owner[j] = i
                return True
        return False

    return all(place(i, set()) for i in range(len(players)))


def best_lineup_value(values: Dict[str, float], slots: Sequence[Tuple[str, ...]],
                      elig: Dict[str, frozenset]) -> float:
    """The most points any legal lineup could hold: every player in `values` may
    start, each in a slot he is eligible for (the rules `lineup_fits` applies to
    the starts). Exact, not a heuristic: the sets of players who can start
    together form a transversal matroid, so taking players best-first and
    keeping each one who still fits is optimal. A slot no one can fill counts 0.

    Not `lineup.compute_optimal_lineup`: that one knows a single (current)
    position per player, so a WR-eligible-that-season RB (Cordarrelle
    Patterson, 2021) could not be placed at WR and the "best" lineup came out
    below the one actually set."""
    chosen: List[str] = []
    total = 0.0
    for p, v in sorted(values.items(), key=lambda kv: -kv[1]):
        if v <= 0 or len(chosen) == len(slots):
            break
        if lineup_fits(chosen + [p], slots, elig):
            chosen.append(p)
            total += v
    return total


def filled_slots(starters: Sequence[str], slots: Sequence[Tuple[str, ...]]
                 ) -> Tuple[List[str], List[Tuple[str, ...]], int]:
    """(the starters who filled a slot, the slots they filled, how many slots
    were left empty). Sleeper marks an empty slot with `Q.EMPTY_SLOT`; the 2020
    ESPN lineups just list fewer starters, so the unlisted tail counts empty."""
    starters = list(starters)[:len(slots)]
    idx = [i for i, p in enumerate(starters) if p != Q.EMPTY_SLOT]
    return [starters[i] for i in idx], [slots[i] for i in idx], len(slots) - len(idx)


def dead_starts(wr: "Q.WeekRow", unavail: Set[str], is_live: bool) -> Set[str]:
    """Starters ruled out (bye / injured / suspended) who scored 0: judged as
    empty slots, not as bold starts. None in a live week (no points yet)."""
    if is_live:
        return set()
    return {s for s in wr.starters if s != Q.EMPTY_SLOT and s in unavail
            and float(wr.players_points.get(s) or 0.0) == 0.0}


def boldness(season: int, weeks: Optional[Sequence[int]] = None,
             params: Params = Params(), include_live: bool = True) -> pd.DataFrame:
    """One row per starting slot: the starter (an empty slot is a row with
    E = 0, Starter "Empty slot" and no Boldness), his E, the best STARTABLE
    available bench player (`lineup_fits`, among the FILLED slots) and his E,
    Boldness, Edge, what actually happened, and every flag a reader needs to
    classify the row."""
    season = int(season)
    played, live = season_weeks(season, include_live)
    wks = [w for w in (list(weeks) if weeks is not None else played + ([live] if live else []))]
    if not wks:
        return pd.DataFrame()
    slots = season_slots(season)
    E = expected_points(season, wks, params)
    E_idx = {(r.gsis_id, r.week): r for r in E.itertuples()}
    bridge = _bridge()
    elig = season_eligibility(season)
    unavail_hist = _unavailable(season)
    teams = season_teams(season)
    names = Q.players().names()
    rows = []
    for wk in sorted(wks):
        is_live = (wk == live)
        unavail = _live_unavailable(season, wk) if is_live else {pid for pid, w in unavail_hist if w == wk}
        for rid, wr in week_rows(season, wk).items():
            starters = list(wr.starters)
            # Taxi = bench, by design (see the module traps).
            bench = [b for b in wr.bench if b not in unavail]

            def info(pid):
                g = bridge.get(pid)
                return E_idx.get((g, wk)) if g else None

            dead = dead_starts(wr, unavail, is_live)
            filled, filled_sl, _ = filled_slots(
                [Q.EMPTY_SLOT if p in dead else p for p in starters], slots)
            for idx, s in enumerate(starters):
                if idx >= len(slots):
                    continue
                slot = slots[idx]
                empty = s == Q.EMPTY_SLOT
                is_dead = s in dead
                si = None if empty else info(s)
                # Best STARTABLE bench player: anyone who could come into the
                # lineup in his place, the other starters reshuffling slots as
                # needed — not only a same-slot swap. Only the filled slots
                # count (empty slots are not boldness); for an empty-slot row,
                # what could have filled THAT slot.
                others = [p for p in filled if p != s]
                fit_sl = (filled_sl + [slot]) if (empty or is_dead) else filled_sl
                cands = [(info(b), b) for b in bench
                         if info(b) is not None and lineup_fits(others + [b], fit_sl, elig)]
                ref = max(cands, key=lambda c: c[0].E) if cands else (None, None)
                ri, r = ref
                e_s = 0.0 if empty else (float(si.E) if si is not None else np.nan)
                e_r = float(ri.E) if ri is not None else np.nan
                edge = e_r - e_s if (pd.notna(e_s) and ri is not None) else np.nan
                rows.append({
                    "Year": season, "Week": wk, "Team": teams.get(rid, f"Roster {rid}"),
                    "Slot": "/".join(slot) if len(slot) > 1 else slot[0],
                    "Starter": "Empty slot" if empty else names.get(s, s), "Starter ID": None if empty else s,
                    "Starter position": si.position if si is not None else None,
                    "E starter": round(e_s, 2) if pd.notna(e_s) else None,
                    "Reference": names.get(r, r) if r else None, "Reference ID": r,
                    "Reference position": ri.position if ri is not None else None,
                    "E reference": round(e_r, 2) if ri is not None else None,
                    "Edge": round(edge, 2) if pd.notna(edge) else None,
                    "Boldness": round(max(0.0, edge), 2) if (pd.notna(edge) and not empty and not is_dead) else None,
                    "Starter points": None if is_live else (0.0 if empty else wr.players_points.get(s)),
                    "Reference points": None if (is_live or not r) else wr.players_points.get(r),
                    "Starter source": "empty slot" if empty else (si.source if si is not None else "unresolved"),
                    "Starter rookie?": bool(si.rookie) if si is not None else None,
                    "Starter games this season": int(si.games_this_season) if si is not None else None,
                    "Starter promoted over": names.get(_sleeper_of(si.promoted_over), si.promoted_over)
                    if si is not None and isinstance(si.promoted_over, str) else None,
                    "Reference source": ri.source if ri is not None else None,
                    "Reference promoted?": bool(isinstance(ri.promoted_over, str)) if ri is not None else None,
                    "Starter unavailable?": (not empty) and s in unavail,
                    "Dead start?": is_dead,
                    "Live week?": is_live,
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Result"] = pd.to_numeric(df["Starter points"], errors="coerce") - pd.to_numeric(df["Reference points"], errors="coerce")
    return df


@functools.lru_cache(maxsize=1)
def _gsis_to_sleeper() -> Dict[str, str]:
    return {g: s for s, g in _bridge().items()}


def _sleeper_of(gsis: Optional[str]) -> Optional[str]:
    return _gsis_to_sleeper().get(gsis) if gsis else None


def team_boldness(season: int, weeks: Optional[Sequence[int]] = None,
                  params: Params = Params(), include_live: bool = True) -> pd.DataFrame:
    """One row per team-week: the ex-ante Max PF (best lineup E allowed,
    `best_lineup_value`, over the slots the manager FILLED) minus the expected
    points of the lineup set, and how many slots were left empty."""
    season = int(season)
    played, live = season_weeks(season, include_live)
    wks = list(weeks) if weeks is not None else played + ([live] if live else [])
    E = expected_points(season, wks, params)
    E_idx = {(r.gsis_id, r.week): float(r.E) for r in E.itertuples()}
    bridge = _bridge()
    slots = season_slots(season)
    elig = season_eligibility(season)
    unavail_hist = _unavailable(season)
    teams = season_teams(season)
    rows = []
    for wk in sorted(wks):
        is_live = wk == live
        unavail = _live_unavailable(season, wk) if is_live else {pid for pid, w in unavail_hist if w == wk}
        for rid, wr in week_rows(season, wk).items():
            _, _, n_empty = filled_slots(wr.starters, slots)
            dead = dead_starts(wr, unavail, is_live)
            starters, filled_sl, _ = filled_slots(
                [Q.EMPTY_SLOT if p in dead else p for p in wr.starters], slots)
            pool = starters + [b for b in wr.bench if b not in unavail]
            e = {p: E_idx.get((bridge.get(p), wk)) for p in pool}
            unresolved = [p for p, v in e.items() if v is None]
            e = {p: v for p, v in e.items() if v is not None}
            chosen = sum(e.get(s, 0.0) for s in starters)
            best = best_lineup_value(e, filled_sl, elig)
            rows.append({"Year": season, "Week": wk, "Team": teams.get(rid, f"Roster {rid}"),
                         "Ex-ante max": round(best, 2), "Expected PF": round(chosen, 2),
                         "Team boldness": round(max(0.0, best - chosen), 2),
                         "Empty slots": int(n_empty),
                         "Unresolved players": len(unresolved), "Live week?": is_live})
    return pd.DataFrame(rows)


def history(seasons: Optional[Sequence[int]] = None, params: Params = Params(),
            include_live: bool = True) -> pd.DataFrame:
    """`boldness()` for every snapshot season (2021 on), concatenated."""
    seasons = seasons or sorted(set(Q.export_seasons()) | set(Q.snapshot_seasons()))
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
    bridge = _bridge()
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


def fit_bust_odds(df: pd.DataFrame) -> Tuple[float, float]:
    """(a, b) of P(reference outscores starter) = 1 / (1 + exp(-(a + b*Edge))),
    fitted by logistic regression (Newton's method) on every completed start
    with an available starter — low-stakes and tank weeks included. In-sample
    when applied to the same history —
    say so when quoting it."""
    d = df[(~df["Live week?"]) & (~df["Starter unavailable?"])]
    d = d.dropna(subset=["Edge", "Result"])
    d = d[d["Result"] != 0]
    x = d["Edge"].to_numpy(dtype=float)
    y = (d["Result"].to_numpy(dtype=float) < 0).astype(float)
    beta = np.zeros(2)
    X = np.column_stack([np.ones_like(x), x])
    for _ in range(50):
        pr = 1 / (1 + np.exp(-X @ beta))
        g = X.T @ (y - pr)
        H = (X * (pr * (1 - pr))[:, None]).T @ X
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-9:
            break
    return float(beta[0]), float(beta[1])


def with_bust_odds(df: pd.DataFrame, coef: Optional[Tuple[float, float]] = None) -> pd.DataFrame:
    """Adds 'Bust odds': the calibrated chance the reference outscores the
    starter, from `fit_bust_odds` (fitted on `df` itself unless `coef` given)."""
    a, b = coef if coef is not None else fit_bust_odds(df)
    edge = pd.to_numeric(df["Edge"], errors="coerce")
    return df.assign(**{"Bust odds": (1 / (1 + np.exp(-(a + b * edge)))).round(3)})


def check_calibration(df: pd.DataFrame, lo: float = -1.4, hi: float = -0.6) -> List[str]:
    """If E is unbiased, Result ≈ -Edge on average: the slope must sit near -1."""
    c = calibration(df)
    if "slope" not in c:
        return [f"too few rows to calibrate ({c['n']})"]
    return [] if lo <= c["slope"] <= hi else [f"calibration slope {c['slope']:.2f} outside [{lo}, {hi}]"]


def check_team_boldness_bounds(season: int, params: Params = Params()) -> List[str]:
    """Team boldness is never negative, and `best_lineup_value` fed ACTUAL
    points over the full roster reproduces the build's Max PF (semifinal bonus
    aside) — the ex-ante max is the same search, fed E."""
    probs: List[str] = []
    tb = team_boldness(season, params=params, include_live=False)
    if (tb["Team boldness"] < 0).any():
        probs.append(f"{season}: negative team boldness")
    tw = Q.load_sheet("team_week")
    tw = tw[Q.numeric(tw, "Year") == season]
    built = {(str(t).lower(), int(w)): float(m) for t, w, m in
             zip(tw["Team"], Q.numeric(tw, "Week"), pd.to_numeric(tw["Max PF"], errors="coerce"))
             if pd.notna(w) and pd.notna(m)}
    slots, elig = season_slots(season), season_eligibility(season)
    teams = season_teams(season)
    played, _ = season_weeks(season, include_live=False)
    n = agree = 0
    for wk in played[:3]:
        for rid, wr in week_rows(season, wk).items():
            v = best_lineup_value(dict(wr.players_points), slots, elig)
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
         grid_k: Sequence[float] = (1.0, 2.0, 4.0),
         grid_h: Sequence[Optional[float]] = (None,)) -> pd.DataFrame:
    """MAE of E against what rostered players actually scored, over a small grid.
    Reported for sensitivity, not to be re-tuned every season (see the playbook's
    forecasting trap about knobs with no interior optimum)."""
    bridge = _bridge()
    out = []
    targets = {}
    for y in seasons:
        rostered = set()
        for wk in season_weeks(y, include_live=False)[0]:
            for wr in week_rows(y, wk).values():
                rostered |= {(bridge.get(p), wk) for p in wr.players if bridge.get(p)}
        log = _season_log(y)
        targets[y] = {(g, w): pt for g, w, pt in zip(log["gsis_id"], log["week"], log["points"])
                      if (g, w) in rostered}
    for d in grid_d:
        for h in grid_h:
            for k in grid_k:
                p = Params(prior_season_weight=d, recency_half_life=h, shrink_games=k, promote=False)
                err = []
                for y in seasons:
                    e = _base_expectations(y, range(1, 19), p)
                    ed = dict(zip(zip(e["gsis_id"], e["week"]), e["E_base"]))
                    err += [abs(ed[key] - v) for key, v in targets[y].items() if key in ed]
                out.append({"prior_season_weight": d, "recency_half_life": h, "shrink_games": k,
                            "MAE": float(np.mean(err)), "n": len(err)})
    return pd.DataFrame(out).sort_values("MAE")
