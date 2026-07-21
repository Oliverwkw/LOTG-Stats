"""Phase 14 (Phase 12 #41): injury-tracker coverage report tests.

Covers status classification (injury / suspension / bye / healthy), per-week
capture summary, played-but-uncaptured week-gap detection (only for tracker-active
seasons), the player_week build cross-check, and the empty-tracker offseason path.

Run: PYTHONPATH=src:lib python tests/test_injury_coverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import injury_coverage as C  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_classify():
    ok = _ok("Out → injury", C._classify("Out", "Active") == "injury")
    ok &= _ok("Questionable → injury", C._classify("Questionable", "") == "injury")
    ok &= _ok("Suspended → suspension", C._classify("", "Suspended") == "suspension")
    ok &= _ok("empty → healthy", C._classify("", "") == "healthy")
    ok &= _ok("Active only → healthy", C._classify("", "Active") == "healthy")
    return ok


def _rows():
    return [
        {"season": "2026", "week": "1", "player_id": "100", "position": "RB",
         "injury_status": "Out", "status": "Active", "on_bye": "false", "captured_at_utc": "t1"},
        {"season": "2026", "week": "1", "player_id": "101", "position": "WR",
         "injury_status": "", "status": "Active", "on_bye": "true", "captured_at_utc": "t1"},
        {"season": "2026", "week": "1", "player_id": "102", "position": "TE",
         "injury_status": "", "status": "Suspended", "on_bye": "false", "captured_at_utc": "t1"},
    ]


def check_capture_summary():
    s = C.capture_summary(_rows())
    v = s.get((2026, 1))
    ok = _ok("one week summarised", v is not None and v["players"] == 3)
    ok &= _ok("injury/suspension/bye counted",
              v["injury"] == 1 and v["suspension"] == 1 and v["bye_true"] == 1, f"got {v}")
    return ok


def check_week_gaps():
    summary = C.capture_summary(_rows())               # captured: 2026 wk1
    played = {2025: {1, 2}, 2026: {1, 2, 3}}           # 2025 is pre-tracker
    gaps = C.week_gaps(summary, played)
    ok = _ok("2026 weeks 2,3 flagged as gaps", gaps.get(2026) == [2, 3], f"got {gaps}")
    ok &= _ok("pre-tracker 2025 NOT flagged", 2025 not in gaps, f"got {gaps}")
    return ok


def check_build_flag_counts():
    pw = pd.DataFrame({
        "Player": ["A", "B", "C"], "Year": [2026, 2026, 2026], "Week": [1, 1, 1],
        "Injury?": ["True", "False", "False"], "Suspension?": ["False", "True", "False"],
        "Bye?": ["False", "False", "True"]})
    f = C.build_flag_counts(pw).get((2026, 1))
    return _ok("build flags counted", f == {"injury": 1, "suspension": 1, "bye": 1}, f"got {f}")


def check_empty_report():
    md, one = C.render_report([], {}, {}, {})
    ok = _ok("empty tracker → 'no captures yet'", "No captures yet" in md)
    ok &= _ok("summary line reflects empty", "tracker empty" in one)
    return ok


def check_populated_report():
    summary = C.capture_summary(_rows())
    gaps = {2026: [2]}
    flags = {(2026, 1): {"injury": 1, "suspension": 1, "bye": 1}}
    md, one = C.render_report(_rows(), summary, gaps, flags)
    ok = _ok("gap surfaced in report", "weeks 2" in md and "no tracker capture" in md)
    ok &= _ok("capture-health table present", "Capture health by week" in md and "| 2026 | 1 |" in md)
    ok &= _ok("one-line counts gaps", "1 played-week gap" in one, f"got {one}")
    return ok


def check_real_smoke():
    # Against the real repo: tracker is empty in the offseason → clean no-op path.
    captures = C.load_captures(_ROOT)
    summary = C.capture_summary(captures)
    md, one = C.render_report(captures, summary, {}, {})
    return _ok("real tracker report renders", isinstance(md, str) and len(md) > 0, one)


def run_all() -> bool:
    tests = [check_classify, check_capture_summary, check_week_gaps,
             check_build_flag_counts, check_empty_report, check_populated_report,
             check_real_smoke]
    all_ok = True
    for t in tests:
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_injury_coverage():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
