"""Phase 14 — weekly automated 3-part audit (monitoring, not a build gate).

A lightweight, scheduled sanity sweep over the committed build outputs. Unlike
the full manual audit (see plan/MASTER_TODO.md), this runs unattended on a cron
and only has to *surface* three failure modes so the owner gets a red run + the
default GitHub "scheduled workflow failed" email:

  PART 1 — UNEXPECTED DIFFS (reproducibility).  Historical (completed-season)
    data should be reproducible: once a season is over, rebuilding must yield
    the same player_week / team_year / trades / … rows. The weekly workflow
    rebuilds FROM SCRATCH with the caches regenerated and passes the exports
    committed at HEAD as `--baseline`, so this part answers "does a cold rebuild
    still reproduce what we ship?". Any add / remove / change to a *past-season*
    row is flagged. Current-season rows legitimately churn, so they're exempt —
    as are the build-volatile columns below, which move on every rebuild by
    design and would otherwise bury the signal (~2k rows/week).

    A row that was EDITED (the overwhelmingly common case) is reported as one
    `changed` entry naming the columns that moved and their old → new values,
    plus a per-sheet roll-up of which columns moved across how many rows —
    which is what identifies the cause. Only rows with no counterpart on the
    other side are reported as a bare add / remove.

    Rows that moved because NFLVERSE revised the data underneath them are NOT
    flagged: upstream back-correcting a completed season is their data moving,
    not our build failing to reproduce it. They're counted and their columns
    reported under the NFLverse section instead — see below.

  NFLVERSE UPSTREAM DRIFT. The audit build re-downloads every season
    (LOTG_REFRESH_EXTERNAL=1), so diffing the committed NFLverse cache against
    the freshly fetched one says exactly what upstream changed. That's an
    informational "NFLverse made N changes" line, and it supplies the
    (player, season, week) coordinates Part 1 uses to attribute its own diffs.
    It becomes a CONFIRMED problem only when the drift is structural (rows,
    columns or files appearing / vanishing) or has moved more of our exports
    than lotg_support.nflverse_drift.MAX_ATTRIBUTED_ROWS.

  PART 2 — SCHEMA BREAKS.  Every sheet's columns are pinned in a committed
    baseline (data/audit/schema_baseline.json). A missing / renamed / reordered
    column is a break; a brand-new column is noted (regenerate the baseline with
    --update-schema when the change is intentional).

  PART 3 — BUILD ERRORS (not attributable to the in-progress season).  We read
    the last build segment of exports/raw/build_debug.log plus the committed
    pytest log, and flag ERROR-level lines / tracebacks / test failures that
    aren't transient network blips or expected current-season preseason noise.

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

# Sheets whose rows carry a per-row season, so completed-season rows are frozen.
# name -> the column that identifies the season. All-time / cumulative sheets
# (player_all_time, team_all_time, league_all_time) are intentionally absent:
# their aggregates roll in the in-progress season and so legitimately move.
SEASON_COL = {
    "player_year": "Year", "team_year": "Year", "league_year": "Year",
    "player_week": "Year", "team_week": "Year", "league_week": "Year",
    "picks": "Year", "trades": "Season", "transactions": "Season",
}

# A few human-readable identifying columns per sheet, for the diff report only.
ID_COLS = {
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

# Columns whose COMPLETED-SEASON values legitimately move on every rebuild (link
# indexes, league-relative percentiles, present-day rolling windows), so a change
# there must not read as a historical-immutability break. The classifier is
# shared with the digest (which uses it to avoid emailing a fake all-time move) —
# see lib/lotg_support/volatile_columns.py for the full rationale and F1 basis.
from lotg_support.volatile_columns import (  # noqa: E402
    is_volatile_column, _VOLATILE_SUBSTRINGS, _VOLATILE_EXACT,
)
from lotg_support.nflverse_drift import Drift, diff_nflverse_cache  # noqa: E402


# ---------------------------------------------------------------------------
# NFLverse attribution
# ---------------------------------------------------------------------------
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

    Only CHANGED rows are attributable. Roster membership comes from Sleeper, so
    an NFLverse revision can never add or remove one of our rows; those stay
    flagged.
    """

    def __init__(self, drift: Drift, cur: Dict[str, pd.DataFrame]) -> None:
        self.active = bool(drift and drift.player_seasons)
        self.player_weeks = set(drift.player_weeks) if drift else set()
        self.player_seasons = set(drift.player_seasons) if drift else set()
        self.team_weeks: Set[tuple] = set()
        self.team_years: Set[tuple] = set()
        self.league_weeks: Set[tuple] = set()
        self.league_years: Set[str] = set()
        self.names_by_year: Dict[str, Set[str]] = defaultdict(set)
        # String-normalised copies: our exports are read as str, NFLverse as int.
        self._pw_keys: Set[tuple] = {(p, str(y), str(w)) for p, y, w in self.player_weeks}
        self._py_keys: Set[tuple] = {(p, str(y)) for p, y in self.player_seasons}
        if not self.active:
            return
        for nm, yr in self.player_seasons:
            self.names_by_year[str(yr)].add(nm)
        self._index_rosters(cur.get("player_week"))

    def _index_rosters(self, pw: Optional[pd.DataFrame]) -> None:
        if pw is None or pw.empty:
            return
        if not {"Player", "Team", "Year", "Week"}.issubset(pw.columns):
            return
        for r in pw[["Player", "Team", "Year", "Week"]].itertuples(index=False):
            p, t, y, w = str(r.Player), str(r.Team), str(r.Year), str(r.Week)
            if (p, y, w) in self._pw_keys:
                self.team_weeks.add((t, y, w))
                self.league_weeks.add((y, w))
            if (p, y) in self._py_keys:
                self.team_years.add((t, y))
                self.league_years.add(y)

    def _mentions(self, text: str, year: str) -> bool:
        names = self.names_by_year.get(str(year))
        if not names or not text:
            return False
        return any(nm in text for nm in names)

    def covers(self, sheet: str, idcols: List[str], key: tuple,
               row: Dict[str, str]) -> bool:
        if not self.active:
            return False
        kv = dict(zip(idcols, key))
        yr = str(kv.get("Year") or row.get("Year") or row.get("Season") or "")
        if sheet == "player_week":
            return (kv.get("Player"), yr, str(kv.get("Week"))) in self._pw_keys
        if sheet == "player_year":
            return (kv.get("Player"), yr) in self._py_keys
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
    audit_nflverse(drift, attributed, rep)
    audit_schema(cur, rep)
    audit_build_log(current_dir / "raw", season, rep)
    return rep


# ---------------------------------------------------------------------------
# NFLverse upstream drift (informational unless significant)
# ---------------------------------------------------------------------------
def audit_nflverse(drift: Drift, attributed_rows: int, rep: Report) -> None:
    """Say what NFLverse changed. Upstream back-correcting a completed season is
    their data moving, not our build failing to reproduce it, so this is a note
    — until it is structural (rows / columns / files appearing or vanishing) or
    it has moved more of our exports than the threshold, at which point it is a
    flag and someone should look."""
    rep.head("NFLverse upstream drift")
    reason = drift.is_significant(attributed_rows) if drift.compared else None
    line = drift.summary()
    if attributed_rows:
        line += (f" That accounts for {attributed_rows} changed past-season row(s) "
                 "in our exports, which Part 1 therefore did not flag.")
    if reason:
        rep.flag(f"{line} Significant: {reason}.")
    else:
        rep.note(line)
    for d in drift.detail_lines():
        rep.raw(f"    - {d}")


# ---------------------------------------------------------------------------
# Part 1 — unexpected diffs (completed-season immutability)
# ---------------------------------------------------------------------------
def _past_rows(df: pd.DataFrame, season_col: str, current_season: int) -> pd.DataFrame:
    if df.empty or season_col not in df.columns:
        return df.iloc[0:0]
    yrs = pd.to_numeric(df[season_col], errors="coerce")
    return df[yrs < current_season]


def _row_key(row: pd.Series, cols: List[str]) -> str:
    return " | ".join(f"{c}={row.get(c, '')}" for c in cols if c in row.index)


def _key_text(idcols: Sequence[str], key: tuple) -> str:
    return " | ".join(f"{c}={v}" for c, v in zip(idcols, key)) or "(row)"


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
        # No identifying columns to pair on — fall back to reporting both sides.
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
    rep.head("Part 1 — unexpected diffs (completed-season immutability)")
    if not base or all(df.empty for df in base.values()):
        rep.note("No baseline exports supplied — skipping the historical diff "
                 "(first run, or the workflow couldn't materialise a prior version).")
        return 0
    if current_season is None:
        rep.note("No season detected in the current exports — skipping diff.")
        return 0
    rep.note(f"In-progress season = **{current_season}** "
             f"(rows for {current_season} are exempt; earlier seasons must be frozen).")

    any_change = False
    flagged_any = False
    skipped_total = 0
    attributed: Dict[str, int] = {}
    attributed_cols: Counter = Counter()
    for name, season_col in SEASON_COL.items():
        c, b = cur.get(name), base.get(name)
        if c is None or b is None or c.empty or b.empty:
            continue
        shared = [col for col in b.columns if col in c.columns]
        # Drop the columns that legitimately drift between builds (link-index
        # references, percentiles, league-baseline stats) — comparing them would
        # flag ~2k historical rows every week. The season column is kept so the
        # row still identifies itself.
        volatile = [col for col in shared
                    if col != season_col and is_volatile_column(col)]
        skipped_total += len(volatile)
        shared = [col for col in shared if col not in volatile]
        if not shared:
            continue
        cp = _past_rows(c, season_col, current_season)[shared]
        bp = _past_rows(b, season_col, current_season)[shared]
        if cp.empty and bp.empty:
            continue
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

        # Peel off the rows an NFLverse revision accounts for. Upstream
        # back-correcting a completed season is not our build failing to
        # reproduce, so those rows are counted and their moved columns reported
        # under the NFLverse section — but they don't fail the run.
        if attrib is not None and attrib.active:
            kept, taken = [], []
            for item in changed:
                k, deltas, row_tup = item
                row = dict(zip(shared, row_tup))
                (taken if attrib.covers(name, idcols, k, row) else kept).append(item)
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
        rep.flag(f"**{name}**: {parts} past-season row(s) — "
                 "historical data is not supposed to change.")

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
    if skipped_total:
        rep.note(f"{skipped_total} build-volatile column(s) across the sheets are "
                 "exempt from this check (link-index references, O-Score / skill / "
                 "Luck / Hardship baselines, tenure & forward-looking values) — "
                 "they legitimately move on every rebuild.")
    total_attributed = sum(attributed.values())
    rep.attributed_sheets = dict(sorted(attributed.items(), key=lambda kv: -kv[1]))
    rep.attributed_columns = attributed_cols.most_common(_MAX_SUMMARY_COLS)
    if total_attributed:
        sheets = ", ".join(f"{k} ({v})" for k, v in rep.attributed_sheets.items())
        cols = ", ".join(f"{c} ({n})" for c, n in attributed_cols.most_common(6))
        rep.note(f"{total_attributed} past-season row(s) moved because NFLverse "
                 f"revised the data underneath them — not flagged. {sheets}."
                 + (f" Columns: {cols}." if cols else ""))
    if not any_change:
        rep.ok("No completed-season row changed since the previous build.")
    elif not flagged_any:
        rep.ok("No completed-season row changed beyond what NFLverse revised upstream.")
    return total_attributed


# ---------------------------------------------------------------------------
# Part 2 — schema breaks
# ---------------------------------------------------------------------------
def current_schema(cur: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
    return {name: list(df.columns) for name, df in cur.items() if not df.empty}


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
        elif have[:len(cols)] != cols:
            rep.flag(f"**{name}**: columns reordered vs the pinned baseline.")
            clean = False
        if extra:
            rep.note(f"**{name}**: {len(extra)} new column(s) — "
                     f"{', '.join(extra[:8])}{' …' if len(extra) > 8 else ''} "
                     "(re-pin with --update-schema if intended).")
    for name in cur:
        if name not in baseline and not cur[name].empty:
            rep.note(f"**{name}**: sheet not in the baseline (new sheet?).")
    if clean:
        rep.ok("Every pinned sheet has all its expected columns, in order.")


def write_schema_baseline(cur: Dict[str, pd.DataFrame]) -> None:
    schema = current_schema(cur)
    _SCHEMA_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    _SCHEMA_BASELINE.write_text(json.dumps(schema, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Part 3 — build errors not attributable to the in-progress season
# ---------------------------------------------------------------------------
# Transient upstream blips that don't indicate a broken build — the cached
# baseline covers them and they self-heal next run.
_TRANSIENT = re.compile(
    r"tunnel connection failed|urlerror|connectionerror|timed out|timeout|"
    r"403 forbidden|404 client error|429|502|503|max retries|temporarily unavailable",
    re.IGNORECASE)
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
    rep.head("Part 3 — build errors (not current-season / transient)")
    debug = logs_dir / "build_debug.log"
    if not debug.exists():
        rep.note(f"No build log at {debug} — nothing to scan.")
    else:
        seg = _last_build_segment(debug.read_text(errors="replace"))
        season_tok = str(current_season) if current_season else None
        flagged, transient, current = [], 0, 0
        for ln in seg.splitlines():
            if not _ERROR_LINE.search(ln):
                continue
            if _TRANSIENT.search(ln):
                transient += 1
                continue
            if season_tok and season_tok in ln:
                current += 1  # preseason / in-progress-season noise (e.g. injuries_2026 404)
                continue
            flagged.append(ln.strip())
        # The build's own data-quality summary is the authoritative error count.
        m = re.findall(r"data-quality sanity:\s*(\d+)\s*ERROR,\s*(\d+)\s*WARN", seg)
        if m:
            errs, warns = (int(x) for x in m[-1])
            (rep.flag if errs else rep.ok)(
                f"build data-quality sanity: {errs} ERROR, {warns} WARN.")
        if flagged:
            rep.flag(f"{len(flagged)} non-transient / non-current-season ERROR line(s):")
            for ln in flagged[:_MAX_REPORT]:
                rep.raw(f"    - {ln}")
        else:
            rep.ok("No non-transient, non-current-season ERROR lines in the last build.")
        if transient or current:
            rep.note(f"ignored {transient} transient-network + {current} "
                     f"current-season ({season_tok}) log line(s).")

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
