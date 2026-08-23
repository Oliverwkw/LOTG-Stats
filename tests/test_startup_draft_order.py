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

The swap is also a real trade now. Its email carried no player legs, so it
parsed to an empty shell that produced no `trades.csv` row; the shell gets its
two teams from the draft record and its six pick legs from the
`commissioner_pick_trades.csv` overlay, the same one that fills in the picks the
other 2020 trade emails dropped. Two of those legs are round-5 picks, which a
"5.0X is a draft-day FAAB buy" shortcut used to swallow — so the guards below
check both that the six read one trade each and that a genuine FAAB buy still
does not.

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


# --------------------------------------------------------------------------- #
# the swap as a trade (needs a build carrying this fix)
# --------------------------------------------------------------------------- #
_TRADES = _ROOT / "exports" / "trades.csv"
_SWAP_TS_PREFIX = "2020-09-09"


def _rows(path):
    import csv
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_sheet_records_the_swap_as_a_two_sided_trade():
    if not _TRADES.exists():
        return _skip("no exports/trades.csv")
    rows = [r for r in _rows(_TRADES) if str(r.get("Date", "")).startswith(_SWAP_TS_PREFIX)]
    assert len(rows) == 2, (
        len(rows), "the startup slot swap should be one trade seen from both sides "
        "— exports may predate the overlay rows in commissioner_pick_trades.csv")
    by_team = {r["Team"]: r for r in rows}
    assert set(by_team) == {"LWebs53", "AceMatthew"}, sorted(by_team)
    for team, other in (("LWebs53", "AceMatthew"), ("AceMatthew", "LWebs53")):
        row = by_team[team]
        assert row["Team's traded with 1"] == other, row
        # Three picks each way, and one side's receipts are the other's sends.
        assert row["Number of assets received"] == "3", row
        assert row["Number of assets traded away"] == "3", row
        assert row["Assets received"] == by_team[other]["Assets sent"], row
        assert row["Assets sent"] == by_team[other]["Assets received"], row
    # Picks are rendered by the label the rest of the sheets parse — "YYYY R.SS
    # (player)" — using the startup's real year, since it has no rookie draft to
    # collide with. The round-5 legs are the ones a "5.0X is a FAAB buy"
    # shortcut used to swallow.
    got = set(by_team["LWebs53"]["Assets received"].split("; "))
    assert got == {"2020 4.05(M. Evans)", "2020 5.04(D. Moore)", "2020 8.05(K. Allen)"}, got


def test_swap_picks_each_count_one_trade():
    if not _HAVE_PICKS:
        return _skip("no exports/picks.csv")
    swapped = [r for r in _startup_rows() if str(r["Original Team"]) != str(r["Team"])]
    assert len(swapped) == 6, len(swapped)
    for r in swapped:
        # All six moved in the SAME deal, so all six read 1 — the round-5 pair
        # used to read 0 while their round-4 and round-8 counterparts read 1.
        assert str(r["Number of trades"]) == "1", (r["Number"], r["Number of trades"])
        # A recorded trade is not a commissioner move.
        assert str(r["Commissioner moved?"]).lower() == "false", r["Number"]
    # And nothing else in the startup moved.
    untouched = [r for r in _startup_rows() if str(r["Original Team"]) == str(r["Team"])]
    assert all(str(r["Number of trades"]) == "0" for r in untouched)


def test_real_faab_buys_are_still_treated_as_synthetic():
    # The startup carve-outs must not let a genuine 5.0X draft-day FAAB buy
    # (2025/2026 only) back into the pick-label map or the trade chain: its
    # trades live under the _R5XX_BASE sentinel key, not plain round 5.
    #
    # What that does NOT mean is "a FAAB buy has no trades". The buy itself
    # counts 0, but the pick is a distinct tradeable asset afterwards and each
    # onward trade counts — 2026's 5.01 and 5.02 both changed hands and read 1
    # in the build BEFORE these carve-outs existed. Asserting 0 across the board
    # only looked safe offline, where the 2025-league build has no 2026 rows at
    # all: the offline data is missing exactly the case that falsifies it.
    if not _HAVE_PICKS:
        return _skip("no exports/picks.csv")
    import csv
    with _PICKS.open(newline="", encoding="utf-8") as fh:
        buys = [r for r in csv.DictReader(fh)
                if str(r["Number"]).startswith("5.") and str(r["Year"]) != "startup"]
    assert buys, "no 5.0X FAAB buys found — the guard would be vacuous"
    untraded = 0
    for r in buys:
        moved = str(r["Original Team"]) != str(r["Team"])
        count = int(float(r["Number of trades"] or 0))
        if moved:
            # It left its buyer, so its sentinel chain has to show that.
            assert count >= 1, (r["Year"], r["Number"], "moved but reads 0 trades")
        else:
            # Never moved: the buy itself must not be counted as a trade.
            assert count == 0, (r["Year"], r["Number"], count)
            untraded += 1
    assert untraded, "every FAAB buy moved — the zero-for-the-buy case is untested"


# --------------------------------------------------------------------------- #
# the drafter, and the 2020 week-1 rosters that settle who it is
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", str(name).lower())


# The exports carry no player ids, so a roster is matched to a draft by name.
# Every sheet here is a build output and uses Sleeper's canonical spelling, so
# exact (punctuation-insensitive) names match — no aliasing needed, and none
# wanted: a "last name + first initial" fallback silently merges Duke Johnson
# with David Johnson, which is the ambiguity trap this repo already documents.


def _startup_by_column(column: str):
    by_team = {}
    for r in _startup_rows():
        by_team.setdefault(str(r[column]), set()).add(_norm(r["Player Picked"]))
    return by_team


def _rosters(year=None, week=None):
    import csv
    out = {}
    with (_EXPORTS / "player_week.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if year is not None and str(r["Year"]) != str(year):
                continue
            if week is not None and str(r["Week"]) != str(week):
                continue
            out.setdefault((r["Team"], str(r["Year"]), str(r["Week"])), set()).add(_norm(r["Player"]))
    return out


_EXPORTS = _ROOT / "exports"


def test_startup_remaining_credits_the_drafter_not_the_slot_owner():
    """`Startup draft players remaining` counts who a team DRAFTED.

    On the six swapped picks the drafter and the slot owner are different
    managers, so the two readings disagree — by up to 3 players across 160
    team-weeks, every season, for both teams in the deal. Recomputed here from
    the picks sheet and the weekly rosters rather than trusted.
    """
    if not _HAVE_PICKS or not (_EXPORTS / "team_week.csv").exists():
        return _skip("no exports/")
    import csv
    drafted = _startup_by_column("Team")          # Final Team = the selector
    owned = _startup_by_column("Original Team")   # slot owner
    rosters = _rosters()
    checked = disagreed = 0
    with (_EXPORTS / "team_week.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            got = str(r.get("Startup draft players remaining", "")).strip()
            if got in ("", "nan", "N/A"):
                continue
            key = (r["Team"], str(r["Year"]), str(r["Week"]))
            men = rosters.get(key)
            if men is None:
                continue
            by_drafter = len(drafted.get(r["Team"], set()) & men)
            by_owner = len(owned.get(r["Team"], set()) & men)
            assert int(float(got)) == by_drafter, (key, got, by_drafter)
            checked += 1
            disagreed += (by_drafter != by_owner)
    assert checked > 500, checked
    # If the two readings never diverged the guard would prove nothing.
    assert disagreed, "drafter and slot owner agree everywhere — guard is vacuous"


def test_2020_week_one_rosters_reconcile_to_the_draft_and_the_ledger():
    """Every 2020 week-1 roster spot traces to a pick, an add, or a drop.

    The strongest available check that the startup and the 2020 offseason are
    completely accounted for: 152 picks, plus the adds and minus the drops the
    transaction log records through week 1, must reproduce the rosters exactly.
    """
    if not _HAVE_PICKS or not (_EXPORTS / "add_drops.csv").exists():
        return _skip("no exports/")
    import csv
    drafted = _startup_by_column("Team")
    adds, drops = {}, {}
    with (_EXPORTS / "add_drops.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            # NFL week 1 2020 ran Sept 10-14; allow the Tuesday after.
            if str(r["Season"]) != "2020" or str(r["Date"])[:10] > "2020-09-15":
                continue
            if r["Player Added"]:
                adds.setdefault(r["Team"], set()).add(_norm(r["Player Added"]))
            if r["Player Dropped"]:
                drops.setdefault(r["Team"], set()).add(_norm(r["Player Dropped"]))
    rosters = _rosters(2020, 1)
    assert len(rosters) == 8, sorted(rosters)
    unexplained = []
    for (team, _y, _w), men in rosters.items():
        got, add, drop = drafted.get(team, set()), adds.get(team, set()), drops.get(team, set())
        unexplained += [f"{team}: {x} on the roster from nowhere" for x in sorted(men - got - add)]
        unexplained += [f"{team}: {x} drafted, absent, no drop" for x in sorted(got - men - drop)]
    assert not unexplained, unexplained


def test_startup_round_five_picks_link_to_their_own_chain():
    """A startup 5.0X is a real round-5 pick, not a FAAB buy.

    Its trades live under plain round 5, so routing it to the `_R5XX_BASE`
    sentinel looks up a key nothing writes and loses the link — including, for
    the two swapped ones, a link to a real trade their round-4 and round-8
    counterparts in the same deal both have.
    """
    if not _HAVE_PICKS:
        return _skip("no exports/picks.csv")
    rows = {str(r["Number"]): r for r in _startup_rows()
            if str(r["Number"]).startswith("5.")}
    assert len(rows) == _TEAMS, sorted(rows)
    for num, r in rows.items():
        prev = str(r["Link to previous transaction"]).strip()
        moved = str(r["Original Team"]) != str(r["Team"])
        if moved:
            assert prev.startswith("T#"), (num, prev, "swapped but no trade link")
        else:
            assert prev in ("", "nan", "N/A"), (num, prev, "never moved but links to a trade")
    # Each swapped pick links to the SAME trade row as its counterparts on the
    # same side of the deal — one trade, six legs, two sides.
    by_side = {}
    for r in _startup_rows():
        if str(r["Original Team"]) == str(r["Team"]):
            continue
        by_side.setdefault(r["Team"], set()).add(str(r["Link to previous transaction"]).strip())
    assert len(by_side) == 2, sorted(by_side)
    for team, links in by_side.items():
        assert len(links) == 1, (team, links, "one deal should be one trade row")


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
        test_sheet_records_the_swap_as_a_two_sided_trade,
        test_swap_picks_each_count_one_trade,
        test_real_faab_buys_are_still_treated_as_synthetic,
        test_startup_remaining_credits_the_drafter_not_the_slot_owner,
        test_2020_week_one_rosters_reconcile_to_the_draft_and_the_ledger,
        test_startup_round_five_picks_link_to_their_own_chain,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all startup draft-order checks passed")
