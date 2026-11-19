"""Weekly player awards (src/lotg.py player_week_award_flags), user rules 2026-11-18.

- Benchwarmer of the week = highest-scoring BENCH player league-wide; Dud of the
  week = lowest-scoring starter; Roster dud of the week = lowest scorer of
  every rostered player (starters + bench).
- Injured / suspended players can't win any of them; a bye week is still eligible.
- Every tied player wins, except a tie at 0 (2+ on 0): nobody. One player alone
  on 0 still wins.
- Projection Over/Underachiever (lotg_support.projections) follow the same tie rule.

Run: python tests/test_weekly_awards.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "lib")]

import lotg  # noqa: E402


def _pw(rows):
    cols = ["Player", "Team", "Year", "Week", "Starter/Bench", "Position", "Points",
            "Injury?", "Suspension?", "Bye?", "% of points (if starter)"]
    out = []
    for r in rows:
        d = dict(zip(cols, r + (None,) * (len(cols) - len(r))))
        for c in ("Injury?", "Suspension?", "Bye?"):
            d[c] = bool(d[c])
        out.append(d)
    return pd.DataFrame(out)


def _winners(pw, col):
    f = lotg.player_week_award_flags(pw)
    return sorted(pw.loc[f[col] == 1, "Player"])


def test_benchwarmer_is_the_top_bench_scorer_not_a_starter():
    pw = _pw([
        ("S1", "A", 2025, 1, "Starter", "WR", 0.0),
        ("S2", "A", 2025, 1, "Starter", "RB", 20.0),
        ("B1", "A", 2025, 1, "Bench", "RB", 30.0),
        ("B2", "B", 2025, 1, "Bench", "QB", 5.0),
    ])
    assert _winners(pw, "Benchwarmer of the week?") == ["B1"]
    assert _winners(pw, "Dud of the week?") == ["S1"]          # one player alone on 0 still wins
    assert _winners(pw, "Roster dud of the week?") == ["S1"]      # starters count too


def test_roster_dud_spans_starters_and_bench():
    pw = _pw([
        ("S1", "A", 2025, 1, "Starter", "QB", -2.0),
        ("B1", "A", 2025, 1, "Bench", "QB", -1.0),
        ("S2", "B", 2025, 1, "Starter", "WR", 4.0),
        ("Hurt", "B", 2025, 1, "Bench", "WR", -3.0, True),        # can't score < 0 when out; exempt anyway
    ])
    assert _winners(pw, "Roster dud of the week?") == ["S1"]
    assert _winners(pw, "Dud of the week?") == ["S1"]


def test_ties_all_win_except_at_zero():
    pw = _pw([
        ("S1", "A", 2025, 1, "Starter", "WR", 25.0),
        ("S2", "B", 2025, 1, "Starter", "WR", 25.0),
        ("S3", "A", 2025, 1, "Starter", "RB", 0.0),
        ("S4", "B", 2025, 1, "Starter", "RB", 0.0),
        ("B1", "A", 2025, 1, "Bench", "TE", 0.0),
        ("B2", "B", 2025, 1, "Bench", "TE", 0.0),
    ])
    assert _winners(pw, "Player of the week?") == ["S1", "S2"]
    assert _winners(pw, "WR of the week?") == ["S1", "S2"]
    assert _winners(pw, "Dud of the week?") == []              # 2 starters tied on 0
    assert _winners(pw, "RB of the week?") == []               # tied at 0 on a max award too
    assert _winners(pw, "Benchwarmer of the week?") == []
    assert _winners(pw, "Roster dud of the week?") == []
    # per team: A's lowest is S3 alone on 0 -> wins
    assert _winners(pw, "Lowest starter on team?") == ["S3", "S4"]


def test_float_noise_is_still_a_tie():
    pw = _pw([
        ("S1", "A", 2025, 1, "Starter", "WR", 0.1 + 0.2),
        ("S2", "B", 2025, 1, "Starter", "WR", 0.3),
    ])
    assert _winners(pw, "Dud of the week?") == ["S1", "S2"]


def test_injured_and_suspended_are_exempt_but_bye_is_not():
    pw = _pw([
        ("Hurt", "A", 2025, 1, "Starter", "WR", 0.0, True),
        ("Susp", "A", 2025, 1, "Starter", "RB", 0.0, False, True),
        ("Bye", "B", 2025, 1, "Starter", "TE", 0.0, False, False, True),
        ("Ok", "B", 2025, 1, "Starter", "QB", 3.0),
        ("A2", "A", 2025, 1, "Starter", "QB", 9.0),
    ])
    assert _winners(pw, "Dud of the week?") == ["Bye"]
    assert _winners(pw, "Lowest starter on team?") == ["A2", "Bye"]
    assert _winners(pw, "Highest starter on team?") == ["A2", "Ok"]


def test_bench_by_position_and_weeks_are_separate():
    pw = _pw([
        ("B1", "A", 2025, 1, "Bench", "QB", 14.0),
        ("B2", "B", 2025, 1, "Bench", "QB", 12.0),
        ("B3", "B", 2025, 2, "Bench", "QB", -1.5),
        ("B4", "A", 2025, 2, "Bench", "WR", 2.0),
    ])
    assert _winners(pw, "Bench QB of the week?") == ["B1", "B3"]
    assert _winners(pw, "Benchwarmer of the week?") == ["B1", "B4"]
    assert _winners(pw, "Roster dud of the week?") == ["B2", "B3"]


def test_captain_ties_and_injury():
    pw = _pw([
        ("C1", "A", 2025, 1, "Starter", "WR", 30.0, False, False, False, 0.25),
        ("C2", "B", 2025, 1, "Starter", "WR", 40.0, False, False, False, 0.25),
        ("C3", "B", 2025, 1, "Starter", "RB", 1.0, False, False, False, 0.01),
    ])
    assert _winners(pw, "Captain?") == ["C1", "C2"]


def test_projection_awards_share_the_tie_rule():
    from lotg_support import projections as P
    x = P.NAMES[0]
    pw = pd.DataFrame({
        "Player": ["a", "b", "c", "d"], "Year": 2025, "Week": 1, "Starter/Bench": "Starter",
        "Points": [10.0, 10.0, 5.0, 5.0], P.proj_col(x): [5.0, 5.0, 5.0, 5.0]})
    for y in P.NAMES[1:]:
        pw[P.proj_col(y)] = float("nan")
    res = P.player_week_awards(pw, pd.Series(False, index=pw.index))
    assert list(res[P.over_col(x)]) == [1, 1, 0, 0]       # +5 tie: both win
    assert list(res[P.under_col(x)]) == [0, 0, 0, 0]      # tie at 0: nobody


def test_digest_snapshot_moves_old_benchwarmer_boards_to_dud():
    import copy
    from lotg_support import digest as D
    old = {"meta": {}, "players": {"Times as Benchwarmer of the week?": {"x": 1}, "Points": {"y": 2}},
           "event_board": [
               {"sheet": "player_year", "column": "Times as Benchwarmer of the week?", "end": "high", "rank": 1},
               {"sheet": "player_week", "column": "Benchwarmer of the week streak", "end": "high", "rank": 1},
               {"sheet": "team_week", "column": "PF", "end": "high", "rank": 1}]}
    m = D.migrate_snapshot_award_split(copy.deepcopy(old))
    assert [e["column"] for e in m["event_board"]] == [
        "Times as Dud of the week?", "Dud of the week streak", "PF"]
    assert set(m["players"]) == {"Times as Dud of the week?", "Points"}
    assert D.migrate_snapshot_award_split(copy.deepcopy(m)) == m       # stamped: once only
    # a snapshot written after the split keeps its (new-meaning) Benchwarmer boards
    new = {"meta": {"benchwarmer_split": "2026-11-18"},
           "event_board": [{"sheet": "player_year", "column": "Times as Benchwarmer of the week?"}]}
    assert D.migrate_snapshot_award_split(copy.deepcopy(new)) == new


def test_exports_match_the_rules():
    """Once a build with these columns has run, the committed flags equal a
    recompute from the same sheet (completed seasons only)."""
    path = _ROOT / "exports" / "player_week.csv"
    if not path.exists():
        print("skip: no exports")
        return
    pw = pd.read_csv(path, low_memory=False)
    if "Dud of the week?" not in pw.columns:
        print("skip: exports predate the 2026-11-18 award rules")
        return
    f = lotg.player_week_award_flags(pw)
    done = pd.to_numeric(pw["Year"], errors="coerce") < 2026
    for c in lotg.PLAYER_WEEK_AWARDS:
        have = pd.to_numeric(pw[c], errors="coerce").fillna(0).astype(int)
        bad = done & (have != f[c])
        assert not bad.any(), f"{c}: {int(bad.sum())} rows differ"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
