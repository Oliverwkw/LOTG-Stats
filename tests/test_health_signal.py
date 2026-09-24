"""Guards for the weekly health email's own signal (2026-09-23 follow-up).

That week's email reported "2 failing tests" and nothing else, while:
  * a gzip body cached under a .csv name crashed the snap-count injury guard
    before it reached 2025, and was silently skipped by the NFLverse drift diff;
  * eight tests that never ran reported PASSED (a skip helper returning True);
  * a Pandas4Warning from our own code sat in every build log.
Each check below pins one of those shut. No network, no exports needed.

Run: PYTHONPATH=src:lib:scripts python tests/test_health_signal.py
"""
from __future__ import annotations

import gzip
import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "lib", _ROOT / "src", _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_CSV = b"season,week,pfr_player_id,offense_snaps\n2025,1,AbcdEf00,40\n"


def test_a_gzip_body_is_cached_as_plain_csv():
    from lotg_support.external import _as_cached_bytes

    body = gzip.compress(_CSV)
    assert _as_cached_bytes(body, Path("nflverse_snap_counts_2025.csv")) == _CSV
    # A target that IS a .gz keeps the compressed bytes it asked for.
    assert _as_cached_bytes(body, Path("x.csv.gz")) == body
    assert _as_cached_bytes(_CSV, Path("x.csv")) == _CSV


def test_a_gzip_bodied_csv_already_on_disk_still_reads():
    from lotg_support.external import read_cached_csv

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "nflverse_snap_counts_2025.csv"
        p.write_bytes(gzip.compress(_CSV))
        assert read_cached_csv(p)["offense_snaps"].tolist() == [40]
        p.write_bytes(_CSV)
        assert read_cached_csv(p)["offense_snaps"].tolist() == [40]


def test_an_unreadable_nflverse_file_is_reported_not_skipped():
    from lotg_support.nflverse_drift import diff_nflverse_cache

    with tempfile.TemporaryDirectory() as d:
        before, after = Path(d) / "b", Path(d) / "a"
        before.mkdir()
        after.mkdir()
        (before / "nflverse_snap_counts_2025.csv").write_bytes(_CSV)
        (after / "nflverse_snap_counts_2025.csv").write_bytes(b"\xff\xfe\x00garbage\x00")
        drift = diff_nflverse_cache(before, after)
        assert drift.unreadable_files, "the unreadable file vanished from the report"
        assert drift.any_change, "an unmeasured file must not read as 'no changes'"
        assert "could not be read" in (drift.is_significant(0) or "")


def _results(tmp: Path, results, complete=True) -> Path:
    raw = tmp / "raw"
    raw.mkdir(exist_ok=True)
    blob = {"exitstatus": 0, "results": results}
    if complete:
        blob["complete"] = True
    (raw / "pytest_results.json").write_text(json.dumps(blob))
    return raw / "pytest.log"


def test_an_unexpected_skip_is_a_flag_and_an_expected_one_a_note():
    import audit_weekly as A

    with tempfile.TemporaryDirectory() as d:
        log = _results(Path(d), [
            {"test": "tests/test_a.py::test_x", "outcome": "passed", "reason": ""},
            {"test": "tests/test_contracts.py::test_big", "outcome": "skipped",
             "reason": "needs the cached nflverse contracts file"},
            {"test": "tests/test_forecast.py::test_an_unsigned_player_cannot_score",
             "outcome": "skipped",
             "reason": "no unsigned players on any roster — nothing to compare"},
        ])
        rep = A.Report()
        A.audit_test_log(log, rep, expect_tests=True)
        text = rep.render()
        assert rep.confirmed == 1, text
        assert "test_contracts.py::test_big" in text and "contracts file" in text, text
        assert "skipped as expected" in text and "unsigned" in text, text


def test_failures_are_named():
    import audit_weekly as A

    with tempfile.TemporaryDirectory() as d:
        log = _results(Path(d), [
            {"test": "tests/test_a.py::test_x", "outcome": "failed", "reason": ""},
            {"test": "tests/test_a.py::test_y", "outcome": "error", "reason": ""},
        ])
        rep = A.Report()
        A.audit_test_log(log, rep, expect_tests=True)
        text = rep.render()
        assert "2 failing test(s)" in text and "test_x" in text and "test_y" in text, text


def test_no_results_is_a_flag_when_the_suite_should_have_run():
    import audit_weekly as A

    with tempfile.TemporaryDirectory() as d:
        rep = A.Report()
        A.audit_test_log(Path(d) / "pytest.log", rep, expect_tests=True)
        assert rep.confirmed == 1, rep.render()
        # An incomplete record (the suite died) is no record; a log with no
        # summary line is a crash, not a pass.
        log = _results(Path(d), [], complete=False)
        log.write_text("tests/test_a.py::test_x PASSED  [ 50%]\nKilled\n")
        rep = A.Report()
        A.audit_test_log(log, rep, expect_tests=True)
        assert rep.confirmed == 1 and "no final pytest summary" in rep.render(), rep.render()
        # The unit-test callers pass bare log dirs: silence there, as before.
        rep = A.Report()
        A.audit_test_log(Path(d) / "nothing.log", rep)
        assert rep.confirmed == 0


def test_the_console_log_fallback_still_counts_failures():
    import audit_weekly as A

    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "pytest.log"
        log.write_text(
            "tests/test_a.py::test_x FAILED                                  [ 50%]\n"
            "tests/test_a.py::test_y PASSED                                  [100%]\n"
            "==================== 1 failed, 1 passed, 8 warnings in 3.21s ====================\n")
        rep = A.Report()
        A.audit_test_log(log, rep, expect_tests=True)
        text = rep.render()
        assert "1 failing test(s)" in text and "tests/test_a.py::test_x" in text, text


def test_warnings_from_our_code_are_flagged_and_third_party_ones_are_not():
    import audit_weekly as A

    with tempfile.TemporaryDirectory() as d:
        raw = Path(d)
        (raw / "runner.log").write_text(
            "/home/runner/work/LOTG-Stats/LOTG-Stats/src/lotg.py:1854: Pandas4Warning: "
            "In a future version, the keys of `groups` will be a tuple\n"
            "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/"
            "_pytest/python.py:171: PytestReturnNotNoneWarning: returned bool\n")
        rep = A.Report()
        A.audit_code_warnings(raw, rep)
        text = rep.render()
        assert rep.confirmed == 1 and "src/lotg.py:1854" in text, text
        assert "_pytest" not in text, text


def test_the_email_shows_the_suite_every_week():
    import send_audit_email as E

    tests = {"summary": "440 passed, 1 skipped", "counts": {"passed": 440, "skipped": 1},
             "tests": [("tests/test_forecast.py::test_an_unsigned_player_cannot_score",
                        "SKIPPED", "no unsigned players on any roster — nothing to compare")]}
    _, html, _ = E.render_email(flags=[], gaps={}, captures_present=True, tests=tests)
    assert "Test suite" in html and "440 passed" in html and "unsigned" in html, html
    _, html, _ = E.render_email(flags=[], gaps={}, captures_present=True, tests=None)
    assert "No test results were read" in html, html


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
