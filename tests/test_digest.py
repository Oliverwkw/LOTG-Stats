"""Phase 14: weekly-digest engine tests.

Exercises ranking, leaderboard-crossing detection, on-pace projection, and the
in-season gate on small synthetic frames (no build required). A final smoke
test runs the whole snapshot pipeline against the real committed exports/ when
present, and SKIPS cleanly otherwise so this is safe in any checkout.

Run: PYTHONPATH=src:lib python tests/test_digest.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


# ---------------------------------------------------------------------------
def check_ranking_order_and_missing():
    df = pd.DataFrame({
        "Player": ["A", "B", "C", "D"],
        "Points": [100.0, 250.0, "N/A", 175.0],
    })
    ranked = D.rank_entities(df, "Player", D.TrackedStat("Points", "pts"))
    order = [r.entity for r in ranked]
    ok = _ok("higher-is-better order + missing dropped", order == ["B", "D", "A"],
             f"got {order}")
    low = D.rank_entities(df, "Player", D.TrackedStat("Points", "pts", higher_is_better=False))
    ok &= _ok("lower-is-better order", [r.entity for r in low] == ["A", "D", "B"])
    return ok


def check_high_end_crossing():
    stat = D.TrackedStat("Max PF", "all-time Max PF", windows=("high",))
    prev = {"teams": {"Max PF": [
        {"entity": "shmuel256", "value": 300},
        {"entity": "BROsenzweig", "value": 290},
    ]}}
    curr = {"teams": {"Max PF": [
        {"entity": "BROsenzweig", "value": 305},
        {"entity": "shmuel256", "value": 300},
    ]}}
    # Point diff at the real TEAM_STATS Max PF entry.
    crossings = D._diff_one_stat("teams", "all-time Max PF",
                                 prev["teams"]["Max PF"], curr["teams"]["Max PF"],
                                 ("high",), D.DEFAULT_WINDOW)
    ok = _ok("one high-end crossing detected", len(crossings) == 1, f"got {len(crossings)}")
    if crossings:
        c = crossings[0]
        ok &= _ok("mover/passed/rank correct",
                  c.mover == "BROsenzweig" and c.passed == "shmuel256" and c.rank == 1,
                  c.sentence())
        ok &= _ok("sentence reads as an overtake", "overtakes" in c.sentence())
    return ok


def check_low_end_crossing():
    # Lower Points = worse. Player E drops below F into the bottom of the board.
    prev = [
        {"entity": "T", "value": 50},
        {"entity": "F", "value": 20},
        {"entity": "E", "value": 25},
    ]
    curr = [
        {"entity": "T", "value": 50},
        {"entity": "E", "value": 22},   # E fell below F
        {"entity": "F", "value": 21},
    ]
    crossings = D._diff_one_stat("players", "all-time points", prev, curr,
                                 ("low",), D.DEFAULT_WINDOW)
    # F is now last (1st-lowest); it slipped past E.
    got = [(c.mover, c.passed, c.rank) for c in crossings]
    ok = _ok("low-end crossing detected", ("F", "E", 1) in got, f"got {got}")
    if crossings:
        ok &= _ok("low-end sentence reads as a slip",
                  any("lowest" in c.sentence() for c in crossings))
    return ok


def check_no_crossing_when_stable():
    board = [{"entity": "A", "value": 3}, {"entity": "B", "value": 2}, {"entity": "C", "value": 1}]
    crossings = D._diff_one_stat("teams", "x", board, board, ("high", "low"), D.DEFAULT_WINDOW)
    return _ok("stable board yields no crossings", crossings == [], f"got {len(crossings)}")


def check_new_entity_no_false_pass():
    prev = [{"entity": "A", "value": 3}]
    curr = [{"entity": "Z", "value": 9}, {"entity": "A", "value": 3}]
    crossings = D._diff_one_stat("players", "x", prev, curr, ("high",), D.DEFAULT_WINDOW)
    # Z is brand new (not in prev) -> must not be reported as passing A.
    return _ok("new entity not reported as a crossing", crossings == [], f"got {crossings}")


def check_in_season_gate():
    tw_empty = pd.DataFrame({"Year": [], "Week": []})
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026]})
    snap = D.build_snapshot(pd.DataFrame({"Player": [], "Points": []}),
                            pd.DataFrame({"Team": [], "Points": []}), ty, tw_empty)
    ok = _ok("offseason -> not in season", not D.is_in_season(snap))
    tw = pd.DataFrame({"Year": [2026, 2026], "Week": [1, 2]})
    snap2 = D.build_snapshot(pd.DataFrame({"Player": [], "Points": []}),
                             pd.DataFrame({"Team": [], "Points": []}), ty, tw)
    ok &= _ok("2 weeks played -> in season", D.is_in_season(snap2))
    ok &= _ok("weeks_completed counted", snap2["meta"]["weeks_completed"] == 2)
    return ok


def check_projection_ranks_against_history():
    # 2 completed seasons + an in-progress one at half pace of a leading year.
    team_year = pd.DataFrame({
        "Team": ["A", "A", "A"],
        "Year": [2024, 2025, 2026],
        "Hardship": [100.0, 60.0, 55.0],   # 2026 is partial
    })
    team_week = pd.DataFrame({
        "Year": [2024] * 14 + [2025] * 14 + [2026] * 7,
        "Week": list(range(1, 15)) + list(range(1, 15)) + list(range(1, 8)),
    })
    proj = D.project_end_of_season(team_year, team_week,
                                   stats=(D.TrackedStat("Hardship", "yearly hardship"),))
    ok = _ok("one projection produced", len(proj) == 1, f"got {len(proj)}")
    if proj:
        p = proj[0]
        # 55 over 7 weeks -> horizon 14 -> ~110 projected, the highest ever.
        ok &= _ok("projected value extrapolated", abs(p.projected - 110.0) < 1e-6,
                  f"projected={p.projected}")
        ok &= _ok("ranked 1st-highest vs history (100, 60)", p.rank == 1 and p.total == 3,
                  p.sentence())
    # Offseason -> no projections.
    tw0 = pd.DataFrame({"Year": [2024] * 14, "Week": list(range(1, 15))})
    ty0 = pd.DataFrame({"Team": ["A", "A"], "Year": [2024, 2026], "Hardship": [100.0, 0.0]})
    empty = D.project_end_of_season(ty0, tw0)
    ok &= _ok("no completed weeks -> no projections", empty == [])
    return ok


def check_render_html_smoke():
    c = D.Crossing("teams", "all-time Max PF", "high", 1, "BRO", "shmuel", 305.0)
    p = D.Projection("A", "yearly hardship", 110.0, 1, 3, True)
    html = D.render_digest_html([c], [p], {"season": 2026, "weeks_completed": 7})
    ok = _ok("html contains crossing", "overtakes" in html)
    ok &= _ok("html contains projection", "on pace" in html)
    ok &= _ok("html contains header week", "week 7" in html)
    empty = D.render_digest_html([], [], {"season": 2026, "weeks_completed": 7})
    ok &= _ok("empty digest has fallback copy", "No leaderboard changes" in empty)
    return ok


def check_real_exports_smoke():
    exports = Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))
    need = ["player_all_time", "team_all_time", "team_year", "team_week"]
    if not all((exports / f"{n}.csv").exists() for n in need):
        print("  [SKIP] real-exports smoke — no build present")
        return True
    frames = {n: pd.read_csv(exports / f"{n}.csv", low_memory=False) for n in need}
    snap = D.build_snapshot(frames["player_all_time"], frames["team_all_time"],
                            frames["team_year"], frames["team_week"])
    ok = _ok("snapshot has player + team sections",
             bool(snap["players"]) and bool(snap["teams"]))
    ok &= _ok("Points ranking non-empty for players",
              len(snap["players"].get("Points", [])) > 0)
    # Diffing a snapshot against itself must yield zero crossings.
    ok &= _ok("self-diff yields no crossings", D.diff_snapshots(snap, snap) == [])
    return ok


def run_all() -> bool:
    tests = [
        check_ranking_order_and_missing,
        check_high_end_crossing,
        check_low_end_crossing,
        check_no_crossing_when_stable,
        check_new_entity_no_false_pass,
        check_in_season_gate,
        check_projection_ranks_against_history,
        check_render_html_smoke,
        check_real_exports_smoke,
    ]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_digest_engine():
    """pytest entrypoint."""
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
