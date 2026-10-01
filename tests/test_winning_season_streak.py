"""team_year `Winning season streak` is decided by completed seasons only.

A season still being played has a provisional Win %. Counting it made the
COMPLETED seasons' rows flip week to week: in 2026, BROsenzweig at 1-1 extended
the run (2025 read "In Progress") and at 1-2 ended it (2025 read 2), found by
the sequential re-audit of runs 568 -> 570. Now [per user] the streak reads the
REGULAR-season record, and a season counts only once it is decided: .500
clinched even losing out extends the run, .500 out of reach even winning out
breaks it, and until then it reads N/A and leaves the run alone. A finished
regular season is always decided. Regular-season games = playoff start - 1.

The guard recomputes the terminal-encoded streak from every row's Regular
season record and checks every row. It skips on exports built before the fix
(the Formulas note says which rule shipped).

Run: python tests/test_winning_season_streak.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
_EXP = _ROOT / "exports"
_COL = "Winning season streak"


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _decided(record: str, games: int):
    """True clinched, False out of reach, None still open."""
    parts = [int(x) for x in str(record).split("-")]
    w, l, t = (parts + [0, 0, 0])[:3]
    score, remaining = w + 0.5 * t, max(0, games - (w + l + t))
    if score >= 0.5 * games:
        return True
    if score + remaining < 0.5 * games:
        return False
    return None


def _expected(seasons):
    """Terminal encoding over (year, winning?) in year order; None = undecided
    (reads N/A, skipped by the run)."""
    run, counts = 0, []
    for yr, winning in seasons:
        if winning is None:
            continue
        run = run + 1 if winning else 0
        counts.append((yr, run))
    out = {yr: "N/A" for yr, winning in seasons if winning is None}
    for k, (yr, c) in enumerate(counts):
        nxt = counts[k + 1][1] if k + 1 < len(counts) else None
        out[yr] = 0 if c == 0 else ("In Progress" if nxt == c + 1 else c)
    return out


def test_only_decided_seasons_move_the_streak():
    ty_p, fo_p = _EXP / "team_year.csv", _EXP / "formulas.csv"
    if not ty_p.exists() or not fo_p.exists():
        return _skip("exports absent")
    fo = pd.read_csv(fo_p, dtype=str, keep_default_na=False)
    note = " ".join(fo.loc[fo["Stat"] == _COL, "Notes"])
    if "neither extends nor breaks" not in note:
        return _skip("exports predate the in-progress-season fix (pre-merge build)")
    from lotg_support import inquiry as Q
    ty = pd.read_csv(ty_p, dtype=str, keep_default_na=False)
    ty["yr"] = pd.to_numeric(ty["Year"], errors="coerce")
    bad, checked = [], 0
    for team, g in ty.sort_values("yr").groupby("Team"):
        seasons = []
        for _, r in g.iterrows():
            yr = int(r.yr)
            if r["Regular season record"] not in ("", "N/A"):
                games = Q.season_meta(yr).playoff_week_start - 1
                seasons.append((yr, _decided(r["Regular season record"], games)))
        want = _expected(seasons)
        for _, r in g.iterrows():
            yr = int(r.yr)
            if yr not in want:
                continue
            checked += 1
            got = str(r[_COL]).replace(".0", "")
            exp = str(want[yr])
            if not (got == exp or (exp == "N/A" and got == "")):
                bad.append((team, yr, r[_COL], want[yr]))
    assert checked >= 8 * 6, f"only {checked} team-seasons checked"
    assert not bad, f"{len(bad)} team-seasons disagree (team, year, got, expected): {bad[:6]}"
    print(f"  {checked} team-seasons recompute from the regular-season record")


if __name__ == "__main__":
    test_only_decided_seasons_move_the_streak()
    print("ok")
