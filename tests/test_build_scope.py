"""No helper name is defined twice in build_all's scope.

build_all is one very long function whose helpers are closures over its locals.
A helper's name is looked up when it is CALLED, not when the caller is defined,
so a second `def` of the same name later in build_all silently replaces the
first for every call that runs after it. Run 519 hit exactly this: add_drops'
two-argument `_player_games` was replaced by the picks block's one-argument one,
and player_additions — which calls add_drops' last-5 helper much later — failed
with a TypeError and exported an empty sheet. Three other pairs were the same
trap, one of them (`_draft_anchor`, date vs str) with different return types.

Run: python tests/test_build_scope.py
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "lotg.py"


def _helper_defs() -> dict:
    tree = ast.parse(_SRC.read_text())
    build_all = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_all")
    names = defaultdict(list)

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names[child.name].append(child.lineno)   # its body is its own scope
            elif not isinstance(child, (ast.Lambda, ast.ClassDef)):
                walk(child)
    walk(build_all)
    return names


def test_no_helper_name_is_defined_twice_in_build_all():
    names = _helper_defs()
    dup = {k: v for k, v in names.items() if len(v) > 1}
    assert not dup, f"helpers defined more than once in build_all (rename one): {dup}"
    assert len(names) > 50, len(names)      # the walk really found build_all's helpers


if __name__ == "__main__":
    test_no_helper_name_is_defined_twice_in_build_all()
    print("ok: no helper name is defined twice in build_all")
