"""lotg_support.workbook_comments: the build workbook's asset-history hover
comments, read from the .xlsx parts without openpyxl.

A small workbook written with openpyxl (skips without it) must come back with
each column-A comment on its data row, the header tooltip skipped, comments
outside column A ignored and column A's value alongside.

Run: python tests/test_workbook_comments.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import workbook_comments as WC  # noqa: E402


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def test_reads_column_a_histories_by_row():
    try:
        from openpyxl import Workbook
        from openpyxl.comments import Comment
    except ImportError:
        return _skip("openpyxl not installed")
    wb = Workbook()
    ws = wb.active
    ws.title = "formulas"
    pa = wb.create_sheet("player_all_time")
    pa.append(["Player", "Points"])
    pa.append(["A.J. Brown", 10])
    pa.append(["Josh Allen", 20])
    pa.append(["No Note", 1])
    pa["A1"].comment = Comment("header tooltip", "x")
    pa["A2"].comment = Comment("2020 Draft: drafted\n2021-01-01: traded to X (X got A.J. Brown; sent y)", "LOTG")
    pa["A3"].comment = Comment("2024-01-01: added by T (free agent)", "LOTG")
    pa["B4"].comment = Comment("not column A", "x")
    rp = wb.create_sheet("rookie_picks")
    rp.append(["Year", "Number"])
    rp.append([2021, "1.01"])
    rp["A2"].comment = Comment("2021 1.01 — originally T's pick", "LOTG")
    path = Path(tempfile.mkdtemp()) / "wb.xlsx"
    wb.save(path)
    h = WC.histories(path)
    assert [(r, a) for r, a, _t in h["player_all_time"]] == [(0, "A.J. Brown"), (1, "Josh Allen")]
    assert h["player_all_time"][0][2].startswith("2020 Draft") and "\n" in h["player_all_time"][0][2]
    assert h["rookie_picks"] == [(0, "2021", "2021 1.01 — originally T's pick")]
    assert "non_rookie_picks" not in h


def test_no_workbook_is_none():
    assert WC.histories(Path(tempfile.mkdtemp()) / "missing.xlsx") is None


TESTS = [test_reads_column_a_histories_by_row, test_no_workbook_is_none]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall workbook-comment checks passed")
