"""2020's starters must be emitted in slot order, or their slot labels are junk.

`lotg.py` labels a starter's slot positionally: it zips a week's `starters`
array against the league's `roster_positions` and calls the first entry QB, the
next two RB1/RB2, and so on. Sleeper publishes `starters` in exactly that order,
so for 2021+ the zip is sound. The 2020 ESPN backfill emitted the week's entries
in whatever order ESPN's API returned them — alphabetical, in practice — so the
zip paired each label with an unrelated player: AceMatthew's week 8 filed Dalvin
Cook as the QB and Derek Carr as the TE, and 781 of the 1,071 starter rows that
can be compared disagreed with ESPN's own `lineupSlotId`.

`espn_2020._slot_ordered` sorts each week's starters into the template order
before they are emitted. Nothing else about 2020 changes: `players`, the roster
lists and `players_points` are all built from the unsorted list, so only the one
column that reads the array's ORDER moves.

Two facts the fix leans on, and which are asserted below rather than assumed:
every 2020 starter resolves to a Sleeper id (the emit drops any that does not,
which would shift every label after it), and the single short lineup of the
season — shmuel256 in week 16, seven men — is short at the TAIL, so a positional
zip cannot mislabel what it does have.

The raw-source checks run wherever `data/espn_2020_raw/` is present. The
export-based check needs a build that includes this fix, so it fails against
exports committed before the first post-merge build.

Run: python tests/test_2020_starter_slots.py
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import espn_2020 as E  # noqa: E402

_RAW = _ROOT / "data" / "espn_2020_raw"
_HAVE_RAW = (_RAW / "week_01.json").exists()
_PLAYER_WEEK = _ROOT / "exports" / "player_week.csv"

# The export's label for each slot of the template, in the order the build
# numbers them: QB, RB1, RB2, WR1, WR2, WR3, TE, FLX1, SFLX.
_LABEL_OF_SLOT = {"QB": ("QB",), "RB": ("RB1", "RB2"), "WR": ("WR1", "WR2", "WR3"),
                  "TE": ("TE",), "FLEX": ("FLX1",), "SUPER_FLEX": ("SFLX",)}


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


_loaded = None


def _espn():
    global _loaded
    if _loaded is None:
        raw = E.load_espn_2020(str(_RAW))
        _loaded = (raw, E.emit_sleeper_2020(raw))
    return _loaded


def _template():
    """The starter portion of `roster_positions`, e.g. QB RB RB WR WR WR TE ..."""
    _, blob = _espn()
    return [p for p in blob["league"]["roster_positions"] if p not in ("BN", "IR")]


# --------------------------------------------------------------------------- #
# the ordering rule itself (no data needed)
# --------------------------------------------------------------------------- #
def test_slot_order_is_stable_within_a_repeated_slot():
    # Two RBs in one lineup are RB1/RB2 by arrival order — the sort must not
    # reorder them, or a rerun could swap which is which for no reason.
    rbs = [{"lineup_slot": 2, "who": "first"}, {"lineup_slot": 2, "who": "second"}]
    lineup = [{"lineup_slot": 7, "who": "sflx"}] + rbs + [{"lineup_slot": 0, "who": "qb"}]
    got = [r["who"] for r in E._slot_ordered(lineup)]
    assert got == ["qb", "first", "second", "sflx"], got


def test_an_unknown_slot_sorts_last_rather_than_displacing_a_known_one():
    lineup = [{"lineup_slot": 16, "who": "dst"}, {"lineup_slot": 0, "who": "qb"}]
    assert [r["who"] for r in E._slot_ordered(lineup)] == ["qb", "dst"]


def test_the_template_order_has_one_source():
    # `_roster_positions` and `_slot_ordered` must agree, so both read
    # START_SLOT_ORDER. If someone reorders one, this catches the other.
    names = [name for _, name in E.START_SLOT_ORDER]
    assert names == ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"], names
    assert E.ESPN_START_SLOT_TO_SLEEPER == dict(E.START_SLOT_ORDER)


# --------------------------------------------------------------------------- #
# against the raw ESPN season
# --------------------------------------------------------------------------- #
def test_every_emitted_lineup_follows_the_roster_position_template():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    loaded, _ = _espn()
    template = _template()
    checked = 0
    for week, rows in loaded["weeks"].items():
        for row in rows:
            slots = [E.ESPN_START_SLOT_TO_SLEEPER.get(p["lineup_slot"])
                     for p in E._slot_ordered(row["starters"])]
            assert slots == template[:len(slots)], (week, row["manager"], slots)
            checked += 1
    assert checked == 128, checked  # 8 teams x 16 weeks


def test_every_starter_carries_a_sleeper_id():
    # The emit drops a starter with no id; one dropped mid-array would shift
    # every label after it, which is the bug this file exists for.
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    loaded, blob = _espn()
    missing = [(w, r["manager"], p["player"])
               for w, rows in loaded["weeks"].items() for r in rows
               for p in r["starters"] if not p.get("sleeper_id")]
    assert missing == [], missing
    for week, rows in blob["matchups_by_week"].items():
        for row in rows:
            assert len(row["starters"]) == len(set(row["starters"])), (week, row)


def test_the_one_short_lineup_is_short_at_the_tail():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    loaded, _ = _espn()
    template = _template()
    short = {(w, r["manager"]): [E.ESPN_START_SLOT_TO_SLEEPER.get(p["lineup_slot"])
                                 for p in E._slot_ordered(r["starters"])]
             for w, rows in loaded["weeks"].items() for r in rows
             if len(r["starters"]) != len(template)}
    assert list(short) == [(16, "shmuel256")], short
    assert short[(16, "shmuel256")] == template[:7]


def test_the_ordering_actually_moves_2020():
    # A guard that cannot fail is not a guard: confirm ESPN's own order really
    # does differ from the template, so the sort is doing work.
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    loaded, _ = _espn()
    moved = sum(1 for rows in loaded["weeks"].values() for r in rows
                if [p["espn_player_id"] for p in r["starters"]]
                != [p["espn_player_id"] for p in E._slot_ordered(r["starters"])])
    assert moved >= 100, moved


# --------------------------------------------------------------------------- #
# against the built sheet (needs a build carrying the fix)
# --------------------------------------------------------------------------- #
def test_the_sheet_labels_each_2020_starter_with_the_slot_espn_recorded():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    if not _PLAYER_WEEK.exists():
        return _skip("no exports/player_week.csv")
    loaded, _ = _espn()
    truth = {}
    for week, rows in loaded["weeks"].items():
        for row in rows:
            for entry in row["starters"]:
                slot = E.ESPN_START_SLOT_TO_SLEEPER.get(entry["lineup_slot"])
                truth[(week, row["manager"], entry["player"])] = slot
    seen = disagree = 0
    examples = []
    with _PLAYER_WEEK.open() as fh:
        for row in csv.DictReader(fh):
            if row["Year"] != "2020" or row["Starter/Bench"] != "Starter":
                continue
            key = (int(row["Week"]), row["Team"], row["Player"])
            slot = truth.get(key)
            if slot is None:      # a name the ESPN bridge spells differently
                continue
            seen += 1
            label = row["Position started in (if starter)"]
            if label not in _LABEL_OF_SLOT[slot]:
                disagree += 1
                if len(examples) < 5:
                    examples.append((key, label, slot))
    assert seen > 900, seen
    assert disagree == 0, (f"{disagree}/{seen} 2020 starter rows carry a slot ESPN "
                           f"did not record — exports predate this fix?", examples)


if __name__ == "__main__":
    for fn in (
        test_slot_order_is_stable_within_a_repeated_slot,
        test_an_unknown_slot_sorts_last_rather_than_displacing_a_known_one,
        test_the_template_order_has_one_source,
        test_every_emitted_lineup_follows_the_roster_position_template,
        test_every_starter_carries_a_sleeper_id,
        test_the_one_short_lineup_is_short_at_the_tail,
        test_the_ordering_actually_moves_2020,
        test_the_sheet_labels_each_2020_starter_with_the_slot_espn_recorded,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all 2020 starter-slot checks passed")
