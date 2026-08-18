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
    """The volume check asks whether attribution out-reaches the revision behind
    it, not whether upstream had a busy week. A fixed ceiling on our attributed
    rows made every large-but-fully-explained release an alarm — which is the
    2026-08-05 email's whole complaint."""
    before = _write_cache(tmp / "vb", _BASE_STATS)
    after_rows = [r[:] for r in _BASE_STATS]
    after_rows[0][4] = 23
    after = _write_cache(tmp / "va", after_rows)
    d = N.diff_nflverse_cache(before, after)     # 1 revised row upstream
    ok = _ok("a handful of attributed rows is routine",
             d.is_significant(N.MAX_ATTRIBUTED_ROWS) is None)
    ok &= _ok("attribution out-reaching the revision is flagged",
              "reaching further" in (d.is_significant(N.MAX_ATTRIBUTED_ROWS + 1) or ""),
              str(d.is_significant(N.MAX_ATTRIBUTED_ROWS + 1)))

    # A big upstream release that our exports merely follow stays informational,
    # however many of our rows moved with it.
    big = N.Drift(compared=True)
    big.files.append(N.FileDrift(name="nflverse_stats_player_week_2025.csv",
                                 changed_cells=18678, changed_rows=12382))
    ok &= _ok("a large release our rows only follow is not escalated",
              big.is_significant(2954) is None, str(big.is_significant(2954)))
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
              "2 row(s) moved because NFLverse revised" in text
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
    ok &= _ok("reported as added", "1 added row(s) moved" in text, text)
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


# --- the channels a revision reaches our exports through -------------------
# The 2026-08-05 email reported 2015 past-season rows as breakages on a week
# whose only cause was upstream drift, because attribution could only match a
# revision to the exact (player, season, week) it landed on. These cover the
# three wider spans, and the line each one must not cross.
def check_name_suffixes_do_not_break_attribution(tmp):
    """NFLverse ships "Calvin Austin III"; Sleeper (our exports) says "Calvin
    Austin". Matching those with == excluded ~6% of the league from
    attribution, so their upstream revisions read as our build breaking."""
    ok = _ok("suffixes fold away",
             N.normalize_name("Calvin Austin III") == N.normalize_name("Calvin Austin"))
    ok &= _ok("so do accents",
              N.normalize_name("Audric Estimé") == N.normalize_name("Audric Estime"))
    ok &= _ok("and initials, via the space-free variant",
              bool(N.name_variants("P.J. Walker") & N.name_variants("PJ Walker")))
    ok &= _ok("distinct players stay distinct",
              N.normalize_name("Josh Allen") != N.normalize_name("Keenan Allen"))

    base_py = pd.DataFrame({"Player": ["Calvin Austin", "Deebo Samuel"],
                            "Year": ["2023", "2023"],
                            "Points (full season)": ["60.60", "185.30"]})
    cur_py = base_py.copy()
    cur_py.loc[0, "Points (full season)"] = "60.40"
    cur_py.loc[1, "Points (full season)"] = "185.20"
    pw = pd.DataFrame({"Player": ["Calvin Austin"], "Team": ["T"],
                       "Year": ["2023"], "Week": ["1"]})
    drift = N.Drift(compared=True)
    drift.player_seasons |= {("Calvin Austin III", 2023), ("Deebo Samuel Sr.", 2023)}
    rep, attributed = _audit(tmp / "s", cur_py, pw, base_py, pw, drift)
    ok &= _ok("both suffixed players are attributed", attributed == 2,
              f"attributed={attributed}\n{rep.render()}")
    ok &= _ok("so nothing is flagged", rep.confirmed == 0, rep.render())
    return ok


def check_alltime_pool_columns_follow_a_position_relabel(tmp):
    """"Positional scoring percentile" places a score in the pooled distribution
    of EVERY active starter score ever recorded at that position, so one
    relabelled position re-seats the whole file — including seasons and players
    upstream never touched. 1596 such rows were flagged as breakages."""
    base_pw = pd.DataFrame({
        "Player": ["Cooper Kupp", "Derrick Henry"], "Team": ["T", "T"],
        "Year": ["2020", "2021"], "Week": ["5", "9"],
        "Positional scoring percentile": ["80.5", "46.7"]})
    cur_pw = base_pw.copy()
    cur_pw["Positional scoring percentile"] = ["80.4", "46.6"]
    py = pd.DataFrame({"Player": ["Cooper Kupp"], "Year": ["2020"], "Points": ["1"]})

    drift = N.Drift(compared=True)
    drift.pools_disturbed = True        # a position label moved upstream
    rep, attributed = _audit(tmp / "p", py, cur_pw, py, base_pw, drift)
    ok = _ok("the pool move explains both rows", attributed == 2,
             f"attributed={attributed}\n{rep.render()}")
    ok &= _ok("nothing is flagged", rep.confirmed == 0, rep.render())

    # ... but only that column. An ordinary stat moving on the same row is not
    # something a repooling can account for.
    cur2 = base_pw.copy()
    cur2["Positional scoring percentile"] = ["80.4", "46.6"]
    cur2["Points"] = ["9.9", "9.9"]
    base2 = base_pw.copy()
    base2["Points"] = ["1.0", "1.0"]
    rep2, attributed2 = _audit(tmp / "p2", py, cur2, py, base2, drift)
    ok &= _ok("an unexplained column keeps the row flagged", rep2.confirmed == 1,
              rep2.render())
    ok &= _ok("and nothing is withheld", attributed2 == 0, f"attributed={attributed2}")
    return ok


def check_season_pool_columns_are_scoped_to_their_season(tmp):
    """The positional adjustment factor and the PAR replacement level are built
    WITHIN a season, so a 2023 revision excuses a 2023 row and no other."""
    base_pk = pd.DataFrame({
        "Year": ["2023", "2021"], "Number": ["1.01", "1.01"],
        "Player Picked": ["Bijan Robinson", "Kyle Pitts"],
        "Avg career PPG adjusted by position": ["13.42", "9.10"]})
    cur_pk = base_pk.copy()
    cur_pk["Avg career PPG adjusted by position"] = ["13.41", "9.09"]
    pw = pd.DataFrame({"Player": ["X"], "Team": ["T"], "Year": ["2023"], "Week": ["1"]})

    drift = N.Drift(compared=True)
    drift.pools_disturbed = True
    drift.pool_seasons.add(2023)

    cur_d, base_d = tmp / "sc", tmp / "sb"
    for d, pk in ((cur_d, cur_pk), (base_d, base_pk)):
        d.mkdir(parents=True, exist_ok=True)
        pk.to_csv(d / "picks.csv", index=False)
        pw.to_csv(d / "player_week.csv", index=False)
    cur = {n: A._read(cur_d, n) for n in A.SHEETS}
    base = {n: A._read(base_d, n) for n in A.SHEETS}
    rep = A.Report()
    attributed = A.audit_diffs(cur, base, 2026, rep, A.NflverseAttribution(drift, cur))
    text = rep.render()
    ok = _ok("the revised season's pick is withheld", "Bijan Robinson" not in text, text)
    ok &= _ok("an untouched season's is still flagged", "Kyle Pitts" in text, text)
    ok &= _ok("one row attributed", attributed == 1, f"attributed={attributed}")
    return ok


def check_career_columns_follow_an_earlier_seasons_revision(tmp):
    """"Change in points from career" reads every season BEFORE the row's, so a
    2022 correction moves the 2023 row. Season-pinned attribution missed all of
    them and reported the carry-over as historical data coming unfrozen."""
    base_py = pd.DataFrame({
        "Player": ["Bailey Zappe", "Jake Browning"], "Year": ["2023", "2024"],
        "Change in points from career": ["29.34", "-141.74"]})
    cur_py = base_py.copy()
    cur_py["Change in points from career"] = ["30.14", "-141.64"]
    pw = pd.DataFrame({"Player": ["Bailey Zappe"], "Team": ["T"],
                       "Year": ["2022"], "Week": ["1"]})

    drift = N.Drift(compared=True)          # both revised in an EARLIER season
    drift.player_seasons |= {("Bailey Zappe", 2022), ("Jake Browning", 2023)}
    rep, attributed = _audit(tmp / "c", cur_py, pw, base_py, pw, drift)
    ok = _ok("the carry-over is attributed", attributed == 2,
             f"attributed={attributed}\n{rep.render()}")
    ok &= _ok("nothing flagged", rep.confirmed == 0, rep.render())

    # A player upstream never touched at all is still a breakage.
    base2 = pd.DataFrame({"Player": ["Derrick Henry"], "Year": ["2023"],
                          "Change in points from career": ["10.0"]})
    cur2 = base2.copy()
    cur2.loc[0, "Change in points from career"] = "99.0"
    rep2, attributed2 = _audit(tmp / "c2", cur2, pw, base2, pw, drift)
    ok &= _ok("an untouched player is still flagged", rep2.confirmed == 1, rep2.render())
    ok &= _ok("and not attributed", attributed2 == 0, f"attributed={attributed2}")
    return ok


def check_current_season_roster_churn_is_not_significant(tmp):
    """The in-progress season's weekly roster file gains rows every time somebody
    is signed. That is not "games appearing or disappearing" — escalating it is
    how a quiet August week led with a red flag."""
    d = N.Drift(compared=True)
    d.files.append(N.FileDrift(name="nflverse_weekly_rosters_2026.csv",
                               changed_cells=4416, changed_rows=699, added_rows=17))
    ok = _ok("routine in-progress-season roster churn is not escalated",
             d.is_significant(0, current_season=2026) is None,
             str(d.is_significant(0, current_season=2026)))
    ok &= _ok("a COMPLETED season gaining rows still is",
              "added / withdrew" in (d.is_significant(0, current_season=2027) or ""),
              str(d.is_significant(0, current_season=2027)))
    ok &= _ok("and with no season known, the old behaviour holds",
              "added / withdrew" in (d.is_significant(0) or ""), str(d.is_significant(0)))
    ok &= _ok("the file's season is read off its name",
              d.files[0].season == 2026, str(d.files[0].season))
    return ok


def check_pool_columns_track_the_builds_scoring_inputs(_tmp):
    """POOL_COLUMNS decides whether a revision counts as re-seating the league
    pools, so it has to stay in step with the columns the build actually turns
    into points (`lotg._LEAGUE_SCORE_MAP` / `_LEAGUE_SCORE_BONUS`)."""
    import ast
    src = ast.parse((_ROOT / "src" / "lotg.py").read_text())
    scoring = set()
    for node in ast.walk(src):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "_LEAGUE_SCORE_MAP" in names:
            for v in ast.literal_eval(node.value).values():
                scoring.update(v)
        elif "_LEAGUE_SCORE_BONUS" in names:
            for _k, col, _thr in ast.literal_eval(node.value):
                scoring.add(col)
    missing = sorted(scoring - N.POOL_COLUMNS)
    ok = _ok("every scoring input is pool-relevant", not missing, f"missing={missing}")
    ok &= _ok("so is the position label", {"position", "position_group"} <= N.POOL_COLUMNS)
    return ok


def check_trade_chain_columns_are_build_volatile(_tmp):
    """Chain-of-custody columns answer "where did these assets end up" as of
    TODAY, so any new trade rewrites them on every deal the assets descend from.
    One 2026-08 trade rewrote three 2024-25 trade rows. Their fixed-fact
    siblings must stay under the immutability check."""
    from lotg_support.volatile_columns import is_volatile_column as vol
    volatile = ["Assets retained now", "Assets traded away", "Assets dropped to FA",
                "Return from trades", "Additional assets traded away in those deals",
                "Return from trades of trades...of trades. Keep going until present day"]
    frozen = ["Assets received", "Assets sent", "Number of assets traded away",
              "Number of assets received", "Total number of assets in trade"]
    ok = _ok("chain-of-custody columns are volatile",
             all(vol(c) for c in volatile), str([c for c in volatile if not vol(c)]))
    ok &= _ok("the deal's own contents and counts are not",
              not any(vol(c) for c in frozen), str([c for c in frozen if vol(c)]))
    return ok


# --- the 2026-08-12 email: what folding alone could not reach ---------------
def check_nflverse_alias_table_bridges_sleeper_spellings(tmp):
    """Some players are spelled differently upstream in a way no folding fixes.
    NFLverse publishes the other spellings itself, in nflverse_player_ids.csv —
    display_name "Bam Knight" carries football_name "Zonovan"; "Nyheim Hines"
    carries short_name "N.Miller-Hines". Both are what our exports say."""
    d = tmp / "al"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"gsis_id": "00-0037157", "display_name": "Bam Knight", "first_name": "Bam",
         "common_first_name": "Bam", "football_name": "Zonovan",
         "last_name": "Knight", "short_name": "Z.Knight"},
        {"gsis_id": "00-0034367", "display_name": "Nyheim Hines", "first_name": "Nyheim",
         "common_first_name": "Nyheim", "football_name": "Nyheim",
         "last_name": "Hines", "short_name": "N.Miller-Hines"},
        {"gsis_id": "00-0039901", "display_name": "Kimani Vidal", "first_name": "Kimani",
         "common_first_name": "Kimani", "football_name": "Kimani",
         "last_name": "Vidal", "short_name": "K.Vidal"},
    ]).to_csv(d / "nflverse_player_ids.csv", index=False)

    al = N.load_name_aliases(d)
    ok = _ok("Sleeper's 'Zonovan Knight' reaches upstream's 'Bam Knight'",
             bool(N.name_variants("Zonovan Knight") & al["00-0037157"]))
    ok &= _ok("and 'Nyheim Miller-Hines' reaches 'Nyheim Hines'",
              bool(N.name_variants("Nyheim Miller-Hines") & al["00-0034367"]))
    ok &= _ok("the published spelling still matches too",
              bool(N.name_variants("Bam Knight") & al["00-0037157"]))
    ok &= _ok("a pick label's short form resolves",
              bool(N.name_variants("K. Vidal") & al["00-0039901"]))
    ok &= _ok("no alias file -> empty table, not a crash", N.load_name_aliases(tmp / "nope") == {})

    # End to end: the stats file prints "Bam Knight", our export says "Zonovan
    # Knight", and the row must still be attributed.
    stats = pd.DataFrame([["00-0037157", "Bam Knight", 2022, 5, 24, 0]],
                         columns=["player_id", "player_display_name", "season",
                                  "week", "receiving_yards", "rushing_first_downs"])
    nb, na = tmp / "nb", tmp / "na"
    for p, yards in ((nb, 24), (na, 23)):
        p.mkdir(parents=True, exist_ok=True)
        s = stats.copy(); s.loc[0, "receiving_yards"] = yards
        s.to_csv(p / "nflverse_stats_player_week_2022.csv", index=False)
    (na / "nflverse_player_ids.csv").write_text((d / "nflverse_player_ids.csv").read_text())
    drift = N.diff_nflverse_cache(nb, na)

    base_py = pd.DataFrame({"Player": ["Zonovan Knight"], "Year": ["2022"],
                            "Points (full season)": ["57.10"]})
    cur_py = base_py.copy(); cur_py.loc[0, "Points (full season)"] = "57.00"
    pw = pd.DataFrame({"Player": ["Zonovan Knight"], "Team": ["T"],
                       "Year": ["2022"], "Week": ["5"]})
    rep, attributed = _audit(tmp / "e2e", cur_py, pw, base_py, pw, drift)
    ok &= _ok("the Sleeper-spelled row is attributed", attributed == 1,
              f"attributed={attributed}\n{rep.render()}")
    ok &= _ok("and not flagged", rep.confirmed == 0, rep.render())
    return ok


def check_traded_picks_name_the_player_they_became(tmp):
    """A trade of nothing but draft picks writes its players as "2024 4.06(K.
    Vidal)". The PPG columns are computed from those players, but the asset
    string folds to nothing a name can match, so 11 such trades were flagged."""
    ok = _ok("the pick's player is pulled out of the label",
             bool(A.NflverseAttribution._names_in("2024 4.06(K. Vidal)")
                  & N.name_variants("K. Vidal")))
    ok &= _ok("plain players still work",
              bool(A.NflverseAttribution._names_in("Mike Gesicki; Allen Lazard")
                   & N.name_variants("Allen Lazard")))

    base_tr = pd.DataFrame({
        "Team": ["BROsenzweig", "LWebs53"], "Team's traded with 1": ["shmuel256", "x"],
        "Date": ["2024-07-13 18:51:36", "2024-01-01 00:00:00"], "Season": ["2024", "2024"],
        "Assets received": ["2024 4.06(K. Vidal)", "2024 4.09(Q. Nobody)"],
        "Assets sent": ["2024 4.07(T. Tracy)", "2024 4.10(Z. Nobody)"],
        "Avg PPG of received players on team": ["6.7826", "1.0"]})
    cur_tr = base_tr.copy()
    cur_tr["Avg PPG of received players on team"] = ["6.8261", "1.5"]
    pw = pd.DataFrame({"Player": ["Kimani Vidal"], "Team": ["T"],
                       "Year": ["2024"], "Week": ["1"]})

    drift = N.Drift(compared=True)
    drift.players |= N.name_variants("K. Vidal") | N.name_variants("T. Tracy")

    cur_d, base_d = tmp / "tc", tmp / "tb"
    for dd, tr in ((cur_d, cur_tr), (base_d, base_tr)):
        dd.mkdir(parents=True, exist_ok=True)
        tr.to_csv(dd / "trades.csv", index=False)
        pw.to_csv(dd / "player_week.csv", index=False)
    cur = {n: A._read(cur_d, n) for n in A.SHEETS}
    base = {n: A._read(base_d, n) for n in A.SHEETS}
    rep = A.Report()
    attributed = A.audit_diffs(cur, base, 2026, rep, A.NflverseAttribution(drift, cur))
    text = rep.render()
    ok &= _ok("the revised pick's trade is withheld", "BROsenzweig" not in text, text)
    ok &= _ok("a trade of picks upstream never touched still flags", "LWebs53" in text, text)
    ok &= _ok("one row attributed", attributed == 1, f"attributed={attributed}")
    return ok


def check_added_columns_are_a_stale_pin_not_a_breakage(_tmp):
    """Three sheets came back red for "columns reordered" because a feature PR
    added 8 columns mid-sheet and the pin hadn't caught up. Nothing was lost —
    that is a pin to refresh, not history coming unfrozen. A real shuffle, and
    a column actually going missing, still flag."""
    pinned = ["A", "B", "C", "D"]
    ok = _ok("inserting new columns keeps the pinned order",
             A._only_insertions(["A", "NEW", "B", "C", "D2", "D"], pinned))
    ok &= _ok("swapping two pinned columns does not",
              not A._only_insertions(["B", "A", "C", "D"], pinned))
    ok &= _ok("a dropped pinned column does not",
              not A._only_insertions(["A", "B", "D"], pinned))

    import json, tempfile, pathlib
    # audit_schema reads a column-only frame as a missing sheet, so give each
    # one a row — otherwise every case below "passes" for the wrong reason.
    def sheet(cols):
        return pd.DataFrame([{c: "1" for c in cols}], columns=cols)

    real = A._SCHEMA_BASELINE
    tmpf = pathlib.Path(tempfile.mkdtemp()) / "schema.json"
    tmpf.write_text(json.dumps({"team_year": pinned}))
    A._SCHEMA_BASELINE = tmpf
    try:
        rep = A.Report()
        A.audit_schema({"team_year": sheet(["A", "B", "NEW", "C", "D"])}, rep)
        # A column that is not in the pin is a change to the shape of what we
        # ship. The audit cannot tell a feature PR from an accident, so it says
        # so and the pin is refreshed deliberately rather than by default.
        ok &= _ok("an insertion is flagged, naming the column and the fix",
                  rep.confirmed == 1 and "NEW" in rep.render()
                  and "--update-schema" in rep.render(), rep.render())
        ok &= _ok("and says to re-pin", "--update-schema" in rep.render(), rep.render())

        rep2 = A.Report()
        A.audit_schema({"team_year": sheet(["B", "A", "C", "D"])}, rep2)
        ok &= _ok("a genuine reorder still flags", rep2.confirmed == 1, rep2.render())
        ok &= _ok("and says so", "reordered" in rep2.render(), rep2.render())

        rep3 = A.Report()
        A.audit_schema({"team_year": sheet(["A", "B", "C"])}, rep3)
        ok &= _ok("a missing column still flags", rep3.confirmed == 1, rep3.render())
        ok &= _ok("naming what is gone", "column(s) gone" in rep3.render(), rep3.render())
    finally:
        A._SCHEMA_BASELINE = real
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
        check_name_suffixes_do_not_break_attribution,
        check_alltime_pool_columns_follow_a_position_relabel,
        check_season_pool_columns_are_scoped_to_their_season,
        check_career_columns_follow_an_earlier_seasons_revision,
        check_current_season_roster_churn_is_not_significant,
        check_pool_columns_track_the_builds_scoring_inputs,
        check_trade_chain_columns_are_build_volatile,
        check_nflverse_alias_table_bridges_sleeper_spellings,
        check_traded_picks_name_the_player_they_became,
        check_added_columns_are_a_stale_pin_not_a_breakage,
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
