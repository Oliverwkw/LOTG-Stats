"""add_drops' Points Added counts the same started weeks as its start count.

"Points Added" (add_drops) is the added player's points in the weeks he started
for this team. It used to window those weeks by each week's THURSDAY, while
"Number of starts before next drop" and player_additions' "Points added" window
by the week's last game in league days (_tenure_stats). A pickup made after a
week's Thursday but before the player's game (Giovani Bernard, LWebs53, Sun
2020-10-25 and Thu 2020-10-29) kept the start in the count and lost its points:
58 of 1,091 matched pickups read low, 39 of them 0.0 on a row with a start.

Checks, over completed seasons:
* add_drops "Points Added" == player_additions "Points added" on every pickup
  the two sheets share (the same tenure, one number);
* a row with no start has no Points Added, and the per-start averages divide by
  the start count;
* Net points = Points Added − Points Lost.

Data-dependent; skips cleanly without exports/.
Run: python tests/test_points_added_consistency.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_EXPORTS = Path(__file__).resolve().parent.parent / "exports"


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _completed(df):
    seasons = pd.to_numeric(df["Season"], errors="coerce")
    return df[seasons < seasons.max()]


def _add_drops():
    ad = pd.read_csv(_EXPORTS / "add_drops.csv", dtype=str, keep_default_na=False)
    ad = ad[ad["Player Added"].str.strip().ne("") & ad["Player Added"].ne("N/A")]
    return _completed(ad).copy()


def check_points_added_matches_player_additions():
    if not ((_EXPORTS / "add_drops.csv").exists() and (_EXPORTS / "player_additions.csv").exists()):
        print("  [SKIP] exports/ absent")
        return True
    ad = _add_drops()
    ad["day"] = ad["Date"].str[:10]
    pa = pd.read_csv(_EXPORTS / "player_additions.csv", dtype=str, keep_default_na=False)
    pa = pa[pa["Addition type"].isin(["Waiver", "Free agency"])].copy()
    pa["day"] = pa["Date"].str[:10]
    key_a, key_p = ["Team", "Player Added", "day"], ["Team", "Player", "day"]
    # Several claims for one player on one team on one day cannot be told apart.
    ad = ad[~ad.duplicated(key_a, keep=False)]
    pa = pa[~pa.duplicated(key_p, keep=False)]
    j = ad.merge(pa, left_on=key_a, right_on=key_p, suffixes=("_ad", "_pa"))
    ok = _ok("the two sheets' pickups line up", len(j) > 500, f"{len(j)} matched")
    a = pd.to_numeric(j["Points Added"], errors="coerce")
    p = pd.to_numeric(j["Points added"], errors="coerce")
    m = (a - p).abs() > 0.011
    bad = j.loc[m, ["Team", "Player", "day"]].assign(add_drops=a[m], player_additions=p[m])
    ok &= _ok("Points Added: same value on every shared pickup", bad.empty,
              f"{len(bad)} differ, e.g. {bad.head(4).values.tolist()}")
    return ok


def check_points_follow_the_start_count():
    if not (_EXPORTS / "add_drops.csv").exists():
        print("  [SKIP] exports/ absent")
        return True
    ad = _add_drops()
    n = lambda c: pd.to_numeric(ad[c], errors="coerce")
    starts, added, lost, net = (n("Number of starts before next drop"), n("Points Added"),
                                n("Points Lost"), n("Net points"))
    ok = True
    m = (starts == 0) & ((added != 0) | (lost != 0))
    ok &= _ok("no start -> no Points Added / Lost", not m.any(),
              f"{int(m.sum())} rows, e.g. {ad.loc[m, ['Team', 'Player Added', 'Date']].head(3).values.tolist()}")
    for col, tot in (("Avg points added", added), ("Avg points lost", lost), ("Avg net points", net)):
        exp = (tot / starts).where(starts > 0, 0.0)
        m = (n(col) - exp).abs() > 0.011
        ok &= _ok(f"{col} = total / starts", not m.any(),
                  f"{int(m.sum())} rows, e.g. {ad.loc[m, ['Team', 'Player Added', 'Date']].head(3).values.tolist()}")
    m = (net - (added - lost)).abs() > 0.011
    ok &= _ok("Net points = Points Added - Points Lost", not m.any(), f"{int(m.sum())} rows")
    return ok


def run_all():
    print("check_points_added_matches_player_additions:")
    ok = check_points_added_matches_player_additions()
    print("\ncheck_points_follow_the_start_count:")
    ok &= check_points_follow_the_start_count()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_points_added_consistency():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
