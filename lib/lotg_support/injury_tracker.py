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

WHAT COUNTS AS A MISSED WEEK (the two rules this module enforces)
----------------------------------------------------------------
1. ONLY Sleeper's Out / IR / PUP / Sus designations flag a week. Questionable
   and Doubtful are *game-time* labels that most often end with the player
   suiting up, so they no longer flag anything; neither do the residual
   COV / DNR / NA / Inactive markers.
2. A player who TOOK THE FIELD is never flagged, even at 0.00 points. The
   snapshot is taken after the week's games, so a player hurt DURING a game
   carries the injury label that the injury happened in — Xavier Worthy, 2025
   week 1: hurt on the opening drive, 1 target, 0 catches, 0.0 points, and
   "Out" for weeks 2-3 right after. Week 1 is a played week; weeks 2-3 are the
   injury. Points alone cannot tell those apart, so we carry a real
   participation signal: `played`, captured live from Sleeper's own weekly stats
   (games played / snap counts) at snapshot time, and cross-checked in the build
   against nflverse's played set once that lands.

Consequently a tracked week is decided ENTIRELY here: when Sleeper carries no
qualifying designation the overlay actively CLEARS the flags rather than leaving
the build's "rostered, scored 0, therefore injured" guess standing. That guess is
what used to stamp Injury? on healthy bench players.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TRACKER_COLUMNS = [
    "season", "week", "player_id", "full_name", "position", "nfl_team",
    "injury_status", "injury_body_part", "status", "on_bye", "played",
    "captured_at_utc",
]

# Fixed NFL schedule (published pre-season, does NOT lag in-season). Used to
# derive each captured week's bye teams AND which week a capture belongs to —
# NOT the lagging weekly stats feed.
_SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"

# nflverse and Sleeper do not spell every franchise the same way. The Rams are
# "LA" in nflverse's schedule and "LAR" on Sleeper, so a raw string compare put
# every Rams player on a bye every week of the season. Both sides of every team
# comparison in this module go through normalize_team().
_TEAM_ALIASES = {
    "LA": "LAR", "STL": "LAR", "RAM": "LAR",
    "SD": "LAC", "SDG": "LAC",
    "OAK": "LV", "LVR": "LV", "RAI": "LV",
    "WSH": "WAS", "WFT": "WAS",
    "ARZ": "ARI", "AZ": "ARI",
    "NWE": "NE", "KCC": "KC", "NOR": "NO", "SFO": "SF", "TAM": "TB",
    "GNB": "GB", "JAC": "JAX", "CLV": "CLE", "BLT": "BAL", "HST": "HOU",
}

# Sleeper designations that mean the player MISSED the week. Deliberately short:
# Out / IR / PUP for injury, Sus for suspension. Matched as whole tokens (plus
# the two long-form `status` spellings) so "ir" can never match inside a word.
_INJURY_TOKENS = {"out", "ir", "pup"}
_INJURY_PHRASES = ("injured reserve", "physically unable")
_SUSPENSION_TOKENS = {"sus", "susp", "suspended", "suspension"}

# Sleeper stat keys that only carry a value when the player was on the field.
# Team-level keys (tm_off_snp & friends) are deliberately excluded: they are
# populated for the whole roster, including players who never dressed.
_PLAYED_STAT_KEYS = ("gp", "off_snp", "def_snp", "st_snp")


def normalize_team(team: Any) -> str:
    """Canonical (Sleeper-style) NFL team abbreviation; '' when unknown."""
    s = str(team or "").strip().upper()
    return _TEAM_ALIASES.get(s, s)


def designation(status: Optional[str]) -> Optional[str]:
    """'suspension' | 'injury' | None for a combined injury_status+status string.

    ONLY Out / IR / PUP / Sus qualify — see rule 1 in the module docstring."""
    words = [w for w in re.split(r"[^a-z0-9]+", str(status or "").lower()) if w]
    if not words:
        return None
    joined = " ".join(words)
    toks = set(words)
    if toks & _SUSPENSION_TOKENS:
        return "suspension"
    if (toks & _INJURY_TOKENS) or any(p in joined for p in _INJURY_PHRASES):
        return "injury"
    return None


def resolve_injury_flags(status: Optional[str], tracker_bye: Optional[bool],
                         points: float,
                         played: Optional[bool] = None) -> Optional[Tuple[bool, bool, bool]]:
    """Single source of truth for the player_week tracker overlay.

    Given a tracker entry (`status` = combined lowercased injury_status+status;
    `tracker_bye` = captured on_bye; `played` = did the player take the field,
    None when neither Sleeper's weekly stats nor nflverse can say yet) and the
    player's fantasy `points` that week, return the (injury, suspension, bye)
    override to apply, or None for "no override".

    A player can play hurt, so a miss needs BOTH points == 0 AND no evidence
    that he played. Bye (from the fixed schedule) wins over injury/suspension;
    the third element is True only for the bye case. The caller applies
    injury/suspension only when the player isn't already on a (separately
    determined) bye.

    Returning all-False is meaningful, not a no-op: it says Sleeper looked at
    this player in this week and saw nothing that kept him off the field."""
    pts = points or 0.0
    if pts != 0.0:
        return None
    if played is True:
        # Took the field. Whatever label he carries now, he did not miss this
        # week — and he cannot have been on a bye. (Xavier Worthy 2025 wk 1.)
        return (False, False, False)
    if tracker_bye is True:
        return (False, False, True)
    d = designation(status)
    if d == "suspension":
        return (False, True, False)
    if d == "injury":
        return (True, False, False)
    return (False, False, False)


def apply_overlay(entry: Optional[Dict[str, Any]], points: float,
                  played: Optional[bool], injury: Any, suspension: Any,
                  bye: Any) -> Tuple[Any, Any, Any]:
    """Fold the tracker's verdict into the build's (injury, suspension, bye).

    The build calls exactly this, so the whole decision is testable end to end.
    A bye the build derived independently is never overwritten by an
    injury/suspension — only the tracker's own bye can set one."""
    if not entry:
        return (injury, suspension, bye)
    ov = resolve_injury_flags(entry.get("status"), entry.get("bye"), points, played)
    if ov is None:
        return (injury, suspension, bye)
    ov_injury, ov_susp, ov_bye = ov
    if ov_bye is True:
        return (False, False, True)
    if bye is True:
        return (injury, suspension, bye)
    return (ov_injury, ov_susp, bye)


def tracker_path(repo_root: Path) -> Path:
    return repo_root / "data" / "injury_tracker.csv"


# ---------------------------------------------------------------------------
# Fixed schedule: bye teams, and which week a capture belongs to
# ---------------------------------------------------------------------------
_SCHEDULE_CACHE: Dict[int, Dict[int, Dict[str, Any]]] = {}


def _fetch_schedule(season: int, timeout: int = 30) -> Dict[int, Dict[str, Any]]:
    """{week: {"teams": {ABBR}, "first": date, "last": date}} for `season`.

    Empty dict on any failure — and a failure is never cached, so the next call
    retries rather than serving an empty schedule for the rest of the run."""
    season = int(season)
    if season in _SCHEDULE_CACHE:
        return _SCHEDULE_CACHE[season]
    try:
        import io
        import requests
        r = requests.get(_SCHEDULE_URL, timeout=timeout)
        r.raise_for_status()
        weeks: Dict[int, Dict[str, Any]] = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                if int(row.get("season")) != season:
                    continue
                wk = int(row.get("week"))
            except Exception:
                continue
            info = weeks.setdefault(wk, {"teams": set(), "first": None, "last": None})
            for k in ("home_team", "away_team"):
                t = normalize_team(row.get(k))
                if t:
                    info["teams"].add(t)
            try:
                d = datetime.strptime(str(row.get("gameday") or "").strip(), "%Y-%m-%d").date()
            except Exception:
                d = None
            if d:
                info["first"] = d if info["first"] is None else min(info["first"], d)
                info["last"] = d if info["last"] is None else max(info["last"], d)
        if not weeks:
            return {}
        _SCHEDULE_CACHE[season] = weeks
        return weeks
    except Exception:
        return {}


def teams_playing(season: int, week: int, timeout: int = 30) -> set:
    """Set of NFL team abbreviations with a game in (season, week), from the
    fixed nflverse schedule, normalized to Sleeper's spelling. Empty set on any
    failure (bye left unknown)."""
    info = _fetch_schedule(season, timeout).get(int(week))
    return set(info["teams"]) if info else set()


def week_from_schedule(season: int, now: Optional[datetime] = None,
                       timeout: int = 30) -> Optional[int]:
    """The most recently STARTED week of `season` as of `now` (UTC).

    This — not Sleeper's /state/nfl — is what a capture is filed under. The
    schedule is fixed and published pre-season, so it cannot disagree with
    itself; /state/nfl rolls its `week` on Sleeper's own clock, which would
    silently file a capture one week off (and, run before kickoff, would file
    the PRESEASON injury picture as week 1). Returns None before the season's
    first game, or when the schedule can't be fetched.

    The 6-hour shift puts a Monday-night game that ends after 00:00 UTC back on
    its own gameday, so a Tuesday-small-hours capture still resolves to the week
    that just finished."""
    sched = _fetch_schedule(season, timeout)
    if not sched:
        return None
    ref = ((now or datetime.now(timezone.utc)) - timedelta(hours=6)).date()
    started = [wk for wk, info in sched.items()
               if info.get("first") and info["first"] <= ref]
    return max(started) if started else None


def season_from_date(day: Optional[date] = None) -> int:
    """NFL season a date belongs to (Jan/Feb belong to the previous season)."""
    d = day or datetime.now(timezone.utc).date()
    return d.year - 1 if d.month <= 2 else d.year


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
def _rostered_pids(sc) -> set:
    """Every player on any roster slot this week (active + taxi + IR/reserve)."""
    pids: set = set()
    for r in (sc.rosters() or []):
        for key in ("players", "starters", "taxi", "reserve"):
            for p in (r.get(key) or []):
                if p:
                    pids.add(str(p))
    return pids


def state_info(sc) -> Dict[str, Any]:
    """Sleeper's /state/nfl as {season, week, season_type}, each None if absent.

    Used only to CROSS-CHECK the schedule-derived week (and to refuse a capture
    outside the regular season when the schedule is unreachable)."""
    st = sc.get("/state/nfl") or {}
    try:
        season = int(st.get("season"))
    except Exception:
        season = None
    wk = st.get("week") or st.get("leg")
    try:
        week = int(wk)
    except Exception:
        week = None
    stype = str(st.get("season_type") or "").strip().lower() or None
    return {"season": season, "week": week, "season_type": stype}


def current_state(sc) -> Tuple[Optional[int], Optional[int]]:
    """(season, week) of the live NFL scoring period, from Sleeper's /state/nfl."""
    st = state_info(sc)
    return st["season"], st["week"]


def played_index(sc, season: int, week: int, season_type: str = "regular") -> Dict[str, bool]:
    """{player_id: True} for players Sleeper's weekly stats show taking the field.

    Sleeper's stats go live DURING games, so unlike nflverse this is available
    the moment the week ends — which is the whole point: it is what separates
    "hurt in the game he played" from "missed the game". Only POSITIVE evidence
    is recorded; a player absent from the payload is unknown, not benched, so a
    missing/failed feed can never manufacture an injury flag.

    Empty dict on any failure (older clients without the endpoint included)."""
    try:
        data = sc.get(f"/stats/nfl/{season_type}/{int(season)}/{int(week)}")
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, bool] = {}
    for pid, stats in data.items():
        if not isinstance(stats, dict):
            continue
        for key in _PLAYED_STAT_KEYS:
            try:
                if float(stats.get(key) or 0) > 0:
                    out[str(pid)] = True
                    break
            except Exception:
                continue
    return out


def capture_rows(sc, season: int, week: int,
                 played: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    """Snapshot Sleeper's current injury/status fields for every rostered player.

    Captures the player's CURRENT NFL team each week, so a player traded between
    NFL teams mid-season is logged on the right team (and gets that team's bye).
    on_bye is derived from the fixed schedule: the player's team has no game this
    week. Left blank (unknown) if the schedule fetch fails, so the build falls
    back to its own bye logic rather than asserting a wrong bye.

    `played` is Sleeper's live participation index for the week (see
    played_index); pass None to fetch it here. Written as "true" or blank —
    never "false", because Sleeper's stats confirm participation and never
    refute it."""
    players = sc.players_nfl() or {}
    rostered = _rostered_pids(sc)
    playing = teams_playing(int(season), int(week))
    if played is None:
        played = played_index(sc, int(season), int(week))
    now = datetime.now(timezone.utc).isoformat()
    rows: List[Dict[str, Any]] = []
    for pid in sorted(rostered):
        m = players.get(pid) or players.get(str(pid)) or {}
        name = m.get("full_name") or " ".join(
            x for x in [m.get("first_name"), m.get("last_name")] if x
        )
        team = (m.get("team") or "").strip()
        if playing and team:
            on_bye = "true" if normalize_team(team) not in playing else "false"
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
            "played": "true" if played.get(str(pid)) else "",
            "captured_at_utc": now,
        })
    return rows


def weeks_present(repo_root: Path, season: int) -> set:
    """Weeks of `season` that already have a captured block."""
    path = tracker_path(repo_root)
    if not path.exists():
        return set()
    out = set()
    try:
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    if int(r.get("season")) == int(season):
                        out.add(int(r.get("week")))
                except Exception:
                    continue
    except Exception:
        return out
    return out


def missing_weeks(repo_root: Path, season: int, through_week: int) -> List[int]:
    """Weeks 1..through_week of `season` with NO captured block.

    Sleeper keeps no injury history, so a week missed here can never be
    backfilled — the gap is permanent and worth shouting about."""
    have = weeks_present(repo_root, season)
    return [wk for wk in range(1, int(through_week) + 1) if wk not in have]


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
    status>, "bye": True/False/None, "played": True/None, "nfl_team": <abbr>} for
    the build's primary injury/suspension/bye overlay. Empty dict when the
    tracker is absent/empty."""
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
                _p = str(r.get("played") or "").strip().lower()
                idx[key] = {
                    "status": status,
                    "bye": bye,
                    # Only ever True or None — see played_index.
                    "played": True if _p in ("true", "1", "yes") else None,
                    "nfl_team": (r.get("nfl_team") or "").strip(),
                }
    except Exception:
        return idx
    return idx
