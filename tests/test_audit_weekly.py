"""Phase 14: weekly automated audit tests.

Covers the three parts of scripts/audit_weekly.py on small synthetic exports:
completed-season immutability diffing (current-season rows exempt, past-season
changes flagged), schema-break detection against a pinned baseline, and the
build-log error scan (transient / current-season noise ignored, real errors
flagged). A final smoke test runs the audit against the real committed exports.

Run: PYTHONPATH=src:lib python tests/test_audit_weekly.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import audit_weekly as A  # noqa: E402


def _ok(name, cond, detail=""):
    # Detail only on failure — the diff checks below pass the whole rendered
    # report as their detail, which is what you want to read when one breaks
    # and pure noise when they all pass.
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or not detail else f" — {detail}"))
    return bool(cond)


def _write(directory: Path, name: str, df: pd.DataFrame):
    directory.mkdir(parents=True, exist_ok=True)
    df.to_csv(directory / f"{name}.csv", index=False)


def check_current_season_ignores_future_picks(tmp):
    cur = {
        "team_year": pd.DataFrame({"Team": ["A", "B"], "Year": ["2025", "2026"]}),
        # picks carry future draft years that must NOT be read as "current".
        "picks": pd.DataFrame({"Year": ["2026", "2027", "2031"], "Number": ["1.01", "1.02", "1.03"]}),
    }
    return _ok("current season from played sheets, not future picks",
              A._current_season(cur) == 2026, f"got {A._current_season(cur)}")


def check_diff_flags_past_change_exempts_current(tmp):
    base_dir, cur_dir = tmp / "base", tmp / "cur"
    base = pd.DataFrame({"Team": ["A", "A", "A"], "Year": ["2024", "2025", "2026"], "PF": ["100", "110", "50"]})
    _write(base_dir, "team_year", base)
    # Change a 2024 (historical) value AND a 2026 (current) value.
    cur = base.copy()
    cur.loc[0, "PF"] = "999"   # historical → must flag
    cur.loc[2, "PF"] = "80"    # current    → exempt
    _write(cur_dir, "team_year", cur)
    curf = {n: A._read(cur_dir, n) for n in A.SHEETS}
    basef = {n: A._read(base_dir, n) for n in A.SHEETS}
    rep = A.Report()
    A.audit_diffs(curf, basef, 2026, rep)
    text = rep.render()
    ok = _ok("historical 2024 change flagged", rep.confirmed == 1, f"confirmed={rep.confirmed}")
    ok &= _ok("report names team_year", "team_year" in text)
    ok &= _ok("current-season 2026 change NOT flagged", "999" not in text or "Year=2026" not in text)
    return ok


def check_diff_clean_when_identical(tmp):
    d1, d2 = tmp / "a", tmp / "b"
    df = pd.DataFrame({"Team": ["A"], "Year": ["2024"], "PF": ["100"]})
    _write(d1, "team_year", df)
    _write(d2, "team_year", df.copy())
    rep = A.Report()
    A.audit_diffs({n: A._read(d1, n) for n in A.SHEETS},
                  {n: A._read(d2, n) for n in A.SHEETS}, 2026, rep)
    return _ok("identical exports → no diff flag", rep.confirmed == 0)


def check_modified_row_names_the_column(tmp):
    """A modified historical row must be reported as ONE change naming the
    column and its old → new value — not as an unexplained removed+added pair
    with identical identifying keys, which is what the health email used to say
    (and which told the maintainer nothing about what actually moved)."""
    base_dir, cur_dir = tmp / "mbase", tmp / "mcur"
    base = pd.DataFrame({
        "Player": ["Jaylin Noel"] * 3,
        "Year": ["2025"] * 3, "Week": ["1", "2", "3"],
        "Points": ["1.7", "0.0", "1.4"], "Injury?": ["False"] * 3,
    })
    _write(base_dir, "player_week", base)
    cur = base.copy()
    cur["Injury?"] = ["True", "True", "True"]      # one column, three rows
    _write(cur_dir, "player_week", cur)
    rep = A.Report()
    A.audit_diffs({n: A._read(cur_dir, n) for n in A.SHEETS},
                  {n: A._read(base_dir, n) for n in A.SHEETS}, 2026, rep)
    text = rep.render()
    ok = _ok("one flag for the sheet", rep.confirmed == 1, f"confirmed={rep.confirmed}")
    ok &= _ok("counted as changed, not added/removed",
              "3 changed past-season row(s)" in text, text)
    ok &= _ok("no bogus added/removed halves",
              "added" not in text and "removed" not in text, text)
    ok &= _ok("rolls the moving column up", "columns that moved: Injury? (3)" in text, text)
    ok &= _ok("shows old → new per row",
              "Player=Jaylin Noel | Year=2025 | Week=1 — Injury?: False → True" in text, text)
    ok &= _ok("untouched columns are not reported", "Points" not in text, text)
    return ok


def check_genuine_add_and_remove_still_separate(tmp):
    """A row that really appeared / disappeared has no counterpart to pair with,
    so it must still be reported as an add / a remove."""
    base_dir, cur_dir = tmp / "abase", tmp / "acur"
    _write(base_dir, "team_year", pd.DataFrame(
        {"Team": ["A", "B"], "Year": ["2024", "2024"], "PF": ["100", "200"]}))
    _write(cur_dir, "team_year", pd.DataFrame(
        {"Team": ["A", "C"], "Year": ["2024", "2024"], "PF": ["100", "300"]}))
    rep = A.Report()
    A.audit_diffs({n: A._read(cur_dir, n) for n in A.SHEETS},
                  {n: A._read(base_dir, n) for n in A.SHEETS}, 2026, rep)
    text = rep.render()
    ok = _ok("counted as 1 added / 1 removed",
             "1 added, 1 removed past-season row(s)" in text, text)
    ok &= _ok("names the added row", "added:   Team=C | Year=2024" in text, text)
    ok &= _ok("names the removed row", "removed: Team=B | Year=2024" in text, text)
    ok &= _ok("no phantom 'changed'", "changed" not in text, text)
    return ok


def check_detail_budget_covers_every_class(tmp):
    """The line budget is shared across changed / added / removed, so a long run
    of one kind can't crowd the others out of the report entirely (it used to:
    25 removals left zero room for the adds, and the email then cut that to 15)."""
    base_dir, cur_dir = tmp / "bbase", tmp / "bcur"
    n = 40
    base = pd.DataFrame({"Team": [f"T{i}" for i in range(n)],
                         "Year": ["2024"] * n, "PF": [str(i) for i in range(n)]})
    _write(base_dir, "team_year", base)
    cur = base.copy()
    cur["PF"] = [str(i + 1) for i in range(n)]              # 40 changed rows
    cur.loc[len(cur)] = {"Team": "NEW", "Year": "2024", "PF": "1"}   # + 1 added
    _write(cur_dir, "team_year", cur)
    rep = A.Report()
    A.audit_diffs({n2: A._read(cur_dir, n2) for n2 in A.SHEETS},
                  {n2: A._read(base_dir, n2) for n2 in A.SHEETS}, 2026, rep)
    text = rep.render()
    ok = _ok("both classes counted", "40 changed, 1 added past-season row(s)" in text, text)
    ok &= _ok("the lone added row still shown", "added:   Team=NEW | Year=2024" in text, text)
    ok &= _ok("truncation is stated, not silent", "… and " in text, text)
    return ok


def check_schema_break_detection(tmp, monkeypatch_baseline):
    cur_dir = tmp / "schema"
    _write(cur_dir, "team_year", pd.DataFrame({"Team": ["A"], "Year": ["2024"]}))  # 'PF' dropped
    baseline = {"team_year": ["Team", "Year", "PF"]}
    bpath = tmp / "schema_baseline.json"
    bpath.write_text(json.dumps(baseline))
    orig = A._SCHEMA_BASELINE
    A._SCHEMA_BASELINE = bpath
    try:
        rep = A.Report()
        A.audit_schema({n: A._read(cur_dir, n) for n in A.SHEETS}, rep)
    finally:
        A._SCHEMA_BASELINE = orig
    return _ok("dropped column flagged as schema break", rep.confirmed == 1, f"confirmed={rep.confirmed}")


def check_build_log_scan(tmp):
    logs = tmp / "raw"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "build_debug.log").write_text(
        "[t] ===== Build start =====\n"
        "[t] ERROR at ktc: URLError: Tunnel connection failed: 403 Forbidden\n"  # transient
        "[t] ERROR seeding 2026 in-progress placeholder rows\n"                   # current-season
        "[t] ERROR at reconcile: ValueError: negative PF impossible\n"            # REAL → flag
        "[t] data-quality sanity: 0 ERROR, 0 WARN across 0 findings\n"
        "[t] ===== Build end =====\n")
    (logs / "pytest.log").write_text("=== 47 passed, 1 skipped in 3s ===\n")
    rep = A.Report()
    A.audit_build_log(logs, 2026, rep)
    text = rep.render()
    ok = _ok("real ValueError flagged", rep.confirmed == 1, f"confirmed={rep.confirmed}")
    ok &= _ok("transient + current-season ignored", "ignored 1 transient-network + 1 current-season" in text)
    ok &= _ok("passing pytest noted clean", "suite passing" in text)
    return ok


def check_build_log_sanity_errors(tmp):
    logs = tmp / "raw2"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "build_debug.log").write_text(
        "===== Build start =====\n"
        "data-quality sanity: 3 ERROR, 2 WARN across 5 findings\n"
        "===== Build end =====\n")
    rep = A.Report()
    A.audit_build_log(logs, 2026, rep)
    return _ok("data-quality ERROR count fails the run", rep.confirmed == 1, f"confirmed={rep.confirmed}")


def check_real_exports_smoke(tmp):
    exports = _ROOT / "exports"
    if not (exports / "team_year.csv").exists():
        print("  [SKIP] real-exports smoke — no build present")
        return True
    cur = {n: A._read(exports, n) for n in A.SHEETS}
    season = A._current_season(cur)
    ok = _ok("season detected from real exports", season is not None and season >= 2020, f"season={season}")

    # Schema drift is reported but NOT asserted here. exports/ is a committed
    # replay cache refreshed on a cadence, so it legitimately lags main's code
    # between refreshes — a PR that adds a column makes the committed CSVs miss
    # it until the next refresh lands, which is normal and must not turn the
    # suite red. (It did: #363 added 6 columns and this assertion failed every
    # run until exports caught up.) The teeth live where they belong — the
    # weekly workflow runs audit_schema against a FRESH build, where a missing
    # column really is a break.
    schema_rep = A.Report()
    A.audit_schema(cur, schema_rep)
    if schema_rep.confirmed:
        print(f"  [INFO] committed exports lag the pinned schema "
              f"({schema_rep.confirmed} difference(s)) — expected between refreshes.")

    rep = A.Report()
    A.audit_build_log(exports / "raw", season, rep)
    ok &= _ok("real committed build is error-clean", rep.confirmed == 0,
              f"confirmed={rep.confirmed}\n{rep.render()}")
    return ok


def check_volatile_columns_exempt(tmp):
    """Audit finding F1: link-index references, O-Score and league-baseline
    columns drift on EVERY rebuild, so a change there must not read as a
    historical-immutability break — while a real stat change still does."""
    ok = _ok("link/O-Score/skill/Luck columns classified volatile",
             all(A.is_volatile_column(c) for c in (
                 "Link to previous transaction", "Link to next transaction per asset",
                 "Link to previous transaction (dropped player)", "O-Score",
                 "Trading skill", "Luck", "Hardship", "Length of tenure on team")))
    ok &= _ok("real stats are NOT classified volatile",
              not any(A.is_volatile_column(c) for c in (
                  "PF", "Points against", "Win %", "Number of transactions", "Margin")))

    base_dir, cur_dir = tmp / "vbase", tmp / "vcur"
    base = pd.DataFrame({
        "Team": ["A", "A"], "Year": ["2024", "2025"],
        "PF": ["100", "110"], "O-Score": ["0.5", "0.6"],
        "Link to previous transaction": ["#12", "#40"],
    })
    _write(base_dir, "team_year", base)
    cur = base.copy()
    cur.loc[0, "O-Score"] = "0.9"                        # volatile → exempt
    cur.loc[0, "Link to previous transaction"] = "#13"   # volatile → exempt
    _write(cur_dir, "team_year", cur)
    rep = A.Report()
    A.audit_diffs({n: A._read(cur_dir, n) for n in A.SHEETS},
                  {n: A._read(base_dir, n) for n in A.SHEETS}, 2026, rep)
    ok &= _ok("volatile-only drift on a past row is not flagged",
              rep.confirmed == 0, f"confirmed={rep.confirmed}")

    cur.loc[0, "PF"] = "999"                             # real stat → must flag
    _write(cur_dir, "team_year", cur)
    rep2 = A.Report()
    A.audit_diffs({n: A._read(cur_dir, n) for n in A.SHEETS},
                  {n: A._read(base_dir, n) for n in A.SHEETS}, 2026, rep2)
    ok &= _ok("a real past-season stat change is still flagged",
              rep2.confirmed == 1, f"confirmed={rep2.confirmed}")
    return ok


def run_all() -> bool:
    import tempfile
    all_ok = True
    tests = [
        check_current_season_ignores_future_picks,
        check_diff_flags_past_change_exempts_current,
        check_diff_clean_when_identical,
        check_modified_row_names_the_column,
        check_genuine_add_and_remove_still_separate,
        check_detail_budget_covers_every_class,
        check_volatile_columns_exempt,
        lambda t: check_schema_break_detection(t, None),
        check_build_log_scan,
        check_build_log_sanity_errors,
        check_real_exports_smoke,
    ]
    for t in tests:
        name = getattr(t, "__name__", "check_schema_break_detection")
        print(f"\n{name}:")
        with tempfile.TemporaryDirectory() as d:
            all_ok &= bool(t(Path(d)))
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_audit_weekly():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
