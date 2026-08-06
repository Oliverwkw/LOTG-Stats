"""Composing several trade rewinds into one scenario.

`replay.compose` / `replay.undo_trades` exist because a teardown is not one
trade: rewinding the 2024 CMC deal alone leaves the rest of that roster sold
off, so the single-trade path understates the combined effect. The risk they
add is the merge — the same player can appear in two undos (traded A->B, later
B->C), and the composed answer must be one C->A move rather than two
contradictory ones.

The guards here are the ones `replay.check_compose` runs, plus the pure-logic
cases that have no committed-data equivalent. There is no build number for
"several trades rewound at once" — the build never asks — so composition is
pinned against the single-trade path, which `check_identity` already ties to the
built PF, bracket and champion.

Everything SKIPs cleanly without the committed snapshot/exports.

Run: python tests/test_replay_compose.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import replay as R  # noqa: E402

_HAVE_DATA = ((_ROOT / "exports" / "team_week.csv").exists()
              and (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists())

# The 2024 Oliverwkw teardown, in the order the league made it. Documented in
# plan/notes/WHATIF_TEARDOWN_2024.md.
TEARDOWN_2024 = ("1090497154780581888",   # Kittle out
                 "1092268177528127488",   # McCaffrey, Kupp, Herbert, Kirk, Thielen out
                 "1095772841745821696",   # Hopkins, Pittman, Pierce out
                 "1117973026936573952",   # Ekeler out
                 "1152469543118536704")   # McLaurin out, at the deadline


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Pure logic — the merge, with no data behind it
# ---------------------------------------------------------------------------
def _scn(*moves: R.Move, season: int = 2024) -> R.Scenario:
    return R.Scenario(season=season, moves=moves)


def test_disjoint_moves_are_simply_unioned():
    a = _scn(R.Move("p1", 3, 7))
    b = _scn(R.Move("p2", 5, 7))
    out = R.compose(2024, [a, b])
    assert set(out.moves) == {R.Move("p1", 3, 7), R.Move("p2", 5, 7)}


def test_a_player_traded_twice_chains_to_one_move():
    # Really: 7 -> 3 in May, then 3 -> 5 in October. Rewinding both puts him
    # back on 7, from the earlier of the two weeks.
    first = _scn(R.Move("p1", 3, 7, from_week=1))
    second = _scn(R.Move("p1", 5, 3, from_week=8))
    out = R.compose(2024, [first, second])
    assert out.moves == (R.Move("p1", 5, 7, from_week=1),)


def test_chaining_does_not_depend_on_the_order_given():
    first = _scn(R.Move("p1", 3, 7, from_week=1))
    second = _scn(R.Move("p1", 5, 3, from_week=8))
    assert R.compose(2024, [second, first]).moves == R.compose(2024, [first, second]).moves


def test_an_undo_composed_with_its_mirror_cancels():
    out = R.compose(2024, [_scn(R.Move("p1", 3, 7)), _scn(R.Move("p1", 7, 3))])
    assert out.moves == ()


def test_endpoints_that_do_not_chain_raise_rather_than_pick_one():
    # Two undos both claim to move him off a different roster: a real ambiguity.
    try:
        R.compose(2024, [_scn(R.Move("p1", 3, 7)), _scn(R.Move("p1", 4, 6))])
    except LookupError as exc:
        assert "do not chain" in str(exc)
    else:
        raise AssertionError("expected a LookupError on unchainable endpoints")


def test_seasons_may_not_be_mixed():
    try:
        R.compose(2024, [_scn(R.Move("p1", 3, 7)), _scn(R.Move("p2", 5, 7), season=2025)])
    except LookupError as exc:
        assert "different seasons" in str(exc)
    else:
        raise AssertionError("expected a LookupError when composing across seasons")


def test_undo_trades_needs_a_selector():
    try:
        R.undo_trades(2024)
    except LookupError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("expected a LookupError with no selector")


# ---------------------------------------------------------------------------
# Against the committed data
# ---------------------------------------------------------------------------
def test_compose_guard_passes_for_every_completed_season():
    if not _HAVE_DATA:
        return _skip("no committed data")
    for year in Q.completed_seasons():
        if not Q.season_meta(year).has_snapshot:
            continue
        problems = R.check_compose(year)
        assert problems == [], f"{year}: {problems}"


def test_three_way_trades_are_refused_not_guessed():
    if not _HAVE_DATA:
        return _skip("no committed data")
    # A pre-existing limit of the single-trade path, inherited by composition:
    # pinned here so it stays a loud refusal rather than a silent wrong answer.
    found = [t for y in Q.completed_seasons() for t in R.three_way_trades(y)]
    if not found:
        return _skip("no three-way trade in the committed data")
    trade = found[0]
    try:
        R.undo_trades(trade.season, transaction_ids=[trade.transaction_id])
    except LookupError as exc:
        assert "sides" in str(exc)
    else:
        raise AssertionError("expected a LookupError on a three-way trade")


def test_one_trade_composed_equals_undo_trade():
    if not _HAVE_DATA:
        return _skip("no committed data")
    one = R.undo_trade(2024, transaction_id=TEARDOWN_2024[1])
    same = R.undo_trades(2024, transaction_ids=[TEARDOWN_2024[1]])
    assert same.moves == one.moves
    # Naming the same trade twice is still one undo, not a double-apply.
    twice = R.undo_trades(2024, transaction_ids=[TEARDOWN_2024[1], TEARDOWN_2024[1]])
    assert set(twice.moves) == set(one.moves)


def test_the_teardown_composes_to_every_players_real_move():
    if not _HAVE_DATA:
        return _skip("no committed data")
    scenario = R.undo_trades(2024, transaction_ids=list(TEARDOWN_2024))
    names = {Q.players().name(m.player_id) for m in scenario.moves}
    # Everyone Oliverwkw sold in the teardown comes back...
    for who in ("Christian McCaffrey", "Cooper Kupp", "Justin Herbert", "Christian Kirk",
                "Adam Thielen", "George Kittle", "DeAndre Hopkins", "Michael Pittman",
                "Alec Pierce", "Austin Ekeler", "Terry McLaurin"):
        assert who in names, f"{who} missing from the composed teardown"
    # ...and everyone who came back the other way leaves again.
    for who in ("Wan'Dale Robinson", "Michael Wilson", "Jameson Williams"):
        assert who in names, f"{who} missing from the composed teardown"

    oliver = next(r for r, t in Q.teams(2024).items() if t == "Oliverwkw")
    arriving = [m for m in scenario.moves if m.to_roster == oliver]
    assert len(arriving) == 11, f"expected 11 players back on Oliverwkw, got {len(arriving)}"


def test_composing_the_teardown_beats_undoing_the_big_trade_alone():
    if not _HAVE_DATA:
        return _skip("no committed data")
    oliver = next(r for r, t in Q.teams(2024).items() if t == "Oliverwkw")

    def wins(scenario):
        result = R.replay(scenario.with_model("anchored"))
        return next(s.wins for s in result.standings if s.roster_id == oliver)

    alone = wins(R.undo_trade(2024, transaction_id=TEARDOWN_2024[1]))
    whole = wins(R.undo_trades(2024, transaction_ids=list(TEARDOWN_2024)))
    # The point of composing: the parts are worth more together than the one
    # headline trade is on its own. Pinned to the documented note.
    assert alone == 5, alone
    assert whole == 8, whole


TESTS = [
    test_disjoint_moves_are_simply_unioned,
    test_a_player_traded_twice_chains_to_one_move,
    test_chaining_does_not_depend_on_the_order_given,
    test_an_undo_composed_with_its_mirror_cancels,
    test_endpoints_that_do_not_chain_raise_rather_than_pick_one,
    test_seasons_may_not_be_mixed,
    test_undo_trades_needs_a_selector,
    test_compose_guard_passes_for_every_completed_season,
    test_three_way_trades_are_refused_not_guessed,
    test_one_trade_composed_equals_undo_trade,
    test_the_teardown_composes_to_every_players_real_move,
    test_composing_the_teardown_beats_undoing_the_big_trade_alone,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall compose checks passed")
