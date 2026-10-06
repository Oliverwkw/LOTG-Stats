"""Guards for `lotg_support.struck_games` — the 2022 wk 17 Bills-Bengals game
(the Damar Hamlin no-contest) that nflverse struck and the league played.

User rule [2026-10-05]: a normal game with a short stat pool. These pin that
the schedule row, the weekly stat lines and the season totals all carry it,
that the stat lines re-score to the points Sleeper (and the league) gave, and
that the four players who dressed and recorded nothing are marked active.

Run: python tests/test_struck_games.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import struck_games as SG  # noqa: E402
from lotg_support.contracts import lotg_points  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_week.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def test_stat_lines_rescore_to_the_league_points():
    rows = SG.struck_stat_rows()
    assert len(rows) and set(rows["game_id"]) == SG.STRUCK_GAME_IDS
    pts = dict(zip(rows["player_display_name"], lotg_points(rows).round(2)))
    # what Sleeper scored, as in player_week for the rostered players
    want = {"Joe Burrow": 6.28, "Josh Allen": 2.72, "Stefon Diggs": 4.6, "Tyler Boyd": 8.4,
            "Tee Higgins": 2.3, "James Cook": 1.8, "Joe Mixon": 1.2, "Devin Singletary": 0.3,
            "Hayden Hurst": 4.5}
    assert {n: pts[n] for n in want} == want, pts


def test_rostered_players_match_player_week():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    pw = pd.read_csv(_ROOT / "exports" / "player_week.csv", low_memory=False)
    pw = pw[(pw["Year"] == 2022) & (pw["Week"] == 17) & pw["NFL team"].isin(["BUF", "CIN"])]
    rows = SG.struck_stat_rows()
    pts = dict(zip(rows["player_display_name"], lotg_points(rows).round(2)))
    for name, p in zip(pw["Player"], pw["Points"]):
        assert round(pts.get(name, 0.0), 2) == round(float(p), 2), (name, pts.get(name), p)


def test_added_once_and_only_where_missing():
    w = pd.DataFrame({"player_id": ["x"], "season": [2022], "week": [16], "game_id": ["2022_16_X_Y"],
                      "season_type": ["REG"], "receptions": [3.0]})
    once = SG.add_struck_stat_rows(w, 2022)
    assert len(once) == 1 + len(SG.struck_stat_rows())
    assert len(SG.add_struck_stat_rows(once, 2022)) == len(once)
    assert len(SG.add_struck_stat_rows(w, 2021)) == 1
    # a stat the game did not produce is 0, as nflverse writes it — never NaN
    added = once[once["game_id"].isin(SG.STRUCK_GAME_IDS)]
    assert added["receptions"].notna().all()


def test_season_totals_gain_the_game():
    rows = SG.struck_stat_rows()
    burrow = rows[rows["player_display_name"] == "Joe Burrow"].iloc[0]
    seas = pd.DataFrame({"player_id": [burrow["player_id"]] * 2, "season_type": ["REG", "REG+POST"],
                         "season": [2022, 2022], "passing_yards": [4423.0, 4423.0], "games": [16, 16]})
    out = SG.add_struck_season_totals(seas, 2022)
    b = out[out["player_id"] == burrow["player_id"]].set_index("season_type")
    assert b.loc["REG", "passing_yards"] == 4423 + 52 and b.loc["REG", "games"] == 17
    assert b.loc["REG+POST", "passing_yards"] == 4423 + 52
    hurst = out[out["player_id"] == rows[rows["player_display_name"] == "Hayden Hurst"].iloc[0]["player_id"]]
    assert set(hurst["season_type"]) == {"REG", "REG+POST"} and (hurst["games"] == 1).all()


def test_dressed_without_a_stat_are_active():
    with open(_ROOT / "data" / "game_day_status.csv", newline="") as fh:
        gds = {(r["player_name"], r["season"], r["week"]): r["status"] for r in csv.DictReader(fh)}
    for name in ("Ja'Marr Chase", "Dawson Knox", "Gabe Davis", "Samaje Perine"):
        assert gds.get((name, "2022", "17")) == "active", name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
