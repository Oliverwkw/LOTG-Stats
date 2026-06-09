"""Data-quality sanity checks over the exported CSVs.

`collect_findings(exports_dir)` returns a list of `Finding(severity, sheet, column,
detail)` for any value outside its plausible range. Shared by:
  - the build, which logs a one-line summary + each ERROR into build_debug.log
    (Phase 12 improvement #45), and
  - tests/test_sanity_ranges.py, which asserts there are no ERROR findings
    (improvement #43).

Checks are deliberately conservative (calibrated against a known-clean build) so
a finding is a real anomaly, not a false positive. Columns that legitimately go
negative (anything named change/difference/diff/net/minus) are skipped by the
count check; only no-data-or-real cells are considered (N/A / In Progress / blank
are dropped before range-testing).
"""
from __future__ import annotations

import math
import os
from collections import namedtuple
from pathlib import Path
from typing import List

import pandas as pd

Finding = namedtuple("Finding", ["severity", "sheet", "column", "detail"])

_SHEETS = [
    "player_week", "player_year", "player_all_time",
    "team_week", "team_year", "team_all_time",
    "league_week", "league_year", "league_all_time",
    "transactions", "trades", "picks",
]

# Columns that can legitimately be negative — never range-check them as counts.
_SIGNED_HINTS = ("change", "difference", "diff", "net", "minus", "delta", "margin",
                 "luck", "par", "above", "skill", "o-score", "score", "value")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.replace({"N/A": None, "In Progress": None, "": None, "nan": None}),
        errors="coerce",
    )


def _is_signed(col: str) -> bool:
    c = col.lower()
    return any(h in c for h in _SIGNED_HINTS)


def collect_findings(exports_dir) -> List[Finding]:
    d = Path(exports_dir)
    out: List[Finding] = []
    for sheet in _SHEETS:
        fp = d / f"{sheet}.csv"
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp, dtype=str, keep_default_na=False, low_memory=False)
        except Exception as e:  # pragma: no cover
            out.append(Finding("ERROR", sheet, "", f"unreadable: {e}"))
            continue
        for col in df.columns:
            cl = col.lower()
            vals = _num(df[col]).dropna()
            if vals.empty:
                continue

            # inf / NaN-as-number never belong in any numeric output column.
            if vals.apply(lambda x: isinstance(x, float) and math.isinf(x)).any():
                out.append(Finding("ERROR", sheet, col, "contains inf"))

            # Win % is a fraction in [0, 1] (exclude signed "… minus Win %").
            if ("win %" in cl or "win%" in cl) and not _is_signed(col):
                bad = vals[(vals < -1e-6) | (vals > 1 + 1e-6)]
                if not bad.empty:
                    out.append(Finding("ERROR", sheet, col,
                                       f"win% out of [0,1]: {len(bad)} cells, "
                                       f"range [{bad.min():.3f}, {bad.max():.3f}]"))

            # Counts ("Number of …") are non-negative.
            if cl.startswith("number of") and not _is_signed(col):
                bad = vals[vals < -1e-6]
                if not bad.empty:
                    out.append(Finding("ERROR", sheet, col,
                                       f"negative count: {len(bad)} cells, min {bad.min()}"))

            # Ages are plausible for an active fantasy roster.
            if cl == "age" or cl.endswith("age when drafted") or cl == "avg age":
                bad = vals[(vals < 18) | (vals > 55)]
                if not bad.empty:
                    out.append(Finding("WARN", sheet, col,
                                       f"implausible age: {len(bad)} cells, "
                                       f"range [{bad.min():.1f}, {bad.max():.1f}]"))

            # N/A-vs-0 consistency: a column that renders the literal "N/A" for
            # no-data AND parses as numeric elsewhere is a `_preserve_na` column;
            # a truly BLANK cell in it is an inconsistent no-data render (should
            # be "N/A" or a real 0).
            raw = df[col].astype(str).str.strip()
            if (raw == "N/A").any() and len(vals) > 0:
                n_blank = int((raw == "").sum())
                if n_blank:
                    out.append(Finding("WARN", sheet, col,
                                       f"N/A-vs-0: {n_blank} blank cells in a column "
                                       f"that elsewhere renders 'N/A'"))
    return out


def summarize(findings: List[Finding]) -> str:
    n_err = sum(1 for f in findings if f.severity == "ERROR")
    n_warn = sum(1 for f in findings if f.severity == "WARN")
    return f"data-quality sanity: {n_err} ERROR, {n_warn} WARN across {len(findings)} findings"


if __name__ == "__main__":
    import sys
    _dir = sys.argv[1] if len(sys.argv) > 1 else (Path(__file__).resolve().parents[2] / "exports")
    fs = collect_findings(_dir)
    print(summarize(fs))
    for f in fs:
        print(f"  {f.severity:5} {f.sheet}.{f.column}: {f.detail}")
    sys.exit(1 if any(f.severity == "ERROR" for f in fs) else 0)
