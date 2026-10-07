"""Game times: which slot each player's NFL game fell in, and where a matchup
stood entering Sunday night, Monday night and its own last game.

Used by the build (player_week "Game slot", the team_week margin and comeback
columns) and by `scripts/inquire.py gametime`, so both read a week the same way.

Inputs are the nflverse schedule the build already caches
(`.cache/nfldata_games.csv`: `gameday`, `weekday`, `gametime` in ET) and the
starters' `NFL team` / `Points` from player_week. A starter's points are placed
at his team's kickoff that week; the league week is the NFL week.

Rules [per user, 2026-10-05]:

- **Game slot** is the kickoff's place in the week: `Thursday` / `Friday` /
  `Saturday` (and `Wednesday` for a Christmas game played before Sunday),
  `Sunday morning` (before 1 pm ET — the international games), `Sunday early`
  (1 pm), `Sunday late` (4 pm), `SNF` (7 pm or later), then `MNF` and, after
  it, `Tuesday` / `Wednesday` (2020's COVID makeups). `Bye` when his team had
  no game that week; N/A without an NFL team.
- **Entering a stage** = every point scored in games that kicked off before it.
  SNF = the first Sunday game at 7 pm or later; Monday = the first game after
  the week's Sunday, so 2020's Tuesday/Wednesday makeups are part of Monday;
  last game = the latest kickoff with a starter from either side of the
  matchup, pulled back to the start of its window (`windows`: a game is over
  GAME_HOURS after kickoff, so the late half of a Monday doubleheader is
  entered when the early half kicks off), and only when it is SNF or later
  (else N/A). A week with no such
  game is N/A. Games that kick off together all count as that stage.
- **Margin entering X** = own points going in minus the opponent's points going
  in. The semifinal +5 counts: points going in are PF minus the starters'
  points from that kickoff on, so the bonus is in from the start.
Comeback columns, per stage X [renamed and extended per user, 2026-10-06]:

- **Margin overcome (entering X)** = how far behind the team was at that moment
  (−Margin entering X), when it was behind and won.
- **Points overcome (entering X)** = the opponent's FINAL score minus own points
  going in, when that is above 0 and the team won (whatever the margin then: it
  is judged against the final, so the opponent's own late players count).
- **% of own points scored X or later** (`in last game` for the last-game stage)
  = own points from that kickoff on ÷ PF. Every game the stage happened in, not
  only comebacks.
- **% of opponent's final points overcome (entering X)** = points overcome ÷ the
  opponent's final.
- **Points / Margin overcome per player left (entering X)** = points / margin
  overcome ÷ the team's own starters still to play from that kickoff on.
- **% of opponent's score overcome (X or later)** = margin overcome ÷ the
  opponent's points going in.
  The overcome columns are N/A unless the team won from behind; % columns are
  fractions (the workbook shows them as percents).
- **Comeback size (entering X)** and **Comeback size** (every kickoff in the
  week) — every game, comeback or not; see `comeback_size`. 0.00 = never
  behind its expected finish (a blowout that never got close).

Comeback size model [per user, 2026-10-06; chosen by log loss over 2020-25]:
at any kickoff, the team's expected final margin is the margin going in plus
the expected points of its starters still to play minus the opponent's. A
starter's expectation is his CLAUDE PROJECTION — the pre-kickoff expected
points `lotg_support.boldness` computes (named so not to be confused with the
Boldness stat) [per user, 2026-10-07]: his
recency-weighted NFL games scored with that season's rules, the LOTG rookie-slot
prior, the next-man-up cuff lift) — the same prediction Boldness judges lineups
on; a starter known to be out (a dead start: flagged bye / injured /
suspended, scored 0) expects 0. A start boldness lacks falls back to his
season-to-date points per game padded with last season and the position
(`expected_points`). Each player's points vary like 2.0·√(his expectation);
z = expected final margin ÷ the spread of everything still to play; win chance
= Φ(z), taken at the start of each kickoff window (never with a game half
played). A team BEHIND ON THE SCOREBOARD has its hole measured from the
projection less a band for projection error, 2.5 × √(starters still to play)
(`projection_band`) [per user, 2026-10-07]: down 57.38 with 4 left and
projected 58 or 60 is a comeback, projected 69.4 is not. The band is the 75th
percentile of how far the Claude and Sleeper projections (what the league
sees live; Sleeper's are fetched only for that test, never by the build)
disagree on the final margin. Depth of a hole = −z when z < 0 (standard deviations behind the
expected finish, capped at 10). Comeback size = the largest depth × the win
chance at any later point (1 at the end for a win, 0 for a loss) × how much of
the turnaround in between the team's own players made: HOLD_SHARE (¼) + ¾ × own
share, own share = own points over expectation ÷ (that + the opponent's points
short of expectation), clipped to 0-1. A win from the hole on the team's own
players scores its whole depth; a lead that survived only because the
opponent's late players fell short counts a quarter [per user: a hold is a
comeback, "but not as a big one"]; a loss scores the comeback it was on course
for at its best moment.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

NA = "N/A"

SNF_HOUR = 19        # a Sunday kickoff at 7 pm ET or later is the night game
EARLY_HOUR = 13      # before 1 pm ET: an international morning game
LATE_HOUR = 16       # 4 pm ET window

STAGES = ("SNF", "Monday", "last game")

# Team-week columns, in sheet order.
MARGIN_COLUMNS = {s: f"Margin entering {s}" for s in STAGES}


def _stage_columns(s: str) -> Tuple[str, ...]:
    later = "in last game" if s == "last game" else f"{s} or later"
    after = "last game" if s == "last game" else f"{s} or later"
    return (f"Margin overcome (entering {s})",
            f"Points overcome (entering {s})",
            f"% of own points scored {later}",
            f"% of opponent's final points overcome (entering {s})",
            f"Points overcome per player left (entering {s})",
            f"Margin overcome per player left (entering {s})",
            f"% of opponent's score overcome ({after})",
            f"Comeback size (entering {s})")


COMEBACK_COLUMNS = {s: _stage_columns(s) for s in STAGES}
COMEBACK_SIZE_COLUMN = "Comeback size"
TEAM_WEEK_COLUMNS: Tuple[str, ...] = tuple(
    [MARGIN_COLUMNS[s] for s in STAGES] + [c for s in STAGES for c in COMEBACK_COLUMNS[s]]
    + [COMEBACK_SIZE_COLUMN])
# Fractions on the sheet (the workbook formats them as percents).
PERCENT_COLUMNS = frozenset(c for s in STAGES for c in COMEBACK_COLUMNS[s] if c.startswith("% of "))
# What was overcome, on a comeback only: the digest ranks only the high end —
# the low end is a pile of 0.1-point "comebacks", not records.
HIGH_END_ONLY = frozenset(c for s in STAGES for i, c in enumerate(COMEBACK_COLUMNS[s])
                          if i in (0, 1, 3, 4, 5, 6))
# #477's names -> today's, for the columns whose meaning and scale did not change
# (the digest snapshot keys boards by column name). The two old % columns were
# 0-100 and are fractions now, and "% of points going in" became a different
# stat, so they start fresh rather than being carried over.
LEGACY_COLUMNS = {
    old: new for s in STAGES for old, new in (
        (f"Down entering {s} comeback (margin overcome)", COMEBACK_COLUMNS[s][0]),
        (f"Down entering {s} comeback (points overcome)", COMEBACK_COLUMNS[s][1]),
        (f"Down entering {s} comeback (per player left)", COMEBACK_COLUMNS[s][4]))
}

# Comeback size model (see the module docstring).
SD_PER_ROOT_POINT = 2.0        # a starter's points vary like 2.0·√(his expectation)
HOLD_SHARE = 0.25              # what a turnaround counts for when the team's own players did none of it
Z_CAP = 10.0
BAND_PER_ROOT_STARTER = 2.5    # projection-error band for a team behind on the scoreboard
GAME_HOURS = 3.0               # a game is over this long after kickoff (see `windows`)
# Fallback expectation, for a starter boldness has none for (or a build where
# boldness failed): season-to-date PPG padded with last season and the position.
EXPECT_POSITION_GAMES = 6      # games' worth of the position average in a starter's expectation
EXPECT_LAST_SEASON_GAMES = 4   # games' worth of his last-season average, when he has one
POSITION_PRIOR_STARTS = 20     # starts' worth of the fixed seed in the position average
POSITION_SEED = {"QB": 18.0, "RB": 15.0, "WR": 14.0, "TE": 11.5}   # starter PPG, 2020-25, rounded
SEED_OTHER = 14.0
GAME_SLOT_COLUMN = "Game slot"

# Sleeper / ESPN spellings the nflverse schedule writes differently.
_TEAM_ALIASES = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV",
                 "SD": "LAC", "STL": "LA"}


# Games nflverse struck but the league played: see lotg_support.struck_games.
from lotg_support.struck_games import STRUCK_GAMES, restore_struck_games  # noqa: E402,F401


def norm_team(team) -> str:
    t = str(team or "").strip().upper()
    return _TEAM_ALIASES.get(t, t)


@dataclass(frozen=True)
class Schedule:
    """Kickoffs (naive ET datetimes) per (season, week, team), and each week's Sunday."""
    kickoff: Dict[Tuple[int, int, str], datetime]
    sunday: Dict[Tuple[int, int], date]

    def week_kickoffs(self, season: int, week: int) -> List[datetime]:
        return sorted({k for (s, w, _t), k in self.kickoff.items() if s == season and w == week})

    def team_kickoff(self, season, week, team) -> Optional[datetime]:
        return self.kickoff.get((int(season), int(week), norm_team(team)))

    def stage_start(self, season: int, week: int, stage: str) -> Optional[datetime]:
        """First kickoff of a league-wide stage: 'SNF', 'Monday', or any game
        slot name ('Sunday early', 'Sunday late', ...). None if the week has none."""
        sun = self.sunday.get((int(season), int(week)))
        if sun is None:
            return None
        if stage == "Monday":
            stage = "MNF"
        ks = self.week_kickoffs(int(season), int(week))
        if stage == "MNF":   # the first game after Sunday, makeups included
            later = [k for k in ks if k.date() > sun]
            return later[0] if later else None
        hit = [k for k in ks if game_slot(k, sun) == stage]
        return hit[0] if hit else None


def load_schedule(games: pd.DataFrame) -> Schedule:
    """Schedule from the nfldata games table (regular season only — the league's
    weeks are NFL regular-season weeks)."""
    kick: Dict[Tuple[int, int, str], datetime] = {}
    sunday: Dict[Tuple[int, int], date] = {}
    if games is None or games.empty or not {"season", "week", "gameday", "gametime",
                                            "home_team", "away_team"}.issubset(games.columns):
        return Schedule(kick, sunday)
    g = restore_struck_games(games)
    if "game_type" in g.columns:
        g = g[g["game_type"].astype(str).str.upper() == "REG"]
    for s, w, gd, gt, h, a in g[["season", "week", "gameday", "gametime", "home_team", "away_team"]] \
            .dropna(subset=["season", "week", "gameday"]).itertuples(index=False):
        try:
            d = datetime.strptime(str(gd)[:10], "%Y-%m-%d").date()
            hh, mm = (str(gt).strip() or "13:00").split(":")[:2] if isinstance(gt, str) else ("13", "00")
            k = datetime.combine(d, time(int(hh), int(mm)))
        except (ValueError, TypeError):
            continue
        for t in (h, a):
            if isinstance(t, str) and t:
                kick[(int(s), int(w), norm_team(t))] = k
        if d.weekday() == 6:
            sunday[(int(s), int(w))] = d
    return Schedule(kick, sunday)


def game_slot(kickoff: Optional[datetime], sunday: Optional[date]) -> str:
    """The kickoff's slot in its week (see the module docstring)."""
    if kickoff is None:
        return "Bye"
    d = kickoff.date()
    if sunday is None or d != sunday:
        if sunday is not None and d > sunday and d.weekday() == 0:
            return "MNF"
        return kickoff.strftime("%A")
    h = kickoff.hour
    if h < EARLY_HOUR:
        return "Sunday morning"
    if h < LATE_HOUR:
        return "Sunday early"
    if h < SNF_HOUR:
        return "Sunday late"
    return "SNF"


def player_slot(schedule: Schedule, season, week, nfl_team) -> str:
    """Game slot for a player_week row; N/A without a real NFL team."""
    t = norm_team(nfl_team)
    if not t or t in ("NFL", "NAN", "NONE", "FA", "N/A"):
        return NA
    try:
        s, w = int(season), int(week)
    except (TypeError, ValueError):
        return NA
    return game_slot(schedule.kickoff.get((s, w, t)), schedule.sunday.get((s, w)))


def late_threshold(sunday: Optional[date]) -> Optional[datetime]:
    """'After Sunday afternoon': Sunday 7 pm ET."""
    return datetime.combine(sunday, time(SNF_HOUR)) if sunday else None


# A starter's week: (kickoff or None, points, expected points, known out?).
# Known out (a dead start: flagged bye / injured / suspended, scored 0)
# expects 0 with no spread — the lineup's manager could see it before kickoff.
Play = Tuple[Optional[datetime], float, float, bool]


def _mu(s: Sequence) -> float:
    return 0.0 if len(s) > 3 and s[3] else s[2]


def _var(s: Sequence) -> float:
    return 0.0 if len(s) > 3 and s[3] else SD_PER_ROOT_POINT ** 2 * max(s[2], 1.0)


def points_from(starters: Iterable[Sequence], t: datetime) -> float:
    """Points scored in games kicking off at or after t."""
    return sum(s[1] for s in starters if s[0] is not None and s[0] >= t)


def _left(starters: Iterable[Sequence], t: datetime) -> List[Sequence]:
    return [s for s in starters if s[0] is not None and s[0] >= t]


def comeback(own_in: float, opp_final: float, won: bool, players_left: int = 0):
    """(points overcome, fraction of own points going in, fraction of the
    opponent's final, per own player left), or None."""
    deficit = round(float(opp_final) - float(own_in), 2)
    if not won or deficit <= 0:
        return None
    pct_in = round(deficit / own_in, 4) if own_in > 0 else None
    pct_opp = round(deficit / opp_final, 4) if opp_final > 0 else None
    per_player = round(deficit / players_left, 2) if players_left > 0 else None
    return deficit, pct_in, pct_opp, per_player


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def win_z(own_in: float, opp_in: float, own_left: Sequence[Sequence],
          opp_left: Sequence[Sequence], band: float = 0.0) -> float:
    """Expected final margin (less `band`) ÷ its spread, from points going in
    and the expected points of the starters still to play (capped at ±Z_CAP)."""
    mean = own_in - opp_in + sum(_mu(s) for s in own_left) - sum(_mu(s) for s in opp_left) - band
    var = sum(_var(s) for s in list(own_left) + list(opp_left))
    if var <= 0:
        z = Z_CAP if mean > 0 else (-Z_CAP if mean < 0 else 0.0)
    else:
        z = mean / math.sqrt(var)
    return max(-Z_CAP, min(Z_CAP, z))


def projection_band(own_in: float, opp_in: float, own_left: Sequence[Sequence],
                    opp_left: Sequence[Sequence]) -> float:
    """Points of projection error a team BEHIND ON THE SCOREBOARD is allowed:
    BAND_PER_ROOT_STARTER × √(starters still to play on both sides, known outs
    aside); 0 when level or ahead. [per user, 2026-10-07] down 57.38 with 4
    starters projected 58 or 60 is a comeback, projected 69.4 is not: the band
    for 4 left is 5.0 — the 75th percentile of how far the Claude and Sleeper
    own projections (what the league sees live) disagree on the final margin."""
    if own_in - opp_in >= 0:
        return 0.0
    n = sum(1 for s in list(own_left) + list(opp_left) if not (len(s) > 3 and s[3]))
    return BAND_PER_ROOT_STARTER * math.sqrt(n)


def _own_part(hole: Sequence[float], later: Sequence[float]) -> float:
    """HOLD_SHARE + the rest × the share of the turnaround between two points
    that the team's own players made (points over their expectation), against
    the opponent's falling short of theirs. 1 = all its own doing; HOLD_SHARE =
    none (a lead that survived the opponent's late players, own side done)."""
    own = hole[1] - later[1]
    turn = own + (hole[2] - later[2])
    share = min(1.0, max(0.0, own / turn)) if turn > 0 else 0.0
    return HOLD_SHARE + (1.0 - HOLD_SHARE) * share


def comeback_size(points: Sequence[Sequence[float]], final: float, from_first: bool = False) -> float:
    """Largest depth (−z, when behind) × the win chance at any later point ×
    the own-doing factor (`_own_part`) between them; the end counts as win
    chance `final` (1 win, 0 loss, ½ tie). `points` in time order, each
    (z, own players' points over expectation still to come, the opponent's
    shortfall still to come[, the hole's z: z with the projection band]) — a
    bare z means no split is known (factor 1). The hole's depth reads the
    banded z (`projection_band`), the later win chance the plain one.
    `from_first` = only the first point's hole counts (a stage's version)."""
    split = [p for p in points if isinstance(p, (tuple, list))]
    pts = [p if isinstance(p, (tuple, list)) else (p, 0.0, 0.0) for p in points]
    later = [(_phi(p[0]), p) for p in pts] + [(final, (None, 0.0, 0.0))]
    best = 0.0
    for i, hole in enumerate(pts[:1] if from_first else pts):
        depth = max(0.0, -(hole[3] if len(hole) > 3 else hole[0]))
        for chance, p in later[i + 1:]:
            if depth:
                best = max(best, depth * chance * (_own_part(hole, p) if split else 1.0))
    return round(best, 2)


def matchup_stage(own: Sequence[Sequence], opp: Sequence[Sequence],
                  own_final: float, opp_final: float, won: bool,
                  t: Optional[datetime]) -> dict:
    """Margin entering t and the comeback from t, for one side of a matchup."""
    if t is None:
        return {"in": None, "opp_in": None, "margin": None, "left": None, "comeback": None}
    own_in = round(own_final - points_from(own, t), 2)
    opp_in = round(opp_final - points_from(opp, t), 2)
    left = len(_left(own, t))
    return {"in": own_in, "opp_in": opp_in, "margin": round(own_in - opp_in, 2), "left": left,
            "comeback": comeback(own_in, opp_final, won, left)}


def checkpoint_z(own: Sequence[Sequence], opp: Sequence[Sequence], own_final: float,
                 opp_final: float, t: datetime) -> float:
    """win_z entering kickoff t."""
    return win_z(own_final - points_from(own, t), opp_final - points_from(opp, t),
                 _left(own, t), _left(opp, t))


def checkpoint(own: Sequence[Sequence], opp: Sequence[Sequence], own_final: float,
               opp_final: float, t: datetime) -> Tuple[float, float, float, float]:
    """(z, own points over expectation still to come, opponent's shortfall
    still to come, the hole's z with the projection band) entering kickoff t —
    a `comeback_size` point."""
    ol, pl = _left(own, t), _left(opp, t)
    own_in, opp_in = own_final - points_from(own, t), opp_final - points_from(opp, t)
    return (win_z(own_in, opp_in, ol, pl),
            sum(s[1] - _mu(s) for s in ol), sum(_mu(s) - s[1] for s in pl),
            win_z(own_in, opp_in, ol, pl, projection_band(own_in, opp_in, ol, pl)))


def kickoffs(own: Sequence[Sequence], opp: Sequence[Sequence]) -> List[datetime]:
    """The matchup's distinct kickoffs, in order."""
    return sorted({s[0] for s in list(own) + list(opp) if s[0] is not None})


def windows(own: Sequence[Sequence], opp: Sequence[Sequence]) -> List[datetime]:
    """The matchup's kickoff windows, by their first kickoff: a kickoff opens a
    new window only when every earlier game is over (GAME_HOURS after its
    kickoff). 4:05 + 4:25, or a Monday doubleheader, is one window: entering
    the 4:25 game, the 4:05 game is still being played, so no moment has the
    one done and the other not started [per user, 2026-10-06]."""
    out: List[datetime] = []
    prev = None
    for k in kickoffs(own, opp):
        if prev is None or k - prev >= timedelta(hours=GAME_HOURS):
            out.append(k)
        prev = k
    return out


def last_game_start(schedule: Schedule, season: int, week: int,
                    own: Sequence[Sequence], opp: Sequence[Sequence]) -> Optional[datetime]:
    """Start of the matchup's last window (`windows`: the latest kickoff with a
    starter from either side, pulled back to the first kickoff of any game still
    being played then), if SNF or later."""
    ws = windows(own, opp)
    thr = late_threshold(schedule.sunday.get((int(season), int(week))))
    if not ws or thr is None:
        return None
    return ws[-1] if ws[-1] >= thr else None


def _won(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "1.0", "yes")


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def expected_points(player_week: pd.DataFrame, schedule: Schedule) -> pd.Series:
    """Each starter row's expected points (NaN elsewhere), from games before
    that week only: his points per game this season, padded with
    EXPECT_LAST_SEASON_GAMES at his last-season average and EXPECT_POSITION_GAMES
    at the position's starter average to date. History = his rostered weeks with
    a game on the schedule (bench weeks too); keyed by Player ID when the frame
    has one (the build), else by name (the exports)."""
    out = pd.Series(float("nan"), index=player_week.index, dtype=float)
    if player_week is None or player_week.empty:
        return out
    id_col = next((c for c in ("Player ID", "Player") if c in player_week.columns), None)
    key = player_week[id_col].astype(str) if id_col else pd.Series(  # no names: no history
        [f"row {i}" for i in player_week.index], index=player_week.index)
    yr = pd.to_numeric(player_week["Year"], errors="coerce")
    wk = pd.to_numeric(player_week["Week"], errors="coerce")
    pts = pd.to_numeric(player_week["Points"], errors="coerce").fillna(0.0)
    pos = player_week["Position"].astype(str) if "Position" in player_week.columns \
        else pd.Series("", index=player_week.index)
    starter = player_week["Starter/Bench"].astype(str).str.lower() == "starter"
    had_game = pd.Series([y == y and w == w and schedule.team_kickoff(y, w, t) is not None
                          for y, w, t in zip(yr, wk, player_week["NFL team"])], index=player_week.index)
    t = yr * 100 + wk
    hist: Dict[str, Tuple[list, list]] = {}
    for k, tt, p in sorted(zip(key[had_game], t[had_game], pts[had_game]), key=lambda r: (r[0], r[1])):
        h = hist.setdefault(k, ([], []))
        h[0].append(int(tt)); h[1].append(float(p))
    # position starter average over every start before the week
    pos_hist: Dict[str, Tuple[list, list]] = {}
    for ps, tt, p in sorted(zip(pos[starter & had_game], t[starter & had_game], pts[starter & had_game]),
                            key=lambda r: (r[0], r[1])):
        h = pos_hist.setdefault(ps, ([], [0.0]))
        h[0].append(int(tt)); h[1].append(h[1][-1] + float(p))
    for i in player_week.index[starter & t.notna()]:
        ti, y, ps = int(t[i]), int(yr[i]), pos[i]
        seed = POSITION_SEED.get(ps, SEED_OTHER)
        ph = pos_hist.get(ps)
        n_pos = bisect_left(ph[0], ti) if ph else 0
        m0 = ((ph[1][n_pos] if ph else 0.0) + POSITION_PRIOR_STARTS * seed) / (n_pos + POSITION_PRIOR_STARTS)
        num, den = EXPECT_POSITION_GAMES * m0, float(EXPECT_POSITION_GAMES)
        h = hist.get(key[i])
        if h:
            ts, ps_ = h
            a, b = bisect_left(ts, (y - 1) * 100), bisect_left(ts, y * 100)
            if b > a:
                num += EXPECT_LAST_SEASON_GAMES * sum(ps_[a:b]) / (b - a)
                den += EXPECT_LAST_SEASON_GAMES
            c = bisect_left(ts, ti)
            num += sum(ps_[b:c]); den += c - b
        out[i] = num / den
    return out


def claude_projections(seasons: Sequence[int]) -> pd.DataFrame:
    """Every start's Claude projection — the pre-kickoff expected points
    `lotg_support.boldness` computes, the ones the build hands
    `team_week_columns` — read off the committed exports and snapshot: Year,
    Week, Team, Player, Player ID, E starter, Dead start?."""
    from lotg_support import boldness as B
    frames = []
    for season in sorted({int(x) for x in seasons}):
        b = B.boldness(season, include_live=False)
        if not b.empty:
            frames.append(b[b["Starter ID"].notna()][["Year", "Week", "Team", "Starter", "Starter ID",
                                                       "E starter", "Dead start?"]])
    if not frames:
        return pd.DataFrame(columns=["Year", "Week", "Team", "Player", "Player ID", "E starter", "Dead start?"])
    return pd.concat(frames, ignore_index=True).rename(columns={"Starter": "Player", "Starter ID": "Player ID"})


def starter_plays(player_week: pd.DataFrame, schedule: Schedule,
                  expected: Optional[pd.DataFrame] = None) -> Dict[Tuple[str, int, int], List[Play]]:
    """(Team, Year, Week) -> [(kickoff or None, points, expected points, known
    out?)] over the week's starters. `expected` = the Claude projection (pre-kickoff
    expectation per start (Year, Week, Team, Player ID or Player, E starter,
    Dead start?: the build's `boldness.build_columns`, or
    `claude_projections`); a start it lacks falls back to `expected_points`."""
    out: Dict[Tuple[str, int, int], List[Play]] = {}
    if player_week is None or player_week.empty:
        return out
    mu = expected_points(player_week, schedule)
    st = player_week[player_week["Starter/Bench"].astype(str).str.lower() == "starter"]
    known: Dict[tuple, Tuple[float, bool]] = {}
    key_col = None
    if expected is not None and not expected.empty:
        key_col = next((c for c in ("Player ID", "Player") if c in expected.columns and c in st.columns), None)
    if key_col:
        for y, w, t, k, e, d in expected[["Year", "Week", "Team", key_col, "E starter", "Dead start?"]] \
                .itertuples(index=False, name=None):
            e_ = _num(e)
            if _num(y) is not None and _num(w) is not None and e_ is not None:
                known[(int(_num(y)), int(_num(w)), str(t), str(k))] = (e_, _won(d))
    keys = st[key_col].astype(str) if key_col else pd.Series("", index=st.index)
    for i, team, y, w, nfl, pts, k in zip(st.index, st["Team"], st["Year"], st["Week"], st["NFL team"],
                                          st["Points"], keys):
        y_, w_ = _num(y), _num(w)
        if y_ is None or w_ is None:
            continue
        e = known.get((int(y_), int(w_), str(team), k))
        if e is None:
            m = mu.get(i)
            e = (m if m is not None and m == m else 0.0, False)
        out.setdefault((str(team), int(y_), int(w_)), []).append(
            (schedule.team_kickoff(y_, w_, nfl), _num(pts) or 0.0, e[0], e[1]))
    return out


def starter_kickoffs(player_week: pd.DataFrame, schedule: Schedule) -> Dict[Tuple[str, int, int], list]:
    """(Team, Year, Week) -> [(kickoff or None, points)] over the week's starters."""
    return {k: [(s[0], s[1]) for s in v] for k, v in starter_plays(player_week, schedule).items()}


def _pct(num, den) -> Optional[float]:
    return round(num / den, 4) if num is not None and den is not None and den > 0 else None


def stage_rows(team_week: pd.DataFrame, player_week: pd.DataFrame, schedule: Schedule,
               stage: str, plays: Optional[Dict] = None,
               expected: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Every team-week entering one stage: points going in on both sides, the
    margin, the comeback (vs the opponent's final) and its size. `stage` is
    'SNF', 'Monday', 'last game' or any game slot name. Percents are fractions."""
    starts = plays if plays is not None else starter_plays(player_week, schedule, expected)
    rows = []
    cols = list(team_week.columns)
    for vals in team_week.itertuples(index=False, name=None):
        rec = dict(zip(cols, vals))
        y, w = _num(rec.get("Year")), _num(rec.get("Week"))
        pf, pa = _num(rec.get("PF")), _num(rec.get("Points against"))
        if y is None or w is None or pf is None or pa is None:
            continue
        y, w = int(y), int(w)
        own = starts.get((str(rec["Team"]), y, w), [])
        opp = starts.get((str(rec["Opponent"]), y, w), [])
        if stage == "last game":
            t = last_game_start(schedule, y, w, own, opp)
        else:
            t = schedule.stage_start(y, w, stage)
        won = _won(rec.get("Win?"))
        final = 1.0 if won else (0.5 if pf == pa else 0.0)
        m = matchup_stage(own, opp, pf, pa, won, t)
        cb = m["comeback"]
        margin_over = -m["margin"] if won and m["margin"] is not None and m["margin"] < 0 else None
        size = None
        if t is not None:
            # Nothing changes between the stage and the matchup's next window,
            # so later points start after that one (never the same state twice);
            # only window starts are moments with every earlier game over.
            ks = windows(own, opp)
            k0 = next((k for k in ks if k >= t), None)
            zs = [checkpoint(own, opp, pf, pa, t)] + \
                 [checkpoint(own, opp, pf, pa, k) for k in ks if k0 is not None and k > k0]
            size = comeback_size(zs, final, from_first=True)
        rows.append({
            "Team": rec["Team"], "Year": y, "Week": w, "Week Name": rec.get("Week Name"),
            "Opponent": rec["Opponent"], "Win?": won, "PF": pf, "Points against": pa,
            "Stage kickoff": t.strftime("%a %Y-%m-%d %H:%M") if t else None,
            "Points going in": m["in"], "Opponent going in": m["opp_in"],
            "Margin entering": m["margin"], "Players left": m["left"],
            "Margin overcome": margin_over,
            "Points after": round(pf - m["in"], 2) if m["in"] is not None else None,
            "Opponent after": round(pa - m["opp_in"], 2) if m["opp_in"] is not None else None,
            "Points overcome": cb[0] if cb else None,
            "% of own points scored after": _pct(round(pf - m["in"], 2), pf) if m["in"] is not None else None,
            "% of opponent's final overcome": cb[2] if cb else None,
            "Points overcome per player left": cb[3] if cb else None,
            "Margin overcome per player left": (round(margin_over / m["left"], 2)
                                                if margin_over is not None and m["left"] else None),
            "% of opponent's score overcome": _pct(margin_over, m["opp_in"]),
            "Win chance going in": round(_phi(zs[0][0]), 4) if t is not None else None,
            "Comeback size": size,
        })
    return pd.DataFrame(rows)


def week_comeback_size(team_week: pd.DataFrame, player_week: pd.DataFrame, schedule: Schedule,
                       plays: Optional[Dict] = None,
                       expected: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Team, Year, Week, Comeback size over every kickoff of the matchup but the
    first (nothing has been scored entering it), plus the lowest win chance."""
    starts = plays if plays is not None else starter_plays(player_week, schedule, expected)
    rows = []
    cols = list(team_week.columns)
    for vals in team_week.itertuples(index=False, name=None):
        rec = dict(zip(cols, vals))
        y, w = _num(rec.get("Year")), _num(rec.get("Week"))
        pf, pa = _num(rec.get("PF")), _num(rec.get("Points against"))
        if y is None or w is None or pf is None or pa is None:
            continue
        y, w = int(y), int(w)
        own = starts.get((str(rec["Team"]), y, w), [])
        opp = starts.get((str(rec["Opponent"]), y, w), [])
        ks = windows(own, opp)
        won = _won(rec.get("Win?"))
        final = 1.0 if won else (0.5 if pf == pa else 0.0)
        zs = [checkpoint(own, opp, pf, pa, k) for k in ks[1:]]
        rows.append({"Team": rec["Team"], "Year": y, "Week": w, "Opponent": rec["Opponent"],
                     "Win?": won, "PF": pf, "Points against": pa,
                     "Lowest win chance": round(min(_phi(z[0]) for z in zs), 4) if zs else None,
                     COMEBACK_SIZE_COLUMN: comeback_size(zs, final) if ks else None})
    return pd.DataFrame(rows)


def team_week_columns(team_week: pd.DataFrame, player_week: pd.DataFrame,
                      schedule: Schedule, expected: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Team, Year, Week + TEAM_WEEK_COLUMNS, N/A where the stage did not happen
    or there was no comeback. `expected`: see `starter_plays`."""
    plays = starter_plays(player_week, schedule, expected)
    base = None
    for stage in STAGES:
        r = stage_rows(team_week, player_week, schedule, stage, plays)
        if r.empty:
            return pd.DataFrame(columns=["Team", "Year", "Week", *TEAM_WEEK_COLUMNS])
        names = COMEBACK_COLUMNS[stage]
        part = pd.DataFrame({"Team": r["Team"], "Year": r["Year"], "Week": r["Week"],
                             MARGIN_COLUMNS[stage]: r["Margin entering"]})
        for name, src in zip(names, ("Margin overcome", "Points overcome", "% of own points scored after",
                                     "% of opponent's final overcome", "Points overcome per player left",
                                     "Margin overcome per player left", "% of opponent's score overcome",
                                     "Comeback size")):
            part[name] = r[src]
        base = part if base is None else base.merge(part, on=["Team", "Year", "Week"], how="outer")
    size = week_comeback_size(team_week, player_week, schedule, plays)
    base = base.merge(size[["Team", "Year", "Week", COMEBACK_SIZE_COLUMN]], on=["Team", "Year", "Week"],
                      how="left")
    out = base[["Team", "Year", "Week", *TEAM_WEEK_COLUMNS]].astype(object)
    return out.where(pd.notna(out), NA)


def slot_points(player_week: pd.DataFrame, schedule: Schedule) -> pd.DataFrame:
    """Starter points per team-week by game slot (one column per slot seen)."""
    st = player_week[player_week["Starter/Bench"].astype(str).str.lower() == "starter"].copy()
    st["Game slot"] = [player_slot(schedule, y, w, t)
                       for y, w, t in zip(st["Year"], st["Week"], st["NFL team"])]
    st["Points"] = pd.to_numeric(st["Points"], errors="coerce").fillna(0.0)
    order = ["Wednesday", "Thursday", "Friday", "Saturday", "Sunday morning", "Sunday early",
             "Sunday late", "SNF", "MNF", "Tuesday", "Bye", NA]
    pv = st.pivot_table(index=["Team", "Year", "Week"], columns="Game slot", values="Points",
                        aggfunc="sum", fill_value=0.0)
    pv = pv[[c for c in order if c in pv.columns] + [c for c in pv.columns if c not in order]]
    return pv.round(2).reset_index()
