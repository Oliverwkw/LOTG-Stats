"""Phase 14: weekly dataset-health email (send_audit_email.py) tests.

Covers recipient selection, the clean-week vs issues-week email rendering
(subject, banner, breakage + injury sections), and that a clean week with
--skip-clean and no creds is a safe no-op. No SMTP is exercised.

Run: PYTHONPATH=src:lib python tests/test_send_audit_email.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import send_audit_email as E  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_recipients():
    ok = _ok("audit_recipients used when present",
             E._audit_recipients({"audit_recipients": ["m@x.com"], "recipients": ["a@x.com"]}) == ["m@x.com"])
    ok &= _ok("falls back to test_recipients",
              E._audit_recipients({"test_recipients": ["t@x.com"]}) == ["t@x.com"])
    ok &= _ok("falls back to recipients",
              E._audit_recipients({"recipients": ["a@x.com", "b@x.com"]}) == ["a@x.com", "b@x.com"])
    return ok


def check_clean_email():
    subject, html, issues = E.render_email(flags=[], gaps={}, captures_present=True)
    ok = _ok("clean subject says all clear", "all clear" in subject and subject.startswith("✅"))
    ok &= _ok("no issues flagged", issues is False)
    ok &= _ok("breakage section clean", "No dataset breakages" in html)
    ok &= _ok("injury section clean", "has an injury capture" in html)
    return ok


def check_detail_lines_not_silently_cut():
    """The audit budgets its own detail lines and says when it truncates. The
    email must not re-cut them at a smaller blind limit — that used to drop the
    columns-that-moved roll-up and every 'added' line off a busy finding."""
    n = E._MAX_DETAIL_LINES
    flags = [{"section": "Part 1 — unexpected diffs", "text": "player_week: 20 changed",
              "details": [f"changed: row {i} — Injury?: False → True" for i in range(n)]}]
    _, html, _ = E.render_email(flags=flags, gaps={}, captures_present=True)
    ok = _ok("keeps the audit's full detail budget",
             all(f"row {i} " in html for i in range(n)), f"limit={n}")
    ok &= _ok("no truncation notice when nothing is cut", "more line(s)" not in html)

    flags[0]["details"] += ["changed: row OVERFLOW — Injury?: False → True"] * 3
    _, html2, _ = E.render_email(flags=flags, gaps={}, captures_present=True)
    ok &= _ok("overflow is stated, not silent", "… and 3 more line(s)" in html2)
    return ok


def check_issues_email():
    flags = [{"section": "Part 1 — unexpected diffs", "text": "team_year: 1 changed past-season row",
              "details": ["changed: Team=A | Year=2024 — PF: 100 → 999"]}]
    gaps = {2026: [2, 3]}
    subject, html, issues = E.render_email(flags=flags, gaps=gaps, captures_present=True)
    ok = _ok("issues subject warns", subject.startswith("⚠️") and "breakage" in subject)
    ok &= _ok("subject counts missed weeks", "2 missed injury weeks" in subject, f"got {subject}")
    ok &= _ok("has_issues True", issues is True)
    ok &= _ok("breakage text rendered", "team_year: 1 changed past-season row" in html)
    ok &= _ok("breakage detail rendered with the moved column",
              "Year=2024 — PF: 100 → 999" in html)
    ok &= _ok("injury gap weeks rendered", "weeks 2, 3" in html)
    return ok


def check_empty_tracker_note():
    _, html, _ = E.render_email(flags=[], gaps={}, captures_present=False)
    return _ok("offseason tracker note shown", "no captures yet" in html)


def check_skip_clean_no_creds_is_noop():
    for k in ("SMTP_USERNAME", "SMTP_PASSWORD", "DIGEST_KEY"):
        os.environ.pop(k, None)
    # Real exports, no baseline, no creds, --skip-clean: must exit 0 without sending.
    rc = E.main(["--exports", str(_ROOT / "exports"), "--skip-clean"])
    return _ok("clean + skip-clean + no creds → exit 0", rc == 0, f"rc={rc}")


def run_all() -> bool:
    all_ok = True
    for t in (check_recipients, check_clean_email, check_issues_email,
              check_detail_lines_not_silently_cut,
              check_empty_tracker_note, check_skip_clean_no_creds_is_noop):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_send_audit_email():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
