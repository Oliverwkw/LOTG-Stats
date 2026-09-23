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


def check_draft_rows_match_the_pick_sheets():
    """A drafted player's tenure on the drafting team is one tenure on both
    sheets, so player_additions' Draft row and the pick sheet agree on it."""
    files = [_EXPORTS / f for f in ("player_additions.csv", "rookie_picks.csv", "non_rookie_picks.csv")]
    if not all(f.exists() for f in files):
        print("  [SKIP] exports/ absent")
        return True
    pa = pd.read_csv(files[0], dtype=str, keep_default_na=False)
    pa = pa[pa["Addition type"] == "Draft"]
    pk = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files[1:]])
    pk = pk.rename(columns={"Player Picked": "Player"})     # Team = the drafting team
    key = ["Player", "Team"]
    pa, pk = pa[~pa.duplicated(key, keep=False)], pk[~pk.duplicated(key, keep=False)]
    j = pa.merge(pk, on=key, suffixes=("_pa", "_pk"))
    a = pd.to_numeric(j["Avg PPG on team_pa"], errors="coerce")
    b = pd.to_numeric(j["Avg PPG on team_pk"], errors="coerce")
    m = (a.isna() != b.isna()) | ((a - b).abs() > 0.011)
    bad = j.loc[m, key].assign(player_additions=a[m], picks=b[m])
    ok = _ok("draft rows line up", len(j) > 300, f"{len(j)} matched")
    ok &= _ok("Avg PPG on team: same value (or both blank) on every drafted tenure", bad.empty,
              f"{len(bad)} differ, e.g. {bad.head(4).values.tolist()}")
    return ok


def check_single_player_trades_match_player_additions():
    """A trade that brought in exactly one player (no picks, no FAAB) has one
    received tenure, so its 'Avg PPG of received players on team' is that
    player's player_additions Trade row 'Avg PPG on team'."""
    tr_p, pa_p = _EXPORTS / "trades.csv", _EXPORTS / "player_additions.csv"
    if not (tr_p.exists() and pa_p.exists()):
        print("  [SKIP] exports/ absent")
        return True
    tr = pd.read_csv(tr_p, dtype=str, keep_default_na=False)
    pa = pd.read_csv(pa_p, dtype=str, keep_default_na=False)
    one = tr[~tr["Assets received"].str.contains(";|FAAB|\\(|^\\d{4} ", regex=True)
             & tr["Assets received"].str.strip().ne("")].copy()
    one["day"] = one["Date"].str[:10]
    pa = pa[pa["Addition type"] == "Trade"].copy()
    pa["day"] = pa["Date"].str[:10]
    one = one[~one.duplicated(["Team", "Assets received", "day"], keep=False)]
    pa = pa[~pa.duplicated(["Team", "Player", "day"], keep=False)]
    j = one.merge(pa, left_on=["Team", "Assets received", "day"], right_on=["Team", "Player", "day"])
    a = pd.to_numeric(j["Avg PPG of received players on team"], errors="coerce")
    b = pd.to_numeric(j["Avg PPG on team"], errors="coerce")
    m = (a.isna() != b.isna()) | ((a - b).abs() > 0.011)
    bad = j.loc[m, ["Team", "Player", "day"]].assign(trades=a[m], player_additions=b[m])
    ok = _ok("single-player trades line up", len(j) > 50, f"{len(j)} matched")
    ok &= _ok("received on-team PPG = the player's own Avg PPG on team", bad.empty,
              f"{len(bad)} differ, e.g. {bad.head(4).values.tolist()}")
    return ok


def run_all():
    print("\ncheck_both_sheets_carry_one_number:")
    ok = check_both_sheets_carry_one_number()
    print("\ncheck_draft_rows_match_the_pick_sheets:")
    ok &= check_draft_rows_match_the_pick_sheets()
    print("\ncheck_single_player_trades_match_player_additions:")
    ok &= check_single_player_trades_match_player_additions()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_ppg_consistency():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
