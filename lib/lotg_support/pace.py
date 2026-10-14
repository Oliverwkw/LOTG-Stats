"""How the weekly digest projects a season column "on pace" (user rules, 2026-10-13).

The digest used to multiply every non-rate season column by weeks-in-season /
weeks-played. That is only right for a stat that piles up evenly week by week,
and the 2026 week-5 email showed what it does to the rest: Tanking — already a
running average — "on pace" for 3.65; a distinct count past its cap (Tre Tucker
on 20 teams, the league on 112 of 33 NFL teams); offseason trades that were done
counting multiplied by 3.4; front-loaded pickups and FAAB read as record paces;
Mahomes' "points minus a full-season baseline" scaled whole to -1,054. Each
column now gets the rule that fits what it measures (`pace_mode`):

  LINEAR      even accumulation: cur × season weeks / weeks played.
  BYE         a player's production: per available week (his NFL team's bye
              weeks are not available) × the available weeks in a season. Josh
              Jacobs' five suspended weeks of five are on pace for 16, Calvin
              Ridley's 2022 record — a bye is neither a suspension nor a game.
  SHAPE       a team / league total: the share of a season's total the league's
              completed seasons had reached by this week (pooled), so late-season
              piles (empty slots, hardship, injuries) and byes are priced in.
  CALENDAR    a transaction count or FAAB: the share of a season's moves the
              completed seasons had made by this week, dated off add_drops /
              trades — offseason moves land in week 1 there just as here.
  SUSPENSION  team / league suspended weeks: what is in, plus every player still
              suspended this week staying out for his available weeks left.
  BASE        "Change in points from career / previous season": the points are
              projected (BYE) and the fixed baseline taken off again.
  ASIS        rates, averages, running averages (Tanking), levels, changes of a
              rate: their current value is their pace.
  ACTUAL      not projectable: a distinct count (players / NFL teams / teams /
              cuffs, which level off and have caps), a season max or min, a net
              change between two rosters (in-season turnover), or a stat the
              offseason finished (offseason trades / turnover, the draft). Its
              actual value is reported once it beats every completed season.
  SKIP        not a season stat at all (Future draft capital is a snapshot).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd

LINEAR, BYE, SHAPE, CALENDAR, SUSPENSION, BASE, ASIS, ACTUAL, SKIP = (
    "linear", "bye", "shape", "calendar", "suspension", "base", "asis", "actual", "skip")

# Not a season stat: a forward-looking snapshot of picks held.
_SKIP = {"future draft capital"}

# Finished before the season's first kickoff: what is in is the season's value.
_DONE_PREFIXES = ("offseason ",)
_DONE = {"number of first round picks made", "total number of picks made", "draft value"}

# Season maxima / minima and net changes between two rosters.
_EXTREMA = {"highest starter score", "lowest starter score",
            "inseason roster turnover", "inseason starter turnover"}

# "Change in points from X" = this season's full-season points − a fixed baseline.
_BASE = {"change in points from career": "Points (full season)",
         "change in points from previous season": "Points (full season)"}

# Transaction counts and FAAB -> the calendar of the add_drops / trades rows.
_CALENDAR = {
    "number of add/drops": "adddrop",
    "number of waiver adds": "waiver",
    "number of free agency adds": "fa",
    "number of pure drops": "puredrop",
    "number of drops": "drop",
    "amount of faab spent": "faab",
    "inseason trades": "inseason_trade",
    "total trades": "trade",
    "number of trades": "trade",
    "total transactions": "transaction",
}

_SUSPENSION = {"weeks suspensions", "weeks of starter suspensions",
               "number of weeks missed due to suspensions"}

# A player's weeks that tick by whether he can play or not.
_PLAYER_CALENDAR_WEEKS = {"weeks rostered", "weeks on bench"}

# The weekly column a season column sums, where its name differs.
SHAPE_ALIAS = {
    ("teams", "Points"): "PF",
    ("teams", "Weeks of injuries"): "Number of Injuries",
    ("teams", "Weeks of starter injuries"): "Number of starter injuries",
    ("league", "Number of weeks missed due to injury"): "Number of Injuries",
}


def _distinct_count(c: str) -> bool:
    """"Number of QB started", "Number of rookies rostered", "Number of cuffs
    started", "Number of NFL teams among rostered players", "Number of teams":
    distinct players / teams over the season."""
    if c == "number of teams" or c.startswith("number of nfl teams among"):
        return True
    return c.startswith("number of ") and (c.endswith(" started") or c.endswith(" rostered"))


def pace_mode(section: str, column: str, *, is_rate, is_counting, is_weekly_count) -> str:
    """The projection rule for one season column (module docstring).

    The digest's own classifiers are passed in (`is_rate_stat`, `is_counting_stat`,
    `is_weekly_counting_stat`) so this module stays the single list of pace
    rules without importing the digest."""
    c = " ".join(str(column).lower().split())
    if is_weekly_count(column):
        return SKIP                 # awards / result flips: the records path
    if c in _SKIP:
        return SKIP
    if c.startswith(_DONE_PREFIXES) or c in _DONE:
        return ACTUAL
    if _distinct_count(c) or c.startswith("most number of") or c in _EXTREMA:
        return ACTUAL
    if section == "players" and c in _BASE:
        return BASE
    if c in _CALENDAR:
        return CALENDAR
    if c in _SUSPENSION and section in ("teams", "league"):
        return SUSPENSION
    if is_rate(column) or not is_counting(column):
        return ASIS
    if section == "players":
        return LINEAR if c in _PLAYER_CALENDAR_WEEKS else BYE
    return SHAPE


def base_column(column: str) -> Optional[str]:
    return _BASE.get(" ".join(str(column).lower().split()))


def calendar_kind(column: str) -> Optional[str]:
    return _CALENDAR.get(" ".join(str(column).lower().split()))


def is_actual_low_end(column: str) -> bool:
    """A season MINIMUM's record is its low end ("Lowest starter score")."""
    return " ".join(str(column).lower().split()) == "lowest starter score"


# ---------------------------------------------------------------------------
# Byes
# ---------------------------------------------------------------------------
def bye_weeks(schedule, season: int, horizon: int) -> Dict[str, set]:
    """{NFL team: its bye week(s) in fantasy weeks 1..horizon}, from a
    `gametime.Schedule` (kickoffs keyed (season, week, team)). {} without one."""
    if schedule is None or not getattr(schedule, "kickoff", None):
        return {}
    played: Dict[str, set] = {}
    for (s, w, t) in schedule.kickoff:
        if s == season:
            played.setdefault(t, set()).add(w)
    weeks = set(range(1, horizon + 1))
    return {t: weeks - ws for t, ws in played.items() if ws}


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------
def _kickoff_tuesday(season: int) -> date:
    sept1 = date(int(season), 9, 1)
    labor_day = sept1.toordinal() + (0 - sept1.weekday()) % 7
    return date.fromordinal(labor_day + 1)


def _move_week(when, season: int) -> Optional[int]:
    """Fantasy week a dated move counts in, for its `season`: before week 1's
    Tuesday -> week 1 (the offseason lands there, as on the sheets)."""
    try:
        d = date.fromisoformat(str(when).strip()[:10])
    except ValueError:
        return None
    start = _kickoff_tuesday(season)
    return 1 if d < start else (d - start).days // 7 + 1


def calendar_shares(add_drops: Optional[pd.DataFrame], trades: Optional[pd.DataFrame],
                    season: int, played: int) -> Dict[str, float]:
    """{kind: share of a completed season's moves made by week `played`},
    pooled over every completed season with any. Kinds as `_CALENDAR`."""
    tallies: Dict[str, list] = {}

    def add(kind, wk, weight=1.0):
        t = tallies.setdefault(kind, [0.0, 0.0])
        t[1] += weight
        if wk is not None and wk <= played:
            t[0] += weight

    def seasons(df):
        return pd.to_numeric(df.get("Season"), errors="coerce") if df is not None else None

    if add_drops is not None and not add_drops.empty and {"Date", "Season"} <= set(add_drops.columns):
        yrs = seasons(add_drops)
        kind_col = next((c for c in add_drops.columns if c.lower().startswith("type of add")), None)
        for i, (y, d) in enumerate(zip(yrs, add_drops["Date"])):
            if pd.isna(y) or int(y) >= season:
                continue
            row = add_drops.iloc[i]
            wk = _move_week(d, int(y))
            added = str(row.get("Player Added") or "").strip() not in ("", "nan", "None", "N/A")
            dropped = str(row.get("Player Dropped") or "").strip() not in ("", "nan", "None", "N/A")
            typ = str(row.get(kind_col) or "").lower() if kind_col else ""
            add("adddrop", wk)
            add("transaction", wk)
            if added and "waiver" in typ:
                add("waiver", wk)
            if added and "free" in typ:
                add("fa", wk)
            if dropped and not added:
                add("puredrop", wk)
            if dropped:
                add("drop", wk)
            faab = pd.to_numeric(pd.Series([row.get("Faab")]), errors="coerce").iloc[0]
            if pd.notna(faab) and faab > 0:
                add("faab", wk, float(faab))
    if trades is not None and not trades.empty and {"Date", "Season"} <= set(trades.columns):
        yrs = seasons(trades)
        seen = set()
        for y, d in zip(yrs, trades["Date"]):
            if pd.isna(y) or int(y) >= season or (int(y), str(d)) in seen:
                continue
            seen.add((int(y), str(d)))       # one trade, however many teams
            wk = _move_week(d, int(y))
            add("trade", wk)
            add("transaction", wk)
            try:
                inseason = date.fromisoformat(str(d)[:10]) >= _kickoff_tuesday(int(y))
            except ValueError:
                inseason = False
            if inseason:
                add("inseason_trade", wk)
    return {k: (by / tot) for k, (by, tot) in tallies.items() if tot > 0 and by > 0}


def shape_share(week_df: Optional[pd.DataFrame], column: str, season: int,
                played: int, horizon: int) -> Optional[float]:
    """Share of a season's total of weekly `column` the completed full-length
    seasons had reached by week `played` (pooled). None for a signed column (a
    share of a sum that can cancel means nothing) or with no history."""
    if week_df is None or week_df.empty or column not in week_df.columns \
            or not {"Year", "Week"} <= set(week_df.columns):
        return None
    yrs = pd.to_numeric(week_df["Year"], errors="coerce")
    wks = pd.to_numeric(week_df["Week"], errors="coerce")
    vals = pd.to_numeric(week_df[column], errors="coerce")
    full = {int(y) for y, m in wks.groupby(yrs).max().items()
            if pd.notna(y) and int(y) < season and m == horizon}
    sel = yrs.isin(full) & vals.notna()
    if not sel.any() or (vals[sel] < 0).any():
        return None
    tot = float(vals[sel].sum())
    by = float(vals[sel & (wks <= played)].sum())
    return by / tot if tot > 0 and by > 0 else None


# ---------------------------------------------------------------------------
# The projector
# ---------------------------------------------------------------------------
@dataclass
class PaceContext:
    """Everything a projection needs about the season so far, built once."""
    season: int
    played: int
    horizon: int
    calendar: Dict[str, float] = field(default_factory=dict)
    # {NFL team: bye weeks this season}; a player's NFL team now.
    byes: Dict[str, set] = field(default_factory=dict)
    nfl_team: Dict[str, str] = field(default_factory=dict)
    # Players suspended in the latest week: {team: [player]}, and the league's.
    suspended: Dict[str, list] = field(default_factory=dict)
    week_frames: Dict[str, Optional[pd.DataFrame]] = field(default_factory=dict)
    _shape: Dict[Tuple[str, str], Optional[float]] = field(default_factory=dict)

    @property
    def linear(self) -> float:
        return self.horizon / self.played

    def bye_split(self, player: str) -> Tuple[int, int]:
        """(bye weeks behind him, bye weeks ahead) for his current NFL team; a
        player with no known team or schedule gets none."""
        team = self.nfl_team.get(str(player))
        bw = self.byes.get(team or "", set())
        return (sum(1 for w in bw if w <= self.played),
                sum(1 for w in bw if self.played < w <= self.horizon))

    def per_available_week(self, player: str, cur: float) -> Optional[float]:
        """cur over his available weeks so far, × his available weeks in the season."""
        behind, ahead = self.bye_split(player)
        avail_so_far = self.played - behind
        if avail_so_far <= 0:
            return None
        return cur + cur / avail_so_far * ((self.horizon - self.played) - ahead)

    def available_weeks_left(self, player: str) -> int:
        _behind, ahead = self.bye_split(player)
        return max(0, (self.horizon - self.played) - ahead)

    def shape(self, section: str, column: str) -> Optional[float]:
        key = (section, column)
        if key not in self._shape:
            weekly = SHAPE_ALIAS.get(key, column)
            self._shape[key] = shape_share(self.week_frames.get(section), weekly,
                                           self.season, self.played, self.horizon)
        return self._shape[key]

    def project(self, section: str, entity: str, column: str, cur: float, mode: str,
                row: Optional[dict] = None) -> Optional[float]:
        """The season value `cur` is on pace for, under `mode`; None when it is
        not projected (ACTUAL / SKIP, or no available week to rate it on)."""
        if mode == ASIS:
            return cur
        if mode == LINEAR:
            return cur * self.linear
        if mode == BYE:
            return self.per_available_week(entity, cur)
        if mode == SHAPE:
            f = self.shape(section, column)
            return cur / f if f else cur * self.linear
        if mode == CALENDAR:
            f = self.calendar.get(calendar_kind(column) or "")
            return cur / f if f else cur * self.linear
        if mode == SUSPENSION:
            out_now = (self.suspended.get(entity, []) if section == "teams"
                       else [p for ps in self.suspended.values() for p in ps])
            return cur + sum(self.available_weeks_left(p) for p in out_now)
        if mode == BASE:
            base_col = base_column(column)
            try:
                base_cur = float((row or {}).get(base_col))
            except (TypeError, ValueError):
                return None
            if pd.isna(base_cur):
                return None
            proj = self.per_available_week(entity, base_cur)
            return None if proj is None else proj - (base_cur - cur)
        return None


def latest_week_facts(player_week: Optional[pd.DataFrame], season: int,
                      played_weeks: Iterable[int]) -> Tuple[Dict[str, str], Dict[str, list]]:
    """({player: NFL team in his latest week this season}, {team: players
    suspended in the latest week}) off player_week."""
    teams: Dict[str, str] = {}
    suspended: Dict[str, list] = {}
    if player_week is None or player_week.empty or \
            not {"Player", "Year", "Week"} <= set(player_week.columns):
        return teams, suspended
    pw = player_week[pd.to_numeric(player_week["Year"], errors="coerce") == season]
    if pw.empty:
        return teams, suspended
    wk = pd.to_numeric(pw["Week"], errors="coerce")
    pw = pw.assign(_w=wk).sort_values("_w")
    if "NFL team" in pw.columns:
        for p, t in zip(pw["Player"].astype(str), pw["NFL team"].astype(str)):
            if t and t not in ("nan", "None", "NFL"):
                teams[p] = t
    last = max(played_weeks) if played_weeks else wk.max()
    if "Suspension?" in pw.columns and "Team" in pw.columns:
        cur = pw[pw["_w"] == last]
        flag = cur["Suspension?"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
        for t, p in zip(cur.loc[flag, "Team"].astype(str), cur.loc[flag, "Player"].astype(str)):
            suspended.setdefault(t, []).append(p)
    return teams, suspended
