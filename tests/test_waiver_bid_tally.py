"""One standing bid per team — not every claim a manager submitted.

"Number of bids", "Total FAAB bid" and the two runner-up columns describe the
AUCTION for a player: how many teams bid, how much was offered, how decisively
the winner beat the next team. Sleeper files every attempt as its own
transaction, so the tally counted a manager's own superseded resubmissions as
separate rivals — AceMatthew's three $8 claims for Spencer Rattler read as an
auction with two bids in it — and counted bids that could never stand at all
(the roster would have been over its limit, the budget was short, a player being
dropped had already played).

`_standing_waiver_bids` keeps one bid per roster: the claim that WON if that
roster won, else its final (latest) claim, which is the bid that was standing
when waivers ran. A bid that could never have been honoured is not in the
auction at all.

Run: PYTHONPATH=src:lib python tests/test_waiver_bid_tally.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("lotg", _ROOT / "src" / "lotg.py")
lotg = importlib.util.module_from_spec(_spec)
sys.modules["lotg"] = lotg          # dataclasses resolve types via sys.modules
_spec.loader.exec_module(lotg)

_T0 = 1756678711547
_OUTBID = "This player was claimed by another owner."
_FULL = "Unfortunately, your roster will have too many players after this transaction."
_BUDGET = "You are over the budget for this transaction."
_PLAYED = "One of the players you are trying to drop has already started playing."


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _claim(roster, bid, *, status="complete", note=None, ts=_T0, pid="11562", ttype="waiver"):
    return {"transaction_id": f"{roster}-{bid}-{ts}", "type": ttype, "status": status,
            "roster_ids": [roster], "created": ts, "adds": {pid: roster}, "drops": {},
            "settings": {"waiver_bid": bid},
            "metadata": {"notes": note} if note else None}


def check_one_bid_per_team():
    """The real 2025-08-31 auction: AceMatthew's winner plus his two superseded
    resubmissions, against one genuine rival."""
    rows = [_claim(3, 8),
            _claim(3, 8, status="failed", note=_OUTBID, ts=_T0 + 37_898),
            _claim(3, 8, status="failed", note=_OUTBID, ts=_T0 + 46_310),
            _claim(5, 5, status="failed", note=_OUTBID, ts=_T0 - 5_000)]
    got = lotg._standing_waiver_bids(rows)["11562"]
    ok = _ok("two teams bid, not four", len(got) == 2, got)
    ok &= _ok("the winner's bid is his winning one", (8.0, True) in got, got)
    ok &= _ok("the rival's losing bid still counts", (5.0, False) in got, got)
    return ok


def check_the_final_bid_is_the_one_that_stood():
    """A team that resubmits at a different amount is offering the LAST one."""
    rows = [_claim(6, 3, status="failed", note=_OUTBID),
            _claim(6, 21, status="failed", note=_OUTBID, ts=_T0 + 20_000),
            _claim(7, 25)]
    got = dict.fromkeys([])
    got = lotg._standing_waiver_bids(rows)["11562"]
    ok = _ok("the superseded 3 is gone, the standing 21 counts",
             sorted(got) == [(21.0, False), (25.0, True)], got)
    # ...and when the roster DID win, the winning claim is the one that counts,
    # even though later resubmissions failed after it (Rattler's shape).
    rows2 = [_claim(3, 12), _claim(3, 12, status="failed", note=_OUTBID, ts=_T0 + 1_000),
             _claim(3, 9, status="failed", note=_OUTBID, ts=_T0 + 2_000)]
    got2 = lotg._standing_waiver_bids(rows2)["11562"]
    ok &= _ok("a winner's later failed resubmission never replaces its win",
              got2 == [(12.0, True)], got2)
    return ok


def check_a_bid_that_could_never_stand_is_not_in_the_auction():
    for note, why in ((_FULL, "roster would be over the limit"),
                      (_BUDGET, "not enough FAAB"),
                      (_PLAYED, "a player it would drop had already played")):
        rows = [_claim(3, 10), _claim(5, 40, status="failed", note=note)]
        got = lotg._standing_waiver_bids(rows)["11562"]
        if not _ok(f"excluded: {why}", got == [(10.0, True)], got):
            return False
    # An outbid rival is real competition and stays.
    rows = [_claim(3, 10), _claim(5, 9, status="failed", note=_OUTBID)]
    return _ok("an outbid rival is still counted",
               sorted(lotg._standing_waiver_bids(rows)["11562"]) == [(9.0, False), (10.0, True)])


def check_the_shape_of_the_tally():
    ok = _ok("no waiver rows -> nothing", lotg._standing_waiver_bids(
        [_claim(3, 5, ttype="free_agent")]) == {})
    ok &= _ok("an empty feed is fine", lotg._standing_waiver_bids([]) == {})
    two = {"transaction_id": "x", "type": "waiver", "status": "complete", "roster_ids": [3],
           "created": _T0, "adds": {"11562": 3, "10213": 3}, "drops": {},
           "settings": {"waiver_bid": 4}}
    got = lotg._standing_waiver_bids([two])
    ok &= _ok("a claim adding two players is a bid on each",
              got == {"11562": [(4.0, True)], "10213": [(4.0, True)]}, got)
    nobid = lotg._standing_waiver_bids([_claim(3, None)])
    ok &= _ok("a claim with no recorded bid counts as $0",
              nobid == {"11562": [(0.0, True)]}, nobid)
    return ok


def run_all():
    tests = [check_one_bid_per_team,
             check_the_final_bid_is_the_one_that_stood,
             check_a_bid_that_could_never_stand_is_not_in_the_auction,
             check_the_shape_of_the_tally]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_waiver_bid_tally():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
