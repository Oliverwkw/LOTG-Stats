"""A live season has no outcome yet — its season-outcome cells render N/A.

Three columns used to read a season in progress as finished:

* team_year "Week of playoff elimination" — the games played so far were taken
  as the whole schedule, so with "0 remaining" every team outside the current
  top four came out eliminated in the latest week (2026 after week 3: four teams
  "eliminated in week 3" at 1-2), and the None of a non-eliminated team was
  zero-filled into the 0 that means "made the bracket".
* league_year "(smallest) Playoff tiebreaker" — a provisional seeding gap
  reported as the season's.
* player_year "Rostered by / Started by champion?", "Started in championship
  game?" — False for every player, i.e. "not on the champion's roster", for a
  season with no champion.

The build now writes N/A for an incomplete season (`_season_is_complete`) and
keeps it N/A through the export fill (`_preserve_na`, plus a boolean branch in
`_fill_missing_values` that used to turn every missing boolean into False).
Completed seasons are unchanged: the four bracket teams still read 0 —
written explicitly now rather than produced by the zero-fill.

Run: python tests/test_live_season_outcomes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

from lotg import _fill_missing_values, _preserve_na  # noqa: E402

_OUTCOME_COLUMNS = (
    "Week of playoff elimination",
    "(smallest) Playoff tiebreaker",
    "Rostered by champion?",
    "Started by champion?",
    "Started in championship game?",
)


def test_season_outcome_columns_keep_na():
    for col in _OUTCOME_COLUMNS:
        assert _preserve_na(col), col


def test_a_live_elimination_week_stays_na_and_a_bracket_zero_stays_zero():
    df = pd.DataFrame({"Week of playoff elimination": [0, 11, "N/A", None]})
    out = _fill_missing_values(df, list(df.columns))["Week of playoff elimination"].tolist()
    assert out[0] == 0 and out[1] == 11
    assert all(v == "N/A" or pd.isna(v) for v in out[2:]), out


def test_a_live_champion_flag_is_na_not_false():
    df = pd.DataFrame({"Rostered by champion?": [True, False, None]})
    out = _fill_missing_values(df, list(df.columns))["Rostered by champion?"].tolist()
    assert out[0] is True and out[1] is False
    assert out[2] is None or pd.isna(out[2]), out


def test_other_booleans_still_default_to_false():
    # the N/A branch is opt-in: an ordinary flag keeps its False default
    col = "Player of the week?"
    assert not _preserve_na(col)
    df = pd.DataFrame({col: [True, None]})
    assert _fill_missing_values(df, [col])[col].tolist() == [True, False]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("ok")
