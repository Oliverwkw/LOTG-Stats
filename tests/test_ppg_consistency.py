"""add_drops and player_additions carry one number for each shared PPG column.

Both sheets describe the same waiver / free-agency pickup, and used to compute
its two PPG columns from different sources:

* "Avg PPG on team" (add_drops: "Average PPG on team") is the league's own
  points (player_week) per game played while rostered here. add_drops used the
  nflverse log over the tenure's dates.
* "PPG of 5 games before pickup" is the player's last 5 NFL games on the
  nflverse log, on any team or none. player_additions used rostered weeks only.

Data-dependent; skips cleanly without exports/.
Run: python tests/test_ppg_consistency.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_EXPORTS = Path(__file__).resolve().parent.parent / "exports"
_PAIRS = (("Average PPG on team", "Avg PPG on team"),
          ("PPG of 5 games before pickup", "PPG of 5 games before pickup"))


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _joined():
    ad = pd.read_csv(_EXPORTS / "add_drops.csv", dtype=str, keep_default_na=False)
    pa = pd.read_csv(_EXPORTS / "player_additions.csv", dtype=str, keep_default_na=False)
    ad = ad[ad["Player Added"].str.strip().ne("") & ad["Player Added"].ne("N/A")].copy()
    ad["day"] = ad["Date"].str[:10]
    pa = pa[pa["Addition type"].isin(["Waiver", "Free agency"])].copy()
    pa["day"] = pa["Date"].str[:10]
    key_a, key_p = ["Team", "Player Added", "day"], ["Team", "Player", "day"]
    # Several claims for one player on one team on one day cannot be told apart.
    ad = ad[~ad.duplicated(key_a, keep=False)]
    pa = pa[~pa.duplicated(key_p, keep=False)]
    return ad.merge(pa, left_on=key_a, right_on=key_p, suffixes=("_ad", "_pa"))


def check_both_sheets_carry_one_number():
    if not ((_EXPORTS / "add_drops.csv").exists() and (_EXPORTS / "player_additions.csv").exists()):
        print("  [SKIP] exports/ absent")
        return True
    j = _joined()
    ok = _ok("the two sheets' pickups line up", len(j) > 500, f"{len(j)} matched")
    for a_col, p_col in _PAIRS:
        a = pd.to_numeric(j[a_col if a_col != p_col else a_col + "_ad"], errors="coerce")
        p = pd.to_numeric(j[p_col if a_col != p_col else p_col + "_pa"], errors="coerce")
        m = (a.isna() != p.isna()) | ((a - p).abs() > 0.011)
        # Assign the MASKED values: .assign() onto an empty frame adopts the
        # assigned Series' index, which turned "nothing differs" into every row.
        bad = j.loc[m, ["Team", "Player", "day"]].assign(add_drops=a[m], player_additions=p[m])
        ok &= _ok(f"{p_col}: same value (or both blank) on every pickup", bad.empty,
                  f"{len(bad)} differ, e.g. {bad.head(4).values.tolist()}")
    return ok


def run_all():
    print("\ncheck_both_sheets_carry_one_number:")
    ok = check_both_sheets_carry_one_number()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_ppg_consistency():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
