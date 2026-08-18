"""Phase 14: weekly dataset-health email (send_audit_email.py) tests.

Covers recipient selection, the clean-week vs issues-week email rendering
(subject, banner, breakage + injury sections, and the lede on a week with
findings), and that a clean week with --skip-clean and no creds is a safe no-op.
No SMTP is exercised, and no lede test reaches the network — ANTHROPIC_API_KEY is
unset in these runs, so every one exercises the counted path.

Run: PYTHONPATH=src:lib python tests/test_send_audit_email.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
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
    ok &= _ok("breakage section clean", "Nothing unaccounted for" in html)
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


def check_nflverse_section():
    """"NFLverse made N changes" is its own informational section — upstream
    back-correcting a completed season is not a dataset breakage."""
    sys.path.insert(0, str(_ROOT / "lib"))
    from lotg_support import nflverse_drift as N

    drift = N.Drift(compared=True)
    drift.files.append(N.FileDrift(
        name="nflverse_stats_player_week_2025.csv", changed_cells=2306,
        changed_rows=1850, top_columns=[("position", 1169), ("fumble_recovery_yards_own", 296)]))
    subject, html, issues = E.render_email(flags=[], gaps={}, captures_present=True,
                                           drift=drift, attributed=32, attributed_cells=57)
    ok = _ok("drift alone is NOT an issue week", issues is False)
    ok &= _ok("subject still says all clear", "all clear" in subject, subject)

    # A week whose entire story is "upstream revised data and our exports
    # followed" IS one line. Not a shorter section list — one line, one bullet,
    # nothing but the title beside it.
    ok &= _ok("says exactly the one sentence",
              "NFLverse changed 2306 values, which in turn changed 57 cells" in html, html)
    text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    expect = (f"LOTG dataset health — {date.today().isoformat()} "
              "NFLverse changed 2306 values, which in turn changed 57 cells")
    ok &= _ok("and nothing else besides the title", text == expect, repr(text))
    ok &= _ok("exactly one bullet", html.count("<li") == 1, html)
    for gone in ("Dataset breakages", "NFLverse changes", "Missed injuries",
                 "All clear this week", "Automated weekly dataset-health check",
                 "position (1169)"):
        ok &= _ok(f"no {gone!r} heading//note", gone not in html)

    # A quiet upstream week is the same shape — there is even less to say.
    _, clean, _ = E.render_email(flags=[], gaps={}, captures_present=True,
                                 drift=N.Drift(compared=True), attributed=0)
    ok &= _ok("a quiet upstream week is the same one line",
              "NFLverse changed 0 values, which in turn changed 0 cells" in clean, clean)

    # The moment anything is flagged the full layout returns, including the
    # breakdown the breakage has to be read against.
    flags = [{"section": "Part 1", "text": "player_year: 1 changed", "details": []}]
    _, busy, _ = E.render_email(flags=flags, gaps={}, captures_present=True,
                                drift=drift, attributed=32,
                                attributed_sheets={"player_year": 32})
    ok &= _ok("a flagged week keeps the sections",
              "Dataset breakages" in busy and "Missed injuries" in busy)
    ok &= _ok("and the breakdown to read it against",
              "position (1169)" in busy and "our rows it explains" in busy, busy[:900])
    ok &= _ok("with the upstream summary spelled out",
              "NFLverse made 2306 value(s) across 1850 row(s)" in busy)

    # A missed injury week is also something to look at, so it un-collapses.
    _, gappy, _ = E.render_email(flags=[], gaps={2026: [3]}, captures_present=True,
                                 drift=drift, attributed=32)
    ok &= _ok("a missed injury week keeps the full layout",
              "Missed injuries" in gappy and "weeks 3" in gappy)

    _, none_html, _ = E.render_email(flags=[], gaps={}, captures_present=True)
    ok &= _ok("no snapshot -> says it wasn't measured",
              "not measured" in none_html, none_html[:400])
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


# ---------------------------------------------------------------------------
# The lede
# ---------------------------------------------------------------------------
def check_lede_only_on_a_week_with_findings():
    """A clean week's email is already one sentence long; summarising it would
    be noise. A week with findings is a wall, which is what the lede is for."""
    flags = [{"section": "Part 1 — unexpected diffs",
              "text": "team_year: 1 changed past-season row",
              "details": ["changed: Team=A | Year=2024 — PF: 100 → 999"]}]
    _, issues_html, _ = E.render_email(flags=flags, gaps={2026: [2, 3]},
                                       captures_present=True)
    _, clean_html, _ = E.render_email(flags=[], gaps={}, captures_present=True)
    lede = "1 finding across 1 audit section and 2 missed injury weeks."
    ok = _ok("a week with findings gets a lede", lede in issues_html, issues_html[:400])
    ok &= _ok("above the first section",
              issues_html.index(lede) < issues_html.index("Dataset breakages"))
    ok &= _ok("a clean week gets none", "audit section" not in clean_html)
    return ok


def check_counted_lede_content():
    """What actually ships until an ANTHROPIC_API_KEY secret exists."""
    two = [{"section": "Part 1 — unexpected diffs", "text": "team_year moved", "details": []},
           {"section": "Part 2 — schema", "text": "picks lost a column", "details": []}]
    ok = _ok("counts findings and sections",
             E._counted_lede(two, {}) == "2 findings across 2 audit sections.",
             E._counted_lede(two, {}))
    ok &= _ok("singular reads correctly",
              E._counted_lede(two[:1], {}) == "1 finding across 1 audit section.",
              E._counted_lede(two[:1], {}))
    ok &= _ok("injury gaps are carried",
              "and 3 missed injury weeks." in E._counted_lede(two, {2026: [1, 2], 2025: [7]}),
              E._counted_lede(two, {2026: [1, 2], 2025: [7]}))
    ok &= _ok("gaps alone still summarise",
              E._counted_lede([], {2026: [4]}) == "1 missed injury week.",
              E._counted_lede([], {2026: [4]}))
    ok &= _ok("nothing to say -> nothing said", E._counted_lede([], {}) == "")
    return ok


def check_lede_material_is_the_audit_own_lines():
    """The model is handed the audit's rendered findings and nothing else — no
    frames, no raw values it would have to interpret."""
    flags = [{"section": "Part 1", "text": "team_year: 1 changed past-season row",
              "details": ["- changed: Team=A | Year=2024 — PF: 100 → 999"]}]
    secs = E._lede_sections(flags, {2026: [2]}, None, 0)
    titles = [t for t, _v, _i in secs]
    lines = [i.sentence() for _t, _v, items in secs for i in items]
    ok = _ok("no empty sections", titles == ["Dataset breakages", "Missed injuries"], titles)
    ok &= _ok("carries the finding", any("team_year: 1 changed" in l for l in lines))
    ok &= _ok("carries its detail", any("PF: 100 → 999" in l for l in lines))
    ok &= _ok("strips the markdown bullet", not any(l.strip().startswith("- ") for l in lines))
    ok &= _ok("names the missed weeks", any("2026: weeks 2" in l for l in lines))
    return ok


def check_lede_cannot_stop_the_email():
    """The point of the whole design: the lede is a nicety on top of an email
    that has to go out. Anything that goes wrong writing it costs the lede and
    nothing else."""
    import lotg_support.email_summary as ES
    flags = [{"section": "Part 1", "text": "team_year moved", "details": []}]

    def _boom(*a, **k):
        raise RuntimeError("summariser exploded")

    prev = ES.ai_summary
    ES.ai_summary = _boom
    try:
        subject, html, issues = E.render_email(flags=flags, gaps={}, captures_present=True)
    finally:
        ES.ai_summary = prev
    ok = _ok("the email still renders", bool(html) and issues is True)
    ok &= _ok("with its subject intact", subject.startswith("⚠️"), subject)
    ok &= _ok("and its findings intact", "team_year moved" in html)
    ok &= _ok("just without a lede", "audit section" not in html)
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_recipients, check_clean_email, check_issues_email,
              check_detail_lines_not_silently_cut, check_nflverse_section,
              check_empty_tracker_note, check_skip_clean_no_creds_is_noop,
              check_lede_only_on_a_week_with_findings, check_counted_lede_content,
              check_lede_material_is_the_audit_own_lines,
              check_lede_cannot_stop_the_email):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_send_audit_email():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
