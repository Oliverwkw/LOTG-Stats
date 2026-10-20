"""A bench player on bye / injured / suspended was graded as a start/sit miss.

player_week measured every bench player against the week's worst starter, even
one who could not have played. On 5-game averages that made a star's bye week a
missed start: Jahmyr Gibbs, benched for Detroit's 2026 week 6 bye, went to
5th-highest ever on "Start/sit miss (5-game avg)" (+20.34) and on its cuff twin
in the 2026-10-20 digest, and such rows held 8 of that column's all-time top
10. On the projections (0 for a bye) they filled the bottom 10 instead.

Those rows now get no reference player, so every start/sit column is N/A on
them. A STARTER who could not play keeps his: starting him was a call.

Run: PYTHONPATH=src:lib python tests/test_unavailable_bench_startsit.py
"""
from __future__ import annotations

import importlib.util
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

_EXPORTS = _ROOT / "exports"
_FLAGS = ("Bye?", "Injury?", "Suspension?")
_COLS = ("Reference player name", "Difference from worst benchable starter (if bench)",
         "Start/sit miss (5-game avg)", "Start/sit miss (5-game avg) adjusted by position",
         "Cuff adjusted difference", "Cuff adjusted difference adjusted by position",
         "Start/sit miss (Sleeper Projection)", "Start/sit miss (Claude Projection)",
         "Start/sit miss (Enhanced Projection)")


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_reference_pid():
    ref = lotg._startsit_reference_pid
    ok = _ok("an available bench player is measured against the worst starter",
             ref(False, False, "B", "W") == "W")
    ok &= _ok("an unavailable bench player gets no reference", ref(False, True, "B", "W") is None)
    ok &= _ok("an available starter is measured against the best bench player",
              ref(True, False, "B", "W") == "B")
    ok &= _ok("an unavailable starter still is (starting him was a call)",
              ref(True, True, "B", "W") == "B")
    ok &= _ok("an empty starting slot stays a bench player's reference",
              ref(False, False, "B", "0") == "0")
    ok &= _ok("no bench / no starters is no reference",
              ref(True, False, None, "W") is None and ref(False, False, "B", None) is None)
    return ok


def check_exports():
    path = _EXPORTS / "player_week.csv"
    if not path.exists():
        print("  [SKIP] exports/player_week.csv absent")
        return True
    pw = pd.read_csv(path, dtype=str, keep_default_na=False)
    done = pw[pd.to_numeric(pw["Year"], errors="coerce") <= 2025]
    out = pd.Series(False, index=done.index)
    for c in _FLAGS:
        out |= done[c].str.strip().str.lower().isin(("true", "1"))
    bench_out = done[out & done["Starter/Bench"].eq("Bench")]
    ok = _ok("completed seasons have unavailable bench rows to check", len(bench_out) > 0,
             f"{len(bench_out)} rows")
    for c in _COLS:
        if c not in done.columns:
            continue
        n = int(bench_out[c].str.strip().ne("").sum())
        ok &= _ok(f"'{c}' is N/A on them", n == 0, f"{n} filled")
    start_out = done[out & done["Starter/Bench"].eq("Starter")]
    ok &= _ok("a starter who could not play keeps his reference",
              start_out["Reference player name"].str.strip().ne("").all(), f"{len(start_out)} rows")
    return ok


def run_all():
    ok = True
    for fn in (check_reference_pid, check_exports):
        print(f"\n{fn.__name__}:")
        ok &= fn()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_unavailable_bench_startsit():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
