"""Unit tests for _blank_pre_season_year_stats.

A season with no played weeks still emits year-grain rows (offseason roster /
trade / draft activity), but every game-derived cell on them is 0 — or derived
from a 0 — only because no games have happened. Those must render N/A, while the
genuine offseason facts stay. Detection keys off the set of seasons that
produced a played (week-grain) row, so it self-corrects every year with no
per-season hardcoding.

Run: python tests/test_pre_season_blanking.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

from lotg import _blank_pre_season_year_stats  # noqa: E402


def _team_year_frame() -> pd.DataFrame:
    # 2024 = completed (real values, incl. a genuine 0), 2026 = not started.
    return pd.DataFrame(
        [
            {"Team": "AceMatthew", "Year": 2024, "Player average age": 26.5,
             "Points": 1800.0, "Number of QB started": 2, "Number of donuts": 0,
             "Trading skill": 55.0, "Number of transactions": 30,
             "Offseason trades": 1.0, "Draft Value": 4.2},
            {"Team": "AceMatthew", "Year": 2026, "Player average age": 0.0,
             "Points": float("nan"), "Number of QB started": 0, "Number of donuts": 0,
             "Trading skill": 44.1, "Number of transactions": 4,
             "Offseason trades": 2.0, "Draft Value": 1.22},
        ]
    )


def test_blanks_not_started_game_stats():
    df = _blank_pre_season_year_stats(_team_year_frame(), "team-year", {2024})
    row26 = df[df["Year"] == 2026].iloc[0]
    # Game-derived stats on the not-started season -> N/A (the reported example
    # is "Player average age", but the whole game-stat family is affected).
    assert row26["Player average age"] == "N/A"
    assert row26["Number of QB started"] == "N/A"
    assert row26["Number of donuts"] == "N/A"
    assert row26["Points"] == "N/A"
    # Genuine offseason facts survive.
    assert row26["Trading skill"] == 44.1
    assert row26["Number of transactions"] == 4
    assert row26["Offseason trades"] == 2.0
    assert row26["Draft Value"] == 1.22
    assert row26["Team"] == "AceMatthew"


def test_completed_season_untouched():
    # A completed season keeps everything, INCLUDING a real 0 ("Number of
    # donuts") which must NOT be turned into N/A.
    df = _blank_pre_season_year_stats(_team_year_frame(), "team-year", {2024})
    row24 = df[df["Year"] == 2024].iloc[0]
    assert row24["Player average age"] == 26.5
    assert row24["Number of donuts"] == 0
    assert row24["Points"] == 1800.0
    assert row24["Number of QB started"] == 2


def test_player_year_keep_set():
    df = pd.DataFrame(
        [
            {"Player": "Audric Estime", "Year": 2026, "Age": 23.15,
             "Points (full season)": 0.0, "Times as Player of the week?": 0,
             "Change in points from previous season": -48.1,
             "Number of transactions": 2, "Rookie?": False, "Top Team": "AceMatthew"},
        ]
    )
    out = _blank_pre_season_year_stats(df, "Player-year", {2024, 2025})
    r = out.iloc[0]
    assert r["Points (full season)"] == "N/A"
    assert r["Times as Player of the week?"] == "N/A"
    # A change derived off the phantom 0-point season is bogus -> N/A.
    assert r["Change in points from previous season"] == "N/A"
    # Offseason identity / activity survives.
    assert r["Age"] == 23.15
    assert r["Number of transactions"] == 2
    assert bool(r["Rookie?"]) is False
    assert r["Top Team"] == "AceMatthew"


def test_noop_when_season_started_or_unknown():
    # Season present in started set -> untouched.
    df = _blank_pre_season_year_stats(_team_year_frame(), "team-year", {2024, 2026})
    assert df[df["Year"] == 2026].iloc[0]["Player average age"] == 0.0
    # No started-season info -> leave everything alone (never guess).
    df2 = _blank_pre_season_year_stats(_team_year_frame(), "team-year", None)
    assert df2[df2["Year"] == 2026].iloc[0]["Player average age"] == 0.0
    # Sheets without a pre-season keep set are ignored entirely.
    df3 = _blank_pre_season_year_stats(_team_year_frame(), "team-all-time", {2024})
    assert df3[df3["Year"] == 2026].iloc[0]["Player average age"] == 0.0


if __name__ == "__main__":
    test_blanks_not_started_game_stats()
    test_completed_season_untouched()
    test_player_year_keep_set()
    test_noop_when_season_started_or_unknown()
    print("ok")
