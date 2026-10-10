"""raw/ktc_provenance.csv is written in a fixed order.

The build's KTC lookups arrive in whatever order its callers walk their assets
(some iterate sets, whose order follows each process's hash seed), so identical
builds dumped the same rows shuffled (main runs 698 / 699 / 700). The dump is
now sorted (`ktc.provenance_frame`): any arrival order gives the same file, and
no row is dropped or merged — the weekly audit reads which assets were carried.

Run: PYTHONPATH=src:lib python tests/test_ktc_provenance.py
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import ktc as K  # noqa: E402

_ROWS = [
    ("6794", "2024-10-01", "2024-10-01", "mirror", 4821.0),
    ("2026 1.??", "2024-10-01", "2024-10-01", "mirror", 5120.5),
    ("4984", "2026-09-09", "2026-08-15", "trailing-edge-carry", 485.0),
    ("4984", "2026-09-09", "2026-08-15", "trailing-edge-carry", 485.0),   # a repeated lookup stays twice
    ("1426", "2020-11-02", None, "no-history", None),
    ("1426", "2023-03-01", "2023-03-01", "off-rolls", 0.0),
    ("2021 4.??", "2020-10-29", "2020-10-01", "backfill-carry", float("nan")),
]


def _frame_for(rows):
    saved = list(K._PROVENANCE)
    try:
        K.reset_provenance()
        K._PROVENANCE.extend(rows)
        return K.provenance_frame()
    finally:
        K.reset_provenance()
        K._PROVENANCE.extend(saved)


def test_any_arrival_order_writes_the_same_file():
    want = _frame_for(_ROWS).to_csv(index=False)
    rng = random.Random(7)
    for _ in range(20):
        rows = list(_ROWS)
        rng.shuffle(rows)
        assert _frame_for(rows).to_csv(index=False) == want


def test_every_row_is_kept_and_the_columns_are_the_audits():
    df = _frame_for(_ROWS)
    assert list(df.columns) == ["asset", "target_date", "quote_date_used", "source", "value"]
    assert len(df) == len(_ROWS)
    # The very rows the unsorted frame held (as the build used to write them).
    import pandas as pd
    before = pd.DataFrame(_ROWS, columns=K.PROVENANCE_COLUMNS)
    rows = lambda d: Counter(tuple(str(v) for v in r) for r in d.itertuples(index=False, name=None))
    assert rows(df) == rows(before)


if __name__ == "__main__":
    test_any_arrival_order_writes_the_same_file()
    test_every_row_is_kept_and_the_columns_are_the_audits()
    print("ok")
