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
    prev = [{"entity": "T", "value": 50}, {"entity": "E", "value": 20}, {"entity": "F", "value": 25}]
    curr = [{"entity": "T", "value": 50}, {"entity": "F", "value": 18}, {"entity": "E", "value": 20}]
    cx = D._column_crossings("players", "Points", prev, curr, _PLAYERS, D.WINDOW, True)
    got = [(c.mover, c.passed, c.rank, c.end) for c in cx]
    return _ok("low-end crossing (F drops below E to the lowest place)", ("F", ("E",), 1, "low") in got, f"got {got}")


def check_every_numeric_column_ranks():
    # #380 excluded the "build-volatile" families (Luck, `... skill`, O-Score,
    # rolling KTC windows) from all-time crossings on the theory that they drift a
    # hair on every recompute. They are back in: a reorder is a reorder, and these
    # are exactly the columns a reader wants to hear about. Nothing numeric is
    # filtered out of a snapshot now.
    names = [f"T{i}" for i in range(8)]
    def teams(swap):
        rows = []
        for i, n in enumerate(names):
            pf, luck = 100 - i, 50 - i
            if swap and n in ("T2", "T3"):        # swap ranks 3/4 on BOTH columns
                pf = {"T2": 96, "T3": 98}[n]
                luck = {"T2": 46, "T3": 48}[n]
            rows.append({"Team": n, "Max PF": pf, "Luck": luck})
        return pd.DataFrame(rows)
    ty = pd.DataFrame({"Team": names, "Year": [2025] * 8})
    tw = pd.DataFrame({"Team": ["T0"], "Year": [2025], "Week": [1]})
    prev = D.build_snapshot(pd.DataFrame({"Player": []}), teams(False), ty, tw)
    curr = D.build_snapshot(pd.DataFrame({"Player": []}), teams(True), ty, tw)
    ok = _ok("Luck ranked in the team snapshot", "Luck" in curr["teams"], list(curr["teams"]))
    ok &= _ok("Max PF ranked in the team snapshot", "Max PF" in curr["teams"])
    cx = D.diff_snapshots(prev, curr)
    cols = {c.column for c in cx}
    ok &= _ok("normal column reorder fires a crossing", "Max PF" in cols, f"got {cols}")
    ok &= _ok("formerly-volatile column reorder fires too", "Luck" in cols, f"got {cols}")
    return ok


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
                  cx[0].mover == "T3" and cx[0].passed == ("T2",) and cx[0].rank == 3 and cx[0].end == "high",
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
    ok = _ok("no yearly items before week 5", early == [], f"got {len(early)}")
    yrs4 = [y for y in seasons[:-1] for _ in range(14)] + [2026] * 4
    wk4 = [w for _ in seasons[:-1] for w in range(1, 15)] + [1, 2, 3, 4]
    ok &= _ok("still none at week 4",
              D.project_on_pace(py, team_year, ly, pd.DataFrame({"Year": yrs4, "Week": wk4})) == [])
    yrs5 = [y for y in seasons[:-1] for _ in range(14)] + [2026] * 5
    wk5 = [w for _ in seasons[:-1] for w in range(1, 15)] + [1, 2, 3, 4, 5]
    ok &= _ok("on-pace starts at week 5",
              D.project_on_pace(py, team_year, ly, pd.DataFrame({"Year": yrs5, "Week": wk5})) != [])

    yrs7 = [y for y in seasons[:-1] for _ in range(14)] + [2026] * 7
    wk7 = [w for _ in seasons[:-1] for w in range(1, 15)] + list(range(1, 8))
    proj = D.project_on_pace(py, team_year, ly, pd.DataFrame({"Year": yrs7, "Week": wk7}))
    cols = {p.column for p in proj}
    ok &= _ok("Hardship projected + is the highest",
              any(p.column == "Hardship" and abs(p.projected - 110) < 1e-6 and p.rank == 1 for p in proj))
    ok &= _ok("Win % projected as-is", any(p.column == "Win %" and abs(p.projected - 0.9) < 1e-6 for p in proj))
    ok &= _ok("weekly-counting stats excluded from on-pace",
              "Times Highest score?" not in cols and "Losses from byes" not in cols, f"got {sorted(cols)}")
    return ok


def check_tie_skip_in_pace():
    # The ONLY exclusion is the >5-tied rule: a value shared by >5 entity-seasons
    # is skipped (that's how 0/1 flags and flat stats fall out). Everything else
    # is included.
    seasons = list(range(2019, 2027))  # 8 seasons
    py = pd.DataFrame({
        "Player": ["A"] * 8, "Year": seasons,
        "Win %": [0.5] * 8,                                   # rate, all tied (8>5) -> skipped
        "Points": [100, 110, 120, 130, 140, 150, 160, 80.0],  # distinct -> included
    })
    ly = pd.DataFrame({"Year": []})
    yrs = [y for y in seasons[:-1] for _ in range(14)] + [2026] * 7
    wk = [w for _ in seasons[:-1] for w in range(1, 15)] + list(range(1, 8))
    tw = pd.DataFrame({"Year": yrs, "Week": wk})
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026]})
    cols = {p.column for p in D.project_on_pace(py, ty, ly, tw)}
    ok = _ok(">5-tied value (Win% all 0.5) skipped", "Win %" not in cols, f"got {sorted(cols)}")
    ok &= _ok("distinct stat still projects", "Points" in cols)
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
    # A record is the HIGH end of a count — real the week it happens, so it does
    # not wait for week 5 the way on-pace does. Only the preseason has none.
    tw2 = pd.DataFrame({"Year": [2023] * 14 + [2026] * 2, "Week": list(range(1, 15)) + [1, 2]})
    ok &= _ok("a record set by week 2 is reported (no week-5 wait)",
              any(r.column == "Times One-man army?" for r in D.yearly_records(py, ty, ly, tw2)))
    tw0 = pd.DataFrame({"Year": [2023] * 14, "Week": list(range(1, 15))})
    ok &= _ok("no records before the season's first week",
              D.yearly_records(py, ty, ly, tw0) == [])
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
    })
    ty = pd.DataFrame({"Team": ["A", "B"], "Year": [2026, 2026]})
    pw = pd.DataFrame({"Player": [], "Year": [], "Week": []})
    lw = pd.DataFrame({"Year": [], "Week": []})
    hl = D.weekly_highlights(pw, tw, lw, ty, window=2)
    got = [(h.entity, h.column, h.end, h.rank) for h in hl]
    ok = _ok("A's 200 is the highest single week ever", ("A", "PF", "high", 1) in got, f"got {got}")
    ok &= _ok("B's 95 is 2nd-lowest single week ever (both ends work)", ("B", "PF", "low", 2) in got)
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


def check_event_highlights():
    picks = pd.DataFrame({
        "Year": [2024, 2024, 2025, 2025],
        "Number": ["1.01", "1.02", "1.03", "1.04"],
        "Player Picked": ["P1", "P2", "P3", "P4"],
        "O-Score": [50, 60, 90, 10.0],   # P3 best ever, P4 worst ever
    })
    ev = D.board_highlights(picks, "rookie_picks", window=3)
    got = [(e.label, e.column, e.end, e.rank) for e in ev]
    ok = _ok("best pick ever flagged highest",
             ("2025 pick 1.03 (P3)", "O-Score", "high", 1) in got, f"got {got}")
    ok &= _ok("worst pick ever flagged lowest",
              ("2025 pick 1.04 (P4)", "O-Score", "low", 1) in got)
    # The board holds every season's rows, which is what lets a re-valued 2024
    # pick be reported at all.
    labels = {e.label for e in ev}
    ok &= _ok("board includes historical picks",
              "2024 pick 1.02 (P2)" in labels, f"labels={sorted(labels)}")
    return ok


def check_board_covers_every_sheet():
    """Season and week rows sit on boards of their own, so a change to a
    COMPLETED season's row is reported — not only the in-progress one's."""
    frames = {
        "team_year": pd.DataFrame({
            "Team": ["A", "B", "C", "D", "E", "F"],
            "Year": [2020, 2021, 2022, 2023, 2024, 2025],
            "PF": [1000.0, 1100, 1200, 1300, 1400, 1500],
        }),
        "player_week": pd.DataFrame({
            "Player": list("abcdef"), "Year": [2020, 2021, 2022, 2023, 2024, 2025],
            "Week": [1, 2, 3, 4, 5, 6], "Points": [10.0, 20, 30, 40, 50, 60],
        }),
    }
    ev = D.all_board_highlights(frames, window=3)
    sheets = {e.sheet for e in ev}
    ok = _ok("team_year gets a board", "team_year" in sheets, f"got {sheets}")
    ok &= _ok("player_week gets a board", "player_week" in sheets, f"got {sheets}")
    ok &= _ok("season rows are labelled by team and year",
              any(e.label == "F 2025" for e in ev), f"got {sorted({e.label for e in ev})}")
    ok &= _ok("week rows are labelled by player, year and week",
              any(e.label == "f 2025 week 6" for e in ev))
    # Re-value a COMPLETED season and the board reports it.
    prior = D.event_board(ev)
    frames["team_year"].loc[0, "PF"] = 9999.0     # 2020 becomes the highest ever
    changes = D.diff_events(prior, D.all_board_highlights(frames, window=3))
    ok &= _ok("a completed season's re-valued row is reported",
              any(c.label == "A 2020" and c.column == "PF" and c.rank == 1 for c in changes),
              f"got {[c.sentence() for c in changes]}")
    return ok


def check_event_board_diff():
    """A recompute that re-values HISTORY must surface: the user-facing case is a
    KTC window change reshuffling the all-time O-Score top 5 on an event sheet.
    It reads as an all-time crossing — "<mover> passes <passed> for Nth-highest"."""
    def picks_with(oscores):
        return pd.DataFrame({
            "Year": [2024, 2024, 2025, 2025],
            "Number": ["1.01", "1.02", "1.03", "1.04"],
            "Player Picked": ["P1", "P2", "P3", "P4"],
            "O-Score": list(oscores),
        })

    def board(oscores):
        return D.board_highlights(picks_with(oscores), "rookie_picks", window=3)

    base = board([50, 60, 90, 10.0])          # high: P3 1st, P2 2nd, P1 3rd; low: P4 1st
    prior = D.event_board(base)
    ok = _ok("board snapshot is a list of dicts",
             bool(prior) and all(isinstance(d, dict) for d in prior))
    ok &= _ok("unchanged data reports nothing", D.diff_events(prior, base) == [])

    # The 2024 pick P1 is re-valued and takes 1st — a historical row moving the
    # all-time top of the board.
    changes = D.diff_events(prior, board([95, 60, 90, 10.0]))
    ok &= _ok("re-valued historical pick reported once", len(changes) == 1,
              f"got {[c.sentence() for c in changes]}")
    c = changes[0] if changes else None
    ok &= _ok("the mover is the re-valued 2024 pick",
              c is not None and c.label == "2024 pick 1.01 (P1)")
    ok &= _ok("it names who it passed and the place taken",
              c is not None and c.passed == ("2025 pick 1.03 (P3)",) and c.rank == 1,
              f"passed={getattr(c, 'passed', None)} rank={getattr(c, 'rank', None)}")
    ok &= _ok("sentence reads like an all-time crossing",
              c is not None and c.sentence() ==
              "2024 pick 1.01 (P1) passes 2025 pick 1.03 (P3) for highest O-Score (95).",
              f"got {c.sentence() if c else None}")
    ok &= _ok("the picks it passed get no line of their own",
              all(x.label == "2024 pick 1.01 (P1)" for x in changes))

    # A pick pushed OFF the board is not announced — only the mover is.
    changes = D.diff_events(prior, board([50, 60, 90, 70.0]))
    ok &= _ok("displaced picks are not reported",
              all("no longer" not in x.sentence() for x in changes),
              f"got {[x.sentence() for x in changes]}")
    ok &= _ok("the climber is reported",
              any(x.label == "2025 pick 1.04 (P4)" for x in changes),
              f"got {[x.sentence() for x in changes]}")

    # A pre-board snapshot (list of key strings) must re-baseline, not report
    # every place on the board as new.
    ok &= _ok("legacy string snapshot re-baselines silently",
              D.diff_events(["picks|2024 pick 1.01 (P1)|O-Score|high:3"], base) == [])
    ok &= _ok("empty prior re-baselines silently", D.diff_events([], base) == [])
    return ok


def check_yearly_counting_low_end_off_board():
    """A season-accumulating count (pure drops, trades, transactions, FAAB) shows
    only its HIGH end on the all-time board — its LOW end ("fewest …") is a
    preseason artifact left to the on-pace projection (week 3+). A non-counting
    yearly stat keeps BOTH ends; and weekly-counting awards are NOT reclassified."""
    ok = _ok("'Number of pure drops' is a yearly counting stat",
             D.is_yearly_counting_stat("Number of pure drops"))
    ok &= _ok("'Number of trades' too", D.is_yearly_counting_stat("Number of trades"))
    ok &= _ok("'PF' is not", not D.is_yearly_counting_stat("PF"))
    ok &= _ok("a weekly-counting award is excluded (keeps both ends)",
              not D.is_yearly_counting_stat("Times highest score?"))

    ty = pd.DataFrame({
        "Team": [f"T{i}" for i in range(6)], "Year": [2021, 2022, 2023, 2024, 2025, 2026],
        "Number of pure drops": [10.0, 8, 6, 4, 2, 0],
        "PF": [100.0, 90, 80, 70, 60, 50],
    })
    hl = D.board_highlights(ty, "team_year", window=3)
    ends = {}
    for h in hl:
        ends.setdefault(h.column, set()).add(h.end)
    ok &= _ok("pure drops: only the HIGH end reaches the board",
              ends.get("Number of pure drops") == {"high"}, ends.get("Number of pure drops"))
    ok &= _ok("PF: both ends stay on the board",
              ends.get("PF") == {"high", "low"}, ends.get("PF"))
    return ok


def check_event_diff_flags_new_rows():
    """is_new means the row's key was in the prior snapshot's FULL row set — a
    genuinely brand-new row (a just-made trade/add, a freshly recorded pick). It
    is told apart from BOTH a re-valued row AND an old row that merely climbs onto
    a board for the first time — the distinction the ranked-only board can't make
    alone, which is why the full key set is threaded through."""
    def picks(rows):
        return pd.DataFrame({"Year": [r[0] for r in rows], "Number": [r[1] for r in rows],
                             "Player Picked": [r[2] for r in rows],
                             "O-Score": [r[3] for r in rows]})
    # Prior FULL set has five picks; P5 exists but sits off the (window=3) board.
    prior_rows = [(2024, "1.01", "P1", 50), (2024, "1.02", "P2", 60),
                  (2025, "1.03", "P3", 90), (2025, "1.04", "P4", 10.0),
                  (2025, "1.05", "P5", 55)]
    prior_keys = D.all_row_keys({"rookie_picks": picks(prior_rows)})
    prior = D.event_board(D.board_highlights(picks(prior_rows), "rookie_picks", window=3))
    # Now: P5 (old, was off the board) is re-valued and climbs to 1st; a genuinely
    # new 2026 pick also lands high; P1 is re-valued upward.
    cur = D.board_highlights(picks([
        (2024, "1.01", "P1", 92), (2024, "1.02", "P2", 60),
        (2025, "1.03", "P3", 90), (2025, "1.04", "P4", 10.0),
        (2025, "1.05", "P5", 99), (2026, "1.06", "NEW", 95)]), "rookie_picks", window=3)
    by = {c.label: c for c in D.diff_events(prior, cur, prior_row_keys=prior_keys)}
    new = by.get("2026 pick 1.06 (NEW)")
    climber = by.get("2025 pick 1.05 (P5)")
    reval = by.get("2024 pick 1.01 (P1)")
    ok = _ok("the brand-new pick is flagged is_new",
             new is not None and new.is_new is True, str(list(by)))
    ok &= _ok("an old row climbing onto the board is NOT is_new",
              climber is not None and climber.is_new is False,
              f"climber={climber and climber.is_new}")
    ok &= _ok("a re-valued existing pick is NOT is_new",
              reval is not None and reval.is_new is False,
              f"reval={reval and reval.is_new}")
    ok &= _ok("without the prior full key set, nothing is called new",
              all(not c.is_new for c in D.diff_events(prior, cur)), "")
    return ok


def check_event_labels():
    """Labels name the assets, so a line says what actually moved."""
    trades = pd.DataFrame([{
        "Team": "Oliverwkw", "Date": "2023-12-05 18:46:43",
        "Assets received": "A; B; C; D; E",
    }])
    label = D._board_label("trades", trades.iloc[0])
    ok = _ok("trade label carries date + assets, capped",
             label == "Oliverwkw's 2023-12-05 trade for A, B, C +2 more", f"got {label}")
    one = D._board_label("trades", pd.DataFrame(
        [{"Team": "T", "Date": "2024-01-02 03:04:05", "Assets received": "Solo"}]).iloc[0])
    ok &= _ok("single asset needs no '+N more'", one == "T's 2024-01-02 trade for Solo", f"got {one}")
    bare = D._board_label("trades", pd.DataFrame(
        [{"Team": "T", "Date": "2024-01-02 03:04:05", "Assets received": ""}]).iloc[0])
    ok &= _ok("a trade with no assets listed still labels", bare == "T's 2024-01-02 trade", f"got {bare}")
    add = D._board_label("add_drops", pd.DataFrame(
        [{"Team": "T", "Date": "2025-09-01 18:00:20", "Player Added": "QJ",
          "Player Dropped": "X"}]).iloc[0])
    ok &= _ok("transaction label names the added player",
              add == "T's 2025-09-01 move for QJ", f"got {add}")
    drop = D._board_label("add_drops", pd.DataFrame(
        [{"Team": "T", "Date": "2025-09-01 18:00:20", "Player Added": "",
          "Player Dropped": "X"}]).iloc[0])
    ok &= _ok("a drop-only row reads as a drop", drop == "T's 2025-09-01 drop of X", f"got {drop}")
    return ok


def check_an_acquisition_never_reads_as_a_disposal():
    """Every player_additions row is a player ARRIVING, so the preposition has to
    say so. "trade of X" said the opposite — the board line
    "AceMatthew's 2025-06-18 trade of Bijan Robinson: KTC at end of season of
    9713 — 1st-highest" reads as trading Bijan away, which is the reverse of what
    that row records."""
    def lab(kind, who="Bijan Robinson"):
        return D._board_label("player_additions", pd.DataFrame(
            [{"Team": "T", "Date": "2025-06-18 12:00:00",
              "Addition type": kind, "Player": who}]).iloc[0])

    ok = _ok("a trade acquisition reads as arriving",
             lab("Trade") == "T's 2025-06-18 trade for Bijan Robinson", f"got {lab('Trade')}")
    ok &= _ok("never the disposal reading", " trade of " not in lab("Trade"))
    # The rest are acquisitions too; they only needed the noun the old label
    # dropped. A draft already takes "of".
    for kind, want in (("Waiver", "T's 2025-06-18 waiver pickup of Bijan Robinson"),
                       ("Free agency", "T's 2025-06-18 free agency pickup of Bijan Robinson"),
                       ("Commissioner", "T's 2025-06-18 commissioner pickup of Bijan Robinson"),
                       ("Draft", "T's 2025-06-18 draft of Bijan Robinson"),
                       ("", "T's 2025-06-18 pickup of Bijan Robinson")):
        ok &= _ok(f"{kind or '(blank)'} reads naturally", lab(kind) == want, f"got {lab(kind)}")
    return ok


def check_the_rename_does_not_desync_the_baseline():
    """A crossing is decided by KEY, so a rename cannot invent or silence a line.
    What it CAN do is desync every label-keyed lookup in `_prior_board` —
    `by_rank`, which supplies the names in "passes …"/"joins a tie with …", and
    `val_by_label`, which is how `_nobody_moved` asks whether the row a mover
    overtook actually moved. `migrate_board_label` reads an old baseline in
    today's spelling so both keep matching."""
    ok = _ok("the legacy trade label migrates",
             D.migrate_board_label("player_additions", "T's 2025-06-18 trade of Bijan Robinson")
             == "T's 2025-06-18 trade for Bijan Robinson")
    ok &= _ok("and the legacy pickup labels",
              D.migrate_board_label("player_additions", "T's 2025-06-18 waiver of X")
              == "T's 2025-06-18 waiver pickup of X")
    # Idempotent: it runs on every read, including of a snapshot already written
    # in the new spelling.
    once = D.migrate_board_label("player_additions", "T's 2025-06-18 trade for X")
    ok &= _ok("idempotent on an already-migrated label",
              once == "T's 2025-06-18 trade for X" and
              D.migrate_board_label("player_additions", once) == once, f"got {once}")
    ok &= _ok("a draft label is left alone",
              D.migrate_board_label("player_additions", "T's 2025-06-18 draft of X")
              == "T's 2025-06-18 draft of X")
    # Scoped to this sheet: add_drops' own "drop of"/"move for" must not be touched.
    for other in ("add_drops", "trades", "team_week"):
        ok &= _ok(f"{other} labels are untouched",
                  D.migrate_board_label(other, "T's 2025-09-01 drop of X")
                  == "T's 2025-09-01 drop of X")
    # And the baseline reader actually applies it, which is the part that matters.
    prior = [{"sheet": "player_additions", "column": "KTC at pickup", "end": "high",
              "key": "player_additions|X|T|2025-06-18|Trade", "rank": 1,
              "label": "T's 2025-06-18 trade of X", "value": 100.0}]
    slot = D._prior_board(prior)[("player_additions", "KTC at pickup", "high")]
    ok &= _ok("_prior_board stores the migrated name in by_rank",
              slot["by_rank"][1] == ["T's 2025-06-18 trade for X"], f"got {slot['by_rank']}")
    ok &= _ok("and keys val_by_label by it too",
              slot.get("val_by_label", {}).get("T's 2025-06-18 trade for X") == 100.0,
              f"got {slot.get('val_by_label')}")
    ok &= _ok("the row key is untouched by any of this",
              slot["by_key"] == {"player_additions|X|T|2025-06-18|Trade": 1})

    # league_year: the sheet has no text column, so its row is a float Series and
    # the email printed "the 2023.0 season passes the 2022.0 season" (run 497).
    # The label drops the ".0"; the KEY must not, or every stored place stops
    # matching; and an old baseline's labels are read in the new spelling.
    # A float column is what upcasts the row, exactly as on the real sheet
    # (Avg PF, Efficiency …); an all-int fixture would keep Year an int and pass
    # against the unfixed label.
    ly = pd.DataFrame([{"Year": 2023, "Donuts (roster)": 130, "Avg PF": 131.5}]).iloc[0]
    ok &= _ok("an all-numeric league_year row still reads as a year",
              D._board_label("league_year", ly) == "the 2023 season",
              f"got {D._board_label('league_year', ly)}")
    ok &= _ok("its key keeps the stored spelling",
              D._board_row_key("league_year", ly) == "league_year|2023.0",
              f"got {D._board_row_key('league_year', ly)}")
    ok &= _ok("the float-year label migrates, idempotently",
              D.migrate_board_label("league_year", "the 2023.0 season") == "the 2023 season"
              and D.migrate_board_label("league_year", "the 2023 season") == "the 2023 season")
    ok &= _ok("other sheets' labels are not rewritten by it",
              D.migrate_board_label("team_year", "the 2023.0 season") == "the 2023.0 season")
    prior = [{"sheet": "league_year", "column": "Donuts (roster)", "end": "high",
              "key": "league_year|2022.0", "rank": 3, "label": "the 2022.0 season",
              "value": 98.0}]
    slot = D._prior_board(prior)[("league_year", "Donuts (roster)", "high")]
    ok &= _ok("_prior_board names an old league season in the new spelling",
              slot["by_rank"][3] == ["the 2022 season"]
              and slot.get("val_by_label", {}).get("the 2022 season") == 98.0,
              f"got {slot['by_rank']} / {slot.get('val_by_label')}")
    return ok


def check_mirrored_columns():
    # A matchup's margin is +M / -M for the two teams: one fact, not two records.
    # Mirrored columns are detected structurally (rows that pair through an
    # opponent column) and ranked over their POSITIVE side only, so the board
    # names each game once, from the winner's row.
    tw = pd.DataFrame({
        "Team":     ["A", "B", "C", "D", "E", "F", "G", "H", "A", "C"],
        "Opponent": ["B", "A", "D", "C", "F", "E", "H", "G", "C", "A"],
        "Year":     [2025] * 8 + [2024, 2024],
        "Week":     [1, 1, 1, 1, 2, 2, 2, 2, 1, 1],
        # Margin mirrors within each matchup; PF does NOT (not two-sided).
        "Margin":   [30, -30, 5, -5, 50, -50, 2, -2, 10, -10],
        "PF":       [120, 90, 100, 95, 140, 90, 101, 99, 110, 100],
    })
    mirrored = D.mirrored_columns(tw, "team_week")
    ok = _ok("margin detected as mirrored", "Margin" in mirrored, f"got {mirrored}")
    ok &= _ok("PF not detected as mirrored", "PF" not in mirrored, f"got {mirrored}")
    ok &= _ok("mirrored pool keeps only the positive side",
              sorted(D.rankable_series(tw, "Margin", True, "team_week").tolist())
              == [2, 5, 10, 30, 50])
    ok &= _ok("an unmirrored column keeps every value",
              len(D.rankable_series(tw, "PF", False)) == 10)

    board = D.board_highlights(tw, "team_week", window=3)
    margins = [(e.label, e.end, e.rank, e.value) for e in board if e.column == "Margin"]
    ok &= _ok("biggest blowout named once, from the winner",
              ("E 2025 week 2", "high", 1, 50.0) in margins, f"got {margins}")
    ok &= _ok("closest game is the LOW end, not a mirror of the blowout",
              ("G 2025 week 2", "low", 1, 2.0) in margins, f"got {margins}")
    ok &= _ok("no loser row on the margin board",
              not any(lbl.startswith(("F ", "H ")) for lbl, *_ in margins), f"got {margins}")
    ok &= _ok("a mirrored column can't report the same game twice",
              len(margins) == len({(r, e) for _, e, r, _ in margins}), f"got {margins}")

    # A symmetric DISTRIBUTION is not a mirror: no opponent pairing, no clipping.
    pw = pd.DataFrame({"Player": list("abcdefgh"), "Year": [2025] * 8, "Week": [1] * 8,
                       "Change from previous week": [9, -9, 4, -4, 7, -7, 1, -1]})
    ok &= _ok("symmetric-but-unpaired column is not mirrored",
              D.mirrored_columns(pw, "player_week") == set())
    lows = [e for e in D.board_highlights(pw, "player_week", window=3)
            if e.column == "Change from previous week" and e.end == "low"]
    ok &= _ok("so its biggest DROP is still a record",
              any(e.value == -9 for e in lows), f"got {[(e.label, e.value) for e in lows]}")
    return ok


def check_even_events_stay_on_the_board():
    # A dead-even event — a tied game, a trade of exactly equal value — reads 0
    # on BOTH of its rows, so a strictly-positive reduction drops it entirely and
    # the board calls the closest NON-even event the most even one ever. Zero is
    # the record at that end: the event is kept, once, from one side.
    tw = pd.DataFrame({
        "Team":     ["A", "B", "C", "D", "E", "F", "G", "H"],
        "Opponent": ["B", "A", "D", "C", "F", "E", "H", "G"],
        "Year":     [2025] * 8,
        "Week":     [1, 1, 1, 1, 2, 2, 2, 2],
        "Margin":   [30, -30, 5, -5, 50, -50, 0, 0],
        "PF":       [120, 90, 100, 95, 140, 90, 100, 100],
    })
    ok = _ok("a tied game is still detected as mirrored",
             "Margin" in D.mirrored_columns(tw, "team_week"))
    pool = sorted(D.rankable_series(tw, "Margin", True, "team_week").tolist())
    ok &= _ok("the tie is in the pool exactly once", pool == [0, 5, 30, 50], f"got {pool}")
    margins = [(e.label, e.end, e.rank, e.value)
               for e in D.board_highlights(tw, "team_week", window=3) if e.column == "Margin"]
    ok &= _ok("the tie is the closest game ever, not the 5-point win",
              ("G 2025 week 2", "low", 1, 0.0) in margins, f"got {margins}")
    ok &= _ok("and it is named from one side only",
              not any(lbl.startswith("H ") for lbl, *_ in margins), f"got {margins}")

    # The same on the trades sheet, where it actually bit: two picks swapped at
    # identical KTC is a 0 difference for both sides — the most even trade there
    # can be, and it belongs at the low end of the board ahead of every non-even
    # deal. Competition ranks: the two-way tie takes 1st and 2nd, next value 3rd.
    sides = list("ABCDEFGHIJKL")
    tr = pd.DataFrame({
        "Team":                  sides,
        "Team's traded with 1":  [sides[i ^ 1] for i in range(len(sides))],
        "Date":                  [d for d in ("2024-07-13 18:27:36", "2024-07-13 18:51:36",
                                              "2024-08-25 00:14:23", "2023-10-22 23:36:43",
                                              "2022-07-24 13:37:22", "2022-08-21 19:10:32")
                                  for _ in (0, 1)],
        "Season":                [2024, 2024, 2024, 2024, 2024, 2024,
                                  2023, 2023, 2022, 2022, 2022, 2022],
        "Assets received":       list("abcdefghijkl"),
        # Two dead-even pick swaps, then four deals with a winning side.
        "KTC value difference at deal time": [0, 0, 0, 0, 7.5, -7.5,
                                              9, -9, 40, -40, 60, -60],
    })
    col = "KTC value difference at deal time"
    ok &= _ok("an even trade is detected as mirrored", col in D.mirrored_columns(tr, "trades"))
    lows = sorted(((e.rank, e.value, e.label)
                   for e in D.board_highlights(tr, "trades", window=3)
                   if e.column == col and e.end == "low"))
    # Competition ranks: the two even trades take 1st and 2nd, so 7.5 is 3rd —
    # not the "lowest KTC value difference at deal time" the email once called it.
    ok &= _ok("both even trades are lowest, once each, pushing 7.5 to 3rd",
              [(r, v) for r, v, _ in lows] == [(1, 0.0), (1, 0.0), (3, 7.5)], f"got {lows}")
    ok &= _ok("each even trade is named from one side only",
              sorted(lbl[0] for _, _, lbl in lows) == ["A", "C", "E"], f"got {lows}")
    return ok


def check_replica_minimal():
    # The offseason seed is intentionally minimal: champion + a note, no
    # reconstructed change sections (those need a prior email's snapshot).
    tw = pd.DataFrame({"Team": ["A", "B"] * 3, "Year": [2025] * 6, "Week": [1, 1, 2, 2, 3, 3]})
    ty = pd.DataFrame({"Team": ["A", "B"], "Year": [2025, 2025], "Result": ["Champion", "2nd"]})
    frames = {"team_week": tw, "team_year": ty}
    html = D.build_replica_html(frames)
    ok = _ok("latest completed (season, week)", D.latest_completed_season_week(tw) == (2025, 3))
    ok &= _ok("champion resolved", D._champion_of(ty, 2025) == "A")
    ok &= _ok("replica names the champion", "A won the 2025 championship" in html)
    ok &= _ok("replica is minimal (no change sections)",
              "single week ever" not in html and "on pace" not in html and "all-time" not in html.lower())
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
              not any(D.is_weekly_counting_stat(c) for c in ["Donuts (roster)", "Points", "Total trades"]))
    # Audit finding F2: "Most number of X from same NFL team" is a season MAX
    # capped by roster size, not a running total. Scaling it by weeks-remaining
    # produced impossible values (6 -> 12.8 at week 8, vs an all-time high of 7)
    # that always ranked 1st, so it must be carried as-is.
    ok &= _ok("'Most number of ... from same NFL team' treated as a level, not cumulative",
              all(D.is_rate_stat(c) for c in
                  ["Most number of players rostered from same NFL team",
                   "Most number of QBs started from same NFL team",
                   "Most number of WR rostered from same NFL team"]))
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
    c = D.Crossing("teams", "Max PF", "high", 3, "BRO", 305.0, passed=("shmuel",))
    p = D.Projection("teams", "A", "Hardship", "high", 1, 3, 110.0)
    m = D.Milestone("PF", 51000.0, 50000.0)
    rec = D.YearlyRecord("teams", "BRO", "Times One-man army?", 9.0)
    html = D.render_digest_html([c], [p], {"season": 2026, "weeks_completed": 7}, [m], [rec])
    ok = _ok("html has crossing + projection + milestone + record + week",
             "passes" in html and "on pace" in html and "League milestones" in html
             and "passes 50,000" in html and "New single-season records" in html
             and "most in any season" in html and "week 7" in html)
    ok &= _ok("empty digest fallback",
              "No leaderboard changes" in D.render_digest_html([], [], {"season": 2026, "weeks_completed": 7}, []))
    return ok


def check_digest_title():
    """In-season names the week (and never says "through"); the offseason names
    the build date instead of the meaningless "week 0"."""
    in_season = {"season": 2026, "weeks_completed": 7,
                 "captured_at": "2026-11-03T14:05:00+00:00"}
    off = {"season": 2026, "weeks_completed": 0,
           "captured_at": "2026-08-04T16:16:14.518605+00:00"}

    t = D.digest_title(in_season)
    ok = _ok("in-season title names the week", t == "LOTG weekly digest — 2026 season, week 7", f"got {t}")
    ok &= _ok("in-season title drops 'through'", "through" not in t, f"got {t}")

    t = D.digest_title(off)
    ok &= _ok("offseason title names the date",
              t == "LOTG weekly digest — 2026 season, August 4, 2026", f"got {t}")
    ok &= _ok("offseason title never says week 0", "week 0" not in t.lower(), f"got {t}")

    # No/bad capture time -> degrade to the season alone, never to "week 0".
    t = D.digest_title({"season": 2026, "weeks_completed": 0})
    ok &= _ok("missing capture time -> season only", t == "LOTG weekly digest — 2026 season", f"got {t}")
    t = D.digest_title({"season": 2026, "weeks_completed": 0, "captured_at": "not a date"})
    ok &= _ok("unparseable capture time -> season only", t == "LOTG weekly digest — 2026 season", f"got {t}")

    # The rendered header uses the same title (unless one is passed explicitly).
    html = D.render_digest_html([], [], off)
    ok &= _ok("offseason header carries the date", "2026 season, August 4, 2026" in html)
    ok &= _ok("in-season header carries the week",
              "2026 season, week 7" in D.render_digest_html([], [], in_season))
    ok &= _ok("explicit header still wins",
              "Custom" in D.render_digest_html([], [], off, header="Custom"))
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


def check_tie_joins_are_said_to_be_ties():
    """Arriving at a place someone already holds is not overtaking them.

    On the event boards ranks run over DISTINCT values, so co-occupancy of a rank
    IS a shared value. Saying "passes X for lowest" while X is still standing on
    it states the opposite of what happened."""
    def hl(key, label, rank, value):
        return D.EventHighlight(sheet="rookie_picks", label=label, column="KTC",
                                end="low", rank=rank, value=value, key=key)

    prior = [{"sheet": "rookie_picks", "key": "k06", "label": "pick 4.06",
              "column": "KTC", "end": "low", "rank": 1, "value": 0.0},
             {"sheet": "rookie_picks", "key": "k07", "label": "pick 4.07",
              "column": "KTC", "end": "low", "rank": 2, "value": 5.0}]
    # 4.07 is re-valued down to 0 and lands ON 4.06's place rather than below it.
    joined = [hl("k06", "pick 4.06", 1, 0.0), hl("k07", "pick 4.07", 1, 0.0)]
    out = D.diff_events(prior, joined)
    ok = _ok("the mover is reported", len(out) == 1, [o.sentence() for o in out])
    ok &= _ok("as a tie-join, not an overtake", bool(out) and out[0].joined,
              out and out[0].sentence())
    ok &= _ok("naming who it is level with", bool(out) and out[0].others == ("pick 4.06",),
              out and out[0].others)
    ok &= _ok("and the sentence says so",
              bool(out) and "joins pick 4.06 in a tie for lowest KTC" in out[0].sentence(),
              out and out[0].sentence())

    # The same move, but 4.06 is pushed off the place: a real overtake.
    took = [hl("k07", "pick 4.07", 1, 0.0), hl("k06", "pick 4.06", 2, 5.0)]
    out2 = D.diff_events(prior, took)
    ok &= _ok("a genuine overtake still says passes",
              len(out2) == 1 and not out2[0].joined and "passes" in out2[0].sentence(),
              [o.sentence() for o in out2])
    return ok


def check_all_time_tie_joins():
    """Same rule on the player/team all-time boards, where ranks are positional
    and a tie is two adjacent entries holding the SAME value."""
    def board(pairs):
        return {"players": {"PF": [{"entity": e, "value": v} for e, v in pairs]}}

    prev = board([("A", 100.0), ("Q", 90.0), ("B", 80.0),
                  ("D", 70.0), ("E", 60.0), ("F", 50.0)])
    # B rises to exactly Q's value and sorts above it on name — it joined the
    # place, it did not take it.
    curr = board([("A", 100.0), ("B", 90.0), ("Q", 90.0),
                  ("D", 70.0), ("E", 60.0), ("F", 50.0)])
    out = [c for c in D.diff_snapshots(prev, curr) if c.mover == "B"]
    ok = _ok("the riser is reported", len(out) == 1, [c.sentence() for c in out])
    ok &= _ok("as a tie-join", bool(out) and out[0].joined, out and out[0].sentence())
    ok &= _ok("phrased 'joins Q in a tie for'", bool(out) and "joins Q in a tie for 2nd-highest PF" in out[0].sentence(),
              out and out[0].sentence())

    # Values that merely ROUND to the same display string are not a tie — both
    # render as "90.0", and calling them level would be a false claim.
    near = board([("A", 100.0), ("B", 90.02), ("Q", 90.0),
                  ("D", 70.0), ("E", 60.0), ("F", 50.0)])
    out2 = [c for c in D.diff_snapshots(prev, near) if c.mover == "B"]
    ok &= _ok("near-equal values are an overtake, not a tie",
              bool(out2) and not out2[0].joined, out2 and out2[0].sentence())
    return ok


def check_section_reading_order():
    """Inside a section: every 1st place before every 2nd, and within one place
    the stats the league argues about before the diagnostics."""
    def mv(label, col, rank):
        return D.EventCrossing(sheet="rookie_picks", label=label, passed=("X",), column=col,
                               end="low", rank=rank, value=1.0)

    items = [mv("first_diagnostic", "Pick-adjusted Difference in KTC", 1),
             mv("second_middling", "KTC at end of rookie year", 2),
             mv("first_middling", "KTC at end of rookie year", 1),
             mv("second_prominent", "O-Score", 2)]
    html = D._grouped_section_html("T", items)
    want = ["first_middling", "first_diagnostic",     # place 1, by relevance
            "second_prominent", "second_middling"]    # then place 2, by relevance
    at = [html.index(f"{w} passes") for w in want]
    ok = _ok("place first, then stat relevance", at == sorted(at),
             [w for _, w in sorted(zip(at, want))])
    ok &= _ok("a diagnostic 1st still beats a prominent 2nd",
              html.index("first_diagnostic passes") < html.index("second_prominent passes"))
    return ok


def check_bullet_groups_stay_together_at_their_best_place():
    """A group is the one thing that lets a reader see everything one entity did
    in a single place; splitting it to interleave its 3rd-place move with someone
    else's would spend exactly that. So it stays whole and takes the position of
    its BEST item — and orders internally by the same rule."""
    def mv(label, col, rank):
        return D.EventCrossing(sheet="rookie_picks", label=label, passed=("X",), column=col,
                               end="low", rank=rank, value=1.0)

    items = [mv("solo", "O-Score", 2),
             mv("grp", "KTC at end of rookie year", 3),
             mv("grp", "O-Score", 1),
             mv("grp", "KTC at end of rookie year", 2)]
    html = D._grouped_section_html("T", items)
    ok = _ok("the group renders as one bullet list", html.count("<ul") == 2, html.count("<ul"))
    ok &= _ok("placed by its best item, ahead of a 2nd-place single",
              html.index("grp:") < html.index("solo passes"))
    inner = html[html.index("grp:"):html.index("solo passes")]
    ok &= _ok("and ordered internally the same way",
              inner.index("for lowest") < inner.index("2nd-lowest") < inner.index("3rd-lowest"),
              inner[:200])
    ok &= _ok("the group is contiguous — nothing interleaved into it",
              "solo" not in inner)
    return ok


def check_records_are_first_places():
    """A single-season record is only emitted when the value beats every
    completed season, so it IS 1st place on that stat's board. Treating it as
    placeless sank the strongest claim in the email below every 5th-place
    shuffle it shared a section with."""
    rec = D.YearlyRecord("teams", "Oliverwkw", "Number of Add/Drops", 47.0)
    ok = _ok("a record carries a place", rec.rank == 1, rec.rank)
    ok &= _ok("and sorts as one", D._order_key(rec)[0] == 1)

    fifth = D.EventCrossing(sheet="rookie_picks", label="z", passed=("X",), column="O-Score",
                            end="low", rank=5, value=1.0)
    html = D._grouped_section_html("T", [fifth, rec])
    ok &= _ok("so it leads a 5th place it shares a section with",
              html.index("most in any season") < html.index("z passes"), html)

    # A milestone is a threshold crossing, not a position on a board — it is the
    # one thing that genuinely has no place.
    ok &= _ok("a milestone is still placeless",
              D._order_key(D.Milestone("PF", 50000.0, 50000.0))[0] == D._NO_PLACE)
    return ok


def check_flat_sections_are_ordered_too():
    """One rule for the whole email: the milestone section has no bullet groups,
    but it still reads best-stat-first."""
    ms = [D.Milestone("Amount of FAAB spent", 12000.0, 10000.0),
          D.Milestone("PF", 500000.0, 500000.0)]
    html = D.render_digest_html([], [], {"season": 2026, "weeks_completed": 7},
                                milestones=ms)
    return _ok("the more relevant stat leads",
               html.index("PF passes") < html.index("Amount of FAAB spent passes"), html)


def check_order_is_stable():
    """Equal items must not reshuffle between builds: the audit diffs this email's
    inputs, and a cosmetic reshuffle would read as movement."""
    def mv(label):
        return D.EventCrossing(sheet="rookie_picks", label=label, passed=("X",), column="O-Score",
                               end="low", rank=1, value=1.0)

    items = [mv("a"), mv("b"), mv("c")]
    once = D._grouped_section_html("T", items)
    twice = D._grouped_section_html("T", list(reversed(items)))
    return _ok("same items, same order regardless of input order", once == twice)


def check_first_place_drops_the_ordinal():
    """"1st-highest" says the same thing twice — "highest" already means first,
    and the doubling is loudest on exactly the lines that matter most. Places
    below first still need the ordinal to mean anything."""
    def cr(rank, end):
        return D.Crossing("players", "PF", end, rank, "A", 10.0, passed=("B",))

    ok = _ok("1st-highest -> highest", "for highest PF" in cr(1, "high").sentence(),
             cr(1, "high").sentence())
    ok &= _ok("1st-lowest -> lowest", "for lowest PF" in cr(1, "low").sentence(),
              cr(1, "low").sentence())
    ok &= _ok("2nd keeps its ordinal", "2nd-highest PF" in cr(2, "high").sentence())
    ok &= _ok("no '1st-' anywhere in a first place",
              "1st-" not in cr(1, "high").sentence() + cr(1, "low").detail())
    # Every phrasing goes through the same helper, so nothing is left behind.
    ok &= _ok("the helper is the only spelling of the phrase",
              D._place(1, "high") == "highest" and D._place(1, "low") == "lowest"
              and D._place(4, "low") == "4th-lowest")
    return ok


def check_a_line_does_not_repeat_its_own_header():
    """A section header says where you are; the lines under it shouldn't say it
    again. `sentence()` keeps the standalone framing the lede needs; `line()` is
    what the section prints."""
    w = D.WeeklyHighlight("players", "A", "Points", "high", 1, 55.4)
    r = D.YearlyRecord("teams", "A", "Total trades", 12.0)
    m = D.Milestone("PF", 112807.0, 100000.0)
    c = D.Crossing("players", "Points", "high", 1, "A", 2100.0, passed=("B",))
    ok = _ok("the lede's copy still stands alone",
             "single week ever" in w.sentence() and "single-season record" in r.sentence()
             and w.sentence().startswith("A's Points this week"))
    ok &= _ok("under 'Single-week records (this week)', drop both",
              w.line() == "A's Points (55.4) — highest ever.", w.line())
    ok &= _ok("under 'New single-season records', say it once",
              r.line() == "A: Total trades (12) — most in any season.", r.line())
    ok &= _ok("under 'League milestones', drop the League",
              m.line() == "PF passes 100,000 (now 112,807).", m.line())
    ok &= _ok("crossings stop saying 'all-time' — the header does, and "
              "EventCrossing never did",
              "all-time" not in c.sentence(), c.sentence())
    return ok


def check_group_label_is_the_bare_entity():
    """The verb used to be the header again, one line apart: "All-time
    leaderboard moves — players" over "Ja'Marr Chase made these all-time
    moves:"."""
    items = [D.Crossing("players", "Points", "high", 1, "A", 10.0, passed=("B",)),
             D.Crossing("players", "Avg points", "high", 2, "A", 22.0, passed=("B",))]
    html = D._grouped_section_html("All-time leaderboard moves — players", items)
    ok = _ok("the label is the entity and a colon", "A:<ul" in html, html[:160])
    ok &= _ok("no verb echoing the header", "all-time moves" not in html, html)
    return ok


def check_league_sections_drop_the_redundant_label():
    """"Season-long results — league" holds nothing but "The league", so
    labelling its bullets "The league:" prints the header a second time. A teams
    section suffixed "teams" must NOT match an entity called "Oliverwkw"."""
    ps = [D.Projection("league", "The league", "Total trades", "high", 3, 8, 44.0, 44.0),
          D.Projection("league", "The league", "Number of Add/Drops", "high", 1, 8, 300.0, 300.0)]
    html = D._grouped_section_html("Season-long results — league", ps)
    ok = _ok("no 'The league:' label", "The league" not in html, html)
    ok &= _ok("items sit at the top level, not under an empty bullet",
              html.count("<ul") == 1, html)
    ok &= _ok("and read as sentences", "Highest Number of Add/Drops (300)." in html, html)

    ok &= _ok("the header must actually name the entity",
              D._label_is_the_header("Season-long results — league", "The league"))
    ok &= _ok("a teams section keeps its labels",
              not D._label_is_the_header("Season-long results — teams", "Oliverwkw"))
    ok &= _ok("and a players section does too",
              not D._label_is_the_header("All-time leaderboard moves — players", "Ja'Marr Chase"))
    ok &= _ok("a header with no suffix never matches",
              not D._label_is_the_header("New single-season records", "The league"))
    return ok


def check_an_invisible_overtake_is_not_reported():
    """An overtake whose two numbers PRINT the same is not news.

    The 2026-09-08 digest led on "2026 pick 4.07 (Darnell Mooney) passes 2026
    pick 3.02 (Chig Okonkwo) for 2nd-lowest Tanking (-0.0)". The margin was
    0.0006 — four decimals below what the sentence shows — on a season with no
    played weeks, and it outranked every other line in the email.
    """
    prev = {"teams": {"Tanking": [{"entity": "A", "value": -0.0034},
                                  {"entity": "B", "value": -0.0033},
                                  {"entity": "C", "value": 5.0},
                                  {"entity": "D", "value": 9.0}]}}
    curr = {"teams": {"Tanking": [{"entity": "A", "value": -0.0041},
                                  {"entity": "B", "value": -0.0047},
                                  {"entity": "C", "value": 5.0},
                                  {"entity": "D", "value": 9.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok = _ok("B overtaking A on an invisible margin is dropped", got == [], f"got {got}")

    # The same rule on the event boards, where that line actually appeared.
    board = [{"sheet": "rookie_picks", "key": "k_a", "label": "pick A", "column": "Tanking",
              "end": "low", "rank": 1, "value": -0.0034},
             {"sheet": "rookie_picks", "key": "k_b", "label": "pick B", "column": "Tanking",
              "end": "low", "rank": 2, "value": -0.0033}]
    events = [D.EventHighlight("rookie_picks", "pick B", "Tanking", "low", 1, -0.0047, "k_b"),
              D.EventHighlight("rookie_picks", "pick A", "Tanking", "low", 2, -0.0041, "k_a")]
    got = [c.sentence() for c in D.diff_events(board, events)]
    ok &= _ok("and on the event board", got == [], f"got {got}")

    # A move the reader CAN see survives — the rule is about visibility, not
    # about small numbers.
    prev2 = {"teams": {"PF": [{"entity": "A", "value": 100.0}, {"entity": "B", "value": 90.0},
                              {"entity": "C", "value": 50.0}]}}
    curr2 = {"teams": {"PF": [{"entity": "A", "value": 100.0}, {"entity": "B", "value": 140.0},
                              {"entity": "C", "value": 50.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev2, curr2)]
    ok &= _ok("a visible overtake is still reported",
              any("B passes A" in s for s in got), f"got {got}")
    ok &= _ok("a tiny negative renders unsigned, not as '-0.0'",
              D._fmt(-0.0047) == "0.0", f"got {D._fmt(-0.0047)!r}")
    return ok


def check_a_tie_join_is_never_suppressed():
    """Equal values are the POINT of a join, so the visibility rule must not eat
    it — otherwise "joins a tie with X for highest" disappears exactly when it is
    most true."""
    prev = {"teams": {"Total trades": [{"entity": "A", "value": 102.0},
                                       {"entity": "B", "value": 100.0},
                                       {"entity": "C", "value": 5.0}]}}
    curr = {"teams": {"Total trades": [{"entity": "A", "value": 102.0},
                                       {"entity": "B", "value": 102.0},
                                       {"entity": "C", "value": 5.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    return _ok("B joining A's tie is reported even though both print 102",
               any("joins A in a tie for" in s for s in got), f"got {got}")


def check_a_cascade_where_nobody_moved_is_not_reported():
    """A leaderboard re-ranks for two reasons and says the same sentence for both.

    Either something moved, or something ABOVE it moved and everyone underneath
    was carried up a place standing still. The 2026-09-08 fix vacated 1st place
    on five KTC boards at once and the next digest reported 23 pick "moves", not
    one of which had its own value change — `Mac Jones passes Justin Fields for
    3rd-highest ...` with both numbers identical to last week's.
    """
    # On a ranking over VALUES an overtake always means somebody moved: two
    # entities that both stand still cannot swap order. So the pure cascade on
    # the all-time sections is the TIE-JOIN — B and C sit unchanged on the same
    # value and are promoted a rank only because A fell past them.
    prev = {"teams": {"KTC": [{"entity": "A", "value": 50.0}, {"entity": "B", "value": 30.0},
                              {"entity": "C", "value": 30.0}, {"entity": "D", "value": 10.0}]}}
    curr = {"teams": {"KTC": [{"entity": "A", "value": 5.0}, {"entity": "B", "value": 30.0},
                              {"entity": "C", "value": 30.0}, {"entity": "D", "value": 10.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok = _ok("B and C, tied and unchanged, are not reported as joining anything",
             not any(s.startswith(("B joins", "C joins")) for s in got), f"got {got}")
    # D did not overtake A either: D stood still and A fell past it. Until
    # 2026-09-22 that line stood (it named the entity that moved); the user ruled
    # a row that did not move passes nobody — "Gerald Everett passes Christian
    # Watson for 3rd-lowest Win % as starter" when Watson had just won.
    ok &= _ok("D, standing still while A fell past it, passes nobody",
              not any(s.startswith("D passes") for s in got), f"got {got}")

    # The MOVER moved -> real, reported.
    prev2 = {"teams": {"X": [{"entity": "P", "value": 10.0}, {"entity": "Q", "value": 5.0},
                             {"entity": "R", "value": 1.0}]}}
    curr2 = {"teams": {"X": [{"entity": "P", "value": 10.0}, {"entity": "Q", "value": 99.0},
                             {"entity": "R", "value": 1.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev2, curr2)]
    ok &= _ok("a mover whose own value rose is reported",
              any(s.startswith("Q passes P") for s in got), f"got {got}")

    # Only the RIVAL moved -> not reported (the same rule, on a separate shape).
    prev3 = {"teams": {"Y": [{"entity": "S", "value": 90.0}, {"entity": "T", "value": 80.0},
                             {"entity": "U", "value": 1.0}]}}
    curr3 = {"teams": {"Y": [{"entity": "S", "value": 2.0}, {"entity": "T", "value": 80.0},
                             {"entity": "U", "value": 1.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev3, curr3)]
    ok &= _ok("a mover the rival fell past is NOT reported",
              not any(s.startswith("T passes") for s in got), f"got {got}")
    # ...but the fall is news, told from the faller's side (user rule 2026-09-23).
    ok &= _ok("the rival that fell 'was passed by' the row that stood still",
              "S was passed by T for highest Y (80), falling to 2." in got, f"got {got}")
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok &= _ok("a faller is passed by every stand-still row now ahead of it, ties too",
              "A was passed by B, C and D for highest KTC (30), falling to 5." in got, f"got {got}")
    return ok


def check_arriving_from_off_the_board_is_judged_on_the_cutoff():
    """A row that was not on the board and is now either climbed on or was
    carried on when the board shortened above it. The prior board's worst place
    is what tells them apart."""
    board = [{"sheet": "rookie_picks", "key": "k_hi", "label": "hi", "column": "KTC",
              "end": "low", "rank": 1, "value": 0.0},
             {"sheet": "rookie_picks", "key": "k_mid", "label": "mid", "column": "KTC",
              "end": "low", "rank": 2, "value": 100.0}]
    # `out` was off the board at 200 (worse than the 100 cutoff) and is on it now
    # only because k_hi left. Nothing about `out` changed.
    events = [D.EventHighlight("rookie_picks", "mid", "KTC", "low", 1, 100.0, "k_mid"),
              D.EventHighlight("rookie_picks", "out", "KTC", "low", 2, 200.0, "k_out")]
    known = ["rookie_picks|k_hi", "k_hi", "k_mid", "k_out", "k_in", "k_tie"]
    got = [c.sentence() for c in D.diff_events(board, events, prior_row_keys=known)]
    ok = _ok("a row carried onto the board by a vacancy is not reported",
             not any(s.startswith("out ") for s in got), f"got {got}")

    # Same board, but the arrival is BETTER than last week's cutoff: it climbed
    # on under its own power, which is news.
    events2 = [D.EventHighlight("rookie_picks", "mid", "KTC", "low", 2, 100.0, "k_mid"),
               D.EventHighlight("rookie_picks", "in", "KTC", "low", 1, 50.0, "k_in")]
    got = [c.sentence() for c in D.diff_events(board, events2, prior_row_keys=known)]
    ok &= _ok("a row that climbed past the cutoff is reported",
              any(s.startswith("in ") for s in got), f"got {got}")

    # Landing exactly ON the cutoff counts as climbing: competition ranks would
    # have put it on the board already if it had held that value last week.
    events3 = [D.EventHighlight("rookie_picks", "mid", "KTC", "low", 1, 100.0, "k_mid"),
               D.EventHighlight("rookie_picks", "tie", "KTC", "low", 1, 100.0, "k_tie")]
    got = [c.sentence() for c in D.diff_events(board, events3, prior_row_keys=known)]
    ok &= _ok("arriving exactly at the cutoff is reported",
              any(s.startswith("tie ") for s in got), f"got {got}")

    # A brand-new row is new data by definition and never suppressed.
    events4 = [D.EventHighlight("rookie_picks", "mid", "KTC", "low", 1, 100.0, "k_mid"),
               D.EventHighlight("rookie_picks", "fresh", "KTC", "low", 2, 200.0, "k_fresh")]
    got = [c.sentence() for c in D.diff_events(board, events4, prior_row_keys=known)]
    ok &= _ok("a brand-new row is reported even at the tail",
              any(s.startswith("fresh ") for s in got), f"got {got}")

    # An older snapshot carries no values at all: nothing can be priced, so the
    # week re-baselines loudly rather than silently swallowing every move.
    bare = [{"sheet": "rookie_picks", "key": "k_mid", "label": "mid", "column": "KTC",
             "end": "low", "rank": 1}]
    events5 = [D.EventHighlight("rookie_picks", "mid", "KTC", "low", 2, 100.0, "k_mid"),
               D.EventHighlight("rookie_picks", "other", "KTC", "low", 1, 50.0, "k_other")]
    got = [c.sentence() for c in D.diff_events(bare, events5, prior_row_keys=known + ["k_other"])]
    ok &= _ok("a valueless prior snapshot suppresses nothing",
              any(s.startswith("other ") for s in got), f"got {got}")
    return ok


def check_an_arrival_at_first_reports_once_however_the_board_below_it_moves():
    """A new leader displaces everyone by one place. That is ONE piece of news.

    The rows it pushes down never become candidates — `diff_events` only reports
    a row whose rank IMPROVED — so the suppression rule only has to get the
    newcomer right, and it must not drop it just because it has no prior value
    on this board.
    """
    def board(rows):
        return [{"sheet": "rookie_picks", "key": f"k_{n}", "label": n, "column": "KTC",
                 "end": "high", "rank": r, "value": v} for n, r, v in rows]

    def ev(rows):
        return [D.EventHighlight("rookie_picks", n, "KTC", "high", r, v, f"k_{n}")
                for n, r, v in rows]
    known = ["k_A", "k_B", "k_C", "k_D", "k_E", "k_N"]
    prior = board([("A", 1, 100.), ("B", 2, 90.), ("C", 3, 80.),
                   ("D", 4, 70.), ("E", 5, 60.)])

    # The case asked about: everyone below is RE-VALUED but keeps relative order.
    got = [c.sentence() for c in D.diff_events(
        prior, ev([("N", 1, 200.), ("A", 2, 99.), ("B", 3, 89.),
                   ("C", 4, 79.), ("D", 5, 69.)]), prior_row_keys=known)]
    ok = _ok("re-valued but order-stable board below -> exactly one line",
             got == ["N passes A for highest KTC (200)."], f"got {got}")

    # Pure displacement: nobody below changes at all.
    got = [c.sentence() for c in D.diff_events(
        prior, ev([("N", 1, 200.), ("A", 2, 100.), ("B", 3, 90.),
                   ("C", 4, 80.), ("D", 5, 70.)]), prior_row_keys=known)]
    ok &= _ok("unchanged board below -> still exactly one line",
              got == ["N passes A for highest KTC (200)."], f"got {got}")

    # A new leader whose value is WORSE than last week's cutoff — the whole board
    # collapsed under it. It did not climb on (it could not have held a place at
    # that value last week), so it passes nobody: since 2026-09-22 a row that did
    # not move is not reported, whoever fell past it.
    got = [c.sentence() for c in D.diff_events(
        prior, ev([("N", 1, 10.), ("A", 2, 5.), ("B", 3, 4.),
                   ("C", 4, 3.), ("D", 5, 2.)]), prior_row_keys=known)]
    ok &= _ok("a collapsed board's new leader, carried there, is not reported",
              got == [], f"got {got}")

    # Tying for first is one line too.
    got = [c.sentence() for c in D.diff_events(
        prior, ev([("N", 1, 100.), ("A", 1, 100.), ("B", 3, 89.),
                   ("C", 4, 79.), ("D", 5, 69.)]), prior_row_keys=known)]
    # B held 2nd, the place the two-way tie now fills alongside 1st.
    ok &= _ok("tying for first -> one line, naming the place it took",
              got == ["N joins A in a tie for highest KTC (100), passing B."], f"got {got}")

    # And a real leapfrog underneath is separate news, so that week reports both.
    got = sorted(c.sentence() for c in D.diff_events(
        prior, ev([("N", 1, 200.), ("C", 2, 95.), ("A", 3, 94.),
                   ("B", 4, 89.), ("D", 5, 69.)]), prior_row_keys=known))
    ok &= _ok("a genuine leapfrog below the newcomer is reported as well",
              len(got) == 2 and got[0].startswith("C passes"), f"got {got}")
    return ok


def check_crossings_carry_last_weeks_value():
    """The lede needs the mover's OWN previous value to tell "the league did
    something" from "the board moved around a row that never budged"."""
    prev = {"teams": {"Total trades": [{"entity": "A", "value": 102.0},
                                       {"entity": "B", "value": 100.0},
                                       {"entity": "C", "value": 5.0}]}}
    curr = {"teams": {"Total trades": [{"entity": "A", "value": 102.0},
                                       {"entity": "B", "value": 102.0},
                                       {"entity": "C", "value": 5.0}]}}
    cx = D.diff_snapshots(prev, curr)
    ok = _ok("an all-time crossing carries prev_value",
             [c.prev_value for c in cx] == [100.0], f"got {[c.prev_value for c in cx]}")
    board = [{"sheet": "trades", "key": "k_a", "label": "trade A", "column": "O-Score",
              "end": "low", "rank": 4, "value": 7.8},
             {"sheet": "trades", "key": "k_b", "label": "trade B", "column": "O-Score",
              "end": "low", "rank": 5, "value": 7.9}]
    events = [D.EventHighlight("trades", "trade B", "O-Score", "low", 4, 7.8, "k_b"),
              D.EventHighlight("trades", "trade A", "O-Score", "low", 4, 7.8, "k_a")]
    ex = D.diff_events(board, events)
    ok &= _ok("an event crossing carries the value it held on the prior board",
              [c.prev_value for c in ex] == [7.9], f"got {[c.prev_value for c in ex]}")
    return ok


def run_all() -> bool:
    tests = [
        check_discovery_drops_non_numeric,
        check_ranking_order_and_missing,
        check_player_high_low_crossings,
        check_low_end_crossing,
        check_every_numeric_column_ranks,
        check_team_any_of_8_reported_once,
        check_new_entity_no_false_pass,
        check_in_season_gate,
        check_projection_gate_scale_and_weekly_exclusion,
        check_tie_skip_in_pace,
        check_yearly_records_for_weekly_stats,
        check_weekly_highlights,

        check_event_highlights,
        check_board_covers_every_sheet,
        check_event_board_diff,
        check_yearly_counting_low_end_off_board,
        check_event_diff_flags_new_rows,
        check_tie_joins_are_said_to_be_ties,
        check_all_time_tie_joins,
        check_section_reading_order,
        check_bullet_groups_stay_together_at_their_best_place,
        check_records_are_first_places,
        check_flat_sections_are_ordered_too,
        check_order_is_stable,
        check_first_place_drops_the_ordinal,
        check_a_line_does_not_repeat_its_own_header,
        check_group_label_is_the_bare_entity,
        check_league_sections_drop_the_redundant_label,
        check_event_labels,
        check_an_acquisition_never_reads_as_a_disposal,
        check_the_rename_does_not_desync_the_baseline,
        check_mirrored_columns,
        check_even_events_stay_on_the_board,
        check_replica_minimal,
        check_league_window,
        check_league_milestones,
        check_pace_diff_reports_only_changes,
        check_rate_and_weekly_classification,
        check_phrasing_catalog,
        check_render_html_smoke,
        check_digest_title,
        check_an_invisible_overtake_is_not_reported,
        check_a_tie_join_is_never_suppressed,
        check_a_cascade_where_nobody_moved_is_not_reported,
        check_arriving_from_off_the_board_is_judged_on_the_cutoff,
        check_an_arrival_at_first_reports_once_however_the_board_below_it_moves,
        check_crossings_carry_last_weeks_value,
        check_counting_stat_classification,
        check_percent_columns_print_as_percent,
        check_single_week_ties_say_tie_and_skip_running_totals,
        check_in_progress_season_rows_only_on_counting_high_end,
        check_young_moves_only_on_counting_high_end,
        check_offseason_move_joins_at_week_5,
        check_week_rows_season_to_date_and_new_stint_wait,
        check_a_running_total_passing_its_own_row_is_not_news,
        check_a_stationary_tie_join_is_not_news,
        check_release_lead_counts_what_the_gate_let_go,
        check_rookie_oscore_week_matches_the_build,
        check_a_season_streak_passing_its_own_season_is_not_news,
        check_a_repeat_pickup_passing_its_own_pickup_is_not_news,
        check_a_head_to_head_streak_is_its_own_rivalry,
        check_an_old_snapshot_without_entities_still_compares_entities,
        check_terminal_encoding_survives_pandas3_strings,
        check_rookie_class_waits_for_week_8_on_player_boards,
        check_columns_are_named_for_the_email,
        check_a_tie_must_fit_inside_the_window,
        check_passes_names_only_the_place_taken,
        check_this_weeks_rows_are_told_once,
        check_opponent_stats_name_the_opponent,
        check_a_tie_reached_together_is_one_line,
        check_real_exports_smoke,
    ]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


# ---------------------------------------------------------------------------
# Week-5 gates, ties, percentages, running totals (2026-09-15 review of week 1)
# ---------------------------------------------------------------------------
def _labels(hl, column=None, end=None):
    return {h.label for h in hl if (column is None or h.column == column)
            and (end is None or h.end == end)}


def _weeks(**season_weeks):
    """team_week with Year/Week only: _weeks(y2025=17, y2026=3)."""
    yrs, wks = [], []
    for k, n in season_weeks.items():
        yrs += [int(k[1:])] * n
        wks += list(range(1, n + 1))
    return pd.DataFrame({"Year": yrs, "Week": wks})


def check_counting_stat_classification():
    ok = True
    for col in ("PF", "Points added", "Faab", "Number of pure drops", "Luck",
                "Times Most injured?", "Total points as team starter", "Games played on team"):
        ok &= _ok(f"'{col}' counts", D.is_counting_stat(col))
    for col in ("Win %", "All-play win % minus Win %", "Avg points", "PPG as team starter",
                "Player addition value", "O-Score", "KTC at pickup", "Trade impact score",
                "Change in points from previous season", "Tanking", "Number", "Season",
                "Increase in points from previous week"):
        ok &= _ok(f"'{col}' does not", not D.is_counting_stat(col))
    return ok


def check_percent_columns_print_as_percent():
    frames = {
        "team_year": pd.DataFrame({"Team": ["A", "B"], "% of points from WRs": [0.104, 0.52],
                                   "% of starters boom": [17.5, 9.0], "Win %": [0.5, 1.0]}),
        "team_all_time": pd.DataFrame({"Team": ["A", "B"], "Win %": [0.45, 0.61]}),
    }
    got = D.note_percent_columns(frames)
    ok = _ok("0-1 '%' columns are found", {"% of points from WRs", "Win %"} <= got, got)
    ok &= _ok("a 0-100 '%' column is not", "% of starters boom" not in got, got)
    ok &= _ok("a fraction prints as a percent",
              D._fmt_stat("% of points from WRs", 0.104) == "10.4%",
              D._fmt_stat("% of points from WRs", 0.104))
    ok &= _ok("a whole fraction prints without decimals", D._fmt_stat("Win %", 1.0) == "100%")
    ok &= _ok("a 0-100 column is left alone", D._fmt_stat("% of starters boom", 17.5) == "17.5")
    line = D.WeeklyHighlight("teams", "A", "% of points from WRs", "low", 2, 0.104).line()
    ok &= _ok("and the email line says 10.4%", "(10.4%)" in line, line)
    two = D._indistinguishable(0.104, [0.096], "% of points from WRs")
    ok &= _ok("10.4% vs 9.6% is visible (both were '0.1')", not two)
    D.note_percent_columns({})
    return ok


def check_single_week_ties_say_tie_and_skip_running_totals():
    tw = pd.DataFrame({
        "Team": ["A", "B", "C", "A", "B", "C"],
        "Year": [2025, 2025, 2025, 2026, 2026, 2026], "Week": [1, 1, 1, 1, 1, 1],
        "PF": [100.0, 150.0, 120.0, 150.0, 90.0, 130.0],
        # terminal-encoded running count: its value hops onto the newest row
        "Bottom half streak": ["In Progress", 0, 4, 5, 0, 0],
        "Number of weeks on team": [30, 40, 50, 31, 41, 51],
    })
    ty = pd.DataFrame({"Team": ["A"], "Year": [2026]})
    hl = D.weekly_highlights(pd.DataFrame(), tw, pd.DataFrame(), ty, window=3,
                             season=2026, week=1)
    a_pf = [h for h in hl if h.entity == "A" and h.column == "PF"]
    ok = _ok("A's 150 ties B's 2025 week for highest PF", a_pf and a_pf[0].tied, a_pf)
    ok &= _ok("the bullet ends '(tie)'", a_pf and a_pf[0].detail().endswith("highest ever (tie)"),
              a_pf and a_pf[0].detail())
    ok &= _ok("the sentence says so too", a_pf and a_pf[0].sentence().endswith("ever (tie)."),
              a_pf and a_pf[0].sentence())
    c_pf = [h for h in hl if h.entity == "C" and h.column == "PF"]
    ok &= _ok("an untied place has no '(tie)'", c_pf and "(tie)" not in c_pf[0].detail(), c_pf)
    cols = {h.column for h in hl}
    ok &= _ok("a terminal-encoded streak is not a single-week record",
              "Bottom half streak" not in cols, cols)
    ok &= _ok("nor is a running count like weeks on team",
              "Number of weeks on team" not in cols, cols)
    return ok


def _season_frames(played_2026):
    ty = pd.DataFrame({
        "Team": ["T1", "T2", "T3", "T4", "T5", "Hi", "Lo"],
        "Year": [2021, 2022, 2023, 2024, 2025, 2026, 2026],
        "PF": [1000.0, 1100, 1200, 1300, 1400, 9999, 5],
        "Win %": [0.5, 0.6, 0.4, 0.55, 0.45, 1.0, 0.0],
    })
    tw = _weeks(y2021=14, y2022=14, y2023=14, y2024=14, y2025=14, y2026=played_2026)
    return {"team_year": ty, "team_week": tw}


def check_in_progress_season_rows_only_on_counting_high_end():
    fr = _season_frames(2)
    hl = D.board_highlights(fr["team_year"], "team_year", window=3, gate=D.BoardGate(fr))
    ok = _ok("this season's high end of a count stands (highest PF)",
             "Hi 2026" in _labels(hl, "PF", "high"), _labels(hl, "PF"))
    ok &= _ok("its low end of a count waits (lowest PF after 2 weeks)",
              "Lo 2026" not in _labels(hl, "PF", "low"), _labels(hl, "PF", "low"))
    ok &= _ok("a rate waits at both ends (Win % 1.0 / 0.0)",
              not {"Hi 2026", "Lo 2026"} & _labels(hl, "Win %"), _labels(hl, "Win %"))
    ok &= _ok("completed seasons fill the places instead",
              "T2 2022" in _labels(hl, "Win %", "high"), _labels(hl, "Win %"))
    ok &= _ok("still waiting at week 5 (the board is for finished seasons)",
              "Lo 2026" not in _labels(D.board_highlights(
                  fr["team_year"], "team_year", window=3,
                  gate=D.BoardGate(_season_frames(5))), "PF", "low"))
    done = _season_frames(14)
    hl2 = D.board_highlights(done["team_year"], "team_year", window=3, gate=D.BoardGate(done))
    ok &= _ok("once the season is complete everything stands",
              "Lo 2026" in _labels(hl2, "PF", "low") and "Hi 2026" in _labels(hl2, "Win %", "high"),
              _labels(hl2))
    nogate = D.board_highlights(fr["team_year"], "team_year", window=3)
    ok &= _ok("no gate -> the board is unchanged", "Lo 2026" in _labels(nogate, "PF", "low"))
    ok &= _ok("nothing names a year: 2027 gates the same way",
              D.BoardGate({"team_year": pd.DataFrame({"Team": ["A"], "Year": [2027]}),
                           "team_week": _weeks(y2026=17, y2027=1)}).season_open)
    return ok


def _trades(extra_date):
    rows = [("T1", "2021-10-05", 2021, 10.0, 30.0, 5.0), ("T2", "2022-10-05", 2022, 11.0, 40.0, 6.0),
            ("T3", "2023-10-05", 2023, 12.0, 50.0, 7.0), ("T4", "2024-10-05", 2024, 13.0, 60.0, 8.0),
            ("T5", "2025-10-05", 2025, 14.0, 70.0, 9.0), ("New", extra_date, 2026, 40.0, 99.0, -50.0)]
    return pd.DataFrame(rows, columns=["Team", "Date", "Season",
                                       "Avg PPG of received players on team", "Points added",
                                       "Trade addition value"]).assign(
        **{"Team's traded with 1": "Z", "Assets received": "Somebody"})


def check_young_moves_only_on_counting_high_end():
    tr = _trades("2026-09-16")            # a week-2 trade (Tue-Mon weeks)
    young = {"trades": tr, "team_week": _weeks(y2025=17, y2026=3)}
    hl = D.board_highlights(tr, "trades", window=3, gate=D.BoardGate(young))
    new = {(h.column, h.end) for h in hl if h.label.startswith("New's")}
    ok = _ok("its counting stat's high end stands (Points added)",
             ("Points added", "high") in new, new)
    ok &= _ok("its average waits (Avg PPG on team)",
              not any(c.startswith("Avg PPG") for c, _e in new), new)
    ok &= _ok("its value waits (lowest Trade addition value)",
              ("Trade addition value", "low") not in new, new)
    aged = {"trades": tr, "team_week": _weeks(y2025=17, y2026=6)}   # weeks 2-6 played
    new2 = {(h.column, h.end) for h in D.board_highlights(tr, "trades", window=3,
                                                          gate=D.BoardGate(aged))
            if h.label.startswith("New's")}
    ok &= _ok("five NFL weeks after the move, all of it stands",
              ("Avg PPG of received players on team", "high") in new2
              and ("Trade addition value", "low") in new2, new2)
    return ok


def check_offseason_move_joins_at_week_5():
    last = {2025: 17}
    ok = _ok("an offseason move is for week 1", D.event_start_week("2026-07-10", last) == (2026, 1))
    ok &= _ok("Monday night belongs to the week just played",
              D.event_start_week("2026-09-14 23:00:00", last) == (2026, 1))
    ok &= _ok("Tuesday starts the next fantasy week",
              D.event_start_week("2026-09-15 10:00:00", last) == (2026, 2))
    ok &= _ok("a January move after a 17-week season is offseason",
              D.event_start_week("2026-01-03", last) == (2026, 1))
    ok &= _ok("...but inside an 18-week season it is that season's week 18",
              D.event_start_week("2026-01-03", {2025: 18}) == (2025, 18))
    ok &= _ok("an unreadable date gates nothing", D.event_start_week("n/a", last) is None)
    tr = _trades("2026-07-10")
    for played, want in ((4, False), (5, True)):
        fr = {"trades": tr, "team_week": _weeks(y2025=17, y2026=played)}
        stands = any(h.label.startswith("New's") and h.column.startswith("Avg PPG")
                     for h in D.board_highlights(tr, "trades", window=3, gate=D.BoardGate(fr)))
        ok &= _ok(f"week {played}: the offseason trade's average {'stands' if want else 'waits'}",
                  stands == want)
    picks = pd.DataFrame({"Year": [2022, 2023, 2024, 2025, 2026], "Number": ["1.01"] * 5,
                          "Player Picked": list("ABCDE"),
                          "Avg PPG on team": [5.0, 6, 7, 8, 30]})
    # The rookie class waits longer: until week 8, when the build grades it.
    for played, want in ((5, False), (7, False), (8, True)):
        fr = {"rookie_picks": picks, "team_week": _weeks(y2025=17, y2026=played)}
        stands = "2026 pick 1.01 (E)" in _labels(D.board_highlights(
            picks, "rookie_picks", window=3, gate=D.BoardGate(fr)), "Avg PPG on team")
        ok &= _ok(f"week {played}: this year's rookie pick {'stands' if want else 'waits'}",
                  stands == want)
    return ok


def check_week_rows_season_to_date_and_new_stint_wait():
    rows = [(f"P{i}", "X", 2025, 17, 20.0 + i, 15.0 + i, 30) for i in range(4)]
    rows += [("New", "Y", 2026, 1, 40.0, 40.0, 1), ("Vet", "Z", 2026, 1, 39.0, 39.0, 50)]
    pw = pd.DataFrame(rows, columns=["Player", "Team", "Year", "Week",
                                     "PPG as team starter this season", "PPG as team starter",
                                     "Number of weeks on team"])
    ty = pd.DataFrame({"Team": ["X"], "Year": [2026]})

    def board(played):
        fr = {"player_week": pw, "team_year": ty, "team_week": _weeks(y2025=17, y2026=played)}
        return D.board_highlights(pw, "player_week", window=3, gate=D.BoardGate(fr))

    b1 = board(1)
    ok = _ok("week 1: no season-to-date average from this season",
             not {"New 2026 week 1", "Vet 2026 week 1"} & _labels(b1, "PPG as team starter this season"),
             _labels(b1, "PPG as team starter this season"))
    ok &= _ok("week 1: a one-week-old stint's PPG on team waits",
              "New 2026 week 1" not in _labels(b1, "PPG as team starter"),
              _labels(b1, "PPG as team starter"))
    ok &= _ok("week 1: a long stint's PPG on team stands",
              "Vet 2026 week 1" in _labels(b1, "PPG as team starter"),
              _labels(b1, "PPG as team starter"))
    b5 = board(5)
    ok &= _ok("week 5: this season's week rows join, week 1 included",
              "New 2026 week 1" in _labels(b5, "PPG as team starter this season"),
              _labels(b5, "PPG as team starter this season"))
    ok &= _ok("week 5: the stint is five weeks old and joins",
              "New 2026 week 1" in _labels(b5, "PPG as team starter"),
              _labels(b5, "PPG as team starter"))
    return ok


def _place(sheet, key, label, col, rank, value, end="high"):
    return {"sheet": sheet, "key": key, "label": label, "column": col,
            "end": end, "rank": rank, "value": value}


def check_a_running_total_passing_its_own_row_is_not_news():
    col = "Weeks rostered by this team"

    def ev(key, label, rank, value):
        return D.EventHighlight("player_week", label, col, "high", rank, value, key=key,
                                running=True)

    prior = [_place("player_week", "ja25", "Josh Allen 2025 week 17", col, 1, 101.0),
             _place("player_week", "dp25", "Dak Prescott 2025 week 17", col, 1, 101.0),
             _place("player_week", "jj25", "Justin Jefferson 2025 week 17", col, 3, 90.0)]
    now = [ev("ja26", "Josh Allen 2026 week 1", 1, 102.0),
           ev("dp26", "Dak Prescott 2026 week 1", 1, 102.0),
           ev("jj26", "Justin Jefferson 2026 week 1", 3, 91.0)]
    got = [c.sentence() for c in D.diff_events(prior, now)]
    ok = _ok("four players ticking up a week in the same order is not news", got == [], got)

    prior2 = [_place("player_week", "a25", "Alpha 2025 week 17", "Bottom half streak", 1, 10.0),
              _place("player_week", "b25", "Beta 2025 week 17", "Bottom half streak", 2, 9.0)]
    now2 = [D.EventHighlight("player_week", "Beta 2026 week 1", "Bottom half streak", "high",
                             1, 11.0, key="b26", running=True),
            D.EventHighlight("player_week", "Alpha 2025 week 17", "Bottom half streak", "high",
                             2, 10.0, key="a25", running=True)]
    got2 = [c.sentence() for c in D.diff_events(prior2, now2)]
    ok &= _ok("climbing past ANOTHER player is news, named without its own old row",
              got2 == ["Beta 2026 week 1 passes Alpha 2025 week 17 for highest Bottom half streak (11)."],
              got2)
    return ok


def check_a_stationary_tie_join_is_not_news():
    prev = {"teams": {"Startup draft players remaining": [
        {"entity": "A", "value": 3.0}, {"entity": "B", "value": 1.0},
        {"entity": "C", "value": 0.0}, {"entity": "D", "value": 0.0}]}}
    curr = {"teams": {"Startup draft players remaining": [
        {"entity": "A", "value": 3.0}, {"entity": "B", "value": 0.0},
        {"entity": "C", "value": 0.0}, {"entity": "D", "value": 0.0}]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok = _ok("teams long at 0 do not 'join a tie' because another team fell to 0",
             not any(s.startswith(("C joins", "D joins")) for s in got), got)

    col = "KTC"
    prior = [_place("rookie_picks", "kA", "pick A", col, 1, 10.0),
             _place("rookie_picks", "kB", "pick B", col, 2, 8.0),
             _place("rookie_picks", "kC", "pick C", col, 2, 8.0)]
    now = [D.EventHighlight("rookie_picks", lbl, col, "high", 1, 8.0, key=k)
           for k, lbl in (("kA", "pick A"), ("kB", "pick B"), ("kC", "pick C"))]
    got2 = [c.sentence() for c in D.diff_events(prior, now)]
    ok &= _ok("nor on an event board, when the row above fell to them", got2 == [], got2)
    return ok


def check_release_lead_counts_what_the_gate_let_go():
    tr = _trades("2026-07-10")
    lagged = {"trades": tr, "team_week": _weeks(y2025=17, y2026=4)}
    now = {"trades": tr, "team_week": _weeks(y2025=17, y2026=5)}
    prior = D.event_board(D.all_board_highlights(lagged, window=3, gate=D.BoardGate(lagged)))
    events = D.all_board_highlights(now, window=3, gate=D.BoardGate(now))
    changes = D.diff_events(prior, events)
    released = [c for c in changes if c.label.startswith("New's")]
    ok = _ok("week 5 releases the offseason trade's averages onto the board", released,
             [c.sentence() for c in changes])
    secs = D.digest_sections(events=changes)
    meta = {"season": 2026, "weeks_completed": 5}
    nd = D.NewData(season=2026, weeks_completed=5, new_weeks={(2026, 5)})
    lead = D.release_lead(now, meta, nd, [], changes, secs, window=3)
    total = sum(len(i) for _t, _g, i in secs)
    ok &= _ok("the week-5 lede counts them", lead.startswith("Week 5 is when")
              and f"{len(released)} of the {total}" in lead
              or (len(released) == total and f"all {total}" in lead), lead)
    nd6 = D.NewData(season=2026, weeks_completed=6, new_weeks={(2026, 6)})
    ok &= _ok("week 6 has no release line",
              D.release_lead(now, {"season": 2026, "weeks_completed": 6}, nd6, [], changes, secs,
                             window=3) == "")
    return ok


def _diff_boards(sheet, before, after, window=3):
    prior = D.event_board(D.board_highlights(before, sheet, window=window))
    return [c.sentence() for c in D.diff_events(prior, D.board_highlights(after, sheet, window=window))]


def check_a_season_streak_passing_its_own_season_is_not_news():
    """A season streak is terminal-encoded like a week one: extending it moves the
    total onto the new season's row. "A 2025 passes A 2024 for 2nd-highest
    Winning season streak" is one team's streak growing, told as two."""
    col = "Winning season streak"

    def ty(a_rows):
        rows = [("D", 2020, 5), ("C", 2021, 1), ("B", 2022, 2)] + a_rows
        return pd.DataFrame(rows, columns=["Team", "Year", col]).astype({col: object})

    before = ty([("A", 2023, "In Progress"), ("A", 2024, 3)])
    after = ty([("A", 2023, "In Progress"), ("A", 2024, "In Progress"), ("A", 2025, 4)])
    got = _diff_boards("team_year", before, after)
    ok = _ok("A 2025 extending the streak A 2024 held is not news", got == [], got)
    record = ty([("A", 2023, "In Progress"), ("A", 2024, "In Progress"), ("A", 2025, 6)])
    got2 = _diff_boards("team_year", before, record)
    ok &= _ok("extending it past ANOTHER team's streak is, naming only them",
              got2 == ["A 2025 passes D 2020 for highest Winning season streak (6)."], got2)
    return ok


def check_a_repeat_pickup_passing_its_own_pickup_is_not_news():
    """"Number of times picked up by this team" counts one team's pickups of one
    player, so each new pickup row is the same tally one higher."""
    col = "Number of times picked up by this team"
    base = [("V", "R", "2020-10-01", 5), ("W", "S", "2020-11-01", 1),
            ("T", "P", "2021-10-01", 1), ("T", "P", "2022-10-01", 2)]

    def ad(rows):
        return pd.DataFrame(rows, columns=["Team", "Player Added", "Date", col]).assign(
            **{"Player Dropped": "", "Season": 2022})

    got = _diff_boards("add_drops", ad(base), ad(base + [("T", "P", "2023-10-01", 3)]), window=2)
    ok = _ok("T picking P up a 3rd time does not pass T's 2nd pickup of P", got == [], got)
    got2 = _diff_boards("add_drops", ad(base), ad(base + [("T", "P", "2023-10-01", 6)]), window=2)
    ok &= _ok("a tally that passes another team's record still reports, naming only it",
              len(got2) == 1 and "passes V's 2020-10-01 move for R" in got2[0], got2)
    return ok


def check_a_head_to_head_streak_is_its_own_rivalry():
    """"Win streak vs this opponent" belongs to a team AND an opponent: A's streak
    over B growing is not news against its own last row, but passing A's streak
    over C is a different rivalry."""
    col = "Win streak vs this opponent"

    def tw(rows):
        return pd.DataFrame(rows, columns=["Team", "Opponent", "Year", "Week", col]).astype({col: object})

    base = [("A", "C", 2024, 3, 6), ("X", "Y", 2020, 1, 3), ("A", "B", 2025, 1, 4)]
    grown = base[:2] + [("A", "B", 2025, 1, "In Progress"), ("A", "B", 2026, 1, 5)]
    got = _diff_boards("team_week", tw(base), tw(grown))
    ok = _ok("A over B growing a week is not news against A over B's last row", got == [], got)
    past = base[:2] + [("A", "B", 2025, 1, "In Progress"), ("A", "B", 2026, 1, 7)]
    got2 = _diff_boards("team_week", tw(base), tw(past))
    ok &= _ok("passing A's streak over C is news",
              got2 == ["A 2026 week 1 passes A 2024 week 3 for highest Win streak vs this opponent (7)."],
              got2)
    return ok


def check_an_old_snapshot_without_entities_still_compares_entities():
    col = "Total points as team starter"
    prior = [_place("player_week", "ja25", "Josh Allen 2025 week 17", col, 1, 2200.0)]
    now = [D.EventHighlight("player_week", "Josh Allen 2026 week 1", col, "high", 1, 2250.9,
                            key="ja26", running=True, entity="Josh Allen")]
    got = [c.sentence() for c in D.diff_events(prior, now)]
    ok = _ok("a baseline written before entities were stored falls back to the label", got == [], got)
    board = D.event_board(now)
    ok &= _ok("and the snapshot now stores each place's entity",
              bool(board) and board[0].get("entity") == "Josh Allen", board)
    return ok


def check_a_season_streak_held_back_keeps_its_run_on_the_board():
    """A season streak running on into the in-progress season moves its total onto
    that (held) row and leaves "In Progress" behind it. Without its completed run
    put back, the run vanishes and the rows below climb a place standing still."""
    col = "Winning season streak"
    ones = [("B", 2022, 1), ("C", 2023, 1), ("D", 2024, 1), ("E", 2024, 1), ("F", 2023, 1)]

    def ty(tail):
        return pd.DataFrame([("A", 2021, 4)] + ones + tail,
                            columns=["Team", "Year", col]).astype({col: object})

    before = ty([("S", 2024, "In Progress"), ("S", 2025, 2), ("S", 2026, None),
                 ("T", 2025, 1), ("T", 2026, None)])
    after = ty([("S", 2024, "In Progress"), ("S", 2025, "In Progress"), ("S", 2026, 3),
                ("T", 2025, "In Progress"), ("T", 2026, 2)])
    seasons = dict(y2021=14, y2022=14, y2023=14, y2024=14, y2025=14)
    g0 = D.BoardGate({"team_year": before, "team_week": _weeks(**seasons)})
    g1 = D.BoardGate({"team_year": after, "team_week": _weeks(**seasons, y2026=1)})
    b0 = D.board_highlights(before, "team_year", window=5, gate=g0)
    b1 = D.board_highlights(after, "team_year", window=5, gate=g1)
    ok = _ok("S's run stays on the board as S 2025 (2) while 2026 is held",
             any(h.label == "S 2025" and h.value == 2.0 for h in b1)
             and "S 2026" not in _labels(b1), [(h.label, h.value) for h in b1])
    got = [c.sentence() for c in D.diff_events(D.event_board(b0), b1)]
    ok &= _ok("nothing below climbs because two runs carried on into 2026", got == [], got)
    done = D.BoardGate({"team_year": after, "team_week": _weeks(**seasons, y2026=14)})
    b2 = D.board_highlights(after, "team_year", window=5, gate=done)
    ok &= _ok("once 2026 is complete the run shows on its own row",
              "S 2026" in _labels(b2) and "S 2025" not in _labels(b2), _labels(b2))
    got2 = [c.sentence() for c in D.diff_events(D.event_board(b1), b2)]
    ok &= _ok("...and moving onto it is not 'S 2026 passes S 2025'",
              not any("passes S 2025" in s or "with S 2025" in s for s in got2), got2)
    return ok


def check_rookie_oscore_week_matches_the_build():
    import re as _re
    src = (_ROOT / "src" / "lotg.py").read_text()
    m = _re.search(r"^_ROOKIE_OSCORE_MIN_WEEK\s*=\s*(\d+)", src, _re.M)
    return _ok("digest's ROOKIE_OSCORE_WEEK == the build's _ROOKIE_OSCORE_MIN_WEEK",
               m and int(m.group(1)) == D.ROOKIE_OSCORE_WEEK, m and m.group(0))


# ---------------------------------------------------------------------------
# Run 515 (2026-09-22, week 2): the week-5 gates did not hold in CI
def _read_csv_as_ci_does(text):
    """read_csv under pandas 3's string inference — what CI installs (3.0.6 on run
    515) — whichever pandas runs the test. On pandas 3 the option may be gone,
    and the default is what we want anyway."""
    import io
    try:
        with pd.option_context("future.infer_string", True):
            return pd.read_csv(io.StringIO(text))
    except (KeyError, pd.errors.OptionError):
        return pd.read_csv(io.StringIO(text))


def check_terminal_encoding_survives_pandas3_strings():
    # The real shape: a CSV column of numbers and "In Progress", no "streak" in
    # its name. Under pandas 3 it reads as the `str` dtype, not `object`, and the
    # old `dtype == object` test lost it: Pat Freiermuth 2026 week 2 passed Pat
    # Freiermuth 2026 week 1 for highest Total weeks on bench.
    pw = _read_csv_as_ci_does(
        "Player,Year,Week,Points,Total weeks on bench,Weeks rostered by this team\n"
        "Pat,2026,1,1.0,In Progress,In Progress\n"
        "Pat,2026,2,2.0,76,103\n"
        "Bo,2025,1,30.0,70,90\n"
        "Cy,2025,1,20.0,10,12\n"
        "Di,2025,1,10.0,5,6\n")
    run = D.running_columns(pw)
    ok = _ok("a CSV-read terminal-encoded total is a running column",
             {"Total weeks on bench", "Weeks rostered by this team"} <= run,
             f"{run} (dtype {pw['Total weeks on bench'].dtype})")
    ok &= _ok("a plain numeric column is not", "Points" not in run, run)
    hl = D.weekly_highlights(pw, pd.DataFrame(), pd.DataFrame(),
                             pd.DataFrame({"Year": [2026]}), window=3, season=2026, week=2)
    cols = {h.column for h in hl}
    ok &= _ok("neither prints as a single-week record",
              not cols & {"Total weeks on bench", "Weeks rostered by this team"}, cols)
    return ok


def check_rookie_class_waits_for_week_8_on_player_boards():
    # Week 2 of 2026: Denzel Boston, two games in, on three all-time rate boards.
    def frames(played):
        return {
            "team_year": pd.DataFrame({"Team": ["A"], "Year": [2026]}),
            "team_week": _weeks(y2025=17, y2026=played),
            "player_week": pd.DataFrame({"Player": ["Rook", "Vet"], "Year": [2026, 2026],
                                         "Week": [1, 1], "Rookie?": [True, False]}),
        }

    def pat(rook_avg, rook_pts):
        vets = [f"V{i}" for i in range(9)]
        return pd.DataFrame({"Player": vets + ["Rook"],
                             "Avg points": [10.0 + i for i in range(9)] + [rook_avg],
                             "Points": [100.0 + 10 * i for i in range(9)] + [rook_pts]})

    team = pd.DataFrame({"Team": ["A", "B"], "Points": [1.0, 2.0]})
    tw = pd.DataFrame({"Year": [], "Week": []})

    def snap(played, rook_avg, rook_pts):
        gate = D.BoardGate(frames(played))
        return D.build_snapshot(pat(rook_avg, rook_pts), team, frames(played)["team_year"], tw,
                                held_players=gate.held_rookies())

    ok = _ok("the class is held before week 8", D.BoardGate(frames(2)).held_rookies() == {"Rook"})
    ok &= _ok("and let go at week 8", D.BoardGate(frames(8)).held_rookies() == set())
    # Week 1 -> 2: the rookie leaps to the top of a rate and of a count.
    cr = D.diff_snapshots(snap(1, 5.0, 5.0), snap(2, 50.0, 500.0))
    mine = {(c.column, c.end) for c in cr if c.mover == "Rook"}
    ok &= _ok("a held rookie's average is not reported", ("Avg points", "high") not in mine, mine)
    ok &= _ok("the high end of his count is", ("Points", "high") in mine, mine)
    # A count's low end is not his to hold either (two games of points).
    cr = D.diff_snapshots(snap(1, 5.0, 500.0), snap(2, 5.0, 1.0))
    ok &= _ok("nor the low end of a count",
              not [c for c in cr if c.mover == "Rook" and c.end == "low"],
              [c.sentence() for c in cr])
    # Week 7 -> 8: released. His average debuts on the board, from below it.
    prior, curr = snap(7, 50.0, 500.0), snap(8, 50.0, 500.0)
    cr = D.diff_snapshots(prior, curr)
    debut = [c for c in cr if c.mover == "Rook" and c.column == "Avg points"]
    ok &= _ok("week 8 reports his debut place on a rate board",
              debut and debut[0].rank == 1 and debut[0].prev_value is None,
              [c.sentence() for c in cr])
    secs = D.digest_sections(crossings=cr)
    nd = D.NewData(season=2026, weeks_completed=8, new_weeks={(2026, 8)})
    lead = D.release_lead(frames(8), curr["meta"], nd, [], [], secs,
                          crossings=cr, prior=prior)
    ok &= _ok("and the week-8 lede counts it", lead.startswith("Week 8 is when"), lead)
    return ok


# ---------------------------------------------------------------------------
# 2026-09-22 review of the week-2 email
def check_columns_are_named_for_the_email():
    ok = _ok("an award drops its '?'",
             D.display_column("Times as Highest starter on team?") == "Times as Highest starter on team")
    ok &= _ok("a points threshold says pts (once)",
              D.display_column("Players over 30 pts (roster)") == "Players over 30 pts (roster)"
              and D.display_column("Players under 10 pts (starters)") == "Players under 10 pts (starters)"
              and D.display_column("Number of games within 10") == "Number of games within 10 pts")
    ok &= _ok("an age column does not",
              D.display_column("Player average age") == "Player average age")
    ok &= _ok("a trade's difference of averages says of what",
              D.display_column("Difference of averages", "trades") == "PPG difference (received − sent)")
    ok &= _ok("an add/drop's says of what, differently",
              D.display_column("Difference of averages", "add_drops")
              == "PPG difference (added − dropped player)")
    c = D.Crossing("players", "Times as Captain?", "high", 1, "A", 3.0, passed=("B",))
    ok &= _ok("and the sentence uses the display name", "Captain?" not in c.sentence(), c.sentence())
    return ok


def check_a_tie_must_fit_inside_the_window():
    ok = _ok("a two-way tie for 5th does not fit", not D._tie_fits(5, 2, 5))
    ok &= _ok("a three-way tie for 4th does not", not D._tie_fits(4, 3, 5))
    ok &= _ok("a two-way tie for 4th does", D._tie_fits(4, 2, 5))
    ok &= _ok("a five-way tie for 1st does", D._tie_fits(1, 5, 5))
    # On a board: 10, 9, 8, then three rows at 7 (4th-6th), then 6.
    pool = pd.Series([10.0, 9.0, 8.0, 7.0, 7.0, 7.0, 6.0, 1.0, 1.0, 0.5])
    places = D._board_places(pool, "high", 5, 5)
    ok &= _ok("the three-way tie for 4th holds no place", 7.0 not in places, places)
    ok &= _ok("and still takes up its places (6 is 7th, off the board)", 6.0 not in places, places)
    # All-time crossing: arriving into a three-way tie for 4th is not reported.
    prev = {"players": {"X": [{"entity": e, "value": v} for e, v in
                              [("A", 10.0), ("B", 9.0), ("C", 8.0), ("D", 7.0), ("E", 7.0),
                               ("F", 3.0)] + [(f"Z{i}", 0.0) for i in range(6)]]}}
    curr = {"players": {"X": [dict(e, value=7.0) if e["entity"] == "F" else e
                              for e in prev["players"]["X"]]}}
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok &= _ok("F joining a three-way tie for 4th is not reported",
              not any(s.startswith("F ") for s in got), got)
    return ok


def check_passes_names_only_the_place_taken():
    # Jaxson Dart, 18.6 -> 1.7 on Consistency percentile: only the row that held
    # the place he took is named, not the 58 he leapt to get there.
    vals = [("R", 0.8), ("M", 0.9), ("C", 1.6), ("F", 1.7), ("J", 1.8)] + \
           [(f"P{i}", 2.0 + i) for i in range(20)] + [("Dart", 18.6)]
    prev = {"players": {"Consistency percentile":
                        [{"entity": e, "value": v} for e, v in vals]}}
    curr = {"players": {"Consistency percentile":
                        [{"entity": e, "value": 1.65 if e == "Dart" else v} for e, v in vals]}}
    got = [c for c in D.diff_snapshots(prev, curr) if c.mover == "Dart"]
    ok = _ok("Dart's move is reported", got, [c.sentence() for c in got])
    ok &= _ok("naming only F, who held the place he took",
              got and got[0].passed == ("F",), got and got[0].passed)
    return ok


def check_this_weeks_rows_are_told_once():
    hl = [D.WeeklyHighlight("players", "Kaleb Johnson", "Diff", "low", 1, -37.3, week=2, tied=True)]
    ev = [
        D.EventCrossing("player_week", "Kaleb Johnson 2026 week 2", "Diff", "low", 1, -37.3,
                        joined=True, others=("Kyle Pitts 2026 week 2",)),
        D.EventCrossing("player_week", "Tahj Brooks 2026 week 2", "Rostered bust streak", "high",
                        3, 17.0, joined=False, passed=("Deshaun Watson 2024 week 17",)),
        D.EventCrossing("player_week", "Kyler Murray 2026 week 1", "Change", "low", 5, -19.4,
                        passed=("Lamar Jackson 2021 week 14",)),
    ]
    out, rest = D.fold_week_boards(hl, ev, {}, [(2026, 2)])
    kj = [h for h in out if h.entity == "Kaleb Johnson"]
    ok = _ok("the record carries who it tied, without the week",
             kj and kj[0].others == ("Kyle Pitts",) and kj[0].detail().endswith("tied with Kyle Pitts"),
             kj and kj[0].detail())
    tb = [h for h in out if h.entity == "Tahj Brooks"]
    ok &= _ok("a running total's move becomes a single-week line",
              tb and "passing Deshaun Watson 2024 week 17" in tb[0].detail(), tb and tb[0].detail())
    # Old weeks keep their season and week — even last week of this season.
    hl2 = [D.WeeklyHighlight("teams", "LWebs53", "Number of WR rostered", "high", 1, 19.0, week=2)]
    ev2 = [D.EventCrossing("team_week", "LWebs53 2026 week 2", "Number of WR rostered", "high", 1,
                           19.0, passed=("LWebs53 2026 week 1",)),
           D.EventCrossing("league_week", "2026 week 2", "Players under 10 pts (roster)", "high", 1,
                           131.0, passed=("2024 week 2",))]
    out2, _r = D.fold_week_boards(hl2, ev2, {}, [(2026, 2)])
    lines = [h.line() for h in out2]
    ok &= _ok("a passed row from an earlier week keeps its year and week",
              any("passing LWebs53 2026 week 1" in x for x in lines)
              and any("passing 2024 week 2" in x for x in lines), lines)
    ok &= _ok("nothing of this week is left on the week board",
              [e.label for e in rest] == ["Kyler Murray 2026 week 1"], [e.label for e in rest])
    secs = dict((t, i) for t, _g, i in D.digest_sections(highlights=out, events=rest))
    ok &= _ok("and last week's move sits under earlier player weeks",
              "All-time leaderboard moves — earlier player weeks" in secs, list(secs))
    return ok


def check_opponent_stats_name_the_opponent():
    tw = pd.DataFrame({"Team": ["shmuel256", "LWebs53"], "Year": [2026, 2022], "Week": [2, 2],
                       "Opponent": ["LWebs53", "stevenb123"]})
    col = "Difference in pregame avg max PF from opponent"
    hl = [D.WeeklyHighlight("teams", "shmuel256", col, "high", 1, 75.0, week=2)]
    ev = [D.EventCrossing("team_week", "shmuel256 2026 week 2", col, "high", 1, 75.0,
                          passed=("LWebs53 2022 week 2",))]
    out, _rest = D.fold_week_boards(hl, ev, {"team_week": tw}, [(2026, 2)])
    line = out[0].line()
    ok = _ok("this week's row names its opponent", "(75 vs LWebs53)" in line, line)
    ok &= _ok("and so does the row it passed", "LWebs53 2022 week 2 (vs stevenb123)" in line, line)
    earlier = [D.EventCrossing("team_week", "LWebs53 2022 week 2", "Win streak vs this opponent",
                               "high", 1, 9.0, passed=("shmuel256 2026 week 2",))]
    D.name_opponents(earlier, {"team_week": tw})
    s = earlier[0].sentence()
    ok &= _ok("an earlier week's move names both opponents",
              s.startswith("LWebs53 2022 week 2 (vs stevenb123) passes shmuel256 2026 week 2 (vs LWebs53)"), s)
    ok &= _ok("without touching the label", earlier[0].label == "LWebs53 2022 week 2")
    return ok


def check_a_tie_reached_together_is_one_line():
    def board(vals):
        return {"players": {"X": [{"entity": e, "value": v} for e, v in vals]
                            + [{"entity": f"z{i}", "value": 0.0} for i in range(8)]}}
    # C (3rd) falls; D, E and F all climb to one new value: they share 3rd-5th,
    # and C, G and H lose those places.
    prev = board([("A", 50), ("B", 40), ("C", 30), ("G", 25), ("H", 24), ("D", 5), ("E", 6), ("F", 7)])
    curr = board([("A", 50), ("B", 40), ("C", 10), ("G", 25), ("H", 24), ("D", 35), ("E", 35), ("F", 35)])
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok = _ok("three who climbed together share the place, in one line",
             got == ["D, E and F share 3rd-highest X (35), passing C, G and H."], got)
    # D climbs into E and F's value (they held 4th-5th): D joins them.
    prev = board([("A", 50), ("B", 40), ("C", 30), ("E", 25), ("F", 25), ("G", 20), ("D", 5)])
    curr = board([("A", 50), ("B", 40), ("C", 10), ("E", 25), ("F", 25), ("G", 20), ("D", 25)])
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok &= _ok("one who climbs into a tie joins its holders by name",
              got == ["D joins E and F in a tie for 3rd-highest X (25), passing C."], got)
    # Two climb into F's value at 2nd.
    prev = board([("A", 50), ("F", 40), ("B", 30), ("C", 20), ("D", 5), ("E", 6)])
    curr = board([("A", 50), ("F", 40), ("B", 30), ("C", 20), ("D", 40), ("E", 40)])
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    ok &= _ok("two who climb into a tie together join it in one line",
              got == ["D and E join F in a tie for 2nd-highest X (40), passing B and C."], got)
    # A four-way tie for 3rd does not fit a top 5: nothing.
    prev = board([("A", 50), ("B", 40), ("C", 30), ("E", 25), ("F", 25), ("G", 25), ("D", 5)])
    curr = board([("A", 50), ("B", 40), ("C", 10), ("E", 25), ("F", 25), ("G", 25), ("D", 25)])
    got = [c.sentence() for c in D.diff_snapshots(prev, curr)]
    # C's fall past the tie is still news, told from C's side (2026-09-23).
    ok &= _ok("a four-way tie for 3rd is not reported",
              got == ["C was passed by E, F and G for 3rd-highest X (25), falling to 10."], got)
    # The same on an event board.
    def ev(rows):
        return [D.EventHighlight("trades", k, "KTC", "high", r, v, key=k) for k, r, v in rows]
    prior = D.event_board(ev([("A", 1, 50.), ("B", 2, 40.), ("C", 3, 30.), ("G", 4, 25.), ("H", 5, 24.)]))
    got = [c.sentence() for c in D.diff_events(
        prior, ev([("A", 1, 50.), ("B", 2, 40.), ("D", 3, 35.), ("E", 3, 35.), ("F", 3, 35.)]),
        prior_row_keys=["A", "B", "C", "D", "E", "F", "G", "H"])]
    ok &= _ok("an event board says it the same way",
              got == ["D, E and F share 3rd-highest KTC (35), passing C, G and H."], got)
    # And this week's rows on a week board: one single-week line.
    hl = [D.WeeklyHighlight("players", n, "Diff", "low", 1, -37.3, week=2, tied=True)
          for n in ("Kyle Pitts", "Kaleb Johnson")]
    evs = D.merge_simultaneous_ties([
        D.EventCrossing("player_week", "Kaleb Johnson 2026 week 2", "Diff", "low", 1, -37.3,
                        joined=True, others=("Kyle Pitts 2026 week 2",),
                        passed=("Cooper Kupp 2022 week 2",)),
        D.EventCrossing("player_week", "Kyle Pitts 2026 week 2", "Diff", "low", 1, -37.3,
                        joined=True, others=("Kaleb Johnson 2026 week 2",),
                        passed=("Cooper Kupp 2022 week 2",))])
    out, _rest = D.fold_week_boards(hl, evs, {}, [(2026, 2)])
    lines = [h.line() for h in out]
    ok &= _ok("two of this week's rows tied with each other are one single-week line",
              lines == ["Kaleb Johnson and Kyle Pitts: Diff (-37.3) — lowest ever (tie), "
                        "passing Cooper Kupp 2022 week 2."], lines)
    return ok


def test_digest_engine():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)


def test_redated_rows_carry_their_snapshot_across():
    """A build that re-dates existing rows (trades dated by completion, a
    synthesized arrival dated from the rosters) must not make them read as NEW
    transactions, nor let a row pass itself on a board under its new date."""
    import pandas as pd
    from lotg_support import digest as D
    cols = ["Team", "Team's traded with 1", "Assets received", "Assets sent", "Date", "Season"]
    old = {"trades": pd.DataFrame([["A", "B", "X", "Y", "2023-03-09 10:00:00", 2023],
                                   ["A", "C", "Z", "W", "2023-05-01 10:00:00", 2023]], columns=cols)}
    new = {"trades": pd.DataFrame([["A", "B", "X", "Y", "2023-03-14 02:10:27", 2023],   # re-dated
                                   ["A", "C", "Z", "W", "2023-05-01 10:00:00", 2023],   # untouched
                                   ["A", "B", "X", "Y", "2024-01-01 12:00:00", 2024]],  # genuinely new
                                  columns=cols)}
    km = D.redate_key_map(old, new)
    k_old = D._board_row_key("trades", old["trades"].iloc[0])
    k_new = D._board_row_key("trades", new["trades"].iloc[0])
    assert km == {k_old: k_new}, km
    snap = {"row_keys": [k_old, D._board_row_key("trades", old["trades"].iloc[1])],
            "event_board": [{"sheet": "trades", "key": k_old, "label": "old label"}]}
    snap = D.apply_key_map(snap, km, new)
    assert k_new in snap["row_keys"] and k_old not in snap["row_keys"]
    assert snap["event_board"][0]["key"] == k_new
    assert snap["event_board"][0]["label"] == D._board_label("trades", new["trades"].iloc[0])
    assert D._board_row_key("trades", new["trades"].iloc[2]) not in snap["row_keys"]   # still new


def test_a_faller_on_an_event_board_was_passed_by_the_row_that_stood_still():
    """Week 2 of 2026: the open Jalen Hurts pickup's Difference of averages fell
    21.069 -> 21.017 below the closed Jeff Wilson move's frozen 21.067. Wilson
    did not pass anyone — Hurts fell — so the line is Hurts's: "was passed by"."""
    from lotg_support import digest as D
    col = "Difference of averages"
    board = [{"sheet": "add_drops", "key": "k_h", "label": "Hurts move", "column": col,
              "end": "high", "rank": 1, "value": 21.069},
             {"sheet": "add_drops", "key": "k_w", "label": "Wilson move", "column": col,
              "end": "high", "rank": 2, "value": 21.067}]
    events = [D.EventHighlight("add_drops", "Wilson move", col, "high", 1, 21.067, "k_w"),
              D.EventHighlight("add_drops", "Hurts move", col, "high", 2, 21.017, "k_h")]
    got = [c.sentence() for c in D.diff_events(board, events, prior_row_keys=["k_h", "k_w"])]
    assert not any(s.startswith("Wilson move passes") for s in got), got
    assert any(s.startswith("Hurts move was passed by Wilson move for highest")
               and s.endswith("falling to 21.0.") for s in got), got
    # A row that ROSE past the faller keeps the active line; nobody is told twice.
    events2 = [D.EventHighlight("add_drops", "Wilson move", col, "high", 1, 21.5, "k_w"),
               D.EventHighlight("add_drops", "Hurts move", col, "high", 2, 21.017, "k_h")]
    got = [c.sentence() for c in D.diff_events(board, events2, prior_row_keys=["k_h", "k_w"])]
    assert any(s.startswith("Wilson move passes Hurts move") for s in got), got
    assert not any("was passed by" in s for s in got), got
