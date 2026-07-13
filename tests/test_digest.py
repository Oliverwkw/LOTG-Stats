"""Phase 14: weekly-digest engine tests.

Exercises column auto-discovery, all-time crossing detection (both leaderboard
ends), on-pace projection with the week-3 yearly gate, phrasing catalog, and the
in-season gate on small synthetic frames. A final smoke test runs the whole
snapshot pipeline against the real committed exports/ when present, and SKIPS
cleanly otherwise so it's safe in any checkout.

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
def check_discovery_drops_non_numeric():
    df = pd.DataFrame({
        "Team": ["A", "B", "C"],
        "Points": [100.0, 250.0, 175.0],
        "Record": ["3-1", "2-2", "1-3"],          # string -> dropped
        "Result": ["Champion", "8th", "5th"],      # string -> dropped
        "Year": [2024, 2024, 2024],                # key -> dropped
        "Win %": ["75%", "50%", "25%"],            # percent -> kept
    })
    cols = set(D.discover_numeric_columns(df, "Team"))
    return _ok("only numeric non-key cols discovered", cols == {"Points", "Win %"},
               f"got {sorted(cols)}")


def check_ranking_order_and_missing():
    df = pd.DataFrame({"Player": ["A", "B", "C", "D"],
                       "Points": [100.0, 250.0, "N/A", 175.0]})
    order = [e["entity"] for e in D.rank_column(df, "Player", "Points")]
    return _ok("descending order + missing dropped", order == ["B", "D", "A"], f"got {order}")


def check_high_end_crossing():
    names = ["shmuel256", "BROsenzweig", "C", "D", "E", "F"]
    prev = [{"entity": n, "value": 300 - 10 * i} for i, n in enumerate(names)]
    # Swap the top two only.
    curr = [{"entity": "BROsenzweig", "value": 305}, {"entity": "shmuel256", "value": 300}] \
        + [{"entity": n, "value": 280 - 10 * i} for i, n in enumerate(["C", "D", "E", "F"])]
    cx = D._column_crossings("teams", "Max PF", prev, curr, D.WINDOW)
    ok = _ok("one high-end crossing", len(cx) == 1, f"got {len(cx)}")
    if cx:
        c = cx[0]
        ok &= _ok("mover/passed/rank + wording",
                  c.mover == "BROsenzweig" and c.passed == "shmuel256"
                  and c.rank == 1 and "highest" in c.sentence(), c.sentence())
    return ok


def check_low_end_crossing():
    prev = [{"entity": "T", "value": 50}, {"entity": "F", "value": 20}, {"entity": "E", "value": 25}]
    curr = [{"entity": "T", "value": 50}, {"entity": "E", "value": 22}, {"entity": "F", "value": 21}]
    cx = D._column_crossings("players", "Points", prev, curr, D.WINDOW)
    got = [(c.mover, c.passed, c.rank, c.end) for c in cx]
    return _ok("low-end crossing (F to 1st-lowest, passing E)",
               ("F", "E", 1, "low") in got, f"got {got}")


def check_no_crossing_when_stable():
    board = [{"entity": "A", "value": 3}, {"entity": "B", "value": 2}, {"entity": "C", "value": 1}]
    return _ok("stable board -> no crossings",
               D._column_crossings("teams", "x", board, board, D.WINDOW) == [])


def check_new_entity_no_false_pass():
    prev = [{"entity": "A", "value": 3}]
    curr = [{"entity": "Z", "value": 9}, {"entity": "A", "value": 3}]
    return _ok("new entity not reported",
               D._column_crossings("players", "x", prev, curr, D.WINDOW) == [])


def check_in_season_gate():
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026], "Points": [10.0]})
    empty_players = pd.DataFrame({"Player": ["A", "B"], "Points": [1.0, 2.0]})
    empty_teams = pd.DataFrame({"Team": ["A", "B"], "Points": [1.0, 2.0]})
    snap0 = D.build_snapshot(empty_players, empty_teams, ty, pd.DataFrame({"Year": [], "Week": []}))
    ok = _ok("offseason -> not in season", not D.is_in_season(snap0))
    tw = pd.DataFrame({"Year": [2026, 2026], "Week": [1, 2]})
    snap2 = D.build_snapshot(empty_players, empty_teams, ty, tw)
    ok &= _ok("2 weeks -> in season + counted",
              D.is_in_season(snap2) and snap2["meta"]["weeks_completed"] == 2)
    return ok


def check_projection_week_gate_and_rank():
    # 3 completed seasons; in-progress 2026 at 7 of 14 weeks.
    team_year = pd.DataFrame({
        "Team": ["A"] * 4, "Year": [2023, 2024, 2025, 2026],
        "Hardship": [40.0, 100.0, 60.0, 55.0],   # 2026 partial -> projects to 110
        "Win %": [0.5, 0.6, 0.4, 0.9],           # rate: projected as-is (0.9)
    })
    player_year = pd.DataFrame({"Player": [], "Year": []})
    league_year = pd.DataFrame({"Year": []})

    tw_week2 = pd.DataFrame({"Year": [2023] * 14 + [2026] * 2,
                             "Week": list(range(1, 15)) + [1, 2]})
    early = D.project_on_pace(player_year, team_year, league_year, tw_week2)
    ok = _ok("no yearly items before week 3", early == [], f"got {len(early)}")

    tw_week7 = pd.DataFrame({"Year": [2023] * 14 + [2024] * 14 + [2025] * 14 + [2026] * 7,
                             "Week": list(range(1, 15)) * 3 + list(range(1, 8))})
    proj = D.project_on_pace(player_year, team_year, league_year, tw_week7, window=2)
    hard = [p for p in proj if p.column == "Hardship"]
    ok &= _ok("Hardship projected to 110, 1st-highest",
              len(hard) == 1 and abs(hard[0].projected - 110.0) < 1e-6
              and hard[0].rank == 1 and hard[0].end == "high", hard[0].sentence() if hard else "none")
    winp = [p for p in proj if p.column == "Win %"]
    ok &= _ok("Win % projected as-is (0.9), not scaled",
              len(winp) == 1 and abs(winp[0].projected - 0.9) < 1e-6, winp[0].sentence() if winp else "none")
    return ok


def check_pace_diff_reports_only_changes():
    p_stay = D.Projection("teams", "A", "Points", "high", 2, 40, 900.0)
    p_move = D.Projection("teams", "B", "Points", "high", 1, 40, 950.0)  # was 2nd, now 1st
    p_new = D.Projection("teams", "C", "Hardship", "low", 1, 40, 5.0)    # newly notable
    prior = D.pace_rank_map([
        D.Projection("teams", "A", "Points", "high", 2, 40, 880.0),
        D.Projection("teams", "B", "Points", "high", 2, 40, 870.0),
    ])
    changed = D.diff_pace(prior, [p_stay, p_move, p_new])
    movers = {(c.entity, c.column) for c in changed}
    ok = _ok("unchanged standing suppressed", ("A", "Points") not in movers, f"got {movers}")
    ok &= _ok("moved standing reported", ("B", "Points") in movers)
    ok &= _ok("newly-notable standing reported", ("C", "Hardship") in movers)
    return ok


def check_rate_classification():
    rates = ["Avg points", "Win %", "Player average age", "Consistency percentile",
             "Starter scoring floor", "PPG starter"]
    cums = ["Points", "Hardship", "Number of donuts", "Total trades", "Amount of FAAB spent"]
    ok = _ok("rate stats classified as rate", all(D.is_rate_stat(c) for c in rates))
    ok &= _ok("cumulative stats classified as cumulative", not any(D.is_rate_stat(c) for c in cums))
    return ok


def check_phrasing_catalog():
    pat = pd.DataFrame({"Player": ["A", "B"], "Points": [1.0, 2.0]})
    tat = pd.DataFrame({"Team": ["A", "B"], "Max PF": [1.0, 2.0]})
    py = pd.DataFrame({"Player": ["A", "B"], "Year": [2024, 2025], "Points": [1.0, 2.0]})
    ty = pd.DataFrame({"Team": ["A", "B"], "Year": [2024, 2025], "Hardship": [1.0, 2.0]})
    ly = pd.DataFrame({"Year": [2024, 2025], "PF": [1.0, 2.0]})
    rows = D.phrasing_catalog(pat, tat, py, ty, ly)
    scopes = {r["scope"] for r in rows}
    ok = _ok("catalog covers all-time + yearly scopes",
             any("all-time" in s for s in scopes) and any("on-pace" in s for s in scopes))
    ok &= _ok("every row has both phrasings",
              all(r["phrase_when_rises"] and r["phrase_when_falls"] for r in rows))
    return ok


def check_render_html_smoke():
    c = D.Crossing("teams", "Max PF", "high", 1, "BRO", "shmuel", 305.0)
    p = D.Projection("teams", "A", "Hardship", "high", 1, 3, 110.0)
    html = D.render_digest_html([c], [p], {"season": 2026, "weeks_completed": 7})
    ok = _ok("html has crossing + projection + week",
             "passes" in html and "on pace" in html and "week 7" in html)
    ok &= _ok("empty digest fallback",
              "No leaderboard changes" in D.render_digest_html([], [], {"season": 2026, "weeks_completed": 7}))
    return ok


def check_real_exports_smoke():
    exports = Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))
    need = ["player_all_time", "team_all_time", "team_year", "team_week"]
    if not all((exports / f"{n}.csv").exists() for n in need):
        print("  [SKIP] real-exports smoke — no build present")
        return True
    fr = {n: pd.read_csv(exports / f"{n}.csv", low_memory=False) for n in need}
    snap = D.build_snapshot(fr["player_all_time"], fr["team_all_time"], fr["team_year"], fr["team_week"])
    ok = _ok("snapshot discovered many player + team stats",
             len(snap["players"]) > 20 and len(snap["teams"]) > 40,
             f"players={len(snap['players'])} teams={len(snap['teams'])}")
    ok &= _ok("Points ranking present for players", len(snap["players"].get("Points", [])) > 100)
    ok &= _ok("self-diff yields no crossings", D.diff_snapshots(snap, snap) == [])
    return ok


def run_all() -> bool:
    tests = [
        check_discovery_drops_non_numeric,
        check_ranking_order_and_missing,
        check_high_end_crossing,
        check_low_end_crossing,
        check_no_crossing_when_stable,
        check_new_entity_no_false_pass,
        check_in_season_gate,
        check_projection_week_gate_and_rank,
        check_pace_diff_reports_only_changes,
        check_rate_classification,
        check_phrasing_catalog,
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
