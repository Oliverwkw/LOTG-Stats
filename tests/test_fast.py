"""Fast stat checks: `lotg_support.fast` counts / ranks and `lotg_support.live`.

The fast path is only worth having if its numbers are the build's numbers, so
every check here reconciles against an export column:

- a snapshot week shaped by `live.build` reproduces player_week `Points` and
  starter/bench roles row for row, and team_week `PF` (no semifinal week);
- `count_over(entering=...)`'s margin equals team_week "Margin entering SNF"
  and "Margin entering Monday" on every team-week (N/A included);
- `count_over` agrees with a direct groupby, and a week fed in as "live" gives
  the same counts and margins as the same week read from the exports.

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


TESTS = [
    test_place_ranks_and_ties,
    test_stage_aliases,
    test_live_build_reproduces_the_export_week,
    test_stage_margin_matches_the_build_columns,
    test_count_over_matches_a_direct_groupby,
    test_a_week_fed_as_live_agrees_with_the_exports,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall fast checks passed")
