"""NFL team / Bye? follow a mid-season NFL trade the week it happens.

player_week's `NFL team` takes every source for THAT week (the stat line, the
snap counts, the weekly roster where its status is on-team) before any season
fallback. Before, a week with no stat line read the player's most common team
of the season, so a traded player's quiet weeks showed the other team — and its
bye (Mike Williams 2024 wk 12) or its kickoff.

Checks, on the committed exports (skip until a build carries the fix — the
build logs "nfl_team_week_first"):
* the cases that motivated it, keyed by Player ID;
* no bye-flagged week shows the player on the field (Snap % > 0);
* a CUT roster row never names the week's team (Cam Newton 2021 wk 1).

Run: python tests/test_nfl_team_week.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_EXPORTS = _ROOT / "exports"

# (Player ID, name for the message, year, week) -> expected NFL team
CASES = {
    ("4068", "Mike Williams", 2024, 11): "PIT",   # traded NYJ -> PIT, played without a stat line
    ("4068", "Mike Williams", 2024, 12): "PIT",   # ... on Thursday; NYJ was on bye
    ("7606", "Kadarius Toney", 2022, 3): "NYG",   # a Giant until the wk 8 trade; season mode said KC
    ("6955", "James Robinson", 2022, 12): "NYJ",  # traded JAX -> NYJ
    ("2133", "Davante Adams", 2024, 5): "LV",     # still a Raider (injured) before the wk 7 trade
    ("954", "Cam Newton", 2021, 1): "CAR",        # NE's wk 1 roster row is CUT: never "NE"
}


def _skip(reason: str) -> bool:
    print(f"  (skip: {reason})")
    return True


def _pw():
    p = _EXPORTS / "player_week.csv"
    log = _EXPORTS / "raw" / "build_debug.log"
    if not p.exists():
        _skip("no exports/")
        return None
    if not log.exists() or "nfl_team_week_first" not in log.read_text(errors="ignore"):
        _skip("exports predate the week-first NFL team order")
        return None
    pw = pd.read_csv(p, low_memory=False, dtype={"Player ID": str})
    if "Player ID" not in pw.columns:
        _skip("exports have no Player ID")
        return None
    return pw


def test_traded_players_read_the_weeks_team():
    pw = _pw()
    if pw is None:
        return
    for (pid, name, y, w), team in CASES.items():
        r = pw[(pw["Player ID"] == pid) & (pw["Year"] == y) & (pw["Week"] == w)]
        assert len(r) == 1, (name, y, w, len(r))
        assert r["NFL team"].iat[0] == team, (name, y, w, r["NFL team"].iat[0], team)
    mw = pw[(pw["Player ID"] == "4068") & (pw["Year"] == 2024) & (pw["Week"] == 12)].iloc[0]
    assert str(mw["Bye?"]).lower() in ("false", "0"), mw["Bye?"]
    assert mw["Game slot"] == "Thursday", mw["Game slot"]


def test_no_bye_week_shows_the_player_on_the_field():
    pw = _pw()
    if pw is None or "Snap %" not in pw.columns:
        return _skip("no Snap % column") if pw is not None else None
    bye = pw["Bye?"].astype(str).str.lower().isin(["true", "1", "1.0"])
    on_field = pd.to_numeric(pw["Snap %"], errors="coerce").fillna(0) > 0
    bad = pw.loc[bye & on_field, ["Player", "Player ID", "Year", "Week", "NFL team"]]
    assert bad.empty, bad.to_string()


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
