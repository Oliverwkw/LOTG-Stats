"""In-house weekly injury/suspension tracker (PR E fix B).

nflverse's weekly stats/injury feeds lag ~2-3 days, which makes a mid-season
build mis-flag players who actually played as injured. Sleeper, by contrast,
carries a LIVE `injury_status` per player — but only for *right now*, and it
changes every week as diagnoses update. So we snapshot it ourselves every week
(a scheduled Monday-night job, see .github/workflows/capture_injuries.yml) and
append to a committed CSV (data/injury_tracker.csv). The main build then reads
that history as the PRIMARY injury/suspension source, with nflverse as backup.

The tracker starts empty (first capture = 2026 week 1), so until it has rows for
a given (season, week) the build simply falls back to the existing nflverse /
Sleeper-meta logic — i.e. a no-op on all historical data.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TRACKER_COLUMNS = [
    "season", "week", "player_id", "full_name", "position", "nfl_team",
    "injury_status", "injury_body_part", "status", "on_bye", "captured_at_utc",
]

# Fixed NFL schedule (published pre-season, does NOT lag in-season). Used only
# to derive each captured week's bye teams — NOT the lagging weekly stats feed.
_SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"


# injury_status / status substrings that mean the player MISSED the week for
# injury reasons (suspension is handled separately via "sus"). A bye always wins.
_INJURY_TERMS = ("out", "ir", "inactive", "pup", "doubtful", "questionable",
                 "dnr", "cov", "reserve", " na")


def resolve_injury_flags(status: Optional[str], tracker_bye: Optional[bool],
                         points: float) -> Optional[Tuple[bool, bool, bool]]:
    """Single source of truth for the player_week tracker overlay.

    Given a tracker entry (`status` = combined lowercased injury_status+status;
    `tracker_bye` = captured on_bye) and the player's fantasy `points` that week,
    return the (injury, suspension, bye) override to apply, or None for "no
    override". A player can play hurt, so a miss is only asserted when points==0.
    Bye (from the fixed schedule) wins over injury/suspension; the third element
    is True only for the bye case. The caller applies injury/suspension only when
    the player isn't already on a (separately determined) bye."""
    pts = points or 0.0
    if pts != 0.0:
        return None
    if tracker_bye is True:
        return (False, False, True)
    s = (status or "")
    if "sus" in s:
        return (False, True, False)
    if any(t in s for t in _INJURY_TERMS):
        return (True, False, False)
    return None


def tracker_path(repo_root: Path) -> Path:
    return repo_root / "data" / "injury_tracker.csv"


def teams_playing(season: int, week: int, timeout: int = 30) -> set:
    """Set of NFL team abbreviations with a game in (season, week), from the
    fixed nflverse schedule. Empty set on any failure (bye left unknown)."""
    try:
        import io
        import requests
        r = requests.get(_SCHEDULE_URL, timeout=timeout)
        r.raise_for_status()
        teams: set = set()
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                if int(row.get("season")) == int(season) and int(row.get("week")) == int(week):
                    for k in ("home_team", "away_team"):
                        t = str(row.get(k) or "").strip().upper()
                        if t:
                            teams.add(t)
            except Exception:
                continue
        return teams
    except Exception:
        return set()


def _rostered_pids(sc) -> set:
    """Every player on any roster slot this week (active + taxi + IR/reserve)."""
    pids: set = set()
    for r in (sc.rosters() or []):
        for key in ("players", "starters", "taxi", "reserve"):
            for p in (r.get(key) or []):
                if p:
                    pids.add(str(p))
    return pids


def current_state(sc) -> Tuple[Optional[int], Optional[int]]:
    """(season, week) of the live NFL scoring period, from Sleeper's /state/nfl."""
    st = sc.get("/state/nfl") or {}
    try:
        season = int(st.get("season"))
    except Exception:
        season = None
    wk = st.get("week")
    if not wk:
        wk = st.get("leg")
    try:
        week = int(wk)
    except Exception:
        week = None
    return season, week


def capture_rows(sc, season: int, week: int) -> List[Dict[str, Any]]:
    """Snapshot Sleeper's current injury/status fields for every rostered player.

    Captures the player's CURRENT NFL team each week, so a player traded between
    NFL teams mid-season is logged on the right team (and gets that team's bye).
    on_bye is derived from the fixed schedule: the player's team has no game this
    week. Left blank (unknown) if the schedule fetch fails, so the build falls
    back to its own bye logic rather than asserting a wrong bye."""
    players = sc.players_nfl() or {}
    rostered = _rostered_pids(sc)
    playing = teams_playing(int(season), int(week))
    now = datetime.now(timezone.utc).isoformat()
    rows: List[Dict[str, Any]] = []
    for pid in sorted(rostered):
        m = players.get(pid) or players.get(str(pid)) or {}
        name = m.get("full_name") or " ".join(
            x for x in [m.get("first_name"), m.get("last_name")] if x
        )
        team = (m.get("team") or "").strip()
        if playing and team:
            on_bye = "true" if team.upper() not in playing else "false"
        else:
            on_bye = ""  # unknown (schedule unavailable, or no NFL team / FA)
        rows.append({
            "season": int(season),
            "week": int(week),
            "player_id": str(pid),
            "full_name": name or "",
            "position": m.get("position") or "",
            "nfl_team": team,
            "injury_status": m.get("injury_status") or "",
            "injury_body_part": m.get("injury_body_part") or "",
            "status": m.get("status") or "",
            "on_bye": on_bye,
            "captured_at_utc": now,
        })
    return rows


def merge_into_csv(repo_root: Path, rows: List[Dict[str, Any]]) -> Path:
    """Append `rows` to the tracker CSV, replacing any prior rows for the same
    (season, week) so a re-run overwrites rather than duplicates."""
    path = tracker_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: List[Dict[str, Any]] = []
    if path.exists():
        with path.open(newline="") as f:
            existing = list(csv.DictReader(f))
    new_keys = {(str(r["season"]), str(r["week"])) for r in rows}
    kept = [r for r in existing
            if (str(r.get("season")), str(r.get("week"))) not in new_keys]
    allrows = kept + rows

    def _sk(r):
        try:
            return (int(r["season"]), int(r["week"]), str(r["player_id"]))
        except Exception:
            return (0, 0, str(r.get("player_id", "")))
    allrows.sort(key=_sk)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRACKER_COLUMNS)
        w.writeheader()
        for r in allrows:
            w.writerow({k: r.get(k, "") for k in TRACKER_COLUMNS})
    return path


def load_status_index(repo_root: Path) -> Dict[Tuple[str, int, int], Dict[str, Any]]:
    """(player_id, season, week) -> {"status": <combined lowercased injury_status+
    status>, "bye": True/False/None, "nfl_team": <abbr>} for the build's primary
    injury/suspension/bye overlay. Empty dict when the tracker is absent/empty."""
    path = tracker_path(repo_root)
    idx: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    if not path.exists():
        return idx
    try:
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    key = (str(r["player_id"]), int(r["season"]), int(r["week"]))
                except Exception:
                    continue
                status = (str(r.get("injury_status") or "") + " "
                          + str(r.get("status") or "")).strip().lower()
                _b = str(r.get("on_bye") or "").strip().lower()
                bye = True if _b in ("true", "1", "yes") else (False if _b in ("false", "0", "no") else None)
                idx[key] = {"status": status, "bye": bye, "nfl_team": (r.get("nfl_team") or "").strip()}
    except Exception:
        return idx
    return idx
