"""The league's 'Startup draft players remaining' counts every startup player on
ANY roster, not the sum of each team's own picks.

A team's count is its own startup picks still on its roster, so a startup player
who is traded or picked up elsewhere leaves his drafter's count. Summing the team
counts therefore read every such move as the player leaving the league: 2026 week
1 went 9 -> 6 while Tua (LWebs53's pick) sat on Oliverwkw and Tony Pollard
(BROsenzweig's) on stevenb123. `_startup_league_remaining` counts the union.

Run: PYTHONPATH=src:lib python tests/test_startup_league_remaining.py
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

import pandas as pd  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _fixture():
    # A drafted p1 + p2, B drafted p3. p9 was never a startup pick.
    picks = [
        {"_is_startup": True, "_player_id": "p1", "Final Team": "A"},
        {"_is_startup": True, "_player_id": "p2", "Final Team": "A"},
        {"_is_startup": True, "_player_id": "p3", "Final Team": "B"},
        {"_is_startup": False, "_player_id": "p9", "Final Team": "B"},
    ]
    pw = pd.DataFrame([
        # 2025 week 17: everyone at home.
        ("A", "p1", 2025, 17), ("A", "p2", 2025, 17), ("B", "p3", 2025, 17),
        ("B", "p9", 2025, 17),
        # 2026 week 1: p2 traded to B, p3 dropped to free agency.
        ("A", "p1", 2026, 1), ("B", "p2", 2026, 1), ("B", "p9", 2026, 1),
        # 2026 week 2: A picks p3 back up off waivers.
        ("A", "p1", 2026, 2), ("B", "p2", 2026, 2), ("A", "p3", 2026, 2),
    ], columns=["Team", "Player ID", "Year", "Week"])
    return picks, pw


def check_league_counts_every_roster():
    picks, pw = _fixture()
    s, r, _wk, _lt = lotg._startup_remaining_maps(picks, pw)
    league = lotg._startup_league_remaining(s, r)
    team_sum = {(y, w): sum(lotg._startup_remaining_count(s, r, t, y, w) for t in ("A", "B"))
                for (y, w) in league}
    ok = _ok("all three home at 2025 week 17", league[(2025, 17)] == 3, league)
    ok &= _ok("a traded startup player still counts for the league",
              league[(2026, 1)] == 2, league)
    ok &= _ok("...while the old team-sum lost him", team_sum[(2026, 1)] == 1, team_sum)
    ok &= _ok("a startup player re-added by a non-drafter counts again",
              league[(2026, 2)] == 3, league)
    ok &= _ok("a non-startup player never counts",
              all(v <= 3 for v in league.values()), league)
    return ok


def check_season_end_reads_last_scored_week():
    picks, pw = _fixture()
    s, r, _wk, _lt = lotg._startup_remaining_maps(picks, pw)
    end = lotg._startup_league_season_end(lotg._startup_league_remaining(s, r))
    ok = _ok("2025 season end = week 17", end.get(2025) == 3, end)
    ok &= _ok("2026 in progress = its latest week (2)", end.get(2026) == 3, end)
    ok &= _ok("a year with no scored week is absent (N/A)", 2027 not in end, end)
    ok &= _ok("empty inputs -> empty map",
              lotg._startup_league_remaining({}, {}) == {})
    return ok


def run_all():
    tests = [check_league_counts_every_roster, check_season_end_reads_last_scored_week]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_startup_league_remaining():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
