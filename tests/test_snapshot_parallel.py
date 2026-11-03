"""snapshot_all writes the same tree whether its seasons run one by one or side by side.

The seasons are fetched in parallel (each is ~55 sequential GETs). This drives it
with a fake Sleeper client and compares every file it writes with what the old
sequential loop wrote for the same responses.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import snapshot as S  # noqa: E402

_LEAGUES = {"L1": ("2023", None), "L2": ("2024", "L1"), "L3": ("2025", "L2")}
_WEEKS = {"L1": 3, "L2": 2, "L3": 4}


class _FakeClient:
    seen_threads: set = set()

    def __init__(self, league_id, cfg):
        self.league_id = league_id

    def players_nfl(self):
        return {"1": {"b": 1, "a": 2}}

    def league(self, lid):
        season, prev = _LEAGUES[lid]
        return {"league_id": lid, "season": season, "previous_league_id": prev}

    def users(self, lid):
        return [{"user_id": f"u-{lid}"}]

    def rosters(self, lid):
        return [{"roster_id": 1, "owner_id": f"u-{lid}"}]

    def matchups(self, week, lid):
        _FakeClient.seen_threads.add(threading.get_ident())
        return [{"week": week, "lid": lid}] if week <= _WEEKS[lid] else []

    def transactions(self, week, lid):
        return [{"tx": f"{lid}-{week}"}]


def _run(tmp: Path):
    orig = (S.SleeperClient, S._download_stats_week, S.load_nflverse_injuries, S.load_dynastyprocess_playerids)
    S.SleeperClient = _FakeClient
    S._download_stats_week = lambda cfg, season, week: [{"season": season, "week": week}]
    S.load_nflverse_injuries = lambda ext, season: pd.DataFrame({"season": [season]})
    S.load_dynastyprocess_playerids = lambda ext: pd.DataFrame({"sleeper_id": ["1"]})
    try:
        S.snapshot_all(tmp, "L3", min_season=None, max_season=None)
    finally:
        S.SleeperClient, S._download_stats_week, S.load_nflverse_injuries, S.load_dynastyprocess_playerids = orig
    snap = tmp / "exports" / "snapshot"
    return {p.relative_to(snap).as_posix(): p.read_text() for p in sorted(snap.rglob("*"))
            if p.is_file() and p.name != S.SNAPSHOT_META_NAME}


def _expected():
    out = {"sleeper_players_nfl.json": json.dumps(S.canonical_players({"1": {"b": 1, "a": 2}}), indent=2)
           if hasattr(S, "canonical_players") else json.dumps({"1": {"b": 1, "a": 2}}, indent=2),
           "dynastyprocess_playerids.csv": "sleeper_id\n1\n"}
    chain = [{"league_id": lid, "season": s, "previous_league_id": p} for lid, (s, p) in _LEAGUES.items()]
    out["league_chain.json"] = json.dumps(chain, indent=2)
    for lg in chain:
        lid, season = lg["league_id"], lg["season"]
        d = f"season_{season}"
        out[f"{d}/league.json"] = json.dumps(lg, indent=2)
        out[f"{d}/nflverse_injuries.csv"] = f"season\n{season}\n"
        out[f"{d}/users.json"] = json.dumps([{"user_id": f"u-{lid}"}], indent=2)
        out[f"{d}/rosters.json"] = json.dumps([{"roster_id": 1, "owner_id": f"u-{lid}"}], indent=2)
        for w in range(1, _WEEKS[lid] + 1):
            wd = f"{d}/weeks/week_{w:02d}"
            out[f"{wd}/matchups.json"] = json.dumps([{"week": w, "lid": lid}], indent=2)
            out[f"{wd}/transactions.json"] = json.dumps([{"tx": f"{lid}-{w}"}], indent=2)
            out[f"{wd}/stats_nfl.json"] = json.dumps([{"season": int(season), "week": w}], indent=2)
    return out


def test_parallel_snapshot_writes_the_sequential_tree():
    with tempfile.TemporaryDirectory() as d:
        got = _run(Path(d))
    want = _expected()
    assert sorted(got) == sorted(want)
    for k in want:
        assert got[k] == want[k], k


if __name__ == "__main__":
    test_parallel_snapshot_writes_the_sequential_tree()
    print("ok")
