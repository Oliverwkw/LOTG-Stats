"""Wins added: how many games a trade or an add/drop actually swung.

Two columns on every row of `trades` and `add_drops`: `Wins added` (the total)
and `Wins added per season` (the same, as a rate: × 17 / games the team has
played since the move — one loss the week after a drop reads −17).

THE RULE
--------
For every week from the move to today — regular season, playoffs, 3rd place
and the toilet bracket alike, each week on its own — replay the team's game
against the opponent it really played, as if the move had never happened:

    v(week) = R_real − R_counterfactual        R = 1 win, ½ tie, 0 loss
    Wins added = Σ v(week)

so a loss the move turned into a win is +1 and a win it turned into a loss
is −1. Nothing is re-seeded and no bracket is re-run. The 2026+ two-week final
is one game (both weeks' points summed).

WHAT THE COUNTERFACTUAL CHANGES
-------------------------------
* Everything the team GAVE UP is back on its roster from the move to today —
  whatever happened to what came back — until the league lets him go (no
  roster for 4 straight weeks) or the team re-acquires him (`_given_up`). A
  given-up pick is the player actually drafted with it, from his rookie season
  on.
* Everything the team RECEIVED leaves its roster while the team holds it, and
  the account follows it forward through the team's own later trades
  ("lineage"): a received pick becomes the player the team drafted with it; a
  received player traded on passes the lineage to that trade's return, at the
  share of the team's side he made up — KTC at that trade's date, FAAB
  weighted 0 (`_downstream_share`). The share is read as a probability: each
  week the counterfactual is evaluated with that return removed (probability
  s) and kept (1 − s), and the two outcomes are averaged — a scrub traded for a
  4th that later anchors a superstar deal at 3% of its value earns 3% of the
  superstar's swings. Dropping a lineage player ends the lineage.
* FAAB is out of the calculation entirely: selling a player for FAAB alone is
  a pure drop, buying one for FAAB alone is a pure add.
* The OPPONENT that week is adjusted only if its roster differs in the
  counterfactual: a given-up player it really held is gone (he is ours), and
  the team that sent us a player gets him back while we still hold him.

THE LINEUP RULE (`cf_lineup_points`)
------------------------------------
No start/sit decision is remade beyond what the change forces. Starting from
the real lineup, with that week's real points:
  1. starters who are not on the counterfactual roster leave their slots;
  2. an arriving player (one who is on the counterfactual roster but was not on
     the real one) may take an open slot or displace a starter, if he is
     eligible and it raises the score;
  3. an open slot no arrival fills goes to the best eligible bench player — a
     forced fill, at most one per departed starter. Bench players never
     displace a starter;
  4. players may move between slots to make that work (an RB can leave the RB
     slot for the flex so a WR can take a slot only he fits), as long as the
     lineup stays legal under the season's slot template.
A player entering the lineup who was not started by ANY team that week (a
bench player, or an arrival who sat on someone's bench or on waivers) counts
for at most 1.5 x his average over his previous 3 NFL games
(`CAP_MULTIPLIER`, `CAP_GAMES`), so a bench boom nobody would have started
does not swing a counterfactual. Every substitution must also be plausible:
the incoming player's 3-game average at least the outgoing one's minus 5
(`PLAUSIBLE_MARGIN`). A player with fewer than 3 prior NFL games (a rookie's
first three) is never moved into a counterfactual lineup, but may be moved out
of one (`Report.unproven_blocked` lists the blocked entries).

DATA
----
2021+ lineups and points come from the Sleeper snapshot (`inquiry.week`, with
the build's late-listing correction); 2020 from the ESPN backfill
(`src/espn_2020.emit_sleeper_2020`), which speaks the same shape. Real results
are `team_week` PF (with the +5 semifinal bonus) against `team_week` Opponent.
A player on nobody's roster that week, and every "previous 3 games" average,
use his nflverse lines under that season's league scoring
(`nflverse_points_from_cache`). The build persists its sleeper -> gsis bridge
(`exports/raw/wins_added_gsis_bridge.csv`) so a recompute scores the same
games. The moves are read from the two sheets
themselves, so the build and a local recompute go through one code path.

Nothing here writes anything; the build calls `compute` and stores the
column.
"""
from __future__ import annotations

import bisect
import itertools
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

from lotg_support import inquiry as Q
from lotg_support.replay import is_legal

COLUMN = "Wins added"
RATE_COLUMN = "Wins added per season"
SEASON_GAMES = 17          # "per season" = per 17 games, every year (2020 had 16)
CAP_MULTIPLIER = 1.5
CAP_GAMES = 3
# A counterfactual substitution must be one the manager could reasonably have
# made: the incoming player's last-3-game average at least the outgoing
# player's minus this many points (`cf_lineup_points`).
PLAUSIBLE_MARGIN = 5.0
# Lineage returns with a share strictly between 0 and 1 that STARTED in a week
# are enumerated exactly; past this many (never seen in this league's data) the
# rest are rounded to removed/kept at 50%.
MAX_ENUMERATED_GROUPS = 6
TWO_WEEK_FINAL_FROM = 2026
EMPTY = Q.EMPTY_SLOT

WeekKey = Tuple[int, int]


# ---------------------------------------------------------------------------
# The league, week by week
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TeamWeek:
    team: str
    starters: Tuple[str, ...]          # real starters, empty slots left out
    players: FrozenSet[str]            # whole roster that week
    pf: float                          # real PF, +5 semifinal bonus included
    offset: float                      # pf − Σ starters' points (the bonus)
    opponent: Optional[str]
    slot_index: Tuple[int, ...] = ()   # each starter's slot in the template (default: in order)

    def slot_of(self) -> Dict[str, int]:
        idx = self.slot_index or tuple(range(len(self.starters)))
        return dict(zip(self.starters, idx))


class League:
    """Every team-week the counterfactual needs, plus player points."""

    def __init__(self, weeks: Dict[WeekKey, Dict[str, TeamWeek]],
                 points: Dict[WeekKey, Dict[str, float]],
                 slots: Dict[int, Tuple[Tuple[str, ...], ...]],
                 eligibility: Dict[int, Dict[str, FrozenSet[str]]],
                 positions: Dict[str, str],
                 nfl_points: Dict[str, Dict[WeekKey, float]],
                 last_game_day: Dict[WeekKey, str]):
        self.weeks = weeks
        self.order: List[WeekKey] = sorted(weeks)
        self._index = {k: i for i, k in enumerate(self.order)}
        self.points_by_week = points
        self.slots = slots
        self.eligibility = eligibility
        self.positions = positions
        self.last_game_day = last_game_day
        self.started: Dict[WeekKey, Set[str]] = {
            k: {p for tw in teams.values() for p in tw.starters} for k, teams in weeks.items()}
        self.holder: Dict[WeekKey, Dict[str, str]] = {
            k: {p: tw.team for tw in teams.values() for p in tw.players} for k, teams in weeks.items()}
        self._nfl: Dict[str, Tuple[List[WeekKey], List[float]]] = {}
        for pid, games in (nfl_points or {}).items():
            keys = sorted(games)
            self._nfl[str(pid)] = (keys, [float(games[k]) for k in keys])
        # Week boundaries: a week runs from the day after the previous week's
        # last game through its own last game (Tuesday-Monday).
        self._ends: List[Tuple[str, WeekKey]] = sorted(
            (day, k) for k, day in last_game_day.items() if k in self._index)
        self._end_days: List[str] = [d for d, _ in self._ends]

    # -- time ------------------------------------------------------------
    def week_of(self, day: str) -> Optional[WeekKey]:
        """The first league week whose last game is on or after `day`."""
        i = bisect.bisect_left(self._end_days, str(day)[:10])
        return self._ends[i][1] if i < len(self._ends) else None

    def week_start(self, key: WeekKey) -> str:
        i = self._index[key]
        if i == 0:
            return "0000-00-00"
        prev = self.last_game_day.get(self.order[i - 1], "0000-00-00")
        return prev  # strictly after this day

    def after(self, key: WeekKey, n: int) -> List[WeekKey]:
        i = self._index.get(key)
        return [] if i is None else self.order[i:i + n]

    def before(self, key: WeekKey, n: int) -> List[WeekKey]:
        i = self._index.get(key)
        return [] if i is None else self.order[max(0, i - n):i]

    def keys_from(self, key: WeekKey) -> List[WeekKey]:
        i = self._index.get(key)
        return [] if i is None else self.order[i:]

    # -- points ----------------------------------------------------------
    def points(self, pid: str, key: WeekKey) -> float:
        wk = self.points_by_week.get(key, {})
        if pid in wk:
            return float(wk[pid])
        hist = self._nfl.get(pid)
        if hist:
            i = bisect.bisect_left(hist[0], key)
            if i < len(hist[0]) and hist[0][i] == key:
                return hist[1][i]
        return 0.0

    def recent_avg(self, pid: str, key: WeekKey) -> Optional[float]:
        """The player's average over his previous 3 played NFL games — None
        until he has played 3 (a rookie's first 3 games: unproven)."""
        hist = self._nfl.get(pid)
        if not hist:
            return None
        i = bisect.bisect_left(hist[0], key)
        if i < CAP_GAMES:
            return None
        prior = hist[1][i - CAP_GAMES:i]
        return sum(prior) / len(prior)

    def cap(self, pid: str, key: WeekKey) -> Optional[float]:
        """1.5 x the player's average over his previous 3 NFL games, or None."""
        avg = self.recent_avg(pid, key)
        return None if avg is None else CAP_MULTIPLIER * avg

    def team_week(self, key: WeekKey, team: str) -> Optional[TeamWeek]:
        return self.weeks.get(key, {}).get(team)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _src_on_path() -> None:
    src = str(Q.repo_root() / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _sleeper_rows(season: int, wk: int) -> Dict[int, Q.WeekRow]:
    return Q.week(season, wk)


def _espn_2020() -> Dict[str, Any]:
    _src_on_path()
    import espn_2020  # noqa: E402  (src/, import-safe)
    return espn_2020.emit_sleeper_2020(espn_2020.load_espn_2020())


def _slots_for(positions: Sequence[str]) -> Tuple[Tuple[str, ...], ...]:
    return tuple(Q._FLEX_POOL.get(p, (p,)) for p in positions if p not in ("BN", "IR", "TAXI"))


def _learn_eligibility(rows_by_week: Iterable[Iterable[Tuple[Sequence[str], Sequence[Tuple[str, ...]]]]],
                       base: Dict[str, str]) -> Dict[str, FrozenSet[str]]:
    """Season eligibility the way `inquiry.season_eligibility` builds it:
    the dictionary position, plus any strict slot the player really started in."""
    learned: Dict[str, Set[str]] = defaultdict(set)
    for week_rows in rows_by_week:
        for starters, slots in week_rows:
            for idx, pid in enumerate(starters):
                if pid == EMPTY or idx >= len(slots):
                    continue
                if len(slots[idx]) == 1:
                    learned[pid].add(slots[idx][0])
    out: Dict[str, FrozenSet[str]] = {}
    for pid in set(base) | set(learned):
        elig = set(learned.get(pid, ()))
        if base.get(pid):
            elig.add(base[pid])
        if elig:
            out[pid] = frozenset(elig)
    return out


def load_league(team_week: pd.DataFrame,
                nfl_points: Optional[Dict[str, Dict[WeekKey, float]]] = None) -> League:
    """Build the week-by-week league from team_week + the lineup sources.

    `team_week` decides which weeks exist and supplies the real PF/opponent.
    `nfl_points` is {sleeper id: {(season, week): league-scored points}}; the
    build passes its own `nfl_games_by_sid`, a local run
    `nflverse_points_from_cache()`.
    """
    tw = team_week.copy()
    tw["Year"] = pd.to_numeric(tw["Year"], errors="coerce")
    tw["Week"] = pd.to_numeric(tw["Week"], errors="coerce")
    tw["PF"] = pd.to_numeric(tw["PF"], errors="coerce")
    tw = tw.dropna(subset=["Year", "Week", "PF"])
    real: Dict[WeekKey, Dict[str, Tuple[float, Optional[str]]]] = defaultdict(dict)
    for team, yr, wk, pf, opp in zip(tw["Team"], tw["Year"], tw["Week"], tw["PF"], tw["Opponent"]):
        o = None if pd.isna(opp) or str(opp).strip() in ("", "nan", "N/A") else str(opp)
        real[(int(yr), int(wk))][str(team)] = (float(pf), o)

    positions = Q.players().positions()
    weeks: Dict[WeekKey, Dict[str, TeamWeek]] = {}
    points: Dict[WeekKey, Dict[str, float]] = {}
    slots: Dict[int, Tuple[Tuple[str, ...], ...]] = {}
    seasons = sorted({k[0] for k in real})
    learned_rows: Dict[int, List[List[Tuple[Sequence[str], Sequence[Tuple[str, ...]]]]]] = defaultdict(list)

    espn = None
    for season in seasons:
        if season >= 2021:
            meta = Q.season_meta(season)
            if not meta.has_snapshot:
                continue
            slots[season] = meta.starting_slots
            names = Q.teams(season)
            fetch = lambda wk, s=season: {names.get(r, str(r)): (row.starters, row.players, row.players_points)
                                          for r, row in _sleeper_rows(s, wk).items()}
        else:
            if espn is None:
                espn = _espn_2020()
            slots[season] = _slots_for(espn["league"]["roster_positions"])
            mgr = {rid: m for m, rid in _espn_rid_map().items()}
            by_week = espn["matchups_by_week"]
            fetch = lambda wk, bw=by_week, mg=mgr: {
                mg.get(r["roster_id"], str(r["roster_id"])): (
                    tuple(str(p) for p in r["starters"]), tuple(str(p) for p in r["players"]),
                    {str(k): float(v or 0.0) for k, v in (r.get("players_points") or {}).items()})
                for r in bw.get(wk, [])}
        for (yr, wk), teams in sorted(real.items()):
            if yr != season:
                continue
            try:
                rows = fetch(wk)
            except FileNotFoundError:
                continue
            if not rows:
                continue
            key = (yr, wk)
            pts: Dict[str, float] = {}
            out: Dict[str, TeamWeek] = {}
            wrows = []
            for team, (pf, opp) in teams.items():
                if team not in rows:
                    continue
                starters, players, ppts = rows[team]
                pts.update({str(k): float(v) for k, v in ppts.items()})
                wrows.append((starters, slots[season]))
                placed = [(i, p) for i, p in enumerate(starters) if p and p != EMPTY]
                real_starters = tuple(p for _, p in placed)
                raw = sum(float(ppts.get(p, 0.0)) for p in real_starters)
                out[team] = TeamWeek(team=team, starters=real_starters,
                                     players=frozenset(str(p) for p in players),
                                     pf=round(pf, 2), offset=round(pf - raw, 2), opponent=opp,
                                     slot_index=tuple(i for i, _ in placed))
            if out:
                weeks[key] = out
                points[key] = pts
                learned_rows[season].append(wrows)
    eligibility = {s: _learn_eligibility(learned_rows[s], positions) for s in slots}
    last_days = _last_game_days(set(weeks))
    return League(weeks, points, slots, eligibility, positions, nfl_points or {}, last_days)


def _espn_rid_map() -> Dict[str, int]:
    _src_on_path()
    import espn_2020  # noqa: E402
    return dict(espn_2020.SLEEPER_ROSTER_ID_BY_MANAGER)


def _last_game_days(keys: Set[WeekKey]) -> Dict[WeekKey, str]:
    days = dict(Q._week_last_game_days(str(Q.repo_root())))
    out = {k: days[k] for k in keys if k in days}
    # Fallback for a week the schedule cache does not know: the Monday ending
    # the week, counted from the season's first Thursday after Labor Day.
    for season, wk in keys - set(out):
        sep1 = date(season, 9, 1)
        labor = sep1.toordinal() + (0 - sep1.weekday()) % 7
        out[(season, wk)] = date.fromordinal(labor + 3 + 4 + 7 * (wk - 1)).isoformat()
    return out


BRIDGE_FILE = "wins_added_gsis_bridge.csv"


def bridge_path() -> Path:
    return Q.repo_root() / "exports" / "raw" / BRIDGE_FILE


def write_gsis_bridge(bridge: Dict[str, str], path: Optional[Path] = None) -> Path:
    """Persist the build's sleeper_id -> gsis_id map (Sleeper's own id with the
    build's last-name correction, then DynastyProcess, then nflverse) so a
    recompute outside the build scores exactly the same nflverse games."""
    path = path or bridge_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted((str(s), str(g)) for s, g in bridge.items() if s and g and str(g).lower() != "nan")
    pd.DataFrame(rows, columns=["sleeper_id", "gsis_id"]).to_csv(path, index=False)
    return path


def load_gsis_bridge() -> Dict[str, str]:
    """The build's persisted bridge; before one exists, the inquiry layer's
    (DynastyProcess first, Sleeper's own field second)."""
    path = bridge_path()
    if path.exists():
        df = pd.read_csv(path, dtype=str)
        return dict(zip(df["sleeper_id"], df["gsis_id"]))
    from lotg_support.scoring_events import gsis_bridge
    return gsis_bridge()


def nflverse_points_from_cache(seasons: Optional[Sequence[int]] = None,
                               bridge: Optional[Dict[str, str]] = None,
                               score: Optional[Callable[..., float]] = None,
                               score_map: Optional[Dict[str, Tuple[str, ...]]] = None,
                               cache_dir: Optional[Path] = None) -> Dict[str, Dict[WeekKey, float]]:
    """League-scored nflverse points by Sleeper id, from the build's `.cache`.

    Regular-season games, each season scored with its own league scoring
    settings (2020 with the ESPN table, earlier seasons with 2020's) through the
    build's `_league_score`. The build and every recompute call this with the
    same bridge (`load_gsis_bridge`), so they score the same games. A gsis id
    two Sleeper ids share is given to both.
    """
    if score is None or score_map is None:
        _src_on_path()
        import lotg  # noqa: E402
        score, score_map = lotg._league_score, lotg._LEAGUE_SCORE_MAP
    bridge = bridge if bridge is not None else load_gsis_bridge()
    gsis_to_sids: Dict[str, List[str]] = defaultdict(list)
    for sid, gsis in bridge.items():
        g = str(gsis or "").strip()
        if g and g.lower() != "nan":
            gsis_to_sids[g].append(str(sid))
    root = Q.repo_root()
    cache_dir = cache_dir or root / ".cache"
    positions = Q.players().positions()
    # From 2017: the three seasons before the league are history only, for the
    # "previous 3 games" average.
    seasons = list(seasons or range(2017, date.today().year + 1))
    first_table = None
    out: Dict[str, Dict[WeekKey, float]] = defaultdict(dict)
    for season in seasons:
        path = cache_dir / f"nflverse_stats_player_week_{season}.csv"
        if not path.exists():
            continue
        if season >= 2021:
            lj = root / "exports" / "snapshot" / f"season_{season}" / "league.json"
            if not lj.exists():
                continue
            scoring = json.loads(lj.read_text()).get("scoring_settings") or {}
        else:
            if first_table is None:
                first_table = _espn_2020()["league"]["scoring_settings"]
            scoring = first_table
        df = pd.read_csv(path, low_memory=False)
        if "season_type" in df.columns:
            df = df[df["season_type"].astype(str).str.upper() == "REG"]
        cols = [c for cs in score_map.values() for c in cs if c in df.columns]
        for r in df[["player_id", "week"] + cols].itertuples(index=False):
            sids = gsis_to_sids.get(str(r[0]))
            if not sids:
                continue
            stats = {k: (None if pd.isna(v) else v) for k, v in zip(cols, r[2:])}
            for sid in sids:
                out[sid][(int(season), int(r[1]))] = score(stats, scoring, positions.get(sid))
    return dict(out)


# ---------------------------------------------------------------------------
# Moves, read from the sheets
# ---------------------------------------------------------------------------
_PICK = re.compile(r"^(\d{4}) (.+)$")
_DRAFTED = re.compile(r"^(\d{4}) (\d+)\.(\d+)\((.*)\)$")


@dataclass
class Asset:
    label: str
    pid: Optional[str] = None          # the player, or the player drafted with the pick
    is_pick: bool = False
    pick_key: Optional[str] = None
    drafted_by: Optional[str] = None   # team that made the selection
    draft_day: Optional[str] = None
    start: Optional[WeekKey] = None    # first week the drafted player counts


@dataclass
class Move:
    sheet: str
    index: Any
    team: str
    stamp: str                         # full Date string (ordering)
    day: str                           # YYYY-MM-DD
    kind: str                          # 'trade' | 'add_drop'
    received: List[Asset] = field(default_factory=list)
    sent: List[Asset] = field(default_factory=list)
    senders: Dict[str, str] = field(default_factory=dict)   # received pid -> team that sent him


def _abbrev(name: str) -> str:
    parts = str(name).split()
    if not parts:
        return ""
    return Q._normalize(parts[0][:1] + " " + " ".join(parts[1:]))


class Resolver:
    """Sheet name -> Sleeper id, using who was on which roster to break ties."""

    def __init__(self, league: League):
        self.league = league
        self.players = Q.players()
        self._espn: Dict[str, List[str]] = {}
        path = Q.repo_root() / "data" / "espn_2020_raw" / "player_id_map.csv"
        if path.exists():
            for r in pd.read_csv(path, dtype=str).itertuples(index=False):
                sid = str(getattr(r, "sleeper_id") or "").split(".")[0]
                if sid and sid != "nan":
                    self._espn.setdefault(Q._normalize(getattr(r, "name")), []).append(sid)
        self.unresolved: List[str] = []

    def candidates(self, name: str) -> List[str]:
        norm = Q._normalize(name)
        ids = list(self.players._by_norm.get(norm, []))
        ids += [i for i in self._espn.get(norm, []) if i not in ids]
        return ids

    def _on_roster(self, pid: str, team: str, keys: Sequence[WeekKey]) -> bool:
        return any(pid in tw.players for k in keys
                   for tw in [self.league.team_week(k, team)] if tw is not None)

    def resolve(self, name: str, team: str, around: Optional[WeekKey], side: str) -> Optional[str]:
        ids = self.candidates(name)
        if not ids:
            try:
                ids = [self.players.resolve(name)]
            except Exception:
                self.unresolved.append(name)
                return None
        if len(ids) == 1:
            return ids[0]
        if around is not None:
            keys = (self.league.after(around, 4) if side == "after"
                    else self.league.before(around, 3) + self.league.after(around, 1))
            hits = [p for p in ids if self._on_roster(p, team, keys)]
            if len(hits) == 1:
                return hits[0]
        hits = [p for p in ids if any(p in tw.players for k in self.league.order
                                      for tw in [self.league.team_week(k, team)] if tw)]
        if len(hits) == 1:
            return hits[0]
        if around is not None:
            # Never on a weekly roster here (added and dropped between two
            # weeks): take whichever namesake was playing in the NFL that year.
            hits = [p for p in ids if any(abs(k[0] - around[0]) <= 1
                                          for k in self.league._nfl.get(p, ((), ()))[0])]
            if len(hits) == 1:
                return hits[0]
        try:
            return self.players.resolve(name)
        except Exception:
            self.unresolved.append(name)
            return None


class PickBook:
    """Pick label (as the sheets write it) -> the player drafted with it."""

    def __init__(self, picks: Sequence[pd.DataFrame], league: League, resolver: Resolver):
        self._rows: Dict[str, List[dict]] = defaultdict(list)
        draft_days = _draft_days()
        for df in picks:
            if df is None or df.empty:
                continue
            for r in df.to_dict("records"):
                year_txt = str(r.get("Year") or "")
                if year_txt.startswith("startup"):
                    year = 2020
                else:
                    m = re.match(r"(\d{4})", year_txt)
                    if not m:
                        continue
                    year = int(m.group(1))
                number = str(r.get("Number") or "").strip()
                if not re.match(r"^\d+\.\d+$", number):
                    continue
                who = str(r.get("Player Picked") or "").strip()
                if who.lower() in ("", "nan", "unknown", "n/a"):
                    continue
                team = str(r.get("Team") or "")
                start = (year, 1)
                pid = resolver.resolve(who, team, _first_key(league, year), "after")
                self._rows[f"{year} {number}"].append({
                    "pid": pid, "name": who, "team": team, "start": start,
                    "day": draft_days.get(year, f"{year}-05-01")})

    def lookup(self, label: str) -> Optional[dict]:
        m = _DRAFTED.match(label.strip())
        if not m:
            return None
        rows = self._rows.get(f"{m.group(1)} {int(m.group(2))}.{m.group(3)}", [])
        if len(rows) > 1:
            want = Q._normalize(m.group(4))
            rows = [r for r in rows if _abbrev(r["name"]) == want] or rows[:1]
        return rows[0] if rows else None


def _first_key(league: League, season: int) -> Optional[WeekKey]:
    for k in league.order:
        if k[0] == season:
            return k
    return None


def _draft_days() -> Dict[int, str]:
    out: Dict[int, str] = {}
    raw = Q.repo_root() / "exports" / "raw"
    for path in raw.glob("drafts_*.json"):
        try:
            blob = json.loads(path.read_text())
        except Exception:
            continue
        stamps = [d.get("start_time") for d in (blob if isinstance(blob, list) else [blob]) if d.get("start_time")]
        if stamps:
            year = int(re.search(r"(\d{4})", path.name).group(1))
            out[year] = datetime.fromtimestamp(min(stamps) / 1000, tz=timezone.utc).date().isoformat()
    return out


def _stamp(value: Any) -> str:
    """A sheet Date as a sortable 'YYYY-MM-DD HH:MM:SS' string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).replace("T", " ")[:19]


def _split_assets(text: Any) -> List[str]:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    return [a.strip() for a in str(text).split(";") if a.strip() and not a.strip().endswith("FAAB")]


def _pick_key(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip())


def _asset(label: str, team: str, key: Optional[WeekKey], side: str,
           resolver: Resolver, picks: PickBook) -> Asset:
    if _PICK.match(label):
        a = Asset(label=label, is_pick=True, pick_key=_pick_key(label))
        hit = picks.lookup(label)
        if hit:
            a.pid, a.drafted_by, a.start, a.draft_day = hit["pid"], hit["team"], hit["start"], hit["day"]
        return a
    return Asset(label=label, pid=resolver.resolve(label, team, key, side))


def moves_from_sheets(trades: pd.DataFrame, add_drops: pd.DataFrame, league: League,
                      picks: Sequence[pd.DataFrame], resolver: Optional[Resolver] = None) -> List[Move]:
    resolver = resolver or Resolver(league)
    book = PickBook(picks, league, resolver)
    moves: List[Move] = []
    for idx, r in trades.iterrows():
        stamp = _stamp(r.get("Date"))
        team = str(r.get("Team") or "")
        key = league.week_of(stamp[:10])
        mv = Move("trades", idx, team, stamp, stamp[:10], "trade")
        mv.received = [_asset(a, team, key, "after", resolver, book) for a in _split_assets(r.get("Assets received"))]
        mv.sent = [_asset(a, team, key, "before", resolver, book) for a in _split_assets(r.get("Assets sent"))]
        moves.append(mv)
    # Who sent each received player: the other row of the same trade (same
    # Date) that lists him among its assets sent. Works for 3-team deals.
    by_stamp: Dict[str, List[Move]] = defaultdict(list)
    for mv in moves:
        by_stamp[mv.stamp].append(mv)
    for mv in moves:
        for a in mv.received:
            if a.is_pick or not a.pid:
                continue
            for other in by_stamp[mv.stamp]:
                if other is not mv and any(s.pid == a.pid for s in other.sent if not s.is_pick):
                    mv.senders[a.pid] = other.team
                    break
    for idx, r in add_drops.iterrows():
        stamp = _stamp(r.get("Date"))
        team = str(r.get("Team") or "")
        key = league.week_of(stamp[:10])
        mv = Move("add_drops", idx, team, stamp, stamp[:10], "add_drop")
        added, dropped = r.get("Player Added"), r.get("Player Dropped")
        if isinstance(added, str) and added.strip():
            mv.received = [Asset(label=added.strip(), pid=resolver.resolve(added.strip(), team, key, "after"))]
        if isinstance(dropped, str) and dropped.strip():
            mv.sent = [Asset(label=dropped.strip(), pid=resolver.resolve(dropped.strip(), team, key, "before"))]
        moves.append(mv)
    return moves


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------
@dataclass
class LineageItem:
    pid: Optional[str]
    pick_key: Optional[str]
    share: float
    group: int
    acquired: str                      # day the team got it
    ended: Optional[str] = None        # day it left through a tracked move
    asset: Optional[Asset] = None


ValueFn = Callable[[Asset, str], Optional[float]]


def _downstream_share(consumed: Sequence[Tuple[LineageItem, Asset]], sent: Sequence[Asset],
                      day: str, value_fn: Optional[ValueFn]) -> float:
    """Share of a later trade's return owed to this move's lineage: lineage
    inputs' KTC (each at its own lineage share) over the team's whole side.
    FAAB is not an input. With no KTC on the whole side, count assets."""
    vals: List[Optional[float]] = [value_fn(a, day) if value_fn else None for a in sent]
    total = sum(v for v in vals if v)
    if total > 0:
        lin = 0.0
        for item, asset in consumed:
            for a, v in zip(sent, vals):
                if a is asset and v:
                    lin += item.share * v
        return max(0.0, min(1.0, lin / total))
    n = len(sent) or 1
    return max(0.0, min(1.0, sum(item.share for item, _ in consumed) / n))


def lineage(move: Move, later: Sequence[Move], value_fn: Optional[ValueFn]) -> List[LineageItem]:
    """Every asset this move's return turned into on the team, with its share."""
    items: List[LineageItem] = []
    for a in move.received:
        items.append(LineageItem(pid=None if a.is_pick else a.pid,
                                 pick_key=a.pick_key if a.is_pick else None,
                                 share=1.0, group=0, acquired=move.day, asset=a))
    next_group = 1

    def convert_drafted(until_day: str) -> None:
        for it in list(items):
            a = it.asset
            if (it.pick_key and it.ended is None and a is not None and a.pid
                    and a.drafted_by == move.team and a.draft_day and a.draft_day <= until_day):
                it.ended = a.draft_day
                items.append(LineageItem(pid=a.pid, pick_key=None, share=it.share, group=it.group,
                                         acquired=a.draft_day))

    for mv in later:
        convert_drafted(mv.day)
        live = [it for it in items if it.ended is None]
        if not live:
            continue
        consumed: List[Tuple[LineageItem, Asset]] = []
        for it in live:
            for a in mv.sent:
                if (it.pid and not a.is_pick and a.pid == it.pid) or (it.pick_key and a.is_pick and a.pick_key == it.pick_key):
                    consumed.append((it, a))
                    break
        if not consumed:
            continue
        for it, _ in consumed:
            it.ended = mv.day
        if mv.kind != "trade":
            continue                     # dropped: the lineage ends
        share = _downstream_share(consumed, mv.sent, mv.day, value_fn)
        if share <= 0:
            continue
        for a in mv.received:
            items.append(LineageItem(pid=None if a.is_pick else a.pid,
                                     pick_key=a.pick_key if a.is_pick else None,
                                     share=share, group=next_group, acquired=mv.day, asset=a))
        next_group += 1
    convert_drafted("9999-12-31")
    return [it for it in items if it.pid]


# ---------------------------------------------------------------------------
# The counterfactual lineup
# ---------------------------------------------------------------------------
@dataclass
class Report:
    rows: int = 0
    unresolved_names: List[str] = field(default_factory=list)
    unproven_blocked: Set[Tuple[str, WeekKey]] = field(default_factory=set)
    optimised_weeks: int = 0
    illegal_real_lineups: List[Tuple[WeekKey, str]] = field(default_factory=list)
    share_fallbacks: int = 0


def cf_lineup_points(league: League, key: WeekKey, tw: TeamWeek, out: Set[str],
                     arrivals: Sequence[str], report: Optional[Report] = None) -> float:
    """Counterfactual starters' points (see the module docstring's lineup rule)."""
    return cf_lineup(league, key, tw, out, arrivals, report)[0]


def cf_lineup(league: League, key: WeekKey, tw: TeamWeek, out: Set[str],
              arrivals: Sequence[str], report: Optional[Report] = None) -> Tuple[float, List[str]]:
    """(points, starters) of the counterfactual lineup — the starters are what
    `cf_lineup_points` scores, returned so a row can be checked by eye.

    The pool is exactly the real roster that week minus `out` (what the move
    brought in) plus `arrivals` (what it gave up). Slot-aware [per user]:

      * every CLEARED slot — one a removed starter occupied — is filled, by a
        different player each: the most plausible eligible option (3-game
        average within PLAUSIBLE_MARGIN of the h-th best option for the h
        cleared slots), else the best eligible one; left empty only if nobody
        on the pool can play it;
      * an arrival takes one explicit role: fill a cleared slot, take a slot
        the manager really left empty, or displace ONE named starter whose
        3-game average he is within PLAUSIBLE_MARGIN of;
      * a bench player only ever fills a cleared slot — directly, or by one
        starter sliding into it and the bench player taking the slot that
        slide frees (the RB slot is cleared and the bench has only a WR: the
        RB in the flex slides into the RB slot and the WR takes the flex). He
        never displaces a starter, so no start/sit change the move did not
        force;
      * a player nobody started that week counts at most 1.5x his 3-game
        average; a player with fewer than 3 prior NFL games is never moved in.
    Among the plausible lineups the highest-scoring one is taken (real points).
    """
    season = key[0]
    slots = league.slots[season]
    elig = league.eligibility[season]
    n = len(slots)
    started = league.started[key]
    slot_of = tw.slot_of()
    kept = [(slot_of[p], p) for p in tw.starters if p not in out]
    cleared = [slot_of[p] for p in tw.starters if p in out]
    empty_real = [i for i in range(n) if i not in set(slot_of.values())]

    def avg(p: str) -> Optional[float]:
        return league.recent_avg(p, key)

    def proven(p: str) -> bool:
        if avg(p) is not None:
            return True
        if report is not None and league.points(p, key) > 0:
            report.unproven_blocked.add((p, key))
        return False

    def entry_value(p: str) -> float:
        pts = league.points(p, key)
        return pts if p in started else min(pts, league.cap(p, key))

    def fits(p: str, i: int) -> bool:
        return bool(elig.get(p, frozenset()) & set(slots[i]))

    def can_take(p: str, i: int, stay: Sequence[Tuple[int, str]]) -> bool:
        """Into slot i directly, or into a starter's slot j while he slides into i."""
        return fits(p, i) or any(fits(p, j) and fits(k, i) for j, k in stay)

    val: Dict[str, float] = {p: league.points(p, key) for _, p in kept}
    arr = [a for a in dict.fromkeys(arrivals)
           if (a not in tw.players or a in out) and a not in val and proven(a)]
    for a in arr:
        val[a] = entry_value(a)
    bench = [b for b in tw.players
             if b not in tw.starters and b not in out and b not in arr and proven(b)]
    for b in bench:
        val[b] = entry_value(b)

    # The fill bar: the h-th best 3-game average among everyone who could take
    # one of the h cleared slots.
    fill_ref: Optional[float] = None
    if cleared:
        fillers = sorted({avg(p) for p in arr + bench
                          if any(can_take(p, i, kept) for i in cleared)}, reverse=True)
        fill_ref = fillers[min(len(cleared), len(fillers)) - 1] if fillers else None

    def plausible_fill(p: str) -> bool:
        return fill_ref is None or avg(p) >= fill_ref - PLAUSIBLE_MARGIN

    def plausible_over(p: str, k: str) -> bool:
        ka = avg(k)
        return ka is None or avg(p) >= ka - PLAUSIBLE_MARGIN

    def fill_bench(open_slots: List[int], stay: List[Tuple[int, str]], taken: Set[str]) -> Optional[List[str]]:
        """Best distinct bench player per open cleared slot (plausible first,
        else best eligible); None if a slot can be filled by nobody — then it
        is left empty (returns the partial fill)."""
        if not open_slots:
            return []
        options: List[List[Optional[str]]] = []
        for i in open_slots:
            elig_b = [b for b in bench if b not in taken and can_take(b, i, stay)]
            good = [b for b in elig_b if plausible_fill(b)] or elig_b
            good = sorted(good, key=lambda b: -val[b])[:len(open_slots) + 2]
            options.append(good or [None])
        best_fill: Optional[List[str]] = None
        best_v = -1.0
        for combo in itertools.product(*options):
            chosen = [b for b in combo if b is not None]
            if len(set(chosen)) != len(chosen):
                continue
            v = sum(val[b] for b in chosen)
            if v > best_v:
                best_v, best_fill = v, chosen
        return best_fill or []

    best_score = -1.0
    best_lineup: List[str] = [p for _, p in kept]

    def consider(lineup: List[str]) -> None:
        nonlocal best_score, best_lineup
        if len(lineup) > n or len(set(lineup)) != len(lineup):
            return
        score = sum(val[p] for p in lineup)
        if score <= best_score + 1e-9:
            return
        if is_legal(lineup + [EMPTY] * (n - len(lineup)), elig, slots):
            best_score, best_lineup = score, lineup

    # Each arrival: unused, fills a cleared slot, takes a real empty slot, or
    # displaces one named starter.
    roles: List[List[Tuple[str, Any]]] = []
    for a in arr:
        r: List[Tuple[str, Any]] = [("none", None)]
        r += [("fill", i) for i in cleared if can_take(a, i, kept)
              and (plausible_fill(a) or not any(can_take(x, i, kept) and plausible_fill(x)
                                                for x in arr + bench))]
        r += [("empty", i) for i in empty_real if can_take(a, i, kept)]
        r += [("disp", (j, k)) for j, k in kept
              if val[a] > val[k] and can_take(a, j, [x for x in kept if x[1] != k])
              and plausible_over(a, k)]
        roles.append(r)

    for combo in itertools.product(*roles) if roles else [()]:
        targets = [t for kind, t in combo if kind != "none"]
        if len(targets) != len(set(map(repr, targets))):
            continue
        displaced = {t[1] for kind, t in combo if kind == "disp"}
        stay = [(j, k) for j, k in kept if k not in displaced]
        used = [a for a, (kind, _) in zip(arr, combo) if kind != "none"]
        filled = {t for kind, t in combo if kind == "fill"}
        open_slots = [i for i in cleared if i not in filled]
        fill = fill_bench(open_slots, stay, set(used))
        consider([k for _, k in stay] + used + fill)
    return round(best_score if best_score >= 0 else sum(val[p] for p in best_lineup), 2), best_lineup


def _result(a: float, b: float) -> float:
    a, b = round(a, 2), round(b, 2)
    return 1.0 if a > b else (0.5 if a == b else 0.0)


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------
def games_for(league: League, team: str, keys: Sequence[WeekKey]) -> List[List[WeekKey]]:
    """The team's games over `keys`: one week each, except the 2026+ two-week
    final, where two consecutive finals weeks against the same opponent are
    one game."""
    out: List[List[WeekKey]] = []
    for key in keys:
        tw = league.team_week(key, team)
        if tw is None or not tw.opponent:
            continue
        season, wk = key
        if season >= TWO_WEEK_FINAL_FROM and out:
            meta = Q.season_meta(season)
            prev = out[-1][-1]
            if (len(meta.finals_weeks) == 2 and wk == meta.finals_weeks[1]
                    and prev == (season, meta.finals_weeks[0])
                    and league.team_week(prev, team).opponent == tw.opponent):
                out[-1].append(key)
                continue
        out.append([key])
    return out


# ---------------------------------------------------------------------------
# The calculation
# ---------------------------------------------------------------------------
def _present(items: Sequence[LineageItem], league: League, key: WeekKey, tw: TeamWeek) -> List[LineageItem]:
    start = league.week_start(key)
    end = league.last_game_day[key]
    return [it for it in items
            if it.pid in tw.players and it.acquired <= end
            and (it.ended is None or it.ended > start)]


UNROSTERED_WEEKS = 4
FOREVER: WeekKey = (9999, 99)


def _given_up(move: Move, league: League,
              later: Sequence[Move] = ()) -> List[Tuple[str, WeekKey, WeekKey]]:
    """(player, first week, last week) for everything the move gave up.

    The count runs from the move to today, and stops early in two cases
    [per user, 2026-10-01]:
      * the league let him go — once he has been on NO roster for
        `UNROSTERED_WEEKS` straight weeks, the count ends with that week
        (the team would have cut him too);
      * the team re-acquires him — the earlier move's count ends the week
        before the re-acquiring move takes effect, so the same player is
        never counted by two of the team's moves at once.
    """
    eff = league.week_of(move.day)
    out: List[Tuple[str, WeekKey, WeekKey]] = []
    for a in move.sent:
        if not a.pid:
            continue
        if a.is_pick:
            if a.start is None:
                continue
            start = a.start if eff is None or a.start > eff else eff
        else:
            start = eff
        if start is None:
            continue
        end = FOREVER
        run = 0
        for k in league.keys_from(start):
            run = 0 if a.pid in league.holder[k] else run + 1
            if run >= UNROSTERED_WEEKS:
                end = k
                break
        for mv in later:
            if any(r.pid == a.pid and not r.is_pick for r in mv.received):
                back = league.week_of(mv.day)
                before = league.before(back, 1) if back else []
                if back is not None:
                    end = min(end, before[0] if before else (0, 0))
                break
        if end >= start:
            out.append((a.pid, start, end))
    return out


def wins_added_for(move: Move, later: Sequence[Move], league: League,
                   value_fn: Optional[ValueFn] = None, report: Optional[Report] = None,
                   through: Optional[WeekKey] = None) -> float:
    """The move's Wins added; `through` stops the count after that week."""
    eff = league.week_of(move.day)
    if eff is None:
        return 0.0
    items = lineage(move, later, value_fn)
    given = _given_up(move, league, later)
    keys = [k for k in league.keys_from(eff) if through is None or k <= through]
    total = 0.0
    for game in games_for(league, move.team, keys):
        total += _game_value(move, game, items, given, league, report)
    return round(total, 4)


def _game_value(move: Move, game: Sequence[WeekKey], items: Sequence[LineageItem],
                given: Sequence[Tuple[str, WeekKey, WeekKey]], league: League, report: Optional[Report]) -> float:
    team = move.team
    per_week = []
    groups: Dict[int, float] = {}
    group_started: Set[int] = set()
    for key in game:
        tw = league.team_week(key, team)
        opp = league.team_week(key, tw.opponent)
        if opp is None:
            return 0.0
        present = _present(items, league, key, tw)
        lineage_now = {it.pid for it in present}
        arrivals = [p for p, start, end in given if start <= key <= end and (p not in tw.players or p in lineage_now)]
        opp_out = {p for p, start, end in given if start <= key <= end and p in opp.players}
        opp_in = [it.pid for it in present if it.group == 0
                  and move.senders.get(it.pid) == opp.team and it.pid not in opp.players]
        for it in present:
            groups[it.group] = it.share
            if it.pid in tw.starters:
                group_started.add(it.group)
        per_week.append((key, tw, opp, present, arrivals, opp_out, opp_in))
    if not any(pres or arr or oo or oi for _, _, _, pres, arr, oo, oi in per_week):
        return 0.0

    real_t = sum(tw.pf for _, tw, _, _, _, _, _ in per_week)
    real_o = sum(op.pf for _, _, op, _, _, _, _ in per_week)
    real_r = _result(real_t, real_o)

    # Bounds: skip the lineup search when no counterfactual can change the result.
    lo_t = hi_t = lo_o = hi_o = 0.0
    for key, tw, opp, present, arrivals, opp_out, opp_in in per_week:
        lost = sum(league.points(it.pid, key) for it in present if it.pid in tw.starters)
        gain = sum(league.points(p, key) for p in arrivals)
        bench_t = sorted((league.points(p, key) for p in tw.players if p not in tw.starters), reverse=True)
        n_out = sum(1 for it in present if it.pid in tw.starters)
        lo_t += tw.pf - lost
        hi_t += tw.pf + gain + sum(bench_t[:n_out])
        o_lost = sum(league.points(p, key) for p in opp_out if p in opp.starters)
        o_gain = sum(league.points(p, key) for p in opp_in)
        bench_o = sorted((league.points(p, key) for p in opp.players if p not in opp.starters), reverse=True)
        n_o = sum(1 for p in opp_out if p in opp.starters)
        lo_o += opp.pf - o_lost
        hi_o += opp.pf + o_gain + sum(bench_o[:n_o])
    if _result(lo_t, hi_o) == real_r == _result(hi_t, lo_o):
        return 0.0

    if report is not None:
        report.optimised_weeks += len(game)
    certain = {g for g, s in groups.items() if s >= 1.0 - 1e-9}
    uncertain = sorted((g for g in groups if g not in certain and g in group_started),
                       key=lambda g: -groups[g])
    enum = uncertain[:MAX_ENUMERATED_GROUPS]
    fixed = certain | {g for g, s in groups.items() if g not in certain and g not in enum and s >= 0.5}

    cf_o = 0.0
    for key, tw, opp, present, arrivals, opp_out, opp_in in per_week:
        if opp_out or opp_in:
            cf_o += cf_lineup_points(league, key, opp, opp_out, opp_in, report) + opp.offset
        else:
            cf_o += opp.pf

    value = 0.0
    for bits in itertools.product((0, 1), repeat=len(enum)):
        prob = 1.0
        removed = set(fixed)
        for g, bit in zip(enum, bits):
            prob *= groups[g] if bit else (1.0 - groups[g])
            if bit:
                removed.add(g)
        if prob <= 0:
            continue
        cf_t = 0.0
        for key, tw, opp, present, arrivals, opp_out, opp_in in per_week:
            out = {it.pid for it in present if it.group in removed}
            if out or arrivals:
                cf_t += cf_lineup_points(league, key, tw, out, arrivals, report) + tw.offset
            else:
                cf_t += tw.pf
        value += prob * (real_r - _result(cf_t, cf_o))
    return value


def explain(move: Move, later: Sequence[Move], league: League,
            value_fn: Optional[ValueFn] = None) -> List[Tuple[Tuple[WeekKey, ...], str, float]]:
    """Every game the move swung: (weeks, opponent, value). For checking a row."""
    eff = league.week_of(move.day)
    if eff is None:
        return []
    items = lineage(move, later, value_fn)
    given = _given_up(move, league, later)
    out = []
    for game in games_for(league, move.team, league.keys_from(eff)):
        v = _game_value(move, game, items, given, league, None)
        if abs(v) > 1e-9:
            out.append((tuple(game), league.team_week(game[0], move.team).opponent, round(v, 4)))
    return out


def later_moves(moves: Sequence[Move]) -> Dict[int, List[Move]]:
    """id(move) -> the same team's moves after it, in order."""
    by_team: Dict[str, List[Move]] = defaultdict(list)
    for mv in moves:
        by_team[mv.team].append(mv)
    for team_moves in by_team.values():
        team_moves.sort(key=lambda m: (m.stamp, 0 if m.kind == "trade" else 1))
    return {id(mv): [m for m in by_team[mv.team] if m.stamp > mv.stamp] for mv in moves}


def games_elapsed(move: Move, league: League, through: Optional[WeekKey] = None) -> int:
    """Games the team has played from the move's first week through the latest
    (the 2026+ two-week final is one game) — the per-season rate's denominator."""
    eff = league.week_of(move.day)
    if eff is None:
        return 0
    keys = [k for k in league.keys_from(eff) if through is None or k <= through]
    return len(games_for(league, move.team, keys))


def per_season(wins: float, games: int) -> Optional[float]:
    """Wins added as a rate: per `SEASON_GAMES` games since the move (N/A before
    the first game). A loss the week after a drop reads −17 after one game."""
    return round(float(wins) * SEASON_GAMES / int(games), 2) if games else None


def compute(trades: pd.DataFrame, add_drops: pd.DataFrame, league: League,
            picks: Sequence[pd.DataFrame], value_fn: Optional[ValueFn] = None,
            report: Optional[Report] = None,
            only: Optional[Set[Tuple[str, Any]]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """`Wins added` and `Wins added per season` for every row of `trades` and
    `add_drops`, as two frames aligned to the inputs' index.

    `only` = {(sheet, index)} evaluates just those rows (the rest stay NaN);
    every row is still read, because a row's lineage runs through the others."""
    report = report if report is not None else Report()
    resolver = Resolver(league)
    moves = moves_from_sheets(trades, add_drops, league, picks, resolver)
    later = later_moves(moves)
    out: Dict[str, Dict[str, Dict[Any, Optional[float]]]] = {
        "trades": {COLUMN: {}, RATE_COLUMN: {}}, "add_drops": {COLUMN: {}, RATE_COLUMN: {}}}
    for mv in moves:
        if only is not None and (mv.sheet, mv.index) not in only:
            continue
        wins = round(wins_added_for(mv, later[id(mv)], league, value_fn, report), 2)
        out[mv.sheet][COLUMN][mv.index] = wins
        out[mv.sheet][RATE_COLUMN][mv.index] = per_season(wins, games_elapsed(mv, league))
        report.rows += 1
    report.unresolved_names = sorted(set(resolver.unresolved))

    def frame(sheet: str, index: pd.Index) -> pd.DataFrame:
        return pd.DataFrame({c: pd.Series(v, dtype=float).reindex(index) for c, v in out[sheet].items()})
    return frame("trades", trades.index), frame("add_drops", add_drops.index)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def check_real_lineups_legal(league: League) -> List[str]:
    """Every real lineup must be legal under our eligibility, or the
    counterfactual search would reject lineups that really happened."""
    bad = []
    for key, teams in league.weeks.items():
        slots = league.slots[key[0]]
        elig = league.eligibility[key[0]]
        for team, tw in teams.items():
            lineup = list(tw.starters)
            if len(lineup) > len(slots) or not is_legal(lineup + [EMPTY] * (len(slots) - len(lineup)), elig, slots):
                bad.append(f"{key} {team}: real lineup not legal under the season template")
    return bad


def check_offsets(league: League) -> List[str]:
    """PF − Σ starters' points must be 0 or the +5 semifinal bonus."""
    bad = []
    for key, teams in league.weeks.items():
        for team, tw in teams.items():
            if not (abs(tw.offset) < 0.011 or abs(tw.offset - 5.0) < 0.011):
                bad.append(f"{key} {team}: PF {tw.pf} vs starters {round(tw.pf - tw.offset, 2)}")
    return bad


def check_no_change_is_zero(league: League, sample: int = 0) -> List[str]:
    """A counterfactual that removes and adds nothing reproduces every score."""
    bad = []
    for key, teams in league.weeks.items():
        for team, tw in teams.items():
            if abs(cf_lineup_points(league, key, tw, set(), []) + tw.offset - tw.pf) > 0.011:
                bad.append(f"{key} {team}")
    return bad


# ---------------------------------------------------------------------------
# Local convenience: everything from the committed exports
# ---------------------------------------------------------------------------
def local_value_fn() -> Optional[ValueFn]:
    """KTC at a date through the build's own index (`lotg_support.ktc`).

    Returns None (shares fall back to asset counts) if the index cannot be
    built here."""
    try:
        from lotg_support.ktc import build_index, asset_value_at
        root = Q.repo_root()
        trades = Q.load_sheet("trades")
        pick_labels: Set[str] = set()
        for col in ("Assets received", "Assets sent"):
            for text in trades[col].dropna():
                for a in _split_assets(text):
                    if _PICK.match(a):
                        pick_labels.add(_ktc_pick_label(a))
        sids = set(Q.players().positions())
        idx = build_index(root, sids, pick_labels, value_col="sf_trade_value")
    except Exception:
        return None

    def fn(asset: Asset, day: str) -> Optional[float]:
        try:
            d = date.fromisoformat(day[:10])
            if asset.is_pick:
                return asset_value_at(_ktc_pick_label(asset.label), None, d, idx)
            return asset_value_at(None, asset.pid, d, idx) if asset.pid else None
        except Exception:
            return None
    return fn


def _ktc_pick_label(label: str) -> str:
    m = re.match(r"^(\d{4}) (\d+)\.(\d+)", label)
    if m:
        return f"{m.group(1)} {int(m.group(2))}.{m.group(3)}"
    m = re.match(r"^(\d{4}) (\d+)", label)
    return f"{m.group(1)} {int(m.group(2))}.??" if m else label


def compute_from_exports(report: Optional[Report] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """The column recomputed from the committed exports (both sheets, with it)."""
    trades = Q.load_sheet("trades").copy()
    add_drops = Q.load_sheet("add_drops").copy()
    league = load_league(Q.load_sheet("team_week"), nflverse_points_from_cache())
    picks = [Q.load_sheet("rookie_picks"), Q.load_sheet("non_rookie_picks")]
    t, a = compute(trades, add_drops, league, picks, local_value_fn(), report)
    for col in (COLUMN, RATE_COLUMN):
        trades[col] = t[col]
        add_drops[col] = a[col]
    return trades, add_drops
