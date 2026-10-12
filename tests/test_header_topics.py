"""Workbook header colours come in blocks [per user, 2026-10-12: "should be
blocks — no random floaters"].

`lotg._header_topics` turns a sheet's header row into one topic per column:
every sheet the build writes must come out with no single-column run, no grey
(Identity) column outside a block of real key columns, and only topics the
palette has a colour for. The synthetic cases pin the smoothing rules.

Run: python tests/test_header_topics.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

import lotg  # noqa: E402

_EXPORTS = _ROOT / "exports"


def _runs(topics):
    return [(k, len(list(g))) for k, g in itertools.groupby(topics)]


def test_unknown_names_take_their_blocks_colour():
    cols = ["Team", "Year", "PF", "Some brand-new column", "Points against"]
    assert lotg._header_topics(cols) == ["Identity", "Identity", "Scoring", "Scoring", "Scoring"]


def test_a_lone_column_joins_a_block():
    # Agreeing neighbours absorb it; otherwise the block before it does.
    assert lotg._header_topics(["Team", "PF", "Tanking", "Points against"])[2] == "Scoring"
    t = lotg._header_topics(["Team", "PF", "Points against", "Tanking", "Number of trades",
                             "Number of Add/Drops"])
    assert t[3] == "Scoring", t
    # ...but never into the leading key block: the column after it wins there.
    t = lotg._header_topics(["Player", "Team", "Points", "Player of the week?", "Captain?"])
    assert t[2] == "Awards", t


def test_projection_families_are_one_block_each():
    assert {lotg._col_topic(f"Start/sit miss ({x} Projection)") for x in ("Sleeper", "Claude", "Enhanced")} \
        == {"Lineup"}
    assert {lotg._col_topic(c) for c in ("Sleeper Projection", "Points above Claude Projection",
                                         "Overachiever (Enhanced Projection) streak",
                                         "Times as Underachiever (Sleeper Projection)")} == {"Projections"}
    assert {lotg._col_topic(c) for c in ("Pre-week Win % (Sleeper Projection)",
                                         "Win % overcome entering SNF (Claude Projection)")} == {"Win odds"}
    assert {lotg._col_topic(c) for c in ("Margin entering SNF", "Points overcome (entering Monday)",
                                         "Choke size (Enhanced Projection)")} == {"Comebacks"}
    assert lotg._col_topic("Hardship (Claude Projections)") == "Hardship & Luck"


def test_every_exported_sheet_is_in_blocks():
    if not _EXPORTS.exists():
        print("  SKIP — no exports")
        return
    sheets = [p for p in sorted(_EXPORTS.glob("*.csv")) if p.stem != "formulas"]
    assert sheets
    problems = []
    for path in sheets:
        cols = list(pd.read_csv(path, nrows=0).columns)
        topics = lotg._header_topics(cols)
        assert set(topics) <= set(lotg._TOPIC_FILL), (path.stem, set(topics) - set(lotg._TOPIC_FILL))
        runs = _runs(topics)
        i = 0
        for k, n in runs:
            if n == 1 and 0 < i < len(cols) - 1:
                problems.append(f"{path.stem}: lone {k} column {cols[i]!r}")
            if k == "Identity":
                odd = [c for c in cols[i:i + n] if lotg._col_topic(c, default=None) != "Identity"]
                if i and odd:
                    problems.append(f"{path.stem}: grey block holds non-key columns {odd[:3]}")
            i += n
    assert not problems, "\n".join(problems)


TESTS = [
    test_unknown_names_take_their_blocks_colour,
    test_a_lone_column_joins_a_block,
    test_projection_families_are_one_block_each,
    test_every_exported_sheet_is_in_blocks,
]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall header-topic checks passed")
