"""The 2020 startup was a SNAKE, so its picks must be numbered by draft ORDER.

A team's draft slot is constant across a draft; the position it picks FROM is
not. At slot 1 you pick 1st in round 1 and 8th in round 2. The startup emit used
to label every pick `round.slot`, which numbered all 72 even-round picks
backwards — Nick Chubb, taken 16th overall, read as `2.01` instead of `2.08`.
That is not only a display bug: the pick-adjustment pass recovers a pick's
overall position from its number as `(round - 1) * 8 + number`, so a reversed
even round silently compared every startup pick against the wrong neighbours.

The other half is ownership. ESPN marks a pick whose slot changed hands with
`owningTeamIds` (the original owner) alongside `teamId` (whoever selected).
Exactly six startup picks carry it — LWebs53 and AceMatthew swapped their round
4, 5 and 8 picks, corroborated by the one picks-only trade in the 2020 email
ledger, timestamped ~6 hours before the draft finished. They are the only reason
the draft is not a pure slot-ordered snake, so they double as the fixture that
proves the numbering is read from ESPN rather than re-derived from the drafter.

The raw-source checks run wherever `data/espn_2020_raw/` is present. The
export-based checks need a build that includes this fix; they skip when
`exports/` is absent.

Run: python tests/test_startup_draft_order.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import espn_2020 as E  # noqa: E402

_RAW = _ROOT / "data" / "espn_2020_raw"
_HAVE_RAW = (_RAW / "view_mDraftDetail.json").exists()
_PICKS = _ROOT / "exports" / "picks.csv"
_HAVE_PICKS = _PICKS.exists()

_TEAMS = len(E.TEAM_TO_MANAGER)
_MGR_BY_RID = {v: k for k, v in E.SLEEPER_ROSTER_ID_BY_MANAGER.items()}

# The six traded picks, keyed by overall pick number:
#   (round, true position in round, drafter, original owner, player)
_TRADED = {
    29: (4, 5, "LWebs53", "AceMatthew", "Mike Evans"),
    31: (4, 7, "AceMatthew", "LWebs53", "Kenny Golladay"),
    34: (5, 2, "AceMatthew", "LWebs53", "Allen Robinson"),
    36: (5, 4, "LWebs53", "AceMatthew", "D.J. Moore"),
    61: (8, 5, "LWebs53", "AceMatthew", "Keenan Allen"),
    63: (8, 7, "AceMatthew", "LWebs53", "Hunter Henry"),
}


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


_picks_cache = None


def _startup_picks():
    global _picks_cache
    if _picks_cache is None:
        _picks_cache = E.emit_sleeper_2020(E.load_espn_2020(str(_RAW)))["draft_picks"]
    return _picks_cache


# --------------------------------------------------------------------------- #
# the snake mapping itself (no data needed)
# --------------------------------------------------------------------------- #
def test_slot_from_pick_in_round_reverses_even_rounds():
    # Odd rounds: position IS the slot. Even rounds: mirrored.
    for pos in range(1, _TEAMS + 1):
        assert E._slot_from_pick_in_round(1, pos) == pos
        assert E._slot_from_pick_in_round(3, pos) == pos
        assert E._slot_from_pick_in_round(2, pos) == _TEAMS + 1 - pos
        assert E._slot_from_pick_in_round(4, pos) == _TEAMS + 1 - pos


def test_slot_mapping_is_an_involution():
    # Applying it twice returns the input, which is what lets the same helper
    # translate slot -> position and position -> slot.
    for rnd in range(1, 20):
        for pos in range(1, _TEAMS + 1):
            once = E._slot_from_pick_in_round(rnd, pos)
            assert E._slot_from_pick_in_round(rnd, once) == pos


def test_slot_mapping_rejects_junk_rather_than_guessing():
    assert E._slot_from_pick_in_round(None, 3) is None
    assert E._slot_from_pick_in_round(2, None) is None
    assert E._slot_from_pick_in_round(2, "x") is None


# --------------------------------------------------------------------------- #
# the emitted picks carry true order + true ownership
# --------------------------------------------------------------------------- #
def test_every_pick_carries_its_true_position_and_owner():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    ps = _startup_picks()
    assert len(ps) == 152, len(ps)
    for p in ps:
        assert p.get("pick_in_round") is not None, p
        assert p.get("original_roster_id") is not None, p
        # 8-team draft: overall position is recoverable from round + position,
        # which is the invariant the pick-adjustment window depends on.
        assert p["pick_no"] == (p["round"] - 1) * _TEAMS + p["pick_in_round"], p


def test_draft_is_a_pure_snake_once_ownership_is_applied():
    # Every pick's slot is the mirror of its position on even rounds. This holds
    # for all 152 only because the slot follows the pick's OWNER; reading it off
    # the drafter instead breaks on the six traded picks.
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    for p in _startup_picks():
        assert p["draft_slot"] == E._slot_from_pick_in_round(p["round"], p["pick_in_round"]), p


def test_the_six_traded_picks_are_exactly_the_known_swap():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    traded = {p["pick_no"]: p for p in _startup_picks()
              if p["roster_id"] != p["original_roster_id"]}
    assert set(traded) == set(_TRADED), sorted(traded)
    for ovr, (rnd, pos, drafter, owner, _player) in _TRADED.items():
        p = traded[ovr]
        assert (p["round"], p["pick_in_round"]) == (rnd, pos), p
        assert _MGR_BY_RID[p["roster_id"]] == drafter, p
        assert _MGR_BY_RID[p["original_roster_id"]] == owner, p
    # A straight two-way swap: the pair exchanged the SAME rounds, so each
    # round's two swapped picks are mirror images of each other.
    for rnd in {r for r, *_ in _TRADED.values()}:
        pair = [p for p in traded.values() if p["round"] == rnd]
        assert len(pair) == 2, rnd
        a, b = pair
        assert a["roster_id"] == b["original_roster_id"]
        assert b["roster_id"] == a["original_roster_id"]


def test_untraded_picks_are_owned_by_their_drafter():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    for p in _startup_picks():
        if p["pick_no"] in _TRADED:
            continue
        assert p["roster_id"] == p["original_roster_id"], p


def test_each_team_picks_once_per_round():
    if not _HAVE_RAW:
        return _skip("no data/espn_2020_raw")
    by_round = {}
    for p in _startup_picks():
        by_round.setdefault(p["round"], []).append(p)
    for rnd, ps in by_round.items():
        assert sorted(x["pick_in_round"] for x in ps) == list(range(1, _TEAMS + 1)), rnd
        assert len({x["draft_slot"] for x in ps}) == _TEAMS, rnd


# --------------------------------------------------------------------------- #
# the picks sheet (needs a build carrying this fix)
# --------------------------------------------------------------------------- #
def _startup_rows():
    import csv
    with _PICKS.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if str(r.get("Year")) == "startup"]


def test_sheet_numbers_startup_picks_by_draft_order():
    if not _HAVE_PICKS:
        return _skip("no exports/picks.csv")
    rows = _startup_rows()
    assert len(rows) == 152, len(rows)
    by_num = {}
    for r in rows:
        m = re.match(r"\s*(\d+)\.(\d+)\s*$", str(r["Number"]))
        assert m, r["Number"]
        by_num[(int(m.group(1)), int(m.group(2)))] = r
    # A complete 19x8 grid: every round holds positions 1..8 exactly once. The
    # slot-labelled version also satisfied this, so the real check is the next
    # one — this just pins the shape the ordering check reads from.
    assert set(by_num) == {(r, s) for r in range(1, 20) for s in range(1, _TEAMS + 1)}
    # The team OWNING position 1 of an odd round owns position 8 of the next
    # (even) round. Chubb, at slot 1, is the concrete case: 1.01 then 2.08.
    # Compare on Original Team — the slot's owner — because on the six swapped
    # picks the drafter is the counterparty and does not follow the snake.
    _stale = ("startup picks are still numbered by draft SLOT, not draft order "
              "— exports predate the snake-numbering fix, or it regressed")
    assert by_num[(1, 1)]["Original Team"] == "Oliverwkw", _stale
    assert by_num[(2, 8)]["Original Team"] == "Oliverwkw", _stale
    assert by_num[(2, 8)]["Player Picked"] == "Nick Chubb", _stale
    for rnd in range(1, 19, 2):
        for pos in range(1, _TEAMS + 1):
            assert (by_num[(rnd, pos)]["Original Team"]
                    == by_num[(rnd + 1, _TEAMS + 1 - pos)]["Original Team"]), (rnd, pos, _stale)


def test_sheet_marks_the_traded_picks_and_only_those():
    if not _HAVE_PICKS:
        return _skip("no exports/picks.csv")
    expected = {f'{rnd}.{pos:02d}': (drafter, owner, player)
                for (rnd, pos, drafter, owner, player) in _TRADED.values()}
    seen = {}
    for r in _startup_rows():
        # "Team" is the pick's Final Team — whoever made the selection.
        if str(r["Original Team"]) != str(r["Team"]):
            seen[str(r["Number"])] = (r["Team"], r["Original Team"], r["Player Picked"])
    assert set(seen) == set(expected), (
        sorted(seen), "startup Original Team should differ from the drafter on "
        "exactly the six swapped picks — exports may predate the fix")
    for num, (drafter, owner, player) in expected.items():
        got_drafter, got_owner, got_player = seen[num]
        assert got_drafter == drafter, (num, got_drafter)
        assert got_owner == owner, (num, got_owner)
        # Names are normalised to Sleeper's spelling on the sheet (DJ Moore),
        # so compare on last name only.
        assert got_player.split()[-1] == player.split()[-1], (num, got_player)


if __name__ == "__main__":
    for fn in (
        test_slot_from_pick_in_round_reverses_even_rounds,
        test_slot_mapping_is_an_involution,
        test_slot_mapping_rejects_junk_rather_than_guessing,
        test_every_pick_carries_its_true_position_and_owner,
        test_draft_is_a_pure_snake_once_ownership_is_applied,
        test_the_six_traded_picks_are_exactly_the_known_swap,
        test_untraded_picks_are_owned_by_their_drafter,
        test_each_team_picks_once_per_round,
        test_sheet_numbers_startup_picks_by_draft_order,
        test_sheet_marks_the_traded_picks_and_only_those,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all startup draft-order checks passed")
