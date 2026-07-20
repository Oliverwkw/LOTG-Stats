"""Phase 14: weekly-digest engine tests.

Covers column auto-discovery, per-section all-time crossings (players top/bottom
5; teams any-of-8, reported once), on-pace projection with the week-3 gate and
the weekly-counting exclusion, league_year's dynamic window, league_all_time
milestones, phrasing catalog, and the in-season gate — on small synthetic
frames. A final smoke test runs the whole pipeline against the real committed
exports/ when present, and SKIPS cleanly otherwise.

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

_PLAYERS = ("high", "low")


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


# ---------------------------------------------------------------------------
def check_discovery_drops_non_numeric():
    df = pd.DataFrame({
        "Team": ["A", "B", "C"], "Points": [100.0, 250.0, 175.0],
        "Record": ["3-1", "2-2", "1-3"], "Result": ["Champion", "8th", "5th"],
        "Year": [2024, 2024, 2024], "Win %": ["75%", "50%", "25%"],
    })
    cols = set(D.discover_numeric_columns(df, "Team"))
    return _ok("only numeric non-key cols discovered", cols == {"Points", "Win %"}, f"got {sorted(cols)}")


def check_ranking_order_and_missing():
    df = pd.DataFrame({"Player": ["A", "B", "C", "D"], "Points": [100.0, 250.0, "N/A", 175.0]})
    order = [e["entity"] for e in D.rank_column(df, "Player", "Points")]
    return _ok("descending order + missing dropped", order == ["B", "D", "A"], f"got {order}")


def check_player_high_low_crossings():
    names = ["s", "B", "C", "D", "E", "F"]
    prev = [{"entity": n, "value": 300 - 10 * i} for i, n in enumerate(names)]
    curr = [{"entity": "B", "value": 305}, {"entity": "s", "value": 300}] \
        + [{"entity": n, "value": 280 - 10 * i} for i, n in enumerate(["C", "D", "E", "F"])]
    cx = D._column_crossings("players", "Points", prev, curr, _PLAYERS, D.WINDOW, True)
    return _ok("player top-swap reports one high crossing",
               len(cx) == 1 and cx[0].mover == "B" and cx[0].end == "high", cx[0].sentence() if cx else "none")


def check_low_end_crossing():
    prev = [{"entity": "T", "value": 50}, {"entity": "F", "value": 20}, {"entity": "E", "value": 25}]
    curr = [{"entity": "T", "value": 50}, {"entity": "E", "value": 22}, {"entity": "F", "value": 21}]
    cx = D._column_crossings("players", "Points", prev, curr, _PLAYERS, D.WINDOW, True)
    got = [(c.mover, c.passed, c.rank, c.end) for c in cx]
    return _ok("low-end crossing (F to 1st-lowest, passing E)", ("F", "E", 1, "low") in got, f"got {got}")


def check_team_any_of_8_reported_once():
    # 8-team board; swap ranks 3 and 4. Team config = high-only, full board.
    names = [f"T{i}" for i in range(8)]
    prev = [{"entity": n, "value": 100 - 10 * i} for i, n in enumerate(names)]
    curr = [dict(e) for e in prev]
    curr[2], curr[3] = dict(curr[3]), dict(curr[2])
    curr[2]["value"], curr[3]["value"] = 75, 70   # T3 now ahead of T2
    cfg = D.CROSSING_CONFIG["teams"]
    cx = D._column_crossings("teams", "Max PF", prev, curr, cfg["ends"], cfg["window"], cfg["cap_half"])
    ok = _ok("mid-board team swap reported exactly once", len(cx) == 1, f"got {len(cx)}")
    if cx:
        ok &= _ok("reported as the riser at its new rank",
                  cx[0].mover == "T3" and cx[0].passed == "T2" and cx[0].rank == 3 and cx[0].end == "high",
                  cx[0].sentence())
    return ok


def check_new_entity_no_false_pass():
    prev = [{"entity": "A", "value": 3}]
    curr = [{"entity": "Z", "value": 9}, {"entity": "A", "value": 3}]
    return _ok("new entity not reported",
               D._column_crossings("players", "x", prev, curr, _PLAYERS, D.WINDOW, True) == [])


def check_in_season_gate():
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026], "Points": [10.0]})
    pl = pd.DataFrame({"Player": ["A", "B"], "Points": [1.0, 2.0]})
    tm = pd.DataFrame({"Team": ["A", "B"], "Points": [1.0, 2.0]})
    snap0 = D.build_snapshot(pl, tm, ty, pd.DataFrame({"Year": [], "Week": []}))
    ok = _ok("offseason -> not in season", not D.is_in_season(snap0))
    tw = pd.DataFrame({"Year": [2026, 2026], "Week": [1, 2]})
    snap2 = D.build_snapshot(pl, tm, ty, tw)
    ok &= _ok("2 weeks -> in season + counted", D.is_in_season(snap2) and snap2["meta"]["weeks_completed"] == 2)
    return ok


def check_projection_gate_scale_and_weekly_exclusion():
    seasons = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    team_year = pd.DataFrame({
        "Team": ["A"] * 7, "Year": seasons,
        "Hardship": [40, 100, 60, 70, 80, 90, 55.0],   # 2026 partial -> 110
        "Win %": [0.5, 0.6, 0.4, 0.5, 0.5, 0.5, 0.9],  # rate -> as-is
        "Times Highest score?": [1, 2, 1, 1, 1, 1, 3], # weekly-counting -> excluded
        "Losses from byes": [0, 1, 0, 1, 0, 1, 2],     # weekly-counting -> excluded
    })
    py = pd.DataFrame({"Player": [], "Year": []})
    ly = pd.DataFrame({"Year": []})
    weeks = [w for y in seasons[:-1] for w in range(1, 15)] + [1, 2]
    yrs = [y for y in seasons[:-1] for _ in range(14)] + [2026, 2026]
    early = D.project_on_pace(py, team_year, ly, pd.DataFrame({"Year": yrs, "Week": weeks}))
    ok = _ok("no yearly items before week 3", early == [], f"got {len(early)}")

    yrs7 = [y for y in seasons[:-1] for _ in range(14)] + [2026] * 7
    wk7 = [w for _ in seasons[:-1] for w in range(1, 15)] + list(range(1, 8))
    proj = D.project_on_pace(py, team_year, ly, pd.DataFrame({"Year": yrs7, "Week": wk7}))
    cols = {p.column for p in proj}
    ok &= _ok("Hardship projected + is 1st-highest",
              any(p.column == "Hardship" and abs(p.projected - 110) < 1e-6 and p.rank == 1 for p in proj))
    ok &= _ok("Win % projected as-is", any(p.column == "Win %" and abs(p.projected - 0.9) < 1e-6 for p in proj))
    ok &= _ok("weekly-counting stats excluded from on-pace",
              "Times Highest score?" not in cols and "Losses from byes" not in cols, f"got {sorted(cols)}")
    return ok


def check_boolean_flags_excluded_from_pace():
    # Per-season 0/1 flag (e.g. #363 "Rostered by champion?") must not project.
    seasons = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    py = pd.DataFrame({
        "Player": ["A"] * 7, "Year": seasons,
        "Points": [100, 200, 150, 180, 190, 210, 90.0],   # normal -> projects
        "Rostered by champion?": [0, 1, 0, 0, 1, 0, 0],    # boolean -> excluded
    })
    empty = pd.DataFrame({"Team": [], "Year": []})
    ly = pd.DataFrame({"Year": []})
    yrs = [y for y in seasons[:-1] for _ in range(14)] + [2026] * 7
    wk = [w for _ in seasons[:-1] for w in range(1, 15)] + list(range(1, 8))
    tw = pd.DataFrame({"Year": yrs, "Week": wk})
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026]})
    proj = D.project_on_pace(py, ty, ly, tw)
    cols = {p.column for p in proj}
    ok = _ok("boolean season flag excluded from on-pace", "Rostered by champion?" not in cols)
    ok &= _ok("normal player stat still projects", "Points" in cols, f"got {sorted(cols)}")
    ok &= _ok("_is_boolean detects 0/1 only", D._is_boolean([0.0, 1.0, 0.0]) and not D._is_boolean([0.0, 2.0]))
    return ok


def check_yearly_records_for_weekly_stats():
    # 3 completed seasons + in-progress 2026 at week 5. "Times One-man army?"
    # (weekly-counting) hits 6 this season, beating the prior best of 5 -> record.
    seasons = [2023, 2024, 2025, 2026]
    ty = pd.DataFrame({
        "Team": ["A", "A", "A", "A"], "Year": seasons,
        "Times One-man army?": [3, 5, 4, 6],   # 6 > prior max 5 -> record
        "Hardship": [40, 50, 45, 30.0],        # on-pace stat, not a record here
        "Rostered by champion?": [0, 1, 0, 0],  # boolean -> never a record
    })
    py = pd.DataFrame({"Player": [], "Year": []})
    ly = pd.DataFrame({"Year": []})
    tw = pd.DataFrame({"Year": [2023] * 14 + [2024] * 14 + [2025] * 14 + [2026] * 5,
                       "Week": list(range(1, 15)) * 3 + list(range(1, 6))})
    recs = D.yearly_records(py, ty, ly, tw)
    cols = {(r.entity, r.column, r.value) for r in recs}
    ok = _ok("weekly-counting record detected", ("A", "Times One-man army?", 6.0) in cols, f"got {cols}")
    ok &= _ok("boolean flag never a record", not any(r.column == "Rostered by champion?" for r in recs))
    ok &= _ok("on-pace stat not a record here", not any(r.column == "Hardship" for r in recs))
    # No record before week 3.
    tw2 = pd.DataFrame({"Year": [2023] * 14 + [2026] * 2, "Week": list(range(1, 15)) + [1, 2]})
    ok &= _ok("no records before week 3", D.yearly_records(py, ty, ly, tw2) == [])
    # Diff: unchanged record suppressed, grown/new record reported.
    prior = D.record_value_map([D.YearlyRecord("teams", "A", "Times One-man army?", 6.0)])
    ok &= _ok("unchanged record suppressed", D.diff_records(prior, recs) == [])
    grown = [D.YearlyRecord("teams", "A", "Times One-man army?", 7.0)]
    ok &= _ok("extended record reported", len(D.diff_records(prior, grown)) == 1)
    ok &= _ok("new record (no prior) reported", len(D.diff_records({}, recs)) == 1)
    return ok


def check_weekly_highlights():
    tw = pd.DataFrame({
        "Team": ["A", "B", "A", "B", "A", "B"],
        "Year": [2025, 2025, 2025, 2025, 2026, 2026],
        "Week": [1, 1, 2, 2, 1, 1],
        "PF": [100, 110, 120, 90, 200, 95.0],      # A 2026-wk1 = 200 = best ever
        "Highest score?": [0, 1, 1, 0, 1, 0],       # boolean -> skipped
    })
    ty = pd.DataFrame({"Team": ["A", "B"], "Year": [2026, 2026]})
    pw = pd.DataFrame({"Player": [], "Year": [], "Week": []})
    lw = pd.DataFrame({"Year": [], "Week": []})
    hl = D.weekly_highlights(pw, tw, lw, ty, window=2)
    got = [(h.entity, h.column, h.end, h.rank) for h in hl]
    ok = _ok("A's 200 is 1st-highest single week ever", ("A", "PF", "high", 1) in got, f"got {got}")
    ok &= _ok("B's 95 is 2nd-lowest single week ever (both ends work)", ("B", "PF", "low", 2) in got)
    ok &= _ok("boolean weekly flag skipped", not any(h.column == "Highest score?" for h in hl))
    ok &= _ok("sentence reads as single-week record",
              any("single week ever" in h.sentence() for h in hl))
    # Tie cap: a value shared by >5 week-rows is skipped on either end.
    tw2 = pd.DataFrame({
        "Team": list("ABCDEF"), "Year": [2025] * 5 + [2026],
        "Week": [1] * 6, "Ct": [3.0] * 6,   # 6 rows tied at 3 -> too common
    })
    ty2 = pd.DataFrame({"Team": ["F"], "Year": [2026]})
    ok &= _ok("value shared by >5 week-rows is skipped",
              D.weekly_highlights(pd.DataFrame({"Player": [], "Year": [], "Week": []}),
                                  tw2, pd.DataFrame({"Year": [], "Week": []}), ty2) == [])
    # Offseason (current season has no team_week rows) -> nothing.
    ty0 = pd.DataFrame({"Team": ["A"], "Year": [2027]})
    ok &= _ok("no highlights when current season has no weeks",
              D.weekly_highlights(pw, tw, lw, ty0) == [])
    return ok


def check_final_rankings():
    py = pd.DataFrame({
        "Player": ["A", "B", "A", "B", "A", "B"],
        "Year": [2023, 2023, 2024, 2024, 2025, 2025],
        "Points": [100, 90, 110, 80, 200, 70.0],          # A-2025=200 best, B-2025=70 worst
        "Times as Captain?": [1, 2, 1, 1, 3, 1],           # weekly-counting -> excluded
    })
    ty = pd.DataFrame({"Team": [], "Year": []})
    ly = pd.DataFrame({"Year": []})
    fr = D.final_rankings(py, ty, ly, 2025, window=3)
    got = {(p.entity, p.column, p.end, p.rank) for p in fr}
    ok = _ok("A's 200 = 1st-highest Points of any season", ("A", "Points", "high", 1) in got, f"got {got}")
    ok &= _ok("B's 70 = 1st-lowest of any season", ("B", "Points", "low", 1) in got)
    ok &= _ok("phrasing says 'finished' + 'of any season'",
              any("finished" in p.sentence() and "of any season" in p.sentence() for p in fr))
    ok &= _ok("weekly-counting excluded from final rankings",
              not any(p.column == "Times as Captain?" for p in fr))
    return ok


def check_event_highlights():
    picks = pd.DataFrame({
        "Year": [2024, 2024, 2025, 2025],
        "Number": ["1.01", "1.02", "1.03", "1.04"],
        "Player Picked": ["P1", "P2", "P3", "P4"],
        "O-Score": [50, 60, 90, 10.0],   # P3 best ever, P4 worst ever
    })
    ev = D.event_highlights(picks, "picks", "Year", 2025, window=3)
    got = [(e.label, e.column, e.end, e.rank) for e in ev]
    ok = _ok("best 2025 pick flagged 1st-highest",
             ("2025 pick 1.03 (P3)", "O-Score", "high", 1) in got, f"got {got}")
    ok &= _ok("worst 2025 pick flagged 1st-lowest",
              ("2025 pick 1.04 (P4)", "O-Score", "low", 1) in got)
    ok &= _ok("sentence names the sheet", any("of any pick ever" in e.sentence() for e in ev))
    # diff: an already-reported event is suppressed; a new one fires.
    prior = D.event_key_map([e for e in ev if e.end == "high"])
    changed = D.diff_events(prior, ev)
    ok &= _ok("prior event suppressed, new kept",
              all(e.end != "high" for e in changed) and any(e.end == "low" for e in changed))
    return ok


def check_replica_and_weekly_filters():
    tw = pd.DataFrame({
        "Team": ["A"] * 3 + ["B"] * 3 + ["A"] * 3 + ["B"] * 3,
        "Year": [2024] * 6 + [2025] * 6,
        "Week": [1, 2, 3] * 4,
        "PF": [100, 50, 200, 90, 80, 70, 60, 300, 40, 55, 65, 75.0],       # single-week
        "Tenure": [1, 2, 3, 1, 2, 3, 4, 5, 6, 4, 5, 6.0],                   # cumulative
        "SeasonTot": ["In Progress", "In Progress", 500, "In Progress", "In Progress", 400,
                      "In Progress", "In Progress", 600, "In Progress", "In Progress", 450],
    })
    ty = pd.DataFrame({"Team": ["A", "B"], "Year": [2025, 2025], "Result": ["Champion", "2nd"]})
    empty_pw = pd.DataFrame({"Player": [], "Year": [], "Week": []})
    empty_lw = pd.DataFrame({"Year": [], "Week": []})

    ok = _ok("latest completed (season, week)", D.latest_completed_season_week(tw) == (2025, 3))
    ok &= _ok("champion resolved", D._champion_of(ty, 2025) == "A")
    hl = D.weekly_highlights(empty_pw, tw, empty_lw, ty)
    cols = {h.column for h in hl}
    ok &= _ok("single-week PF kept", "PF" in cols, f"got {cols}")
    ok &= _ok("cumulative (monotonic) column dropped", "Tenure" not in cols)
    ok &= _ok("season-summary (In Progress) column dropped", "SeasonTot" not in cols)

    frames = {"team_week": tw, "team_year": ty, "player_year": pd.DataFrame({"Player": [], "Year": []}),
              "league_year": pd.DataFrame({"Year": []}), "player_week": empty_pw, "league_week": empty_lw}
    html = D.build_replica_html(frames)
    ok &= _ok("replica names the champion", "A won the 2025 championship" in html)
    ok &= _ok("replica has a single-week record", "single week ever" in html)
    ok &= _ok("replica header is a season wrap", "season wrap" in html)
    return ok


def check_league_window():
    def ly(n):
        return pd.DataFrame({"Year": list(range(2020, 2020 + n))})
    ok = _ok("3 seasons -> window 1", D._league_window(ly(3)) == 1)
    ok &= _ok("7 seasons -> window 2", D._league_window(ly(7)) == 2)
    ok &= _ok("20 seasons -> capped at 5", D._league_window(ly(20)) == 5)
    ok &= _ok("2 seasons -> window 0 (nothing)", D._league_window(ly(2)) == 0)
    return ok


def check_league_milestones():
    ms = D.milestone_crossings({"PF": 49000.0}, {"PF": 51000.0})
    ok = _ok("PF crossing 50k reported", len(ms) == 1 and ms[0].milestone == 50000.0, ms[0].sentence() if ms else "none")
    ok &= _ok("no crossing within the same bucket", D.milestone_crossings({"PF": 51000.0}, {"PF": 52000.0}) == [])
    ok &= _ok("no prior -> no milestone (baseline)", D.milestone_crossings({}, {"PF": 51000.0}) == [])
    lat = pd.DataFrame({"PF": [49000.0], "Total trades": [140.0], "Foo": [3.0]})
    vals = D.league_milestone_values(lat)
    ok &= _ok("major-stat values extracted, others ignored",
              vals.get("PF") == 49000.0 and vals.get("Total trades") == 140.0 and "Foo" not in vals)
    return ok


def check_pace_diff_reports_only_changes():
    p_stay = D.Projection("teams", "A", "Points", "high", 2, 40, 900.0)
    p_move = D.Projection("teams", "B", "Points", "high", 1, 40, 950.0)
    p_new = D.Projection("teams", "C", "Hardship", "low", 1, 40, 5.0)
    prior = D.pace_rank_map([
        D.Projection("teams", "A", "Points", "high", 2, 40, 880.0),
        D.Projection("teams", "B", "Points", "high", 2, 40, 870.0),
    ])
    movers = {(c.entity, c.column) for c in D.diff_pace(prior, [p_stay, p_move, p_new])}
    ok = _ok("unchanged standing suppressed", ("A", "Points") not in movers, f"got {movers}")
    ok &= _ok("moved standing reported", ("B", "Points") in movers)
    ok &= _ok("newly-notable standing reported", ("C", "Hardship") in movers)
    return ok


def check_rate_and_weekly_classification():
    ok = _ok("rate stats classified", all(D.is_rate_stat(c) for c in ["Avg points", "Win %", "PPG starter"]))
    ok &= _ok("cumulative not rate", not any(D.is_rate_stat(c) for c in ["Points", "Hardship", "Total trades"]))
    ok &= _ok("weekly-counting detected",
              all(D.is_weekly_counting_stat(c) for c in
                  ["Times as Captain?", "Times One-man army?", "Wins from byes",
                   "Losses from hardship (2-sided)", "Losses from byes"]))
    ok &= _ok("normal counts not weekly-counting",
              not any(D.is_weekly_counting_stat(c) for c in ["Number of donuts", "Points", "Total trades"]))
    return ok


def check_phrasing_catalog():
    pat = pd.DataFrame({"Player": ["A", "B"], "Points": [1.0, 2.0]})
    tat = pd.DataFrame({"Team": ["A", "B"], "Max PF": [1.0, 2.0], "Times One-man army?": [1, 2]})
    py = pd.DataFrame({"Player": ["A", "B"], "Year": [2024, 2025], "Points": [1.0, 2.0]})
    ty = pd.DataFrame({"Team": ["A", "B"], "Year": [2024, 2025], "Hardship": [1.0, 2.0], "Times One-man army?": [1, 2]})
    ly = pd.DataFrame({"Year": [2024, 2025], "PF": [1.0, 2.0]})
    lat = pd.DataFrame({"PF": [49000.0], "Total trades": [140.0]})
    rows = D.phrasing_catalog(pat, tat, py, ty, ly, lat)
    scopes = {r["scope"] for r in rows}
    ok = _ok("has team any-of-8 scope", any("any movement among the 8" in s for s in scopes))
    ok &= _ok("has league milestone scope", any("milestone" in s for s in scopes))
    ok &= _ok("weekly-counting yearly stat marked as record alert",
              any(r["stat"] == "Times One-man army?" and "record" in r["scope"]
                  and r["sheet"] == "team_year" for r in rows))
    return ok


def check_render_html_smoke():
    c = D.Crossing("teams", "Max PF", "high", 3, "BRO", "shmuel", 305.0)
    p = D.Projection("teams", "A", "Hardship", "high", 1, 3, 110.0)
    m = D.Milestone("PF", 51000.0, 50000.0)
    rec = D.YearlyRecord("teams", "BRO", "Times One-man army?", 9.0)
    html = D.render_digest_html([c], [p], {"season": 2026, "weeks_completed": 7}, [m], [rec])
    ok = _ok("html has crossing + projection + milestone + record + week",
             "passes" in html and "on pace" in html and "League milestones" in html
             and "passes 50,000" in html and "New single-season records" in html
             and "sets a new single-season record" in html and "week 7" in html)
    ok &= _ok("empty digest fallback",
              "No leaderboard changes" in D.render_digest_html([], [], {"season": 2026, "weeks_completed": 7}, []))
    return ok


def check_real_exports_smoke():
    exports = Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))
    need = ["player_all_time", "team_all_time", "team_year", "team_week", "league_all_time"]
    if not all((exports / f"{n}.csv").exists() for n in need):
        print("  [SKIP] real-exports smoke — no build present")
        return True
    fr = {n: pd.read_csv(exports / f"{n}.csv", low_memory=False) for n in need}
    snap = D.build_snapshot(fr["player_all_time"], fr["team_all_time"], fr["team_year"],
                            fr["team_week"], league_all_time=fr["league_all_time"])
    ok = _ok("snapshot discovered many player + team stats",
             len(snap["players"]) > 20 and len(snap["teams"]) > 40,
             f"players={len(snap['players'])} teams={len(snap['teams'])}")
    ok &= _ok("league milestone values captured", len(snap["league_milestones"]) >= 1,
              f"got {snap['league_milestones']}")
    ok &= _ok("self-diff yields no crossings", D.diff_snapshots(snap, snap) == [])
    return ok


def run_all() -> bool:
    tests = [
        check_discovery_drops_non_numeric,
        check_ranking_order_and_missing,
        check_player_high_low_crossings,
        check_low_end_crossing,
        check_team_any_of_8_reported_once,
        check_new_entity_no_false_pass,
        check_in_season_gate,
        check_projection_gate_scale_and_weekly_exclusion,
        check_boolean_flags_excluded_from_pace,
        check_yearly_records_for_weekly_stats,
        check_weekly_highlights,
        check_final_rankings,
        check_event_highlights,
        check_replica_and_weekly_filters,
        check_league_window,
        check_league_milestones,
        check_pace_diff_reports_only_changes,
        check_rate_and_weekly_classification,
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
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
