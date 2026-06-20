"""Offline build harness (no network).

Serves every Sleeper/external HTTP call from the committed `.cache/sleeper`
tree and `exports/snapshot/` so the FULL build can run for seasons 2020-2025
without touching the network (the sandbox has no Sleeper egress). Targets the
2025 league id so the live 2026 league (the only uncached chain link) is never
walked.

Usage: PYTHONPATH=src:lib python3 scripts/offline_build.py
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".cache" / "sleeper"
SNAP = REPO / "exports" / "snapshot"

import lotg_support.utils as _utils

_orig_fetch = _utils.fetch_json
_misses: dict[str, int] = {}


def _offline_fetch(url, cfg, logger=None):
    # 1) Sleeper on-disk cache (sha1 of the url), covers all of 2021-2025 + drafts.
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cp = CACHE / f"{h}.json"
    if cp.exists() and cp.stat().st_size > 0:
        try:
            return json.loads(cp.read_text())
        except Exception:
            pass
    # 2) The giant /players/nfl feed: from the committed snapshot.
    if url.endswith("/players/nfl"):
        p = SNAP / "sleeper_players_nfl.json"
        if p.exists():
            return json.loads(p.read_text())
    # 3) Anything else (live 2026 league, KTC live, etc.): unavailable offline.
    _misses[url] = _misses.get(url, 0) + 1
    return None


_utils.fetch_json = _offline_fetch
# external.py / sleeper.py imported fetch_json by name — patch those bindings too.
for _modname in ("lotg_support.external", "lotg_support.sleeper", "lotg_support.snapshot",
                 "lotg_support.ktc"):
    try:
        _m = __import__(_modname, fromlist=["fetch_json"])
        if hasattr(_m, "fetch_json"):
            _m.fetch_json = _offline_fetch
    except Exception:
        pass

import yaml
import lotg

# Point the build at the 2025 league (last fully-cached season) so the live
# 2026 link is never walked. Rewrite config in-memory via the loader.
_cfg_path = REPO / "config" / "league.yaml"
_cfg = yaml.safe_load(_cfg_path.read_text())
_cfg["league_id"] = "1192931349575991296"  # 2025 league id (cached)
_cfg["min_season"] = 2019
_cfg["max_season"] = 2025

_orig_safe_load = yaml.safe_load


def _patched_safe_load(s):
    return _cfg


yaml.safe_load = _patched_safe_load

if __name__ == "__main__":
    os.environ["LOTG_MODE"] = "build"
    try:
        lotg.main()
    finally:
        if _misses:
            print(f"\n[offline] {sum(_misses.values())} unresolved fetches across "
                  f"{len(_misses)} urls:")
            for u, n in sorted(_misses.items(), key=lambda kv: -kv[1])[:40]:
                print(f"  {n:4} {u}")
