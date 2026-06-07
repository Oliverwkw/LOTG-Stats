"""Phase 11A coverage guard: every NON-OBVIOUS output column must be documented
in the Formulas sheet (src/formulas.py `_ROWS`).

Reuses the SAME coverage logic the build uses (formulas.undocumented_columns),
so the test and the build-time warning can't disagree. An entry documents a
column when its name appears (case/space-insensitive) as a "/"-token of `Stat`
or in the entry's internal `Columns` list; pure identity/label columns and
generated per-opponent/pick columns are exempt.

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


def test_every_nonobvious_column_is_documented():
    uncovered = find_uncovered()
    assert not uncovered, (
        f"{len(uncovered)} output column(s) lack a Formulas-sheet entry:\n  "
        + "\n  ".join(uncovered)
    )


if __name__ == "__main__":
    u = find_uncovered()
    if u:
        print(f"{len(u)} undocumented columns:")
        for c in u:
            print(f"   {c}")
        sys.exit(1)
    print("All non-obvious columns documented.")
