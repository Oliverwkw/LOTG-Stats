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
    ok = _ok("no yearly items before week 3", early == [], f"got {len(early)}")

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
              sorted(D.rankable_series(tw, "Margin", True).tolist()) == [2, 5, 10, 30, 50])
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
              not any(D.is_weekly_counting_stat(c) for c in ["Number of donuts", "Points", "Total trades"]))
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
              bool(out) and "joins a tie with pick 4.06 for lowest KTC" in out[0].sentence(),
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
    ok &= _ok("phrased 'joins a tie with'", bool(out) and "joins a tie with Q for 2nd-highest PF" in out[0].sentence(),
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
        check_mirrored_columns,
        check_replica_minimal,
        check_league_window,
        check_league_milestones,
        check_pace_diff_reports_only_changes,
        check_rate_and_weekly_classification,
        check_phrasing_catalog,
        check_render_html_smoke,
        check_digest_title,
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
