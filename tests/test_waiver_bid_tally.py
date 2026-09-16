"""One standing bid per team — not every claim a manager submitted.

"Number of bids", "Total FAAB bid" and the two runner-up columns describe the
AUCTION for a player: how many teams bid, how much was offered, how decisively
the winner beat the next team. Sleeper files every attempt as its own
transaction, so the tally counted a manager's own superseded resubmissions as
separate rivals — AceMatthew's three $8 claims for Spencer Rattler read as an
auction with two bids in it — and counted bids that could never stand at all
(the roster would have been over its limit, the budget was short, a player being
dropped had already played).

`_standing_waiver_bids` keeps one bid per roster PER WAIVER RUN: the claim that
WON if that roster won it, else its final (latest) claim, which is the bid that
was standing when that run processed. A bid that could never have been honoured
is not in the auction at all.

The run matters. A fantasy week can hold two runs, and a manager can win the same
player in both — LWebs53 took Nico Collins at $7 on 2023-09-04 and again at $11
the next day, after the commissioner reversed the first. Scoping the auction to
the week instead of the run kept only the $7 and left the $11 row reporting a
total smaller than its own winning bid.

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


_RUN = _T0 + 90_000          # when the run settled: Sleeper's status_updated


def _claim(roster, bid, *, status="complete", note=None, ts=_T0, pid="11562",
           ttype="waiver", run=_RUN):
    return {"transaction_id": f"{roster}-{bid}-{ts}", "type": ttype, "status": status,
            "roster_ids": [roster], "created": ts, "status_updated": run,
            "adds": {pid: roster}, "drops": {}, "settings": {"waiver_bid": bid},
            "metadata": {"notes": note} if note else None}


def _auction(rows, pid="11562", run=_RUN):
    return lotg._standing_waiver_bids(rows).get((pid, run), [])


def check_one_bid_per_team():
    """The real 2025-08-31 auction: AceMatthew's winner plus his two superseded
    resubmissions, against one genuine rival."""
    rows = [_claim(3, 8),
            _claim(3, 8, status="failed", note=_OUTBID, ts=_T0 + 37_898),
            _claim(3, 8, status="failed", note=_OUTBID, ts=_T0 + 46_310),
            _claim(5, 5, status="failed", note=_OUTBID, ts=_T0 - 5_000)]
    got = _auction(rows)
    ok = _ok("two teams bid, not four", len(got) == 2, got)
    ok &= _ok("the winner's bid is his winning one", (8.0, True) in got, got)
    ok &= _ok("the rival's losing bid still counts", (5.0, False) in got, got)
    return ok


def check_the_final_bid_is_the_one_that_stood():
    """A team that resubmits at a different amount is offering the LAST one."""
    rows = [_claim(6, 3, status="failed", note=_OUTBID),
            _claim(6, 21, status="failed", note=_OUTBID, ts=_T0 + 20_000),
            _claim(7, 25)]
    got = _auction(rows)
    ok = _ok("the superseded 3 is gone, the standing 21 counts",
             sorted(got) == [(21.0, False), (25.0, True)], got)
    # ...and when the roster DID win, the winning claim is the one that counts,
    # even though later resubmissions failed after it (Rattler's shape).
    rows2 = [_claim(3, 12), _claim(3, 12, status="failed", note=_OUTBID, ts=_T0 + 1_000),
             _claim(3, 9, status="failed", note=_OUTBID, ts=_T0 + 2_000)]
    got2 = _auction(rows2)
    ok &= _ok("a winner's later failed resubmission never replaces its win",
              got2 == [(12.0, True)], got2)
    return ok


def check_a_bid_that_could_never_stand_is_not_in_the_auction():
    for note, why in ((_FULL, "roster would be over the limit"),
                      (_BUDGET, "not enough FAAB"),
                      (_PLAYED, "a player it would drop had already played")):
        rows = [_claim(3, 10), _claim(5, 40, status="failed", note=note)]
        got = _auction(rows)
        if not _ok(f"excluded: {why}", got == [(10.0, True)], got):
            return False
    # An outbid rival is real competition and stays.
    rows = [_claim(3, 10), _claim(5, 9, status="failed", note=_OUTBID)]
    return _ok("an outbid rival is still counted",
               sorted(_auction(rows)) == [(9.0, False), (10.0, True)])


def check_the_shape_of_the_tally():
    ok = _ok("no waiver rows -> nothing", lotg._standing_waiver_bids(
        [_claim(3, 5, ttype="free_agent")]) == {})
    ok &= _ok("an empty feed is fine", lotg._standing_waiver_bids([]) == {})
    two = {"transaction_id": "x", "type": "waiver", "status": "complete", "roster_ids": [3],
           "created": _T0, "status_updated": _RUN, "adds": {"11562": 3, "10213": 3},
           "drops": {}, "settings": {"waiver_bid": 4}}
    got = lotg._standing_waiver_bids([two])
    ok &= _ok("a claim adding two players is a bid on each",
              got == {("11562", _RUN): [(4.0, True)], ("10213", _RUN): [(4.0, True)]}, got)
    ok &= _ok("a claim with no recorded bid counts as $0",
              _auction([_claim(3, None)]) == [(0.0, True)])
    return ok


def check_each_waiver_run_is_its_own_auction():
    """The real 2023-09-04/05 pair: LWebs53 won Nico Collins at $7, the
    commissioner reversed it, and he won again at $11 in the next day's run.
    Two runs, two auctions — scoping to the week dropped the $11 and left its
    row reporting a total below its own winning bid."""
    run_a, run_b = _RUN, _RUN + 86_400_000
    rows = [_claim(3, 7, ts=_T0, run=run_a),
            _claim(5, 4, status="failed", note=_OUTBID, ts=_T0 + 100, run=run_a),
            _claim(3, 11, ts=_T0 + 4_000, run=run_b)]
    got = lotg._standing_waiver_bids(rows)
    ok = _ok("two auctions, not one", sorted(got) == sorted([("11562", run_a), ("11562", run_b)]), sorted(got))
    ok &= _ok("the first run keeps its winner and its rival",
              sorted(got[("11562", run_a)]) == [(4.0, False), (7.0, True)], got[("11562", run_a)])
    ok &= _ok("the second run keeps its own winning bid",
              got[("11562", run_b)] == [(11.0, True)], got[("11562", run_b)])
    return ok


def run_all():
    tests = [check_one_bid_per_team,
             check_each_waiver_run_is_its_own_auction,
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
