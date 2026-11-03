"""The offline harness (scripts/offline_build.py) has the scope its docstring states.

It replays seasons 2020-2025 from committed files only: Sleeper from `.cache/sleeper`
(sha1 of the URL) and the snapshot's /players/nfl, nflverse from `.cache`, 2020 from
the ESPN backfill. It points the build at the 2025 league so the live season (never
cached: its endpoints change every week) is not walked. Out of scope, by design: the
live season, KTC (reads N/A offline) and anything else the network serves.

This pins that statement against the committed data, so a cache gap shows here as a
named missing endpoint instead of a silently thinner offline build.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BASE = "https://api.sleeper.app/v1"
_HARNESS = _ROOT / "scripts" / "offline_build.py"
_CHAIN = _ROOT / "exports" / "snapshot" / "league_chain.json"
_CACHE = _ROOT / ".cache" / "sleeper"
LAST_OFFLINE_SEASON = 2025
# The regular season + playoffs the build walks (week 18 is not in the league calendar).
_WEEKS = range(1, 18)


def _harness_config():
    src = _HARNESS.read_text()
    lid = re.search(r'_cfg\["league_id"\]\s*=\s*"(\d+)"', src).group(1)
    max_season = int(re.search(r'_cfg\["max_season"\]\s*=\s*(\d+)', src).group(1))
    return lid, max_season


def _cached(path: str) -> bool:
    p = _CACHE / f"{hashlib.sha1((_BASE + path).encode()).hexdigest()}.json"
    return p.exists() and p.stat().st_size > 0


def test_harness_targets_the_last_offline_season():
    if not _CHAIN.exists():
        return
    lid, max_season = _harness_config()
    assert max_season == LAST_OFFLINE_SEASON
    by_season = {int(x["season"]): str(x["league_id"]) for x in json.loads(_CHAIN.read_text())}
    assert by_season.get(LAST_OFFLINE_SEASON) == lid, (
        f"offline_build.py points at league {lid}, the chain's {LAST_OFFLINE_SEASON} league is "
        f"{by_season.get(LAST_OFFLINE_SEASON)}")


def test_every_in_scope_sleeper_endpoint_is_cached():
    if not (_CHAIN.exists() and _CACHE.exists()):
        return
    missing = []
    for lg in json.loads(_CHAIN.read_text()):
        season, lid = int(lg["season"]), str(lg["league_id"])
        if season > LAST_OFFLINE_SEASON:
            continue
        paths = [f"/league/{lid}", *(f"/league/{lid}/{e}" for e in
                 ("users", "rosters", "traded_picks", "losers_bracket", "drafts"))]
        paths += [f"/league/{lid}/{e}/{w}" for e in ("matchups", "transactions") for w in _WEEKS]
        missing += [f"{season} {p}" for p in paths if not _cached(p)]
    assert not missing, "offline replay would miss: " + ", ".join(missing[:20])


def test_the_live_season_is_out_of_scope():
    """Nothing caches the live league: it is mutable (sleeper.SleeperClient's no-cache list)."""
    if not (_CHAIN.exists() and _CACHE.exists()):
        return
    live = [x for x in json.loads(_CHAIN.read_text()) if int(x["season"]) > LAST_OFFLINE_SEASON]
    for lg in live:
        assert not _cached(f"/league/{lg['league_id']}/rosters")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
