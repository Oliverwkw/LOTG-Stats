"""Filtered stats (`lotg_support.filtered_stats`): digest-only columns that are an
exported column with a row filter — "PF in a loss", "PF in a win", and the same
pair for Max PF and Efficiency.

Checks that they are added to the digest's frames like any other column, ranked
at their one end only on the all-time boards, the single-week highlights and
the drop-off lookup, and that the base column's own boards are untouched. On
synthetic frames; no exports needed.

Run: PYTHONPATH=src:lib python tests/test_filtered_stats.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import digest as D  # noqa: E402
from lotg_support import filtered_stats as F  # noqa: E402


def _team_week():
    """Two seasons of four teams; week 1 of 2026 holds the loss record (190) and
    the win low (80). 2025's games are 150/120 + 140/100 each week."""
    rows = []
    for wk in range(1, 5):
        for team, pf, won in (("A", 150 + wk, True), ("B", 120 + wk, False),
                              ("C", 140 + wk, True), ("D", 100 + wk, False)):
            rows.append({"Team": team, "Year": 2025, "Week": wk, "Win?": won, "PF": float(pf),
                         "Max PF": float(pf) + 20, "Efficiency": pf / (pf + 20.0)})
    for team, pf, won in (("A", 200.0, True), ("B", 190.0, False),
                          ("C", 80.0, True), ("D", 75.0, False)):
        rows.append({"Team": team, "Year": 2026, "Week": 1, "Win?": won, "PF": pf,
                     "Max PF": pf + 20, "Efficiency": pf / (pf + 20.0)})
    return pd.DataFrame(rows)


def _frames():
    frames = {"team_week": _team_week()}
    F.add_filtered_stats(frames)
    return frames


def test_added_as_filtered_copies_of_the_base_column():
    tw = _frames()["team_week"]
    loss, win = tw["Win?"] == False, tw["Win?"] == True  # noqa: E712
    assert (tw.loc[loss, "PF in a loss"] == tw.loc[loss, "PF"]).all()
    assert tw.loc[win, "PF in a loss"].isna().all()
    assert (tw.loc[win, "PF in a win"] == tw.loc[win, "PF"]).all()
    assert tw.loc[loss, "PF in a win"].isna().all()
    # Neither a tie nor an unplayed week's blank counts as a win or a loss.
    odd = pd.DataFrame({"Team": ["A", "B"], "Win?": [None, "Tie"], "PF": [99.0, 98.0]})
    f = {"team_week": odd}
    F.add_filtered_stats(f)
    assert f["team_week"][["PF in a loss", "PF in a win"]].isna().all().all()


def test_missing_sheet_or_base_is_skipped():
    assert F.add_filtered_stats({}) == []
    assert F.add_filtered_stats({"team_week": pd.DataFrame({"Team": ["A"]})}) == []


def test_boards_rank_one_end_only():
    ev = D.board_highlights(_frames()["team_week"], "team_week")
    ends = {(e.column, e.end) for e in ev}
    assert ("PF in a loss", "high") in ends and ("PF in a loss", "low") not in ends
    assert ("PF in a win", "low") in ends and ("PF in a win", "high") not in ends
    # The base column keeps both of its ends.
    assert ("PF", "high") in ends and ("PF", "low") in ends
    top = [e for e in ev if e.column == "PF in a loss" and e.rank == 1]
    assert [(e.label, e.value) for e in top] == [("B 2026 week 1", 190.0)], top
    low = [e for e in ev if e.column == "PF in a win" and e.rank == 1]
    assert [(e.label, e.value) for e in low] == [("C 2026 week 1", 80.0)], low


def test_single_week_highlights_rank_one_end_only():
    fr = _frames()
    hs = D._highlights_for_frame("teams", fr["team_week"], "Team", 2026, 1, D.WINDOW,
                                 sheet="team_week")
    got = {(h.entity, h.column, h.end, h.rank) for h in hs if h.column.startswith("PF in")}
    assert got == {("B", "PF in a loss", "high", 1), ("C", "PF in a win", "low", 1)}, got
    # D's 75 is the lowest PF in a loss — but that end is not ranked.
    assert not any(h.column == "PF in a loss" and h.end == "low" for h in hs)
    assert any(h.entity == "D" and h.column == "PF" and h.end == "low" for h in hs)


def test_dropoff_lookup_has_no_board_at_the_unranked_end():
    fr = _frames()
    look = D.board_value_lookup(fr)
    key = D._board_row_key("team_week", fr["team_week"].iloc[-2])   # C 2026 week 1
    assert look("team_week", "PF in a win", "low", key) == 80.0
    assert look("team_week", "PF in a win", "high", key) is None
    keyb = D._board_row_key("team_week", fr["team_week"].iloc[-3])  # B 2026 week 1
    assert look("team_week", "PF in a loss", "high", keyb) == 190.0
    assert look("team_week", "PF in a loss", "low", keyb) is None


def test_every_pair_ranks_its_own_end():
    ev = D.board_highlights(_frames()["team_week"], "team_week")
    ends = {(e.column, e.end) for e in ev}
    for base in ("PF", "Max PF", "Efficiency"):
        assert (f"{base} in a loss", "high") in ends and (f"{base} in a loss", "low") not in ends
        assert (f"{base} in a win", "low") in ends and (f"{base} in a win", "high") not in ends
    top = {e.column: e.label for e in ev if e.rank == 1 and " in a " in e.column}
    assert top == {c: ("B 2026 week 1" if "loss" in c else "C 2026 week 1")
                   for c in top} and len(top) == 6, top


def test_printed_like_the_column_they_filter():
    D.note_percent_columns(_frames())
    # Efficiency is a 0-1 fraction the workbook shows as a percent.
    assert D._fmt_stat("Efficiency", 0.9876) == "98.76%"
    assert D._fmt_stat("Efficiency in a loss", 0.9876) == "98.76%"
    assert D._fmt_stat("Efficiency in a win", 0.47) == "47.00%"
    assert D._fmt_stat("PF in a loss", 195.56) == D._fmt_stat("PF", 195.56) == "195.56"
    assert D._fmt_stat("Max PF in a win", 115.2) == "115.20"


def test_percent_only_where_the_workbook_shows_one():
    # A " rate" the workbook shows as a plain 0.23 is not printed as "22.99%".
    frames = {"team_year": pd.DataFrame({"Team": ["A", "B", "C"],
                                         "3-year roster retention rate": [0.2299, 0.5, 0.1],
                                         "Win %": [0.5, 0.25, 0.75]})}
    got = D.note_percent_columns(frames)
    assert "3-year roster retention rate" not in got and "Win %" in got, got
    assert D._fmt_stat("3-year roster retention rate", 0.2299) == "0.23"
    assert D._fmt_stat("Win %", 0.5) == "50.00%"


def test_on_pace_projects_one_end_only():
    """player_year "Avg points by a rookie" is ranked high only, so a rookie on
    pace for one of the LOWEST is not reported (the base column's board is)."""
    rows = [{"Player": f"P{y}{i}", "Year": y, "Rookie?": True, "Avg points": float(5 + i)}
            for y in (2023, 2024, 2025) for i in range(5)]
    rows += [{"Player": "Low", "Year": 2026, "Rookie?": True, "Avg points": 0.5},
             {"Player": "High", "Year": 2026, "Rookie?": True, "Avg points": 40.0}]
    py = pd.DataFrame(rows)
    frames = {"player_year": py}
    F.add_filtered_stats(frames)
    got = {(p.entity, p.column, p.end) for p in
           D._project_frame("players", frames["player_year"], "Player",
                            D._pace.PaceContext(season=2026, played=5, horizon=10), 5)}
    assert ("High", "Avg points by a rookie", "high") in got, got
    assert ("Low", "Avg points by a rookie", "low") not in got, got
    assert ("Low", "Avg points", "low") in got, got


def _player_week():
    """Two teams' rosters for 2026 week 1 of `_team_week` (B lost, C won)."""
    return pd.DataFrame([
        {"Player": "QB1", "Team": "B", "Year": 2026, "Week": 1, "Starter/Bench": "Starter",
         "Position": "QB", "Rookie?": False, "Points": 40.0},
        {"Player": "RB1", "Team": "B", "Year": 2026, "Week": 1, "Starter/Bench": "Bench",
         "Position": "RB", "Rookie?": True, "Points": 30.0},
        {"Player": "WR1", "Team": "C", "Year": 2026, "Week": 1, "Starter/Bench": "Starter",
         "Position": "WR", "Rookie?": True, "Points": 35.0},
        {"Player": "TE1", "Team": "C", "Year": 2026, "Week": 1, "Starter/Bench": "Bench",
         "Position": "TE", "Rookie?": False, "Points": 20.0},
    ])


def test_player_week_stats_by_role_position_and_result():
    for with_column in (False, True):          # team_week lookup, then player_week's Win?
        pw = _player_week()
        if with_column:
            pw["Win?"] = [False, False, True, True]
        frames = {"team_week": _team_week(), "player_week": pw}
        F.add_filtered_stats(frames)
        pw = frames["player_week"].set_index("Player")

        def has(col):
            return sorted(pw.index[pw[col].notna()])
        assert has("Points as starter") == ["QB1", "WR1"]
        assert has("Points on bench") == ["RB1", "TE1"]
        assert has("QB points") == ["QB1"] and has("QB points on bench") == []
        assert has("RB points on bench") == ["RB1"] and has("WR points as starter") == ["WR1"]
        assert has("Points by a rookie starter") == ["WR1"]
        assert has("Points by a starter in a loss") == ["QB1"], with_column
        assert has("Points on bench in a loss") == ["RB1"], with_column
    # Every player_week stat is ranked at its high end only.
    assert all(f.end == "high" for f in F.FILTERED_STATS if f.sheet == "player_week")


def test_player_week_win_matches_team_week():
    """The exported player_week `Win?` is its team's team_week result (build data)."""
    pw_p, tw_p = _ROOT / "exports" / "player_week.csv", _ROOT / "exports" / "team_week.csv"
    pw = pd.read_csv(pw_p, low_memory=False) if pw_p.exists() else None
    if pw is None or "Win?" not in pw.columns:
        try:
            import pytest
            pytest.skip("exports/ has no player_week Win? yet (built before the column)")
        except ImportError:
            print("  SKIP — exports/ has no player_week Win? yet")
            return
    tw = pd.read_csv(tw_p, low_memory=False)
    keys = ["Team", "Year", "Week"]
    m = pw[keys + ["Win?"]].merge(tw[keys + ["Win?"]], on=keys, how="left",
                                  suffixes=("", "_team"))
    done = pd.to_numeric(m["Year"], errors="coerce") < pd.to_numeric(m["Year"], errors="coerce").max()
    assert len(m) == len(pw)
    bad = m[done & (m["Win?"].astype(str) != m["Win?_team"].astype(str))]
    assert bad.empty, bad.head()


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  [FAIL] {name} — {exc}")
            except BaseException as exc:      # pytest.skip outside pytest
                if type(exc).__name__ != "Skipped":
                    raise
                print(f"  [SKIP] {name} — {exc}")
    sys.exit(1 if fails else 0)
