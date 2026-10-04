"""The Formulas sheet's 'Equation (API stats only)' column (src/formula_equations.py).

Every documented stat carries exactly one equation, every ⟨Stat⟩ cross-reference
names a real Formulas row, and the emitted sheet leads with the glossary the
equations are written in. Static — needs no exports/.

Run directly (`python tests/test_formula_equations.py`) or via pytest.
"""
import csv
import importlib.util
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "src" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_stat_has_one_equation():
    f, e = _load("formulas"), _load("formula_equations")
    keys = [(r["Stat"], r["Sheet"]) for r in f._ROWS]
    assert len(keys) == len(set(keys)), "two Formulas rows share a (Stat, Sheet) key"
    missing = [k for k in keys if not str(e.EQUATIONS.get(k, "")).strip()]
    stale = sorted(set(e.EQUATIONS) - set(keys))
    assert not missing, f"Formulas rows with no equation: {missing}"
    assert not stale, f"equations for rows that no longer exist (renamed?): {stale}"


def test_cross_references_resolve():
    f, e = _load("formulas"), _load("formula_equations")
    stats = {part.strip() for r in f._ROWS for part in [r["Stat"]] + r["Stat"].split("/")}
    bad = sorted({(k, ref) for k, eq in e.EQUATIONS.items()
                  for ref in re.findall(r"⟨([^⟩]+)⟩", eq)
                  if ref not in stats and ref != "Stat"})
    assert not bad, f"⟨⟩ references to no Formulas row: {bad}"


def test_output_leads_with_glossary_and_matches_plan():
    f, e = _load("formulas"), _load("formula_equations")
    out = f.build_output({})
    with open(_ROOT / "plan" / "LOTG Plan - Sheet1.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    i = rows[0].index("Formulas")
    plan_cols = [r[i] for r in rows[1:] if len(r) > i and r[i]]
    assert list(out.columns) == plan_cols
    n_gloss = len(e.RAW_VARIABLES) + len(e.OPERATORS)
    assert set(out["Sheet"].iloc[:n_gloss]) == {e.RAW_SHEET, e.OPS_SHEET}
    assert len(out) == n_gloss + len(f._ROWS)
    assert out[e.COLUMN].astype(str).str.strip().ne("").all()


if __name__ == "__main__":
    for fn in (test_every_stat_has_one_equation, test_cross_references_resolve,
               test_output_leads_with_glossary_and_matches_plan):
        fn()
        print(f"ok  {fn.__name__}")
