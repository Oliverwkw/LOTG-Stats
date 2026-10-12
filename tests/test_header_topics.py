"""Every sheet reads in topic blocks [per user, 2026-10-12: "organized blocks
for readability, not colors for organization. No color repeated in more than
one block per sheet, most columns should be part of big blocks organized by
topic"].

The plan CSV lists each sheet's columns grouped by topic, and the workbook
colours each header by `lotg._header_topics`. So on every sheet — in the plan
and in what the build wrote — each topic must be ONE contiguous run, and every
topic must have a palette colour. The synthetic cases pin the topic rules the
grouping leans on.

Run: python tests/test_header_topics.py
"""
from __future__ import annotations

import itertools
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

import lotg  # noqa: E402
from lotg_support.plan import load_plan_catalog  # noqa: E402

_EXPORTS = _ROOT / "exports"
_PLAN = _ROOT / "plan" / "LOTG Plan - Sheet1.csv"


def _split_blocks(name, cols):
    """Problems with one sheet's header row: a topic in two places, or a topic
    with no colour."""
    topics = lotg._header_topics(cols)
    runs = [k for k, _ in itertools.groupby(topics)]
    twice = sorted(t for t, n in Counter(runs).items() if n > 1)
    out = []
    if twice:
        where = {t: [cols[i] for i, x in enumerate(topics) if x == t][:4] for t in twice}
        out.append(f"{name}: topic(s) in more than one block: {where}")
    uncoloured = set(topics) - set(lotg._TOPIC_FILL)
    if uncoloured:
        out.append(f"{name}: no colour for {sorted(uncoloured)}")
    return out


def test_unknown_names_take_their_blocks_topic():
    cols = ["Team", "Year", "PF", "Some brand-new column", "Points against"]
    assert lotg._header_topics(cols) == ["Identity", "Identity", "Scoring", "Scoring", "Scoring"]


def test_topic_rules_the_grouping_leans_on():
    t = lotg._col_topic
    assert {t(f"Start/sit miss ({x} Projection)") for x in ("Sleeper", "Claude", "Enhanced")} == {"Lineup"}
    assert t("Reference player name") == "Lineup"
    assert {t(c) for c in ("Sleeper Projection", "Points above Claude Projection",
                           "Overachiever (Enhanced Projection) streak",
                           "Times as Underachiever (Sleeper Projection)")} == {"Projections"}
    assert {t(c) for c in ("Pre-week Win % (Sleeper Projection)",
                           "Win % overcome entering SNF (Claude Projection)")} == {"Win odds"}
    assert {t(c) for c in ("Margin entering SNF", "Points overcome (entering Monday)",
                           "Choke size (Enhanced Projection)")} == {"Comebacks"}
    assert t("Hardship (Claude Projections)") == "Hardship & Luck"
    # "age" is a word, not a substring: "Average …", "free agency" are not ages.
    assert t("Average weekly starter turnover") == "Activity"
    assert t("Number of free agency adds") == "Activity"
    assert t("Player average age") == "Roster"
    assert t("Team's traded with 1") == "Identity" and t("Team's traded with 3") == "Partners"


def test_the_plan_lists_every_sheet_in_blocks():
    problems = []
    for sheet, cols in load_plan_catalog(_PLAN).items():
        if sheet != "Formulas":
            problems += _split_blocks(sheet, cols)
    assert not problems, "\n".join(problems)


def test_every_exported_sheet_is_in_blocks():
    """What the build wrote, including the columns it adds at run time (the
    per-opponent vs columns, extra trade partners)."""
    if not _EXPORTS.exists():
        print("  SKIP — no exports")
        return
    problems = []
    for path in sorted(_EXPORTS.glob("*.csv")):
        if path.stem != "formulas":
            problems += _split_blocks(path.stem, list(pd.read_csv(path, nrows=0).columns))
    assert not problems, "\n".join(problems)


TESTS = [
    test_unknown_names_take_their_blocks_topic,
    test_topic_rules_the_grouping_leans_on,
    test_the_plan_lists_every_sheet_in_blocks,
    test_every_exported_sheet_is_in_blocks,
]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall header-topic checks passed")
