"""player_week 'Reference player name' printed "0" on 92 bench rows.

Sleeper writes "0" in a lineup's starters for a slot left empty. It scores 0, so
it is the worst starter a bench player is measured against, and the column fell
back to the raw id. It now reads "Empty slot" (2022 weeks 13, 16, 17 and 2025
week 9 in the committed history).

Run: PYTHONPATH=src:lib python tests/test_empty_slot_reference.py
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
_REF = "Reference player name"
_WORST = "Difference from worst benchable starter (if bench)"


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_reference_name():
    meta = {"4046": {"full_name": "Patrick Mahomes"}, "9999": {}}
    ok = _ok("an empty slot reads 'Empty slot'", lotg._reference_name("0", meta) == "Empty slot")
    ok &= _ok("a known player reads his name", lotg._reference_name("4046", meta) == "Patrick Mahomes")
    ok &= _ok("a nameless player keeps his id", lotg._reference_name("9999", meta) == "9999")
    ok &= _ok("no reference is None", lotg._reference_name(None, meta) is None)
    return ok


def check_exports_name_empty_slots():
    path = _EXPORTS / "player_week.csv"
    if not path.exists():
        print("  [SKIP] exports/player_week.csv absent")
        return True
    pw = pd.read_csv(path, dtype=str, keep_default_na=False)
    done = pw[pd.to_numeric(pw["Year"], errors="coerce") <= 2025]
    ok = _ok("no reference player is the raw empty-slot id", (done[_REF] == "0").sum() == 0,
             f"{(done[_REF] == '0').sum()} rows")
    empty = done[done[_REF] == "Empty slot"]
    ok &= _ok("only bench rows are measured against an empty slot",
              (empty["Starter/Bench"] == "Bench").all(), f"{len(empty)} rows")
    ok &= _ok("and the difference is the player's own points (the slot scored 0)",
              (pd.to_numeric(empty[_WORST]) == pd.to_numeric(empty["Points"])).all())
    return ok


def run_all():
    ok = True
    for fn in (check_reference_name, check_exports_name_empty_slots):
        print(f"\n{fn.__name__}:")
        ok &= fn()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_empty_slot_reference():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
