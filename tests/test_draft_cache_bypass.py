"""Live-draft cache-bypass guard (lotg_support.sleeper.SleeperClient).

The on-disk cache exists for immutable Sleeper responses, but a draft is mutable
until it completes: fetched while `pre_draft` its /draft/{id}/picks returns an
empty list. Without a bypass that empty response gets cached and reused forever,
so a draft that fills in later never shows its picks — this is exactly why the
2026 rookie draft read Unknown / 1.??. The build registers the LIVE league's
draft ids in `no_cache_draft_ids`; those `/draft/{id}` and `/draft/{id}/picks`
URLs must then skip the cache while every other cacheable URL still caches.

Run: python tests/test_draft_cache_bypass.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support.sleeper import SleeperClient  # noqa: E402
from lotg_support.utils import HttpConfig  # noqa: E402

LIVE_LEAGUE = "111111111111111111"
PAST_LEAGUE = "999999999999999999"
LIVE_DRAFT = "aaaaaaaaaaaaaaaaaa"
PAST_DRAFT = "bbbbbbbbbbbbbbbbbb"


def _client(tmp: Path) -> SleeperClient:
    return SleeperClient(LIVE_LEAGUE, HttpConfig(), cache_dir=tmp)


def test_registered_live_draft_bypasses_cache(tmp_path=None):
    tmp = tmp_path or Path("/tmp")
    sc = _client(tmp)
    sc.no_cache_draft_ids.add(LIVE_DRAFT)
    # Both the draft object and its picks for the live draft must skip the cache.
    assert sc._should_cache(sc._url(f"/draft/{LIVE_DRAFT}")) is False
    assert sc._should_cache(sc._url(f"/draft/{LIVE_DRAFT}/picks")) is False


def test_unregistered_past_draft_still_caches(tmp_path=None):
    tmp = tmp_path or Path("/tmp")
    sc = _client(tmp)
    sc.no_cache_draft_ids.add(LIVE_DRAFT)
    # A past-season (immutable) draft is not registered — it must stay cacheable.
    assert sc._should_cache(sc._url(f"/draft/{PAST_DRAFT}")) is True
    assert sc._should_cache(sc._url(f"/draft/{PAST_DRAFT}/picks")) is True


def test_empty_registry_caches_all_drafts(tmp_path=None):
    tmp = tmp_path or Path("/tmp")
    sc = _client(tmp)
    # No live draft registered (e.g. build before the draft loop) -> unchanged
    # behavior: draft endpoints cache as before.
    assert sc._should_cache(sc._url(f"/draft/{LIVE_DRAFT}/picks")) is True


def test_current_league_and_players_still_never_cache(tmp_path=None):
    tmp = tmp_path or Path("/tmp")
    sc = _client(tmp)
    sc.no_cache_draft_ids.add(LIVE_DRAFT)
    # The pre-existing no-cache markers are untouched by the draft bypass.
    assert sc._should_cache(sc._url(f"/league/{LIVE_LEAGUE}/rosters")) is False
    assert sc._should_cache(sc._url("/players/nfl")) is False
    # A historical league's endpoints remain cacheable.
    assert sc._should_cache(sc._url(f"/league/{PAST_LEAGUE}/rosters")) is True


def test_no_cache_dir_never_caches(tmp_path=None):
    # Without a cache_dir the client always hits the API — bypass logic is moot.
    sc = SleeperClient(LIVE_LEAGUE, HttpConfig(), cache_dir=None)
    sc.no_cache_draft_ids.add(LIVE_DRAFT)
    assert sc._should_cache(sc._url(f"/draft/{LIVE_DRAFT}/picks")) is False


if __name__ == "__main__":
    for fn in (
        test_registered_live_draft_bypasses_cache,
        test_unregistered_past_draft_still_caches,
        test_empty_registry_caches_all_drafts,
        test_current_league_and_players_still_never_cache,
        test_no_cache_dir_never_caches,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all draft-cache-bypass checks passed")
