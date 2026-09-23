"""Two trailing averages that were thin early in a season (2026 week 2's digest).

* team_week "Difference in pregame avg max PF from opponent" averaged Max PF over
  the season's earlier weeks, so week 2 compared ONE game each: shmuel256's +75
  went straight to the top of the all-time board. It is now blank before week
  `_PREGAME_MIN_WEEK` (4), and the UPST flag built on it is N/A there too.
* player_week "Difference in averages of best/worst startables over previous 5
  games" reset its window every season, so week 2 averaged one game: Kaleb
  Johnson, Kyle Pitts, Jaylen Waddle, Ja'Kobi Lane and Jake Ferguson filled the
  all-time bottom 5 in one week. The window is now the player's last 5
  regular-season NFL games (nflverse, rostered or not), across seasons; a
  rookie averages what he has, anyone else short of five is N/A.

Run: PYTHONPATH=src:lib python tests/test_early_season_windows.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("lotg", _ROOT / "src" / "lotg.py")
lotg = importlib.util.module_from_spec(_spec)
sys.modules["lotg"] = lotg          # dataclasses resolve types via sys.modules
_spec.loader.exec_module(lotg)

_EXPORTS = _ROOT / "exports"
_STARTABLES = "Difference in averages of best/worst startables over previous 5 games"
_PREGAME = "Difference in pregame avg max PF from opponent"


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_pregame_average_waits_for_week_4():
    tw = pd.DataFrame({
        "Team": ["A"] * 5 + ["B"] * 2,
        "Year": [2026] * 5 + [2025, 2026],
        "Week": [1, 2, 3, 4, 5, 17, 1],
        "Max PF": [100.0, 200.0, 150.0, 170.0, 90.0, 999.0, 120.0],
    }).sort_values(["Team", "Year", "Week"]).reset_index(drop=True)
    avg = lotg._pregame_avg_max_pf(tw)
    a = avg[tw["Team"] == "A"].tolist()
    ok = _ok("weeks 1-3 are blank", all(pd.isna(v) for v in a[:3]), a)
    ok &= _ok("week 4 averages weeks 1-3", a[3] == 150.0, a)
    ok &= _ok("week 5 averages weeks 1-4", a[4] == 155.0, a)
    b = avg[tw["Team"] == "B"].tolist()
    ok &= _ok("last season's weeks never feed this season's average", pd.isna(b[1]), b)
    return ok


def check_upst_is_na_early_and_renders_whole():
    tw = pd.DataFrame({"Team": ["A"] * 4, "Year": [2026] * 4, "Week": [1, 3, 4, 5],
                       "UPST": [float("nan"), float("nan"), 1.0, 0.0]})
    shown = lotg._fill_missing_values(tw.copy(), ["UPST"])["UPST"].tolist()
    ok = _ok("UPST reads N/A in weeks 1-3 and whole numbers after", shown == ["N/A", "N/A", 1, 0],
             shown)
    ok &= _ok("a league row of only N/A weeks is N/A",
              lotg._upst_total(pd.Series([float("nan")] * 3)) is None)
    ok &= _ok("otherwise the sum of the weeks that have one",
              lotg._upst_total(pd.Series([float("nan"), 1.0, 0.0, 1.0])) == 2)
    return ok


def check_startables_window_is_the_nfl_game_log():
    games = {
        # A veteran: 2025 weeks 13-17 (one of them a 0-point snap appearance),
        # then 2026 week 1. Weeks he sat on waivers count; so do unrostered ones.
        "v": {(2025, 13): 13.0, (2025, 14): 14.0, (2025, 15): 0.0, (2025, 16): 16.0,
              (2025, 17): 17.0, (2026, 1): 50.0},
        "r": {(2026, 1): 1.0, (2026, 2): 2.0, (2026, 3): 3.0},      # a rookie
        "s": {(2025, 17): 8.0, (2026, 1): 4.0},                       # a second-year player
    }
    pw = pd.DataFrame({
        "Player": ["Vet", "Vet", "Rook", "Rook", "Rook", "Soph"],
        "Player ID": ["v", "v", "r", "r", "r", "s"],
        "Year": [2026] * 6, "Week": [1, 2, 1, 2, 4, 2],
    })
    rookie = pd.Series([False, False, True, True, True, False], index=pw.index)
    avg = lotg._previous_nfl_avgs(pw, games, rookie_mask=rookie)
    ok = _ok("week 1 reaches back into last season (a 0-point game counts)",
             avg[("v", 2026, 1)] == 12.0, avg[("v", 2026, 1)])
    ok &= _ok("week 2 rolls week 1 in and 2025 week 13 out", avg[("v", 2026, 2)] == 19.4,
              avg[("v", 2026, 2)])
    ok &= _ok("a rookie has no average before his first game", avg[("r", 2026, 1)] is None)
    ok &= _ok("then averages what he has (week 2: one game)", avg[("r", 2026, 2)] == 1.0,
              avg[("r", 2026, 2)])
    ok &= _ok("(week 4: three games)", avg[("r", 2026, 4)] == 2.0, avg[("r", 2026, 4)])
    ok &= _ok("a non-rookie short of five has none", avg[("s", 2026, 2)] is None,
              avg[("s", 2026, 2)])
    ok &= _ok("an unknown player has none",
              lotg._previous_nfl_avgs(pw.assign(**{"Player ID": "x"}), games)[("x", 2026, 1)] is None)
    twins = pd.DataFrame({"Player": ["Mike Williams", "Mike Williams"], "Player ID": ["v", "s"],
                          "Year": [2026, 2026], "Week": [2, 2]})
    t = lotg._previous_nfl_avgs(twins, games)
    ok &= _ok("two players sharing a name keep their own averages (keyed by id)",
              t[("v", 2026, 2)] == 19.4 and t[("s", 2026, 2)] is None, t)
    return ok


def _completed(df):
    years = pd.to_numeric(df["Year"], errors="coerce")
    return df[years < years.max()]


def check_exports_hold_both_windows():
    tw_p, pw_p = _EXPORTS / "team_week.csv", _EXPORTS / "player_week.csv"
    if not (tw_p.exists() and pw_p.exists()):
        print("  [SKIP] exports/ absent")
        return True
    tw = _completed(pd.read_csv(tw_p, low_memory=False))
    early = pd.to_numeric(tw["Week"], errors="coerce") < lotg._PREGAME_MIN_WEEK
    filled = pd.to_numeric(tw.loc[early, _PREGAME], errors="coerce").notna()
    ok = _ok("no completed season has a pregame difference before week 4", not filled.any(),
             f"{int(filled.sum())} rows")
    upst = pd.to_numeric(tw.loc[early, "UPST"], errors="coerce")
    ok &= _ok("nor an upset call (N/A)", upst.isna().all(), f"{int(upst.notna().sum())} rows")
    ok &= _ok("week 4 on still has them",
              pd.to_numeric(tw.loc[~early, _PREGAME], errors="coerce").notna().any())

    pw = _completed(pd.read_csv(pw_p, low_memory=False))
    val = pd.to_numeric(pw[_STARTABLES], errors="coerce")
    no_ref = pw["Reference player name"].isna() | (pw["Reference player name"].astype(str).str.strip() == "")
    ok &= _ok("a row with no reference player has no startables value (N/A, not a filled 0)",
              not (no_ref & val.notna()).any(), f"{int((no_ref & val.notna()).sum())} rows")
    return ok


def check_no_two_players_share_a_name_in_a_week():
    """The window is keyed by id, so a shared name cannot mix two averages any
    more; but the workbook links 'Reference player name' to a row by name. Red
    here means two different players share a name in one week — fix the link
    (key it by id) rather than this guard."""
    pw_p = _EXPORTS / "player_week.csv"
    if not pw_p.exists():
        print("  [SKIP] exports/ absent")
        return True
    pw = pd.read_csv(pw_p, dtype=str, keep_default_na=False, usecols=["Player", "Year", "Week"])
    dup = pw[pw.duplicated(["Player", "Year", "Week"], keep=False)]
    return _ok("no two player_week rows share a name in one week", dup.empty,
               dup.head(6).values.tolist())


def run_all():
    tests = [
        check_pregame_average_waits_for_week_4,
        check_startables_window_is_the_nfl_game_log,
        check_upst_is_na_early_and_renders_whole,
        check_exports_hold_both_windows,
        check_no_two_players_share_a_name_in_a_week,
    ]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_early_season_windows():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
