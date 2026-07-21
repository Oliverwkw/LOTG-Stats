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
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
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

_MAX_REPORT = 25  # cap per-sheet diff lines so the report stays readable

# Columns whose COMPLETED-SEASON values legitimately move on every rebuild, so
# comparing them would flag thousands of rows every week and drown the real
# signal. Measured against a pure rebuild-to-rebuild export pair (runs 435->436,
# no code change in between): 1,956 past-season rows churn, essentially all of it
# from the columns below. See plan/AUDIT_PHASE14_3PART.md finding F1.
#
#   * "Link to ..."  — row-INDEX references into the transactions sheet. Every
#     new current-season event shifts the indices, rewriting every historical
#     row's pointer. Dominates the churn (842 + 795 + 563 + 550 rows on
#     transactions alone).
#   * O-Score / skill / Luck / Hardship — percentiles and league-wide baselines
#     computed over a universe that includes the in-progress season.
#   * Forward-looking or wall-clock values — a past row's "Date dropped/traded"
#     fills in when the asset finally moves; tenure counts real elapsed time;
#     future draft capital re-values as upcoming picks trade.
#
# Everything else stays under the immutability check, which is where a genuine
# historical regression would show up.
_VOLATILE_SUBSTRINGS = (
    "link to",
    "o-score",
    "skill",                # Drafting / Trading / Transaction skill
    "length of tenure",
    "trade impact score",
    "date dropped/traded",
)
_VOLATILE_EXACT = {
    "Luck", "Hardship", "Starter-adjusted Hardship", "Number of teams",
    "Tanking", "Future draft capital", "Startup draft players remaining",
}


def is_volatile_column(column: str) -> bool:
    """True if a completed-season value in this column is expected to drift
    between builds (so it must not count as a historical-immutability break)."""
    if column in _VOLATILE_EXACT:
        return True
    c = column.lower()
    return any(s in c for s in _VOLATILE_SUBSTRINGS)


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


def run_audit(current_dir: Path, baseline_dir: Optional[Path]) -> Report:
    """Run all three audit parts against a build directory (+ optional git
    baseline for Part 1) and return the populated Report."""
    cur = {n: _read(current_dir, n) for n in SHEETS}
    base = {n: _read(baseline_dir, n) for n in SHEETS} if baseline_dir else {}
    season = _current_season(cur)
    rep = Report()
    audit_diffs(cur, base, season, rep)
    audit_schema(cur, rep)
    audit_build_log(current_dir / "raw", season, rep)
    return rep


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


def audit_diffs(cur: Dict[str, pd.DataFrame], base: Dict[str, pd.DataFrame],
                current_season: Optional[int], rep: Report) -> None:
    rep.head("Part 1 — unexpected diffs (completed-season immutability)")
    if not base or all(df.empty for df in base.values()):
        rep.note("No baseline exports supplied — skipping the historical diff "
                 "(first run, or the workflow couldn't materialise a prior version).")
        return
    if current_season is None:
        rep.note("No season detected in the current exports — skipping diff.")
        return
    rep.note(f"In-progress season = **{current_season}** "
             f"(rows for {current_season} are exempt; earlier seasons must be frozen).")

    any_change = False
    skipped_total = 0
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
        # Full-row multiset diff: a changed historical row shows up as one
        # removed (old) + one added (new) tuple. No canonical key needed.
        cur_rows = pd.Series([tuple(r) for r in cp.itertuples(index=False, name=None)])
        base_rows = pd.Series([tuple(r) for r in bp.itertuples(index=False, name=None)])
        cur_counts = cur_rows.value_counts()
        base_counts = base_rows.value_counts()
        removed = base_counts.subtract(cur_counts, fill_value=0)
        removed = removed[removed > 0]
        added = cur_counts.subtract(base_counts, fill_value=0)
        added = added[added > 0]
        if removed.empty and added.empty:
            continue
        any_change = True
        idcols = [c2 for c2 in ID_COLS.get(name, []) if c2 in shared]
        rep.flag(f"**{name}**: {int(added.sum())} added / {int(removed.sum())} removed "
                 f"past-season row(s) — historical data is not supposed to change.")
        shown = 0
        for tup in list(removed.index)[:_MAX_REPORT]:
            row = pd.Series(dict(zip(shared, tup)))
            rep.raw(f"    - removed: {_row_key(row, idcols)}")
            shown += 1
        for tup in list(added.index)[:max(0, _MAX_REPORT - shown)]:
            row = pd.Series(dict(zip(shared, tup)))
            rep.raw(f"    - added:   {_row_key(row, idcols)}")
    if skipped_total:
        rep.note(f"{skipped_total} build-volatile column(s) across the sheets are "
                 "exempt from this check (link-index references, O-Score / skill / "
                 "Luck / Hardship baselines, tenure & forward-looking values) — "
                 "they legitimately move on every rebuild.")
    if not any_change:
        rep.ok("No completed-season row changed since the previous build.")


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
    args = ap.parse_args(argv)

    current_dir = Path(args.current)
    cur = {n: _read(current_dir, n) for n in SHEETS}

    if args.update_schema:
        write_schema_baseline(cur)
        print(f"[audit] schema baseline pinned -> {_SCHEMA_BASELINE}")
        return 0

    rep = run_audit(current_dir, Path(args.baseline) if args.baseline else None)

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
