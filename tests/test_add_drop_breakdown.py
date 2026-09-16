"""The Add/Drop breakdown must be a breakdown:

    Number of waiver adds + Number of free agency adds + Number of pure drops
        == Number of Add/Drops

on every frame that carries the four columns (league_week, league_year,
league_all_time, team_week, team_year, team_all_time). Three columns that do not
add up to the total they claim to split are not a breakdown of anything, and the
gap is invisible to a reader who does not think to sum them.

It held nowhere before this guard, in two independent ways:

  * **Season and all-time were 6 short.** The bucket test asked
    `type == "free_agent"`, so Sleeper's THIRD add type — `commissioner` — fell
    through into no bucket at all. Six adds across the league's history (five in
    2021, one in 2024) sat in the total and in none of the parts. A commissioner
    add is an acquisition that was not won on waivers, which is what the FA
    bucket counts, so it belongs there.
  * **Weekly was 199 over, and wrong.** `Number of Add/Drops` on team_week came
    from Sleeper's own `leg` on each transaction, while the three parts came from
    the build's league week clock (`_season_week_of`). Sleeper files every
    PRESEASON move under week 1, so 160 of the 199 were offseason moves piled
    into a week 1 row (2025 week 1 alone read 108 against a true 62); the rest
    was week-boundary drift, landing moves one week off in both directions.

So the weekly numbers are now written once, from the same rows and the same
clock as the parts. That makes two further properties true, and both are checked
here because they are what "the same rows" actually means:

  * every frame's Add/Drops total equals the number of rows in add_drops.csv
    that can reach it, and
  * a team-week's count equals the add_drops.csv rows dated into that week.

The identity is checked on EVERY row, in-progress seasons included: unlike the
immutability guards this is a within-build consistency property, so a current
season that does not balance is a defect today, not a season waiting to finish.

Reads the committed exports and SKIPS cleanly when they are absent.

Run: PYTHONPATH=src:lib python tests/test_add_drop_breakdown.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

import lotg  # noqa: E402

_TOTAL = "Number of Add/Drops"
_PARTS = ("Number of waiver adds", "Number of free agency adds", "Number of pure drops")
_FRAMES = ("league_week", "league_year", "league_all_time",
           "team_week", "team_year", "team_all_time")


def _exports() -> Path:
    return Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace({"N/A": None, "In Progress": None, "": None}),
                         errors="coerce").fillna(0.0)


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _label(frame: pd.DataFrame, i) -> str:
    bits = [str(frame.at[i, c]) for c in ("Team", "Year", "Week") if c in frame.columns]
    return "/".join(bits) or f"row {i}"


# The line the build logs once team_week's weekly counts are on the
# Tuesday-Monday week. Exports without it were built on the old Thursday clock,
# so the weekly checks below would fail for the right reason at the wrong time.
_TUESDAY_WEEK_MARKER = "on the Tuesday-Monday league week"


def _built_on_the_tuesday_week(d: Path) -> bool:
    try:
        return _TUESDAY_WEEK_MARKER in (d / "raw" / "build_debug.log").read_text(errors="replace")
    except Exception:
        return False


def check_the_parts_add_up_to_the_total() -> bool:
    d = _exports()
    ok = True
    for name in _FRAMES:
        path = d / f"{name}.csv"
        if not path.exists():
            print(f"  [SKIP] {name}.csv absent")
            continue
        df = pd.read_csv(path, low_memory=False)
        if not {_TOTAL, *_PARTS}.issubset(df.columns):
            print(f"  [SKIP] {name} does not carry all four columns")
            continue
        total = _num(df[_TOTAL])
        parts = sum(_num(df[c]) for c in _PARTS)
        bad = (total - parts).abs() > 1e-9
        # Over-inclusive: name the first few offenders and both numbers, so a
        # failure says which rows to open rather than only how many.
        detail = f"{int(bad.sum())}/{len(df)} rows off"
        if bad.any():
            shown = [f"{_label(df, i)}: total {total[i]:.0f} vs parts {parts[i]:.0f}"
                     for i in list(df.index[bad])[:6]]
            detail += " — " + "; ".join(shown)
            if int(bad.sum()) > 6:
                detail += f"; … and {int(bad.sum()) - 6} more"
        ok &= _ok(f"{name}: waiver + FA + drops == Add/Drops", not bad.any(), detail)
    return ok


def check_the_totals_match_the_detail_sheet() -> bool:
    """add_drops.csv is the row-level source of truth; the rollups count its rows.

    Each frame is held to the rows it can actually reach, not to the whole sheet:
    an all-time frame reaches every row, a season frame only the seasons it has
    (league_year carries no row for a season with no played weeks yet, while
    team_year does), and team_week only the rows dated into a week the sheet
    actually has — an offseason move has no weekly bucket by design. Spelling
    each reach out is the point: assuming they are all equal is what let the
    weekly frames drift 199 rows from the detail sheet unnoticed.
    """
    d = _exports()
    ad_path = d / "add_drops.csv"
    if not ad_path.exists():
        print("  [SKIP] no add_drops.csv")
        return True
    ad = pd.read_csv(ad_path, low_memory=False)
    ad_season = pd.to_numeric(ad["Season"], errors="coerce")
    ok = True

    for name in ("team_year", "team_all_time", "league_year", "league_all_time"):
        path = d / f"{name}.csv"
        if not path.exists():
            print(f"  [SKIP] {name}.csv absent")
            continue
        frame = pd.read_csv(path, low_memory=False)
        if "Year" in frame.columns:
            years = set(pd.to_numeric(frame["Year"], errors="coerce").dropna())
            want = int(ad_season.isin(years).sum())
            reach = f"seasons {min(years):.0f}-{max(years):.0f}" if years else "no seasons"
        else:
            want, reach = len(ad), "every season"
        got = int(_num(frame[_TOTAL]).sum())
        ok &= _ok(f"{name} counts the add_drops rows it reaches ({reach})",
                  got == want, f"{got} vs {want}")

    if not _built_on_the_tuesday_week(d):
        print("  [SKIP] team_week: these exports predate the Tuesday-Monday week "
              f"(no {_TUESDAY_WEEK_MARKER!r} in raw/build_debug.log)")
        return ok
    tw_path, ad_ok = d / "team_week.csv", "Date" in ad.columns
    if not tw_path.exists() or not ad_ok:
        print("  [SKIP] no team_week.csv / no Date column")
        return ok
    tw = pd.read_csv(tw_path, low_memory=False)
    tw["Year"] = pd.to_numeric(tw["Year"], errors="coerce")
    tw["Week"] = pd.to_numeric(tw["Week"], errors="coerce")
    keys = set(zip(tw["Team"].astype(str), tw["Year"], tw["Week"]))

    when = pd.to_datetime(ad["Date"], errors="coerce")
    season = pd.to_numeric(ad["Season"], errors="coerce")
    expect: dict = {}
    for team, w, s in zip(ad["Team"].astype(str), when, season):
        if pd.isna(w) or pd.isna(s):
            continue
        wk = lotg._season_week_of(w.date(), int(s))
        if not wk:
            continue                       # offseason: no weekly bucket, by design
        key = (team, float(s), float(wk))
        if key in keys:                    # a week the sheet actually has
            expect[key] = expect.get(key, 0) + 1

    got = {(str(t), y, w): int(v) for t, y, w, v in
           zip(tw["Team"], tw["Year"], tw["Week"], _num(tw[_TOTAL])) if v}
    ok &= _ok("team_week totals equal the add_drops rows dated into each week",
              got == expect,
              f"{sum(got.values())} credited vs {sum(expect.values())} expected; "
              f"{len({k for k in set(got) | set(expect) if got.get(k) != expect.get(k)})} "
              "team-week(s) differ")
    return ok


def check_every_detail_row_lands_in_exactly_one_bucket() -> bool:
    """The classifier's own precondition. A row with neither an added nor a
    dropped player would balance the identity while belonging in no bucket, so
    the guard above could not see it — this is where it would show up."""
    d = _exports()
    path = d / "add_drops.csv"
    if not path.exists():
        print("  [SKIP] no add_drops.csv")
        return True
    ad = pd.read_csv(path, low_memory=False)
    added = ad["Player Added"].astype(str).str.strip().replace({"nan": "", "None": ""})
    dropped = ad["Player Dropped"].astype(str).str.strip().replace({"nan": "", "None": ""})
    neither = (added == "") & (dropped == "")
    ok = _ok("no row is neither an add nor a drop", not neither.any(),
             f"{int(neither.sum())} row(s)")
    # And every add carries a type the classifier can read, so the waiver/FA
    # split is a real split rather than "waiver, or everything else".
    tcol = "type of add/drop (waiver/free agency)"
    if tcol in ad.columns:
        kinds = set(ad.loc[added != "", tcol].astype(str).str.strip().unique())
        known = {"waiver", "free_agent", "commissioner"}
        ok &= _ok("every add's type is one the build knows", kinds <= known,
                  f"unexpected: {sorted(kinds - known)}" if kinds - known
                  else f"{sorted(kinds)}")
    return ok


def check_team_week_trades_match_the_trades_sheet() -> bool:
    """team_week's trade count is the trades.csv rows dated into that week, on the
    same Tuesday-Monday week as the add/drops beside it. It used to come from
    Sleeper's `leg`, which rolls over partway through a Wednesday: 98 team-weeks
    disagreed with the trade dates, and Quiet streak read two clocks at once."""
    d = _exports()
    tw_path, tr_path = d / "team_week.csv", d / "trades.csv"
    if not tw_path.exists() or not tr_path.exists():
        print("  [SKIP] no team_week.csv / trades.csv")
        return True
    if not _built_on_the_tuesday_week(d):
        print("  [SKIP] these exports predate the Tuesday-Monday week")
        return True
    tw = pd.read_csv(tw_path, low_memory=False)
    tr = pd.read_csv(tr_path, low_memory=False)
    if "Number of trades" not in tw.columns or not {"Date", "Season", "Team"} <= set(tr.columns):
        print("  [SKIP] no Number of trades / trade Date")
        return True
    tw["Year"] = pd.to_numeric(tw["Year"], errors="coerce")
    tw["Week"] = pd.to_numeric(tw["Week"], errors="coerce")
    keys = set(zip(tw["Team"].astype(str), tw["Year"], tw["Week"]))
    when = pd.to_datetime(tr["Date"], errors="coerce")
    season = pd.to_numeric(tr["Season"], errors="coerce")
    expect: dict = {}
    for team, w, s in zip(tr["Team"].astype(str), when, season):
        if pd.isna(w) or pd.isna(s):
            continue
        wk = lotg._season_week_of(w.date(), int(s))
        if not wk:
            continue
        key = (team, float(s), float(wk))
        if key in keys:
            expect[key] = expect.get(key, 0) + 1
    got = {(str(t), y, w): int(v) for t, y, w, v in
           zip(tw["Team"], tw["Year"], tw["Week"], _num(tw["Number of trades"])) if v}
    diff = {k for k in set(got) | set(expect) if got.get(k) != expect.get(k)}
    return _ok("team_week trades equal the trades.csv rows dated into each week",
               not diff, f"{sum(got.values())} credited vs {sum(expect.values())} expected; "
               f"{len(diff)} team-week(s) differ: {sorted(diff)[:6]}")


# The line the build logs once team_week's FAAB is on the Tuesday-Monday week too.
_FAAB_WEEK_MARKER = "Amount of FAAB spent rebuilt from add_drop_rows"


def check_team_week_faab_matches_the_add_drops_sheet() -> bool:
    """team_week's "Amount of FAAB spent" is the Faab on the add_drops.csv rows
    dated into that week — the same rows and week as its Add/Drops count.

    It used to follow Sleeper's `leg`, which files every offseason move under week
    1, so January waivers sat in the week 1 row (2026: AceMatthew $45 against $44
    of week-1 bids, stevenb123 $11 against $8; six team-weeks 2023-2026) and ~160
    team-weeks sat a week off. A claim the commissioner reversed and add_drops
    dropped (Oliverwkw's $1 Jerome Ford, 2023-09-04) was still counted weekly."""
    d = _exports()
    tw_path, ad_path = d / "team_week.csv", d / "add_drops.csv"
    if not tw_path.exists() or not ad_path.exists():
        print("  [SKIP] no team_week.csv / add_drops.csv")
        return True
    try:
        built = _FAAB_WEEK_MARKER in (d / "raw" / "build_debug.log").read_text(errors="replace")
    except Exception:
        built = False
    if not built:
        print(f"  [SKIP] these exports predate weekly FAAB on the Tuesday-Monday week "
              f"(no {_FAAB_WEEK_MARKER!r} in raw/build_debug.log)")
        return True
    tw = pd.read_csv(tw_path, low_memory=False)
    ad = pd.read_csv(ad_path, low_memory=False)
    col = "Amount of FAAB spent"
    tw["Year"] = pd.to_numeric(tw["Year"], errors="coerce")
    tw["Week"] = pd.to_numeric(tw["Week"], errors="coerce")
    keys = set(zip(tw["Team"].astype(str), tw["Year"], tw["Week"]))
    when = pd.to_datetime(ad["Date"], errors="coerce")
    season = pd.to_numeric(ad["Season"], errors="coerce")
    faab = pd.to_numeric(ad["Faab"], errors="coerce").fillna(0.0)
    expect: dict = {}
    for team, w, s, f in zip(ad["Team"].astype(str), when, season, faab):
        if pd.isna(w) or pd.isna(s) or not f:
            continue
        wk = lotg._season_week_of(w.date(), int(s))
        key = (team, float(s), float(wk))
        if wk and key in keys:
            expect[key] = round(expect.get(key, 0.0) + float(f), 2)
    got = {(str(t), y, w): round(float(v), 2) for t, y, w, v in
           zip(tw["Team"], tw["Year"], tw["Week"], _num(tw[col])) if v}
    diff = sorted(k for k in set(got) | set(expect)
                  if abs(got.get(k, 0.0) - expect.get(k, 0.0)) > 1e-6)
    return _ok("team_week FAAB equals the add_drops Faab dated into each week",
               not diff, f"${sum(got.values()):.0f} credited vs ${sum(expect.values()):.0f} "
               f"expected; {len(diff)} team-week(s) differ: "
               f"{[(k, got.get(k), expect.get(k)) for k in diff[:6]]}")


def run_all() -> bool:
    if not (_exports() / "team_year.csv").exists():
        print("no exports/ — SKIP")
        return True
    all_ok = True
    for t in (check_the_parts_add_up_to_the_total,
              check_the_totals_match_the_detail_sheet,
              check_every_detail_row_lands_in_exactly_one_bucket,
              check_team_week_trades_match_the_trades_sheet,
              check_team_week_faab_matches_the_add_drops_sheet):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_add_drop_breakdown():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
