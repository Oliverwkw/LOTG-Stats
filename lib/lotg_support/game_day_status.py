"""Hand-researched game-day status for 2020-2025 weeks with no snap on record.

WHY THIS EXISTS. The build flags `Injury?` on a rostered player who scored 0,
was not on a bye and did not appear. Once snap counts were unioned into the
appearance set (PR #426), what was left in 2020-2025 still carried 173 weeks of
players on an ACTIVE roster with 0 snaps — and a player can be on the 48-man
game-day roster and never take the field. Backup quarterbacks are most of it
(Riley Leonard 2025, Russell Wilson 2025 wks 5-9, Jake Browning 2024 wks 1-7,
Desmond Ridder 2022), plus healthy depth backs and receivers who dressed and sat.
Those are not injuries.

No feed separates them. nflverse's snap counts only list players who took a
snap; its weekly-roster `ACT` covers the game-day inactives too; and Sleeper's
`gms_active` is right for active-roster players but not for anyone on a reserve
list (Jeff Wilson 2021, on PUP, reads as active). So each week was looked up by
hand in the team's own inactive list or a game report, and the answer is
recorded here with its source. The tracker (data/injury_tracker.csv) captures
this live from 2026, so the file is closed: it may not hold a season at or after
`TRACKER_FIRST_SEASON`.

One status clears a flag. Everything else documents a flag that stays:

  active             dressed, never took a snap   -> NOT injured
  inactive           on the game-day inactive list -> injured (Out)
  emergency_qb3      the emergency third QB is on the inactive list -> Out
  reserve            IR / PUP / NFI / COVID list   -> injured
  ruled_out_pregame  dressed, hurt in warmups, ruled out before kickoff
                     (Rome Odunze 2025 wk15)       -> injured

Only `active` rows are read by the build; the rest are there so the next
reviewer can see the week was checked and why it kept its flag.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Set

from .injury_tracker import TRACKER_FIRST_SEASON, looks_like_gsis

GAME_DAY_STATUS_COLUMNS = [
    "player_name", "gsis_id", "season", "week", "nfl_team", "status", "detail", "source",
]

# status -> did he dress (be on the game-day roster and eligible to play)?
GAME_DAY_STATUSES = {
    "active": True,
    "inactive": False,
    "emergency_qb3": False,
    "reserve": False,
    "ruled_out_pregame": False,
}


def read_rows(path: Path) -> List[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def validate(rows: List[dict]) -> List[str]:
    """Every problem with the file, as readable strings. Empty means clean."""
    problems: List[str] = []
    seen: Set[tuple] = set()
    for i, r in enumerate(rows, start=2):          # line 1 is the header
        where = f"line {i} ({r.get('player_name')!r})"
        missing = [c for c in GAME_DAY_STATUS_COLUMNS if c not in r]
        if missing:
            problems.append(f"{where}: missing columns {missing}")
            continue
        try:
            season, week = int(r["season"]), int(r["week"])
        except (TypeError, ValueError):
            problems.append(f"{where}: season/week not integers")
            continue
        if season >= TRACKER_FIRST_SEASON:
            problems.append(f"{where}: season {season} belongs to the tracker, not this file")
        if not 1 <= week <= 18:
            problems.append(f"{where}: week {week} is not a regular-season week")
        if not looks_like_gsis(str(r["gsis_id"]).strip()):
            problems.append(f"{where}: gsis_id {r['gsis_id']!r} is not a gsis id")
        if r["status"] not in GAME_DAY_STATUSES:
            problems.append(f"{where}: unknown status {r['status']!r}")
        if not str(r["source"]).startswith("http"):
            problems.append(f"{where}: no source URL")
        if not str(r["detail"]).strip():
            problems.append(f"{where}: no detail")
        key = (str(r["gsis_id"]).strip(), season, week)
        if key in seen:
            problems.append(f"{where}: duplicate {key}")
        seen.add(key)
    return problems


def dressed_by_week(path: Path, season: int) -> Dict[int, Set[str]]:
    """{week: {gsis_id}} of players recorded as ACTIVE for `season`.

    Empty for a season the tracker owns, so a stray row can never reach into a
    live season, and for a missing file."""
    if int(season) >= TRACKER_FIRST_SEASON:
        return {}
    out: Dict[int, Set[str]] = {}
    for r in read_rows(path):
        try:
            if int(r["season"]) != int(season) or r["status"] != "active":
                continue
            gsis = str(r["gsis_id"]).strip()
            if looks_like_gsis(gsis):
                out.setdefault(int(r["week"]), set()).add(gsis)
        except (KeyError, TypeError, ValueError):
            continue
    return out
