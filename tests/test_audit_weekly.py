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
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
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
    rep = A.Report()
    A.audit_schema(cur, rep)          # against the committed baseline
    A.audit_build_log(exports / "raw", season, rep)
    ok &= _ok("real committed build is schema-clean + error-clean", rep.confirmed == 0,
              f"confirmed={rep.confirmed}\n{rep.render()}")
    return ok


def run_all() -> bool:
    import tempfile
    all_ok = True
    tests = [
        check_current_season_ignores_future_picks,
        check_diff_flags_past_change_exempts_current,
        check_diff_clean_when_identical,
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
