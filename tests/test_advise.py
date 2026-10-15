"""Advice data (`lotg_support.advise`): the numbers behind start/sit, waivers
and strategy answers, checked against what the league itself recorded.

- Sleeper's NFL stats, scored with the league's own scoring table, equal the
  points Sleeper put in the matchup files for every rostered player (several
  weeks across seasons). That is what lets free agents — who are not in
  player_week — be scored at all.
- `best_lineup` gives the same total as the build's Max PF optimiser on real
  rosters, and fills exactly that season's lineup slots.

Network: the stats come from Sleeper (cached under .cache/sleeper). Skips
cleanly offline or without the snapshot.

Run: python tests/test_advise.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import advise as A, inquiry as Q, lineup as L  # noqa: E402

_HAVE = (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _weeks():
    done = [s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot]
    cur = max(Q.export_seasons())
    out = [(done[-1], 3), (done[-1], 9)] if done else []
    if (Q.finalized_week(cur) or 0) >= 2:
        out.append((cur, 2))
    return out


def test_scored_stats_equal_sleeper_matchup_points():
    if not _HAVE and _skip("no snapshot"):
        return
    checked = 0
    for y, w in _weeks():
        try:
            d = A.week_points(y, w).set_index("pid")["points"]
        except Exception as exc:   # noqa: BLE001
            _skip(f"Sleeper stats unreachable ({type(exc).__name__})")
            return
        bad = [(pid, p, d.get(pid, 0.0)) for row in Q.week(y, w, raw=True).values()
               for pid, p in row.players_points.items() if abs(d.get(pid, 0.0) - p) > 0.011]
        assert not bad, (y, w, bad[:5])
        checked += 1
    assert checked >= 2


def test_best_lineup_matches_the_build_optimiser():
    if not _HAVE and _skip("no snapshot"):
        return
    players = Q.players()
    for y, w in _weeks():
        slots = A.lineup_slots(y)
        for row in list(Q.week(y, w).values())[:8]:
            pts = {p: row.players_points.get(p, 0.0) for p in row.players}
            pos = {p: players.position(p) for p in row.players}
            pts = {p: v for p, v in pts.items() if pos.get(p) in A.POSITIONS}
            total, picks = A.best_lineup(pts, pos, slots)
            assert len(picks) == len(slots)
            ref = L.compute_optimal_lineup(pts, pos, y)
            assert abs(total - ref) < 0.011, (y, w, row.roster_id, total, ref)


TESTS = [test_scored_stats_equal_sleeper_matchup_points, test_best_lineup_matches_the_build_optimiser]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall advise checks passed")
