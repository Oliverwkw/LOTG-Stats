"""Fast stat checks: `lotg_support.fast` counts / ranks and `lotg_support.live`.

The fast path is only worth having if its numbers are the build's numbers, so
every check here reconciles against an export column:

- a snapshot week shaped by `live.build` reproduces player_week `Points` and
  starter/bench roles row for row, and team_week `PF` (no semifinal week);
- `count_over(entering=...)`'s margin equals team_week "Margin entering SNF"
  and "Margin entering Monday" on every team-week (N/A included);
- `count_over` agrees with a direct groupby, and a week fed in as "live" gives
  the same counts and margins as the same week read from the exports;
- the acquisition columns cover every finished row and reproduce the
  "Waiver share vs win %" inquiry (2026-10-15), and `corr`'s p-values are
  scipy's (t-distribution) without scipy.

No network: the live code is exercised through the committed snapshot. Only
completed seasons are asserted against. Skips cleanly without `exports/`.

Run: python tests/test_fast.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import fast, inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "team_week.csv").exists()
_HAVE_SNAPSHOT = (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()
_HAVE_SCHEDULE = (_ROOT / ".cache" / "nfldata_games.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _season() -> int:
    return max(s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot)


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_place_ranks_and_ties():
    h = pd.Series([6, 5, 5, 4, 1])
    assert fast.place(h, 7) == (1, 0, 5)
    assert fast.place(h, 6) == (1, 1, 5)
    assert fast.place(h, 5) == (2, 2, 5)
    assert fast.place(h, 2, higher_is_better=False) == (2, 0, 5)


def test_stage_aliases():
    assert fast.stage_name("late") == "Sunday late"
    assert fast.stage_name("MNF") == "Monday"
    assert fast.stage_name("SNF") == "SNF"
    assert fast.stage_name("Sunday early") == "Sunday early"


# ---------------------------------------------------------------------------
# Against the committed data
# ---------------------------------------------------------------------------
def test_live_build_reproduces_the_export_week():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT) and _skip("no exports/snapshot"):
        return
    from lotg_support import live
    season = _season()
    pw = fast.player_weeks()
    tw = Q.load_sheet("team_week")
    checked = 0
    for wk in (3, 5, 9):
        names = tw[(tw["Year"] == str(season)) & (tw["Week"] == str(wk))]
        if names.empty or names["Week Name"].iloc[0] == "Semifinal":
            continue
        lw = live.fetch(season, wk, source="snapshot")
        ex = pw[(pw["Year"] == season) & (pw["Week"] == wk)]
        exp = {(t, p): (round(x, 2), sb) for t, p, x, sb in
               zip(ex["Team"], ex["Player"], ex["Points"], ex["Starter/Bench"])}
        got = {(t, p): (round(x, 2), sb) for t, p, x, sb in
               zip(lw.player_week["Team"], lw.player_week["Player"], lw.player_week["Points"],
                   lw.player_week["Starter/Bench"])}
        common = set(exp) & set(got)
        # Sleeper lists a move completed after the week as part of it; the build
        # takes it back off (late listings) — those rows may differ, nothing else.
        assert len(common) >= 0.97 * len(exp), (season, wk, len(common), len(exp))
        diffs = [k for k in common if exp[k] != got[k]]
        assert not diffs, (season, wk, diffs[:5])
        pf = dict(zip(names["Team"], pd.to_numeric(names["PF"])))
        for t, v in zip(lw.team_week["Team"], lw.team_week["PF"]):
            assert abs(pf[t] - v) < 0.011, (season, wk, t, pf[t], v)
        checked += 1
    assert checked >= 2


def test_stage_margin_matches_the_build_columns():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE) and _skip("no exports/schedule"):
        return
    tw = Q.load_sheet("team_week")
    done = set(Q.completed_seasons())
    for stage, col in (("SNF", "Margin entering SNF"), ("Monday", "Margin entering Monday")):
        c = fast.count_over(18, entering=stage)
        c = c[c["Year"].isin(done)]
        ref = tw[["Team", "Year", "Week", col]].copy()
        ref["Year"] = pd.to_numeric(ref["Year"]).astype("Int64")
        ref["Week"] = pd.to_numeric(ref["Week"]).astype("Int64")
        ref = ref[ref["Year"].isin(done)]
        ref["ref"] = pd.to_numeric(ref[col], errors="coerce")
        m = ref.merge(c[["Team", "Year", "Week", "Margin"]], on=["Team", "Year", "Week"], how="left")
        both_na = m["ref"].isna() & m["Margin"].isna()
        close = (m["ref"] - m["Margin"]).abs() < 0.011
        bad = m[~(both_na | close)]
        assert bad.empty, (stage, len(bad), bad.head().to_dict("records"))


def test_count_over_matches_a_direct_groupby():
    if not _HAVE_EXPORTS and _skip("no exports"):
        return
    done = Q.completed_seasons()
    c = fast.count_over(18, result="loss", years=done)
    pw = fast.player_weeks()
    pw = pw[pw["Year"].isin(done)]
    st = pw[pw["Starter/Bench"] == "Starter"]
    direct = st[st["Points"] > 18].groupby(["Team", "Year", "Week"]).size()
    lost = st[~st["Win?"] & (st["Margin"] != 0)].drop_duplicates(["Team", "Year", "Week"])
    expect = direct.reindex(pd.MultiIndex.from_frame(lost[["Team", "Year", "Week"]])).fillna(0).astype(int)
    got = c.set_index(["Team", "Year", "Week"])["n"]
    assert len(got) == len(expect)
    assert (got.reindex(expect.index) == expect).all()
    # strict vs >=: the only difference is the rows at exactly the line
    ge = fast.count_over(18, result="loss", years=done, strict=False).set_index(["Team", "Year", "Week"])
    g = c.set_index(["Team", "Year", "Week"])
    assert ((ge["n"] - g["n"].reindex(ge.index)) == ge["at_threshold"]).all()


def test_a_week_fed_as_live_agrees_with_the_exports():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT and _HAVE_SCHEDULE) and _skip("no exports/snapshot/schedule"):
        return
    from lotg_support import live
    season = _season()
    wk = 5
    lw = live.fetch(season, wk, source="snapshot")
    a = fast.count_over(18, entering="Sunday late", years=[season])
    a = a[a["Week"] == wk].set_index("Team")
    b = fast.count_over(18, entering="Sunday late", live=lw)
    b = b[b["Live"]].set_index("Team")
    assert set(a.index) == set(b.index)
    # snapshot mode slots each player by the exports' NFL team for that week
    # (live mode uses his current team), so the two must agree exactly
    n_diff = (a["n"] != b["n"].reindex(a.index)).sum()
    m_diff = ((a["Margin"] - b["Margin"].reindex(a.index)).abs() > 0.011).sum()
    assert n_diff == 0 and m_diff == 0, (n_diff, m_diff)


def test_slot_count_matches_a_direct_groupby():
    if not _HAVE_EXPORTS and _skip("no exports"):
        return
    assert fast.slot_name("monday") == "MNF" and fast.slot_name("late") == "Sunday late"
    c = fast.count_over(float("-inf"), slots=["Monday"])
    pw = fast.player_weeks()
    st = pw[(pw["Starter/Bench"] == "Starter") & (pw["Game slot"] == "MNF")]
    direct = st.groupby(["Team", "Year", "Week"]).size()
    got = c.set_index(["Team", "Year", "Week"])["n"]
    assert (got.reindex(direct.index) == direct).all()
    assert int(got.sum()) == len(st)


def test_typed_sheet_keeps_every_value():
    if not _HAVE_EXPORTS and _skip("no exports"):
        return
    raw = Q.load_sheet("team_week")
    t = fast.typed_sheet("team_week")
    assert list(t.columns) == list(raw.columns) and len(t) == len(raw)
    for col in ("PF", "Margin entering Monday", "Players over 20 pts (starters)"):
        assert pd.api.types.is_numeric_dtype(t[col]), col
        ref = pd.to_numeric(raw[col], errors="coerce")
        assert ((ref - t[col]).abs().fillna(0) < 1e-9).all() and (ref.isna() == t[col].isna()).all(), col
    assert t["Win?"].dtype == bool
    assert not fast.find_columns("margin entering monday").empty


def test_q_runs_statements_and_sees_frames_inside_lambdas():
    if not _HAVE_EXPORTS and _skip("no exports"):
        return
    import contextlib
    import io
    import runpy
    cli = runpy.run_path(str(_ROOT / "scripts" / "fast.py"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli["main"](["q", "x = 2; (lambda: int(twt.PF.notna().sum()) * 0 + x)()"])
    assert buf.getvalue().strip() == "2"


# ---------------------------------------------------------------------------
# Acquisition columns and corr (the "waiver share vs win %" inquiry)
# ---------------------------------------------------------------------------
def test_t_pvalue_and_corr_match_reference_values():
    # scipy.stats.t.sf(2.0, 10) * 2 = 0.073388; t = 0 gives 1
    assert abs(fast.t_pvalue(2.0, 10) - 0.0733880) < 1e-6
    assert abs(fast.t_pvalue(0.0, 30) - 1.0) < 1e-12
    assert abs(fast.betainc(2, 3, 0.4) - 0.5248) < 1e-9
    import numpy as np
    rng = np.random.default_rng(1)
    z = rng.normal(size=300)
    x = z + rng.normal(size=300)
    y = z + rng.normal(size=300)
    x, y, z = (pd.Series(v) for v in (x, y, z))
    raw = fast.corr(x, y).iloc[0]
    assert abs(raw.pearson - np.corrcoef(x, y)[0, 1]) < 5e-4 and raw.p < 1e-6
    assert abs(raw.spearman - np.corrcoef(x.rank(), y.rank())[0, 1]) < 5e-4
    part = fast.corr(x, y, control=z.rename("z")).iloc[0]       # the shared cause removed
    assert abs(part.pearson) < 0.15 and part.controls == "z"
    half = fast.corr(x, y, where=pd.Series(np.arange(300) < 150)).iloc[0]
    assert half.n == 150


def test_acquisition_columns_cover_every_finished_row():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE) and _skip("no exports/schedule"):
        return
    pw = fast.player_weeks()
    done = pw[pw["Year"].isin(Q.completed_seasons())]
    assert done["Acquired via"].isin(["Waiver", "Free agency", "Trade", "Draft", "Commissioner"]).all(), \
        done["Acquired via"].value_counts()
    assert (done.loc[done["Week"] == 1, "Season source"] == "Week-1 roster").all()
    picked = done["In-season pickup"]
    assert (done.loc[picked, "Week"] > 1).all()
    assert done.loc[picked, "Acquired via"].isin(fast.PICKUP_TYPES).all()
    # the stint began no later than the week it is used in
    assert (pd.to_datetime(done["Acquired"]).dt.year <= done["Year"].astype(int) + 1).all()


def test_live_rows_get_the_same_acquisition_columns():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT and _HAVE_SCHEDULE) and _skip("no exports/snapshot/schedule"):
        return
    from lotg_support import live
    season, wk = _season(), 5
    lw = live.fetch(season, wk, source="snapshot")
    keys = ["Player", "Team"]
    a = fast.player_weeks()
    a = a[(a["Year"] == season) & (a["Week"] == wk)].set_index(keys)
    b = fast.player_weeks(lw)
    b = b[b["Live"]].set_index(keys)
    common = a.index.intersection(b.index)
    assert len(common) > 0.95 * len(a)
    for c in ("Acquired via", "Season source", "In-season pickup"):
        assert (a.loc[common, c] == b.loc[common, c]).all(), c


def test_waiver_share_reconciles_with_the_waiver_inquiry():
    """The 2026-10-15 "Waiver share vs win %" thread, 40 team-seasons 2021-25,
    regular season. Its in-season-pickup numbers reproduce exactly. Its
    current-stint join placed weeks at week-1 Thursday + 7(N-1), so a player
    added Friday-Monday and started that week matched his PREVIOUS stint;
    the columns here match every row (the build's Tuesday-Monday week rule
    gives the same labels row for row), which moves those r by <= 0.025."""
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE) and _skip("no exports/schedule"):
        return
    if not set(range(2021, 2026)) <= set(Q.completed_seasons()) and _skip("2021-25 not all complete"):
        return
    yrs = range(2021, 2026)
    pw = fast.player_weeks()
    ts = fast.team_seasons()
    new = fast.starter_share("In-season pickup", years=yrs)
    orig = fast.starter_share(pw["Acquired via"].isin(fast.PICKUP_TYPES), years=yrs)
    assert len(new) == len(orig) == 40
    by_year = new.groupby(level="Year").mean()
    assert 0.0165 <= by_year.min() and by_year.max() <= 0.0405, by_year   # "1.7-4.0%"
    win, ap = ts["Regular season win %"], ts["Regular season all-play win %"]

    def r(x, y, **kw):
        return fast.corr(x, y, **kw).iloc[0]

    near = lambda got, want, tol=0.03: abs(got - want) <= tol    # noqa: E731
    assert near(r(new, win).pearson, -0.01, 0.01) and near(r(new, win).p, 0.94, 0.02)
    assert near(r(new, ap).pearson, -0.09, 0.01) and near(r(new, ap).p, 0.57, 0.02)
    assert near(r(orig, win).pearson, -0.31) and near(r(orig, win).spearman, -0.29)
    assert near(r(orig, ap).pearson, -0.54) and r(orig, ap).p < 0.001
    assert near(r(orig, ts["Tanking"]).pearson, 0.48)
    keep = ts["Tanking"] < 0.5
    assert r(orig, win, where=keep).n == 31
    assert near(r(orig, win, where=keep).pearson, 0.00) and near(r(orig, ap, where=keep).pearson, -0.29)
    assert near(r(orig, win, control=ts["Tanking"]).pearson, 0.07)
    assert near(r(orig, ap, control=ts["Tanking"]).pearson, -0.29)


def test_q_has_corr_share_and_team_seasons():
    if not (_HAVE_EXPORTS and _HAVE_SCHEDULE) and _skip("no exports/schedule"):
        return
    import contextlib
    import io
    import runpy
    cli = runpy.run_path(str(_ROOT / "scripts" / "fast.py"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli["main"](["q", "corr(share('In-season pickup', years=range(2021, 2026)), ts['Regular season win %'])"])
    out = buf.getvalue()
    assert "pearson" in out and " 40 " in out, out


TESTS = [
    test_place_ranks_and_ties,
    test_stage_aliases,
    test_live_build_reproduces_the_export_week,
    test_stage_margin_matches_the_build_columns,
    test_count_over_matches_a_direct_groupby,
    test_a_week_fed_as_live_agrees_with_the_exports,
    test_slot_count_matches_a_direct_groupby,
    test_typed_sheet_keeps_every_value,
    test_q_runs_statements_and_sees_frames_inside_lambdas,
    test_t_pvalue_and_corr_match_reference_values,
    test_acquisition_columns_cover_every_finished_row,
    test_live_rows_get_the_same_acquisition_columns,
    test_waiver_share_reconciles_with_the_waiver_inquiry,
    test_q_has_corr_share_and_team_seasons,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall fast checks passed")
