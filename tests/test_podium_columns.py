"""The Podium columns reconcile to team_week PF.

Three columns, the top-3 twin of the Top half family (same rules, 3 in place
of the median):

  team_week                     Podium?        PF >= the week's 3rd-highest PF (ties shared)
  team_week                     Podium streak  all-time run of Podium? weeks, terminal-encoded
  team_year / team_all_time     Times Podium?  count of Podium? weeks

Everything is recomputed from team_week's own PF, so nothing is pinned to a
value that moves. The season count is checked on seasons before the latest one
in team_week, so an in-progress week cannot race it. Skips while the committed
exports predate the columns (they reach exports/ with the first post-merge
build); a build carrying only SOME of them fails.

Run: python tests/test_podium_columns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_EXP = _ROOT / "exports"

_WEEK_COLS = ["Podium?", "Podium streak"]
_COUNT = "Times Podium?"


def _read(name: str):
    p = _EXP / f"{name}.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _flag(s):
    return s.astype(str).str.strip().str.lower().isin(("true", "1", "1.0", "yes"))


def _team_week():
    """team_week, or None (with a printed skip) when the columns are not there yet."""
    tw = _read("team_week")
    if tw is None:
        print("  SKIP — exports/team_week.csv absent")
        return None
    have = [c for c in _WEEK_COLS if c in tw.columns]
    if not have:
        print("  SKIP — team_week predates the Podium columns (pre-merge exports)")
        return None
    assert have == _WEEK_COLS, f"team_week carries only some of the Podium columns: {have}"
    tw = tw.copy()
    tw["Year"], tw["Week"] = _num(tw["Year"]), _num(tw["Week"])
    tw["_pf"] = _num(tw["PF"]).fillna(0.0)
    tw["_pod"] = _flag(tw["Podium?"])
    return tw


def _expected_flag(tw: pd.DataFrame) -> pd.Series:
    third = tw.groupby(["Year", "Week"])["_pf"].transform(lambda s: s.nlargest(3).min())
    return tw["_pf"] >= third


def test_podium_flag_is_top_three_by_pf():
    tw = _team_week()
    if tw is None:
        return
    want = _expected_flag(tw)
    bad = tw[want != tw["_pod"]]
    assert bad.empty, f"{len(bad)} Podium? rows disagree with PF >= 3rd-highest:\n" + \
        bad[["Team", "Year", "Week", "PF", "Podium?"]].head(10).to_string()
    # Every week has a podium of at least 3 (more only on a tie for 3rd), and a
    # podium team is always a top-half team.
    per_week = tw.groupby(["Year", "Week"])["_pod"].sum()
    assert (per_week >= 3).all(), per_week[per_week < 3]
    if "Top half of league?" in tw.columns:
        stray = tw[tw["_pod"] & ~_flag(tw["Top half of league?"])]
        assert stray.empty, f"{len(stray)} podium rows not in the top half"
    print(f"  Podium? matches PF >= 3rd-highest on all {len(tw)} team-weeks "
          f"({int(tw['_pod'].sum())} podium finishes)")


def test_podium_streak_is_the_terminal_encoded_run():
    tw = _team_week()
    if tw is None:
        return
    tw = tw.sort_values(["Team", "Year", "Week"]).reset_index(drop=True)
    want = []
    for _, g in tw.groupby("Team", sort=False):
        flags = g["_pod"].tolist()
        run, runs = 0, []
        for f in flags:
            run = run + 1 if f else 0
            runs.append(run)
        for k, r in enumerate(runs):
            nxt = runs[k + 1] if k + 1 < len(runs) else 0
            want.append(0 if r == 0 else ("In Progress" if nxt == r + 1 else r))
    got = [("In Progress" if str(v).strip() == "In Progress" else int(float(v)))
           for v in tw["Podium streak"]]
    bad = [(tw.at[i, "Team"], tw.at[i, "Year"], tw.at[i, "Week"], g, w)
           for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, f"{len(bad)} Podium streak cells differ (team, year, week, got, want): {bad[:10]}"
    longest = max((v for v in want if v != "In Progress"), default=0)
    print(f"  Podium streak recomputes on all {len(tw)} team-weeks (longest run {longest})")


def test_times_podium_is_the_weekly_sum():
    tw = _team_week()
    if tw is None:
        return
    ty, ta = _read("team_year"), _read("team_all_time")
    assert ty is not None and ta is not None, "team_year / team_all_time absent beside team_week"
    assert _COUNT in ty.columns and _COUNT in ta.columns, "Times Podium? missing beside the weekly columns"
    latest = int(tw["Year"].max())
    wk = tw[tw["Year"] < latest].groupby(["Team", "Year"])["_pod"].sum().rename("want").reset_index()
    ty = ty.assign(Year=_num(ty["Year"]))
    m = wk.merge(ty[["Team", "Year", _COUNT]], on=["Team", "Year"], how="left")
    d = (_num(m[_COUNT]) - m["want"]).abs()
    assert m[_COUNT].notna().all() and d.max() == 0, m[d != 0].head(10).to_string()
    at = tw.groupby("Team")["_pod"].sum().rename("want").reset_index()
    m2 = at.merge(ta[["Team", _COUNT]], on="Team", how="left")
    d2 = (_num(m2[_COUNT]) - m2["want"]).abs()
    assert m2[_COUNT].notna().all() and d2.max() == 0, m2[d2 != 0].to_string()
    print(f"  Times Podium? = Σ weekly on {len(m)} completed team-seasons and {len(m2)} teams all-time")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            try:
                fn()
            except AssertionError as e:
                fails += 1
                print(f"  FAIL — {e}")
    sys.exit(1 if fails else 0)
