"""A losing waiver claim must never displace the winning one.

Sleeper files every waiver bid as its own transaction: one `complete` winner and
a `failed` row per losing bid. It also emits the SAME claim twice — one copy bare
and one carrying the drop the claim would make — which `_prune_duplicate_tx`
collapses by keeping the copy with the drop.

Those two rules met on 2025-08-31. AceMatthew submitted three $8 claims for
Spencer Rattler (seq 27, 28, 29); the winner (seq 27, complete) carried no drop,
while his two superseded resubmissions (failed) each carried one. The dedup read
"same manager, same add, one has a drop" and replaced the WINNER with a loser,
and the failed-status filter then deleted it. The claim, its $8, and Rattler's
arrival on AceMatthew's roster all vanished — the build later synthesized a
phantom free-agent pickup dated the day before he was dropped, two months later.

So the merge is skipped whenever it would discard a complete row for one that is
not. It is the only such loss in the league's history (one claim, verified across
every cached transaction feed), and it stays impossible.

Run: PYTHONPATH=src:lib python tests/test_waiver_claim_dedup.py
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

_T0 = 1756678711547          # 2025-08-31 22:18:31Z, the real claim


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _tx(tid, *, adds=None, drops=None, status="complete", ts=_T0, creator="ace", ttype="waiver"):
    return {"transaction_id": tid, "type": ttype, "status": status, "creator": creator,
            "created": ts, "adds": {p: 3 for p in (adds or [])},
            "drops": {p: 3 for p in (drops or [])}, "settings": {"waiver_bid": 8}}


def _ids(rows):
    return [str(r["transaction_id"]) for r in rows]


def check_the_winning_claim_survives_its_losing_twins():
    """The real 2025-08-31 rows: seq 27 complete (no drop), 28 and 29 failed
    (each with a drop), all within 46 seconds."""
    rows = [_tx("27", adds=["11562"]),
            _tx("28", adds=["11562"], drops=["11619"], status="failed", ts=_T0 + 37_898),
            _tx("29", adds=["11562"], drops=["10213"], status="failed", ts=_T0 + 46_310)]
    out = lotg._prune_duplicate_tx(rows)
    ok = _ok("the complete claim is kept", "27" in _ids(out), _ids(out))
    kept = [r for r in out if (r.get("status") or "complete") == "complete"]
    ok &= _ok("and it is the only complete row left", _ids(kept) == ["27"], _ids(kept))
    ok &= _ok("the losing bids are left for the status filter to drop",
              {"28", "29"} <= set(_ids(out)), _ids(out))
    return ok


def check_the_duplicate_claim_quirk_still_collapses():
    """What the rule is FOR: one claim emitted twice, bare and with its drop.
    Both are complete, so the copy carrying the drop is the one to keep."""
    bare = _tx("a", adds=["100"])
    with_drop = _tx("b", adds=["100"], drops=["200"], ts=_T0 + 1_000)
    ok = _ok("the bare copy gives way to the one with the drop",
             _ids(lotg._prune_duplicate_tx([bare, with_drop])) == ["b"],
             _ids(lotg._prune_duplicate_tx([bare, with_drop])))
    # ...in either arrival order.
    ok &= _ok("and the same holds when the drop arrives first",
              _ids(lotg._prune_duplicate_tx([_tx("b", adds=["100"], drops=["200"]),
                                             _tx("a", adds=["100"], ts=_T0 + 1_000)])) == ["b"])
    # A failed bare copy beside a complete one with the drop still collapses:
    # nothing complete is lost.
    ok &= _ok("a failed bare copy is still absorbed",
              _ids(lotg._prune_duplicate_tx([
                  _tx("a", adds=["100"], status="failed"),
                  _tx("b", adds=["100"], drops=["200"], ts=_T0 + 1_000)])) == ["b"])
    return ok


def check_unrelated_rows_are_untouched():
    ok = _ok("two claims more than 60s apart are two events",
             _ids(lotg._prune_duplicate_tx([
                 _tx("a", adds=["100"]),
                 _tx("b", adds=["100"], drops=["200"], ts=_T0 + 61_000)])) == ["a", "b"])
    ok &= _ok("different managers never merge",
              _ids(lotg._prune_duplicate_tx([
                  _tx("a", adds=["100"]),
                  _tx("b", adds=["100"], drops=["200"], creator="other",
                      ts=_T0 + 1_000)])) == ["a", "b"])
    ok &= _ok("different adds never merge",
              _ids(lotg._prune_duplicate_tx([
                  _tx("a", adds=["100"]),
                  _tx("b", adds=["101"], drops=["200"], ts=_T0 + 1_000)])) == ["a", "b"])
    ok &= _ok("an empty feed is fine", lotg._prune_duplicate_tx([]) == [])
    return ok


def check_the_inverted_commissioner_swap_still_collapses():
    """Case (b): the same event mirrored at an identical timestamp — one row
    keyed as adds/drops, the other as drops/adds."""
    out = lotg._prune_duplicate_tx([_tx("a", adds=["100"], drops=["200"], ttype="commissioner"),
                                    _tx("b", adds=["200"], drops=["100"], ttype="commissioner")])
    return _ok("one side of the mirror is kept", len(out) == 1, _ids(out))


def run_all():
    tests = [check_the_winning_claim_survives_its_losing_twins,
             check_the_duplicate_claim_quirk_still_collapses,
             check_unrelated_rows_are_untouched,
             check_the_inverted_commissioner_swap_still_collapses]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_waiver_claim_dedup():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
