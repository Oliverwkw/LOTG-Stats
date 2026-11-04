"""Phantom drops: the would-be drop on a transaction that did not happen.

A failed waiver claim moved nobody. Sleeper's API used to return the player it
would have cut in `drops`; it now returns `drops: null` on every failed claim.
`.cache/sleeper` (the build's input for past leagues) kept 190 of the old drops
over 51 weeks of 2021-25, so it disagreed with the committed snapshot on data
about drops that never happened. `lotg_support.sleeper.strip_phantom_drops`
normalises every read and write, and these tests keep cache and snapshot equal.

Runnable as `pytest tests/test_sleeper_phantom_drops.py` or directly.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import sleeper as S  # noqa: E402
from lotg_support.utils import HttpConfig  # noqa: E402

_SNAP = _ROOT / "exports" / "snapshot"
_CACHE = _ROOT / ".cache" / "sleeper"


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _tx(status, drops, tid="1"):
    return {"transaction_id": tid, "type": "waiver", "status": status,
            "adds": {"100": 3}, "drops": drops, "roster_ids": [3]}


def test_only_transactions_that_did_not_happen_lose_their_drops():
    txs = [_tx("failed", {"200": 3}, "a"), _tx("complete", {"201": 3}, "b"),
           _tx(None, {"202": 3}, "c"), _tx("failed", None, "d")]
    assert S.strip_phantom_drops(txs) == 1
    assert [t["drops"] for t in txs] == [None, {"201": 3}, {"202": 3}, None]
    assert S.strip_phantom_drops(txs) == 0          # idempotent
    assert S.strip_phantom_drops(None) == 0 and S.strip_phantom_drops({}) == 0


def test_a_cached_feed_is_served_and_healed_without_its_phantom_drops():
    with tempfile.TemporaryDirectory() as d:
        sc = S.SleeperClient("999", HttpConfig(), cache_dir=Path(d))
        url = sc._url("/league/123/transactions/5")       # a past league: cached
        assert sc._should_cache(url)
        cp = sc._cache_path(url)
        cp.write_text(json.dumps([_tx("failed", {"200": 3}), _tx("complete", {"201": 3}, "2")]))
        got = sc.transactions(5, "123")
        assert [t["drops"] for t in got] == [None, {"201": 3}]
        # The file itself is rewritten, so a restored older Actions cache cannot
        # carry the phantom drop into the Tuesday .cache commit.
        assert [t["drops"] for t in json.loads(cp.read_text())] == [None, {"201": 3}]
        # Other endpoints are served as cached, untouched.
        other = sc._url("/league/123/matchups/5")
        sc._cache_path(other).write_text(json.dumps([_tx("failed", {"200": 3})]))
        assert sc.matchups(5, "123")[0]["drops"] == {"200": 3}


def _past_weeks():
    chain = json.loads((_SNAP / "league_chain.json").read_text())
    for lg in chain:
        season, lid = int(lg["season"]), str(lg["league_id"])
        for wk in sorted((_SNAP / f"season_{season}" / "weeks").glob("week_*")):
            url = f"https://api.sleeper.app/v1/league/{lid}/transactions/{int(wk.name[5:])}"
            cp = _CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
            if cp.exists():                  # the live league is never cached
                yield season, wk.name, json.loads((wk / "transactions.json").read_text()), \
                    json.loads(cp.read_text())


def test_cache_and_snapshot_agree_on_every_past_transaction():
    if not (_SNAP / "league_chain.json").exists() or not _CACHE.exists():
        return _skip("no snapshot / cache")
    weeks = 0
    for season, week, snap, cache in _past_weeks():
        weeks += 1
        for side, txs in (("snapshot", snap), ("cache", cache)):
            phantom = [t["transaction_id"] for t in txs
                       if (t.get("status") or "complete") != "complete" and t.get("drops")]
            assert not phantom, f"{side} {season} {week}: phantom drops on {phantom}"
        key = lambda t: str(t.get("transaction_id"))  # noqa: E731
        assert sorted(snap, key=key) == sorted(cache, key=key), f"{season} {week} differs"
    assert weeks >= 80, weeks        # 2021-25: every finished week has a cached feed


TESTS = [
    test_only_transactions_that_did_not_happen_lose_their_drops,
    test_a_cached_feed_is_served_and_healed_without_its_phantom_drops,
    test_cache_and_snapshot_agree_on_every_past_transaction,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall phantom-drop checks passed")
