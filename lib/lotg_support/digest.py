"""Phase 14 — in-season weekly digest: rank-snapshot + diff + projection engine.

This is the *data core* of the Tuesday-morning digest email. It is deliberately
pure logic — no network, no SMTP, no recipient handling — so it is fully unit
testable offline against the committed CSVs. The delivery layer (recipients,
SMTP / provider) is intentionally deferred: the Phase 14 plan records
"Delivery / recipients: TBD (user will specify before phase starts)", so this
module stops at rendering the digest HTML. `scripts/build_digest.py` is the CLI
that wires it to the built `exports/` tree and the committed snapshot.

Three things the digest surfaces (from the Phase 14 spec):
  1. All-time top/bottom-5 rank changes for players (e.g. "Kyler Murray's
     -0.4 points passes JJ McCarthy for 4th-lowest all-time").
  2. All-time team rank changes (e.g. "BROsenzweig passes shmuel256 in Max PF
     for 3rd-highest all-time").
  3. On-pace end-of-season projections for the in-progress season (linear
     extrapolation of a team's cumulative pace, ranked against completed
     seasons).

The engine flow is: read the built CSVs -> `build_snapshot()` (ordered rankings
+ meta) -> persist as JSON -> next week `diff_snapshots(prev, curr)` yields a
list of narrative strings. Projections read the current-season `team_year` row
and scale by weeks completed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import json
import math

import pandas as pd


# ---------------------------------------------------------------------------
# Tracked stats
# ---------------------------------------------------------------------------
# Each tracked stat names an output column, whether "rank 1" is the highest or
# lowest value, and a human label used in the narrative. `windows` controls
# which ends of the leaderboard the digest watches: "high" watches the top of
# the ranking, "low" the bottom. The spec wants BOTH ends for players ("top and
# bottom 5"); teams headline the top.
#
# These lists are the single place to extend digest coverage — add a row and it
# flows through snapshot, diff, and the rendered email with no other change.

@dataclass(frozen=True)
class TrackedStat:
    column: str          # exact CSV column name
    label: str           # phrase used in narratives, e.g. "all-time points"
    higher_is_better: bool = True   # True: rank 1 = largest value
    windows: tuple = ("high", "low")  # which ends to watch: high / low


# Player all-time headline stats (player_all_time.csv). Watch both ends.
PLAYER_STATS: tuple = (
    TrackedStat("Points", "all-time points"),
    TrackedStat("Adjusted Avg points", "all-time adjusted PPG"),
    TrackedStat("Total points as starter", "all-time starter points"),
    TrackedStat("Starter PAR", "all-time PAR"),
    TrackedStat("Times as Player of the week?", "Player-of-the-week awards", windows=("high",)),
    TrackedStat("Number of trades", "career trades", windows=("high",)),
)

# Team all-time headline stats (team_all_time.csv). Watch the top.
TEAM_STATS: tuple = (
    TrackedStat("Points", "all-time points", windows=("high",)),
    TrackedStat("Max PF", "all-time Max PF", windows=("high",)),
    TrackedStat("All time win %", "all-time win %", windows=("high",)),
    TrackedStat("Championships", "championships", windows=("high",)),
    TrackedStat("Avg yearly luck", "average yearly luck", windows=("high", "low")),
    TrackedStat("Efficiency", "all-time efficiency", windows=("high",)),
)

# Team per-season cumulative stats that make sense to extrapolate linearly from
# the in-progress season's pace. Each is ranked against completed seasons.
PROJECTION_STATS: tuple = (
    TrackedStat("Points", "yearly points"),
    TrackedStat("Max PF", "yearly Max PF"),
    TrackedStat("Hardship", "yearly hardship"),
    TrackedStat("Starter-adjusted Hardship", "yearly starter-adjusted hardship"),
    TrackedStat("Number of transactions", "yearly transactions", windows=("high",)),
    TrackedStat("Losses from hardship", "yearly losses from hardship", windows=("high",)),
)

# Watch window size: top/bottom N of the leaderboard.
DEFAULT_WINDOW = 5

# Sentinels the build writes for "no value". Treated as missing for ranking.
_MISSING = {"N/A", "In Progress", "", "None", "nan"}


# ---------------------------------------------------------------------------
# Numeric coercion
# ---------------------------------------------------------------------------
def _to_float(value) -> Optional[float]:
    """Parse a cell to float, or None for sentinels / unparseable values."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s in _MISSING:
        return None
    # Some columns carry a comma-grouped or %-suffixed render; be forgiving.
    s = s.replace(",", "").rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th'."""
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _fmt(value: float) -> str:
    """Compact number render for narratives: ints as ints, else 1 decimal."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}"


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------
@dataclass
class RankedEntry:
    entity: str
    value: float


def rank_entities(df: pd.DataFrame, entity_col: str, stat: TrackedStat) -> List[RankedEntry]:
    """Ordered best -> worst list for one stat (rank = list index + 1).

    Rows with a missing/sentinel value are dropped. Ties keep a stable order by
    entity name so the ranking is deterministic across runs.
    """
    if stat.column not in df.columns or entity_col not in df.columns:
        return []
    rows: List[RankedEntry] = []
    for _, row in df.iterrows():
        v = _to_float(row[stat.column])
        if v is None:
            continue
        rows.append(RankedEntry(str(row[entity_col]), v))
    rows.sort(key=lambda r: (-r.value if stat.higher_is_better else r.value, r.entity))
    return rows


def _rankings_for(df: pd.DataFrame, entity_col: str, stats: Sequence[TrackedStat]) -> dict:
    out = {}
    for stat in stats:
        ranked = rank_entities(df, entity_col, stat)
        if ranked:
            out[stat.column] = [{"entity": r.entity, "value": r.value} for r in ranked]
    return out


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
def current_season(team_year: pd.DataFrame) -> Optional[int]:
    """The latest season present (the in-progress one during the NFL season)."""
    seasons = [int(y) for y in team_year["Year"].dropna().astype(int).unique()] \
        if "Year" in team_year.columns else []
    return max(seasons) if seasons else None


def weeks_completed(team_week: pd.DataFrame, season: int) -> int:
    """Number of distinct completed weeks for `season` in team_week.

    The build only writes a team_week row once a week is final (Phase 5E
    freshness gate), so this is a faithful "games played so far" count. 0 means
    the season is offseason / not yet started -> the digest skips (in-season
    only).
    """
    if team_week.empty or "Year" not in team_week.columns or "Week" not in team_week.columns:
        return 0
    sub = team_week[pd.to_numeric(team_week["Year"], errors="coerce") == season]
    weeks = pd.to_numeric(sub["Week"], errors="coerce").dropna().unique()
    return int(len(weeks))


def build_snapshot(
    player_all_time: pd.DataFrame,
    team_all_time: pd.DataFrame,
    team_year: pd.DataFrame,
    team_week: pd.DataFrame,
    captured_at: Optional[datetime] = None,
) -> dict:
    """Compute the full ranked snapshot + meta for the current build."""
    captured_at = captured_at or datetime.now(timezone.utc)
    season = current_season(team_year)
    weeks = weeks_completed(team_week, season) if season is not None else 0
    return {
        "meta": {
            "captured_at": captured_at.isoformat(),
            "season": season,
            "weeks_completed": weeks,
        },
        "players": _rankings_for(player_all_time, "Player", PLAYER_STATS),
        "teams": _rankings_for(team_all_time, "Team", TEAM_STATS),
    }


def is_in_season(snapshot: dict) -> bool:
    """True once at least one week of the current season is final."""
    return int(snapshot.get("meta", {}).get("weeks_completed", 0) or 0) >= 1


# ---------------------------------------------------------------------------
# Diff -> narratives
# ---------------------------------------------------------------------------
@dataclass
class Crossing:
    section: str        # "players" | "teams"
    stat_label: str
    window: str         # "high" | "low"
    rank: int           # slot the mover now occupies (1-indexed within window end)
    mover: str
    passed: str
    value: float

    def sentence(self) -> str:
        val = _fmt(self.value)
        if self.window == "high":
            return (f"{self.mover} ({val}) overtakes {self.passed} "
                    f"for {_ordinal(self.rank)}-highest {self.stat_label}.")
        return (f"{self.mover} ({val}) slips past {self.passed} "
                f"to {_ordinal(self.rank)}-lowest {self.stat_label}.")


def _rank_map(entries: Sequence[dict]) -> Dict[str, int]:
    return {e["entity"]: i + 1 for i, e in enumerate(entries)}


def _diff_one_stat(
    section: str,
    label: str,
    prev: Sequence[dict],
    curr: Sequence[dict],
    windows: Sequence[str],
    window: int,
) -> List[Crossing]:
    """Detect leaderboard crossings within the watched window(s) of one stat.

    A crossing is emitted when an entity present in BOTH snapshots improves its
    rank (moves toward rank 1 for the "high" end, or toward the bottom for the
    "low" end) and now sits inside the top/bottom `window`, having overtaken the
    entity it now sits directly ahead of. One sentence per mover per end.
    """
    out: List[Crossing] = []
    prev_rank = _rank_map(prev)
    n = len(curr)
    for end in windows:
        # Slot indices (0-based) that make up this window end.
        if end == "high":
            slots = range(0, min(window, n))
        else:  # "low"
            slots = range(max(0, n - window), n)
        for idx in slots:
            entry = curr[idx]
            mover = entry["entity"]
            if mover not in prev_rank:
                continue  # new entity — no prior rank to cross from
            new_rank = idx + 1
            old_rank = prev_rank[mover]
            improved = (new_rank < old_rank) if end == "high" else (new_rank > old_rank)
            if not improved:
                continue
            # Who did it pass? For the high end, the entity now directly behind
            # it (idx+1) that used to be ahead. For the low end, the entity now
            # directly ahead of it (idx-1) that used to be behind.
            neighbor_idx = idx + 1 if end == "high" else idx - 1
            if not (0 <= neighbor_idx < n):
                continue
            passed = curr[neighbor_idx]["entity"]
            # Only call it a "pass" if the ordering actually flipped vs before.
            passed_old = prev_rank.get(passed)
            if passed_old is None:
                continue
            flipped = (passed_old < old_rank) if end == "high" else (passed_old > old_rank)
            if not flipped:
                continue
            # Present the slot relative to the window end (low end counts up
            # from the bottom: last row = 1st-lowest).
            display_rank = new_rank if end == "high" else (n - idx)
            out.append(Crossing(section, label, end, display_rank, mover, passed, entry["value"]))
    return out


def diff_snapshots(prev: dict, curr: dict, window: int = DEFAULT_WINDOW) -> List[Crossing]:
    """All leaderboard crossings between two snapshots (players then teams)."""
    crossings: List[Crossing] = []
    for section, stats in (("players", PLAYER_STATS), ("teams", TEAM_STATS)):
        prev_sec = prev.get(section, {})
        curr_sec = curr.get(section, {})
        for stat in stats:
            p = prev_sec.get(stat.column)
            c = curr_sec.get(stat.column)
            if not p or not c:
                continue
            crossings.extend(
                _diff_one_stat(section, stat.label, p, c, stat.windows, window)
            )
    return crossings


# ---------------------------------------------------------------------------
# On-pace projections
# ---------------------------------------------------------------------------
@dataclass
class Projection:
    team: str
    stat_label: str
    projected: float
    rank: int           # projected rank among completed seasons + this projection
    total: int          # number of ranked seasons (completed + this one)
    higher_is_better: bool

    def sentence(self) -> str:
        end = "highest" if self.higher_is_better else "lowest"
        return (f"{self.team} is on pace for {_ordinal(self.rank)}-{end} "
                f"{self.stat_label} ({_fmt(self.projected)}).")


def _season_horizon(team_week: pd.DataFrame, current: int) -> Optional[int]:
    """Full-season week count to extrapolate to = max weeks in a completed prior
    season. None if there is no completed prior season to learn from."""
    if team_week.empty or "Year" not in team_week.columns or "Week" not in team_week.columns:
        return None
    years = pd.to_numeric(team_week["Year"], errors="coerce")
    weeks = pd.to_numeric(team_week["Week"], errors="coerce")
    prior_max = 0
    for y in sorted({int(v) for v in years.dropna().unique() if int(v) < current}):
        wk = weeks[years == y].dropna()
        if len(wk):
            prior_max = max(prior_max, int(wk.max()))
    return prior_max or None


def project_end_of_season(
    team_year: pd.DataFrame,
    team_week: pd.DataFrame,
    stats: Sequence[TrackedStat] = PROJECTION_STATS,
) -> List[Projection]:
    """Linear extrapolation of each team's in-progress cumulative pace to a full
    season, ranked against every completed season on record.

    Returns [] in the offseason (no completed weeks) or before there is any
    completed prior season to define the horizon / historical ranking pool.
    """
    season = current_season(team_year)
    if season is None:
        return []
    played = weeks_completed(team_week, season)
    horizon = _season_horizon(team_week, season)
    if played < 1 or not horizon or played >= horizon:
        return []
    scale = horizon / played
    curr_rows = team_year[pd.to_numeric(team_year["Year"], errors="coerce") == season]
    hist_rows = team_year[pd.to_numeric(team_year["Year"], errors="coerce") < season]

    projections: List[Projection] = []
    for stat in stats:
        if stat.column not in team_year.columns:
            continue
        # Historical completed-season values for this stat.
        hist_vals: List[float] = []
        for _, r in hist_rows.iterrows():
            v = _to_float(r[stat.column])
            if v is not None:
                hist_vals.append(v)
        if not hist_vals:
            continue
        for _, r in curr_rows.iterrows():
            cur = _to_float(r[stat.column])
            if cur is None:
                continue
            projected = cur * scale
            pool = sorted(hist_vals + [projected],
                          reverse=stat.higher_is_better)
            # Rank of this projection within the pool (stable: first match).
            rank = next(i + 1 for i, v in enumerate(pool)
                        if abs(v - projected) < 1e-9)
            projections.append(Projection(
                team=str(r["Team"]),
                stat_label=stat.label,
                projected=projected,
                rank=rank,
                total=len(pool),
                higher_is_better=stat.higher_is_better,
            ))
    return projections


# ---------------------------------------------------------------------------
# HTML render
# ---------------------------------------------------------------------------
def _section_html(title: str, lines: Sequence[str]) -> str:
    if not lines:
        return ""
    items = "\n".join(f"      <li>{ln}</li>" for ln in lines)
    return (
        f'  <h2 style="font:600 18px/1.3 system-ui,sans-serif;'
        f'margin:24px 0 8px;color:#1a2b3c;">{title}</h2>\n'
        f'    <ul style="margin:0;padding-left:20px;'
        f'font:15px/1.5 system-ui,sans-serif;color:#333;">\n{items}\n    </ul>\n'
    )


def render_digest_html(
    crossings: Sequence[Crossing],
    projections: Sequence[Projection],
    meta: dict,
) -> str:
    """Assemble the digest email body from crossings + projections."""
    player_lines = [c.sentence() for c in crossings if c.section == "players"]
    team_lines = [c.sentence() for c in crossings if c.section == "teams"]
    proj_lines = [p.sentence() for p in projections]

    season = meta.get("season")
    week = meta.get("weeks_completed")
    header = f"LOTG weekly digest — {season} season, through week {week}"

    body = [
        '<div style="max-width:640px;margin:0 auto;padding:16px;">',
        f'  <h1 style="font:700 22px/1.3 system-ui,sans-serif;'
        f'color:#0b2545;margin:0 0 4px;">{header}</h1>',
    ]
    body.append(_section_html("All-time leaderboard moves — players", player_lines))
    body.append(_section_html("All-time leaderboard moves — teams", team_lines))
    body.append(_section_html("On-pace projections", proj_lines))

    if not (player_lines or team_lines or proj_lines):
        body.append(
            '  <p style="font:15px system-ui,sans-serif;color:#666;">'
            'No leaderboard changes this week.</p>'
        )
    body.append("</div>")
    return "\n".join(b for b in body if b)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
def load_snapshot(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def save_snapshot(path: Path, snapshot: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(snapshot, indent=2, sort_keys=True))
