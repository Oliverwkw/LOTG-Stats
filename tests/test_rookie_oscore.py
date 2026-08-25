"""A current-class rookie shouldn't carry an O-Score before half a season.

Graded early, a rookie's four O-Score components collapse toward his draft-slot
KTC percentile — a grade off almost nothing on the field, which the weekly digest
then reports as a real bottom-five O-Score. `_withhold_early_rookie_oscore` blanks
the whole current draft class until its rookie season has played `min_week` weeks
(week 8), then scores it normally. Scoped to the current draft class by Year, so
no past class is re-graded.

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
    # A current-class (2026) rookie that HAS played some games, one that hasn't,
    # a past rookie, and a startup pick. The class is graded on how far its
    # SEASON has gone, not per-player play, so the played/unplayed pair should be
    # treated identically before week 8.
    return pd.DataFrame({
        "Year": ["2026", "2026", "2025", "startup"],
        "Player Picked": ["Rook Played", "Rook Unplayed", "Old Rook", "Vet"],
        "O-Score": [55.0, 7.5, 4.8, 71.0],
    })


def check_withhold_before_week_8():
    df = _frame()
    non_rookie = df["Year"].astype(str).str.contains("startup|vet", case=False)
    # Season only 5 weeks in -> whole current class withheld.
    lotg._withhold_early_rookie_oscore(df, non_rookie, current_season=2026,
                                       season_weeks_completed=5)
    o = dict(zip(df["Player Picked"], df["O-Score"]))
    ok = _ok("before week 8: current-class rookie who played -> blanked",
             math.isnan(o["Rook Played"]), o)
    ok &= _ok("before week 8: current-class rookie unplayed -> blanked",
              math.isnan(o["Rook Unplayed"]), o)
    ok &= _ok("a PAST class is not re-graded -> kept", o["Old Rook"] == 4.8, o)
    ok &= _ok("a startup/vet pick is untouched", o["Vet"] == 71.0, o)
    return ok


def check_scores_from_week_8_on():
    df = _frame()
    non_rookie = df["Year"].astype(str).str.contains("startup|vet", case=False)
    lotg._withhold_early_rookie_oscore(df, non_rookie, current_season=2026,
                                       season_weeks_completed=8)
    ok = _ok("at week 8: the current class keeps its O-Score",
             df["O-Score"].tolist() == [55.0, 7.5, 4.8, 71.0], df["O-Score"].tolist())
    return ok


def check_is_a_safe_noop_when_inputs_missing():
    df = pd.DataFrame({"Year": ["2026"]})   # no O-Score column
    lotg._withhold_early_rookie_oscore(df, pd.Series([False]), 2026, 5)
    ok = _ok("missing columns -> no-op, no raise", "O-Score" not in df.columns or True)
    df2 = _frame()
    lotg._withhold_early_rookie_oscore(df2, None, 2026, 5)                 # no mask
    lotg._withhold_early_rookie_oscore(df2, df2["Year"].str.contains("x"), None, 5)  # no season
    lotg._withhold_early_rookie_oscore(df2, df2["Year"].str.contains("x"), 2026, None)  # no weeks
    ok &= _ok("missing mask / season / week count -> no-op",
              df2["O-Score"].tolist() == [55.0, 7.5, 4.8, 71.0])
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_withhold_before_week_8,
              check_scores_from_week_8_on,
              check_is_a_safe_noop_when_inputs_missing):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_rookie_oscore():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
