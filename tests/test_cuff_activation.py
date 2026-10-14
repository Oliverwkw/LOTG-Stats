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


def _act(pw):
    return pw[pd.to_numeric(pw[_ACT], errors="coerce").fillna(0) > 0]


def test_a_cuff_stays_activated_for_the_whole_absence():
    """Once activated by a teammate's injury, he is activated every week he
    starts until that teammate plays again — his own play in the gap cannot argue
    him out (user, 2026-10-13). Jerome Ford, Nick Chubb out from 2023 week 3."""
    pw = _pw()
    if pw is None:
        return
    act = _act(pw)
    inj = pw[_flag(pw["Injury?"])]
    k = ["Team", "NFL team", "Position"]
    hurt = {}
    for r in inj[k + ["Year", "Week", "Player"]].astype(str).values.tolist():
        hurt.setdefault(tuple(r[:3]) + (r[3],), {}).setdefault(int(r[4]), set()).add(r[5])
    starts = pw[pw["Starter/Bench"].astype(str).eq("Starter")]
    started = set(map(tuple, starts[["Player", "Team", "Year", "Week"]].astype(str).values.tolist()))
    activated = set(map(tuple, act[["Player", "Team", "Year", "Week"]].astype(str).values.tolist()))
    missed = []
    for p, t, y, w in sorted(activated):
        nfl, pos = act.loc[(act["Player"].astype(str) == p) & (act["Team"].astype(str) == t)
                           & (act["Year"].astype(str) == y) & (act["Week"].astype(str) == w),
                           ["NFL team", "Position"]].astype(str).values[0]
        spell = hurt.get((t, nfl, pos, y), {})
        who = spell.get(int(w), set())
        nxt = int(w) + 1
        while who & spell.get(nxt, set()):      # the same teammate still out
            who = who & spell[nxt]
            if (p, t, y, str(nxt)) in started and (p, t, y, str(nxt)) not in activated:
                missed.append((p, t, y, nxt))
            nxt += 1
    assert not missed, missed[:10]
    ford = {int(w) for p, t, y, w in activated if p == "Jerome Ford" and y == "2023"}
    assert {3, 4, 7} <= ford and len(ford) > 3, sorted(ford)


def test_a_teammate_two_offseasons_out_backs_nobody_up():
    pw = _pw()
    if pw is None:
        return
    act = _act(pw)
    # Tank Dell's last game: 2024 week 16. One offseason on (2025) Noel is still
    # his cuff; two on (2026) he is not.
    noel = act[(act["Player"] == "Jaylin Noel") & (act["Year"] == 2026)]
    assert noel.empty, noel[["Week"]].values.tolist()
    assert not act[(act["Player"] == "Jaylin Noel") & (act["Year"] == 2025)].empty


def test_a_top_rookie_pick_is_no_ones_cuff():
    """Tetairoa McMillan (2025, a top-12 rookie pick) filled in for an injured
    Jalen Coker but was never his cuff (user, 2026-10-13)."""
    pw = _pw()
    if pw is None:
        return
    act = _act(pw)
    tm = act[(act["Player"] == "Tetairoa McMillan") & (act["Year"] == 2025)]
    assert tm.empty, sorted(tm["Week"])


if __name__ == "__main__":
    test_a_cuff_stays_activated_for_the_whole_absence()
    test_a_teammate_two_offseasons_out_backs_nobody_up()
    test_a_top_rookie_pick_is_no_ones_cuff()
    test_every_activation_is_a_start_with_an_injured_teammate()
    test_cuffs_started_counts_distinct_activated_players()
    print("PASS")
