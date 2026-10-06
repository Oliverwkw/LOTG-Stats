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
  matchup, and only when it is SNF or later (else N/A). A week with no such
  game is N/A. Games that kick off together all count as that stage.
- **Margin entering X** = own points going in minus the opponent's points going
  in. The semifinal +5 counts: points going in are PF minus the starters'
  points from that kickoff on, so the bonus is in from the start.
- **Down entering X comeback** = the opponent's FINAL score minus own points
  going in, when that is above 0 and the team won (whatever the margin then:
  it is judged against the final, so the opponent's own late players count).
  N/A otherwise. Two % versions: of own points going in, and of the
  opponent's final; and a per-player version: divided by the team's own
  starters still to play from that kickoff on.
"""
from __future__ import annotations

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
COMEBACK_COLUMNS = {
    s: (f"Down entering {s} comeback",
        f"Down entering {s} comeback (% of points going in)",
        f"Down entering {s} comeback (% of opponent's final)",
        f"Down entering {s} comeback (per player left)")
    for s in STAGES
}
TEAM_WEEK_COLUMNS: Tuple[str, ...] = tuple(
    [MARGIN_COLUMNS[s] for s in STAGES] + [c for s in STAGES for c in COMEBACK_COLUMNS[s]])
GAME_SLOT_COLUMN = "Game slot"

# Sleeper / ESPN spellings the nflverse schedule writes differently.
_TEAM_ALIASES = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV",
                 "SD": "LAC", "STL": "LA"}


# Games nflverse struck from the schedule whose points Sleeper kept: the 2022
# Bills-Bengals week 17 Monday night game, abandoned in the 1st quarter.
_STRUCK_GAMES = {(2022, 17): (datetime(2023, 1, 2, 20, 30), ("BUF", "CIN"))}


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
    g = games
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
    for (s, w), (k, teams) in _STRUCK_GAMES.items():
        for t in teams:
            kick.setdefault((s, w, t), k)
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


def points_from(starters: Iterable[Tuple[Optional[datetime], float]], t: datetime) -> float:
    """Points scored in games kicking off at or after t."""
    return sum(p for k, p in starters if k is not None and k >= t)


def comeback(own_in: float, opp_final: float, won: bool, players_left: int = 0):
    """(points overcome, % of points going in, % of opponent's final, per own
    player left), or None."""
    deficit = round(float(opp_final) - float(own_in), 2)
    if not won or deficit <= 0:
        return None
    pct_in = round(deficit / own_in * 100, 1) if own_in > 0 else None
    pct_opp = round(deficit / opp_final * 100, 1) if opp_final > 0 else None
    per_player = round(deficit / players_left, 2) if players_left > 0 else None
    return deficit, pct_in, pct_opp, per_player


def matchup_stage(own: Sequence[Tuple[Optional[datetime], float]],
                  opp: Sequence[Tuple[Optional[datetime], float]],
                  own_final: float, opp_final: float, won: bool,
                  t: Optional[datetime]) -> dict:
    """Margin entering t and the comeback from t, for one side of a matchup."""
    if t is None:
        return {"in": None, "opp_in": None, "margin": None, "left": None, "comeback": None}
    own_in = round(own_final - points_from(own, t), 2)
    opp_in = round(opp_final - points_from(opp, t), 2)
    left = sum(1 for k, _p in own if k is not None and k >= t)
    return {"in": own_in, "opp_in": opp_in, "margin": round(own_in - opp_in, 2), "left": left,
            "comeback": comeback(own_in, opp_final, won, left)}


def last_game_start(schedule: Schedule, season: int, week: int,
                    own: Sequence[Tuple[Optional[datetime], float]],
                    opp: Sequence[Tuple[Optional[datetime], float]]) -> Optional[datetime]:
    """Latest kickoff with a starter from either side, if SNF or later."""
    ks = [k for k, _p in list(own) + list(opp) if k is not None]
    thr = late_threshold(schedule.sunday.get((int(season), int(week))))
    if not ks or thr is None:
        return None
    last = max(ks)
    return last if last >= thr else None


def _won(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "1.0", "yes")


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def starter_kickoffs(player_week: pd.DataFrame, schedule: Schedule) -> Dict[Tuple[str, int, int], list]:
    """(Team, Year, Week) -> [(kickoff or None, points)] over the week's starters."""
    out: Dict[Tuple[str, int, int], list] = {}
    if player_week is None or player_week.empty:
        return out
    st = player_week[player_week["Starter/Bench"].astype(str).str.lower() == "starter"]
    for team, y, w, nfl, pts in st[["Team", "Year", "Week", "NFL team", "Points"]].itertuples(index=False):
        y_, w_ = _num(y), _num(w)
        if y_ is None or w_ is None:
            continue
        key = (str(team), int(y_), int(w_))
        out.setdefault(key, []).append((schedule.team_kickoff(y_, w_, nfl), _num(pts) or 0.0))
    return out


def stage_rows(team_week: pd.DataFrame, player_week: pd.DataFrame, schedule: Schedule,
               stage: str) -> pd.DataFrame:
    """Every team-week entering one stage: points going in on both sides, the
    margin, and the comeback (vs the opponent's final). `stage` is 'SNF',
    'Monday', 'last game' or any game slot name."""
    starts = starter_kickoffs(player_week, schedule)
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
        m = matchup_stage(own, opp, pf, pa, won, t)
        cb = m["comeback"]
        rows.append({
            "Team": rec["Team"], "Year": y, "Week": w, "Week Name": rec.get("Week Name"),
            "Opponent": rec["Opponent"], "Win?": won, "PF": pf, "Points against": pa,
            "Stage kickoff": t.strftime("%a %Y-%m-%d %H:%M") if t else None,
            "Points going in": m["in"], "Opponent going in": m["opp_in"],
            "Margin entering": m["margin"], "Players left": m["left"],
            "Points after": round(pf - m["in"], 2) if m["in"] is not None else None,
            "Opponent after": round(pa - m["opp_in"], 2) if m["opp_in"] is not None else None,
            "Comeback": cb[0] if cb else None,
            "Comeback (% of points going in)": cb[1] if cb else None,
            "Comeback (% of opponent's final)": cb[2] if cb else None,
            "Comeback (per player left)": cb[3] if cb else None,
        })
    return pd.DataFrame(rows)


def team_week_columns(team_week: pd.DataFrame, player_week: pd.DataFrame,
                      schedule: Schedule) -> pd.DataFrame:
    """Team, Year, Week + TEAM_WEEK_COLUMNS, N/A where the stage did not happen
    or there was no comeback."""
    base = None
    for stage in STAGES:
        r = stage_rows(team_week, player_week, schedule, stage)
        if r.empty:
            return pd.DataFrame(columns=["Team", "Year", "Week", *TEAM_WEEK_COLUMNS])
        pts, pct_in, pct_opp, per_pl = COMEBACK_COLUMNS[stage]
        part = pd.DataFrame({
            "Team": r["Team"], "Year": r["Year"], "Week": r["Week"],
            MARGIN_COLUMNS[stage]: r["Margin entering"],
            pts: r["Comeback"], pct_in: r["Comeback (% of points going in)"],
            pct_opp: r["Comeback (% of opponent's final)"],
            per_pl: r["Comeback (per player left)"],
        })
        base = part if base is None else base.merge(part, on=["Team", "Year", "Week"], how="outer")
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
