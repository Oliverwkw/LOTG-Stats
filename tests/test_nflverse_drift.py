"""NFLverse upstream drift: measure it, report it, don't call it a breakage.

NFLverse back-corrects completed seasons. Those revisions used to surface as
Part 1 "historical data is not supposed to change" flags — true statements about
rows that moved, but nothing our build could fix. These tests cover the split:

  * lotg_support.nflverse_drift diffs two cache snapshots and summarises them
  * audit_weekly attributes its own past-season diffs to that drift and reports
    them instead of flagging them
  * a change upstream cannot explain is still flagged
  * structural drift (rows/columns/files moving) and drift that has moved an
    unreasonable share of our exports DO get flagged

Run: PYTHONPATH=src:lib python tests/test_nflverse_drift.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import audit_weekly as A                       # noqa: E402
from lotg_support import nflverse_drift as N    # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or not detail else f" — {detail}"))
    return bool(cond)


def _stats(rows):
    return pd.DataFrame(rows, columns=["player_id", "player_display_name", "season",
                                       "week", "receiving_yards", "rushing_first_downs"])


_BASE_STATS = [
    ["1", "Cooper Kupp", 2025, 13, 24, 0],
    ["2", "Jaylin Noel", 2025, 17, 54, 1],
    ["3", "Derrick Henry", 2023, 6, 12, 8],
]


def _write_cache(d: Path, rows) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    _stats(rows).to_csv(d / "nflverse_stats_player_week_2025.csv", index=False)
    return d


def check_diff_finds_and_locates_revisions(tmp):
    before = _write_cache(tmp / "nb", _BASE_STATS)
    after_rows = [r[:] for r in _BASE_STATS]
    after_rows[0][4] = 23          # Kupp week 13 receiving yards revised
    after_rows[1][5] = 0           # Noel week 17 rushing first down withdrawn
    after = _write_cache(tmp / "na", after_rows)

    d = N.diff_nflverse_cache(before, after)
    ok = _ok("compared", d.compared)
    ok &= _ok("counts the revised values", d.changed_cells == 2, f"cells={d.changed_cells}")
    ok &= _ok("counts the revised rows", d.changed_rows == 2, f"rows={d.changed_rows}")
    ok &= _ok("summary reads as 'NFLverse made N changes'",
              d.summary().startswith("NFLverse made 2 value(s) across 2 row(s)"), d.summary())
    ok &= _ok("locates Kupp's revised week", ("Cooper Kupp", 2025, 13) in d.player_weeks)
    ok &= _ok("locates Noel's revised week", ("Jaylin Noel", 2025, 17) in d.player_weeks)
    ok &= _ok("leaves untouched players alone",
              ("Derrick Henry", 2023) not in d.player_seasons)
    ok &= _ok("routine revisions are not significant",
              d.is_significant(attributed_rows=2) is None, str(d.is_significant(2)))
    return ok


def check_no_change_reads_clean(tmp):
    before = _write_cache(tmp / "cb", _BASE_STATS)
    after = _write_cache(tmp / "ca", [r[:] for r in _BASE_STATS])
    d = N.diff_nflverse_cache(before, after)
    ok = _ok("no drift detected", not d.any_change)
    ok &= _ok("says so plainly", "no changes" in d.summary(), d.summary())
    return ok


def check_missing_snapshot_is_not_a_finding(tmp):
    d = N.diff_nflverse_cache(None, tmp / "nowhere")
    ok = _ok("nothing to compare -> compared is False", d.compared is False)
    ok &= _ok("not treated as drift", not d.any_change)
    ok &= _ok("never significant", d.is_significant(attributed_rows=10_000) is None)
    return ok


def check_structural_drift_is_significant(tmp):
    before = _write_cache(tmp / "sb", _BASE_STATS)
    after_rows = [r[:] for r in _BASE_STATS] + [["4", "New Guy", 2025, 3, 10, 0]]
    after = _write_cache(tmp / "sa", after_rows)
    d = N.diff_nflverse_cache(before, after)
    ok = _ok("an added row is structural", d.structural)
    ok &= _ok("and is flagged", "added / withdrew" in (d.is_significant(0) or ""),
              str(d.is_significant(0)))

    # A dropped column is worse: the build may be reading it.
    d2f = tmp / "sc"
    d2f.mkdir(parents=True, exist_ok=True)
    _stats(_BASE_STATS).drop(columns=["rushing_first_downs"]).to_csv(
        d2f / "nflverse_stats_player_week_2025.csv", index=False)
    d2 = N.diff_nflverse_cache(before, d2f)
    ok &= _ok("a dropped column is flagged",
              "dropped" in (d2.is_significant(0) or ""), str(d2.is_significant(0)))
    return ok


def check_volume_threshold_is_significant(tmp):
    before = _write_cache(tmp / "vb", _BASE_STATS)
    after_rows = [r[:] for r in _BASE_STATS]
    after_rows[0][4] = 23
    after = _write_cache(tmp / "va", after_rows)
    d = N.diff_nflverse_cache(before, after)
    ok = _ok("under the threshold stays informational",
             d.is_significant(N.MAX_ATTRIBUTED_ROWS) is None)
    ok &= _ok("over the threshold is flagged",
              "threshold" in (d.is_significant(N.MAX_ATTRIBUTED_ROWS + 1) or ""),
              str(d.is_significant(N.MAX_ATTRIBUTED_ROWS + 1)))
    return ok


# --- attribution inside the audit -----------------------------------------
def _exports(d: Path, py: pd.DataFrame, pw: pd.DataFrame) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    py.to_csv(d / "player_year.csv", index=False)
    pw.to_csv(d / "player_week.csv", index=False)
    return d


def _audit(tmp, cur_py, cur_pw, base_py, base_pw, drift):
    cur_d = _exports(tmp / "cur", cur_py, cur_pw)
    base_d = _exports(tmp / "base", base_py, base_pw)
    cur = {n: A._read(cur_d, n) for n in A.SHEETS}
    base = {n: A._read(base_d, n) for n in A.SHEETS}
    rep = A.Report()
    attributed = A.audit_diffs(cur, base, 2026, rep, A.NflverseAttribution(drift, cur))
    return rep, attributed


def check_audit_withholds_attributable_rows(tmp):
    """The 2026-07-29 email in miniature: two players whose past-season rows
    moved only because NFLverse revised them, plus one that upstream cannot
    account for. Only the last one is a breakage."""
    base_py = pd.DataFrame({
        "Player": ["Cooper Kupp", "Jaylin Noel", "Derrick Henry"],
        "Year": ["2025", "2025", "2023"],
        "Points (full season)": ["153.10", "68.40", "300.00"],
    })
    cur_py = base_py.copy()
    cur_py.loc[0, "Points (full season)"] = "153.00"   # NFLverse revision
    cur_py.loc[1, "Points (full season)"] = "68.30"    # NFLverse revision
    cur_py.loc[2, "Points (full season)"] = "999.00"   # ours — must flag
    pw = pd.DataFrame({"Player": ["Cooper Kupp"], "Team": ["BROsenzweig"],
                       "Year": ["2025"], "Week": ["1"]})

    drift = N.Drift(compared=True)
    drift.player_seasons |= {("Cooper Kupp", 2025), ("Jaylin Noel", 2025)}
    drift.player_weeks |= {("Cooper Kupp", 2025, 13), ("Jaylin Noel", 2025, 17)}

    rep, attributed = _audit(tmp / "w", cur_py, pw, base_py, pw, drift)
    text = rep.render()
    ok = _ok("only the unexplained row is a breakage", rep.confirmed == 1,
             f"confirmed={rep.confirmed}\n{text}")
    ok &= _ok("and it is named", "Derrick Henry" in text, text)
    ok &= _ok("the attributable rows are withheld",
              "Cooper Kupp" not in text and "Jaylin Noel" not in text, text)
    ok &= _ok("but counted", attributed == 2, f"attributed={attributed}")
    ok &= _ok("and reported, with the column",
              "2 past-season row(s) moved because NFLverse revised" in text
              and "Points (full season) (2)" in text, text)
    return ok


def check_no_drift_means_everything_still_flags(tmp):
    """With no NFLverse drift to attribute to, behaviour is unchanged."""
    base_py = pd.DataFrame({"Player": ["Cooper Kupp"], "Year": ["2025"],
                            "Points (full season)": ["153.10"]})
    cur_py = base_py.copy()
    cur_py.loc[0, "Points (full season)"] = "153.00"
    pw = pd.DataFrame({"Player": ["Cooper Kupp"], "Team": ["T"], "Year": ["2025"], "Week": ["1"]})
    rep, attributed = _audit(tmp / "n", cur_py, pw, base_py, pw, N.Drift())
    text = rep.render()
    ok = _ok("flagged", rep.confirmed == 1, f"confirmed={rep.confirmed}")
    ok &= _ok("nothing attributed", attributed == 0)
    ok &= _ok("shows the delta", "153.10 → 153.00" in text, text)
    return ok


def check_downstream_rows_follow_the_player(tmp):
    """A team/league row has no player on it, so it is attributed through the
    roster: the revised player was on that team that week."""
    pw = pd.DataFrame({"Player": ["Jaylin Noel"], "Team": ["plehv79"],
                       "Year": ["2025"], "Week": ["17"]})
    base_tw = pd.DataFrame({"Team": ["plehv79", "LWebs53"], "Year": ["2025", "2025"],
                            "Week": ["17", "17"], "Number of donuts": ["3", "1"]})
    cur_tw = base_tw.copy()
    cur_tw.loc[0, "Number of donuts"] = "2"    # plehv79 — reachable from Noel
    cur_tw.loc[1, "Number of donuts"] = "5"    # LWebs53 — not

    drift = N.Drift(compared=True)
    drift.player_seasons.add(("Jaylin Noel", 2025))
    drift.player_weeks.add(("Jaylin Noel", 2025, 17))

    cur_d, base_d = tmp / "dc", tmp / "db"
    for d, tw in ((cur_d, cur_tw), (base_d, base_tw)):
        d.mkdir(parents=True, exist_ok=True)
        tw.to_csv(d / "team_week.csv", index=False)
        pw.to_csv(d / "player_week.csv", index=False)
    cur = {n: A._read(cur_d, n) for n in A.SHEETS}
    base = {n: A._read(base_d, n) for n in A.SHEETS}
    rep = A.Report()
    attributed = A.audit_diffs(cur, base, 2026, rep, A.NflverseAttribution(drift, cur))
    text = rep.render()
    ok = _ok("the revised player's team-week is withheld", "plehv79" not in text, text)
    ok &= _ok("another team's is still flagged", "LWebs53" in text, text)
    ok &= _ok("one row attributed", attributed == 1, f"attributed={attributed}")
    return ok


def check_added_removed_rows_are_never_attributed(tmp):
    """Roster membership comes from Sleeper, so upstream can never add or remove
    one of our rows — those stay flagged even for a revised player."""
    base_py = pd.DataFrame({"Player": ["Cooper Kupp"], "Year": ["2025"], "Points": ["10"]})
    cur_py = pd.DataFrame({"Player": ["Cooper Kupp", "Cooper Kupp"],
                           "Year": ["2025", "2024"], "Points": ["10", "5"]})
    pw = pd.DataFrame({"Player": ["Cooper Kupp"], "Team": ["T"], "Year": ["2025"], "Week": ["1"]})
    drift = N.Drift(compared=True)
    drift.player_seasons |= {("Cooper Kupp", 2025), ("Cooper Kupp", 2024)}
    rep, attributed = _audit(tmp / "ar", cur_py, pw, base_py, pw, drift)
    text = rep.render()
    ok = _ok("the added row is still flagged", rep.confirmed == 1, f"{rep.confirmed}\n{text}")
    ok &= _ok("reported as added", "1 added past-season row(s)" in text, text)
    ok &= _ok("nothing attributed", attributed == 0, f"attributed={attributed}")
    return ok


def check_significant_drift_flags_in_the_report(tmp):
    drift = N.Drift(compared=True)
    drift.missing_files = ["nflverse_stats_player_week_2024.csv"]
    rep = A.Report()
    A.audit_nflverse(drift, 0, rep)
    ok = _ok("a vanished upstream file is a confirmed problem", rep.confirmed == 1,
             f"confirmed={rep.confirmed}")

    routine = N.Drift(compared=True)
    routine.files.append(N.FileDrift(name="f.csv", changed_cells=9, changed_rows=4))
    rep2 = A.Report()
    A.audit_nflverse(routine, 4, rep2)
    ok &= _ok("routine drift is informational", rep2.confirmed == 0)
    ok &= _ok("and still says what changed",
              "NFLverse made 9 value(s) across 4 row(s)" in rep2.render(), rep2.render())
    return ok


def run_all() -> bool:
    all_ok = True
    tests = [
        check_diff_finds_and_locates_revisions,
        check_no_change_reads_clean,
        check_missing_snapshot_is_not_a_finding,
        check_structural_drift_is_significant,
        check_volume_threshold_is_significant,
        check_audit_withholds_attributable_rows,
        check_no_drift_means_everything_still_flags,
        check_downstream_rows_follow_the_player,
        check_added_removed_rows_are_never_attributed,
        lambda _t: check_significant_drift_flags_in_the_report(_t),
    ]
    with tempfile.TemporaryDirectory() as d:
        for i, t in enumerate(tests):
            print(f"\n{getattr(t, '__name__', 'check_significant_drift_flags_in_the_report')}:")
            all_ok &= bool(t(Path(d) / f"t{i}"))
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_nflverse_drift():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
