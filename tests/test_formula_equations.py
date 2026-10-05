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


def test_glossary_cross_references_resolve():
    f, e = _load("formulas"), _load("formula_equations")
    stats = {part.strip() for r in f._ROWS for part in [r["Stat"]] + r["Stat"].split("/")}
    bad = sorted({ref for _b, _s, m, d, _p in e.ENTRIES for ref in re.findall(r"⟨([^⟩]+)⟩", m + " " + d)
                  if ref not in stats and ref != "Stat"})
    assert not bad, f"glossary ⟨⟩ references to no Formulas row: {bad}"


def test_glossary_rows_are_the_5_use_symbols():
    """User rule: a symbol is a glossary row only if MIN_USES+ equations need
    it; every other symbol is defined in each cell that uses it."""
    e = _load("formula_equations")
    n = e.usage()
    always = {s for _b, s, _m, _d, p in e.ENTRIES if p is e.ALWAYS}
    rows = {s for _sheet, s, _m, _d in e.glossary()}
    assert all(n[s] >= e.MIN_USES for s in rows - always)
    assert not [s for s in n if n[s] >= e.MIN_USES and s not in rows]
    for key in e.EQUATIONS:
        cell = e.expanded(key)
        for sym in e._closure(e.EQUATIONS[key]) - set(rows):
            assert f"{sym} = " in cell, f"{key}: {sym} is neither a glossary row nor defined in-cell"


def test_output_leads_with_glossary_and_matches_plan():
    f, e = _load("formulas"), _load("formula_equations")
    out = f.build_output({})
    with open(_ROOT / "plan" / "LOTG Plan - Sheet1.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    i = rows[0].index("Formulas")
    plan_cols = [r[i] for r in rows[1:] if len(r) > i and r[i]]
    assert list(out.columns) == plan_cols
    n_gloss = len(e.glossary())
    assert set(out["Sheet"].iloc[:n_gloss]) <= {e.RAW_SHEET, e.OPS_SHEET, e.CTX_SHEET, e.MODEL_SHEET}
    assert len(out) == n_gloss + len(f._ROWS)
    assert out[e.COLUMN].astype(str).str.strip().ne("").all()


def test_in_cell_clauses_keep_symbol_case():
    """A where-clause lower-cases a leading sentence word ('The …' → 'the …')
    but never a symbol or name ('Kp = …', 'Sep 1 …', 'Bust ≤ …')."""
    e = _load("formula_equations")
    assert e._clause("The first league week.") == "the first league week"
    assert e._clause("Kp = S(t,w) ∖ OUT") == "Kp = S(t,w) ∖ OUT"
    assert e._clause("Sep 1 of y + 7(w − 1).") == "Sep 1 of y + 7(w − 1)"
    assert e._clause("Bust ≤ q10 < Lower") == "Bust ≤ q10 < Lower"
    for key in e.EQUATIONS:
        cell = e.expanded(key)
        assert "kp = S(t,w)" not in cell and "= sep 1" not in cell and "= bust ≤" not in cell, key


if __name__ == "__main__":
    for fn in (test_every_stat_has_one_equation, test_cross_references_resolve,
               test_glossary_cross_references_resolve, test_glossary_rows_are_the_5_use_symbols, test_in_cell_clauses_keep_symbol_case,
               test_output_leads_with_glossary_and_matches_plan):
        fn()
        print(f"ok  {fn.__name__}")
