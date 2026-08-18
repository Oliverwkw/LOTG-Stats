"""Phase 14 — weekly automated 3-part audit (monitoring, not a build gate).

A lightweight, scheduled sanity sweep over the committed build outputs. Unlike
the full manual audit (see plan/MASTER_TODO.md), this runs unattended on a cron
and only has to *surface* three failure modes so the owner gets a red run + the
default GitHub "scheduled workflow failed" email:

  PART 1 — UNEXPECTED DIFFS (reproducibility).  The weekly workflow rebuilds
    FROM SCRATCH with the caches regenerated and passes the exports committed at
    HEAD as `--baseline`, so this part answers "does a cold rebuild still
    reproduce what we ship?".

    NOTHING IS EXEMPT BY NAME. Every sheet (including the all-time rollups,
    which carry no per-row season), every column (including the ones that move
    most weeks — O-Score, the skill / Luck family, rolling KTC windows) and every
    row (current and future seasons included) is compared. Each of the old
    exemptions was a prediction about which movements could not be bugs, and the
    predictions were wrong: the picks sheet is two-thirds future-dated rows that
    were never compared, and the first week they were, a 2028 pick had quietly
    changed hands. An audit that decides in advance what does not count cannot
    catch what it excluded.

    TWO MOVEMENTS ARE SUPPRESSED, AND ONLY WHERE THEY ARE PROVED. A tenure
    counter that advanced by the same elapsed time as the rest of its sheet is
    the wall clock; a "Link to …" that was renumbered but still resolves to the
    same event is a row number, not a relationship. Both are verified per row
    against the data — a tenure that moved by some other amount, or backwards,
    and a pointer that now lands on a different event, are flagged. That is the
    opposite of a name-based exemption: it is the only form of the rule that can
    still catch the bug it is filtering around. A third suppression, NFLverse
    upstream revisions, is described below.

    A row that was EDITED (the overwhelmingly common case) is reported as one
    `changed` entry naming the columns that moved and their old → new values,
    plus a per-sheet roll-up of which columns moved across how many rows —
    which is what identifies the cause. Only rows with no counterpart on the
    other side are reported as a bare add / remove.

    Rows that moved because NFLVERSE revised the data underneath them ARE still
    flagged; the attribution is reported alongside as the likely cause to check
    first. It is deliberately permissive enough to absorb a real regression that
    lands on the same row in the same week, so treating it as an excuse is
    exactly how such a bug would hide. "Underneath them"
    is wider than the row itself: a revision reaches our exports through three
    spans (the all-time percentile pool, a season's own positional baselines,
    and one player's whole game log), so a row is attributed when every column that
    moved in it rides a span the week's drift disturbed. See the channel tables
    below `NflverseAttribution` for why each family of columns belongs where.

  NFLVERSE UPSTREAM DRIFT. The audit build re-downloads every season
    (LOTG_REFRESH_EXTERNAL=1), so diffing the committed NFLverse cache against
    the freshly fetched one says exactly what upstream changed. That's an
    informational "NFLverse made N changes" line, and it supplies the
    (player, season, week) coordinates Part 1 uses to attribute its own diffs.
    It becomes a CONFIRMED problem in its own right when the drift is structural
    (rows, columns or files appearing / vanishing) or has moved more of our
    exports than lotg_support.nflverse_drift.MAX_ATTRIBUTED_ROWS — but the rows
    it touched are flagged in Part 1 either way.

  PART 2 — SCHEMA BREAKS.  Every sheet's columns are pinned in a committed
    baseline (data/audit/schema_baseline.json). A missing, renamed, reordered OR
    added column is a break, as is a sheet that is not pinned at all — the audit
    cannot tell a feature PR from an accident, so the pin gets refreshed
    deliberately (--update-schema) rather than by default.

  PART 3 — BUILD ERRORS.  We read the last build segment of
    exports/raw/build_debug.log plus the pytest log and flag every ERROR-level
    line and test failure. Nothing is written off as a transient blip or as
    in-progress-season noise. (Only the LAST build segment is read — the log
    accumulates runs, and earlier segments are earlier builds that were already
    reported.)

Exit code is 1 when any part has a CONFIRMED problem (so the scheduled run goes
red and notifies), else 0. The report is written to stdout and, when running in
Actions, appended to $GITHUB_STEP_SUMMARY.

Usage:
  PYTHONPATH=src:lib python scripts/audit_weekly.py \
      --current exports --baseline /tmp/baseline_exports
  python scripts/audit_weekly.py --update-schema        # re-pin the schema
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))   # so the shared classifier imports standalone
_SCHEMA_BASELINE = _ROOT / "data" / "audit" / "schema_baseline.json"

# All exported sheets (CSV basenames).
SHEETS = [
    "player_all_time", "team_all_time", "league_all_time",
    "player_year", "team_year", "league_year",
    "player_week", "team_week", "league_week",
    "picks", "trades", "transactions",
]

# Sheets whose rows carry a per-row season. This is now only a LABEL — it names
# the column so a reported row can say which season it belongs to. It does NOT
# decide what gets compared: every sheet, every column and every row is diffed
# (see audit_diffs). The all-time sheets are absent because their rows have no
# season, not because they are out of scope.
SEASON_COL = {
    "player_year": "Year", "team_year": "Year", "league_year": "Year",
    "player_week": "Year", "team_week": "Year", "league_week": "Year",
    "picks": "Year", "trades": "Season", "transactions": "Season",
}

# A few human-readable identifying columns per sheet, for the diff report only.
ID_COLS = {
    "player_all_time": ["Player"], "team_all_time": ["Team"],
    "league_all_time": [],          # one row; classify_diff pairs it positionally
    "player_year": ["Player", "Year"], "team_year": ["Team", "Year"],
    "league_year": ["Year"],
    "player_week": ["Player", "Year", "Week"], "team_week": ["Team", "Year", "Week"],
    "league_week": ["Year", "Week"],
    "picks": ["Year", "Number", "Player Picked"],
    "trades": ["Team", "Team's traded with 1", "Date"],
    "transactions": ["Team", "Player Added", "Player Dropped", "Date"],
}

_MAX_REPORT = 25       # cap per-sheet diff lines so the report stays readable
_MAX_DELTA_COLS = 4    # cap the "col: old → new" pairs shown for one changed row
_MAX_SUMMARY_COLS = 8  # cap the per-sheet "columns that moved" roll-up

# NOTE: lib/lotg_support/volatile_columns.py is deliberately NOT imported here
# any more. Classifying a column as "expected to drift" and then not comparing it
# is how a real regression in that column goes unreported; the audit now compares
# everything and lets the per-sheet roll-up carry the explanation instead.
from lotg_support.nflverse_drift import (  # noqa: E402
    Drift, diff_nflverse_cache, name_variants, normalize_name,
)


# ---------------------------------------------------------------------------
# NFLverse attribution
# ---------------------------------------------------------------------------
# An upstream revision does not only move the row it lands on. Our derived
# columns read the NFLverse game log through three different spans, and a
# coordinate-exact (player, season, week) match — all the audit had — can only
# see the first. Each span below is the channel one family of columns travels,
# and a row is attributed only when EVERY column that moved in it has a channel the
# week's drift can actually account for.

# ALL-TIME POOL. "Positional scoring percentile" places a score inside the
# pooled distribution of every active starter score ever recorded at that
# position (src/lotg.py `_positional_tier_bars`), so the pool has no season: one
# relabelled position anywhere re-seats every percentile in the file. Measured
# on the committed exports, flipping a single TE week to WR moves 1770 of the
# 21376 percentile values — which is the shape of the 1596 one-row-per-0.1
# percentile "breakages" this reporting was rebuilt for.
_POOL_ALLTIME_COLUMNS = ("positional scoring percentile",)

# WITHIN-SEASON POOL. The rest of the league-relative family is computed inside
# a single season, so it is only attributable to a revision in that same season:
#   * Starter PAR — replacement level is the bottom third of that (year, week,
#     position)'s started scores, so it moves for the whole cohort.
#   * "… adjusted by position" and the values built on top of it (player /
#     trade addition value, the pick-adjusted differences) — scaled by
#     `_pos_factor(season, pos)` = that season's league starter average over its
#     positional average.
_POOL_SEASON_COLUMNS = ("starter par", "adjusted by position",
                        "player addition value", "trade addition value")

# PLAYER GAME LOG, ANY SEASON. These read a span of one named player's log that
# reaches outside the row's own season — backwards ("… from career", "… from
# previous season", career PPG) or forwards to the present day (the on-team and
# post-drop PPG windows, which run until the player leaves). A 2022 correction
# therefore moves a 2023 row, and pinning attribution to the row's season left
# every one of those looking like our build failing to reproduce.
_PLAYER_LOG_COLUMNS = (
    "points (full season)", "from career", "from previous season", "ppg",
    "difference of averages", "points added", "points lost", "net points",
    "dropped avg points", "dropped total points",
)

# Where each sheet names the players a row is about, for the game-log channel.
# team_* / league_* are absent on purpose: they name no player, so they stay on
# the roster-reachability path below.
PLAYER_NAME_COLS = {
    "player_week": ["Player"], "player_year": ["Player"],
    "picks": ["Player Picked"],
    "transactions": ["Player Added", "Player Dropped"],
    "trades": ["Assets received", "Assets sent"],
}


def _matches(column: str, needles) -> bool:
    c = str(column).lower()
    return any(n in c for n in needles)


# The player a draft pick became, as our asset lists write it: "2024 4.06(K. Vidal)".
_PAREN = re.compile(r"\(([^)]*)\)")
class NflverseAttribution:
    """Which of our rows a given NFLverse revision can account for.

    NFLverse back-corrects completed seasons, so a past-season row of ours that
    moves *because upstream moved* is not a reproducibility failure and must not
    read as a dataset breakage. `Drift` gives us the (player, season, week)
    coordinates it revised; this maps those onto each sheet's identifying key.

    Downstream sheets (team / league / trades) carry no player, so they're
    reached through the current player_week roster: a team-week is attributed
    when a revised player was on that roster that week, and so on up. That is
    deliberately permissive — it can absorb a genuine regression that happens to
    land on the same row in a week when upstream also moved. The audit keeps the
    count and the moved columns visible in the report for exactly that reason:
    attributed rows are reported, just not flagged.

    Player names are compared FOLDED (nflverse_drift.normalize_name), because
    the two sides spell them differently: upstream ships "Calvin Austin III" and
    "Deebo Samuel Sr." where our Sleeper-sourced exports say "Calvin Austin" and
    "Deebo Samuel". Exact string matching silently excluded 31 of the 308 players
    in the 2025 exports from attribution, so their upstream revisions were
    reported as our build failing to reproduce history.

    Only CHANGED rows are attributable. Roster membership comes from Sleeper, so
    an NFLverse revision can never add or remove one of our rows; those stay
    flagged.
    """

    def __init__(self, drift: Drift, cur: Dict[str, pd.DataFrame]) -> None:
        self.player_weeks = set(drift.player_weeks) if drift else set()
        self.player_seasons = set(drift.player_seasons) if drift else set()
        self.players: Set[str] = set()
        for p in (drift.players if drift else ()):
            self.players |= name_variants(p)
        self.pools_disturbed = bool(drift and drift.pools_disturbed)
        self.pool_seasons: Set[str] = {str(y) for y in (drift.pool_seasons if drift else ())}
        self.active = bool(self.player_seasons or self.players or self.pools_disturbed)
        self.team_weeks: Set[tuple] = set()
        self.team_years: Set[tuple] = set()
        self.league_weeks: Set[tuple] = set()
        self.league_years: Set[str] = set()
        self.names_by_year: Dict[str, Set[str]] = defaultdict(set)
        # Folded + string-normalised copies: our exports are read as str,
        # NFLverse as int, and the two spell suffixed names differently.
        self._pw_keys: Set[tuple] = {(normalize_name(p), str(y), str(w))
                                     for p, y, w in self.player_weeks}
        self._py_keys: Set[tuple] = {(normalize_name(p), str(y))
                                     for p, y in self.player_seasons}
        # A player named in the drift's coordinates is a revised player too —
        # older Drift objects (and the tests) only populate the coordinate sets.
        for p, _ in self._py_keys:
            self.players |= name_variants(p)
        if not self.active:
            return
        for nm, yr in self.player_seasons:
            self.names_by_year[str(yr)].add(normalize_name(nm))
        self._index_rosters(cur.get("player_week"))

    def _index_rosters(self, pw: Optional[pd.DataFrame]) -> None:
        if pw is None or pw.empty:
            return
        if not {"Player", "Team", "Year", "Week"}.issubset(pw.columns):
            return
        for r in pw[["Player", "Team", "Year", "Week"]].itertuples(index=False):
            p, t, y, w = normalize_name(r.Player), str(r.Team), str(r.Year), str(r.Week)
            if (p, y, w) in self._pw_keys:
                self.team_weeks.add((t, y, w))
                self.league_weeks.add((y, w))
            if (p, y) in self._py_keys:
                self.team_years.add((t, y))
                self.league_years.add(y)

    @staticmethod
    def _names_in(text: str) -> Set[str]:
        """The player names inside a cell.

        Asset lists are ';'-separated and mix plain players ("Mike Gesicki")
        with draft picks. A pick names the player it became in parentheses,
        abbreviated — "2024 4.06(K. Vidal)" — so the whole part folds to
        something no player name can match, and a trade made entirely of picks
        had nothing attributable on it at all even though its PPG columns are
        computed from exactly those players. Pull the parenthesised half out too:
        it is nflverse's own `short_name` form, which `load_name_aliases`
        indexes. Team names appear in the same position on unmade picks
        ("2028 4(LWebs53)") and simply match nobody.
        """
        out: Set[str] = set()
        for part in str(text or "").split(";"):
            out |= name_variants(part)
            for inner in _PAREN.findall(part):
                out |= name_variants(inner)
        return out

    def _mentions(self, text: str, year: str) -> bool:
        names = self.names_by_year.get(str(year))
        if not names or not text:
            return False
        return any(nm in normalize_name(text) for nm in names)

    def _row_players(self, sheet: str, kv: Dict[str, str],
                     row: Dict[str, str]) -> Set[str]:
        out: Set[str] = set()
        for col in PLAYER_NAME_COLS.get(sheet, []):
            val = kv.get(col, row.get(col))
            if val:
                out |= self._names_in(val)
        return out

    def covers(self, sheet: str, idcols: List[str], key: tuple,
               row: Dict[str, str]) -> bool:
        if not self.active:
            return False
        kv = dict(zip(idcols, key))
        yr = str(kv.get("Year") or row.get("Year") or row.get("Season") or "")
        if sheet == "player_week":
            return (normalize_name(kv.get("Player")), yr, str(kv.get("Week"))) in self._pw_keys
        if sheet == "player_year":
            return (normalize_name(kv.get("Player")), yr) in self._py_keys
        if sheet == "team_week":
            return (str(kv.get("Team")), yr, str(kv.get("Week"))) in self.team_weeks
        if sheet == "team_year":
            return (str(kv.get("Team")), yr) in self.team_years
        if sheet == "league_week":
            return (yr, str(kv.get("Week"))) in self.league_weeks
        if sheet == "league_year":
            return yr in self.league_years
        if sheet == "picks":
            return self._mentions(str(kv.get("Player Picked") or ""), yr)
        if sheet == "transactions":
            return self._mentions(
                f"{kv.get('Player Added') or ''};{kv.get('Player Dropped') or ''}", yr)
        if sheet == "trades":
            return self._mentions(
                f"{row.get('Assets received') or ''};{row.get('Assets sent') or ''}", yr)
        return False

    def covers_columns(self, sheet: str, idcols: List[str], key: tuple,
                       row: Dict[str, str], moved: Sequence[str]) -> Optional[str]:
        """Can upstream account for EVERY column that moved in this row?

        The coordinate match above answers "did upstream revise this exact row";
        this answers the harder half — "did upstream revise something this row's
        value is computed FROM". A row is only attributed when every moved column
        rides a channel the week's drift actually disturbed, so one unexplained
        column still fails the whole row.

        Returns the channel it came through — "pool" when the row moved purely
        because a league baseline was re-seated, "direct" when a named player's
        own log moved — or None when upstream cannot account for it. The two are
        counted apart because they mean different things: a direct attribution
        is one upstream revision landing on one row of ours, while a pool
        attribution is fan-out (one relabelled position moves ~1770 percentile
        values), so only the direct count says anything about VOLUME.
        """
        if not self.active or not moved:
            return None
        kv = dict(zip(idcols, key))
        yr = str(kv.get("Year") or row.get("Year") or row.get("Season") or "")
        pool_season = yr in self.pool_seasons
        players = None      # resolved lazily; the name columns are the expensive bit
        pool_only = True
        for col in moved:
            if self.pools_disturbed and _matches(col, _POOL_ALLTIME_COLUMNS):
                continue
            if pool_season and _matches(col, _POOL_SEASON_COLUMNS):
                continue
            if _matches(col, _PLAYER_LOG_COLUMNS):
                if players is None:
                    players = self._row_players(sheet, kv, row)
                if any(p in self.players for p in players):
                    pool_only = False
                    continue
            return None
        return "pool" if pool_only else "direct"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read(directory: Path, name: str) -> pd.DataFrame:
    p = directory / f"{name}.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, low_memory=False, dtype=str, keep_default_na=False)


# Played-stat sheets only for detecting the in-progress season — picks / trades
# carry FUTURE years (upcoming draft picks, forward pick swaps) that would push
# the "current season" past reality.
_SEASON_SOURCES = ("team_year", "team_week", "player_year", "player_week")


def _current_season(cur: Dict[str, pd.DataFrame]) -> Optional[int]:
    """The in-progress (latest) season = max valid Year across the played-stat
    sheets (team_year seeds a placeholder row for the in-progress season)."""
    best: Optional[int] = None
    for name in _SEASON_SOURCES:
        df = cur.get(name)
        col = SEASON_COL.get(name)
        if df is None or df.empty or col not in df.columns:
            continue
        yrs = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(yrs):
            m = int(yrs.max())
            best = m if best is None else max(best, m)
    return best


class Report:
    """Collects findings as structured (kind, text, section) entries; a CONFIRMED
    (`flag`) finding fails the run. Renders to Markdown, and `grouped_flags()`
    pulls just the confirmed problems (with their detail lines + section) for the
    weekly health email."""

    def __init__(self) -> None:
        self.entries: List[tuple] = []   # (kind, text) with kind in head/ok/note/flag/raw
        self.confirmed = 0
        self._section = ""
        # Populated by run_audit so the email can render the NFLverse section
        # without re-diffing the caches.
        self.drift: Optional[Drift] = None
        self.nflverse_attributed = 0
        # Split of the above: rows a revision landed on directly, vs rows swept
        # along when a league-relative baseline was re-seated. Only the direct
        # count is a measure of how much upstream actually moved — see
        # NflverseAttribution.covers_columns.
        self.attributed_direct = 0
        self.attributed_pool = 0
        # Individual VALUES that moved in the attributed rows (a row usually
        # carries several). This is what the collapsed one-line email reports as
        # the reach of an upstream release into our exports.
        self.attributed_cells = 0
        self.attributed_sheets: Dict[str, int] = {}
        self.attributed_columns: List[Tuple[str, int]] = []

    def head(self, text: str) -> None:
        self._section = text
        self.entries.append(("head", text))

    def ok(self, text: str) -> None:
        self.entries.append(("ok", text))

    def note(self, text: str) -> None:
        self.entries.append(("note", text))

    def flag(self, text: str) -> None:
        self.confirmed += 1
        self.entries.append(("flag", text, self._section))

    def raw(self, text: str) -> None:
        self.entries.append(("raw", text))

    def render(self) -> str:
        status = "❌ PROBLEMS FOUND" if self.confirmed else "✅ CLEAN"
        marks = {"head": lambda t: f"\n## {t}\n", "ok": lambda t: f"- ✅ {t}",
                 "note": lambda t: f"- ℹ️ {t}", "flag": lambda t: f"- ❌ {t}",
                 "raw": lambda t: t}
        body = "\n".join(marks[e[0]](e[1]) for e in self.entries)
        return f"# Weekly audit — {status} ({self.confirmed} confirmed)\n" + body

    def grouped_flags(self) -> List[dict]:
        """[{section, text, details:[...]}] for each confirmed problem — the
        detail lines are the `raw` entries that immediately follow the flag."""
        out: List[dict] = []
        for i, e in enumerate(self.entries):
            if e[0] != "flag":
                continue
            details = []
            for nxt in self.entries[i + 1:]:
                if nxt[0] != "raw":
                    break
                details.append(nxt[1].strip())
            out.append({"section": e[2] if len(e) > 2 else "", "text": e[1], "details": details})
        return out


def run_audit(current_dir: Path, baseline_dir: Optional[Path],
              nflverse_before: Optional[Path] = None,
              nflverse_after: Optional[Path] = None) -> Report:
    """Run all three audit parts against a build directory (+ optional git
    baseline for Part 1, + optional NFLverse cache snapshots) and return the
    populated Report."""
    cur = {n: _read(current_dir, n) for n in SHEETS}
    base = {n: _read(baseline_dir, n) for n in SHEETS} if baseline_dir else {}
    season = _current_season(cur)
    rep = Report()
    drift = diff_nflverse_cache(nflverse_before, nflverse_after)
    attrib = NflverseAttribution(drift, cur)
    attributed = audit_diffs(cur, base, season, rep, attrib)
    rep.drift, rep.nflverse_attributed = drift, attributed
    # The volume threshold is judged on the DIRECT attributions only: pooled
    # fan-out scales with how league-relative our stats are, not with how much
    # upstream changed, so counting it would put every position relabel over the
    # line no matter how small the revision behind it.
    audit_nflverse(drift, rep.attributed_direct, rep, season, attributed)
    audit_schema(cur, rep)
    audit_build_log(current_dir / "raw", season, rep)
    return rep


# ---------------------------------------------------------------------------
# NFLverse upstream drift (informational unless significant)
# ---------------------------------------------------------------------------
def audit_nflverse(drift: Drift, attributed_rows: int, rep: Report,
                   current_season: Optional[int] = None,
                   reported_rows: Optional[int] = None) -> None:
    """Say what NFLverse changed. Upstream back-correcting a completed season is
    their data moving, not our build failing to reproduce it, so this is a note
    — until it is structural (rows / columns / files appearing or vanishing) or
    it has moved more of our exports than the threshold, at which point it is a
    flag and someone should look."""
    rep.head("NFLverse upstream drift")
    reason = drift.is_significant(attributed_rows, current_season) if drift.compared else None
    line = drift.summary()
    shown = attributed_rows if reported_rows is None else reported_rows
    if shown:
        line += (f" That accounts for {shown} changed past-season row(s) "
                 "in our exports, which Part 1 therefore did not flag.")
    if reason:
        rep.flag(f"{line} Significant: {reason}.")
    else:
        rep.note(line)
    for d in drift.detail_lines():
        rep.raw(f"    - {d}")


# ---------------------------------------------------------------------------
# The wall clock
# ---------------------------------------------------------------------------
# One family of columns is a stopwatch: "how long has this asset been on this
# team", counted to TODAY. Every still-held asset advances by exactly the days
# between the two builds, so a week's rebuild moves ~270 rows by an identical
# amount. That is the clock, not a change, and reporting it every week trains
# the reader to skim the one part of the email that must not be skimmed.
#
# It is suppressed only where it is PROVABLY the clock: the row moved by the
# same amount as the bulk of its sheet, and forwards. A tenure that moved by
# some other amount, or backwards, or on an asset whose tenure should have
# stopped, is not the clock and is still flagged — which is the failure a blanket
# name-based exemption would have hidden.
_WALL_CLOCK_COLUMNS = ("length of tenure",)


def is_wall_clock_column(column: str) -> bool:
    return any(n in str(column).lower() for n in _WALL_CLOCK_COLUMNS)


def _tick(deltas: Sequence[tuple]) -> Optional[float]:
    """The advance a wall-clock delta represents, or None if it isn't one."""
    for col, old, new in deltas:
        if not is_wall_clock_column(col):
            continue
        try:
            step = float(new) - float(old)
        except (TypeError, ValueError):
            return None
        return step if step > 0 else None
    return None


def wall_clock_step(changed: Sequence[tuple]) -> Optional[float]:
    """The one advance the sheet's clock columns share this week, if there is
    one. Taken as the modal positive step so a single odd row can't define it."""
    steps = Counter(t for t in (_tick(d) for _k, d, _r in changed) if t is not None)
    if not steps:
        return None
    step, n = steps.most_common(1)[0]
    return step if n >= 2 else None


def strip_wall_clock(changed: List[tuple], step: Optional[float]) -> Tuple[List[tuple], int]:
    """Drop the clock's own tick from each row's deltas; rows left with nothing
    else are the clock and nothing more. Returns (kept, rows_dropped)."""
    if step is None:
        return changed, 0
    kept, dropped = [], 0
    for k, deltas, row in changed:
        rest = [(c, o, n) for c, o, n in deltas
                if not (is_wall_clock_column(c) and _tick([(c, o, n)]) == step)]
        if not rest:
            dropped += 1
            continue
        kept.append((k, rest, row))
    return kept, dropped


# ---------------------------------------------------------------------------
# Row-index pointers
# ---------------------------------------------------------------------------
# The "Link to …" columns are 1-based ROW NUMBERS into another sheet — "T#193"
# is the 193rd trade, "#48" the 48th transaction. Insert six trades and every
# later pointer renumbers, so one ordinary week rewrites ~750 of them without a
# single relationship changing.
#
# Suppressed only where the pointer still means the same thing: both sides are
# resolved against their own sheet and the delta is dropped only when they land
# on the SAME event. A pointer that now resolves to a different trade — or to
# nothing — is a real repointing bug and is flagged, which is exactly what a
# name-based exemption on "link to" could never see.
# A cell holds one pointer ("#48") or a per-asset list ("T#7; #54; PH#64").
_LINK_TARGETS = {"T": "trades", "": "transactions", "PH": "picks"}
_LINK_REF = re.compile(r"^\s*([A-Za-z]*)#(\d+)\s*$")


_WINDOW_COLUMNS = ("year later", "years later", "year after", "years after")


def is_window_column(column: str) -> bool:
    """A KTC value measured a fixed time AFTER the event — it cannot be computed
    until that anniversary passes."""
    c = str(column).lower()
    return any(n in c for n in _WINDOW_COLUMNS)


def _is_blank(v) -> bool:
    return str(v).strip().lower() in ("", "nan", "n/a", "none")


def strip_matured_windows(changed: List[tuple]) -> Tuple[List[tuple], int]:
    """Drop the first value a rolling window takes. Blank → a number is the
    anniversary arriving; a number → a different number is not, and neither is
    0 → a number, which is a value that was wrong and has been corrected."""
    kept, matured = [], 0
    for k, deltas, row in changed:
        rest = [(c, o, n) for c, o, n in deltas
                if not (is_window_column(c) and _is_blank(o) and not _is_blank(n))]
        if not rest:
            matured += 1
            continue
        kept.append((k, rest, row))
    return kept, matured


def is_link_column(column: str) -> bool:
    return "link to" in str(column).lower()


def _resolve_refs(cell: str, frames: Dict[str, pd.DataFrame]) -> Optional[list]:
    """Every pointer in the cell, resolved to what it points AT. None if any one
    of them can't be read — an unreadable pointer is not something to wave off."""
    out = []
    for part in str(cell).split(";"):
        if not part.strip():
            out.append(("", ))          # an empty slot is itself a value
            continue
        target = _resolve_link(part, frames)
        if target is None:
            return None
        out.append(target)
    return out


def _resolve_link(ref: str, frames: Dict[str, pd.DataFrame]) -> Optional[tuple]:
    """(sheet, identifying-key) the pointer lands on, or None if it can't be read."""
    m = _LINK_REF.match(str(ref))
    if not m:
        return None
    sheet = _LINK_TARGETS.get(m.group(1).upper())
    df = frames.get(sheet) if sheet else None
    if df is None or df.empty:
        return None
    i = int(m.group(2)) - 1               # the exports write these 1-based
    if not (0 <= i < len(df)):
        return None
    row = df.iloc[i]
    cols = [c for c in ID_COLS.get(sheet, []) if c in df.columns]
    return (sheet,) + tuple(str(row[c]) for c in cols)


def strip_stable_links(changed: List[tuple], base_frames: Dict[str, pd.DataFrame],
                       cur_frames: Dict[str, pd.DataFrame]) -> Tuple[List[tuple], int]:
    """Drop pointer deltas that were only renumbered. Returns (kept, rows_dropped)."""
    kept, dropped = [], 0
    for k, deltas, row in changed:
        rest = []
        for col, old, new in deltas:
            if is_link_column(col):
                was = _resolve_refs(old, base_frames)
                now = _resolve_refs(new, cur_frames)
                if was is not None and was == now:
                    continue          # same events, new row numbers
            rest.append((col, old, new))
        if not rest:
            dropped += 1
            continue
        kept.append((k, rest, row))
    return kept, dropped


# ---------------------------------------------------------------------------
# League events
# ---------------------------------------------------------------------------
# When a trade lands, the dataset is SUPPOSED to move. Trade counts change,
# players change hands, the league-relative percentiles every team and deal is
# scored against re-seat, and pointers that had nowhere to point now do. That is
# new information arriving, not the build failing to reproduce — three deals one
# week moved 500+ rows, and reporting them as breakages is how the one row that
# mattered got lost.
#
# Gated on there actually being new events: with no adds or removes this week,
# none of it is suppressed and an O-Score that moves on its own is still a
# finding.
_EVENT_COLUMNS = (
    "number of trades", "total trades", "offseason trades", "number of transactions",
    "number of teams", "last team", "drafting skill", "trading skill",
    "transaction skill", "o-score", "trade impact score", "future draft capital",
    "assets retained now", "assets traded away", "assets dropped to fa",
    "return from trades", "additional assets traded away in those deals",
    "date dropped/traded",
)
# Where a sheet names the players an event moved, so a tenure that STOPPED
# because the asset left can be told from a tenure that moved for no reason.
_EVENT_PLAYER_COLS = {
    "picks": ("Player Picked",),
    "trades": ("Assets received", "Assets sent"),
    "transactions": ("Player Added", "Player Dropped"),
}


def is_event_column(column: str) -> bool:
    c = str(column).lower()
    return c == "team" or any(n in c for n in _EVENT_COLUMNS)


class LeagueEvents:
    """The picks / trades / transactions rows that are new (or gone) this week,
    and what they touched."""

    def __init__(self, cur: Dict[str, pd.DataFrame], base: Dict[str, pd.DataFrame]) -> None:
        self.targets: Set[tuple] = set()      # (sheet, *id-key) of each new/removed row
        self.players: Set[str] = set()
        for sheet in _EVENT_PLAYER_COLS:
            c, b = cur.get(sheet), base.get(sheet)
            if c is None or b is None or c.empty or b.empty:
                continue
            idc = [x for x in ID_COLS.get(sheet, []) if x in c.columns and x in b.columns]
            if not idc:
                continue
            ck = {tuple(str(v) for v in r) for r in c[idc].values}
            bk = {tuple(str(v) for v in r) for r in b[idc].values}
            fresh = (ck - bk) | (bk - ck)
            if not fresh:
                continue
            self.targets |= {(sheet,) + k for k in fresh}
            rows = c[[tuple(str(v) for v in r) in fresh for r in c[idc].values]]
            for col in _EVENT_PLAYER_COLS[sheet]:
                if col not in rows.columns:
                    continue
                for cell in rows[col].dropna().astype(str):
                    for part in cell.split(";"):
                        name = _PAREN.sub("", part).strip()
                        if name:
                            self.players.add(name)
        self.active = bool(self.targets)

    def _links_to_new_events(self, old, new, base_frames, cur_frames) -> bool:
        """True when the pointer only gained or lost references to this week's
        new events — the deal that just happened being wired in."""
        was, now = _resolve_refs(old, base_frames), _resolve_refs(new, cur_frames)
        if was is None or now is None:
            return False
        moved = [t for t in (set(map(tuple, was)) ^ set(map(tuple, now))) if t != ("",)]
        return bool(moved) and all(t in self.targets for t in moved)

    def is_new_row(self, sheet: str, idcols: Sequence[str], key: tuple) -> bool:
        """True when this whole row IS one of the week's events, or belongs to a
        player one of them moved — a trade's own two rows, and the season row a
        player gains when he joins a team."""
        if (sheet,) + tuple(key) in self.targets:
            return True
        named = {str(v) for c, v in zip(idcols, key)
                 if c in ("Player", "Player Picked", "Player Added", "Player Dropped")}
        return bool(named & self.players)

    def covers(self, sheet: str, deltas, row: dict,
               base_frames, cur_frames) -> bool:
        """True when every column that moved in this row is the new events
        arriving."""
        named = {str(row.get(c, "")) for c in _EVENT_PLAYER_COLS.get(sheet, ())}
        touched = bool(named & self.players)
        for col, old, new in deltas:
            if is_event_column(col):
                continue
            if is_link_column(col) and self._links_to_new_events(old, new,
                                                                 base_frames, cur_frames):
                continue
            if is_wall_clock_column(col) and touched:
                continue          # the tenure stopped because the asset moved
            return False
        return True


# ---------------------------------------------------------------------------
# Part 1 — unexpected diffs (completed-season immutability)
# ---------------------------------------------------------------------------
def _row_key(row: pd.Series, cols: List[str]) -> str:
    return " | ".join(f"{c}={row.get(c, '')}" for c in cols if c in row.index)


def _key_text(idcols: Sequence[str], key: tuple) -> str:
    return " | ".join(f"{c}={v}" for c, v in zip(idcols, key)) or "(row)"


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _fmt(v: str) -> str:
    """Blanks are the most common half of a drift pair; make them visible."""
    return "∅" if v == "" else str(v)


def classify_diff(shared: List[str], idcols: List[str],
                  base_rows: List[tuple], cur_rows: List[tuple]) -> Tuple[list, list, list]:
    """Split a past-season multiset diff into (changed, added, removed).

    A full-row multiset diff cannot tell a MODIFIED row from a delete+insert:
    every edited row shows up once on each side. In practice essentially every
    real finding is a modification, so reporting the two halves separately
    produced the useless "N added / N removed, same identifying keys" email that
    never said WHAT moved. So we re-pair the two sides on the sheet's
    identifying columns: keys present on both sides are modifications (returned
    with their per-column old → new deltas), leftovers are genuine adds/removes.

    Returns ([(key, [(col, old, new), …], new_row_tuple), …],
             [added key], [removed key]).
    """
    pos = {c: i for i, c in enumerate(shared)}
    kpos = [pos[c] for c in idcols if c in pos]
    if not kpos:
        # A one-row sheet (league_all_time) has no identifying columns, but the
        # single row on each side IS the pair — report it as a modification with
        # its deltas rather than as a meaningless add + remove.
        if len(cur_rows) == 1 and len(base_rows) == 1:
            deltas = [(shared[j], base_rows[0][j], cur_rows[0][j])
                      for j in range(len(shared)) if base_rows[0][j] != cur_rows[0][j]]
            return [((), deltas, cur_rows[0])], [], []
        # Otherwise there is nothing to pair on — report both sides.
        return [], [() for _ in cur_rows], [() for _ in base_rows]

    def key(t: tuple) -> tuple:
        return tuple(t[i] for i in kpos)

    by_added: Dict[tuple, List[tuple]] = defaultdict(list)
    by_removed: Dict[tuple, List[tuple]] = defaultdict(list)
    for t in cur_rows:
        by_added[key(t)].append(t)
    for t in base_rows:
        by_removed[key(t)].append(t)

    changed: List[tuple] = []
    added: List[tuple] = []
    removed: List[tuple] = []
    for k in sorted(set(by_added) | set(by_removed)):
        a, r = by_added.get(k, []), by_removed.get(k, [])
        paired = min(len(a), len(r))
        for i in range(paired):
            deltas = [(shared[j], r[i][j], a[i][j])
                      for j in range(len(shared)) if r[i][j] != a[i][j]]
            changed.append((k, deltas, a[i]))
        added.extend([k] * (len(a) - paired))
        removed.extend([k] * (len(r) - paired))
    return changed, added, removed


def audit_diffs(cur: Dict[str, pd.DataFrame], base: Dict[str, pd.DataFrame],
                current_season: Optional[int], rep: Report,
                attrib: Optional[NflverseAttribution] = None) -> int:
    """Report past-season rows that moved. Returns the number of rows withheld
    from the flags because an NFLverse revision accounts for them."""
    rep.head("Part 1 — unexpected diffs (every sheet, every column, every row)")
    if not base or all(df.empty for df in base.values()):
        rep.note("No baseline exports supplied — skipping the diff "
                 "(first run, or the workflow couldn't materialise a prior version).")
        return 0
    if current_season is not None:
        rep.note(f"In-progress season = **{current_season}** — named for context only. "
                 "Nothing is exempt: a moved row is flagged whichever season it is in.")

    any_change = False
    flagged_any = False
    pool_swept = 0
    attributed: Dict[str, int] = {}
    attributed_cols: Counter = Counter()
    events = LeagueEvents(cur, base)
    for name in SHEETS:
        c, b = cur.get(name), base.get(name)
        if c is None or b is None or c.empty or b.empty:
            continue
        # EVERY shared column. There is no build-volatile exemption: a column
        # that moves every week is either a bug or a fact about the data, and
        # the audit's job is to say so rather than to decide in advance which
        # movements do not count. (The per-sheet "columns that moved" roll-up
        # below is what keeps a broad, explainable move readable.)
        shared = [col for col in b.columns if col in c.columns]
        if not shared:
            continue
        # EVERY row, current and future seasons included. "Completed seasons are
        # frozen" was a narrower question than "does this build reproduce"; a
        # current-season row that moves for the wrong reason is just as much a
        # bug, and the picks sheet is two-thirds future-dated rows that the old
        # gate never compared at all.
        cp = c[shared]
        bp = b[shared]
        # Full-row multiset diff, then re-paired on the identifying columns so a
        # MODIFIED row is reported as one change (with the columns that moved)
        # rather than as an unexplained removed+added pair.
        cur_counts = Counter(cp.itertuples(index=False, name=None))
        base_counts = Counter(bp.itertuples(index=False, name=None))
        added_tups = list((cur_counts - base_counts).elements())
        removed_tups = list((base_counts - cur_counts).elements())
        if not added_tups and not removed_tups:
            continue
        any_change = True
        idcols = [c2 for c2 in ID_COLS.get(name, []) if c2 in shared]
        changed, added, removed = classify_diff(shared, idcols, removed_tups, added_tups)

        # Peel off the wall clock first — a tenure counter advancing by the same
        # amount as the rest of its sheet is time passing, not the dataset
        # moving. Anything the clock does NOT explain stays in `changed`.
        step = wall_clock_step(changed)
        changed, _ticked = strip_wall_clock(changed, step)

        # Same idea for the row-index pointers: a renumbered pointer that still
        # lands on the same event is not a change to the dataset.
        changed, _renumbered = strip_stable_links(changed, base, cur)

        # A rolling KTC window reaching its anniversary and taking its first
        # value is the calendar, not the dataset moving.
        changed, _matured = strip_matured_windows(changed)

        # New league events — a trade landing is supposed to move the counts,
        # the league-relative scores and the pointers that now have somewhere to
        # point. Suppressed only while there ARE new events this week.
        if events.active:
            changed = [item for item in changed
                       if not events.covers(name, item[1],
                                            dict(zip(shared, item[2])), base, cur)]
            added = [k for k in added if not events.is_new_row(name, idcols, k)]
            removed = [k for k in removed if not events.is_new_row(name, idcols, k)]

        # Peel off the rows an NFLverse revision accounts for. Upstream
        # back-correcting a season is THEIR data moving, not our build failing to
        # reproduce it — measured on the 2026-08-12 run that is 2,935 of our rows
        # in one week, and calling those bugs would bury every real finding. They
        # are counted and their columns reported under the NFLverse section.
        if attrib is not None and attrib.active:
            kept, taken = [], []
            for item in changed:
                k, deltas, row_tup = item
                row = dict(zip(shared, row_tup))
                cols = [c for c, _o, _n in deltas]
                if attrib.covers(name, idcols, k, row):
                    channel = "direct"
                else:
                    channel = attrib.covers_columns(name, idcols, k, row, cols)
                if channel is None:
                    kept.append(item)
                    continue
                taken.append(item)
                if channel == "pool":
                    pool_swept += 1
            if taken:
                attributed[name] = attributed.get(name, 0) + len(taken)
                for _, deltas, _ in taken:
                    for col, _o, _n in deltas:
                        attributed_cols[col] += 1
            changed = kept
        if not changed and not added and not removed:
            continue

        counts = [(len(changed), "changed"), (len(added), "added"), (len(removed), "removed")]
        parts = ", ".join(f"{n} {label}" for n, label in counts if n)
        flagged_any = True
        rep.flag(f"**{name}**: {parts} row(s) moved since the committed build.")

        # The roll-up is the actionable line: one column moving across many rows
        # is a single cause (a revised upstream feed, a formula change), not N
        # mysteries. It's what tells the maintainer whether to fix the build or
        # to classify the column as build-volatile.
        moved = Counter(col for _, deltas, _ in changed for col, _, _ in deltas)
        if moved:
            top = ", ".join(f"{c} ({n})" for c, n in moved.most_common(_MAX_SUMMARY_COLS))
            extra = f" … +{len(moved) - _MAX_SUMMARY_COLS} more column(s)" \
                if len(moved) > _MAX_SUMMARY_COLS else ""
            rep.raw(f"    - columns that moved: {top}{extra}")

        # Share the line budget across the classes present, so a long list of
        # one kind can't silently swallow the others (it used to: 25 removals
        # left zero room for the adds, and the email then cut that to 15).
        present = [n for n, _ in counts if n]
        per_class = max(3, _MAX_REPORT // max(1, len(present)))

        def _emit(items, render) -> None:
            for it in items[:per_class]:
                rep.raw(render(it))
            if len(items) > per_class:
                rep.raw(f"    - … and {len(items) - per_class} more")

        def _changed_line(item) -> str:
            k, deltas, _row = item
            shown_cols = "; ".join(f"{c}: {_fmt(o)} → {_fmt(n)}"
                                   for c, o, n in deltas[:_MAX_DELTA_COLS])
            if len(deltas) > _MAX_DELTA_COLS:
                shown_cols += f"; (+{len(deltas) - _MAX_DELTA_COLS} more column(s))"
            return f"    - changed: {_key_text(idcols, k)} — {shown_cols}"

        _emit(changed, _changed_line)
        _emit(added, lambda k: f"    - added:   {_key_text(idcols, k)}")
        _emit(removed, lambda k: f"    - removed: {_key_text(idcols, k)}")
    total_attributed = sum(attributed.values())
    rep.attributed_sheets = dict(sorted(attributed.items(), key=lambda kv: -kv[1]))
    rep.attributed_columns = attributed_cols.most_common(_MAX_SUMMARY_COLS)
    rep.attributed_cells = sum(attributed_cols.values())
    rep.attributed_pool = pool_swept
    rep.attributed_direct = total_attributed - pool_swept
    if total_attributed:
        sheets = ", ".join(f"{k} ({v})" for k, v in rep.attributed_sheets.items())
        cols = ", ".join(f"{c} ({n})" for c, n in attributed_cols.most_common(6))
        swept = (f" {pool_swept} of them are league-relative values swept along by a "
                 "re-seated positional baseline." if pool_swept else "")
        rep.note(f"{total_attributed} row(s) moved because NFLverse revised the "
                 f"data underneath them — not flagged. {sheets}."
                 + (f" Columns: {cols}." if cols else "") + swept)
    if not any_change:
        rep.ok("Not one row of any sheet changed since the committed build.")
    elif not flagged_any:
        rep.ok("Every row that moved is explained — an upstream NFLverse revision "
               "or the wall clock. Nothing unaccounted for.")
    return total_attributed


# ---------------------------------------------------------------------------
# Part 2 — schema breaks
# ---------------------------------------------------------------------------
def current_schema(cur: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
    return {name: list(df.columns) for name, df in cur.items() if not df.empty}


def _only_insertions(have: Sequence[str], pinned: Sequence[str]) -> bool:
    """True when `have` is `pinned` with new columns inserted — every pinned
    column still present, still in its pinned order relative to the others."""
    it = iter(have)
    return all(c in it for c in pinned)


def audit_schema(cur: Dict[str, pd.DataFrame], rep: Report) -> None:
    rep.head("Part 2 — schema breaks")
    if not _SCHEMA_BASELINE.exists():
        rep.note(f"No schema baseline at {_SCHEMA_BASELINE.relative_to(_ROOT)} — "
                 "run `python scripts/audit_weekly.py --update-schema` once to pin it.")
        return
    baseline = json.loads(_SCHEMA_BASELINE.read_text())
    clean = True
    for name, cols in baseline.items():
        df = cur.get(name)
        if df is None or df.empty:
            rep.flag(f"**{name}**: sheet is missing / empty in the current build.")
            clean = False
            continue
        have = list(df.columns)
        missing = [c for c in cols if c not in have]
        extra = [c for c in have if c not in cols]
        if missing:
            rep.flag(f"**{name}**: {len(missing)} expected column(s) gone — "
                     f"{', '.join(missing[:8])}{' …' if len(missing) > 8 else ''}")
            clean = False
        elif have[:len(cols)] != cols and not _only_insertions(have, cols):
            # Genuinely shuffled: the pinned columns no longer appear in their
            # pinned order relative to each other, which breaks consumers that
            # read by position. Adding a column mid-sheet does NOT do that, and
            # is handled as a stale pin below.
            rep.flag(f"**{name}**: columns reordered vs the pinned baseline.")
            clean = False
        if extra:
            # A schema that no longer matches its pin is a change to the shape of
            # what we ship, whether the cause is a feature PR or an accident. The
            # audit cannot tell those apart, so it says so and the pin gets
            # refreshed deliberately (--update-schema) rather than by default.
            rep.flag(f"**{name}**: {len(extra)} column(s) not in the pinned baseline — "
                     f"{', '.join(extra[:8])}{' …' if len(extra) > 8 else ''} "
                     "(re-pin with --update-schema if intended).")
            clean = False
    for name in cur:
        if name not in baseline and not cur[name].empty:
            rep.flag(f"**{name}**: sheet is not in the pinned baseline "
                     "(re-pin with --update-schema if intended).")
            clean = False
    if clean:
        rep.ok("Every pinned sheet has all its expected columns, in order.")


def write_schema_baseline(cur: Dict[str, pd.DataFrame]) -> None:
    schema = current_schema(cur)
    _SCHEMA_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    _SCHEMA_BASELINE.write_text(json.dumps(schema, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Part 3 — build errors
# ---------------------------------------------------------------------------
# There is no transient allowance any more. A 403 that "self-heals next run" is
# also what a source that has started blocking us looks like on its first week,
# and a build that silently fell back to cached data produced numbers nobody
# checked. Every ERROR-shaped line in the last build is reported.
# A candidate error line is a structured build-log ERROR ("[ts] ERROR at …") or a
# Python exception *terminator* ("urllib.error.URLError: …"). Bare "Traceback"
# headers and intermediate code frames carry no diagnosis, so we skip them and
# classify the terminal exception line instead (which does mention the cause).
_ERROR_LINE = re.compile(r"\]\s+ERROR\b|^\s*[\w.]+(Error|Exception):")


def _last_build_segment(text: str) -> str:
    """The build_debug.log accumulates runs; analyse only the most recent one."""
    starts = [m.start() for m in re.finditer(r"=====\s*Build start\s*=====", text)]
    return text[starts[-1]:] if starts else text


def audit_build_log(logs_dir: Path, current_season: Optional[int], rep: Report) -> None:
    # `current_season` is accepted for call compatibility and deliberately unused:
    # a log line is no longer written off because it mentions the in-progress year.
    rep.head("Part 3 — build errors (every ERROR line in the last build)")
    debug = logs_dir / "build_debug.log"
    if not debug.exists():
        rep.note(f"No build log at {debug} — nothing to scan.")
    else:
        seg = _last_build_segment(debug.read_text(errors="replace"))
        flagged = [ln.strip() for ln in seg.splitlines() if _ERROR_LINE.search(ln)]
        # The build's own data-quality summary is the authoritative error count.
        m = re.findall(r"data-quality sanity:\s*(\d+)\s*ERROR,\s*(\d+)\s*WARN", seg)
        if m:
            errs, warns = (int(x) for x in m[-1])
            (rep.flag if errs else rep.ok)(
                f"build data-quality sanity: {errs} ERROR, {warns} WARN.")
        if flagged:
            rep.flag(f"{len(flagged)} ERROR line(s) in the last build:")
            for ln in flagged[:_MAX_REPORT]:
                rep.raw(f"    - {ln}")
            if len(flagged) > _MAX_REPORT:
                rep.raw(f"    - … and {len(flagged) - _MAX_REPORT} more")
        else:
            rep.ok("No ERROR lines in the last build.")

    pytest_log = logs_dir / "pytest.log"
    if pytest_log.exists():
        tail = pytest_log.read_text(errors="replace")
        m = re.search(r"(\d+) failed", tail)
        if m and int(m.group(1)) > 0:
            rep.flag(f"committed pytest log reports {m.group(1)} failing test(s).")
        elif re.search(r"\bpassed\b", tail):
            rep.ok("committed pytest log shows the suite passing.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weekly automated 3-part audit.")
    ap.add_argument("--current", default=str(_ROOT / "exports"),
                    help="directory of the current build's CSVs (+ raw/ logs)")
    ap.add_argument("--baseline", default=None,
                    help="directory of the previous committed CSVs (for Part 1)")
    ap.add_argument("--update-schema", action="store_true",
                    help="re-pin data/audit/schema_baseline.json from --current and exit")
    ap.add_argument("--nflverse-before", default=None,
                    help="directory of the NFLverse cache CSVs as committed (pre-build)")
    ap.add_argument("--nflverse-after", default=str(_ROOT / ".cache"),
                    help="directory of the NFLverse cache CSVs after the build re-fetched them")
    args = ap.parse_args(argv)

    current_dir = Path(args.current)
    cur = {n: _read(current_dir, n) for n in SHEETS}

    if args.update_schema:
        write_schema_baseline(cur)
        print(f"[audit] schema baseline pinned -> {_SCHEMA_BASELINE}")
        return 0

    rep = run_audit(
        current_dir,
        Path(args.baseline) if args.baseline else None,
        Path(args.nflverse_before) if args.nflverse_before else None,
        Path(args.nflverse_after) if args.nflverse_after else None,
    )

    out = rep.render()
    print(out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a") as fh:
                fh.write(out + "\n")
        except OSError:
            pass
    return 1 if rep.confirmed else 0


if __name__ == "__main__":
    sys.exit(main())
