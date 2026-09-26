"""The per-week PPG grid and the position-adjusted twin of every player PPG column.

Two additions, both recomputed here from the sheets themselves:

  1. The starter / rostered / healthy grid, where a sheet lacked a combination.
     player_year / player_all_time
       PPG starter per rostered week            Total points as starter / Weeks rostered
       Adjusted PPG starter per rostered week   healthy-week starter points / Healthy weeks rostered
     player_additions (per tenure)
       Adjusted Avg points added                healthy started points / healthy starts
       Avg points added per rostered week       Points added / Tenure (NFL weeks)
       Adjusted Avg points added per rostered week   healthy started points / Games played on team
       Avg points per rostered week on team     (Points added + Bench points on team) / Tenure
       PPG bench on team                        Bench points on team / Bench weeks on team
       Adjusted PPG bench on team               healthy bench points / Healthy bench weeks on team

  2. "<column> adjusted by position" beside every player PPG column (team and
     league averages mix every position and have none). The factor is the
     build's `_pos_factor`: that season's league starter average / that
     season's starter average at the player's position, both over player_week's
     STARTED rows — recomputed here from player_week.

Only completed seasons are recomputed (the latest season in player_week is left
out, so an in-progress week cannot race the check). Skips while the committed
exports predate the columns (they reach exports/ with the first post-merge
build); a build carrying only SOME of them fails.

Run: python tests/test_ppg_position_adjusted.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_EXP = _ROOT / "exports"
_A = " adjusted by position"

_PLAYER_BASES = ["Avg points", "Adjusted Avg points", "PPG starter", "Adjusted PPG starter",
                 "PPG bench", "Adjusted PPG bench", "PPG starter per rostered week",
                 "Adjusted PPG starter per rostered week", "PPG starter vs bench diff",
                 "Starter PAR per game"]
_NEW = {
    "player_year": (["PPG starter per rostered week", "Adjusted PPG starter per rostered week"]
                    + [b + _A for b in _PLAYER_BASES + [
                        "Avg points (full season)", "Change in avg points from previous season",
                        "Change in avg points from career"]]),
    "player_all_time": (["PPG starter per rostered week", "Adjusted PPG starter per rostered week"]
                        + [b + _A for b in _PLAYER_BASES + ["Avg points (full career)"]]),
    "player_additions": [c for b in ("Adjusted Avg points added", "Avg points added per rostered week",
                                     "Adjusted Avg points added per rostered week",
                                     "Avg points per rostered week on team", "PPG bench on team",
                                     "Adjusted PPG bench on team") for c in (b, b + _A)]
                        + ["PPG of 5 games before pickup" + _A],
    "add_drops": [b + _A for b in ("Average PPG on team", "Average PPG of dropped player over same time",
                                   "PPG of 5 games before pickup", "Dropped avg points")],
    "trades": [b + _A for b in ("Avg PPG of received players on team",
                                "Avg PPG of sent players over same time",
                                "Avg PPG of received players in 5 games before trade")],
    "player_week": ["PPG as team starter" + _A, "PPG as team starter adjusted by position this season",
                    "Difference in averages of best/worst startables over previous 5 games" + _A,
                    "Cuff adjusted difference" + _A],
}


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


def _sheet(name: str):
    """The sheet, or None (with a printed skip) when it predates the columns.
    Fails when only part of the set shipped."""
    df = _read(name)
    if df is None:
        _skip(f"exports/{name}.csv absent")
        return None
    have = [c for c in _NEW[name] if c in df.columns]
    if not have:
        _skip(f"{name} predates the PPG grid / position-adjusted columns (pre-merge exports)")
        return None
    assert have == _NEW[name], f"{name} carries only some of the new columns: {sorted(set(_NEW[name]) - set(have))}"
    return df


def _weekly(pw: pd.DataFrame) -> pd.DataFrame:
    w = pw[["Player", "Team", "Year", "Week", "Starter/Bench", "Position", "Points",
            "Injury?", "Suspension?", "Bye?"]].copy()
    w["Year"] = _num(w["Year"])
    w["Points"] = _num(w["Points"]).fillna(0.0)
    w["Position"] = w["Position"].astype(str).str.upper()
    w["start"] = w["Starter/Bench"].astype(str).str.strip().eq("Starter")
    w["healthy"] = ~(_flag(w["Injury?"]) | _flag(w["Suspension?"]) | _flag(w["Bye?"]))
    return w


def _factors(w: pd.DataFrame) -> dict:
    """{(season, position): league starter avg / position starter avg}."""
    st = w[w["start"]]
    league = st.groupby("Year")["Points"].mean()
    pos = st.groupby(["Year", "Position"])["Points"].mean()
    return {(int(y), p): float(league[y] / v) for (y, p), v in pos.items() if v and league.get(y)}


def _close(a, b, tol):
    a, b = _num(a), _num(b)
    return (a.isna() & b.isna()) | ((a - b).abs() <= tol)


def test_player_year_recomputes_from_player_week():
    py = _sheet("player_year")
    pw = _read("player_week")
    if py is None or pw is None:
        return True
    w = _weekly(pw)
    fac = _factors(w)
    last = int(w["Year"].max())
    w = w[w["Year"] < last]
    w["f"] = [fac.get((int(y), p), 1.0) for y, p in zip(w["Year"], w["Position"])]
    w["sp"] = w["Points"].where(w["start"], 0.0)
    w["hsp"] = w["sp"].where(w["healthy"], 0.0)
    g = w.assign(sp_f=w["sp"] * w["f"], hsp_f=w["hsp"] * w["f"],
                 pts_f=w["Points"] * w["f"]).groupby(["Player", "Year"])
    exp = pd.DataFrame({
        "n": g.size(), "hw": g["healthy"].sum(), "sp": g["sp"].sum(), "hsp": g["hsp"].sum(),
        "sp_f": g["sp_f"].sum(), "hsp_f": g["hsp_f"].sum(), "pts_f": g["pts_f"].sum(),
        "starts": g["start"].sum(),
    }).reset_index()
    py = py[_num(py["Year"]) < last]
    py = py[~py.duplicated(["Player", "Year"], keep=False)]
    m = py.merge(exp, on=["Player", "Year"], how="inner")
    assert len(m) > 1000, f"only {len(m)} player-seasons matched player_week"
    per = lambda a, b: a / b.where(b > 0)  # noqa: E731
    checks = {
        "PPG starter per rostered week": per(m["sp"], m["n"]),
        "Adjusted PPG starter per rostered week": per(m["hsp"], m["hw"]),
        "PPG starter per rostered week" + _A: per(m["sp_f"], m["n"]),
        "Adjusted PPG starter per rostered week" + _A: per(m["hsp_f"], m["hw"]),
        "PPG starter" + _A: per(m["sp_f"], m["starts"]),
        "Avg points" + _A: per(m["pts_f"], m["n"]),
    }
    for col, want in checks.items():
        bad = ~_close(m[col], want.round(4), 2e-4)
        assert not bad.any(), f"{col}: {int(bad.sum())} player-seasons disagree with player_week"
    # Within one season every adjusted column is its base x that season's factor
    # — checked on EVERY season row (the factor comes from the same build).
    pos_by_name = _weekly(pw).groupby("Player")["Position"].first()
    m = py_all = _read("player_year")
    m = m[m["Player"].isin(pos_by_name.index) & _num(m["Year"]).notna()]
    f = pd.Series([fac.get((int(y), p), 1.0) for y, p in
                   zip(_num(m["Year"]), m["Player"].map(pos_by_name))], index=m.index)
    assert len(m) > 0.9 * len(py_all), "most player_year rows should have a position"
    for base in ("Adjusted Avg points", "Adjusted PPG starter", "PPG bench", "Adjusted PPG bench",
                 "Avg points (full season)", "PPG starter vs bench diff"):
        bad = ~_close(m[base + _A], _num(m[base]) * f, 2e-4 * (1 + f.abs()) + 1e-4)
        assert not bad.any(), f"{base}{_A}: {int(bad.sum())} rows are not base x factor"
    # PAR is rounded to 0.01 before and after scaling.
    bad = ~_close(m["Starter PAR per game" + _A], _num(m["Starter PAR per game"]) * f, 0.006 + 0.005 * f)
    assert not bad.any(), f"Starter PAR per game{_A}: {int(bad.sum())} rows are not base x factor"
    print(f"  {len(m)} completed player-seasons reconcile to player_week")


def test_player_year_change_columns():
    py = _sheet("player_year")
    if py is None:
        return True
    py = py.assign(_y=_num(py["Year"])).sort_values(["Player", "_y"])
    py = py[~py.duplicated(["Player", "Year"], keep=False)]
    adj = _num(py["Avg points (full season)" + _A])
    want = adj.groupby(py["Player"]).diff()
    # A season with no NFL game reads 0.0 on the sheet but has no average, so
    # its change is blank; compare where the base change exists.
    k = _num(py["Change in avg points from previous season"]).notna()
    bad = k & ~_close(py["Change in avg points from previous season" + _A], want, 2e-4)
    assert not bad.any(), f"{int(bad.sum())} rows: adjusted season-over-season change != diff of adjusted averages"
    # The career change is blank exactly where the base one is (same guards).
    for base in ("Change in avg points from previous season", "Change in avg points from career",
                 "Avg points (full season)"):
        assert (_num(py[base]).isna() == _num(py[base + _A]).isna()).all(), f"{base}: blanks disagree"


def test_all_time_pools_the_seasons():
    py, pa = _sheet("player_year"), _sheet("player_all_time")
    if py is None or pa is None:
        return True
    pa = pa[~pa["Player"].duplicated(keep=False)]
    py = py.assign(starts=_num(py["Weeks as starter"]), ros=_num(py["Weeks rostered"]),
                   hw=_num(py["Healthy weeks rostered"]))
    # Season sums reconstructed from each season's averages x their denominators.
    py["sp_f"] = (_num(py["PPG starter" + _A]) * py["starts"]).fillna(0.0)
    py["sp"] = _num(py["Total points as starter"]).fillna(0.0)
    s = py.groupby("Player")[["sp_f", "sp", "starts", "ros"]].sum()
    m = pa.set_index("Player").join(s, how="inner")
    assert len(m) > 300, f"only {len(m)} players to check"
    for col, want in (("PPG starter" + _A, m["sp_f"] / m["starts"].where(m["starts"] > 0)),
                      ("PPG starter per rostered week", m["sp"] / m["ros"].where(m["ros"] > 0))):
        bad = ~_close(m[col], want, 2e-3)
        assert not bad.any(), f"{col}: all-time != pooled seasons for {int(bad.sum())} players"


def test_blank_exactly_where_base_is():
    for name in ("player_year", "player_all_time", "player_additions", "add_drops", "trades"):
        df = _sheet(name)
        if df is None:
            continue
        for col in _NEW[name]:
            if not col.endswith(_A):
                continue
            base = df[col[:-len(_A)]]
            # "PPG of 5 games before pickup" is a text-kind column (its name
            # carries "pick"), so compare the parsed numbers.
            assert (_num(base).isna() == _num(df[col]).isna()).all(), f"{name}: {col} blank where its base is not"


def test_player_additions_grid():
    pa = _sheet("player_additions")
    if pa is None:
        return True
    ten, starts = _num(pa["Tenure (NFL weeks)"]), _num(pa["Number of starts before next drop"])
    games, hbench = _num(pa["Games played on team"]), _num(pa["Healthy bench weeks on team"])
    bench = _num(pa["Bench weeks on team"])
    added, benched = _num(pa["Points added"]), _num(pa["Bench points on team"])
    per = lambda a, b: (a / b.where(b > 0)).round(2)  # noqa: E731
    # The two sides of each ratio are rounded to 0.01 on the sheet.
    tol = 0.011
    ok = ten > 0
    for col, want in (("Avg points added per rostered week", per(added, ten)),
                      ("Avg points per rostered week on team", per(added + benched, ten)),
                      ("PPG bench on team", per(benched, bench))):
        bad = ok & ~_close(pa[col], want, tol + 0.01 * (1 / bench.where(bench > 0).fillna(1)))
        assert not bad.any(), f"{col}: {int(bad.sum())} rows disagree"
    # Healthy started / bench points are not on the sheet; a missed week scores
    # 0 (Injury? requires it; a bye has no game), so they equal the gross ones.
    hstarts = games - hbench
    for col, want in (("Adjusted Avg points added", per(added, hstarts)),
                      ("Adjusted Avg points added per rostered week", per(added, games)),
                      ("Adjusted PPG bench on team", per(benched, hbench))):
        bad = ok & ~_close(pa[col], want, 0.02)
        # A 0.0 fill on an empty denominator (the "Avg points added" convention).
        bad &= ~(_num(pa[col]).fillna(0).eq(0) & want.isna())
        assert not bad.any(), f"{col}: {int(bad.sum())} rows disagree"
    # Every twin on a row scales its base by ONE factor: the player's position
    # in the addition's Season (the factor the sheet's existing "... adjusted
    # by position" columns already apply), recomputed from player_week.
    pw = _read("player_week")
    w = _weekly(pw)
    fac, pos = _factors(w), w.groupby("Player")["Position"].first()
    f = pd.Series([fac.get((int(y), p), np.nan) if pd.notna(y) else np.nan
                   for y, p in zip(_num(pa["Season"]), pa["Player"].map(pos))], index=pa.index)
    base_on, adj_on = _num(pa["Avg PPG on team"]), _num(pa["Avg PPG on team adjusted by position"])
    k0 = f.notna() & (base_on >= 5)
    assert k0.sum() > 500, f"only {int(k0.sum())} rows to check the factor on"
    bad = k0 & ((adj_on - base_on * f).abs() > 0.006 + 0.005 * f)
    assert not bad.any(), f"'Avg PPG on team adjusted by position' disagrees with the recomputed factor on {int(bad.sum())} rows"
    for col in _NEW["player_additions"]:
        if not col.endswith(_A):
            continue
        b, a = _num(pa[col[:-len(_A)]]), _num(pa[col])
        k = f.notna() & b.notna() & (b.abs() >= 1)
        bad = k & ((a - b * f).abs() > 0.006 + 0.005 * f.abs())
        assert not bad.any(), f"{col}: {int(bad.sum())} rows use a different factor from 'Avg PPG on team'"


def test_difference_columns_split_into_their_twins():
    """add_drops / trades: the existing 'Difference of averages adjusted by
    position' is exactly the new received/added twin minus the sent/dropped
    twin (a missing side counts as 0)."""
    for name, a_col, b_col in (
            ("add_drops", "Average PPG on team" + _A, "Average PPG of dropped player over same time" + _A),
            ("trades", "Avg PPG of received players on team" + _A, "Avg PPG of sent players over same time" + _A)):
        df = _sheet(name)
        if df is None:
            continue
        a, b = _num(df[a_col]), _num(df[b_col])
        d = _num(df["Difference of averages adjusted by position"])
        # Pre-existing: a few add_drops rows keep a first-pass difference after
        # the final pass blanked BOTH of its sides (never rostered a week here;
        # e.g. K.J. Osborn, Oliverwkw 2023-01-11) — the unadjusted "Difference
        # of averages" carries the same stale value. Left out and counted.
        orphan = d.notna() & a.isna() & b.isna()
        if orphan.any():
            print(f"  NOTE {name}: {int(orphan.sum())} difference(s) with neither side on the sheet (pre-existing)")
        k = d.notna() & ~orphan
        bad = k & ((d - (a.fillna(0) - b.fillna(0))).abs() > 2e-4)
        assert not bad.any(), f"{name}: {int(bad.sum())} rows where the adjusted difference != its twins"


def test_add_drops_twins_use_each_players_factor():
    """add_drops scales each side by its own player's position in the move's
    season — the sheet's existing convention for 'Difference of averages
    adjusted by position': the calendar year of the move in UTC (the Date
    column shows league/Eastern time, so a New Year's Eve evening move is the
    next year's)."""
    ad, pw = _sheet("add_drops"), _read("player_week")
    if ad is None or pw is None:
        return True
    w = _weekly(pw)
    fac = _factors(w)
    pos = w.groupby("Player")["Position"].first()
    yr = (pd.to_datetime(ad["Date"], errors="coerce").dt.tz_localize(
        "America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC").dt.year)
    checked = 0
    for side, cols in (("Player Added", ("Average PPG on team", "PPG of 5 games before pickup")),
                       ("Player Dropped", ("Average PPG of dropped player over same time", "Dropped avg points"))):
        f = pd.Series([fac.get((int(y), p), np.nan) if pd.notna(y) else np.nan
                       for y, p in zip(yr, ad[side].map(pos))], index=ad.index)
        for col in cols:
            b, a = _num(ad[col]), _num(ad[col + _A])
            k = f.notna() & b.notna() & (b.abs() >= 1)
            # 5 games before pickup is rounded to 0.01 on the sheet; the rest to 1e-4.
            tol = 0.006 * (1 + f) if col.startswith("PPG of 5") else 2e-4 * (1 + f)
            bad = k & ((a - b * f).abs() > tol)
            assert not bad.any(), f"add_drops {col}{_A}: {int(bad.sum())} rows not base x the {side} factor"
            checked += int(k.sum())
    assert checked > 1000, f"only {checked} add_drops cells checked"


def test_player_week_twins():
    pw = _sheet("player_week")
    if pw is None:
        return True
    w = _weekly(pw)
    fac = _factors(w)
    f = pd.Series([fac.get((int(y), p), 1.0) if pd.notna(y) else np.nan
                   for y, p in zip(w["Year"], w["Position"])], index=pw.index)
    # Season-to-date tenure PPG: one season, one factor.
    base, adj = _num(pw["PPG as team starter this season"]), _num(pw["PPG as team starter adjusted by position this season"])
    assert (base.isna() == adj.isna()).all(), "tenure PPG twin blank where its base is not"
    bad = base.notna() & ((adj - base * f).abs() > 0.006 + 0.005 * f)
    assert not bad.any(), f"PPG as team starter this season: {int(bad.sum())} twins are not base x factor"
    # The 5-game start/sit difference: same-position calls scale by the factor.
    d, da = (_num(pw["Difference in averages of best/worst startables over previous 5 games"]),
             _num(pw["Difference in averages of best/worst startables over previous 5 games" + _A]))
    c, ca = _num(pw["Cuff adjusted difference"]), _num(pw["Cuff adjusted difference" + _A])
    assert (d.isna() == da.isna()).all() and (c.isna() == ca.isna()).all(), "5-game twins blank where base is not"
    pos_by_name = w.groupby("Player")["Position"].first()
    same = pw["Reference player name"].map(pos_by_name).eq(w["Position"]) & d.notna()
    assert same.sum() > 1000, f"only {int(same.sum())} same-position start/sit rows"
    bad = same & ((da - d * f).abs() > 0.006 + 0.005 * f)
    assert not bad.any(), f"5-game difference{_A}: {int(bad.sum())} same-position rows are not base x factor"
    # The cuff halving applies to the twin exactly as to the base: halved rows
    # halve it, every other row carries it unchanged.
    half = d.notna() & (c - d * 0.5).abs().le(0.006) & (d.abs() > 0.02)
    bad = half & ((ca - da * 0.5).abs() > 0.006)
    assert not bad.any(), f"Cuff adjusted difference{_A}: {int(bad.sum())} rows not halved like the base"
    whole = d.notna() & (c == d) & ~half
    bad = whole & (ca != da)
    assert not bad.any(), f"Cuff adjusted difference{_A}: {int(bad.sum())} unhalved rows differ from the difference"
    # Cross-position rows: the twin moves with the factor ratio — a start/sit
    # call between two players at one position cannot flip sign, and a twin
    # never exceeds the larger factor x (|base| + both 5-game averages' scale).
    fmax = max(fac.values())
    bad = d.notna() & (da.abs() > fmax * 100)
    assert not bad.any(), "5-game difference twin out of any plausible range"


if __name__ == "__main__":
    for fn in (test_player_year_recomputes_from_player_week, test_player_year_change_columns,
               test_all_time_pools_the_seasons, test_blank_exactly_where_base_is,
               test_player_additions_grid, test_difference_columns_split_into_their_twins,
               test_add_drops_twins_use_each_players_factor, test_player_week_twins):
        print(fn.__name__)
        fn()
    print("ok")
