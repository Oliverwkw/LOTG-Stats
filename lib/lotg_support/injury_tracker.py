"""In-house weekly injury/suspension tracker (PR E fix B).

nflverse's weekly stats/injury feeds lag ~2-3 days, which makes a mid-season
build mis-flag players who actually played as injured. Sleeper, by contrast,
carries a LIVE `injury_status` per player — but only for *right now*, and it
changes every week as diagnoses update. So we snapshot it ourselves and append
to a committed CSV (data/injury_tracker.csv). The main build then reads that
history as the PRIMARY injury/suspension source, with nflverse as backup.

Each week is snapshotted more than once, because one read cannot answer both
halves of the question:
  * a GAMEDAY SWEEP (sweep_injuries.yml, daily 16:00 UTC, exiting in seconds
    unless the schedule says there is a game today) catches the designations
    the teams actually played under — a tag the team clears on the Monday, a
    21-day IR window opening, a suspension ending, is gone by Tuesday, and the
    week would read as a played 0.00 instead of a miss;
  * the FINAL CAPTURE (capture_injuries.yml, Tue 05:00 UTC) carries
    participation, which Sleeper's weekly stats only have once the games are
    over, and which is what stops a man hurt DURING a game from being recorded
    as having missed it.
They merge into one row per player-week — see merge_capture().

The tracker starts empty (first capture = 2026 week 1), so until it has rows for
a given (season, week) the build simply falls back to the existing nflverse /
Sleeper-meta logic — i.e. a no-op on all historical data.

WHAT COUNTS AS A MISSED WEEK (the two rules this module enforces)
----------------------------------------------------------------
1. ONLY a designation that GUARANTEES the player did not play flags a week — a
   game-day inactive (Out, Sus) or a reserve list he is ineligible to play from
   (IR, PUP, NFI, COV, DNR). Questionable and Doubtful are *game-time* labels
   that most often end with the player suiting up, so they flag nothing; nor
   does Practice Squad (elevatable), Sleeper's roster-level "Inactive", or the
   ambiguous "NA". The full vocabulary and the reasoning per value is at
   `_INJURY_TOKENS` below.
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

TWO THINGS THE OVERLAY IS NOT ALLOWED TO TOUCH
----------------------------------------------
* A season before TRACKER_FIRST_SEASON. The tracker is forward-only: 2025 and
  earlier were built by the nflverse/meta process and keep the flags it gave
  them, so no capture — however it got into the CSV — can reach back into a
  season that is already published. load_status_index() drops those rows.
* A week whose flags a human wrote down by hand, in data/suspensions.csv or
  data/injuries.csv. See the `curated` argument of apply_overlay().
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
    "captures", "captured_at_utc", "finalized_at_utc",
]

# A week is captured more than once — see merge_capture(). Which capture each
# merged column comes from:
#   injury_status / injury_body_part / status  the STRONGEST designation any
#       capture saw (suspension > injury > clear); ties keep the earliest, which
#       is the one nearest kickoff
#   captured_at_utc                            when THAT capture ran
#   full_name / position / nfl_team            the newest capture (a player
#       traded mid-week ends the week on his new team)
#   on_bye                                     the EARLIEST non-blank, i.e. the
#       capture nearest kick-off. Every other column takes the newest, and this
#       one must not: a bye belongs to the team the player was on when the games
#       were played, and an NFL trade landing between two captures of the same
#       week makes the newest capture name the wrong team. That is the one place
#       a wrong team becomes a wrong WEEK, because a bye is an outright override
#       (resolve_injury_flags returns it as a verdict, not as advice) and a bye
#       drops the week from the played-week denominators — so the week does not
#       read wrong, it silently disappears
#   played                                     true if ANY capture saw him play
#   captures                                   how many captures are folded in
#   finalized_at_utc                           when the post-week capture ran,
#       blank until it does
_DESIGNATION_COLUMNS = ("injury_status", "injury_body_part", "status")
_IDENTITY_COLUMNS = ("full_name", "position", "nfl_team")
_DESIGNATION_RANK = {None: 0, "injury": 1, "suspension": 2}

# Fixed NFL schedule (published pre-season, does NOT lag in-season). Used to
# derive each captured week's bye teams AND which week a capture belongs to —
# NOT the lagging weekly stats feed.
_SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"

# The schedule file carries the POSTSEASON too, as weeks 19-22 (WC/DIV/CON/SB).
# Only REG rows are kept, so a captured week is always a week the fantasy league
# actually plays. Without this the January cron — which fires on every Tuesday of
# the month — filed weeks 19, 20 and 21 every season (22, the Super Bowl, falls
# in February, when the cron does not fire), and `on_bye` for a playoff week
# marks all 20-28 teams whose season is over as being on a bye.
_REGULAR_SEASON_GAME_TYPE = "REG"

# The tracker's first capture. Rows before this are refused by
# load_status_index(), so the overlay can never reach a season that was built
# under the nflverse/meta process — history stays on the process that produced
# it, whatever ends up in the CSV.
TRACKER_FIRST_SEASON = 2026

# Sleeper pads a roster's `starters` list with the string "0" for an empty slot.
# It is not a player, and capturing it writes one nameless, teamless row per
# capture (9 such slots across the 2026 rosters).
_ROSTER_SENTINEL_PIDS = {"0"}

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

# Sleeper designations that GUARANTEE the player did not play. The full
# vocabulary Sleeper emits, counted over the committed 12,225-player snapshot
# (exports/snapshot/sleeper_players_nfl.json):
#
#   status:         Active · Inactive · Injured Reserve · Physically Unable to
#                   Perform · Practice Squad · Non Football Injury · "" (45
#                   players carry no status at all, including all 32 team DSTs)
#   injury_status:  Questionable · IR · NA · PUP · Sus · Out · DNR · COV · Doubtful
#
# FLAGGED — each one is a game-day inactive or a reserve list, and a player on a
# reserve list is ineligible to play, so absence is certain:
#   Out · IR (+IR-R, "Injured Reserve") · PUP ("Physically Unable to Perform")
#   NFI ("Non Football Injury") · COV (reserve/COVID) · DNR ("Did Not Report")
#   Sus (the suspension bucket)
#
# NOT FLAGGED, and why:
#   Questionable / Doubtful — game-time labels; the player usually suits up.
#   Practice Squad — can be elevated for the week and play.
#   Inactive — Sleeper's roster status (3,430 of 12,225 players: free agents, cut
#     and retired players), not a game-day inactive. It says nothing about a
#     given week, and the build's own team/bye logic already routes players with
#     no NFL team to Bye? — which is the audit fix that stopped retired
#     meme-pickups (Brady '24/'25, Brees '24) counting as injuries.
#   NA — genuinely ambiguous: 92 players carry it, 26 of them alongside status
#     "Active", so it cannot simply mean "not on a roster". It guarantees
#     nothing we can defend, so it decides nothing.
#
# Matched as whole tokens (plus the long-form `status` spellings as phrases) so
# "ir" can never match inside a word.
_INJURY_TOKENS = {"out", "ir", "pup", "nfi", "cov", "covid", "dnr"}
_INJURY_PHRASES = ("injured reserve", "physically unable", "non football injury",
                   "did not report", "reserve covid")
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

    Only a designation that guarantees the player did not play qualifies — see
    rule 1 in the module docstring and the per-value reasoning at
    `_INJURY_TOKENS`."""
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
                  bye: Any, curated: bool = False) -> Tuple[Any, Any, Any]:
    """Fold the tracker's verdict into the build's (injury, suspension, bye).

    The build calls exactly this, so the whole decision is testable end to end.
    A bye the build derived independently is never overwritten by an
    injury/suspension — only the tracker's own bye can set one.

    `curated` says the build's flags for this (player, season, week) came from a
    HAND-WRITTEN file — data/suspensions.csv or data/injuries.csv. Those exist
    precisely because no feed reports the fact: nflverse's game-status report
    does not list suspended players at all, and a player on season-ending IR
    drops off it entirely. Sleeper's dictionary is no better — it carries "Sus"
    for ten players league-wide at any moment, and only for as long as the
    suspension is current. So a curated week is left exactly as the human wrote
    it: the tracker may not clear it, and may not reclassify it. Only a bye
    outranks it, which is what the build already does everywhere else."""
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
    if curated:
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
                # Regular season only — see _REGULAR_SEASON_GAME_TYPE.
                if str(row.get("game_type") or "").strip().upper() != _REGULAR_SEASON_GAME_TYPE:
                    continue
                wk = int(row.get("week"))
            except Exception:
                continue
            info = weeks.setdefault(wk, {"teams": set(), "days": set(),
                                        "first": None, "last": None})
            for k in ("home_team", "away_team"):
                t = normalize_team(row.get(k))
                if t:
                    info["teams"].add(t)
            try:
                d = datetime.strptime(str(row.get("gameday") or "").strip(), "%Y-%m-%d").date()
            except Exception:
                d = None
            if d:
                info["days"].add(d)
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


# UTC -> "which NFL gameday is this". ET is UTC-4/-5, and a night game runs past
# midnight UTC, so shifting back 6 hours puts every kick-off and every whistle on
# the gameday it belongs to.
_GAMEDAY_SHIFT = timedelta(hours=6)


def gameday(now: Optional[datetime] = None) -> date:
    """The NFL gameday `now` falls on (see _GAMEDAY_SHIFT)."""
    return ((now or datetime.now(timezone.utc)) - _GAMEDAY_SHIFT).date()


def gameday_week(season: int, now: Optional[datetime] = None,
                 timeout: int = 30) -> Optional[int]:
    """The week that has a game TODAY, or None on a day with no NFL game.

    This is what a gameday sweep files under, and what tells it whether to run at
    all. It reads the real schedule rather than the calendar because NFL gamedays
    are not a fixed weekday set: across 2024-2026 they land on Wednesday,
    Thursday, Friday, Saturday, Sunday and Monday — 2026 opens on a WEDNESDAY —
    and a game has been moved to a Tuesday before (2021 week 15). A weekday cron
    would have to be edited for each of those; this does not."""
    day = gameday(now)
    for wk, info in sorted(_fetch_schedule(season, timeout).items()):
        if day in (info.get("days") or set()):
            return wk
    return None


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
    ref = gameday(now)
    started = [wk for wk, info in sched.items()
               if info.get("first") and info["first"] <= ref]
    return max(started) if started else None


def state_week_drift(state_week: Optional[int], sched_week: Optional[int]) -> str:
    """'unknown' | 'agree' | 'rolled' | 'drift' for Sleeper's week vs the schedule's.

    Sleeper's /state/nfl points at the week to be PLAYED NEXT and rolls some time
    after the Monday night game, so by the Tuesday 05:00 UTC capture it has
    usually already advanced: state == schedule + 1 is the ORDINARY state of the
    world ('rolled'), not a fault. Warning on it every week would train us to
    ignore the one week it means something. Anything else — the state lagging
    behind, or running two or more weeks ahead — is a real disagreement
    ('drift')."""
    if state_week is None or sched_week is None:
        return "unknown"
    delta = int(state_week) - int(sched_week)
    if delta == 0:
        return "agree"
    if delta == 1:
        return "rolled"
    return "drift"


def season_from_date(day: Optional[date] = None) -> int:
    """NFL season a date belongs to (Jan/Feb belong to the previous season)."""
    d = day or datetime.now(timezone.utc).date()
    return d.year - 1 if d.month <= 2 else d.year


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
def _rostered_pids(sc) -> set:
    """Every player on any roster slot this week (active + taxi + IR/reserve).

    Sleeper's empty-slot sentinel ("0") is dropped — see _ROSTER_SENTINEL_PIDS."""
    pids: set = set()
    for r in (sc.rosters() or []):
        for key in ("players", "starters", "taxi", "reserve"):
            for p in (r.get(key) or []):
                if p and str(p) not in _ROSTER_SENTINEL_PIDS:
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
            "captures": 1,
            "captured_at_utc": now,
            "finalized_at_utc": "",
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


class TrackerUnreadable(RuntimeError):
    """The committed CSV exists, holds data, and none of it could be recovered.

    Raised INSTEAD of writing, because the alternative is worse: every writer
    rewrites the whole file, so treating an unreadable file as "no rows" would
    silently replace the season's history with the one week being captured. One
    lost week is a gap the coverage report shouts about; a truncated tracker is
    not recoverable at all."""


def _read_existing(path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Rows already in the tracker, salvaging what a damaged file allows.

    The readers (load_status_index and friends) degrade to empty on a corrupt
    file, which is right for them — a build with no overlay is a build. The
    WRITERS cannot do that, and they also cannot simply propagate the error: a
    csv.Error out of here kills the weekly capture, and Sleeper keeps no injury
    history, so that week is gone for good. So a damaged file costs us its
    damaged lines and nothing else, loudly."""
    if not path.exists() or not path.is_file():
        return [], None
    try:
        with path.open(newline="") as f:
            return list(csv.DictReader(f)), None
    except Exception:
        pass
    raw = b""
    try:
        raw = path.read_bytes()
    except Exception as e:
        raise TrackerUnreadable(f"{path} could not be read at all: {e}")
    # NUL bytes (a truncated or interrupted write) are what csv refuses outright.
    text = raw.decode("utf-8", errors="replace").replace("\x00", "")
    rows: List[Dict[str, Any]] = []
    dropped = 0
    try:
        import io as _io
        reader = csv.DictReader(_io.StringIO(text))
        while True:
            try:
                rows.append(next(reader))
            except StopIteration:
                break
            except Exception:
                dropped += 1
                if dropped > 100000:
                    break
    except Exception:
        pass
    if not rows and raw.strip():
        raise TrackerUnreadable(
            f"{path} holds {len(raw)} bytes and no row survived parsing. Refusing to "
            f"write, because writing would replace the whole tracker with this one "
            f"capture. Fix or restore the file (git checkout) and re-run.")
    return rows, (f"::warning::{path} was damaged: recovered {len(rows)} row(s), "
                  f"dropped {dropped}. The capture below is merged into what was "
                  f"recovered." if (dropped or rows) else None)


def _write_rows(path: Path, allrows: List[Dict[str, Any]]) -> Path:
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


def merge_into_csv(repo_root: Path, rows: List[Dict[str, Any]]) -> Path:
    """REPLACE any prior rows for the same (season, week) with `rows`.

    The deliberate overwrite behind `--force`. Routine captures go through
    merge_capture(), which accumulates."""
    path = tracker_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing, note = _read_existing(path)
    if note:
        print(note)
    new_keys = {(str(r["season"]), str(r["week"])) for r in rows}
    kept = [r for r in existing
            if (str(r.get("season")), str(r.get("week"))) not in new_keys]
    return _write_rows(path, kept + list(rows))


def _row_rank(row: Dict[str, Any]) -> int:
    combined = (str(row.get("injury_status") or "") + " "
                + str(row.get("status") or "")).strip().lower()
    return _DESIGNATION_RANK[designation(combined)]


def _merge_row(old: Dict[str, Any], new: Dict[str, Any], final: bool) -> Dict[str, Any]:
    """Fold one capture of a player-week into what earlier captures already said.

    See the column table at _DESIGNATION_COLUMNS. The rule that matters is the
    designation: the STRONGEST any capture saw wins, because a designation that
    was on him at kick-off answers the sheet's question — did something keep him
    off the field this week — even if the team had cleared it by Tuesday. That
    cannot invent an injury, because `played` is what clears a flag and it only
    ever accumulates True: a man who took the field is still not flagged, however
    the week ended for him."""
    out = dict(old)
    for c in _IDENTITY_COLUMNS:
        if new.get(c) not in (None, ""):
            out[c] = new[c]
    # on_bye keeps the EARLIEST non-blank — see the column table above. A player
    # traded on the Monday from a team that played to one that was idle is not
    # retrospectively on a bye.
    if str(old.get("on_bye") or "").strip() == "":
        out["on_bye"] = new.get("on_bye", "")
    if str(new.get("played") or "").strip().lower() in ("true", "1", "yes"):
        out["played"] = "true"
    # Strictly stronger wins; a tie keeps the earlier capture, which is the one
    # nearest kick-off.
    if _row_rank(new) > _row_rank(old):
        for c in _DESIGNATION_COLUMNS:
            out[c] = new.get(c, "")
        out["captured_at_utc"] = new.get("captured_at_utc", "")
    try:
        out["captures"] = int(old.get("captures") or 1) + 1
    except (TypeError, ValueError):
        out["captures"] = 2
    if final:
        out["finalized_at_utc"] = new.get("captured_at_utc", "")
    return out


def merge_capture(repo_root: Path, rows: List[Dict[str, Any]],
                  final: bool = True) -> Path:
    """Fold one capture of a (season, week) into the tracker, PER PLAYER.

    A week is captured several times — a sweep on each of its gamedays, then the
    post-week capture that settles participation — so this accumulates rather
    than replacing. Replacing would be actively destructive in both directions: a
    gameday sweep runs before the games and would wipe the `played` evidence the
    final capture is for, and the final capture runs after the team has had two
    days to clear a designation and would wipe what the sweep saw at kick-off.

    Use merge_into_csv() for the deliberate `--force` overwrite of a whole block.
    Players any capture saw are kept, so a mid-week waiver add or drop does not
    lose the other captures' rows."""
    path = tracker_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing, note = _read_existing(path)
    if note:
        print(note)
    blocks = {(str(r["season"]), str(r["week"])) for r in rows}
    kept = [r for r in existing
            if (str(r.get("season")), str(r.get("week"))) not in blocks]
    prior = {(str(r.get("season")), str(r.get("week")), str(r.get("player_id"))): r
             for r in existing
             if (str(r.get("season")), str(r.get("week"))) in blocks}
    merged: List[Dict[str, Any]] = []
    for r in rows:
        key = (str(r["season"]), str(r["week"]), str(r["player_id"]))
        old = prior.pop(key, None)
        if old is None:
            row = dict(r)
            row["finalized_at_utc"] = r.get("captured_at_utc", "") if final else ""
            merged.append(row)
        else:
            merged.append(_merge_row(old, r, final))
    # Players an earlier capture of this week saw and this one did not (dropped
    # mid-week). Their designation stands; only the capture count is untouched.
    merged.extend(prior.values())
    return _write_rows(path, kept + merged)


def sweep_counts(repo_root: Path, season: int, week: int) -> List[int]:
    """Per-player capture counts for one (season, week).

    max() == 1 means the week has only its final capture behind it: nobody swept
    a gameday, so its designations are whatever Sleeper happened to be showing on
    Tuesday, two days after the games."""
    path = tracker_path(repo_root)
    out: List[int] = []
    if not path.exists():
        return out
    try:
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    if int(r.get("season")) == int(season) and int(r.get("week")) == int(week):
                        out.append(int(r.get("captures") or 1))
                except Exception:
                    continue
    except Exception:
        return out
    return out


def weeks_finalized(repo_root: Path, season: int) -> set:
    """Weeks of `season` whose POST-WEEK capture has run.

    Not the same as weeks_present(): a week with only gameday sweeps in it has
    rows but no participation picture, and still needs its final capture."""
    path = tracker_path(repo_root)
    out: set = set()
    if not path.exists():
        return out
    try:
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    if int(r.get("season")) != int(season):
                        continue
                    if str(r.get("finalized_at_utc") or "").strip():
                        out.add(int(r.get("week")))
                except Exception:
                    continue
    except Exception:
        return out
    return out


def load_status_index(repo_root: Path) -> Dict[Tuple[str, int, int], Dict[str, Any]]:
    """(player_id, season, week) -> {"status": <combined lowercased injury_status+
    status>, "bye": True/False/None, "played": True/None, "nfl_team": <abbr>} for
    the build's primary injury/suspension/bye overlay. Empty dict when the
    tracker is absent/empty.

    Rows for a season before TRACKER_FIRST_SEASON are dropped. The tracker is
    forward-only by design — 2025 and earlier were built by the nflverse/meta
    process and must keep the flags that process gave them — and this is what
    enforces it, rather than leaving it to depend on nobody ever running
    `capture_injuries.py --season 2024`."""
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
                if key[1] < TRACKER_FIRST_SEASON:
                    continue   # forward-only; see the docstring
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
