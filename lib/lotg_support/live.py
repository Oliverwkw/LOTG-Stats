"""The week being played right now, straight from Sleeper, shaped like the
exports so a "midweek" question runs through the same code as a historical one.

    from lotg_support import live
    lw = live.fetch()                  # current season/week from Sleeper's NFL state
    lw.player_week                     # one row per rostered player in a matchup
    lw.team_week                       # one row per team: PF so far, opponent, margin

`player_week` carries the export's own column names (`Player`, `Team`, `Year`,
`Week`, `Starter/Bench`, `Position`, `Position started in (if starter)`, `NFL
team`, `Game slot`, `Points`, `Win?`) plus `Kickoff` (ET) and `Game status`, so `lotg_support.fast` can stack it under
the committed `player_week` and rank the live week against every finished one.

What it is and is not:

- **Raw Sleeper points.** For a finished week these equal the export's
  `Points` row for row (`tests/test_live.py` checks 2026 week 5: 252/252), but
  team `PF` here is the sum of starters' points — no semifinal +5 (the build adds
  it; it matters only in a semifinal week).
- **`Win?` is "leading right now"**, not a result. A tie reads False.
- **`Game status` is a clock heuristic**, not a feed: `not started` before
  kickoff, `final?` from GAME_HOURS after kickoff, `in progress` between. Sleeper's
  matchup endpoint carries no game state. Say so when a number depends on it.
- **No late-listing correction.** `inquiry.week()` undoes moves Sleeper lists
  after the week's last game; a live week has not ended, so there is nothing
  to undo yet.

No network at all with `source="snapshot"` — the committed snapshot's copy of
the same week (what the tests use, and a fallback when Sleeper is unreachable;
it is as old as `exports/snapshot/_snapshot_meta.json` says).
"""
from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from lotg_support import inquiry as Q
from lotg_support.gametime import game_slot, load_schedule, norm_team

BASE = "https://api.sleeper.app/v1"
GAME_HOURS = 3.5          # a game is "final?" this long after kickoff
TIMEOUT = 10

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:          # pragma: no cover - tzdata missing
    _ET = None


def now_et() -> datetime:
    """Naive ET 'now' (the schedule's kickoffs are naive ET)."""
    utc = datetime.now(timezone.utc)
    if _ET is None:
        return (utc - timedelta(hours=4)).replace(tzinfo=None)
    return utc.astimezone(_ET).replace(tzinfo=None)


def _get(path: str) -> Any:
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": "LOTG-Stats-inquiry/1.0",
                                                           "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:     # honours HTTPS_PROXY
        return json.loads(r.read().decode("utf-8"))


def league_id() -> str:
    meta = json.loads((Q.snapshot_dir() / "_snapshot_meta.json").read_text())
    return str(meta["league_id"])


def nfl_state() -> Dict[str, Any]:
    """Sleeper's /state/nfl: {'season': '2026', 'week': 6, 'season_type': ...}."""
    return _get("/state/nfl")


@dataclass
class LiveWeek:
    season: int
    week: int
    source: str                    # "sleeper" or "snapshot"
    fetched_at_et: datetime
    player_week: pd.DataFrame
    team_week: pd.DataFrame

    def caveats(self) -> List[str]:
        out = [f"{self.season} week {self.week}, {self.source} as of {self.fetched_at_et:%a %Y-%m-%d %H:%M} ET; "
               "raw Sleeper points (no semifinal +5); 'Win?' = leading now"]
        st = self.player_week[self.player_week["Starter/Bench"] == "Starter"]
        counts = st["Game status"].value_counts()
        if len(st) and counts.get("final?", 0) < len(st):
            out.append("starters league-wide: " + ", ".join(f"{counts.get(k, 0)} {k}" for k in
                       ("not started", "in progress", "final?") if counts.get(k, 0))
                       + f" (status is a kickoff+{GAME_HOURS:g}h clock guess, not a feed)")
        if self.source == "snapshot":
            out.append("snapshot copy, not live — check _snapshot_meta.json captured_at")
        return out


def _schedule():
    games = Q.schedule()
    return load_schedule(games) if not games.empty else None


def _status(kick: Optional[datetime], now: datetime) -> str:
    if kick is None:
        return "no game"
    if now < kick:
        return "not started"
    if now >= kick + timedelta(hours=GAME_HOURS):
        return "final?"
    return "in progress"


def slot_labels(roster_positions: List[str]) -> List[str]:
    """The export's starter-slot labels (QB, RB1, RB2, WR1.., TE, FLX1, FLX2,
    SFLX) for Sleeper's `roster_positions`, in starter order — the build's own
    labelling (src/lotg.py, `starter_slot`)."""
    out, counts = [], {}
    for pos in roster_positions:
        up = str(pos or "").upper()
        if up in ("BN", "BE", "BENCH", "IR", "TAXI", ""):
            continue
        base = "SFLX" if up in ("SUPER_FLEX", "SUPERFLEX", "SFLEX", "SFLX") else "FLX" if up in ("FLEX", "FLX") else up
        counts[base] = counts.get(base, 0) + 1
        out.append(f"{base}{counts[base]}" if base in ("RB", "WR", "FLX") else base)
    return out


def _roster_positions(season: int) -> List[str]:
    try:
        return list(Q._snap(f"season_{int(season)}/league.json").get("roster_positions") or [])
    except (FileNotFoundError, OSError, ValueError):
        return []


def build(season: int, week: int, matchups: List[dict], rosters: List[dict], users: List[dict],
          now: Optional[datetime] = None, source: str = "sleeper",
          nfl_teams: Optional[Dict[tuple, str]] = None,
          roster_positions: Optional[List[str]] = None) -> LiveWeek:
    """Shape raw Sleeper rows into a LiveWeek (pure; `fetch` feeds it).

    A player's NFL team (hence his kickoff and slot) is his CURRENT team from
    the player dictionary — right for the live week. `nfl_teams` {(Team,
    Player): NFL team} overrides it, for replaying a past week.
    `roster_positions` (default: that season's snapshot league.json) labels
    each starter's slot; empty when neither is available."""
    now = now or now_et()
    labels = slot_labels(_roster_positions(season) if roster_positions is None else roster_positions)
    P = Q.players()
    names = {u["user_id"]: (u.get("display_name") or u.get("username") or u["user_id"]) for u in users}
    team_of = {r["roster_id"]: Q.canonical_team(names.get(r.get("owner_id"), f"Roster {r['roster_id']}"))
               for r in rosters}
    sched = _schedule()
    sunday = sched.sunday.get((season, week)) if sched else None
    by_mid: Dict[Any, List[int]] = {}
    for m in matchups:
        by_mid.setdefault(m.get("matchup_id"), []).append(m["roster_id"])
    opp = {}
    for mid, rids in by_mid.items():
        if mid is not None and len(rids) == 2:
            opp[rids[0]], opp[rids[1]] = rids[1], rids[0]
    pf = {m["roster_id"]: round(sum(float(x or 0) for x in (m.get("starters_points") or [])), 2)
          for m in matchups}

    prow = []
    for m in matchups:
        rid = m["roster_id"]
        starters = [str(p) for p in (m.get("starters") or [])]
        slot = {pid: lab for pid, lab in zip(starters, labels) if pid != "0"}
        pts = {str(k): float(v or 0) for k, v in (m.get("players_points") or {}).items()}
        lead = rid in opp and pf[rid] > pf[opp[rid]]
        for pid in [str(p) for p in (m.get("players") or [])]:
            if pid == "0":
                continue
            meta = P.meta(pid)
            nfl = (nfl_teams or {}).get((team_of[rid], meta.name)) or meta.nfl_team
            nfl = norm_team(nfl) if nfl else ""
            kick = sched.team_kickoff(season, week, nfl) if (sched and nfl) else None
            prow.append({
                "Player": meta.name, "Team": team_of[rid], "Year": season, "Week": week,
                "Starter/Bench": "Starter" if pid in starters else "Bench",
                "Position": meta.position, "Position started in (if starter)": slot.get(pid),
                "NFL team": nfl,
                "Game slot": game_slot(kick, sunday) if nfl else "N/A",
                "Kickoff": kick, "Game status": _status(kick, now),
                "Points": pts.get(pid, 0.0), "Win?": lead, "Player ID": pid,
            })
    trow = []
    for m in matchups:
        rid = m["roster_id"]
        o = opp.get(rid)
        trow.append({"Team": team_of[rid], "Year": season, "Week": week,
                     "Opponent": team_of.get(o) if o else None,
                     "PF": pf[rid], "Points against": pf.get(o) if o else None,
                     "Margin": round(pf[rid] - pf[o], 2) if o else None,
                     "Win?": bool(o and pf[rid] > pf[o])})
    pw = pd.DataFrame(prow)
    tw = pd.DataFrame(trow)
    if not pw.empty:
        left = pw[(pw["Starter/Bench"] == "Starter") & (pw["Game status"] == "not started")] \
            .groupby("Team").size()
        tw["Starters not started"] = tw["Team"].map(left).fillna(0).astype(int)
    return LiveWeek(season, week, source, now, pw, tw)


def fetch(season: Optional[int] = None, week: Optional[int] = None, source: str = "sleeper",
          now: Optional[datetime] = None) -> LiveWeek:
    """The live week (default: Sleeper's current season and week).

    `source="snapshot"` reads the committed snapshot's copy instead (no network)."""
    if source == "snapshot":
        if season is None or week is None:
            raise ValueError("snapshot source needs season and week")
        base = f"season_{int(season)}"
        m = Q._snap(f"{base}/weeks/week_{int(week):02d}/matchups.json")
        teams = None
        try:   # a finished week: the exports know each player's team THAT week
            pw = Q.load_sheet("player_week")
            pw = pw[(pw["Year"] == str(season)) & (pw["Week"] == str(week))]
            teams = dict(zip(zip(pw["Team"], pw["Player"]), pw["NFL team"]))
        except FileNotFoundError:
            pass
        return build(int(season), int(week), m, Q._snap(f"{base}/rosters.json"),
                     Q._snap(f"{base}/users.json"), now=now, source="snapshot", nfl_teams=teams)
    lid = league_id()
    with ThreadPoolExecutor(4) as ex:
        st = ex.submit(nfl_state) if (season is None or week is None) else None
        ro = ex.submit(_get, f"/league/{lid}/rosters")
        us = ex.submit(_get, f"/league/{lid}/users")
        if st is not None:
            state = st.result()
            season = int(state.get("league_season") or state["season"]) if season is None else season
            week = int(state.get("display_week") or state["week"]) if week is None else week
        mu = ex.submit(_get, f"/league/{lid}/matchups/{int(week)}")
        return build(int(season), int(week), mu.result(), ro.result(), us.result(), now=now)
