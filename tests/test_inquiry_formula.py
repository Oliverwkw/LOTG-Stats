"""`inquiry.formula` / `inquire.py formula`: a stat in words and as an equation.

Reads the definitions from src/ (formulas._ROWS + formula_equations), so it is
static and needs no exports; the `_formula_index` check (multi-sheet Formulas
rows indexed under every sheet they name) reads exports/formulas.csv and SKIPs
cleanly without it.

Run: python tests/test_inquiry_formula.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_FORMULAS = (_ROOT / "exports" / "formulas.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def test_formula_gives_words_and_equation():
    [doc] = Q.formula("Efficiency")
    assert "PF / Max PF" in doc.english
    assert doc.math.startswith("PF / MaxPF")
    syms = {s for _b, s, _m, _d in doc.glossary}
    assert {"PF(t,w)", "MaxPF(t,w)", "pts(p,w)"} <= syms


def test_formula_is_case_insensitive_and_lists_every_documenting_row():
    docs = Q.formula("player addition value")
    assert len(docs) >= 3                      # add_drops, the pick sheets, player_additions
    assert {d.sheets for d in docs} >= {"add_drops", "player_additions"}
    [one] = Q.formula("Player addition value", sheet="add_drops")
    assert one.sheets == "add_drops"


def test_model_rows_carry_their_math_in_cell():
    [wa] = Q.formula("Wins added")
    assert wa.math.startswith("WA(move)") and "LCF(t,w; OUT, IN) = " in wa.math
    # a symbol defined in-cell is not also listed as a glossary row
    assert "LCF(t,w; OUT, IN)" not in {s for _b, s, _m, _d in wa.glossary}


def test_unknown_column_suggests():
    try:
        Q.formula("Lukc")
    except KeyError as e:
        assert "Luck" in str(e)
    else:
        raise AssertionError("expected a KeyError")


def test_formula_keys_expand_multi_sheet_rows():
    keys = Q._formula_keys("Wins added", "add_drops / trades")
    assert keys == [("add_drops", "Wins added"), ("trades", "Wins added")]
    keys = Q._formula_keys("Luck (team_all_time: 'Avg yearly luck')",
                           "team_week / team_year (Luck); team_all_time (Avg yearly luck)")
    assert {s for s, _ in keys} == {"team_week", "team_year", "team_all_time"}


def test_describe_finds_multi_sheet_formulas():
    if not _HAVE_FORMULAS:
        return _skip("no exports/formulas.csv")
    idx = Q._formula_index(str(Q.repo_root()))
    assert idx.get(("trades", "Wins added"), ("", ""))[0].startswith("Games the move swung")
    assert idx.get(("add_drops", "Wins added"), ("", ""))[0].startswith("Games the move swung")


TESTS = [test_formula_gives_words_and_equation,
         test_formula_is_case_insensitive_and_lists_every_documenting_row,
         test_model_rows_carry_their_math_in_cell, test_unknown_column_suggests,
         test_formula_keys_expand_multi_sheet_rows, test_describe_finds_multi_sheet_formulas]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
