"""player_additions' "... (multiple stints)" tenure family (moved from
player_week's lifetime player-team columns, per user 2026-10-13).

Each column recomputes from player_week over every week a player was on a
team: weeks started / benched / rostered, % started, his starter points and
their share of the team's starter points (all its seasons), PPG as a starter,
and weeks as the team's highest / lowest starter. The value sits on the
player-team's LATEST stint row; its earlier stints read "In Progress"; where a
value is undefined (a PPG with no start) every row is blank. The adjusted PPG
twin is blank exactly where its base is.

Run: python tests/test_multi_stint_tenure.py   (or pytest tests/)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_EXP = Path(__file__).resolve().parent.parent / "exports"
_S = " (multiple stints)"
_BASES = ("Total weeks as team starter", "Total weeks on bench", "Weeks rostered by this team",
          "% of starts on team", "% of team points on team", "Total points as team starter",
          "PPG as team starter", "PPG as team starter adjusted by position",
          "Total times highest starter on team", "Total times lowest starter on team")


def _load():
    pa_p, pw_p = _EXP / "player_additions.csv", _EXP / "player_week.csv"
    if not (pa_p.exists() and pw_p.exists()):
        print("  SKIP — exports absent")
        return None, None
    pa = pd.read_csv(pa_p, low_memory=False)
    if "PPG as team starter" + _S not in pa.columns:
        print("  SKIP — the multiple-stints family is not built yet")
        return None, None
    return pa, pd.read_csv(pw_p, low_memory=False)


def test_the_lifetime_family_left_player_week_for_player_additions():
    pa, pw = _load()
    if pa is None:
        return
    for b in _BASES:
        assert b not in pw.columns, f"{b} still on player_week"
        assert b + _S in pa.columns, f"{b}{_S} missing from player_additions"
        assert b + " this season" in pw.columns or b == "PPG as team starter adjusted by position", b
    assert "PPG as team starter adjusted by position this season" in pw.columns


def _flag(s):
    return s.astype(str).str.strip().str.lower().isin(("true", "1", "1.0", "yes"))


def _expected(pw):
    pts = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)
    st = pw["Starter/Bench"].astype(str).eq("Starter")
    df = pd.DataFrame({"Team": pw["Team"].astype(str), "Player": pw["Player"].astype(str),
                       "sp": pts.where(st, 0.0), "s": st.astype(int), "r": 1,
                       "hi": _flag(pw["Highest starter on team?"]).astype(int),
                       "lo": _flag(pw["Lowest starter on team?"]).astype(int)})
    team_sp = df.groupby("Team")["sp"].sum()
    g = df.groupby(["Team", "Player"]).sum()
    s = g["s"].where(g["s"] > 0)
    tsp = pd.Series(g.index.get_level_values("Team"), index=g.index).map(team_sp)
    return {
        "Total weeks as team starter": g["s"],
        "Total weeks on bench": g["r"] - g["s"],
        "Weeks rostered by this team": g["r"],
        "% of starts on team": (g["s"] / g["r"]).round(4),
        "% of team points on team": (g["sp"] / tsp.where(tsp > 0)).round(4),
        "Total points as team starter": g["sp"].round(2),
        "PPG as team starter": (g["sp"] / s).round(2),
        "Total times highest starter on team": g["hi"],
        "Total times lowest starter on team": g["lo"],
    }


def _blank(v):
    return pd.isna(v) or str(v).strip() in ("", "nan", "None")


def test_each_recomputes_from_player_week_on_the_latest_stint():
    pa, pw = _load()
    if pa is None:
        return
    want = _expected(pw)
    key = list(zip(pa["Team"].astype(str), pa["Player"].astype(str)))
    latest = set(pa.assign(_k=key).drop_duplicates("_k", keep="last").index)
    bad, checked = [], {}
    for base, exp_s in want.items():
        col = pa[base + _S]
        tol = 0.00011 if base.startswith("%") else 0.011
        for i, k in enumerate(key):
            v, exp = col.iat[i], exp_s.get(k, np.nan)
            if pd.isna(exp):
                if not _blank(v):
                    bad.append((base, k, v, "should be blank"))
                continue
            if i not in latest:
                if str(v) != "In Progress":
                    bad.append((base, k, v, "earlier stint should read In Progress"))
                continue
            checked[base] = checked.get(base, 0) + 1
            if _blank(v) or abs(float(v) - float(exp)) > tol:
                bad.append((base, k, v, float(exp)))
    assert all(n > 500 for n in checked.values()) and len(checked) == len(want), checked
    assert not bad, bad[:10]


def test_the_adjusted_twin_is_blank_exactly_where_its_base_is():
    pa, _pw = _load()
    if pa is None:
        return
    a = pa["PPG as team starter" + _S].map(_blank)
    b = pa["PPG as team starter adjusted by position" + _S].map(_blank)
    assert (a == b).all(), int((a != b).sum())
    ip = pa["PPG as team starter" + _S].astype(str).eq("In Progress")
    assert ip.eq(pa["PPG as team starter adjusted by position" + _S].astype(str).eq("In Progress")).all()


if __name__ == "__main__":
    test_the_lifetime_family_left_player_week_for_player_additions()
    test_each_recomputes_from_player_week_on_the_latest_stint()
    test_the_adjusted_twin_is_blank_exactly_where_its_base_is()
    print("PASS")
