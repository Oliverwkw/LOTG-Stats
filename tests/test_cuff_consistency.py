"""One handcuff definition across add_drops, player_additions and the pick sheets.

The acquisition cuff flag (user rule, 2026-09-22) is computed by one helper,
`_is_cuff`, at the moment of the move. So the same pickup carries one flag on
add_drops ("Cuff at time of pickup?") and player_additions ("Cuff at pickup?"),
and a drafted player one flag on the pick sheet ("Cuff when drafted?") and his
player_additions Draft row. Before the rule the two pickup sheets used different
tests and disagreed on 30 of 1,094 pickups.

Data-dependent; skips cleanly without exports/.
Run: python tests/test_cuff_consistency.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_EXPORTS = Path(__file__).resolve().parent.parent / "exports"


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _flag(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def check_pickups_carry_one_flag():
    ad_p, pa_p = _EXPORTS / "add_drops.csv", _EXPORTS / "player_additions.csv"
    if not (ad_p.exists() and pa_p.exists()):
        print("  [SKIP] exports/ absent")
        return True
    ad = pd.read_csv(ad_p, dtype=str, keep_default_na=False)
    pa = pd.read_csv(pa_p, dtype=str, keep_default_na=False)
    ad = ad[ad["Player Added"].str.strip().ne("") & ad["Player Added"].ne("N/A")].copy()
    ad["day"] = ad["Date"].str[:10]
    pa = pa[pa["Addition type"].isin(["Waiver", "Free agency"])].copy()
    pa["day"] = pa["Date"].str[:10]
    ka, kp = ["Team", "Player Added", "day"], ["Team", "Player", "day"]
    ad, pa = ad[~ad.duplicated(ka, keep=False)], pa[~pa.duplicated(kp, keep=False)]
    j = ad.merge(pa, left_on=ka, right_on=kp)
    m = _flag(j["Cuff at time of pickup?"]) != _flag(j["Cuff at pickup?"])
    ok = _ok("pickups line up", len(j) > 500, f"{len(j)} matched")
    ok &= _ok("same cuff flag on every pickup", not m.any(),
              f"{int(m.sum())} differ, e.g. {j.loc[m, kp].head(4).values.tolist()}")
    return ok


def check_draft_rows_carry_the_picks_flag():
    files = [_EXPORTS / f for f in ("player_additions.csv", "rookie_picks.csv", "non_rookie_picks.csv")]
    if not all(f.exists() for f in files):
        print("  [SKIP] exports/ absent")
        return True
    pa = pd.read_csv(files[0], dtype=str, keep_default_na=False)
    pa = pa[pa["Addition type"] == "Draft"]
    pk = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files[1:]])
    pk = pk.rename(columns={"Player Picked": "Player"})
    key = ["Player", "Team"]
    pa, pk = pa[~pa.duplicated(key, keep=False)], pk[~pk.duplicated(key, keep=False)]
    j = pa.merge(pk, on=key)
    m = _flag(j["Cuff at pickup?"]) != _flag(j["Cuff when drafted?"])
    ok = _ok("draft rows line up", len(j) > 300, f"{len(j)} matched")
    ok &= _ok("same cuff flag on every drafted player", not m.any(),
              f"{int(m.sum())} differ, e.g. {j.loc[m, key].head(4).values.tolist()}")
    return ok


def run_all():
    ok = True
    for fn in (check_pickups_carry_one_flag, check_draft_rows_carry_the_picks_flag):
        print(f"\n{fn.__name__}:")
        ok &= fn()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_cuff_consistency():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
