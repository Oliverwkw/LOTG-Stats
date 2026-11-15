"""ESPN's injury feed: every NFL team's current injury list with an estimated
return date, captured daily by a GitHub workflow (no Claude, no API key).

WHY (2026-11-15): Sleeper's player dictionary says *that* a player is hurt
(Out / IR / Questionable) but never for how long, so the forecast had to treat
Achane's torn ACL like a sprained ankle until someone wrote a row into
plan/notes/forecast_status_2026.csv by hand. ESPN's public core API carries,
for every player on a team's injury list, `details.returnDate` (an estimated
return date, from the reporting ESPN syndicates) plus the reporting itself.

WHAT THE DATES MEAN, checked against the reporting on 2026-11-15 (73 rostered
injured or tagged players, every one found and matched by id):
  * 2027-02-15 (after the Super Bowl) is ESPN's "not this season" date. It is
    used both for confirmed season-ending injuries (Achane ACL, McLaurin
    patellar tendon, Hurts blood clots, Noel "will miss the remainder of the
    season") AND for "no timeline" (Jayden Reed: "without a clear timeline for
    a return"). So the date alone never ends a season here: `season_ending`
    also needs the reporting to say so (SEASON_WORDS) or a tear that always
    does (SEASON_INJURIES: ACL, Achilles, patellar tendon). Reed stays on the
    IR curve.
  * Any other date is an estimate of the EARLIEST return: Lamar Jackson's
    "6-to-10 weeks" was dated at six; IR players are usually dated at their
    first eligible game; a ruled-out player at his team's next game. So the
    forecast uses a date only to hold the player out of the weeks BEFORE it,
    and from that week he returns on the league's own fitted curve (first-week
    hazard), never more likely than that.

NOT YET VALIDATED: ESPN keeps only each player's latest entry and there is no
reachable archive, so no past season can be replayed against these dates.
`log_path()` gets one row each time a player's status or date changes, so the
dates can be scored against data/injury_tracker.csv after the season
(`calibration()`).

Mapping ESPN -> Sleeper is by id: nflverse's weekly rosters (espn_id and
sleeper_id on one row), then Sleeper's own espn_id, then DynastyProcess's id
table; only a player none of them knows is matched by normalized name, team
and position (and logged as such).

The build never imports this module (tests/test_espn_injuries.py checks); the
forecast reads the committed CSV.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import functools
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
SEASON_SENTINEL_MONTH = 2          # a return date in February or later = not this season
FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K")
STATUSES = ("Injured Reserve", "Out", "Doubtful", "Questionable", "Suspension",
            "Physically Unable to Perform", "Day-To-Day")

SEASON_WORDS = re.compile(
    r"season-ending|year-ending|"
    r"(rest|remainder|balance|entirety) of (the|his) (\d{4} )?(regular )?(season|year|campaign)|"
    r"miss (all of |the )?(the )?(entire |rest of the )?(\d{4} )?(season|campaign)|"
    r"(entire|whole) (\d{4} )?(regular )?(season|rookie season|campaign)|"
    r"out for the (\d{4} )?(season|year)|"
    r"(his|the|\d{4}) (season|campaign) (is|was) (officially )?over|ending his (\d{4} )?season|"
    r"never play football again|retire",
    re.I)
SEASON_INJURIES = re.compile(r"\bACL\b|achilles|patellar", re.I)

CURRENT_COLUMNS = ["season", "sleeper_id", "espn_id", "player", "position", "nfl_team", "status",
                   "fantasy_status", "return_date", "return_week", "season_ending", "evidence",
                   "injury", "updated", "matched_by", "captured_at_utc"]
LOG_COLUMNS = ["season", "sleeper_id", "espn_id", "player", "position", "status", "return_date",
               "return_week", "season_ending", "evidence", "injury", "updated", "first_seen_utc"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def current_path(root: Optional[Path] = None) -> Path:
    return Path(root or repo_root()) / "data" / "espn_injuries.csv"


def log_path(root: Optional[Path] = None) -> Path:
    return Path(root or repo_root()) / "data" / "espn_injury_log.csv"


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------
def _date(s) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def after_season(return_date: Optional[date], season: int) -> bool:
    """ESPN's 'not this season' date: on or after 1 Feb of the next year."""
    return return_date is not None and return_date >= date(int(season) + 1, SEASON_SENTINEL_MONTH, 1)


def classify(item: dict, season: int) -> Tuple[bool, str]:
    """(season_ending, evidence) for one ESPN injury entry.

    Season-ending needs BOTH the after-season date and a reason: the reporting
    says so, or the injury is a tear that always ends a season. `evidence` is
    the matched phrase (a few words, never the article)."""
    det = item.get("details") or {}
    if str(item.get("status") or "") not in ("Injured Reserve", "Out", "Physically Unable to Perform",
                                             "Suspension"):
        return False, ""
    if not after_season(_date(det.get("returnDate")), season):
        return False, ""
    text = " ".join(str(item.get(k) or "") for k in ("shortComment", "longComment"))
    m = SEASON_WORDS.search(text)
    if m:
        return True, m.group(0).lower()
    injury = " ".join(str(det.get(k) or "") for k in ("type", "location", "detail"))
    m = SEASON_INJURIES.search(injury) or SEASON_INJURIES.search(text)
    if m:
        return True, m.group(0).lower() + " tear"
    return False, ""


def injury_label(item: dict) -> str:
    det = item.get("details") or {}
    parts = [str(det.get("type") or ""), str(det.get("detail") or "")]
    return " - ".join(p for p in parts if p and p != "Not Specified")


# ---------------------------------------------------------------------------
# NFL calendar
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _week_ends(season: int, root: str) -> Tuple[Tuple[int, date], ...]:
    """((week, last game day), ...) for the regular season, from nfldata's schedule."""
    path = Path(root) / ".cache" / "nfldata_games.csv"
    if not path.exists():
        return ()
    last: Dict[int, date] = {}
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            if r.get("season") != str(season) or r.get("game_type") != "REG":
                continue
            d, w = _date(r.get("gameday")), int(r["week"])
            if d and (w not in last or d > last[w]):
                last[w] = d
    return tuple(sorted(last.items()))


def week_of(d: Optional[date], season: int, root: Optional[Path] = None) -> Optional[int]:
    """The NFL week whose games a return date falls in (a Wednesday before a
    Thursday game counts for that week); the last week + 1 for a date after the
    regular season; None for ESPN's after-season date."""
    if d is None:
        return None
    ends = _week_ends(int(season), str(root or repo_root()))
    for w, end in ends:
        if d <= end:
            return w
    # after the regular season but before ESPN's "not this season" date (a
    # January estimate): one past the last week, so every fantasy week is out
    return ends[-1][0] + 1 if ends and not after_season(d, season) else None


# ---------------------------------------------------------------------------
# Id bridge ESPN -> Sleeper
# ---------------------------------------------------------------------------
def _norm(name: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(name).lower().replace("-", " "))
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return " ".join(s.split())


def espn_to_sleeper(season: int, root: Optional[Path] = None,
                    players: Optional[dict] = None) -> Dict[str, str]:
    """{espn_id: sleeper_id}: nflverse weekly rosters first, then Sleeper's own
    espn_id, then DynastyProcess. Later sources never overwrite earlier ones."""
    root = Path(root or repo_root())
    out: Dict[str, str] = {}

    def add(e, s):
        e, s = str(e or "").split(".")[0].strip(), str(s or "").split(".")[0].strip()
        if e and s and e != "nan" and s != "nan":
            out.setdefault(e, s)

    for yr in (season, season - 1):
        p = root / ".cache" / f"nflverse_weekly_rosters_{yr}.csv"
        if p.exists():
            with p.open(newline="") as f:
                rows = list(csv.DictReader(f))
            for r in sorted(rows, key=lambda r: -int(r.get("week") or 0)):
                add(r.get("espn_id"), r.get("sleeper_id"))
    if players is None:
        players = _sleeper_players(root)
    for pid, meta in players.items():
        add(meta.get("espn_id"), pid)
    p = root / "exports" / "snapshot" / "dynastyprocess_playerids.csv"
    if p.exists():
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                add(r.get("espn_id"), r.get("sleeper_id"))
    return out


def _sleeper_players(root: Path) -> dict:
    p = root / "exports" / "snapshot" / "sleeper_players_nfl.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------------------
# Fetch (network) and write
# ---------------------------------------------------------------------------
def _get(session, url: str, tries: int = 3):
    for a in range(tries):
        try:
            r = session.get(url.replace("http://", "https://"), timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:                                    # noqa: BLE001 — retried, then reported
            if a == tries - 1:
                raise
            time.sleep(1 + 2 * a)
    return None


def fetch(session=None, workers: int = 16) -> List[dict]:
    """Every team's injury entries (about 2000, ~5 s): one entry per player, the
    latest, with `_espn_id` and `_team_id` added."""
    if session is None:
        import requests
        session = requests.Session()
        session.headers["User-Agent"] = "lotg-stats injury capture"
    teams = _get(session, f"{BASE}/teams?limit=50")["items"]
    ids = [re.search(r"/teams/(\d+)", t["$ref"]).group(1) for t in teams]
    refs: List[Tuple[str, str]] = []
    with cf.ThreadPoolExecutor(workers) as ex:
        for tid, page in zip(ids, ex.map(lambda t: _get(session, f"{BASE}/teams/{t}/injuries?limit=300"), ids)):
            refs += [(tid, i["$ref"]) for i in (page or {}).get("items", [])]
    out: List[dict] = []
    with cf.ThreadPoolExecutor(workers) as ex:
        for (tid, ref), item in zip(refs, ex.map(lambda r: _get(session, r[1]), refs)):
            if item:
                item["_team_id"] = tid
                item["_espn_id"] = re.search(r"athletes/(\d+)", ref).group(1)
                out.append(item)
    if len(ids) < 32 or not out:
        raise RuntimeError(f"ESPN returned {len(ids)} teams and {len(out)} injury entries")
    return out


def _athlete(session, item: dict) -> dict:
    ref = (item.get("athlete") or {}).get("$ref")
    return (_get(session, ref) or {}) if ref else {}


def build_rows(items: Sequence[dict], season: int, captured_at: str,
               root: Optional[Path] = None, session=None) -> Tuple[List[dict], List[str]]:
    """(rows for data/espn_injuries.csv, problems). Rows: every listed (not
    Active) fantasy-position player, mapped to his Sleeper id."""
    root = Path(root or repo_root())
    players = _sleeper_players(root)
    bridge = espn_to_sleeper(season, root, players)
    by_name: Dict[Tuple[str, str], List[str]] = {}
    for pid, m in players.items():
        if m.get("position") in FANTASY_POSITIONS:
            by_name.setdefault((_norm(m.get("full_name") or ""), m.get("position")), []).append(pid)
    rows, problems = [], []
    for it in items:
        status = str(it.get("status") or "")
        if not status or status == "Active":
            continue
        eid = str(it["_espn_id"])
        pid, how = bridge.get(eid), "id"
        meta = players.get(pid, {}) if pid else {}
        if not pid:
            if session is None:
                continue
            a = _athlete(session, it)
            pos = ((a.get("position") or {}).get("abbreviation") or "")
            if pos not in FANTASY_POSITIONS:
                continue
            hits = by_name.get((_norm(a.get("fullName") or ""), pos), [])
            if len(hits) != 1:
                problems.append(f"ESPN {eid} {a.get('fullName')} ({pos}): {len(hits)} Sleeper matches")
                continue
            pid, how, meta = hits[0], "name", players[hits[0]]
        pos = meta.get("position") or ""
        if pos not in FANTASY_POSITIONS:
            continue
        det = it.get("details") or {}
        rd = _date(det.get("returnDate"))
        ending, evidence = classify(it, season)
        rows.append({
            "season": season, "sleeper_id": pid, "espn_id": eid,
            "player": meta.get("full_name") or "", "position": pos, "nfl_team": meta.get("team") or "",
            "status": status, "fantasy_status": ((det.get("fantasyStatus") or {}).get("description") or ""),
            "return_date": rd.isoformat() if rd else "",
            "return_week": "" if after_season(rd, season) else (week_of(rd, season, root) or ""),
            "season_ending": "true" if ending else "false", "evidence": evidence,
            "injury": injury_label(it), "updated": str(it.get("date") or "")[:16],
            "matched_by": how, "captured_at_utc": captured_at,
        })
    seen: Dict[str, int] = {}
    for r in rows:
        seen[r["sleeper_id"]] = seen.get(r["sleeper_id"], 0) + 1
    dup = [k for k, v in seen.items() if v > 1]
    if dup:
        problems.append(f"Sleeper ids listed twice (kept the newest): {dup}")
        best: Dict[str, dict] = {}
        for r in rows:
            if r["sleeper_id"] not in best or r["updated"] > best[r["sleeper_id"]]["updated"]:
                best[r["sleeper_id"]] = r
        rows = list(best.values())
    rows.sort(key=lambda r: (r["status"], r["player"]))
    return rows, problems


def _read(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write(rows: Sequence[dict], root: Optional[Path] = None) -> Tuple[int, int]:
    """Overwrite the current file; append to the log each player whose status,
    date or season-ending flag differs from his last logged row. Returns
    (rows written, log rows added)."""
    root = Path(root or repo_root())
    cur = current_path(root)
    cur.parent.mkdir(parents=True, exist_ok=True)
    with cur.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CURRENT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    log = log_path(root)
    last: Dict[Tuple[str, str], dict] = {}
    for r in _read(log):
        last[(r["season"], r["sleeper_id"])] = r
    key = ("status", "return_date", "season_ending")
    new = []
    for r in rows:
        prev = last.get((str(r["season"]), r["sleeper_id"]))
        if prev is None or any(str(prev[k]) != str(r[k]) for k in key):
            new.append({c: r.get(c, "") for c in LOG_COLUMNS if c != "first_seen_utc"}
                       | {"first_seen_utc": r["captured_at_utc"]})
    # a player who left every list since his last row: log that he is off it
    listed = {r["sleeper_id"] for r in rows}
    seasons = {str(r["season"]) for r in rows}
    stamp = rows[0]["captured_at_utc"] if rows else datetime.now(timezone.utc).isoformat()
    for (season, pid), prev in last.items():
        if season in seasons and pid not in listed and prev["status"] != "Active":
            new.append({c: prev.get(c, "") for c in LOG_COLUMNS}
                       | {"status": "Active", "return_date": "", "return_week": "",
                          "season_ending": "false", "evidence": "", "first_seen_utc": stamp})
    if new:
        exists = log.exists()
        with log.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            if not exists:
                w.writeheader()
            w.writerows(new)
    return len(rows), len(new)


# ---------------------------------------------------------------------------
# Read (what the forecast uses)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EspnStatus:
    player: str
    status: str
    return_date: Optional[date]
    return_week: Optional[int]
    season_ending: bool
    evidence: str
    injury: str
    updated: str
    captured_at: str

    def label(self) -> str:
        if self.season_ending:
            return f"ESPN: out for season ({self.evidence})"
        if self.return_week:
            return f"ESPN: est. back wk {self.return_week}"
        if self.return_date is not None:
            return "ESPN: no timeline (not season-ending)"
        return f"ESPN: {self.status}"


@functools.lru_cache(maxsize=None)
def _current_cached(season: int, root: str) -> Tuple[Tuple[str, EspnStatus], ...]:
    out = []
    for r in _read(current_path(Path(root))):
        if str(r.get("season")) != str(season):
            continue
        out.append((r["sleeper_id"], EspnStatus(
            player=r["player"], status=r["status"], return_date=_date(r["return_date"]),
            return_week=int(r["return_week"]) if str(r.get("return_week") or "").isdigit() else None,
            season_ending=str(r["season_ending"]).lower() == "true", evidence=r["evidence"],
            injury=r["injury"], updated=r["updated"], captured_at=r["captured_at_utc"])))
    return tuple(out)


def current(season: int, root: Optional[Path] = None) -> Dict[str, EspnStatus]:
    """{sleeper_id: EspnStatus} from the committed capture for `season`."""
    return dict(_current_cached(int(season), str(root or repo_root())))


def captured_at(season: int, root: Optional[Path] = None) -> Optional[datetime]:
    rows = current(season, root)
    if not rows:
        return None
    s = max(v.captured_at for v in rows.values())
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Calibration (after the season): ESPN's dates against who actually played
# ---------------------------------------------------------------------------
def calibration(season: int, root: Optional[Path] = None) -> List[dict]:
    """For every logged estimate (season-ending or dated) the first week the
    player then appeared in data/injury_tracker.csv as having played.

    Rows: player, sleeper_id, logged (UTC), status, return_week, season_ending,
    first_played_after. `first_played_after` is None if he never played again
    that season. Read with the tracker's own caveats (it covers rostered
    players only)."""
    root = Path(root or repo_root())
    played: Dict[str, List[int]] = {}
    for r in _read(root / "data" / "injury_tracker.csv"):
        if str(r.get("season")) == str(season) and str(r.get("played")).lower() == "true":
            played.setdefault(r["player_id"], []).append(int(r["week"]))
    out = []
    for r in _read(log_path(root)):
        if str(r.get("season")) != str(season) or r["status"] == "Active":
            continue
        seen = _date(r["first_seen_utc"])
        wk = week_of(seen, season, root) if seen else None
        later = sorted(w for w in played.get(r["sleeper_id"], []) if wk is None or w > wk)
        out.append({"player": r["player"], "sleeper_id": r["sleeper_id"], "logged": r["first_seen_utc"],
                    "status": r["status"], "return_week": r["return_week"],
                    "season_ending": r["season_ending"], "first_played_after": later[0] if later else None})
    return out


def capture(season: int, root: Optional[Path] = None, dry_run: bool = False) -> str:
    """Fetch, map, write. Returns a one-paragraph summary for the workflow log."""
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "lotg-stats injury capture"
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = fetch(session)
    rows, problems = build_rows(items, season, stamp, root, session=session)
    ending = sum(r["season_ending"] == "true" for r in rows)
    dated = sum(bool(r["return_week"]) for r in rows)
    lines = [f"{len(items)} ESPN entries -> {len(rows)} listed fantasy players "
             f"({ending} season-ending, {dated} with an in-season return week)"]
    lines += [f"  ! {p}" for p in problems]
    if not dry_run:
        n, added = write(rows, root)
        lines.append(f"wrote {n} rows; {added} change(s) logged")
    return "\n".join(lines)
