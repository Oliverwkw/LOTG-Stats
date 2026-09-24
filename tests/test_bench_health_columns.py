"""The bench / healthy-week columns reconcile to player_week.

Eight columns, added so "how often did he sit when he could have played" is
answerable off the sheets (the Pat Freiermuth inquiry: 75 healthy games on
JacobRosenzweig, 11 starts):

  player_year / player_all_time
    Healthy weeks rostered   rostered weeks that were not a bye/injury/suspension
    Healthy weeks on bench   benched weeks among those
    Healthy % of starts      healthy starts / healthy weeks rostered
    Total points on bench    points scored in benched weeks
  player_additions (per tenure)
    Bench weeks on team          Tenure (NFL weeks) - Number of starts before next drop
    Healthy bench weeks on team  benched healthy weeks in the tenure
    Injured weeks on team        Injury?-flagged weeks in the tenure
    Bench points on team         points scored in benched weeks in the tenure

The rest of the request already existed and is NOT duplicated: starts
("Weeks as starter" / "Number of starts before next drop"), weeks on bench, start % ("% of starts"
/ "% of starts made while rostered"), injured weeks ("Weeks missed due to
injury"), and on player_additions healthy weeks ("Games played on team") and
healthy start % ("Injury adjusted % of starts made while rostered").
player_additions' "Starts on team" was dropped as an exact duplicate of
"Number of starts before next drop".

Everything here is recomputed from player_week, so nothing is pinned to a value
that moves. The season recompute runs on seasons before the latest one in
player_week, so an in-progress week cannot race it. Skips while the committed
exports predate the columns (they reach exports/ with the first post-merge
build); a build carrying only SOME of them fails.

Run: python tests/test_bench_health_columns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_EXP = _ROOT / "exports"

_PLAYER_COLS = ["Healthy weeks on bench", "Healthy weeks rostered",
                "Healthy % of starts", "Total points on bench"]
_PA_COLS = ["Bench weeks on team", "Healthy bench weeks on team",
            "Injured weeks on team", "Bench points on team"]


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _read(name: str):
    p = _EXP / f"{name}.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _flag(s):
    return s.astype(str).str.strip().str.lower().isin(("true", "1", "yes"))


def _frames(sheet: str, cols):
    """(player_week, sheet) or a skip reason. Fails when only part of the set shipped."""
    pw, df = _read("player_week"), _read(sheet)
    if pw is None or df is None:
        return None, f"exports/{sheet}.csv or player_week.csv absent"
    have = [c for c in cols if c in df.columns]
    if not have:
        return None, f"{sheet} predates the bench/healthy columns (pre-merge exports)"
    assert have == cols, f"{sheet} carries only some of the new columns: {have}"
    return (pw, df), None


def _weekly(pw: pd.DataFrame) -> pd.DataFrame:
    w = pw[["Player", "Team", "Year", "Week", "Starter/Bench", "Points",
            "Injury?", "Suspension?", "Bye?"]].copy()
    w["Points"] = _num(w["Points"]).fillna(0.0)
    w["start"] = w["Starter/Bench"].astype(str).str.strip().eq("Starter")
    w["injured"] = _flag(w["Injury?"])
    w["healthy"] = ~(w["injured"] | _flag(w["Suspension?"]) | _flag(w["Bye?"]))
    return w


def test_player_year_recomputes_from_player_week():
    got, why = _frames("player_year", _PLAYER_COLS)
    if got is None:
        return _skip(why)
    pw, py = got
    w = _weekly(pw)
    last = int(_num(w["Year"]).max())
    w = w[_num(w["Year"]) < last]
    exp = w.groupby(["Player", "Year"]).agg(
        hw=("healthy", "sum"),
        hb=("healthy", lambda s: int((s & ~w.loc[s.index, "start"]).sum())),
        hs=("healthy", lambda s: int((s & w.loc[s.index, "start"]).sum())),
        bp=("Points", lambda s: float(s[~w.loc[s.index, "start"]].sum())),
    ).reset_index()
    py = py[_num(py["Year"]) < last]
    # A name two players share in one season is one group in player_week but
    # two rows here; compare the unambiguous rows (all but a handful).
    py = py[~py.duplicated(["Player", "Year"], keep=False)]
    m = py.merge(exp, on=["Player", "Year"], how="inner")
    assert len(m) > 1000, f"only {len(m)} player-seasons matched player_week"
    bad = m[(_num(m["Healthy weeks rostered"]) != m["hw"])
            | (_num(m["Healthy weeks on bench"]) != m["hb"])
            | ((_num(m["Total points on bench"]) - m["bp"]).abs() > 0.011)]
    assert bad.empty, f"{len(bad)} player-seasons disagree with player_week:\n{bad.head()}"
    rate = m[m["hw"] > 0]
    off = rate[((_num(rate["Healthy % of starts"]) - rate["hs"] / rate["hw"]).abs() > 5e-5)]
    assert off.empty, f"{len(off)} player-seasons with a wrong Healthy % of starts:\n{off.head()}"
    # A padded row with no rostered week reads 0 on the three counts.
    print(f"  {len(m)} completed player-seasons reconcile to player_week")


def test_player_year_internal_identities():
    got, why = _frames("player_year", _PLAYER_COLS)
    if got is None:
        return _skip(why)
    for name in ("player_year", "player_all_time"):
        df = _read(name)
        ros, bench = _num(df["Weeks rostered"]), _num(df["Weeks on bench"])
        hw, hb = _num(df["Healthy weeks rostered"]), _num(df["Healthy weeks on bench"])
        starts, inj = _num(df["Weeks as starter"]), _num(df["Weeks missed due to injury"])
        sus = _num(df["Weeks missed due to suspension"])
        pct = _num(df["Healthy % of starts"])
        # A new column is blank exactly where its existing sibling is (a row the
        # build leaves unfilled — the offline harness's out-of-range season).
        for new, old in ((hb, bench), (hw, ros), (pct, _num(df["% of starts"]))):
            assert (new.isna() == old.isna()).all(), f"{name}: blank cells disagree with the gross column"
        k = ros.notna()
        ros, bench, hw, hb, starts, inj, sus, pct = (
            x[k] for x in (ros, bench, hw, hb, starts, inj, sus, pct))
        assert (hb <= bench).all() and (hw <= ros).all(), f"{name}: healthy exceeds gross"
        # Healthy + injured + suspended never exceeds rostered (byes are the gap).
        assert (hw + inj + sus <= ros).all(), f"{name}: healthy + injured + suspended > rostered"
        assert ((hw - hb) <= starts).all(), f"{name}: healthy starts exceed starts"
        assert pct.between(0, 1).all(), f"{name}: Healthy % of starts outside 0-1"


def test_all_time_sums_the_seasons():
    got, why = _frames("player_all_time", _PLAYER_COLS)
    if got is None:
        return _skip(why)
    py, pa = _read("player_year"), _read("player_all_time")
    # The sheets carry no Player ID; a name is unique on each (the pid-collision
    # fix), so the name is the join key. Rows sharing a name are left out.
    pa = pa[~pa["Player"].duplicated(keep=False)]
    cols = ["Healthy weeks on bench", "Healthy weeks rostered", "Total points on bench"]
    s = py.assign(**{c: _num(py[c]) for c in cols}).groupby("Player")[cols].sum()
    m = pa.set_index("Player")[cols].apply(_num).join(s, rsuffix="_sum", how="inner")
    assert len(m) == len(pa), "a player_all_time row has no player_year rows"
    for c in cols:
        # Each season's points are rounded to 0.01 before they are summed.
        d = (m[c] - m[f"{c}_sum"]).abs()
        assert (d <= 0.05).all(), f"{c}: all-time != sum of seasons for {int((d > 0.05).sum())} players"


def test_player_additions_reconcile():
    got, why = _frames("player_additions", _PA_COLS)
    if got is None:
        return _skip(why)
    pw, pa = got
    ten, starts = _num(pa["Tenure (NFL weeks)"]), _num(pa["Number of starts before next drop"])
    games = _num(pa["Games played on team"])
    bench, hbench = _num(pa["Bench weeks on team"]), _num(pa["Healthy bench weeks on team"])
    inj = _num(pa["Injured weeks on team"])
    has = ten > 0
    assert (bench[has] == (ten - starts)[has]).all(), "Bench weeks != Tenure weeks - Starts"
    assert (hbench <= bench).all() and (hbench <= games).all(), "healthy bench exceeds its bounds"
    assert ((games + inj)[has] <= ten[has]).all(), "Games played + injured weeks > tenure"
    # Healthy bench share is the complement of the injury-adjusted start rate.
    rate = _num(pa["Injury adjusted % of starts made while rostered"])
    g = games > 0
    off = ((hbench[g] / games[g]) - (1 - rate[g])).abs() > 5e-5
    assert not off.any(), f"{int(off.sum())} rows: healthy bench share != 1 - injury-adjusted start %"

    # A (team, player) pair with ONE addition row owns every rostered week of
    # the pair (#439), so its tenure totals equal the pair's player_week totals.
    w = _weekly(pw)
    tot = w.groupby(["Team", "Player"]).agg(
        n=("Week", "size"), inj=("injured", "sum"),
        bp=("Points", lambda s: float(s[~w.loc[s.index, "start"]].sum())),
        pts=("Points", "sum")).reset_index()
    single = pa[~pa.duplicated(["Team", "Player"], keep=False)]
    m = single.merge(tot, on=["Team", "Player"], how="inner")
    m = m[_num(m["Tenure (NFL weeks)"]) == m["n"]]
    assert len(m) > 500, f"only {len(m)} single-tenure pairs to check"
    bad = m[(_num(m["Injured weeks on team"]) != m["inj"])
            | ((_num(m["Bench points on team"]) - m["bp"]).abs() > 0.011)
            | ((_num(m["Bench points on team"]) + _num(m["Points added"]) - m["pts"]).abs() > 0.03)]
    assert bad.empty, f"{len(bad)} single-tenure rows disagree with player_week:\n{bad.head()}"
    print(f"  {len(m)} single-tenure additions reconcile to player_week")


if __name__ == "__main__":
    for fn in (test_player_year_recomputes_from_player_week, test_player_year_internal_identities,
               test_all_time_sums_the_seasons, test_player_additions_reconcile):
        print(fn.__name__)
        fn()
    print("ok")
