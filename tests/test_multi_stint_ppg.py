"""player_additions "PPG as team starter (multiple stints)" (moved from
player_week's "PPG as team starter", per user 2026-10-13).

Recomputed from player_week: a player's started points for a team / his starts
for it, over every week he was on it, sits on that player-team's LATEST stint
row; its earlier stints read "In Progress"; a player-team with no start is
blank on every row. The adjusted twin is blank exactly where the base is.

Run: python tests/test_multi_stint_ppg.py   (or pytest tests/)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_EXP = Path(__file__).resolve().parent.parent / "exports"
_COL = "PPG as team starter (multiple stints)"
_ADJ = "PPG as team starter adjusted by position (multiple stints)"


def _load():
    pa_p, pw_p = _EXP / "player_additions.csv", _EXP / "player_week.csv"
    if not (pa_p.exists() and pw_p.exists()):
        print("  SKIP — exports absent")
        return None, None
    pa = pd.read_csv(pa_p, low_memory=False)
    if _COL not in pa.columns:
        print(f"  SKIP — {_COL} not built yet")
        return None, None
    return pa, pd.read_csv(pw_p, low_memory=False)


def test_the_lifetime_pair_left_player_week():
    pa, pw = _load()
    if pa is None:
        return
    assert "PPG as team starter" not in pw.columns
    assert "PPG as team starter adjusted by position" not in pw.columns
    assert "PPG as team starter this season" in pw.columns
    assert _ADJ in pa.columns


def test_it_recomputes_from_player_week_on_the_latest_stint():
    pa, pw = _load()
    if pa is None:
        return
    pts = pd.to_numeric(pw["Points"], errors="coerce").fillna(0.0)
    st = pw["Starter/Bench"].astype(str).eq("Starter")
    g = pd.DataFrame({"Team": pw["Team"].astype(str), "Player": pw["Player"].astype(str),
                      "sp": pts.where(st, 0.0), "s": st.astype(int)}).groupby(["Team", "Player"]).sum()
    want = (g["sp"] / g["s"].where(g["s"] > 0)).round(2)
    key = list(zip(pa["Team"].astype(str), pa["Player"].astype(str)))
    latest = set(pa.assign(_k=key).drop_duplicates("_k", keep="last").index)
    bad, checked = [], 0
    for i, k in enumerate(key):
        v, exp = pa.at[i, _COL], want.get(k)
        blank = pd.isna(v) or str(v).strip() in ("", "nan")
        if exp is None or pd.isna(exp):
            if not blank:
                bad.append((k, v, "should be blank"))
            continue
        if i not in latest:
            if str(v) != "In Progress":
                bad.append((k, v, "earlier stint should read In Progress"))
            continue
        checked += 1
        if blank or abs(float(v) - float(exp)) > 0.011:
            bad.append((k, v, exp))
        adj = pa.at[i, _ADJ]
        if pd.isna(adj) or str(adj).strip() in ("", "nan"):
            bad.append((k, adj, "adjusted twin blank where the base is not"))
    assert checked > 500, checked
    assert not bad, bad[:10]


if __name__ == "__main__":
    test_the_lifetime_pair_left_player_week()
    test_it_recomputes_from_player_week_on_the_latest_stint()
    print("PASS")
