"""The weekly handcuff columns agree with each other (user rule, 2026-09-23).

player_week "- Activated Cuff? ..." is the shared handcuff test applied to the
week's roster, plus: he started, and a qualifying teammate was injured. The team
sheets count it: "Number of cuffs started" is the team-week's activated cuffs
(DISTINCT players at the year / all-time grain), and never exceeds "Number of
cuffs rostered", which counts every rostered player the test flags.

Data-dependent; skips cleanly without exports/.
Run: python tests/test_cuff_weekly.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_EXPORTS = Path(__file__).resolve().parent.parent / "exports"


def _flag(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0", "yes"])


def _load():
    pw = pd.read_csv(_EXPORTS / "player_week.csv", dtype=str, keep_default_na=False)
    tw = pd.read_csv(_EXPORTS / "team_week.csv", dtype=str, keep_default_na=False)
    ty = pd.read_csv(_EXPORTS / "team_year.csv", dtype=str, keep_default_na=False)
    col = next(c for c in pw.columns if c.startswith("- Activated Cuff?"))
    return pw, tw, ty, col


def test_weekly_cuff_columns_agree():
    if not all((_EXPORTS / f).exists() for f in ("player_week.csv", "team_week.csv", "team_year.csv")):
        print("  SKIP — exports/ absent")
        return
    pw, tw, ty, col = _load()
    assert "Did he start while a teammate he is the handcuff for was injured" in col, col
    act = pw[_flag(pw[col])]
    assert (act["Starter/Bench"].str.lower() == "starter").all(), \
        act.loc[act["Starter/Bench"].str.lower() != "starter", ["Player", "Team", "Year", "Week"]].head()
    per_wk = act.groupby(["Team", "Year", "Week"]).size()
    tw = tw.set_index(["Team", "Year", "Week"])
    started = pd.to_numeric(tw["Number of cuffs started"], errors="coerce").fillna(0)
    rostered = pd.to_numeric(tw["Number of cuffs rostered"], errors="coerce").fillna(0)
    got = per_wk.reindex(tw.index).fillna(0)
    bad = started[(started - got).abs() > 0]
    assert bad.empty, f"team_week cuffs started != activated player-weeks: {bad.head().to_dict()}"
    assert (started <= rostered).all(), "more cuffs started than rostered in a week"
    per_yr = act.groupby(["Team", "Year"])["Player"].nunique()
    ty = ty.set_index(["Team", "Year"])
    yr = pd.to_numeric(ty["Number of cuffs started"], errors="coerce").fillna(0)
    bad_y = yr[(yr - per_yr.reindex(ty.index).fillna(0)).abs() > 0]
    assert bad_y.empty, f"team_year cuffs started != distinct activated players: {bad_y.head().to_dict()}"


if __name__ == "__main__":
    test_weekly_cuff_columns_agree()
    print("ok: weekly cuff columns agree")
