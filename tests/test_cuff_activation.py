"""A handcuff counts as STARTED only when activated (user rule, 2026-10-13, at
the 3 PPG margin): he started, and a same-NFL-team, same-position teammate on
his fantasy roster was injured that week. A cuff who merely started — the
starter healthy — is rostered, not started.

Checked on player_week's "- Activated Cuff?" and the team_year / league_year
"Number of cuffs started" built from it (distinct players).

Run: python tests/test_cuff_activation.py   (or pytest tests/)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_EXP = Path(__file__).resolve().parent.parent / "exports"
_ACT = "- Activated Cuff? (Did he start while a teammate he is the handcuff for was injured?)"


def _flag(s):
    return s.astype(str).str.strip().str.lower().isin(("true", "1", "1.0", "yes"))


def _pw():
    p = _EXP / "player_week.csv"
    if not p.exists():
        print("  SKIP — exports absent")
        return None
    pw = pd.read_csv(p, low_memory=False)
    return pw if _ACT in pw.columns else None


def test_every_activation_is_a_start_with_an_injured_teammate():
    pw = _pw()
    if pw is None:
        return
    act = pw[pd.to_numeric(pw[_ACT], errors="coerce").fillna(0) > 0]
    assert len(act) > 50, len(act)
    assert act["Starter/Bench"].astype(str).eq("Starter").all(), \
        act.loc[~act["Starter/Bench"].astype(str).eq("Starter"), ["Player", "Year", "Week"]].head()
    inj = pw[_flag(pw["Injury?"])]
    k = ["Team", "Year", "Week", "NFL team", "Position"]
    hurt = set(map(tuple, inj[k].astype(str).values.tolist()))
    missing = [tuple(r) for r in act[k + ["Player"]].astype(str).values.tolist()
               if tuple(r[:5]) not in hurt]
    assert not missing, missing[:10]


def test_cuffs_started_counts_distinct_activated_players():
    pw = _pw()
    ty_p = _EXP / "team_year.csv"
    if pw is None or not ty_p.exists():
        return
    ty = pd.read_csv(ty_p, low_memory=False)
    act = pw[pd.to_numeric(pw[_ACT], errors="coerce").fillna(0) > 0]
    want = act.groupby(["Team", "Year"])["Player"].nunique()
    got = ty.set_index(["Team", "Year"])["Number of cuffs started"]
    bad = [(k, int(got.get(k, 0)), int(want.get(k, 0))) for k in got.index
           if int(pd.to_numeric(got.get(k), errors="coerce") or 0) != int(want.get(k, 0))]
    assert not bad, bad[:10]


if __name__ == "__main__":
    test_every_activation_is_a_start_with_an_injured_teammate()
    test_cuffs_started_counts_distinct_activated_players()
    print("PASS")
