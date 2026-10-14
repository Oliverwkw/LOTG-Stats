"""Who filled the flex slots (lotg_support.flex_shares).

`% of FLX WR/RB/TE` and `% of SFLX WR/RB/TE/QB` on team_year / team_all_time /
league_year / league_all_time: the positional split of the starts made in the
regular flex slots (FLX1, FLX2) and the superflex (SFLX), pooled over the
period. Empty slots have no player_week row, so they count nowhere.

Run: python tests/test_flex_shares.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import flex_shares as F  # noqa: E402

_EXPORTS = _ROOT / "exports"


def _start(team, year, slot, pos, starter=True):
    return {"Team": team, "Year": year, "Starter/Bench": "Starter" if starter else "Bench",
            F.SLOT_COL: slot if starter else None, "Position": pos}


def _pw():
    return pd.DataFrame([
        _start("A", 2024, "FLX1", "WR"), _start("A", 2024, "FLX2", "RB"),
        _start("A", 2024, "FLX1", "WR"), _start("A", 2024, "FLX2", "TE"),
        _start("A", 2024, "SFLX", "QB"), _start("A", 2024, "SFLX", "WR"),
        _start("A", 2024, "QB", "QB"), _start("A", 2024, "WR1", "WR"),
        _start("A", 2024, None, "WR", starter=False),
        _start("B", 2024, "FLX1", "RB"), _start("B", 2024, "SFLX", "QB"),
        _start("B", 2025, "WR2", "WR"),           # a season with no flex starts
    ])


def test_slot_kind():
    assert F.slot_kind("FLX1") == "FLX" and F.slot_kind("FLX2") == "FLX" and F.slot_kind("flx") == "FLX"
    assert F.slot_kind("SFLX") == "SFLX"
    for other in ("QB", "WR1", "RB2", "TE", "", None, "BN"):
        assert F.slot_kind(other) is None, other


def test_team_year_shares_pool_both_flex_slots():
    out = F.flex_shares(_pw(), ["Team", "Year"]).set_index(["Team", "Year"])
    a = out.loc[("A", 2024)]
    assert (a["% of FLX WR"], a["% of FLX RB"], a["% of FLX TE"]) == (50.0, 25.0, 25.0)
    assert (a["% of SFLX QB"], a["% of SFLX WR"], a["% of SFLX RB"], a["% of SFLX TE"]) == (50.0, 50.0, 0.0, 0.0)
    b = out.loc[("B", 2024)]
    assert (b["% of FLX RB"], b["% of FLX WR"], b["% of SFLX QB"]) == (100.0, 0.0, 100.0)
    # no flex starts → no row, so the build's left merge leaves it N/A (not 0)
    assert ("B", 2025) not in out.index


def test_bench_and_fixed_slots_are_ignored():
    pw = _pw()
    pw = pd.concat([pw, pd.DataFrame([_start("A", 2024, "FLX1", "QB", starter=False)])])
    a = F.flex_shares(pw, ["Team", "Year"]).set_index(["Team", "Year"]).loc[("A", 2024)]
    assert a["% of FLX WR"] == 50.0


def test_league_pooled_and_all_time():
    ly = F.flex_shares(_pw(), ["Year"]).set_index("Year").loc[2024]
    assert ly["% of FLX WR"] == 40.0 and ly["% of FLX RB"] == 40.0 and ly["% of FLX TE"] == 20.0
    la = F.flex_shares(_pw(), [])
    assert len(la) == 1 and la.at[0, "% of SFLX QB"] == round(2 / 3 * 100, 1)
    assert list(la.columns) == F.COLUMNS


def test_only_one_kind_leaves_the_other_none():
    pw = pd.DataFrame([_start("A", 2024, "SFLX", "QB")])
    r = F.flex_shares(pw, ["Team"]).iloc[0]
    assert r["% of SFLX QB"] == 100.0 and r["% of FLX WR"] is None


def test_empty_input():
    out = F.flex_shares(pd.DataFrame(), ["Team"])
    assert out.empty and list(out.columns) == ["Team"] + F.COLUMNS


def _exports_pw():
    p = _EXPORTS / "player_week.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, usecols=["Team", "Year", "Starter/Bench", F.SLOT_COL, "Position"])


def test_committed_data_shares_are_sane():
    """On the committed player_week: every completed team-season has both
    families summing to 100, and no QB is ever in a regular flex slot."""
    pw = _exports_pw()
    if pw is None:
        print("exports/ absent — data checks not run")
        return
    fs = F.flex_starts(pw)
    assert not (fs[fs["_kind"] == "FLX"]["Position"] == "QB").any(), "QB in a regular flex slot"
    done = pw[pw["Year"] < pw["Year"].max()]
    ty = F.flex_shares(done, ["Team", "Year"])
    assert len(ty) == done.groupby(["Team", "Year"]).ngroups
    for fam, pos in (("FLX", F.FLX_POSITIONS), ("SFLX", F.SFLX_POSITIONS)):
        tot = ty[[f"% of {fam} {p}" for p in pos]].astype(float).sum(axis=1)
        assert ((tot - 100).abs() <= 0.3).all(), (fam, tot.describe())


def test_committed_sheets_match_player_week():
    """Where the committed sheets already carry the columns, they reproduce
    from player_week (completed seasons only)."""
    pw = _exports_pw()
    ty_p = _EXPORTS / "team_year.csv"
    if pw is None or not ty_p.exists():
        print("exports/ absent — reconciliation not run")
        return
    ty = pd.read_csv(ty_p)
    if not set(F.COLUMNS).issubset(ty.columns):
        print("committed team_year predates the flex-share columns — reconciliation not run")
        return
    last = pw["Year"].max()
    want = F.flex_shares(pw[pw["Year"] < last], ["Team", "Year"])
    got = ty[pd.to_numeric(ty["Year"], errors="coerce") < last]
    got = got.assign(Year=pd.to_numeric(got["Year"]).astype(int))
    m = want.merge(got[["Team", "Year"] + F.COLUMNS], on=["Team", "Year"], suffixes=("", "_sheet"))
    assert len(m) == len(want)
    for c in F.COLUMNS:
        a = pd.to_numeric(m[c], errors="coerce")
        b = pd.to_numeric(m[f"{c}_sheet"], errors="coerce")
        assert ((a - b).abs().fillna(0) < 0.051).all() and (a.isna() == b.isna()).all(), c


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
