"""Phase 11A coverage guard: every NON-OBVIOUS output column must be documented
in the Formulas sheet (src/formulas.py `_ROWS`).

Reuses the SAME coverage logic the build uses (formulas.undocumented_columns),
so the test and the build-time warning can't disagree. An entry documents a
column when its name appears (case/space-insensitive) as a "/"-token of `Stat`
or in the entry's internal `Columns` list; pure identity/label columns and
generated per-opponent/pick columns are exempt.

The coverage check reads `plan/stats_catalog.json`, which is a hand-maintained
mirror of the real column source (`plan/LOTG Plan - Sheet1.csv`). A column added
to the plan but not the mirror is invisible to the guard above — so the mirror is
itself asserted in sync here, closing that blind spot.

Run directly (`python tests/test_formulas_coverage.py`) or via pytest.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_formulas():
    spec = importlib.util.spec_from_file_location("formulas", _ROOT / "src" / "formulas.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def find_uncovered():
    formulas = _load_formulas()
    catalog = json.loads((_ROOT / "plan" / "stats_catalog.json").read_text())
    return formulas.undocumented_columns(catalog)


def find_catalog_drift():
    """(sheet, missing_from_catalog, stale_in_catalog) for every sheet whose
    stats_catalog.json entry disagrees with the plan CSV the build actually
    exports from."""
    sys.path.insert(0, str(_ROOT / "lib"))
    from lotg_support.plan import load_plan_catalog  # noqa: E402

    plan = load_plan_catalog(_ROOT / "plan" / "LOTG Plan - Sheet1.csv")
    catalog = json.loads((_ROOT / "plan" / "stats_catalog.json").read_text())
    drift = []
    for sheet in sorted(set(plan) | set(catalog)):
        want, have = plan.get(sheet, []), catalog.get(sheet, [])
        missing = [c for c in want if c not in have]
        stale = [c for c in have if c not in want]
        if missing or stale:
            drift.append((sheet, missing, stale))
    return drift


def test_every_nonobvious_column_is_documented():
    uncovered = find_uncovered()
    assert not uncovered, (
        f"{len(uncovered)} output column(s) lack a Formulas-sheet entry:\n  "
        + "\n  ".join(uncovered)
    )


def test_stats_catalog_matches_the_plan():
    drift = find_catalog_drift()
    assert not drift, "plan/stats_catalog.json is out of sync with the plan CSV:\n  " + "\n  ".join(
        f"{sheet}: missing {missing}, stale {stale}" for sheet, missing, stale in drift
    )


if __name__ == "__main__":
    bad = 0
    for sheet, missing, stale in find_catalog_drift():
        bad += 1
        print(f"stats_catalog.json drift in {sheet}: missing {missing}, stale {stale}")
    if bad:
        sys.exit(1)
    print("stats_catalog.json in sync with the plan.")
    u = find_uncovered()
    if u:
        print(f"{len(u)} undocumented columns:")
        for c in u:
            print(f"   {c}")
        sys.exit(1)
    print("All non-obvious columns documented.")
