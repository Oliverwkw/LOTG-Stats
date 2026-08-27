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

Coverage runs columns -> entries. The REVERSE direction has its own guard below:
an entry naming a sheet that no longer exists is invisible to a coverage check,
so a sheet rename leaves stale `Sheet` fields behind silently. That is exactly
what the picks -> non_rookie_picks / rookie_picks split did to two entries.

Run directly (`python tests/test_formulas_coverage.py`) or via pytest.
"""
from __future__ import annotations

import importlib.util
import json
import re
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


def find_unknown_sheet_names():
    """[(Stat, bad_name)] for every Formulas entry whose `Sheet` field names a
    sheet the build does not write.

    The field is free text ("team_year / team_all_time", and occasionally a
    parenthetical or an aside), so only BARE snake_case tokens are checked —
    anything containing a space or punctuation is prose, not a sheet name. That
    keeps the guard silent on "all add/drop & trade counts" while still catching
    a retired name like `picks` sitting alone between two slashes.
    """
    formulas = _load_formulas()
    known = {s.lower() for s in formulas._OUTPUT_SHEETS}
    bad = []
    for e in formulas._ROWS:
        for part in re.split(r"[/;]", str(e.get("Sheet", ""))):
            # Drop a trailing aside: "team_year (Luck)" -> "team_year".
            tok = re.sub(r"\s*\(.*?\)\s*$", "", part).strip().lower()
            if not tok or not re.fullmatch(r"[a-z][a-z0-9_]*", tok):
                continue                      # prose, not a sheet name
            if tok not in known:
                bad.append((str(e.get("Stat", "?")), tok))
    return bad


def test_no_entry_names_a_sheet_that_does_not_exist():
    bad = find_unknown_sheet_names()
    assert not bad, (
        "Formulas entries name sheet(s) the build no longer writes "
        f"(known: {', '.join(sorted(_load_formulas()._OUTPUT_SHEETS))}):\n  "
        + "\n  ".join(f"{stat!r} -> {name!r}" for stat, name in bad)
    )


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
    stale_sheets = find_unknown_sheet_names()
    if stale_sheets:
        print(f"{len(stale_sheets)} entry/entries name a sheet that does not exist:")
        for stat, name in stale_sheets:
            print(f"   {stat!r} -> {name!r}")
        sys.exit(1)
    print("Every Formulas Sheet name resolves to a real output sheet.")
