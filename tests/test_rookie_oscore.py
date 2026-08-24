"""A current-class rookie shouldn't carry an O-Score before he has played.

Until a rookie's first game his four O-Score components collapse to his draft-slot
KTC percentile — a grade off nothing on the field, which the weekly digest then
reports as a real bottom-five O-Score (the 2026 Fernando Mendoza / Ty Simpson
lines in the run-474 test email). `_withhold_unplayed_rookie_oscore` blanks it
until "Avg PPG on team" is a real number (after week 1 of his first season),
scoped to the current draft class so no past rookie is re-graded.

Run: PYTHONPATH=src:lib python tests/test_rookie_oscore.py
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("lotg", _ROOT / "src" / "lotg.py")
lotg = importlib.util.module_from_spec(_spec)
sys.modules["lotg"] = lotg          # dataclasses resolve types via sys.modules
_spec.loader.exec_module(lotg)


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _frame():
    # Current-class rookies "with no game yet" take TWO build-time shapes: NaN
    # (never rostered for an NFL week) and 0.0 (already rostered in the preseason
    # but no game — the shape the PR #410 audit caught an .isna()-only gate
    # missing). Plus a played rookie, a past rookie, and a startup pick.
    return pd.DataFrame({
        "Year": ["2026", "2026", "2026", "2025", "startup"],
        "Player Picked": ["Rook NaN", "Rook Zero", "Rook Played", "Old Rook", "Vet"],
        "Avg PPG on team": [float("nan"), 0.0, 12.0, float("nan"), 20.0],
        "O-Score": [6.9, 7.5, 55.0, 4.8, 71.0],
    })


def check_withhold_unplayed_rookie_oscore():
    df = _frame()
    non_rookie = df["Year"].astype(str).str.contains("startup|vet", case=False)
    lotg._withhold_unplayed_rookie_oscore(df, non_rookie, current_season=2026)
    o = dict(zip(df["Player Picked"], df["O-Score"]))
    ok = _ok("current-class rookie, no game (NaN AvgPPG) -> blanked",
             math.isnan(o["Rook NaN"]), o)
    ok &= _ok("current-class rookie, no game (0.0 AvgPPG at build) -> blanked",
              math.isnan(o["Rook Zero"]), o)
    ok &= _ok("current-class rookie who HAS played -> kept", o["Rook Played"] == 55.0, o)
    ok &= _ok("a PAST rookie is not re-graded (week 1 long passed) -> kept",
              o["Old Rook"] == 4.8, o)
    ok &= _ok("a startup/vet pick is untouched", o["Vet"] == 71.0, o)
    return ok


def check_is_a_safe_noop_when_columns_missing():
    # No "Avg PPG on team" column: must not raise, must change nothing.
    df = pd.DataFrame({"Year": ["2026"], "O-Score": [6.9]})
    nr = pd.Series([False])
    lotg._withhold_unplayed_rookie_oscore(df, nr, current_season=2026)
    ok = _ok("missing columns -> no-op, no raise", df["O-Score"].iloc[0] == 6.9)
    # Missing season / mask -> no-op.
    df2 = _frame()
    lotg._withhold_unplayed_rookie_oscore(df2, None, current_season=2026)
    lotg._withhold_unplayed_rookie_oscore(df2, df2["Year"].str.contains("x"), current_season=None)
    ok &= _ok("missing mask or season -> no-op",
              df2["O-Score"].tolist() == [6.9, 7.5, 55.0, 4.8, 71.0])
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_withhold_unplayed_rookie_oscore,
              check_is_a_safe_noop_when_columns_missing):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_rookie_oscore():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
